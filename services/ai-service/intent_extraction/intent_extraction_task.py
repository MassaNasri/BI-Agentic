from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from intent_extraction.error_handler import (
    IntentExtractionInputError,
    classify_intent_extraction_error,
    decide_intent_extraction_action,
)
from intent_extraction.llm_extractor import extract_structured_intent, infer_intent_type
from intent_extraction.predictive_parser import parse_predictive_intent
from intent_extraction.routing import route_intent
from intent_extraction.schemas import (
    IntentExtractionConfig,
    IntentExtractionTaskResult,
    NextStepType,
    build_intent_extraction_failed_result,
    build_intent_extraction_success_result,
)
from intent_extraction.validation import validate_structured_intent
from shared.query_planner import normalize_analytical_intent
from shared.confidence import stage_confidence
from shared.pipeline_trace import make_attempt
from shared.stage_contract import stage_allows_progress


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_logger() -> logging.Logger:
    return logging.getLogger(__name__)


def _log_event(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    payload = {"timestamp": _utc_now(), **fields}
    logger.log(level, "%s | %s", message, json.dumps(payload, sort_keys=True, default=str))


def _validate_inputs(query: str, schema: dict[str, list[dict[str, Any]]]) -> tuple[str, dict[str, list[dict[str, Any]]]]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise IntentExtractionInputError("query is empty.")

    if not isinstance(schema, dict):
        raise IntentExtractionInputError("schema must be a dictionary.")
    if not schema:
        raise IntentExtractionInputError("schema is empty.")

    return normalized_query, schema


def _next_step_for_intent_type(intent_type: str) -> NextStepType:
    return "forecasting" if intent_type == "predictive" else "metabase"


def _extract_and_validate(
    *,
    query: str,
    schema: dict[str, list[dict[str, Any]]],
    config: IntentExtractionConfig,
    logger: logging.Logger,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    _log_event(
        logger,
        logging.INFO,
        "Intent extraction started",
        input_query=query,
        schema_table_count=len(schema),
    )

    extracted_result = extract_structured_intent(
        query=query,
        schema=schema,
        config=config,
        logger=logger,
        log_event=_log_event,
        include_debug=True,
    )
    if isinstance(extracted_result, tuple):
        extracted_intent, llm_debug = extracted_result
    else:
        extracted_intent = extracted_result
        llm_debug = {}
    _log_event(
        logger,
        logging.INFO,
        "Intent extracted from LLM",
        extracted_intent=extracted_intent,
    )

    validated_intent = validate_structured_intent(
        intent=extracted_intent,
        schema=schema,
    )
    detected_type = validated_intent["intent_type"]
    _log_event(
        logger,
        logging.INFO,
        "Intent type classified",
        detected_type=detected_type,
    )
    return extracted_intent, validated_intent, detected_type, llm_debug


def _fallback_extract_and_validate(
    *,
    query: str,
    schema: dict[str, list[dict[str, Any]]],
    logger: logging.Logger,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    normalized_intent = normalize_analytical_intent(
        question=query,
        raw_intent={},
        schema=schema,
    )
    fallback_metrics = [
        str(metric.get("column", "")).strip()
        for metric in normalized_intent.get("metrics", [])
        if isinstance(metric, dict) and str(metric.get("column", "")).strip()
    ]
    fallback_dimensions = [
        str(dimension).strip()
        for dimension in normalized_intent.get("dimensions", [])
        if str(dimension).strip()
    ]
    fallback_filters = [
        filter_item
        for filter_item in normalized_intent.get("filters", [])
        if isinstance(filter_item, dict)
    ]
    fallback_aggregation = "SUM"
    for metric in normalized_intent.get("metrics", []):
        if isinstance(metric, dict) and str(metric.get("aggregation", "")).strip():
            fallback_aggregation = str(metric.get("aggregation", "")).strip().upper()
            break
    fallback_target_column = fallback_metrics[0] if fallback_metrics else "*"
    inferred_type = infer_intent_type(query=query, hinted_intent_type=None)
    extracted_intent = {
        "intent_type": inferred_type,
        "intent": str(normalized_intent.get("intent", "projection")),
        "metrics": fallback_metrics or ["*"],
        "metric_specs": [
            {
                "column": metric.get("column"),
                "aggregation": metric.get("aggregation"),
                "alias": metric.get("alias"),
            }
            for metric in normalized_intent.get("metrics", [])
            if isinstance(metric, dict) and metric.get("column")
        ],
        "dimensions": fallback_dimensions,
        "filters": fallback_filters,
        "time_range": "all_time",
        "aggregation": fallback_aggregation,
        "target_column": fallback_target_column,
        "table": str(normalized_intent.get("table", "")).strip(),
        "order_by": normalized_intent.get("order_by", []),
        "limit": normalized_intent.get("limit"),
        "ranking": normalized_intent.get("ranking", {}),
        "operations": normalized_intent.get("operations", []),
        "ambiguities": normalized_intent.get("ambiguities", []),
    }
    validated_intent = validate_structured_intent(intent=extracted_intent, schema=schema)
    detected_type = validated_intent["intent_type"]
    _log_event(
        logger,
        logging.WARNING,
        "Intent extraction fallback used",
        extracted_intent=extracted_intent,
        validated_intent=validated_intent,
    )
    return (
        extracted_intent,
        validated_intent,
        detected_type,
        {
            "provider": "deterministic_fallback",
            "fallback_source": "shared.query_planner.normalize_analytical_intent",
            "normalized_intent": normalized_intent,
        },
    )


def run_intent_extraction_stage(query: str, schema: dict, route: str = "analytical") -> dict[str, Any]:
    """
    Stage runtime for:
    1) extracting structured intent
    2) validating against schema
    3) determining predictive vs analytical intent type
    """
    logger = _get_logger()
    config = IntentExtractionConfig.from_env()
    retry_count = 0
    attempts: list[dict[str, Any]] = []
    stage_started_at = _utc_now()
    stage_started_perf = time.perf_counter()
    llm_debug: dict[str, Any] = {}

    normalized_route = str(route or "analytical").strip().lower() or "analytical"

    while True:
        try:
            attempt_started_perf = time.perf_counter()
            normalized_query, normalized_schema = _validate_inputs(query, schema)
            inferred_predictive_type = infer_intent_type(query=normalized_query, hinted_intent_type=None)
            predictive_route_required = (
                normalized_route == "forecasting"
                or inferred_predictive_type == "predictive"
            )
            if predictive_route_required:
                predictive_intent = parse_predictive_intent(query=normalized_query, schema=normalized_schema)
                attempts.append(
                    make_attempt(
                        attempt_number=len(attempts) + 1,
                        input_payload={"query": normalized_query, "schema_tables": list(normalized_schema.keys())},
                        output_payload={
                            "extracted_intent": predictive_intent,
                            "validated_intent": predictive_intent,
                                "intent_type": "predictive",
                                "predictive_route_required": predictive_route_required,
                            },
                            success=True,
                        retry_triggered=False,
                        model_or_method_used="predictive_intent_parser",
                        duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                        validation_result={"is_valid": True},
                    )
                )
                finished_at = _utc_now()
                return {
                    "status": "success",
                    "confidence": 0.9,
                    "intent_type": "predictive",
                    "next_step": "forecasting",
                    "error_type": "none",
                    "action_taken": "proceed",
                    "query": normalized_query,
                    "schema": normalized_schema,
                    "extracted_intent": predictive_intent,
                    "validated_intent": predictive_intent,
                    "attempts": attempts,
                    "attempts_count": len(attempts),
                    "started_at": stage_started_at,
                    "finished_at": finished_at,
                    "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                    "warnings": [],
                    "errors": [],
                    "debug_metadata": {
                        "route": "forecasting",
                        "route_source": (
                            "explicit_route"
                            if normalized_route == "forecasting"
                            else "predictive_inference_guard"
                        ),
                        "predictive_parser": "deterministic_schema_aware",
                    },
                }

            extracted_intent, validated_intent, detected_type, llm_debug = _extract_and_validate(
                query=normalized_query,
                schema=normalized_schema,
                config=config,
                logger=logger,
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"query": normalized_query, "schema_tables": list(normalized_schema.keys())},
                    output_payload={
                        "extracted_intent": extracted_intent,
                        "validated_intent": validated_intent,
                        "intent_type": detected_type,
                    },
                    success=True,
                    retry_triggered=False,
                    model_or_method_used=f"{config.llm_provider}_intent_extractor",
                    duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                    validation_result={"is_valid": True},
                )
            )
            finished_at = _utc_now()
            return {
                "status": "success",
                "confidence": 0.86,
                "intent_type": detected_type,
                "next_step": _next_step_for_intent_type(detected_type),
                "error_type": "none",
                "action_taken": "proceed",
                "query": normalized_query,
                "schema": normalized_schema,
                "extracted_intent": extracted_intent,
                "validated_intent": validated_intent,
                "attempts": attempts,
                "attempts_count": len(attempts),
                "started_at": stage_started_at,
                "finished_at": finished_at,
                "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                "warnings": [],
                "errors": [],
                "debug_metadata": {
                    "llm_provider": config.llm_provider,
                    "route": normalized_route,
                    "llm_prompt": llm_debug.get("prompt"),
                    "llm_raw_output": llm_debug.get("raw_output"),
                    "llm_parsed_payload": llm_debug.get("parsed_payload"),
                },
            }
        except Exception as exc:  # noqa: BLE001
            error_type = classify_intent_extraction_error(exc)
            action_taken = decide_intent_extraction_action(
                error_type=error_type,
                retry_count=retry_count,
                config=config,
            )
            normalized_query_for_fallback = str(query or "").strip()
            normalized_schema_for_fallback = schema if isinstance(schema, dict) else {}

            if (
                action_taken == "stop"
                and error_type in {"system", "model", "unknown"}
                and normalized_query_for_fallback
                and normalized_schema_for_fallback
            ):
                try:
                    attempt_started_perf = time.perf_counter()
                    extracted_intent, validated_intent, detected_type, llm_debug = _fallback_extract_and_validate(
                        query=normalized_query_for_fallback,
                        schema=normalized_schema_for_fallback,
                        logger=logger,
                    )
                    attempts.append(
                        make_attempt(
                            attempt_number=len(attempts) + 1,
                            input_payload={
                                "query": normalized_query_for_fallback,
                                "schema_tables": list(normalized_schema_for_fallback.keys()),
                            },
                            output_payload={
                                "extracted_intent": extracted_intent,
                                "validated_intent": validated_intent,
                                "intent_type": detected_type,
                                "fallback_reason": str(exc),
                            },
                            success=True,
                            retry_triggered=False,
                            model_or_method_used="heuristic_query_planner_fallback",
                            duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                            validation_result={"is_valid": True, "fallback_used": True},
                        )
                    )
                    finished_at = _utc_now()
                    return {
                        "status": "degraded",
                        "degraded": True,
                        "degradation_reason": "intent_extraction_llm_fallback",
                        "confidence": 0.58,
                        "intent_type": detected_type,
                        "next_step": _next_step_for_intent_type(detected_type),
                        "error_type": "none",
                        "action_taken": "proceed",
                        "query": normalized_query_for_fallback,
                        "schema": normalized_schema_for_fallback,
                        "extracted_intent": extracted_intent,
                        "validated_intent": validated_intent,
                        "attempts": attempts,
                        "attempts_count": len(attempts),
                        "started_at": stage_started_at,
                        "finished_at": finished_at,
                        "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                        "warnings": [
                            {
                                "type": "intent_extraction_llm_fallback",
                                "message": (
                                    "LLM intent extraction failed; used deterministic query-planner "
                                    "fallback to continue the analytical flow."
                                ),
                            }
                        ],
                        "errors": [],
                        "debug_metadata": {
                            "llm_provider": config.llm_provider,
                            "route": normalized_route,
                            "llm_prompt": llm_debug.get("prompt"),
                            "llm_raw_output": llm_debug.get("raw_output"),
                            "llm_parsed_payload": llm_debug.get("parsed_payload"),
                            "llm_fallback_used": True,
                            "llm_fallback_error_type": error_type,
                            "llm_fallback_error": str(exc),
                            "fallback_source": llm_debug.get("fallback_source"),
                        },
                    }
                except Exception as fallback_exc:  # noqa: BLE001
                    _log_event(
                        logger,
                        logging.ERROR,
                        "Intent extraction fallback failed",
                        original_error=str(exc),
                        fallback_error=str(fallback_exc),
                    )

            inferred_type = infer_intent_type(query=str(query or ""), hinted_intent_type=None)
            next_step = _next_step_for_intent_type(inferred_type)
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"query": str(query or "")},
                    output_payload={},
                    success=False,
                    retry_triggered=action_taken == "retry",
                    retry_reason=str(exc) if action_taken == "retry" else "",
                    model_or_method_used=f"{config.llm_provider}_intent_extractor",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type=error_type,
                    error_message=str(exc),
                )
            )

            _log_event(
                logger,
                logging.ERROR,
                "Intent extraction stage failed",
                input_query=str(query or ""),
                error_type=error_type,
                action_taken=action_taken,
                retry_count=retry_count,
                error=str(exc),
            )

            if action_taken == "retry":
                retry_count += 1
                continue

            failed_result: dict[str, Any] = build_intent_extraction_failed_result(
                intent_type=inferred_type,
                next_step=next_step,
                error_type=error_type,
                action_taken=action_taken,
            )
            failed_result["query"] = str(query or "")
            failed_result["schema"] = schema if isinstance(schema, dict) else {}
            failed_result["attempts"] = attempts
            failed_result["attempts_count"] = len(attempts)
            failed_result["started_at"] = stage_started_at
            failed_result["finished_at"] = _utc_now()
            failed_result["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            failed_result["warnings"] = []
            failed_result["errors"] = [{"type": error_type, "message": str(exc)}]
            failed_result["debug_metadata"] = {
                "llm_provider": config.llm_provider,
                "route": normalized_route,
                "llm_prompt": llm_debug.get("prompt"),
                "llm_raw_output": llm_debug.get("raw_output"),
            }
            failed_result["confidence"] = stage_confidence(failed_result, base_success=0.86, base_degraded=0.58)
            return failed_result


def run_intent_extraction(query: str, schema: dict) -> dict:
    """
    Full runtime for legacy contract:
    extraction -> validation -> SQL build -> ClickHouse execution -> downstream routing.
    """
    stage_result = run_intent_extraction_stage(query=query, schema=schema)
    if not stage_allows_progress(stage_result.get("status"), degraded=bool(stage_result.get("degraded"))):
        return stage_result

    logger = _get_logger()
    config = IntentExtractionConfig.from_env()
    retry_count = 0
    attempts: list[dict[str, Any]] = []
    stage_started_at = _utc_now()
    stage_started_perf = time.perf_counter()

    normalized_query = str(stage_result.get("query", "")).strip()
    normalized_schema = stage_result.get("schema", {}) or {}
    extracted_intent = stage_result.get("extracted_intent", {}) or {}
    validated_intent = stage_result.get("validated_intent", {}) or {}
    detected_type = str(stage_result.get("intent_type", "analytical") or "analytical")
    next_step = _next_step_for_intent_type(detected_type)

    while True:
        try:
            attempt_started_perf = time.perf_counter()
            routing_result = route_intent(
                query=normalized_query,
                intent=validated_intent,
                schema=normalized_schema,
                config=config,
            )
            _log_event(
                logger,
                logging.INFO,
                "Routing decision completed",
                intent_type=detected_type,
                next_step=routing_result["next_step"],
                sql_query=routing_result["sql_query"],
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={
                        "query": normalized_query,
                        "intent_type": detected_type,
                        "validated_intent": validated_intent,
                    },
                    output_payload=routing_result,
                    success=True,
                    retry_triggered=False,
                    model_or_method_used="route_intent",
                    duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                    validation_result={"is_valid": True},
                )
            )

            result: IntentExtractionTaskResult = build_intent_extraction_success_result(
                intent_type=detected_type,  # type: ignore[arg-type]
                sql_query=routing_result["sql_query"],
                next_step=routing_result["next_step"],
                extracted_intent=extracted_intent,
                normalized_intent=routing_result["normalized_intent"],
                execution_result=routing_result.get("execution_result"),
                downstream_result=routing_result.get("downstream_result"),
            )
            result["attempts"] = attempts
            result["attempts_count"] = len(attempts)
            result["started_at"] = stage_started_at
            result["finished_at"] = _utc_now()
            result["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            result["warnings"] = []
            result["errors"] = []
            result["confidence"] = stage_confidence(stage_result, base_success=0.86, base_degraded=0.58)
            return result
        except Exception as exc:  # noqa: BLE001
            error_type = classify_intent_extraction_error(exc)
            action_taken = decide_intent_extraction_action(
                error_type=error_type,
                retry_count=retry_count,
                config=config,
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"query": normalized_query, "validated_intent": validated_intent},
                    output_payload={},
                    success=False,
                    retry_triggered=action_taken == "retry",
                    retry_reason=str(exc) if action_taken == "retry" else "",
                    model_or_method_used="route_intent",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type=error_type,
                    error_message=str(exc),
                )
            )

            _log_event(
                logger,
                logging.ERROR,
                "Intent routing/execution failed",
                input_query=normalized_query,
                error_type=error_type,
                action_taken=action_taken,
                retry_count=retry_count,
                error=str(exc),
            )

            if action_taken == "retry":
                retry_count += 1
                continue

            failed_payload = build_intent_extraction_failed_result(
                intent_type=detected_type,  # type: ignore[arg-type]
                next_step=next_step,
                error_type=error_type,
                action_taken=action_taken,
            )
            failed_payload["attempts"] = attempts
            failed_payload["attempts_count"] = len(attempts)
            failed_payload["started_at"] = stage_started_at
            failed_payload["finished_at"] = _utc_now()
            failed_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            failed_payload["warnings"] = []
            failed_payload["errors"] = [{"type": error_type, "message": str(exc)}]
            failed_payload["confidence"] = stage_confidence(failed_payload, base_success=0.86, base_degraded=0.58)
            return failed_payload


def _attach_fn_compat(func):
    """
    Keep compatibility for existing call sites/tests that use Prefect's `.fn`.
    """
    setattr(func, "fn", func)
    return func


@_attach_fn_compat
def intent_extraction_task(query: str, schema: dict) -> dict:
    return run_intent_extraction(query=query, schema=schema)
