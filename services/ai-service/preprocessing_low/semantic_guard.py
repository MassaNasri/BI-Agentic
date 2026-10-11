from __future__ import annotations

import re
from typing import Any


_WORD_PATTERN = re.compile(r"\b[\w']+\b", flags=re.UNICODE)
_SPACE_PATTERN = re.compile(r"\s+")


PROTECTED_SEMANTIC_PHRASES = {
    "metrics": [
        "total sales",
        "order count",
        "number of orders",
        "average order count",
    ],
    "temporal": [
        "over time",
        "by day",
        "by date",
        "by week",
        "by month",
        "by quarter",
        "by year",
        "last week",
        "last month",
        "last year",
        "next week",
        "next month",
        "next 30 days",
        "forecast horizon",
    ],
    "grouping": [
        "grouped by",
        "for each",
        "for every",
        "order by",
    ],
    "comparison": [
        "compared to",
        "relationship between",
    ],
    "filters": [
        "greater than",
        "more than",
        "at least",
        "less than",
        "equal to",
        "not equal to",
    ],
}

PROTECTED_SEMANTIC_TERMS = {
    "sales",
    "revenue",
    "orders",
    "order",
    "customers",
    "customer",
    "profit",
    "quantity",
    "count",
    "average",
    "avg",
    "sum",
    "total",
    "value",
    "price",
    "amount",
    "day",
    "days",
    "date",
    "dates",
    "week",
    "weeks",
    "month",
    "months",
    "quarter",
    "quarters",
    "year",
    "years",
    "daily",
    "weekly",
    "monthly",
    "yearly",
    "future",
    "by",
    "per",
    "each",
    "across",
    "over",
    "distribution",
    "distributed",
    "percentage",
    "percent",
    "share",
    "ratio",
    "compare",
    "compared",
    "comparison",
    "versus",
    "vs",
    "between",
    "relationship",
    "correlation",
    "trend",
    "growth",
    "change",
    "top",
    "bottom",
    "highest",
    "lowest",
    "maximum",
    "minimum",
    "best",
    "worst",
    "rank",
    "exceeded",
    "exceeds",
    "above",
    "below",
    "under",
    "before",
    "after",
    "from",
    "to",
    "predict",
    "forecast",
    "next",
    "expected",
    "estimate",
    "projection",
    "upcoming",
    "chart",
    "graph",
    "plot",
    "line",
    "bar",
    "pie",
    "scatter",
    "histogram",
}

FILTER_OPERATOR_MAP = {
    "exceeded": ">",
    "exceeds": ">",
    "greater than": ">",
    "more than": ">",
    "above": ">",
    "at least": ">=",
    "less than": "<",
    "below": "<",
    "under": "<",
    "equal to": "=",
    "between": "BETWEEN",
}

_DYNAMIC_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("ranking", "top_n", re.compile(r"\btop\s+\d+\b", flags=re.IGNORECASE)),
    ("ranking", "bottom_n", re.compile(r"\bbottom\s+\d+\b", flags=re.IGNORECASE)),
    (
        "temporal",
        "next_n_periods",
        re.compile(r"\bnext\s+\d+\s+(?:day|days|week|weeks|month|months|quarter|quarters|year|years)\b", flags=re.IGNORECASE),
    ),
    (
        "temporal",
        "last_n_periods",
        re.compile(r"\blast\s+\d+\s+(?:day|days|week|weeks|month|months|quarter|quarters|year|years)\b", flags=re.IGNORECASE),
    ),
    (
        "filters",
        "date_range",
        re.compile(r"\bfrom\s+[a-zA-Z0-9_ -]+\s+to\s+[a-zA-Z0-9_ -]+\b", flags=re.IGNORECASE),
    ),
)


def normalize_for_semantic_compare(text: str) -> str:
    normalized = str(text or "").lower()
    normalized = re.sub(r"[_-]+", " ", normalized)
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return _SPACE_PATTERN.sub(" ", normalized).strip()


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = normalize_for_semantic_compare(phrase)
    return bool(re.search(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", normalized_text))


def _append_unique(items: list[dict[str, str]], item: dict[str, str], seen: set[tuple[str, str]]) -> None:
    signature = (item["term"].lower(), item.get("category", ""))
    if signature in seen:
        return
    seen.add(signature)
    items.append(item)


def extract_semantic_terms(text: str) -> list[dict[str, str]]:
    normalized = normalize_for_semantic_compare(text)
    if not normalized:
        return []

    terms: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for category, phrases in PROTECTED_SEMANTIC_PHRASES.items():
        for phrase in phrases:
            if _contains_phrase(normalized, phrase):
                _append_unique(terms, {"term": normalize_for_semantic_compare(phrase), "category": category, "type": "phrase"}, seen)

    for category, name, pattern in _DYNAMIC_PATTERNS:
        for match in pattern.finditer(str(text or "")):
            term = normalize_for_semantic_compare(match.group(0))
            if term:
                _append_unique(terms, {"term": term, "category": category, "type": name}, seen)

    for match in _WORD_PATTERN.finditer(normalized):
        token = match.group(0).lower()
        if token in PROTECTED_SEMANTIC_TERMS or token.isdigit():
            category = "numeric_constraint" if token.isdigit() else "semantic_token"
            _append_unique(terms, {"term": token, "category": category, "type": "token"}, seen)

    return terms


def extract_filter_operators(text: str) -> list[dict[str, str]]:
    normalized = normalize_for_semantic_compare(text)
    operators: list[dict[str, str]] = []
    seen: set[str] = set()
    for phrase, operator in FILTER_OPERATOR_MAP.items():
        if not _contains_phrase(normalized, phrase):
            continue
        if phrase in seen:
            continue
        seen.add(phrase)
        operators.append({"term": phrase, "operator": operator})
    return operators


def find_missing_semantic_terms(original_text: str, cleaned_text: str) -> list[str]:
    cleaned_normalized = normalize_for_semantic_compare(cleaned_text)
    missing: list[str] = []
    for item in extract_semantic_terms(original_text):
        term = item["term"]
        if not _contains_phrase(cleaned_normalized, term):
            missing.append(term)
    return missing


def semantic_metadata(original_text: str, cleaned_text: str) -> dict[str, Any]:
    missing_terms = find_missing_semantic_terms(original_text, cleaned_text)
    return {
        "semantic_terms_original": extract_semantic_terms(original_text),
        "semantic_terms_cleaned": extract_semantic_terms(cleaned_text),
        "preserved_terms": [item["term"] for item in extract_semantic_terms(original_text) if item["term"] not in missing_terms],
        "missing_semantic_terms": missing_terms,
        "filter_operators": extract_filter_operators(original_text),
        "semantic_preservation_passed": not missing_terms,
    }


def validate_semantic_preservation(original_text: str, cleaned_text: str) -> dict[str, Any]:
    metadata = semantic_metadata(original_text, cleaned_text)
    return {
        "is_valid": bool(metadata["semantic_preservation_passed"]),
        "missing_terms": metadata["missing_semantic_terms"],
        "metadata": metadata,
    }
