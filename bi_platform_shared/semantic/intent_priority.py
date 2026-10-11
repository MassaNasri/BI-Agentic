"""
Weighted BI intent scoring and conflict resolution (dataset-agnostic).

Used by chart selection and optionally merged into analytical IR traces so
temporal / time-series semantics consistently dominate generic compare / pair
semantics unless explicit correlation language is present.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

# Explicit correlation / scatter semantics — relationship wins over temporal.
_EXPLICIT_CORRELATION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, flags=re.IGNORECASE)
    for p in (
        r"\brelationship\s+between\b",
        r"\bcorrelation\s+between\b",
        r"\bcorrelat(?:e|ed|es|ing)\s+with\b",
        r"\bcorrelation\s+with\b",
        r"\bassociated\s+with\b",
        r"\bassociation\s+between\b",
        r"\bscatter(?:\s+plot)?\b",
        r"\bjoint\s+distribution\b",
        r"\bhow\s+.+?\s+correlat",
    )
)


def explicit_correlation_language(question: str) -> bool:
    text = str(question or "").strip()
    if not text:
        return False
    return any(p.search(text) for p in _EXPLICIT_CORRELATION_PATTERNS)


# phrase -> weight (arbitrary scale; normalized later)
_TEMPORAL_SIGNALS: tuple[tuple[str, float], ...] = (
    ("over time", 3.2),
    ("through time", 3.0),
    ("across time", 3.0),
    ("time series", 3.0),
    ("timeline", 2.6),
    ("over the last", 2.2),
    ("over the past", 2.2),
    ("during the last", 2.2),
    ("during the past", 2.2),
    ("across months", 2.4),
    ("across years", 2.4),
    ("across weeks", 2.4),
    ("across days", 2.4),
    ("month over month", 2.5),
    ("year over year", 2.5),
    ("week over week", 2.5),
    ("day over day", 2.5),
    ("growth over time", 3.0),
    ("trend over time", 3.0),
    ("historical", 1.8),
    ("by month", 2.4),
    ("by day", 2.4),
    ("by week", 2.4),
    ("by quarter", 2.4),
    ("by year", 2.4),
    ("by hour", 2.2),
    ("per month", 2.2),
    ("per day", 2.2),
    ("per week", 2.2),
    ("per quarter", 2.2),
    ("per year", 2.2),
    ("grouped by month", 2.4),
    ("grouped by day", 2.4),
    ("grouped by week", 2.4),
    ("grouped by quarter", 2.4),
    ("grouped by year", 2.4),
    ("for each month", 2.2),
    ("for each day", 2.2),
    ("for each week", 2.2),
    ("in each month", 2.2),
    ("each month", 2.0),
    ("each day", 2.0),
    ("each week", 2.0),
    ("monthly", 1.8),
    ("daily", 1.8),
    ("weekly", 1.8),
    ("quarterly", 1.8),
    ("yearly", 1.8),
    ("hourly", 1.6),
    ("annually", 1.8),
    ("over years", 2.4),
    ("over months", 2.4),
    ("over weeks", 2.2),
    ("over quarters", 2.4),
    ("historical", 1.8),
)

_TEMPORAL_REGEX = re.compile(
    r"\b(?:trend|trends|growth|increase|decrease|seasonality|evolution|historical|timeline)\b",
    flags=re.IGNORECASE,
)

_TEMPORAL_BUCKET_REGEX = re.compile(
    r"\b(?:what|which)\s+(?:hour|hours|day|days|week|weeks|month|months|quarter|quarters|year|years)\b"
    r"|"
    r"\b(?:hour|hours|day|days|week|weeks|month|months|quarter|quarters|year|years)\s+"
    r"(?:generated|produced|recorded|experienced|had)\b",
    flags=re.IGNORECASE,
)

_TEMPORAL_GROUPING_REGEX = re.compile(
    r"\b(?:by|per|group(?:ed)?\s+by|for\s+each|in\s+each)\s+"
    r"(?:hour|day|week|month|quarter|year)s?\b"
    r"|"
    r"\b(?:hourly|daily|weekly|monthly|quarterly|yearly|annually)\b"
    r"|"
    r"\bover\s+time\b"
    r"|"
    r"\btime\s+series\b"
    r"|"
    r"\btimeline\b",
    flags=re.IGNORECASE,
)

# Generic dual-metric comparison (scatter risk) without explicit correlation wording.
_COMPARE_TWO_SIDED = re.compile(
    r"\bcompare\s+.+?\s+(?:and|with|to|against|vs\.?|versus)\s+.+",
    flags=re.IGNORECASE | re.DOTALL,
)
_TWO_SIDED_VS = re.compile(r".+\b(?:vs\.?|versus)\s+.+", flags=re.IGNORECASE | re.DOTALL)

_RELATIONSHIP_LEX = (
    "relationship",
    "correlation",
    "associate",
    "association",
    "impact",
    "effect",
    "influence",
)


def _raw_temporal_score(lowered: str) -> float:
    score = 0.0
    for phrase, weight in sorted(_TEMPORAL_SIGNALS, key=lambda x: len(x[0]), reverse=True):
        if phrase in lowered:
            score += weight
    if _TEMPORAL_REGEX.search(lowered):
        score += 1.2
    if _TEMPORAL_BUCKET_REGEX.search(lowered):
        score += 2.2
    return score


def _temporal_dominance_enforced(lowered: str, *, raw_temporal: float, explicit_corr: bool) -> bool:
    if explicit_corr:
        return False
    if _TEMPORAL_GROUPING_REGEX.search(lowered):
        return True
    if _TEMPORAL_BUCKET_REGEX.search(lowered):
        return True
    return raw_temporal >= 2.0


def _raw_relationship_score(lowered: str) -> float:
    score = 0.0
    if explicit_correlation_language(lowered):
        score += 6.0
    if _COMPARE_TWO_SIDED.search(lowered) or _TWO_SIDED_VS.search(lowered):
        score += 2.0
    padded = f" {lowered} "
    for kw in _RELATIONSHIP_LEX:
        if f" {kw} " in padded:
            score += 1.5
    return score


def _softmax_normalize(raw: dict[str, float]) -> dict[str, float]:
    if not raw:
        return {}
    m = max(raw.values())
    if m <= 0:
        return {k: 0.0 for k in raw}
    exp_vals = {k: math.exp((v - m) / max(m, 1.0)) for k, v in raw.items()}
    s = sum(exp_vals.values()) or 1.0
    return {k: round(v / s, 4) for k, v in exp_vals.items()}


def build_intent_priority_payload(question: str) -> dict[str, Any]:
    """
    Structured intent scores in [0, 1] (sum not necessarily 1; softmax-normalized
    scores stored under intent_priority_normalized).
    """
    q = str(question or "").strip()
    lowered = q.lower()
    explicit_corr = explicit_correlation_language(q)
    raw_temporal = _raw_temporal_score(lowered)
    raw_rel = _raw_relationship_score(lowered)
    temporal_dominance = _temporal_dominance_enforced(
        lowered,
        raw_temporal=raw_temporal,
        explicit_corr=explicit_corr,
    )
    # Deterministic conflict resolution:
    # temporal grouping language should dominate generic compare semantics unless
    # explicit correlation/scatter language is present.
    if temporal_dominance:
        raw_temporal += 1.0
        raw_rel *= 0.22
    elif raw_temporal >= 4.0 and not explicit_corr:
        raw_rel *= 0.35
    raw_scores = {
        "time_series": raw_temporal,
        "relationship": raw_rel,
    }
    normalized = _softmax_normalize(raw_scores)
    if not normalized or all(value <= 0.0 for value in normalized.values()):
        dominant = "none"
    else:
        dominant = max(normalized, key=normalized.get)
    suppress_relationship = bool(
        not explicit_corr
        and (
            temporal_dominance
            or (
                normalized.get("time_series", 0.0) > normalized.get("relationship", 0.0)
                and raw_temporal >= 1.2
            )
        )
    )
    return {
        "intent_priority": {
            "time_series": float(normalized.get("time_series", 0.0)),
            "relationship": float(normalized.get("relationship", 0.0)),
        },
        "intent_priority_raw": raw_scores,
        "dominant_intent": dominant,
        "explicit_correlation": explicit_corr,
        "temporal_dominance_enforced": temporal_dominance,
        "suppress_relationship_scatter": suppress_relationship,
    }


def resolve_chart_semantics(question: str, intent_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """
    Merge NL-derived priority with structured intent hints already on the payload
    (time_grouping_detected, time_granularity, analysis_mode).
    """
    payload = intent_payload if isinstance(intent_payload, Mapping) else {}
    q_text = str(question or payload.get("raw_question") or "").strip()
    base = build_intent_priority_payload(q_text)

    boost_ts = 0.0
    if bool(payload.get("time_grouping_detected")):
        boost_ts += 0.12
    tg = str(payload.get("time_granularity") or "").strip().lower()
    if tg in {"hour", "day", "week", "month", "quarter", "year"}:
        boost_ts += 0.08
    if str(payload.get("intent") or "").strip().lower() == "time_series":
        boost_ts += 0.1
    ops = {str(o).strip().lower() for o in (payload.get("operations") or []) if str(o).strip()}
    if "time_grouping" in ops:
        boost_ts += 0.08

    if boost_ts:
        ip = dict(base["intent_priority"])
        ip["time_series"] = min(1.0, ip.get("time_series", 0.0) + boost_ts)
        # Re-softmax the two headline families for trace readability.
        ip = _softmax_normalize({"time_series": ip["time_series"], "relationship": ip.get("relationship", 0.0)})
        base["intent_priority"] = {
            "time_series": float(ip.get("time_series", 0.0)),
            "relationship": float(ip.get("relationship", 0.0)),
        }
        base["dominant_intent"] = max(base["intent_priority"], key=base["intent_priority"].get)

    analysis_mode = str(payload.get("analysis_mode") or "").strip().lower()
    if analysis_mode == "relationship" and base.get("suppress_relationship_scatter"):
        base["analysis_mode_override"] = ""
    base["suppress_relationship_scatter"] = bool(
        base.get("suppress_relationship_scatter")
        or (
            not base.get("explicit_correlation")
            and str(base.get("dominant_intent") or "") == "time_series"
            and base["intent_priority"].get("time_series", 0) > base["intent_priority"].get("relationship", 0)
        )
    )
    return base


__all__ = [
    "build_intent_priority_payload",
    "explicit_correlation_language",
    "resolve_chart_semantics",
]
