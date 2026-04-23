from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
_DEFAULT_OLLAMA_MODEL = "gemma3:1b"
_DEFAULT_TIMEOUT_SECONDS = 15
_DEFAULT_MAX_RETRIES = 2
_TRANSIENT_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}

ANALYTICAL_KEYWORDS = (
    "average",
    "avg",
    "sum",
    "count",
    "number of",
    "max",
    "min",
    "total",
    "distribution",
    "percent",
    "percentage",
    "ratio",
    "share",
    "median",
    "mean",
    "highest",
    "lowest",
    "by",
    "per",
    "group",
    "breakdown",
    "compare",
    "across",
    "trend",
    "top",
    "bottom",
    "rank",
    "over time",
    "population",
    "revenue",
    "profit",
    "margin",
    "sales",
)

PREDICTIVE_KEYWORDS = (
    "forecast",
    "predict",
    "prediction",
    "projected",
    "projection",
    "expected",
    "future",
    "next",
    "upcoming",
)

_PREDICTIVE_PATTERNS = (
    r"\bfor\s+the\s+next\b",
    r"\bin\s+the\s+next\b",
    r"\bover\s+the\s+next\b",
    r"\bnext\s+\d+\s+(day|days|week|weeks|month|months|year|years)\b",
    r"\b(?:for|in|over)\s+the\s+next\s+\d+\s+(day|days|week|weeks|month|months|year|years)\b",
    r"\bnext\s+(day|week|month|year)\b",
    r"\btrend\b.*\b(next|future|upcoming|forecast|predict)\b",
    r"\b(next|future|upcoming|forecast|predict)\b.*\btrend\b",
)

_ANALYTICAL_PATTERNS = (
    r"\b(total|sum|average|avg|mean|count|number\s+of|max|min)\b",
    r"\b(by|per|across|for each|in each)\b",
    r"\bhow many\b",
    r"\b(top|bottom)\s+\d+\b",
)

_CONVERSATIONAL_PATTERNS = (
    r"\bhello\b",
    r"\bhi\b",
    r"\bhey\b",
    r"\bhow are you\b",
    r"\bthanks?\b",
    r"\bthank you\b",
)


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase_value = str(phrase or "").strip().lower()
    if not phrase_value:
        return False
    phrase_pattern = r"\b" + re.escape(phrase_value).replace(r"\ ", r"\s+") + r"\b"
    return bool(re.search(phrase_pattern, text))


def _build_decision_payload(
    *,
    classification: str,
    decision_source: str,
    llm_raw_response: str = "",
    llm_error: str = "",
    llm_explicit_decision: bool = False,
) -> dict[str, Any]:
    normalized_raw = str(classification).strip().lower()
    if normalized_raw in {"predictive", "forecast", "forecasting"}:
        normalized = "predictive"
    elif normalized_raw == "analytical":
        normalized = "analytical"
    else:
        normalized = "conversational"
    needs_sql = normalized in {"analytical", "predictive"}
    question_type = normalized if normalized in {"analytical", "predictive"} else "informational"
    return {
        "classification": normalized,
        "question_type": question_type,
        "needs_sql": needs_sql,
        "needs_chart": needs_sql,
        "requires_forecast": normalized == "predictive",
        "route": "forecasting" if normalized == "predictive" else ("analytical" if normalized == "analytical" else "stop"),
        "decision_source": decision_source,
        "llm_raw_response": llm_raw_response,
        "llm_error": llm_error,
        "llm_explicit_decision": bool(llm_explicit_decision),
    }


def _get_ollama_url() -> str:
    return str(os.getenv("INTENT_CLASSIFIER_OLLAMA_URL", _DEFAULT_OLLAMA_URL)).strip() or _DEFAULT_OLLAMA_URL


def _get_ollama_model() -> str:
    return str(os.getenv("INTENT_CLASSIFIER_OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL)).strip() or _DEFAULT_OLLAMA_MODEL


def _get_timeout_seconds() -> int:
    raw_value = str(os.getenv("INTENT_CLASSIFIER_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)).strip()
    try:
        parsed = int(raw_value)
    except ValueError:
        parsed = _DEFAULT_TIMEOUT_SECONDS
    return max(1, parsed)


def _get_max_retries() -> int:
    raw_value = str(os.getenv("INTENT_CLASSIFIER_LLM_RETRIES", _DEFAULT_MAX_RETRIES)).strip()
    try:
        parsed = int(raw_value)
    except ValueError:
        parsed = _DEFAULT_MAX_RETRIES
    return max(0, min(parsed, 5))


def is_force_analytical(question: str) -> bool:
    """Rule-based check for clearly analytical questions."""
    normalized = _normalize_text(question)
    if not normalized:
        return False

    if any(re.search(pattern, normalized) for pattern in _ANALYTICAL_PATTERNS):
        return True
    return any(_contains_phrase(normalized, keyword) for keyword in ANALYTICAL_KEYWORDS)


def _heuristic_classification(question: str) -> dict[str, Any]:
    """
    Local fallback when Ollama is unavailable.
    Safety policy: default to analytical to avoid false conversational rejection.
    """
    normalized = _normalize_text(question)
    if not normalized:
        return _build_decision_payload(
            classification="conversational",
            decision_source="heuristic_empty_input",
            llm_explicit_decision=False,
        )

    if _has_predictive_signal(normalized):
        return _build_decision_payload(
            classification="predictive",
            decision_source="heuristic_predictive_rule_based",
            llm_explicit_decision=False,
        )

    if is_force_analytical(normalized):
        return _build_decision_payload(
            classification="analytical",
            decision_source="heuristic_rule_based",
            llm_explicit_decision=False,
        )

    if any(re.search(pattern, normalized) for pattern in _CONVERSATIONAL_PATTERNS):
        return _build_decision_payload(
            classification="conversational",
            decision_source="heuristic_conversational_pattern",
            llm_explicit_decision=False,
        )

    return _build_decision_payload(
        classification="analytical",
        decision_source="heuristic_default_analytical",
        llm_explicit_decision=False,
    )


def _build_prompt(question: str) -> str:
    return (
        "You are an intent classifier for a BI assistant.\n"
        "Classify the user query into exactly one label:\n"
        "- analytical: requires data analysis (aggregations/grouping/comparisons/trends)\n"
        "- predictive: requires forecasting/prediction for future periods\n"
        "- conversational: greeting/chitchat/help text without data analysis\n\n"
        "Output constraints:\n"
        "- Output exactly one lowercase word.\n"
        "- Allowed outputs: analytical OR predictive OR conversational\n"
        "- No punctuation.\n"
        "- No explanations.\n\n"
        f"Query: {question}\n"
        "Label:"
    )


def _extract_ollama_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error_message = payload.get("error")
            if isinstance(error_message, str) and error_message.strip():
                return error_message.strip()
    except ValueError:
        pass
    return response.text.strip()


def _parse_llm_label(raw_output: str) -> str:
    normalized = _normalize_text(raw_output)
    if normalized in {"analytical", "predictive", "conversational"}:
        return normalized
    if normalized in {"forecast", "forecasting"}:
        return "predictive"
    if normalized in {"informational", "information", "non_analytical", "non-analytical"}:
        return "conversational"

    if normalized.startswith("{") and normalized.endswith("}"):
        try:
            payload = json.loads(normalized)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            for key in ("classification", "label", "question_type", "intent_type", "type"):
                value = payload.get(key)
                if value is None:
                    continue
                parsed = _normalize_text(value)
                if parsed in {"analytical", "predictive", "conversational"}:
                    return parsed
                if parsed in {"forecast", "forecasting"}:
                    return "predictive"
                if parsed in {"informational", "information", "non_analytical", "non-analytical"}:
                    return "conversational"

    match = re.search(r"\b(analytical|predictive|forecast|forecasting|conversational|informational)\b", normalized)
    if match:
        value = match.group(1)
        if value == "informational":
            return "conversational"
        if value in {"forecast", "forecasting"}:
            return "predictive"
        return value

    raise ValueError(f"Unsupported classifier output: {raw_output!r}")


def _call_ollama_classifier(*, question: str) -> str:
    ollama_url = _get_ollama_url()
    ollama_model = _get_ollama_model()
    timeout_seconds = _get_timeout_seconds()
    max_retries = _get_max_retries()
    prompt = _build_prompt(question)
    payload = {
        "model": ollama_model,
        "prompt": prompt,
        "stream": False,
    }

    last_error: str = ""
    for attempt in range(max_retries + 1):
        attempt_index = attempt + 1
        logger.info(
            "[Intent Detection] LLM request attempt=%s/%s endpoint=%s model=%s input=%r",
            attempt_index,
            max_retries + 1,
            ollama_url,
            ollama_model,
            question[:200],
        )
        try:
            response = requests.post(
                ollama_url,
                json=payload,
                timeout=timeout_seconds,
            )
        except requests.Timeout as exc:
            last_error = f"Ollama timeout after {timeout_seconds}s: {exc}"
            if attempt < max_retries:
                time.sleep(min(2.0, 0.25 * (2**attempt)))
                continue
            raise RuntimeError(last_error) from exc
        except requests.ConnectionError as exc:
            last_error = f"Ollama connection error: {exc}"
            if attempt < max_retries:
                time.sleep(min(2.0, 0.25 * (2**attempt)))
                continue
            raise RuntimeError(last_error) from exc
        except requests.RequestException as exc:
            last_error = f"Ollama request error: {exc}"
            if attempt < max_retries:
                time.sleep(min(2.0, 0.25 * (2**attempt)))
                continue
            raise RuntimeError(last_error) from exc

        if response.status_code in _TRANSIENT_HTTP_STATUSES:
            last_error = (
                f"Ollama transient HTTP {response.status_code}: "
                f"{_extract_ollama_error_message(response)}"
            )
            if attempt < max_retries:
                time.sleep(min(2.0, 0.25 * (2**attempt)))
                continue
            raise RuntimeError(last_error)

        if response.status_code >= 400:
            last_error = (
                f"Ollama HTTP {response.status_code}: "
                f"{_extract_ollama_error_message(response)}"
            )
            raise RuntimeError(last_error)

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Ollama returned non-JSON payload.") from exc

        raw_output = str(response_payload.get("response", "")).strip()
        logger.info("[Intent Detection] LLM raw response=%r", raw_output[:500])
        if not raw_output:
            last_error = "Ollama returned empty response."
            if attempt < max_retries:
                time.sleep(min(2.0, 0.25 * (2**attempt)))
                continue
            raise RuntimeError(last_error)

        return raw_output

    raise RuntimeError(last_error or "Ollama classifier failed.")


def classify_question(question: str) -> dict[str, Any]:
    """
    Intent classification result with explicit decision metadata.
    """
    normalized_question = _normalize_text(question)
    if not normalized_question:
        return _build_decision_payload(
            classification="conversational",
            decision_source="empty_input",
            llm_explicit_decision=False,
        )

    # Rule-based guard (higher priority than LLM).
    if _has_predictive_signal(normalized_question):
        return _build_decision_payload(
            classification="predictive",
            decision_source="predictive_rule_based_guard",
            llm_explicit_decision=False,
        )

    if is_force_analytical(normalized_question):
        return _build_decision_payload(
            classification="analytical",
            decision_source="rule_based_guard",
            llm_explicit_decision=False,
        )

    try:
        raw_output = _call_ollama_classifier(question=normalized_question)
        classification = _parse_llm_label(raw_output)
        return _build_decision_payload(
            classification=classification,
            decision_source="llm_explicit",
            llm_raw_response=raw_output,
            llm_explicit_decision=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[Intent Detection] LLM classification failed, applying safety fallback. error=%s",
            str(exc),
        )
        fallback = _heuristic_classification(normalized_question)
        fallback["llm_error"] = str(exc)
        return fallback


def _has_predictive_signal(question: str) -> bool:
    normalized = _normalize_text(question)
    if not normalized:
        return False
    if any(_contains_phrase(normalized, keyword) for keyword in PREDICTIVE_KEYWORDS):
        return True
    return any(re.search(pattern, normalized) for pattern in _PREDICTIVE_PATTERNS)
