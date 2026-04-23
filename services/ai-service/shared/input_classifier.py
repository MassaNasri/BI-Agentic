from __future__ import annotations

import re
from typing import Any


_CONVERSATIONAL_PATTERNS = (
    r"\bhow are you\b",
    r"\bhello\b",
    r"\bhi\b",
    r"\bhey\b",
    r"\bthanks?\b",
    r"\bthank you\b",
    r"\bwho are you\b",
    r"\bwhat can you do\b",
    r"\bgood (morning|afternoon|evening)\b",
)

_FORECAST_PATTERNS = (
    r"\bforecast\b",
    r"\bpredict\b",
    r"\bprediction\b",
    r"\bproject(?:ed|ion)?\b",
    r"\bexpected\b",
    r"\bfuture\b",
    r"\bupcoming\b",
    r"\bfor\s+the\s+next\b",
    r"\bin\s+the\s+next\b",
    r"\bover\s+the\s+next\b",
    r"\bnext\s+(week|month|quarter|year)\b",
    r"\bnext\s+\d+\s+(day|days|week|weeks|month|months|year|years)\b",
    r"\b(?:for|in|over)\s+the\s+next\s+\d+\s+(day|days|week|weeks|month|months|year|years)\b",
    r"\bwhat\s+will\s+be\b",
    r"\btrend\b.*\b(next|future|upcoming|forecast|predict)\b",
    r"\b(next|future|upcoming|forecast|predict)\b.*\btrend\b",
)

_ANALYTICAL_HINTS = (
    "sum",
    "total",
    "average",
    "avg",
    "count",
    "number of",
    "max",
    "min",
    "by",
    "per",
    "group",
    "breakdown",
    "trend",
    "compare",
    "distribution",
    "distributed",
    "spread",
    "histogram",
    "frequency",
    "impact",
    "relationship",
    "correlation",
    "effect",
    "influence",
    "across",
    "population",
    "region",
    "regions",
    "revenue",
    "profit",
    "margin",
)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _contains_hint(text: str, hint: str) -> bool:
    normalized_hint = str(hint or "").strip().lower()
    if not normalized_hint:
        return False
    pattern = r"\b" + re.escape(normalized_hint).replace(r"\ ", r"\s+") + r"\b"
    return bool(re.search(pattern, text))


def _is_punctuation_only(text: str) -> bool:
    if not text:
        return False
    return bool(re.fullmatch(r"[\W_]+", text, flags=re.UNICODE))


def _is_empty_or_silence(text: str) -> bool:
    return not bool(re.search(r"\w", text or "", flags=re.UNICODE))


def _is_numeric_only(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return bool(re.fullmatch(r"[\d\s,._-]+", normalized) and re.search(r"\d", normalized))


def _is_noise_like(text: str) -> bool:
    normalized = re.sub(r"[^\w\s]", " ", str(text or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return False
    noise_tokens = (
        "uh",
        "uhh",
        "uhhh",
        "um",
        "umm",
        "ummm",
        "erm",
        "hmm",
        "mmm",
        "ah",
        "eh",
        "mm",
        "like",
        "please",
        "you",
        "know",
    )
    tokens = normalized.split()
    if not tokens:
        return False
    if normalized in {"you know", "uh huh", "mm hmm"}:
        return True
    return all(
        token in noise_tokens
        or bool(re.fullmatch(r"(?:uh+|um+|erm+|hmm+|mmm+|ah+|eh+|mm+)", token))
        for token in tokens
    )


def classify_input(
    *,
    raw_text: str,
    cleaned_text: str | None = None,
    transcription_status: str | None = None,
    source: str = "text",
) -> dict[str, Any]:
    raw = _normalize_text(raw_text)
    cleaned = _normalize_text(cleaned_text if cleaned_text is not None else raw)
    lowered = cleaned.lower()

    if transcription_status and str(transcription_status).lower() == "failed":
        return {
            "classification": "transcription_failure",
            "confidence": 1.0,
            "reason": "transcription_stage_failed",
            "source": source,
            "route": "stop",
            "flags": ["upstream_failure"],
        }

    if not raw and source == "audio":
        return {
            "classification": "no_speech_detected",
            "confidence": 1.0,
            "reason": "empty_transcript_from_audio",
            "source": source,
            "route": "stop",
            "flags": ["no_content"],
        }

    if not raw:
        return {
            "classification": "empty_input",
            "confidence": 1.0,
            "reason": "empty_text",
            "source": source,
            "route": "stop",
            "flags": ["no_content"],
        }

    if _is_punctuation_only(raw):
        return {
            "classification": "invalid_input",
            "confidence": 1.0,
            "reason": "punctuation_only",
            "source": source,
            "route": "stop",
            "flags": ["invalid_chars_only", "punctuation_only_input"],
        }

    if _is_numeric_only(raw):
        return {
            "classification": "invalid_input",
            "confidence": 1.0,
            "reason": "numeric_only",
            "source": source,
            "route": "stop",
            "flags": ["invalid_chars_only", "numeric_only_input"],
        }

    if not cleaned:
        if _is_noise_like(raw):
            return {
                "classification": "noise_input",
                "confidence": 0.99,
                "reason": "noise_only_tokens",
                "source": source,
                "route": "stop",
                "flags": ["noise_input", "no_content_after_cleaning"],
            }
        return {
            "classification": "empty_input",
            "confidence": 1.0,
            "reason": "cleaned_text_empty",
            "source": source,
            "route": "stop",
            "flags": ["no_content_after_cleaning"],
        }

    if _is_empty_or_silence(cleaned):
        if _is_noise_like(raw):
            return {
                "classification": "noise_input",
                "confidence": 0.99,
                "reason": "noise_only_tokens",
                "source": source,
                "route": "stop",
                "flags": ["noise_input", "no_content_after_cleaning"],
            }
        label = "no_speech_detected" if source == "audio" else "empty_input"
        return {
            "classification": label,
            "confidence": 0.99,
            "reason": "no_meaningful_tokens_detected",
            "source": source,
            "route": "stop",
            "flags": ["no_content_after_cleaning"],
        }

    if _is_numeric_only(cleaned):
        return {
            "classification": "invalid_input",
            "confidence": 1.0,
            "reason": "numeric_only",
            "source": source,
            "route": "stop",
            "flags": ["invalid_chars_only", "numeric_only_input"],
        }

    if _is_noise_like(cleaned):
        return {
            "classification": "noise_input",
            "confidence": 0.97,
            "reason": "noise_only_tokens",
            "source": source,
            "route": "stop",
            "flags": ["noise_input"],
        }

    if any(re.search(pattern, lowered) for pattern in _CONVERSATIONAL_PATTERNS):
        return {
            "classification": "conversational",
            "confidence": 0.95,
            "reason": "conversational_pattern_detected",
            "source": source,
            "route": "stop",
            "flags": ["non_analytical"],
        }

    if any(re.search(pattern, lowered) for pattern in _FORECAST_PATTERNS):
        return {
            "classification": "forecast",
            "confidence": 0.9,
            "reason": "forecast_pattern_detected",
            "source": source,
            "route": "proceed",
            "flags": ["analytical"],
        }

    if any(_contains_hint(lowered, token) for token in _ANALYTICAL_HINTS):
        return {
            "classification": "analytical",
            "confidence": 0.88,
            "reason": "analytical_keywords_detected",
            "source": source,
            "route": "proceed",
            "flags": ["analytical"],
        }

    return {
        "classification": "conversational",
        "confidence": 0.55,
        "reason": "no_analytical_signals_detected",
        "source": source,
        "route": "stop",
        "flags": ["low_confidence_default"],
    }
