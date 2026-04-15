from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from reasoning_app.llm_intent_client import classify_question
from shared.input_classifier import classify_input
from shared.pipeline_trace import make_attempt


IntentErrorType = Literal["system", "model", "input", "logic", "unknown"]
IntentActionType = Literal["retry", "stop"]


class IntentClassificationResult(TypedDict):
    status: Literal["success", "failed"]
    is_analytical: bool
    error_type: str
    action_taken: IntentActionType


class IntentClassificationError(Exception):
    """Base exception for intent classification task failures."""


class IntentInputError(IntentClassificationError):
    """Input text cannot be classified."""


class IntentLogicError(IntentClassificationError):
    """Unexpected return shape from existing classifier wrapper."""


class IntentModelOutputError(IntentClassificationError):
    """Classifier output values are malformed."""


@dataclass(frozen=True)
class IntentTaskConfig:
    max_retries: int

    @classmethod
    def from_env(cls) -> "IntentTaskConfig":
        raw = os.getenv("INTENT_CLASSIFICATION_MAX_RETRIES")
        if raw is None:
            return cls(max_retries=1)
        try:
            parsed = int(raw)
        except ValueError:
            parsed = 1
        return cls(max_retries=max(0, min(parsed, 1)))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_logger() -> logging.Logger:
    return logging.getLogger(__name__)


def _log_event(logger: logging.Logger, level: int, message: str, **fields: object) -> None:
    payload = {"timestamp": _utc_now(), **fields}
    logger.log(level, "%s | %s", message, json.dumps(payload, sort_keys=True, default=str))


def classify_intent_task_error(exception: BaseException) -> IntentErrorType:
    if isinstance(exception, IntentInputError):
        return "input"

    if isinstance(exception, IntentModelOutputError):
        return "model"

    if isinstance(exception, IntentLogicError):
        return "logic"

    lowered = str(exception).lower()
    if "timeout" in lowered or "timed out" in lowered or "temporary" in lowered:
        return "system"

    return "unknown"


def _decide_intent_action(
    error_type: IntentErrorType,
    retry_count: int,
    config: IntentTaskConfig,
) -> IntentActionType:
    if error_type in {"input", "logic"}:
        return "stop"
    if error_type in {"system", "model", "unknown"} and retry_count < config.max_retries:
        return "retry"
    return "stop"


def _validate_cleaned_text(cleaned_text: str) -> None:
    if cleaned_text is None:
        raise IntentInputError("Input text is missing.")


_STRONG_ANALYTICAL_PATTERNS = (
    r"\b(show|list|give|display|plot)\b.*\b(total|sum|average|avg|count|number\s+of|max|min|distribution|breakdown|population|revenue|profit|margin|sales|age)\b",
    r"\b(total|sum|average|avg|count|number\s+of|max|min)\b.*\b(by|per|across|for each|in each)\b",
    r"\b(distribution|breakdown)\b.*\b(by|per|across|for each|in each)\b",
    r"\b(top|bottom)\s+\d+\b.*\bby\b",
    r"\bhow many\b.*\b(by|per|across|for each|in each)\b",
)

_ANALYTICAL_KEYWORDS = (
    "total",
    "sum",
    "average",
    "avg",
    "count",
    "number of",
    "max",
    "min",
    "median",
    "mean",
    "population",
    "revenue",
    "profit",
    "margin",
    "sales",
    "age",
    "trend",
    "distribution",
    "breakdown",
    "compare",
    "top",
    "bottom",
)

_GROUP_BY_KEYWORDS = (
    "by",
    "per",
    "across",
    "for each",
    "in each",
    "group by",
)

_STRONG_CONVERSATIONAL_PATTERNS = (
    r"\bhello\b",
    r"\bhi\b",
    r"\bhey\b",
    r"\bhow are you\b",
    r"\bthanks?\b",
    r"\bthank you\b",
    r"\bgood (morning|afternoon|evening)\b",
)

_SKIP_LABELS = {
    "invalid_input",
    "numeric_only_input",
    "noise_input",
    "empty_input",
    "transcription_failure",
    "no_speech_detected",
}


def _normalize_intent_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_intent_text(phrase)
    if not normalized_phrase:
        return False
    pattern = r"\b" + re.escape(normalized_phrase).replace(r"\ ", r"\s+") + r"\b"
    return bool(re.search(pattern, text))


def _detect_rule_based_analytical(text: str) -> dict[str, Any]:
    normalized = _normalize_intent_text(text)
    if not normalized:
        return {
            "is_analytical": False,
            "matched_keywords": [],
            "matched_grouping_keywords": [],
            "matched_patterns": [],
        }

    matched_keywords = [
        keyword
        for keyword in _ANALYTICAL_KEYWORDS
        if _contains_phrase(normalized, keyword)
    ]
    matched_grouping_keywords = [
        keyword
        for keyword in _GROUP_BY_KEYWORDS
        if _contains_phrase(normalized, keyword)
    ]
    matched_patterns = [
        pattern
        for pattern in _STRONG_ANALYTICAL_PATTERNS
        if re.search(pattern, normalized)
    ]

    has_metric_signal = bool(matched_keywords)
    has_group_signal = bool(matched_grouping_keywords)
    is_analytical = bool(
        matched_patterns
        or has_metric_signal
        or (has_group_signal and has_metric_signal)
    )
    return {
        "is_analytical": is_analytical,
        "matched_keywords": matched_keywords,
        "matched_grouping_keywords": matched_grouping_keywords,
        "matched_patterns": matched_patterns,
    }


def _is_strong_conversational_signal(text: str) -> bool:
    normalized = _normalize_intent_text(text)
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in _STRONG_CONVERSATIONAL_PATTERNS)


def _extract_classifier_label(classifier_output: Any) -> tuple[str, bool]:
    if not isinstance(classifier_output, dict):
        raise IntentLogicError("Classifier output must be a dictionary.")

    decision_source = _normalize_intent_text(classifier_output.get("decision_source"))
    llm_explicit_flag = bool(classifier_output.get("llm_explicit_decision", False))

    classification_candidates = [
        classifier_output.get("classification"),
        classifier_output.get("question_type"),
        classifier_output.get("intent_type"),
    ]
    for candidate in classification_candidates:
        normalized = _normalize_intent_text(candidate)
        if normalized == "analytical":
            return "analytical", bool(llm_explicit_flag or decision_source == "llm_explicit")
        if normalized in {"conversational", "informational", "information", "non_analytical", "non-analytical"}:
            return "conversational", bool(llm_explicit_flag or decision_source == "llm_explicit")

    needs_sql = classifier_output.get("needs_sql")
    if isinstance(needs_sql, bool):
        return ("analytical" if needs_sql else "conversational"), False

    raise IntentModelOutputError("Classifier output is missing an interpretable label.")


def _log_intent_detection_summary(
    *,
    logger: logging.Logger,
    input_text: str,
    rule_based_detected: bool,
    llm_label: str,
    llm_source: str,
    final_label: str,
) -> None:
    _log_event(
        logger,
        logging.INFO,
        "[Intent Detection] Decision",
        input_text=input_text[:200],
        rule_based="SUCCESS" if rule_based_detected else "FAILED",
        llm=llm_label or "SKIPPED",
        llm_source=llm_source or "n/a",
        final=final_label,
    )


def run_intent_classification(
    cleaned_text: str,
    raw_text: str | None = None,
    *,
    source: str = "text",
    transcription_status: str | None = None,
) -> dict:
    """
    Runtime wrapper for existing analytical-vs-non-analytical intent classification.
    """
    logger = _get_logger()
    config = IntentTaskConfig.from_env()
    retry_count = 0
    stage_started_at = _utc_now()
    stage_started_perf = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    normalized_cleaned_text = _normalize_intent_text(cleaned_text)
    normalized_raw_text = _normalize_intent_text(raw_text if raw_text is not None else cleaned_text or "")

    pre_classification = classify_input(
        raw_text=normalized_raw_text,
        cleaned_text=normalized_cleaned_text,
        source=source,
        transcription_status=transcription_status,
    )
    _log_event(
        logger,
        logging.INFO,
        "Intent pre-classification completed",
        classification=pre_classification.get("classification"),
        reason=pre_classification.get("reason"),
        confidence=pre_classification.get("confidence"),
        source=source,
    )
    attempts.append(
        make_attempt(
            attempt_number=1,
            input_payload={
                "raw_text": normalized_raw_text,
                "cleaned_text": normalized_cleaned_text,
                "source": source,
                "transcription_status": transcription_status,
            },
            output_payload=pre_classification,
            success=True,
            retry_triggered=False,
            model_or_method_used="rule_based_input_classifier",
            duration_ms=0,
            validation_result={"is_valid": True},
        )
    )

    pre_label = str(pre_classification.get("classification", "")).strip().lower()
    pre_reason = str(pre_classification.get("reason", "")).strip().lower()
    pre_confidence = float(pre_classification.get("confidence", 0.0) or 0.0)
    if pre_label in _SKIP_LABELS:
        finished_at = _utc_now()
        return {
            "status": "success",
            "is_analytical": False,
            "error_type": "none",
            "action_taken": "stop",
            "classification": pre_label or "invalid_input",
            "classification_reason": pre_classification.get("reason", ""),
            "confidence": float(pre_classification.get("confidence", 0.5) or 0.5),
            "question_type": pre_label or "unknown",
            "raw_classifier_output": pre_classification,
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": finished_at,
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [],
            "debug_metadata": {
                "route": "stop",
                "classification_source": "rule_based_input_classifier",
            },
        }

    rule_detection = _detect_rule_based_analytical(normalized_cleaned_text)
    rule_based_detected = bool(rule_detection.get("is_analytical"))
    if pre_label == "forecast":
        rule_based_detected = True
    _log_event(
        logger,
        logging.INFO,
        "Rule-based analytical detection evaluated",
        detected=rule_based_detected,
        matched_keywords=rule_detection.get("matched_keywords", []),
        matched_grouping_keywords=rule_detection.get("matched_grouping_keywords", []),
    )

    attempts.append(
        make_attempt(
            attempt_number=len(attempts) + 1,
            input_payload={"cleaned_text": normalized_cleaned_text},
            output_payload={
                "rule_based_detected": rule_based_detected,
                "matched_keywords": rule_detection.get("matched_keywords", []),
                "matched_grouping_keywords": rule_detection.get("matched_grouping_keywords", []),
                "matched_patterns": rule_detection.get("matched_patterns", []),
                "input_classifier_label": pre_label,
            },
            success=True,
            retry_triggered=False,
            model_or_method_used="rule_based_intent_detector",
            duration_ms=0,
            validation_result={"is_valid": True},
        )
    )

    if rule_based_detected:
        _log_intent_detection_summary(
            logger=logger,
            input_text=normalized_cleaned_text,
            rule_based_detected=True,
            llm_label="SKIPPED",
            llm_source="rule_based",
            final_label="analytical",
        )
        finished_at = _utc_now()
        return {
            "status": "success",
            "is_analytical": True,
            "error_type": "none",
            "action_taken": "stop",
            "classification": "analytical",
            "classification_reason": "rule_based_analytical_detection",
            "confidence": 0.92,
            "question_type": "analytical",
            "raw_classifier_output": {
                "rule_based": rule_detection,
                "input_classifier": pre_classification,
            },
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": finished_at,
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [],
            "debug_metadata": {
                "route": "proceed",
                "classification_source": "rule_based_intent_detector",
                "rule_based": rule_detection,
            },
        }

    strong_conversational_signal = (
        pre_label == "conversational"
        and pre_reason == "conversational_pattern_detected"
        and pre_confidence >= 0.9
        and _is_strong_conversational_signal(normalized_cleaned_text)
    )
    if strong_conversational_signal:
        attempts.append(
            make_attempt(
                attempt_number=len(attempts) + 1,
                input_payload={"cleaned_text": normalized_cleaned_text},
                output_payload={"classification": "conversational", "reason": pre_reason},
                success=True,
                retry_triggered=False,
                model_or_method_used="rule_based_conversational_guard",
                duration_ms=0,
                validation_result={"is_valid": True},
            )
        )
        _log_intent_detection_summary(
            logger=logger,
            input_text=normalized_cleaned_text,
            rule_based_detected=False,
            llm_label="SKIPPED",
            llm_source="rule_based_conversational_guard",
            final_label="conversational",
        )
        finished_at = _utc_now()
        return {
            "status": "success",
            "is_analytical": False,
            "error_type": "none",
            "action_taken": "stop",
            "classification": "conversational",
            "classification_reason": "rule_based_conversational_detection",
            "confidence": max(pre_confidence, 0.9),
            "question_type": "conversational",
            "raw_classifier_output": pre_classification,
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": finished_at,
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [],
            "debug_metadata": {
                "route": "stop",
                "classification_source": "rule_based_conversational_guard",
                "input_classifier": pre_classification,
            },
        }

    while True:
        try:
            _validate_cleaned_text(normalized_cleaned_text)
            llm_started_perf = time.perf_counter()
            classifier_output = classify_question(normalized_cleaned_text)
            llm_label, llm_is_explicit = _extract_classifier_label(classifier_output)
            llm_duration_ms = int((time.perf_counter() - llm_started_perf) * 1000)

            if llm_is_explicit and llm_label == "conversational":
                final_label = "conversational"
                final_reason = "llm_explicit_conversational"
                confidence = 0.78
            elif llm_is_explicit and llm_label == "analytical":
                final_label = "analytical"
                final_reason = "llm_explicit_analytical"
                confidence = 0.86
            else:
                # Guardrail: avoid routing non-analytical/noise-like inputs into SQL on weak signals.
                if llm_label == "conversational" and pre_label in {"conversational", "noise_input", "invalid_input"}:
                    final_label = "conversational"
                    final_reason = "heuristic_conversational_alignment"
                    confidence = max(pre_confidence, 0.72)
                elif pre_label == "analytical":
                    final_label = "analytical"
                    final_reason = "heuristic_analytical_alignment"
                    confidence = max(pre_confidence, 0.72)
                elif pre_label == "forecast":
                    final_label = "analytical"
                    final_reason = "heuristic_forecast_alignment"
                    confidence = max(pre_confidence, 0.74)
                else:
                    final_label = "conversational"
                    final_reason = "safety_default_conversational"
                    confidence = max(pre_confidence, 0.68)

            is_analytical = final_label == "analytical"
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"cleaned_text": normalized_cleaned_text},
                    output_payload=classifier_output,
                    success=True,
                    retry_triggered=False,
                    model_or_method_used="llm_intent_classifier",
                    duration_ms=llm_duration_ms,
                    validation_result={
                        "is_valid": True,
                        "needs_sql": classifier_output.get("needs_sql"),
                        "question_type": classifier_output.get("question_type"),
                        "llm_label": llm_label,
                        "llm_explicit_decision": llm_is_explicit,
                    },
                )
            )

            _log_intent_detection_summary(
                logger=logger,
                input_text=normalized_cleaned_text,
                rule_based_detected=False,
                llm_label=llm_label,
                llm_source=str(classifier_output.get("decision_source") or "llm_intent_classifier"),
                final_label=final_label,
            )

            finished_at = _utc_now()
            return {
                "status": "success",
                "is_analytical": is_analytical,
                "error_type": "none",
                "action_taken": "stop",
                "classification": final_label,
                "classification_reason": final_reason,
                "confidence": confidence,
                "question_type": final_label,
                "raw_classifier_output": classifier_output,
                "attempts": attempts,
                "attempts_count": len(attempts),
                "started_at": stage_started_at,
                "finished_at": finished_at,
                "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                "warnings": [],
                "errors": [],
                "debug_metadata": {
                    "route": "proceed" if final_label == "analytical" else "stop",
                    "classification_source": "llm_intent_classifier",
                    "llm_label": llm_label,
                    "llm_explicit_decision": llm_is_explicit,
                },
            }
        except Exception as exc:  # noqa: BLE001
            error_type = classify_intent_task_error(exc)
            action_taken = _decide_intent_action(
                error_type=error_type,
                retry_count=retry_count,
                config=config,
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"cleaned_text": normalized_cleaned_text},
                    output_payload={},
                    success=False,
                    retry_triggered=action_taken == "retry",
                    retry_reason=str(exc) if action_taken == "retry" else "",
                    model_or_method_used="llm_intent_classifier",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type=error_type,
                    error_message=str(exc),
                )
            )

            _log_event(
                logger,
                logging.ERROR,
                "Intent classification failed",
                input_chars=len(str(normalized_cleaned_text or "")),
                input_text_preview=str(normalized_cleaned_text or "")[:200],
                error_type=error_type,
                action_taken=action_taken,
                retry_count=retry_count,
                error=str(exc),
            )

            if action_taken == "retry":
                retry_count += 1
                continue

            finished_at = _utc_now()
            _log_intent_detection_summary(
                logger=logger,
                input_text=normalized_cleaned_text,
                rule_based_detected=False,
                llm_label="ERROR",
                llm_source="llm_intent_classifier",
                final_label="analytical" if pre_label in {"analytical", "forecast"} else "conversational",
            )
            return {
                "status": "success",
                "is_analytical": bool(pre_label in {"analytical", "forecast"}),
                "error_type": "none",
                "action_taken": "stop",
                "classification": "analytical" if pre_label in {"analytical", "forecast"} else "conversational",
                "classification_reason": (
                    "safety_default_analytical_on_llm_error"
                    if pre_label in {"analytical", "forecast"}
                    else "safety_default_conversational_on_llm_error"
                ),
                "confidence": max(pre_confidence, 0.68),
                "question_type": "analytical" if pre_label in {"analytical", "forecast"} else "conversational",
                "raw_classifier_output": {},
                "attempts": attempts,
                "attempts_count": len(attempts),
                "started_at": stage_started_at,
                "finished_at": finished_at,
                "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                "warnings": [{"type": error_type, "message": str(exc)}],
                "errors": [],
                "debug_metadata": {
                    "route": "proceed" if pre_label in {"analytical", "forecast"} else "stop",
                    "classification_source": "safety_default",
                    "llm_error": str(exc),
                },
            }


def _attach_fn_compat(func):
    """
    Keep compatibility for existing call sites/tests that use Prefect's `.fn`.
    """
    setattr(func, "fn", func)
    return func


@_attach_fn_compat
def intent_classification_task(cleaned_text: str) -> dict:
    return run_intent_classification(cleaned_text=cleaned_text)


def route_intent_classification(
    cleaned_text: str,
    classification_result: dict[str, Any],
    user_id: str = "",
) -> dict[str, Any]:
    """
    Decision-based routing after intent classification.
    """
    if classification_result.get("status") != "success":
        return {
            "status": "failed",
            "message": "Intent classification failed.",
            "reason": "intent_classification_failed",
            "details": classification_result,
        }

    classification_label = str(classification_result.get("classification", "")).strip().lower()
    if classification_label in {
        "invalid_input",
        "numeric_only_input",
        "noise_input",
        "empty_input",
        "transcription_failure",
        "no_speech_detected",
    }:
        reason = classification_result.get("classification_reason") or classification_label
        return {
            "status": "rejected",
            "message": f"The request is invalid for analysis: {reason}.",
            "reason": classification_label,
            "classification": classification_result,
        }

    if classification_label == "conversational" or not bool(classification_result.get("is_analytical", False)):
        return {
            "status": "rejected",
            "message": "The question is not analytical and cannot be processed.",
            "reason": "non_analytical",
            "classification": classification_result,
        }

    return {
        "status": "routed",
        "next_stage": "preprocessing_high",
        "module_path": "services/ai-service/preprocessing_high/",
        "classification": classification_result,
        "payload": {
            "cleaned_text": cleaned_text,
            "user_id": str(user_id or "").strip(),
        },
    }
