"""
Reusable temporal intent, grouping, and relationship-vs-time-series arbitration
for BI NL → structured intent. Dataset-agnostic; uses phrases and patterns, not
fixed metric names.
"""

from __future__ import annotations

import re
from typing import Any

# --- Explicit correlation / scatter semantics (relationship wins over temporal) ---
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


_EXPLICIT_TEMPORAL_PHRASES: tuple[str, ...] = (
    "over time", "across time", "through time", "time series",
    "by day", "by month", "by week", "by quarter", "by year", "by hour",
    "per day", "per month", "per week", "per quarter", "per year",
    "daily", "weekly", "monthly", "quarterly", "yearly", "annually",
    "hourly", "timeline",
)

_EXPLICIT_TEMPORAL_PHRASE_REGEX = re.compile(
    r"\b(?:trend|trends|time[\s_]series)\b", flags=re.IGNORECASE,
)


def has_explicit_temporal_phrase(question: str) -> bool:
    """True when the question contains any unambiguous temporal-analysis phrase."""
    lowered = str(question or "").strip().lower()
    if not lowered:
        return False
    normalized_ws = re.sub(r"\s+", " ", lowered).strip()
    if any(phrase in normalized_ws for phrase in _EXPLICIT_TEMPORAL_PHRASES):
        return True
    if re.search(r"\bover\s+time\b|\bthrough\s+time\b|\bacross\s+time\b", lowered):
        return True
    return bool(_EXPLICIT_TEMPORAL_PHRASE_REGEX.search(lowered))


# phrase -> (granularity or "", weight for temporal-vs-relationship scoring)
_TEMPORAL_SIGNALS: tuple[tuple[str, str, int], ...] = (
    ("over time", "day", 12),
    ("through time", "day", 12),
    ("across time", "day", 12),
    ("time series", "day", 12),
    ("timeline", "day", 10),
    ("over the last", "day", 8),
    ("over the past", "day", 8),
    ("during the last", "day", 8),
    ("during the past", "day", 8),
    ("across months", "month", 9),
    ("across years", "year", 9),
    ("across weeks", "week", 9),
    ("across days", "day", 9),
    ("month over month", "month", 9),
    ("year over year", "year", 9),
    ("week over week", "week", 9),
    ("day over day", "day", 9),
    ("growth over time", "day", 11),
    ("trend over time", "day", 11),
    ("historical", "day", 7),
    ("over years", "year", 8),
    ("over months", "month", 8),
    ("over weeks", "week", 8),
    ("over quarters", "quarter", 8),
    ("by month", "month", 8),
    ("by day", "day", 8),
    ("by week", "week", 8),
    ("by quarter", "quarter", 8),
    ("by year", "year", 8),
    ("by hour", "hour", 8),
    ("per month", "month", 8),
    ("per day", "day", 8),
    ("per week", "week", 8),
    ("per quarter", "quarter", 8),
    ("per year", "year", 8),
    ("grouped by month", "month", 8),
    ("grouped by day", "day", 8),
    ("grouped by week", "week", 8),
    ("grouped by quarter", "quarter", 8),
    ("grouped by year", "year", 8),
    ("for each month", "month", 8),
    ("for each day", "day", 8),
    ("for each week", "week", 8),
    ("in each month", "month", 8),
    ("each month", "month", 7),
    ("each day", "day", 7),
    ("each week", "week", 7),
    ("monthly", "month", 6),
    ("daily", "day", 6),
    ("weekly", "week", 6),
    ("quarterly", "quarter", 6),
    ("yearly", "year", 6),
    ("hourly", "hour", 6),
    ("annually", "year", 6),
    (r"\btrend\b", "day", 5),
    (r"\bgrowth\b", "", 4),
    (r"\bevolution\b", "day", 4),
    (r"\bseasonality\b", "month", 5),
    (r"\b(?:what|which)\s+(?:hour|hours|day|days|week|weeks|month|months|quarter|quarters|year|years)\b", "day", 8),
    (
        r"\b(?:hour|hours|day|days|week|weeks|month|months|quarter|quarters|year|years)\s+"
        r"(?:generated|produced|showed|recorded|experienced|had)\b",
        "day",
        8,
    ),
    (
        r"\b(?:best|worst|highest|lowest|top|bottom)\s+performing\s+"
        r"(?:hour|hours|day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
        "day",
        8,
    ),
)

# Compiled weak signals (single regex check)
_WEAK_TEMPORAL_REGEX = re.compile(
    r"\b(?:"
    r"over\s+time|through\s+time|across\s+time|time\s+series|timeline|"
    r"monthly|daily|weekly|quarterly|yearly|hourly|annually|"
    r"trend|growth|seasonality|historical|timeline"
    r")\b",
    flags=re.IGNORECASE,
)

# Two-sided comparison without explicit correlation language (scatter risk)
_COMPARE_TWO_SIDED = re.compile(
    r"\bcompare\s+.+?\s+(?:and|with|to|against|vs\.?|versus)\s+.+",
    flags=re.IGNORECASE | re.DOTALL,
)
_TWO_SIDED_VS = re.compile(r".+\b(?:vs\.?|versus)\s+.+", flags=re.IGNORECASE | re.DOTALL)


def temporal_intent_score(question: str) -> int:
    lowered = str(question or "").strip().lower()
    if not lowered:
        return 0
    score = 0
    for phrase, _grain, weight in _TEMPORAL_SIGNALS:
        if phrase.startswith("\\"):
            if re.search(phrase, lowered):
                score += weight
        elif phrase in lowered:
            score += weight
    if _WEAK_TEMPORAL_REGEX.search(lowered):
        score += 2
    return score


def temporal_priority_over_relationship(question: str) -> bool:
    """
    True when temporal semantics should suppress generic compare→scatter routing.
    """
    if explicit_correlation_language(question):
        return False
    return temporal_intent_score(question) >= 5


def infer_nl_time_granularity(question: str) -> str:
    """
    Best-effort grain from NL (empty string if none). Stronger / longer phrases first.
    """
    lowered = str(question or "").strip().lower()
    if not lowered:
        return ""

    bucket_word_to_grain = {
        "hour": "hour",
        "hours": "hour",
        "day": "day",
        "days": "day",
        "date": "day",
        "week": "week",
        "weeks": "week",
        "month": "month",
        "months": "month",
        "quarter": "quarter",
        "quarters": "quarter",
        "year": "year",
        "years": "year",
    }

    bucket_match = re.search(
        r"\b(?:what|which)\s+(hour|hours|day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
        lowered,
    )
    if bucket_match:
        return bucket_word_to_grain.get(bucket_match.group(1).lower(), "")

    generated_match = re.search(
        r"\b(hour|hours|day|days|week|weeks|month|months|quarter|quarters|year|years)\s+"
        r"(?:generated|produced|showed|recorded|experienced|had)\b",
        lowered,
    )
    if generated_match:
        return bucket_word_to_grain.get(generated_match.group(1).lower(), "")

    performing_match = re.search(
        r"\b(?:best|worst|highest|lowest|top|bottom)\s+performing\s+"
        r"(hour|hours|day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
        lowered,
    )
    if performing_match:
        return bucket_word_to_grain.get(performing_match.group(1).lower(), "")

    best_grain = ""
    best_rank = -1
    ordered = sorted(_TEMPORAL_SIGNALS, key=lambda x: len(x[0]), reverse=True)
    for phrase, grain, weight in ordered:
        if phrase.startswith("\\"):
            if re.search(phrase, lowered) and weight > best_rank:
                best_rank = weight
                if grain:
                    best_grain = grain
            continue
        if phrase in lowered and weight > best_rank:
            best_rank = weight
            if grain:
                best_grain = grain
    if best_grain:
        return best_grain
    if re.search(r"\b(?:by|per|grouped by)\s+date\b", lowered):
        return "day"
    if re.search(r"\b(?:by|per|grouped by)\s+time\b", lowered):
        return "hour"
    if best_rank > 0 and _WEAK_TEMPORAL_REGEX.search(lowered):
        return "day"
    return ""


def build_grouping_metadata(question: str, *, time_granularity: str) -> dict[str, Any]:
    grain = str(time_granularity or "").strip().lower() or infer_nl_time_granularity(question)
    required = bool(grain)
    return {
        "time_unit": grain or None,
        "time_grain": grain or None,
        "group_by_required": required,
        "required": required,
        "source": "nl_temporal_semantics" if grain else "none",
    }


def analyze_temporal_intent(question: str) -> dict[str, Any]:
    q = str(question or "").strip()
    ql = q.lower()
    explicit_corr = explicit_correlation_language(q)
    score = temporal_intent_score(q)
    grain = infer_nl_time_granularity(q)
    temporal_dom = temporal_priority_over_relationship(q)
    if explicit_corr:
        family = "relationship"
    elif temporal_dom or bool(grain):
        family = "time_series"
    elif _COMPARE_TWO_SIDED.search(ql) or _TWO_SIDED_VS.search(ql):
        family = "relationship"
    else:
        family = "none"
    return {
        "intent_family": family,
        "temporal_strength": score,
        "explicit_correlation": explicit_corr,
        "temporal_priority_over_relationship": temporal_dom,
        "suggested_granularity": grain or None,
        "grouping": build_grouping_metadata(q, time_granularity=grain or ""),
    }


def should_treat_as_relationship_scatter(question: str) -> bool:
    """
    Scatter / dual-metric correlation path — only when not temporally dominant
    and (explicit correlation or classic two-sided compare).
    """
    ql = str(question or "").strip().lower()
    if not ql:
        return False
    if explicit_correlation_language(question):
        return True
    if temporal_priority_over_relationship(question):
        return False
    if _COMPARE_TWO_SIDED.search(ql) or _TWO_SIDED_VS.search(ql):
        return True
    # Other relationship keywords (impact, effect) without temporal dominance
    weak_rel = (
        "relationship",
        "correlation",
        "associate",
        "association",
        "impact",
        "effect",
        "influence",
    )
    if any(f" {k} " in f" {ql} " for k in weak_rel):
        return True
    return False


# --- Composite: superlative ranking among time buckets (e.g. best month by sales) ---
_BUCKET_WORD_TO_GRAIN = {
    "hour": "hour",
    "hours": "hour",
    "day": "day",
    "days": "day",
    "date": "day",
    "week": "week",
    "weeks": "week",
    "month": "month",
    "months": "month",
    "quarter": "quarter",
    "quarters": "quarter",
    "year": "year",
    "years": "year",
}


def detect_composite_temporal_superlative(question: str) -> dict[str, Any]:
    """
    Detect rank-among-time-buckets intent (highest month, top quarter by revenue).
    """
    ql = str(question or "").strip().lower()
    if not ql:
        return {"active": False, "time_granularity": "", "ranking_direction": None}

    direction = None
    if re.search(
        r"\b(?:highest|largest|most|top|maximum|max|best|greatest|biggest|peak)\b",
        ql,
    ):
        direction = "DESC"
    elif re.search(
        r"\b(?:lowest|smallest|least|bottom|minimum|min|worst|weakest)\b",
        ql,
    ):
        direction = "ASC"

    grain = ""
    # what/which <grain> ... superlative
    m = re.search(
        r"\b(?:what|which)\s+(hour|hours|day|days|date|week|weeks|month|months|quarter|quarters|year|years)\b",
        ql,
    )
    if m:
        grain = _BUCKET_WORD_TO_GRAIN.get(m.group(1).lower(), "")
    # superlative ... <grain>
    if not grain and direction:
        m2 = re.search(
            r"\b(?:highest|lowest|largest|smallest|best|worst|top|bottom|maximum|minimum|peak)\b"
            r"[\w\s]{0,160}?\b(hour|hours|day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
            ql,
        )
        if m2:
            grain = _BUCKET_WORD_TO_GRAIN.get(m2.group(1).lower(), "")
    if not grain and direction:
        m5 = re.search(
            r"\b(month|months|quarter|quarters|day|days|week|weeks|year|years)\s+"
            r"(?:generated|produced|saw|had|showed|recorded|experienced)\s+"
            r"(?:the\s+)?(?:highest|lowest|largest|smallest|best|worst|most|least|maximum|minimum|peak)\b",
            ql,
        )
        if m5:
            grain = _BUCKET_WORD_TO_GRAIN.get(m5.group(1).lower(), "")
    if not grain and direction:
        m6 = re.search(
            r"\b(?:highest|lowest|largest|smallest|best|worst|top|bottom|maximum|minimum|peak)\b"
            r"[\w\s]{0,140}?\b(month|months|day|days|week|weeks|quarter|quarters|year|years)\b",
            ql,
        )
        if m6:
            grain = _BUCKET_WORD_TO_GRAIN.get(m6.group(1).lower(), "")
    if not grain and direction:
        m4 = re.search(
            r"\b(?:best|worst)\s+performing\s+(hour|hours|day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
            ql,
        )
        if m4:
            grain = _BUCKET_WORD_TO_GRAIN.get(m4.group(1).lower(), "")
    # top <grain> by
    if not grain and re.search(r"\btop\s+(month|months|day|days|week|weeks|quarter|quarters|year|years)\s+by\b", ql):
        m3 = re.search(
            r"\btop\s+(month|months|day|days|week|weeks|quarter|quarters|year|years)\s+by\b",
            ql,
        )
        if m3:
            grain = _BUCKET_WORD_TO_GRAIN.get(m3.group(1).lower(), "")

    active = bool(direction and grain)
    return {
        "active": active,
        "time_granularity": grain,
        "ranking_direction": direction,
    }


def metric_lexical_variants(token: str) -> set[str]:
    """BI-safe singular/plural variants for a single identifier token (not global stemming)."""
    t = str(token or "").strip().lower()
    if not t:
        return set()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", t):
        return {t}
    out: set[str] = {t}
    if len(t) > 3 and t.endswith("ies") and len(t) > 4 and t[-4] not in "aeiou":
        out.add(t[:-3] + "y")
    if len(t) > 2 and t.endswith("s") and not t.endswith(("ss", "us", "is", "ous")):
        stem = t[:-1]
        if stem:
            out.add(stem)
    if len(t) > 2 and not t.endswith("s"):
        out.add(t + "s")
        if t.endswith("y") and t[-2] not in "aeiou":
            out.add(t[:-1] + "ies")
        elif t.endswith(("ch", "sh", "x", "z")):
            out.add(t + "es")
    return {x for x in out if len(x) > 1}
