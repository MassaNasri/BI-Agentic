from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from preprocessing_low.cleaners import _rule_based_clean_with_changes
from preprocessing_low.error_handler import (
    PreprocessInputError,
    _decide_preprocess_action,
    classify_preprocess_error,
)
from preprocessing_low.llm_client import _call_ollama_preprocessor
from preprocessing_low.schemas import (
    TextPreprocessConfig,
    build_preprocess_failed_result,
    build_preprocess_success_result,
)
from shared.confidence import preprocessing_low_confidence
from shared.pipeline_trace import make_attempt


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_logger() -> logging.Logger:
    return logging.getLogger(__name__)


def _log_event(logger: logging.Logger, level: int, message: str, **fields: object) -> None:
    payload = {"timestamp": _utc_now(), **fields}
    logger.log(level, "%s | %s", message, json.dumps(payload, sort_keys=True, default=str))


def run_preprocess_text(text: str) -> dict:
    """
    Runtime entrypoint for language-agnostic text preprocessing.
    """
    logger = _get_logger()
    config = TextPreprocessConfig.from_env()
    retry_count = 0
    stage_started_at = _utc_now()
    stage_started_perf = time.perf_counter()
    attempts: list[dict] = []

    try:
        source_text = text if isinstance(text, str) else str(text or "")
        rule_started_perf = time.perf_counter()
        rule_cleaned_text, detected_changes, input_flags = _rule_based_clean_with_changes(source_text)
        rule_duration_ms = int((time.perf_counter() - rule_started_perf) * 1000)
        rule_validation = {
            "is_valid": True,
            "flags": input_flags,
            "change_count": len(detected_changes),
        }
        attempts.append(
            make_attempt(
                attempt_number=1,
                input_payload={"text": source_text},
                output_payload={"cleaned_text": rule_cleaned_text, "detected_changes": detected_changes},
                success=True,
                retry_triggered=False,
                model_or_method_used="rule_based_cleaner",
                duration_ms=rule_duration_ms,
                validation_result=rule_validation,
            )
        )
    except Exception as exc:  # noqa: BLE001
        error_type = classify_preprocess_error(exc)
        finished_at = _utc_now()
        _log_event(
            logger,
            logging.ERROR,
            "Text preprocessing input validation failed",
            error_type=error_type,
            action_taken="stop",
            error=str(exc),
        )
        failure_payload = build_preprocess_failed_result(error_type=error_type, action_taken="stop")
        failure_payload["errors"] = [{"type": error_type, "message": str(exc)}]
        failure_payload["attempts"] = attempts
        failure_payload["attempts_count"] = len(attempts)
        failure_payload["started_at"] = stage_started_at
        failure_payload["finished_at"] = finished_at
        failure_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
        failure_payload["debug_metadata"] = {"input_chars": len(str(text or ""))}
        failure_payload["confidence"] = preprocessing_low_confidence(failure_payload)
        return failure_payload

    _log_event(
        logger,
        logging.INFO,
        "Rule-based text preprocessing completed",
        input_chars=len(source_text),
        cleaned_chars=len(rule_cleaned_text),
    )

    # Keep explicit empty/punctuation outcomes observable for downstream input classification.
    if (
        not source_text.strip()
        or rule_cleaned_text == ""
        or bool(input_flags.get("punctuation_only_input"))
        or bool(input_flags.get("numeric_only_input"))
        or bool(input_flags.get("noise_input"))
        or bool(input_flags.get("silence_like_input"))
    ):
        finished_at = _utc_now()
        success_payload = build_preprocess_success_result(cleaned_text=rule_cleaned_text)
        success_payload["detected_changes"] = detected_changes
        success_payload["warnings"] = [
            {
                "type": "empty_after_cleaning",
                "message": "Input was classified as empty, punctuation-only, numeric-only, noise-like, or silence-like during low preprocessing.",
            }
        ]
        success_payload["attempts"] = attempts
        success_payload["attempts_count"] = len(attempts)
        success_payload["started_at"] = stage_started_at
        success_payload["finished_at"] = finished_at
        success_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
        success_payload["debug_metadata"] = {
            "input_chars": len(source_text),
            "cleaned_chars": len(rule_cleaned_text),
            "input_flags": input_flags,
        }
        success_payload["confidence"] = preprocessing_low_confidence(success_payload)
        return success_payload

    while True:
        try:
            llm_started_perf = time.perf_counter()
            cleaned_text = _call_ollama_preprocessor(
                rule_cleaned_text,
                config=config,
                logger=logger,
                log_event=_log_event,
            )
            llm_cleaned_text, llm_changes, llm_flags = _rule_based_clean_with_changes(cleaned_text)
            final_cleaned_text = llm_cleaned_text or rule_cleaned_text
            final_changes = list(detected_changes)
            final_changes.extend(llm_changes)
            if source_text.strip() and source_text.strip() != final_cleaned_text and not final_changes:
                final_changes.append(
                    {
                        "type": "normalized_text",
                        "before": source_text.strip(),
                        "after": final_cleaned_text,
                    }
                )
            llm_duration_ms = int((time.perf_counter() - llm_started_perf) * 1000)
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"text": rule_cleaned_text},
                    output_payload={
                        "cleaned_text": final_cleaned_text,
                        "llm_raw_output": cleaned_text,
                        "post_llm_changes": llm_changes,
                    },
                    success=True,
                    retry_triggered=False,
                    model_or_method_used=f"ollama:{config.ollama_model}",
                    duration_ms=llm_duration_ms,
                    validation_result={"is_valid": bool(final_cleaned_text.strip()), "flags": llm_flags},
                )
            )
            finished_at = _utc_now()
            success_payload = build_preprocess_success_result(cleaned_text=final_cleaned_text)
            success_payload["detected_changes"] = final_changes
            success_payload["attempts"] = attempts
            success_payload["attempts_count"] = len(attempts)
            success_payload["started_at"] = stage_started_at
            success_payload["finished_at"] = finished_at
            success_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            success_payload["debug_metadata"] = {
                "input_chars": len(source_text),
                "rule_cleaned_chars": len(rule_cleaned_text),
                "final_cleaned_chars": len(final_cleaned_text),
                "input_flags": input_flags,
                "llm_output_flags": llm_flags,
            }
            success_payload["confidence"] = preprocessing_low_confidence(success_payload)
            return success_payload
        except Exception as exc:  # noqa: BLE001
            error_type = classify_preprocess_error(exc)
            action_taken = _decide_preprocess_action(
                error_type=error_type,
                retry_count=retry_count,
                config=config,
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"text": rule_cleaned_text},
                    output_payload={},
                    success=False,
                    retry_triggered=action_taken == "retry",
                    retry_reason=str(exc) if action_taken == "retry" else "",
                    model_or_method_used=f"ollama:{config.ollama_model}",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type=error_type,
                    error_message=str(exc),
                )
            )
            _log_event(
                logger,
                logging.ERROR,
                "LLM-based text preprocessing failed",
                error_type=error_type,
                action_taken=action_taken,
                retry_count=retry_count,
                error=str(exc),
            )

            if action_taken == "retry":
                retry_count += 1
                continue

            if error_type != "input" and bool(rule_cleaned_text.strip()):
                finished_at = _utc_now()
                fallback_payload = build_preprocess_success_result(cleaned_text=rule_cleaned_text)
                fallback_payload["detected_changes"] = detected_changes
                fallback_payload["attempts"] = attempts
                fallback_payload["attempts_count"] = len(attempts)
                fallback_payload["started_at"] = stage_started_at
                fallback_payload["finished_at"] = finished_at
                fallback_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
                fallback_payload["warnings"] = [
                    {
                        "type": "llm_preprocessing_fallback",
                        "message": (
                            "Ollama preprocessing failed; continued with deterministic "
                            "rule-based cleaned text."
                        ),
                    }
                ]
                fallback_payload["errors"] = []
                fallback_payload["debug_metadata"] = {
                    "input_chars": len(source_text),
                    "rule_cleaned_chars": len(rule_cleaned_text),
                    "input_flags": input_flags,
                    "llm_fallback_used": True,
                    "llm_fallback_error_type": error_type,
                    "llm_fallback_error": str(exc),
                }
                _log_event(
                    logger,
                    logging.WARNING,
                    "LLM preprocessing fallback activated",
                    fallback_error_type=error_type,
                    fallback_error=str(exc),
                    cleaned_chars=len(rule_cleaned_text),
                )
                fallback_payload["degraded"] = True
                fallback_payload["degradation_reason"] = "llm_preprocessing_fallback"
                fallback_payload["status"] = "degraded"
                fallback_payload["confidence"] = preprocessing_low_confidence(fallback_payload)
                return fallback_payload

            finished_at = _utc_now()
            failed_payload = build_preprocess_failed_result(
                error_type=error_type,
                action_taken=action_taken,
            )
            failed_payload["detected_changes"] = detected_changes
            failed_payload["errors"] = [{"type": error_type, "message": str(exc)}]
            failed_payload["attempts"] = attempts
            failed_payload["attempts_count"] = len(attempts)
            failed_payload["started_at"] = stage_started_at
            failed_payload["finished_at"] = finished_at
            failed_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            failed_payload["debug_metadata"] = {
                "input_chars": len(source_text),
                "rule_cleaned_chars": len(rule_cleaned_text),
                "input_flags": input_flags,
            }
            failed_payload["confidence"] = preprocessing_low_confidence(failed_payload)
            return failed_payload


def _attach_fn_compat(func):
    """
    Keep compatibility for existing call sites/tests that use Prefect's `.fn`.
    """
    setattr(func, "fn", func)
    return func


@_attach_fn_compat
def preprocess_text_task(text: str) -> dict:
    return run_preprocess_text(text)
