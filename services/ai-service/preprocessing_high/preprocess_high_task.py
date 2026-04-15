from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from preprocessing_high.diagnostics import build_schema_resolution_diagnostics
from preprocessing_high.error_handler import (
    PreprocessHighInputError,
    PreprocessHighMissingColumnError,
    classify_preprocess_high_error,
    decide_preprocess_high_action,
)
from preprocessing_high.llm_client import (
    build_deterministic_schema_validation_result,
    correct_query_terms,
    validate_query_schema_usage,
)
from preprocessing_high.schema_loader import load_user_schema
from preprocessing_high.schemas import (
    HighPreprocessConfig,
    PreprocessHighResult,
    build_preprocess_high_failed_result,
    build_preprocess_high_rejected_result,
    build_preprocess_high_success_result,
)
from shared.pipeline_trace import make_attempt


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_logger() -> logging.Logger:
    return logging.getLogger(__name__)


def _log_event(logger: logging.Logger, level: int, message: str, **fields: object) -> None:
    payload = {"timestamp": _utc_now(), **fields}
    logger.log(level, "%s | %s", message, json.dumps(payload, sort_keys=True, default=str))


def _validate_inputs(cleaned_text: str, user_id: str) -> tuple[str, str]:
    normalized_text = str(cleaned_text or "").strip()
    if not normalized_text:
        raise PreprocessHighInputError("cleaned_text is empty.")

    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        raise PreprocessHighInputError("user_id is empty.")

    return normalized_text, normalized_user_id


def run_preprocess_high(cleaned_text: str, user_id: str) -> PreprocessHighResult:
    """
    Shared runtime function so this module can be reused by Dagster assets and direct callers.
    """
    logger = _get_logger()
    config = HighPreprocessConfig.from_env()
    retry_count = 0
    final_query = ""
    loaded_schema = None
    validation_result = None
    diagnostics: dict[str, object] = {}
    attempts: list[dict[str, object]] = []
    stage_started_at = _utc_now()
    stage_started_perf = time.perf_counter()

    while True:
        try:
            attempt_started_perf = time.perf_counter()
            normalized_text, normalized_user_id = _validate_inputs(cleaned_text, user_id)
            loaded_schema = load_user_schema(
                user_id=normalized_user_id,
                config=config,
                logger=logger,
                log_event=_log_event,
            )

            final_query = correct_query_terms(
                query=normalized_text,
                loaded_schema=loaded_schema,
                config=config,
                logger=logger,
                log_event=_log_event,
            )

            validation_result = validate_query_schema_usage(
                corrected_query=final_query,
                loaded_schema=loaded_schema,
                config=config,
                logger=logger,
                log_event=_log_event,
            )

            diagnostics = build_schema_resolution_diagnostics(
                original_query=normalized_text,
                corrected_query=final_query,
                loaded_schema=loaded_schema,
                validation_result=validation_result,
            )

            schema_validation_status = str(diagnostics.get("schema_validation_status", "unknown")).strip().lower()
            has_schema_validation_issue = schema_validation_status != "valid" or not bool(
                validation_result.get("is_valid", False)
            )

            if has_schema_validation_issue:
                unresolved_terms = [str(term) for term in diagnostics.get("unresolved_terms", []) if str(term)]
                unsupported_terms = [str(term) for term in diagnostics.get("unsupported_terms", []) if str(term)]
                missing_column = str(validation_result.get("missing_column") or "").strip() or "unknown"
                if missing_column == "unknown" and unresolved_terms:
                    missing_column = unresolved_terms[0]

                if unresolved_terms:
                    message = (
                        "Schema validation failed because the query contains unresolved terms: "
                        f"{', '.join(unresolved_terms)}."
                    )
                    recommended_fix = (
                        "Use only existing schema columns (region, city, total_population, "
                        "male_population, female_population, avg_age, employment_rate)."
                    )
                elif unsupported_terms:
                    message = (
                        "Schema validation failed because the query uses unsupported time concepts: "
                        f"{', '.join(unsupported_terms)}."
                    )
                    recommended_fix = (
                        "Remove time-based grouping/filtering or add a Date/DateTime column to the dataset."
                    )
                else:
                    message = "Schema validation failed due to invalid schema references."
                    recommended_fix = "Use existing table/column names from the current dataset schema."

                attempts.append(
                    make_attempt(
                        attempt_number=len(attempts) + 1,
                        input_payload={"query": normalized_text, "user_id": normalized_user_id},
                        output_payload={
                            "final_query": final_query,
                            "validation_result": validation_result,
                            "diagnostics": diagnostics,
                        },
                        success=False,
                        retry_triggered=False,
                        model_or_method_used=f"schema_loader+ollama:{config.ollama_model}",
                        duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                        validation_result={"is_valid": False, "missing_column": missing_column},
                        error_type="business",
                        error_message=message,
                    )
                )
                rejected_payload = build_preprocess_high_rejected_result(
                    final_query=final_query,
                    missing_column=missing_column,
                    message=message,
                    schema_used=loaded_schema.schema,
                    mappings=validation_result.get("mappings", []),
                    derivable_columns=validation_result.get("derivable_columns", []),
                    invalid_mappings=validation_result.get("invalid_mappings", []),
                )
                rejected_payload.update(diagnostics)
                rejected_payload["root_cause_detail"] = message
                rejected_payload["analyst_recommended_fix"] = recommended_fix
                rejected_payload["attempts"] = attempts
                rejected_payload["attempts_count"] = len(attempts)
                rejected_payload["warnings"] = [
                    {
                        "type": "schema_validation_rejected",
                        "message": message,
                    }
                ]
                rejected_payload["errors"] = [
                    {
                        "type": "business",
                        "message": message,
                    }
                ]
                rejected_payload["started_at"] = stage_started_at
                rejected_payload["finished_at"] = _utc_now()
                rejected_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
                rejected_payload["debug_metadata"] = {
                    "user_id": normalized_user_id,
                    "schema_tables": len(loaded_schema.schema.get("tables", [])),
                }
                return rejected_payload

            _log_event(
                logger,
                logging.INFO,
                "High preprocessing completed successfully",
                user_id=normalized_user_id,
                schema_valid=True,
                final_query_preview=final_query[:200],
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"query": normalized_text, "user_id": normalized_user_id},
                    output_payload={
                        "final_query": final_query,
                        "validation_result": validation_result,
                        "diagnostics": diagnostics,
                    },
                    success=True,
                    retry_triggered=False,
                    model_or_method_used=f"schema_loader+ollama:{config.ollama_model}",
                    duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                    validation_result={"is_valid": True},
                )
            )
            success_payload = build_preprocess_high_success_result(
                final_query=final_query,
                schema_used=loaded_schema.schema,
                mappings=validation_result.get("mappings", []),
                derivable_columns=validation_result.get("derivable_columns", []),
                invalid_mappings=validation_result.get("invalid_mappings", []),
            )
            success_payload.update(diagnostics)
            success_payload["attempts"] = attempts
            success_payload["attempts_count"] = len(attempts)
            success_payload["warnings"] = []
            success_payload["errors"] = []
            success_payload["started_at"] = stage_started_at
            success_payload["finished_at"] = _utc_now()
            success_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            success_payload["debug_metadata"] = {
                "user_id": normalized_user_id,
                "schema_tables": len(loaded_schema.schema.get("tables", [])),
            }
            return success_payload
        except PreprocessHighMissingColumnError as exc:
            _log_event(
                logger,
                logging.WARNING,
                "High preprocessing rejected due to missing column",
                missing_column=exc.missing_column,
                final_query_preview=final_query[:200],
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"query": cleaned_text, "user_id": user_id},
                    output_payload={},
                    success=False,
                    retry_triggered=False,
                    model_or_method_used=f"schema_loader+ollama:{config.ollama_model}",
                    duration_ms=0,
                    validation_result={"is_valid": False, "missing_column": exc.missing_column},
                    error_type="business",
                    error_message=str(exc),
                )
            )
            rejected_payload = build_preprocess_high_rejected_result(
                final_query=final_query,
                missing_column=exc.missing_column,
                schema_used=(loaded_schema.schema if loaded_schema else None),
                mappings=(validation_result.get("mappings", []) if validation_result else None),
                derivable_columns=(
                    validation_result.get("derivable_columns", [])
                    if validation_result
                    else None
                ),
                invalid_mappings=(
                    validation_result.get("invalid_mappings", [])
                    if validation_result
                    else None
                ),
            )
            rejected_payload["attempts"] = attempts
            rejected_payload["attempts_count"] = len(attempts)
            rejected_payload["warnings"] = []
            rejected_payload["errors"] = [{"type": "business", "message": str(exc)}]
            rejected_payload["started_at"] = stage_started_at
            rejected_payload["finished_at"] = _utc_now()
            rejected_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            rejected_payload["debug_metadata"] = {}
            return rejected_payload
        except Exception as exc:  # noqa: BLE001
            error_type = classify_preprocess_high_error(exc)
            action_taken = decide_preprocess_high_action(
                error_type=error_type,
                retry_count=retry_count,
                config=config,
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"query": cleaned_text, "user_id": user_id},
                    output_payload={},
                    success=False,
                    retry_triggered=action_taken == "retry",
                    retry_reason=str(exc) if action_taken == "retry" else "",
                    model_or_method_used=f"schema_loader+ollama:{config.ollama_model}",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type=error_type,
                    error_message=str(exc),
                )
            )

            _log_event(
                logger,
                logging.ERROR,
                "High preprocessing failed",
                error_type=error_type,
                action_taken=action_taken,
                retry_count=retry_count,
                final_query_preview=final_query[:200],
                error=str(exc),
            )

            if action_taken == "retry":
                retry_count += 1
                continue

            if error_type in {"llm", "system", "unknown"} and loaded_schema is not None:
                fallback_query = final_query or str(cleaned_text or "").strip()
                fallback_validation_result = build_deterministic_schema_validation_result(
                    corrected_query=fallback_query,
                    loaded_schema=loaded_schema,
                )
                fallback_diagnostics = build_schema_resolution_diagnostics(
                    original_query=str(cleaned_text or "").strip(),
                    corrected_query=fallback_query,
                    loaded_schema=loaded_schema,
                    validation_result=fallback_validation_result,
                )
                fallback_schema_status = str(
                    fallback_diagnostics.get("schema_validation_status", "unknown")
                ).strip().lower()
                fallback_is_valid = bool(fallback_validation_result.get("is_valid", False))
                fallback_success = fallback_is_valid and fallback_schema_status == "valid"
                attempts.append(
                    make_attempt(
                        attempt_number=len(attempts) + 1,
                        input_payload={"query": cleaned_text, "user_id": user_id},
                        output_payload={
                            "final_query": fallback_query,
                            "validation_result": fallback_validation_result,
                            "diagnostics": fallback_diagnostics,
                        },
                        success=fallback_success,
                        retry_triggered=False,
                        model_or_method_used="deterministic_schema_fallback",
                        duration_ms=0,
                        validation_result={
                            "is_valid": fallback_success,
                            "schema_validation_status": fallback_schema_status,
                        },
                        error_type="" if fallback_success else "business",
                        error_message="" if fallback_success else str(exc),
                    )
                )

                if fallback_success:
                    success_payload = build_preprocess_high_success_result(
                        final_query=fallback_query,
                        schema_used=loaded_schema.schema,
                        mappings=fallback_validation_result.get("mappings", []),
                        derivable_columns=fallback_validation_result.get("derivable_columns", []),
                        invalid_mappings=fallback_validation_result.get("invalid_mappings", []),
                    )
                    success_payload.update(fallback_diagnostics)
                    success_payload["attempts"] = attempts
                    success_payload["attempts_count"] = len(attempts)
                    success_payload["warnings"] = [
                        {
                            "type": "schema_validation_llm_fallback",
                            "message": (
                                "LLM schema correction/validation failed; deterministic "
                                "schema fallback was used."
                            ),
                        }
                    ]
                    success_payload["errors"] = []
                    success_payload["started_at"] = stage_started_at
                    success_payload["finished_at"] = _utc_now()
                    success_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
                    success_payload["debug_metadata"] = {
                        "retry_count": retry_count,
                        "action_taken": action_taken,
                        "llm_fallback_used": True,
                        "llm_fallback_error_type": error_type,
                        "llm_fallback_error": str(exc),
                        "schema_tables": len(loaded_schema.schema.get("tables", [])),
                    }
                    _log_event(
                        logger,
                        logging.WARNING,
                        "High preprocessing fallback activated",
                        fallback_mode="deterministic_schema_validation",
                        final_query_preview=fallback_query[:200],
                    )
                    return success_payload

                unresolved_terms = [
                    str(term) for term in fallback_diagnostics.get("unresolved_terms", []) if str(term)
                ]
                unsupported_terms = [
                    str(term) for term in fallback_diagnostics.get("unsupported_terms", []) if str(term)
                ]
                missing_column = str(fallback_validation_result.get("missing_column") or "").strip() or "unknown"
                if missing_column == "unknown" and unresolved_terms:
                    missing_column = unresolved_terms[0]
                if unresolved_terms:
                    fallback_message = (
                        "Schema validation failed because the query contains unresolved terms: "
                        f"{', '.join(unresolved_terms)}."
                    )
                elif unsupported_terms:
                    fallback_message = (
                        "Schema validation failed because the query uses unsupported time concepts: "
                        f"{', '.join(unsupported_terms)}."
                    )
                else:
                    fallback_message = "Schema validation failed due to invalid schema references."

                rejected_payload = build_preprocess_high_rejected_result(
                    final_query=fallback_query,
                    missing_column=missing_column,
                    message=fallback_message,
                    schema_used=loaded_schema.schema,
                    mappings=fallback_validation_result.get("mappings", []),
                    derivable_columns=fallback_validation_result.get("derivable_columns", []),
                    invalid_mappings=fallback_validation_result.get("invalid_mappings", []),
                )
                rejected_payload.update(fallback_diagnostics)
                rejected_payload["attempts"] = attempts
                rejected_payload["attempts_count"] = len(attempts)
                rejected_payload["warnings"] = [
                    {
                        "type": "schema_validation_llm_fallback_rejected",
                        "message": (
                            "LLM schema correction/validation failed and deterministic "
                            "fallback also found invalid schema references."
                        ),
                    }
                ]
                rejected_payload["errors"] = [{"type": "business", "message": fallback_message}]
                rejected_payload["started_at"] = stage_started_at
                rejected_payload["finished_at"] = _utc_now()
                rejected_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
                rejected_payload["debug_metadata"] = {
                    "retry_count": retry_count,
                    "action_taken": action_taken,
                    "llm_fallback_used": True,
                    "llm_fallback_error_type": error_type,
                    "llm_fallback_error": str(exc),
                }
                return rejected_payload

            failed_payload = build_preprocess_high_failed_result(
                error_type=error_type,
                action_taken=action_taken,
                final_query=final_query,
                schema_used=(loaded_schema.schema if loaded_schema else None),
                mappings=(validation_result.get("mappings", []) if validation_result else None),
                derivable_columns=(
                    validation_result.get("derivable_columns", [])
                    if validation_result
                    else None
                ),
                invalid_mappings=(
                    validation_result.get("invalid_mappings", [])
                    if validation_result
                    else None
                ),
            )
            if diagnostics:
                failed_payload.update(diagnostics)
            failed_payload["attempts"] = attempts
            failed_payload["attempts_count"] = len(attempts)
            failed_payload["warnings"] = []
            failed_payload["errors"] = [{"type": error_type, "message": str(exc)}]
            failed_payload["started_at"] = stage_started_at
            failed_payload["finished_at"] = _utc_now()
            failed_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            failed_payload["debug_metadata"] = {
                "retry_count": retry_count,
                "action_taken": action_taken,
            }
            return failed_payload


def _attach_fn_compat(func):
    """
    Keep compatibility for existing call sites/tests that use Prefect's `.fn`.
    """
    setattr(func, "fn", func)
    return func


@_attach_fn_compat
def preprocess_high_task(cleaned_text: str, user_id: str) -> dict:
    return run_preprocess_high(cleaned_text=cleaned_text, user_id=user_id)
