"""
Domain-agnostic BI natural-language semantics: filter operators, verb stems,
and multi-metric conjunction hints. Used by preprocessing diagnostics, intent
normalization, and SQL planning — not tied to any single dataset or question.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# --- Natural-language filter phrases → canonical SQL-style operators (longest first) ---
_FILTER_PHRASE_OPERATOR: list[tuple[str, str]] = [
    ("not equal to", "!="),
    ("no less than", ">="),
    ("no more than", "<="),
    ("greater than", ">"),
    ("less than", "<"),
    ("equal to", "="),
    ("not equals", "!="),
    ("more than", ">"),
    ("at least", ">="),
    ("at most", "<="),
    ("fewer than", "<"),
    ("higher than", ">"),
    ("lower than", "<"),
    ("exceeded", ">"),
    ("exceeds", ">"),
    ("exceeding", ">"),
    ("equals", "="),
    ("below", "<"),
    ("above", ">"),
    ("under", "<"),
    ("over", ">"),
]

# Phrases whose tokens should be ignored for schema residual diagnostics when matched in-query.
_ANALYTICAL_SEMANTIC_VOCAB: dict[str, dict[str, Any]] = {
    "growth": {
        "semantic_meaning": "trend_change",
        "operations": ("aggregation", "comparison", "time_grouping"),
    },
    "trend": {
        "semantic_meaning": "time_series",
        "operations": ("aggregation", "time_grouping"),
    },
    "trends": {
        "semantic_meaning": "time_series",
        "operations": ("aggregation", "time_grouping"),
    },
    "increase": {
        "semantic_meaning": "positive_change",
        "operations": ("comparison", "time_grouping"),
    },
    "increases": {
        "semantic_meaning": "positive_change",
        "operations": ("comparison", "time_grouping"),
    },
    "increasing": {
        "semantic_meaning": "positive_change",
        "operations": ("comparison", "time_grouping"),
    },
    "decrease": {
        "semantic_meaning": "negative_change",
        "operations": ("comparison", "time_grouping"),
    },
    "decreases": {
        "semantic_meaning": "negative_change",
        "operations": ("comparison", "time_grouping"),
    },
    "decreasing": {
        "semantic_meaning": "negative_change",
        "operations": ("comparison", "time_grouping"),
    },
    "generated": {
        "semantic_meaning": "aggregation_contribution",
        "operations": ("aggregation", "grouping"),
    },
    "generates": {
        "semantic_meaning": "aggregation_contribution",
        "operations": ("aggregation", "grouping"),
    },
    "produced": {
        "semantic_meaning": "aggregation_contribution",
        "operations": ("aggregation", "grouping"),
    },
    "produces": {
        "semantic_meaning": "aggregation_contribution",
        "operations": ("aggregation", "grouping"),
    },
    "performing": {
        "semantic_meaning": "ranking_performance",
        "operations": ("ranking", "grouping"),
    },
    "best performing": {
        "semantic_meaning": "ranking_desc",
        "operations": ("ranking", "grouping", "limiting"),
    },
    "worst performing": {
        "semantic_meaning": "ranking_asc",
        "operations": ("ranking", "grouping", "limiting"),
    },
    "highest": {
        "semantic_meaning": "ranking_desc",
        "operations": ("ranking", "limiting"),
    },
    "top": {
        "semantic_meaning": "ranking_desc",
        "operations": ("ranking", "limiting"),
    },
    "best": {
        "semantic_meaning": "ranking_desc",
        "operations": ("ranking", "limiting"),
    },
    "largest": {
        "semantic_meaning": "ranking_desc",
        "operations": ("ranking", "limiting"),
    },
    "maximum": {
        "semantic_meaning": "ranking_desc",
        "operations": ("ranking", "limiting"),
    },
    "lowest": {
        "semantic_meaning": "ranking_asc",
        "operations": ("ranking", "limiting"),
    },
    "bottom": {
        "semantic_meaning": "ranking_asc",
        "operations": ("ranking", "limiting"),
    },
    "worst": {
        "semantic_meaning": "ranking_asc",
        "operations": ("ranking", "limiting"),
    },
    "smallest": {
        "semantic_meaning": "ranking_asc",
        "operations": ("ranking", "limiting"),
    },
    "minimum": {
        "semantic_meaning": "ranking_asc",
        "operations": ("ranking", "limiting"),
    },
    "historical": {
        "semantic_meaning": "time_series",
        "operations": ("aggregation", "time_grouping"),
    },
    "timeline": {
        "semantic_meaning": "time_series",
        "operations": ("aggregation", "time_grouping"),
    },
    "over time": {
        "semantic_meaning": "time_series",
        "operations": ("aggregation", "time_grouping"),
    },
    "change": {
        "semantic_meaning": "trend_change",
        "operations": ("comparison", "time_grouping"),
    },
    "changes": {
        "semantic_meaning": "trend_change",
        "operations": ("comparison", "time_grouping"),
    },
    "delta": {
        "semantic_meaning": "trend_change",
        "operations": ("comparison", "time_grouping"),
    },
    "performance": {
        "semantic_meaning": "ranking_performance",
        "operations": ("ranking", "grouping"),
    },
    "ranking": {
        "semantic_meaning": "ranking",
        "operations": ("ranking",),
    },
    "rank": {
        "semantic_meaning": "ranking",
        "operations": ("ranking",),
    },
    "ranked": {
        "semantic_meaning": "ranking",
        "operations": ("ranking",),
    },
    "contribution": {
        "semantic_meaning": "aggregation_contribution",
        "operations": ("aggregation", "grouping"),
    },
    "contributions": {
        "semantic_meaning": "aggregation_contribution",
        "operations": ("aggregation", "grouping"),
    },
}


def _build_analytical_concept_lexicon() -> frozenset[str]:
    base_terms = {
        "growth",
        "trend",
        "trends",
        "increase",
        "increases",
        "increasing",
        "decrease",
        "decreases",
        "decreasing",
        "generated",
        "generates",
        "produced",
        "produces",
        "performing",
        "performance",
        "historical",
        "timeline",
        "change",
        "changes",
        "delta",
        "velocity",
        "momentum",
        "ranking",
        "rank",
        "ranked",
        "superlative",
        "contribution",
        "contributions",
        "highest",
        "lowest",
        "top",
        "bottom",
        "best",
        "worst",
        "largest",
        "smallest",
        "maximum",
        "minimum",
    }
    for phrase in _ANALYTICAL_SEMANTIC_VOCAB:
        for token in re.findall(r"[a-z0-9_]+", phrase.lower()):
            if len(token) > 1:
                base_terms.add(token)
    return frozenset(base_terms)


_ANALYTICAL_CONCEPT_LEXICON: frozenset[str] = _build_analytical_concept_lexicon()


def analytical_concept_tokens() -> frozenset[str]:
    """BI analytical vocabulary — not physical schema columns."""
    return _ANALYTICAL_CONCEPT_LEXICON


_MULTIWORD_OPERATOR_PHRASES: tuple[str, ...] = tuple(
    phrase for phrase, _ in _FILTER_PHRASE_OPERATOR if " " in phrase
)

# Canonical analytics / BI verb roots (extensible; stems are matched algorithmically).
_BI_VERB_ROOTS: frozenset[str] = frozenset(
    {
        "aggregate",
        "bin",
        "break",
        "bucket",
        "chart",
        "compare",
        "compute",
        "correlate",
        "count",
        "decompose",
        "distribute",
        "drill",
        "estimate",
        "evaluate",
        "exceed",
        "explain",
        "explore",
        "filter",
        "fit",
        "forecast",
        "group",
        "inspect",
        "interpolate",
        "join",
        "measure",
        "model",
        "monitor",
        "normalize",
        "parse",
        "pivot",
        "plot",
        "predict",
        "profile",
        "project",
        "query",
        "rank",
        "reconcile",
        "regress",
        "report",
        "rollup",
        "sample",
        "score",
        "segment",
        "slice",
        "smooth",
        "sort",
        "split",
        "summarize",
        "total",
        "track",
        "trend",
        "visualize",
    }
)

_HINT_STOP: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "all",
        "total",
        "overall",
        "sum",
        "average",
        "avg",
        "mean",
        "number",
        "count",
        "each",
        "every",
        "where",
        "when",
        "which",
        "what",
        "how",
        "for",
        "from",
        "to",
        "in",
        "on",
        "of",
        "by",
        "per",
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "year",
        "years",
        "date",
        "time",
        "show",
        "list",
        "display",
        "give",
        "get",
        "me",
        "please",
        "us",
        "our",
        "my",
        "your",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "that",
        "this",
        "those",
        "these",
        "there",
        "here",
        "with",
        "without",
        "into",
        "onto",
        "about",
        "around",
        "across",
        "through",
        "during",
        "before",
        "after",
        "between",
        "among",
        "within",
        "against",
        "alongside",
        "along",
        "versus",
        "vs",
        "and",
        "or",
        "not",
        "no",
        "any",
        "some",
        "few",
        "many",
        "much",
        "more",
        "most",
        "less",
        "least",
        "than",
        "then",
        "also",
        "only",
        "just",
        "both",
        "either",
        "neither",
        "other",
        "another",
        "such",
        "same",
        "different",
        "next",
        "last",
        "first",
        "second",
        "third",
        "new",
        "old",
        "current",
        "previous",
        "future",
        "past",
        "today",
        "yesterday",
        "tomorrow",
        "daily",
        "weekly",
        "monthly",
        "quarterly",
        "yearly",
        "hourly",
        "data",
        "rows",
        "records",
        "values",
        "results",
        "table",
        "dataset",
        "report",
        "dashboard",
        "metric",
        "metrics",
        "dimension",
        "dimensions",
        "field",
        "fields",
        "column",
        "columns",
        "compare",
        "compared",
        "comparing",
        "comparison",
        "trend",
        "trends",
        "pattern",
        "patterns",
        "insight",
        "insights",
        "analysis",
        "analyses",
        "summary",
        "summaries",
        "overview",
        "breakdown",
        "distribution",
        "relationship",
        "relationships",
        "correlation",
        "ranking",
        "rank",
        "compare",
        "compared",
        "comparing",
        "comparison",
    }
)

_CONJUNCTION_SPLIT_RE = re.compile(
    r"\s+(?:,|\band\b|\bvs\.?\b|\bversus\b|\bagainst\b|\balongside\b|\bcompared\s+to\b)\s+",
    flags=re.IGNORECASE,
)

_PREFIX_SCRUB: frozenset[str] = _HINT_STOP | frozenset(
    {
        "show",
        "list",
        "display",
        "give",
        "get",
        "days",
        "day",
        "rows",
        "row",
        "records",
        "record",
        "entries",
        "entry",
        "having",
        "when",
        "while",
        "whose",
    }
)


def _normalize_numeric_value(raw: str) -> int | float:
    text = str(raw or "").strip()
    if "." in text:
        return float(text)
    return int(text)


def extract_semantic_filters(query: str) -> list[dict[str, Any]]:
    """
    Detect natural-language threshold phrases anchored on the operator, then
    infer the nearest metric tokens to the left. Does not rewrite the question.
    """
    text = str(query or "").strip().lower()
    if not text:
        return []

    ordered = sorted(_FILTER_PHRASE_OPERATOR, key=lambda item: len(item[0]), reverse=True)
    matches: list[dict[str, Any]] = []
    consumed: list[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        for a, b in consumed:
            if start < b and end > a:
                return True
        return False

    for phrase, operator in ordered:
        pattern = re.compile(
            rf"\b{re.escape(phrase)}\s+(-?\d+(?:\.\d+)?)\b",
            flags=re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            phrase_start = m.start()
            value_end = m.end()
            if _overlaps(phrase_start, value_end):
                continue
            prefix = text[:phrase_start].rstrip()
            raw_words = re.findall(r"[a-z0-9_]+", prefix)
            words = [w for w in raw_words if w not in _PREFIX_SCRUB and not w.isdigit()]
            left_context = " ".join(words[-6:]) if words else ""
            metric_hint = _metric_hint_tail(left_context)
            value_raw = str(m.group(1) or "").strip()
            if not value_raw:
                continue
            consumed.append((phrase_start, value_end))
            matches.append(
                {
                    "phrase": phrase,
                    "operator": operator,
                    "value": _normalize_numeric_value(value_raw),
                    "metric_hint": metric_hint or left_context,
                    "left_context": left_context,
                }
            )
    return matches


def _metric_hint_tail(left_context: str) -> str:
    tokens = [t for t in re.findall(r"[a-z0-9_]+", str(left_context or "").lower()) if t]
    tail: list[str] = []
    for token in reversed(tokens):
        if token in _HINT_STOP:
            break
        tail.append(token)
        if len(tail) >= 4:
            break
    tail.reverse()
    return " ".join(tail) if tail else str(left_context or "").strip()


def extract_canonical_verbs(query: str) -> list[dict[str, str]]:
    """
    Map inflected BI verbs to canonical roots for internal reasoning; originals
    are preserved for traces.
    """
    text = str(query or "").strip()
    if not text:
        return []

    results: list[dict[str, str]] = []
    seen: set[str] = set()

    for match in re.finditer(r"\b([A-Za-z]{4,})\b", text):
        original = match.group(1)
        lower = original.lower()
        if lower in seen:
            continue
        canonical = _canonicalize_verb_token(lower)
        if not canonical or canonical == lower:
            continue
        seen.add(lower)
        results.append({"original": lower, "canonical": canonical})
    return results


def _canonicalize_verb_token(lower: str) -> str | None:
    if lower in _BI_VERB_ROOTS:
        return None
    if lower.endswith("ies") and len(lower) > 4:
        stem = lower[:-3] + "y"
        if stem in _BI_VERB_ROOTS:
            return stem
    if lower.endswith("ing") and len(lower) > 5:
        stem = lower[:-3]
        if stem in _BI_VERB_ROOTS:
            return stem
        if f"{stem}e" in _BI_VERB_ROOTS:
            return f"{stem}e"
        if len(stem) > 2 and stem[-1] == stem[-2] and stem[:-1] in _BI_VERB_ROOTS:
            return stem[:-1]
    if lower.endswith("ed") and len(lower) > 4:
        stem = lower[:-2]
        if stem in _BI_VERB_ROOTS:
            return stem
        if f"{stem}e" in _BI_VERB_ROOTS:
            return f"{stem}e"
        if len(stem) > 2 and stem[-1] == stem[-2] and stem[:-1] in _BI_VERB_ROOTS:
            return stem[:-1]
    if lower.endswith("es") and len(lower) > 4:
        stem = lower[:-2]
        if stem in _BI_VERB_ROOTS:
            return stem
        if f"{stem}e" in _BI_VERB_ROOTS:
            return f"{stem}e"
    if lower.endswith("s") and len(lower) > 4:
        stem = lower[:-1]
        if stem in _BI_VERB_ROOTS:
            return stem
    return None


def schema_diagnostic_ignore_tokens(query: str) -> set[str]:
    """
    Tokens that must not be treated as unresolved schema references when they
    appear as part of recognized NL filter operators or inflected BI verbs.
    """
    lowered = str(query or "").strip().lower()
    ignored: set[str] = set()
    if not lowered:
        return ignored

    for phrase, _op in _FILTER_PHRASE_OPERATOR:
        if phrase not in lowered:
            continue
        for token in phrase.split():
            token = re.sub(r"[^a-z0-9]+", "", token.lower())
            if token:
                ignored.add(token)

    for item in extract_semantic_filters(query):
        hint = str(item.get("metric_hint") or "").strip().lower()
        for token in re.findall(r"[a-z0-9_]+", hint):
            if token:
                ignored.add(token)

    for mapping in extract_canonical_verbs(query):
        orig = str(mapping.get("original") or "").strip().lower()
        if orig:
            ignored.add(orig)

    for multi in _MULTIWORD_OPERATOR_PHRASES:
        if multi in lowered:
            ignored.update(multi.split())

    ignored |= _ANALYTICAL_CONCEPT_LEXICON

    return ignored


def has_natural_comparison_language(query: str) -> bool:
    lowered = str(query or "").strip().lower()
    if not lowered:
        return False
    for phrase, _op in _FILTER_PHRASE_OPERATOR:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return True
    if re.search(r"(>=|<=|!=|>|<|=)", lowered):
        return True
    return False


def extract_conjoined_metric_phrases(question: str) -> list[str]:
    """
    Heuristic chunks on conjunctions / compare-lead-ins for multi-metric questions.
    Returns raw cleaned hints (not schema column names).
    """
    q = str(question or "").strip().lower()
    if not q:
        return []

    q = re.sub(r"\b(?:over|across|through)\s+time\b.*$", "", q, flags=re.IGNORECASE)
    q = re.sub(r"\bby\s+(?:hour|day|week|month|quarter|year)\b.*$", "", q, flags=re.IGNORECASE)
    q = re.sub(r"\bfor\s+(?:the\s+)?(?:next|past)\s+\d+\s+\w+.*$", "", q, flags=re.IGNORECASE)
    q = q.strip()

    hints: list[str] = []

    compare_body = re.search(
        r"\b(?:compare|compared|comparing)\s+(.+)$",
        q,
        flags=re.IGNORECASE,
    )
    if compare_body:
        body = compare_body.group(1).strip()
        for chunk in _CONJUNCTION_SPLIT_RE.split(body):
            hint = _clean_conjoined_hint(chunk)
            if hint:
                hints.append(hint)

    lead = re.search(
        r"\b(?:show|list|display|give)\s+(.+)$",
        q,
        flags=re.IGNORECASE,
    )
    if lead:
        body = lead.group(1).strip()
        body = re.split(r"\bwhere\b|\bhaving\b|\bthat\b", body, maxsplit=1)[0].strip()
        if _CONJUNCTION_SPLIT_RE.search(body):
            for chunk in _CONJUNCTION_SPLIT_RE.split(body):
                hint = _clean_conjoined_hint(chunk)
                if hint:
                    hints.append(hint)

    for pattern in (
        r"\b([a-z_][a-z0-9_ ]{0,48}?)\s+(?:vs\.?|versus)\s+([a-z_][a-z0-9_ ]{0,48}?)\b",
        r"\b([a-z_][a-z0-9_ ]{0,48}?)\s+with\s+([a-z_][a-z0-9_ ]{0,48}?)\b",
    ):
        for m in re.finditer(pattern, q, flags=re.IGNORECASE):
            a = _clean_conjoined_hint(m.group(1))
            b = _clean_conjoined_hint(m.group(2))
            if a:
                hints.append(a)
            if b:
                hints.append(b)

    deduped: list[str] = []
    seen: set[str] = set()
    for hint in hints:
        key = hint.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(hint)
    return deduped


def _clean_conjoined_hint(chunk: str) -> str:
    tokens = [
        t
        for t in re.findall(r"[a-z0-9_]+", str(chunk or "").lower())
        if t not in _HINT_STOP and len(t) > 1
    ]
    return " ".join(tokens[:6])


def extract_analytical_semantics(query: str) -> list[dict[str, Any]]:
    """
    Resolve analytical-language tokens/phrases into semantic concepts that should
    influence intent reasoning and planning (not schema matching).
    """
    lowered = str(query or "").strip().lower()
    if not lowered:
        return []

    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    ordered = sorted(_ANALYTICAL_SEMANTIC_VOCAB.items(), key=lambda item: len(item[0]), reverse=True)
    for phrase, semantic_payload in ordered:
        pattern = re.compile(rf"(?<![a-z0-9_]){re.escape(phrase)}(?![a-z0-9_])", flags=re.IGNORECASE)
        if not pattern.search(lowered):
            continue
        if phrase in seen:
            continue
        seen.add(phrase)
        matches.append(
            {
                "term": phrase,
                "semantic_meaning": str(semantic_payload.get("semantic_meaning", "")).strip() or "analytical_concept",
                "operations": [
                    str(op).strip()
                    for op in semantic_payload.get("operations", ())
                    if str(op).strip()
                ],
            }
        )
    return matches


def build_analytical_semantic_hints(query: str) -> dict[str, Any]:
    semantics = extract_analytical_semantics(query)
    operations: set[str] = set()
    meanings: set[str] = set()
    ranking_direction: str | None = None

    for item in semantics:
        for op in item.get("operations", []):
            if str(op).strip():
                operations.add(str(op).strip())
        meaning = str(item.get("semantic_meaning", "")).strip()
        if meaning:
            meanings.add(meaning)
        if meaning == "ranking_desc":
            ranking_direction = "DESC"
        elif meaning == "ranking_asc" and ranking_direction != "DESC":
            ranking_direction = "ASC"

    return {
        "semantic_operations": sorted(operations),
        "semantic_meanings": sorted(meanings),
        "ranking_direction_hint": ranking_direction,
        "time_series_signal": bool(
            {"time_series", "trend_change", "positive_change", "negative_change"} & meanings
        ),
    }


def build_nl_semantic_metadata(query: str) -> dict[str, Any]:
    analytical_semantics = extract_analytical_semantics(query)
    semantic_hints = build_analytical_semantic_hints(query)
    return {
        "semantic_filters": extract_semantic_filters(query),
        "canonical_verbs": extract_canonical_verbs(query),
        "conjoined_metric_hints": extract_conjoined_metric_phrases(query),
        "schema_diagnostic_ignore_tokens": sorted(schema_diagnostic_ignore_tokens(query)),
        "analytical_concepts": sorted(_ANALYTICAL_CONCEPT_LEXICON & set(re.findall(r"[a-z0-9_]+", str(query or "").lower()))),
        "analytical_semantics": analytical_semantics,
        "analytical_semantic_hints": semantic_hints,
    }


def extra_numeric_filter_pattern_specs() -> list[dict[str, Any]]:
    """
    Patterns merged into query_planner.NUMERIC_FILTER_PATTERNS for NL operators
    not covered by the legacy list (e.g. exceeded, at least).
    """
    return [
        {
            "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s+(?:exceeded|exceeds|exceeding|exceed)\s+(-?\d+(?:\.\d+)?)\b",
            "operator": ">",
            "captures_operator": False,
        },
        {
            "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s+(?:at least|no less than)\s+(-?\d+(?:\.\d+)?)\b",
            "operator": ">=",
            "captures_operator": False,
        },
        {
            "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s+(?:at most|no more than)\s+(-?\d+(?:\.\d+)?)\b",
            "operator": "<=",
            "captures_operator": False,
        },
        {
            "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s+(?:equals?|equal to)\s+(-?\d+(?:\.\d+)?)\b",
            "operator": "=",
            "captures_operator": False,
        },
    ]


def predictive_metric_columns_from_query(
    query: str,
    columns: Iterable[dict[str, Any]],
    *,
    max_metrics: int = 4,
) -> list[str]:
    """
    Resolve multiple numeric metrics from conjunction-style predictive questions
    using the same hint machinery as analytical planning.
    """
    from shared import query_planner as _qp

    cols_list = [c for c in columns if isinstance(c, dict) and str(c.get("name", "")).strip()]
    numeric_names = [
        str(c.get("name", "")).strip()
        for c in cols_list
        if str(c.get("name", "")).strip() and _qp.is_numeric_type(str(c.get("type", "")).strip())
    ]
    if not numeric_names:
        return []

    pseudo_schema = {"__t__": cols_list}
    meta = _qp.build_schema_metadata(pseudo_schema)["__t__"]
    all_cols = meta["columns"]

    resolved: list[str] = []
    seen: set[str] = set()

    for hint in extract_conjoined_metric_phrases(query):
        col = _qp._resolve_column_name(hint, all_cols)
        if col and col in numeric_names and col.lower() not in seen:
            seen.add(col.lower())
            resolved.append(col)
        if len(resolved) >= max_metrics:
            break

    if not resolved:
        single = _qp._resolve_column_name(str(query or ""), all_cols)
        if single and single in numeric_names:
            resolved.append(single)

    if len(resolved) < 2:
        tokens = set(re.findall(r"[a-z0-9_]+", str(query or "").lower()))
        scored = sorted(
            numeric_names,
            key=lambda name: len(tokens & set(re.findall(r"[a-z0-9_]+", name.lower()))),
            reverse=True,
        )
        for name in scored:
            if name.lower() not in seen:
                resolved.append(name)
                seen.add(name.lower())
            if len(resolved) >= max_metrics:
                break

    return resolved[:max_metrics]
