
import re
from typing import Any

from bi_platform_shared.semantic.intent_priority import build_intent_priority_payload

from shared.bi_semantic_layer import (
    build_nl_semantic_metadata,
    extract_conjoined_metric_phrases,
    extract_semantic_filters,
    extra_numeric_filter_pattern_specs,
)
from shared.bi_temporal_semantics import (
    analyze_temporal_intent,
    build_grouping_metadata,
    detect_composite_temporal_superlative,
    infer_nl_time_granularity,
    metric_lexical_variants,
    should_treat_as_relationship_scatter,
)
from shared.schema_filtering import is_technical_table_name
from shared.schema_utils import (
    build_table_metadata,
    is_technical_column_name,
    is_date_type,
    is_numeric_type,
    tokenize,
    unqualify_table_name,
)


DESC_RANK_KEYWORDS = (
    "highest",
    "largest",
    "most",
    "top",
    "maximum",
    "max",
    "best",
    "greatest",
    "biggest",
)
ASC_RANK_KEYWORDS = (
    "lowest",
    "smallest",
    "least",
    "bottom",
    "minimum",
    "min",
    "worst",
)

AVG_KEYWORDS = ("average", "avg", "mean")
COUNT_KEYWORDS = ("count", "how many", "number of")
SUM_KEYWORDS = ("sum", "total of", "in total", "overall total", "total")
MAX_KEYWORDS = ("maximum", "max")
MIN_KEYWORDS = ("minimum", "min")

TEMPORAL_BUCKET_TOKENS = {
    "hour",
    "hours",
    "day",
    "days",
    "date",
    "week",
    "weeks",
    "month",
    "months",
    "quarter",
    "quarters",
    "year",
    "years",
    "time",
    "timestamp",
    "period",
    "ds",
}

VALID_AGGREGATIONS = {"SUM", "AVG", "COUNT", "MIN", "MAX"}
VALID_FILTER_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "IN", "LIKE", "BETWEEN"}

RATE_LIKE_TOKENS = ("rate", "ratio", "percent", "percentage", "pct", "share")
AVG_LIKE_TOKENS = ("avg", "average", "mean", "median")
ADDITIVE_HINT_TOKENS = ("total", "count", "population", "amount", "sales", "revenue", "cost", "profit")
IDENTIFIER_LIKE_TOKENS = ("id", "code", "uuid", "key", "number", "num")
BUSINESS_METRIC_HINT_TOKENS = (
    "sales",
    "total_sales",
    "revenue",
    "orders",
    "order_count",
    "customers",
    "customer_count",
    "quantity",
    "amount",
)
ROW_COUNT_INTENT_PATTERNS = (
    r"\bnumber of rows\b",
    r"\bnumber of records\b",
    r"\bcount of (?:rows|records|entries|transactions|days|weeks|items)\b",
    r"\bcount (?:rows|records|entries|transactions|days|weeks|items)\b",
    r"\bhow many rows\b",
    r"\bhow many records\b",
    r"\bhow many entries\b",
    r"\bhow many transactions\b",
    r"\bhow many days\b",
    r"\bhow many weeks\b",
    r"\bhow many items\b",
)
TIME_GRANULARITY_EXPRESSIONS = {
    "hour": "toStartOfHour({column})",
    "day": "toDate({column})",
    "week": "toStartOfWeek({column})",
    "month": "toStartOfMonth({column})",
    "quarter": "toStartOfQuarter({column})",
    "year": "toStartOfYear({column})",
}
TIME_GRANULARITY_TERMS = {"hour", "day", "week", "month", "quarter", "year"}
DISTRIBUTION_KEYWORDS = ("distribution", "distributed", "histogram", "spread", "frequency")

TIME_GRAIN_DETECTION_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    # Explicit grain phrases.
    (re.compile(r"\b(?:by|per|for each|in each|each)\s+hour\b", flags=re.IGNORECASE), "hour", "explicit"),
    (re.compile(r"\b(?:by|per|for each|in each|each)\s+day\b", flags=re.IGNORECASE), "day", "explicit"),
    (re.compile(r"\b(?:by|per|for each|in each|each)\s+week\b", flags=re.IGNORECASE), "week", "explicit"),
    (re.compile(r"\b(?:by|per|for each|in each|each)\s+month\b", flags=re.IGNORECASE), "month", "explicit"),
    (re.compile(r"\b(?:by|per|for each|in each|each)\s+quarter\b", flags=re.IGNORECASE), "quarter", "explicit"),
    (re.compile(r"\b(?:by|per|for each|in each|each)\s+year\b", flags=re.IGNORECASE), "year", "explicit"),
    # Frequency adjectives.
    (re.compile(r"\bhourly\b", flags=re.IGNORECASE), "hour", "explicit"),
    (re.compile(r"\bdaily\b", flags=re.IGNORECASE), "day", "explicit"),
    (re.compile(r"\bweekly\b", flags=re.IGNORECASE), "week", "explicit"),
    (re.compile(r"\bmonthly\b", flags=re.IGNORECASE), "month", "explicit"),
    (re.compile(r"\bquarterly\b", flags=re.IGNORECASE), "quarter", "explicit"),
    (re.compile(r"\b(?:yearly|annual|annually)\b", flags=re.IGNORECASE), "year", "explicit"),
    # Explicit "over/across <grain>" forms.
    (re.compile(r"\bover\s+hours?\b", flags=re.IGNORECASE), "hour", "explicit"),
    (re.compile(r"\bover\s+days?\b", flags=re.IGNORECASE), "day", "explicit"),
    (re.compile(r"\bover\s+weeks?\b", flags=re.IGNORECASE), "week", "explicit"),
    (re.compile(r"\bover\s+months?\b", flags=re.IGNORECASE), "month", "explicit"),
    (re.compile(r"\bover\s+quarters?\b", flags=re.IGNORECASE), "quarter", "explicit"),
    (re.compile(r"\bover\s+years?\b", flags=re.IGNORECASE), "year", "explicit"),
    (re.compile(r"\bacross\s+hours?\b", flags=re.IGNORECASE), "hour", "explicit"),
    (re.compile(r"\bacross\s+days?\b", flags=re.IGNORECASE), "day", "explicit"),
    (re.compile(r"\bacross\s+weeks?\b", flags=re.IGNORECASE), "week", "explicit"),
    (re.compile(r"\bacross\s+months?\b", flags=re.IGNORECASE), "month", "explicit"),
    (re.compile(r"\bacross\s+quarters?\b", flags=re.IGNORECASE), "quarter", "explicit"),
    (re.compile(r"\bacross\s+years?\b", flags=re.IGNORECASE), "year", "explicit"),
)

TIME_DEFAULT_GROUPING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bover\s+time\b", flags=re.IGNORECASE),
    re.compile(r"\bthrough\s+time\b", flags=re.IGNORECASE),
    re.compile(r"\bacross\s+time\b", flags=re.IGNORECASE),
    re.compile(r"\btime\s+series\b", flags=re.IGNORECASE),
    re.compile(r"\btimeline\b", flags=re.IGNORECASE),
    re.compile(r"\btrend\b", flags=re.IGNORECASE),
)

NUMERIC_FILTER_PATTERNS = [
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s+(?:is\s+)?(?:above|over|greater than|more than|higher than)\s+(-?\d+(?:\.\d+)?)\b",
        "operator": ">",
        "captures_operator": False,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s+(?:is\s+)?(?:below|under|less than|fewer than|lower than)\s+(-?\d+(?:\.\d+)?)\b",
        "operator": "<",
        "captures_operator": False,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s*>\s*(-?\d+(?:\.\d+)?)\b",
        "operator": ">",
        "captures_operator": False,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s*<\s*(-?\d+(?:\.\d+)?)\b",
        "operator": "<",
        "captures_operator": False,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s*(>=|=>)\s*(-?\d+(?:\.\d+)?)\b",
        "operator": ">=",
        "captures_operator": True,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s*(<=|=<)\s*(-?\d+(?:\.\d+)?)\b",
        "operator": "<=",
        "captures_operator": True,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s*(=|==)\s*(-?\d+(?:\.\d+)?)\b",
        "operator": "=",
        "captures_operator": True,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s+(?:is\s+)?(?:not equal to|not equals|!=)\s+(-?\d+(?:\.\d+)?)\b",
        "operator": "!=",
        "captures_operator": False,
    },
]
NUMERIC_FILTER_PATTERNS.extend(extra_numeric_filter_pattern_specs())

BETWEEN_FILTER_PATTERNS = [
    r"\b([a-z_][a-z0-9_ ]+?)\s+between\s+(-?\d+(?:\.\d+)?)\s+and\s+(-?\d+(?:\.\d+)?)\b",
    r"\b([a-z_][a-z0-9_ ]+?)\s+from\s+(-?\d+(?:\.\d+)?)\s+to\s+(-?\d+(?:\.\d+)?)\b",
]

TEXT_FILTER_PATTERNS = [
    r"\b(?:where|with)\s+([a-z_][a-z0-9_ ]+?)\s+(?:is|equals|equal to|=)\s+['\"]?([a-z0-9_ -]+?)['\"]?(?:\b|$)",
    r"\b([a-z_][a-z0-9_ ]+?)\s+(?:is|equals|equal to|=)\s+['\"]?([a-z0-9_ -]+?)['\"]?(?:\b|$)",
    r"\bin\s+the\s+([a-z0-9_ -]+?)\s+([a-z_][a-z0-9_ ]+?)(?:\b|$)",
]

TEXT_CONTAINS_PATTERNS = [
    r"\b([a-z_][a-z0-9_ ]+?)\s+contains\s+['\"]?([a-z0-9_ -]+?)['\"]?(?:\b|$)",
    r"\b([a-z_][a-z0-9_ ]+?)\s+like\s+['\"]?([a-z0-9_ -%]+?)['\"]?(?:\b|$)",
]

LANGUAGE_STOP_TOKENS = {
    "a",
    "an",
    "all",
    "and",
    "are",
    "as",
    "at",
    "between",
    "by",
    "compare",
    "compared",
    "comparing",
    "comparison",
    "do",
    "does",
    "day",
    "days",
    "for",
    "from",
    "give",
    "had",
    "has",
    "have",
    "how",
    "in",
    "is",
    "list",
    "me",
    "month",
    "months",
    "of",
    "on",
    "or",
    "over",
    "please",
    "quarter",
    "quarters",
    "relationship",
    "show",
    "the",
    "to",
    "trend",
    "trends",
    "versus",
    "vs",
    "was",
    "week",
    "weeks",
    "were",
    "what",
    "when",
    "where",
    "which",
    "with",
    "year",
    "years",
    "generated",
    "generates",
    "produced",
    "produces",
    "performing",
    "performance",
    "increase",
    "increases",
    "decrease",
    "decreases",
}

DERIVED_METRIC_PATTERNS = [
    {
        "aliases": ("average order value", "aov"),
        "numerator_tokens": ("sales", "revenue", "amount"),
        "denominator_tokens": ("orders", "order"),
        "alias": "average_order_value",
    },
    {
        "aliases": ("conversion rate", "conversion"),
        "numerator_tokens": ("orders", "conversions"),
        "denominator_tokens": ("customers", "visitors", "users", "leads"),
        "alias": "conversion_rate",
    },
    {
        "aliases": ("revenue per customer", "sales per customer"),
        "numerator_tokens": ("revenue", "sales", "amount"),
        "denominator_tokens": ("customers", "customer"),
        "alias": "revenue_per_customer",
    },
    {
        "aliases": ("average basket size", "basket size"),
        "numerator_tokens": ("items", "quantity", "units"),
        "denominator_tokens": ("orders", "order"),
        "alias": "average_basket_size",
    },
]


def build_schema_metadata(schema: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for table, columns in schema.items():
        normalized_columns = []
        for col in columns:
            col_type = col.get("type", "")
            col_name = str(col.get("name", "")).strip()
            if not col_name or is_technical_column_name(col_name):
                continue
            inferred_is_date = bool(is_date_type(col_type) or _looks_temporal_column_name(col_name))
            normalized_columns.append(
                {
                    "name": col_name,
                    "type": col_type,
                    "is_numeric": col.get("is_numeric", is_numeric_type(col_type)),
                    "is_date": col.get("is_date", inferred_is_date),
                    "is_dimension": col.get(
                        "is_dimension",
                        not is_numeric_type(col_type) and not inferred_is_date,
                    ),
                }
            )
        metadata[table] = build_table_metadata(normalized_columns)
    return metadata


def _looks_temporal_column_name(column_name: str) -> bool:
    lowered = str(column_name or "").strip().lower()
    if not lowered:
        return False
    if lowered in {"ds", "date", "timestamp", "created_at"}:
        return True
    return bool(
        lowered.endswith(("_at", "_date", "_time"))
        or any(token in lowered for token in ("date", "time", "timestamp", "day", "week", "month", "year"))
    )


def _is_relationship_question(question_lower: str) -> bool:
    """
    Relationship / scatter path — delegated to temporal-vs-relationship arbitration.
    """
    return should_treat_as_relationship_scatter(str(question_lower or ""))


def _is_distribution_question(question_lower: str) -> bool:
    normalized = str(question_lower or "").strip().lower()
    return any(keyword in normalized for keyword in DISTRIBUTION_KEYWORDS)


def _resolve_numeric_hint(hint: str, table_meta: dict[str, Any], ambiguities: list[dict[str, Any]]) -> str | None:
    numeric_columns = table_meta.get("numeric_columns", [])
    if not numeric_columns:
        return None
    return _resolve_column_name_with_ambiguity(
        candidate=hint,
        columns=[table_meta["column_map"][c] for c in numeric_columns],
        context="metric",
        ambiguities=ambiguities,
    )


def _derive_metric_by_token_groups(
    *,
    table_meta: dict[str, Any],
    ambiguities: list[dict[str, Any]],
    numerator_tokens: tuple[str, ...],
    denominator_tokens: tuple[str, ...],
    alias: str,
) -> dict[str, Any] | None:
    numerator_column = None
    denominator_column = None

    for token in numerator_tokens:
        numerator_column = _resolve_numeric_hint(token, table_meta, ambiguities)
        if numerator_column:
            break
    for token in denominator_tokens:
        denominator_column = _resolve_numeric_hint(token, table_meta, ambiguities)
        if denominator_column:
            break

    if not numerator_column or not denominator_column:
        return None
    if numerator_column == denominator_column:
        return None

    return {
        "column": numerator_column,
        "aggregation": "SUM",
        "alias": alias,
        "formula": {
            "type": "ratio",
            "numerator": {"column": numerator_column, "aggregation": "SUM"},
            "denominator": {"column": denominator_column, "aggregation": "SUM"},
            "safe_division": True,
        },
    }


def _infer_derived_metric(
    *,
    question_lower: str,
    table_meta: dict[str, Any],
    ambiguities: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for pattern in DERIVED_METRIC_PATTERNS:
        aliases = pattern.get("aliases", ())
        if not any(alias in question_lower for alias in aliases):
            continue
        derived = _derive_metric_by_token_groups(
            table_meta=table_meta,
            ambiguities=ambiguities,
            numerator_tokens=tuple(pattern.get("numerator_tokens", ())),
            denominator_tokens=tuple(pattern.get("denominator_tokens", ())),
            alias=str(pattern.get("alias", "derived_metric")).strip() or "derived_metric",
        )
        if derived:
            return derived

    per_match = re.search(r"\b([a-z_][a-z0-9_ ]+?)\s+per\s+([a-z_][a-z0-9_ ]+?)\b", question_lower)
    if per_match:
        denominator_hint = per_match.group(2).strip().lower()
        if denominator_hint not in TIME_GRANULARITY_TERMS:
            numerator_hint = per_match.group(1).strip()
            numerator_column = _resolve_numeric_hint(numerator_hint, table_meta, ambiguities)
            denominator_column = _resolve_numeric_hint(denominator_hint, table_meta, ambiguities)
            if numerator_column and denominator_column and numerator_column != denominator_column:
                return {
                    "column": numerator_column,
                    "aggregation": "SUM",
                    "alias": f"{numerator_column}_per_{denominator_column}",
                    "formula": {
                        "type": "ratio",
                        "numerator": {"column": numerator_column, "aggregation": "SUM"},
                        "denominator": {"column": denominator_column, "aggregation": "SUM"},
                        "safe_division": True,
                    },
                }
    return None


def _infer_relationship_metrics(
    *,
    question: str,
    table_meta: dict[str, Any],
    ambiguities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    all_columns = table_meta["columns"]
    numeric_columns = table_meta["numeric_columns"]
    if not numeric_columns:
        return []

    resolved: list[str] = []
    relation_match = re.search(
        r"\bbetween\s+([a-z_][a-z0-9_ ]+?)\s+and\s+([a-z_][a-z0-9_ ]+)",
        question.lower(),
    )
    if not relation_match:
        relation_match = re.search(
            r"\bcompare\s+([a-z_][a-z0-9_ ]+?)\s+(?:and|with|to|against|vs|versus)\s+([a-z_][a-z0-9_ ]+)",
            question.lower(),
        )
    if relation_match:
        candidates = [_clean_metric_hint(relation_match.group(1).strip()), _clean_metric_hint(relation_match.group(2).strip())]
        for candidate in candidates:
            mapped = _resolve_column_name_with_ambiguity(
                candidate=candidate,
                columns=[table_meta["column_map"][c] for c in numeric_columns],
                context="metric",
                ambiguities=ambiguities,
            )
            if mapped and mapped not in resolved:
                resolved.append(mapped)

    if len(resolved) < 2:
        for hint in _extract_metric_hints_from_question(question):
            mapped = _resolve_column_name_with_ambiguity(
                candidate=hint,
                columns=[table_meta["column_map"][c] for c in numeric_columns],
                context="metric",
                ambiguities=ambiguities,
            )
            if mapped and mapped not in resolved:
                resolved.append(mapped)
            if len(resolved) >= 2:
                break

    if len(resolved) < 2:
        scored = sorted(
            numeric_columns,
            key=lambda col: _score_metric_column(col, tokenize(question)),
            reverse=True,
        )
        for col in scored[:2]:
            if col not in resolved:
                resolved.append(col)
            if len(resolved) >= 2:
                break

    if len(resolved) < 2:
        return []

    return [
        {"column": resolved[0], "aggregation": None, "alias": resolved[0]},
        {"column": resolved[1], "aggregation": None, "alias": resolved[1]},
    ]


def _extract_preselected_columns(raw_intent: dict[str, Any], table_meta: dict[str, Any]) -> list[str]:
    candidate_lists = [
        raw_intent.get("selected_columns_preprocessing_high"),
        raw_intent.get("selected_columns"),
    ]
    selected: list[str] = []
    seen: set[str] = set()
    valid_columns = {
        str(column.get("name", "")).strip()
        for column in table_meta.get("columns", [])
        if isinstance(column, dict) and str(column.get("name", "")).strip()
    }

    for raw_list in candidate_lists:
        if not isinstance(raw_list, list):
            continue
        for item in raw_list:
            column_name = str(item or "").strip()
            if not column_name:
                continue
            if column_name not in valid_columns:
                continue
            lowered = column_name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            selected.append(column_name)
    return selected


def normalize_analytical_intent(
    *,
    question: str,
    raw_intent: dict[str, Any],
    schema: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    if not schema:
        raise ValueError("Schema is empty; cannot plan query")

    schema_metadata = build_schema_metadata(schema)
    ambiguities: list[dict[str, Any]] = []
    nl_semantics = build_nl_semantic_metadata(question)
    analytical_semantic_hints = (
        nl_semantics.get("analytical_semantic_hints")
        if isinstance(nl_semantics.get("analytical_semantic_hints"), dict)
        else {}
    )
    intent_priority_payload = build_intent_priority_payload(question)

    table = _resolve_table(question, raw_intent, schema_metadata, ambiguities=ambiguities)
    if not table:
        raise ValueError("Could not resolve target table from schema")

    table_meta = schema_metadata[table]
    question_lower = question.lower()
    temporal_semantics = analyze_temporal_intent(question)
    composite_rank = detect_composite_temporal_superlative(question)
    relationship_requested = _is_relationship_question(question_lower)
    explicit_correlation_requested = bool(intent_priority_payload.get("explicit_correlation"))
    minimal_temporal_query = _is_minimal_temporal_grouping_query(question_lower)
    temporal_dominance_active = (
        bool(intent_priority_payload.get("suppress_relationship_scatter"))
        and str(intent_priority_payload.get("dominant_intent", "")).strip().lower() == "time_series"
    )
    if minimal_temporal_query and not explicit_correlation_requested:
        temporal_dominance_active = True
    if relationship_requested and temporal_dominance_active:
        relationship_requested = False
    distribution_requested = _is_distribution_question(question_lower)
    preselected_columns = _extract_preselected_columns(raw_intent, table_meta)
    preselected_metric_columns = [
        column_name
        for column_name in preselected_columns
        if column_name in table_meta.get("numeric_columns", [])
    ]
    metric_lock_enabled = bool(preselected_metric_columns)

    dimensions = _infer_dimensions(question, raw_intent, table_meta, ambiguities=ambiguities)
    if dimensions and relationship_requested and not explicit_correlation_requested:
        # "Compare X and Y by <dimension>" is a grouped categorical comparison,
        # not a row-wise correlation/scatter request. Keep explicit relationship,
        # correlation and scatter wording on the relationship path.
        relationship_requested = False
    time_grain_detection = detect_time_grain(question)
    time_granularity = str(time_grain_detection.get("grain") or "").strip().lower()
    time_grain_source = str(time_grain_detection.get("source") or "none").strip().lower() or "none"
    detected_time_phrase = str(time_grain_detection.get("matched_phrase") or "").strip()
    if not time_granularity and composite_rank.get("active"):
        time_granularity = str(composite_rank.get("time_granularity") or "").strip().lower()
        if time_granularity:
            time_grain_source = "inferred"
            if not detected_time_phrase:
                detected_time_phrase = str(composite_rank.get("matched_phrase") or "").strip()
    composite_bucket_rank = bool(composite_rank.get("active"))
    time_column = _select_time_column(table_meta) if time_granularity else ""
    time_dimension_expression = ""
    time_dimension_alias = ""
    time_grouping_detected = bool(time_granularity and time_column)
    if time_granularity == "hour" and not _supports_hour_granularity(table_meta=table_meta, column_name=time_column):
        raise ValueError("Granularity not supported: hour-level data not available")
    if time_grouping_detected:
        time_dimension_alias = "period"
        time_dimension_expression = _time_dimension_expression(
            table_meta=table_meta,
            column_name=time_column,
            granularity=time_granularity,
        )
        if relationship_requested and explicit_correlation_requested:
            # Explicit correlation language ("relationship between", "correlation",
            # "scatter", etc.) should preserve relationship intent even when temporal
            # hints are present in the same sentence.
            time_grouping_detected = False
            time_granularity = ""
            time_grain_source = "none"
            detected_time_phrase = ""
            time_column = ""
            time_dimension_expression = ""
            time_dimension_alias = ""
        else:
            # Time-series intent takes precedence over generic "compare X and Y" phrasing.
            # Without this, prompts like "compare sales and orders per week" can be
            # misrouted into relationship/scatter semantics and lose the time axis.
            relationship_requested = False
            if time_column not in dimensions:
                dimensions = [time_column, *dimensions]
                ambiguities.append(
                    {
                        "type": "dimension_inference",
                        "message": f"Time grouping detected ({time_granularity}); auto-selected time dimension.",
                        "candidates": [time_column],
                        "selected_dimension": time_column,
                        "resolution": "auto_selected_dimension",
                    }
                )

    ranking = _infer_ranking(question_lower=question_lower, raw_intent=raw_intent)
    ranking_direction_hint = str(analytical_semantic_hints.get("ranking_direction_hint") or "").strip().upper()
    if ranking_direction_hint in {"ASC", "DESC"} and not ranking.get("direction"):
        ranking["direction"] = ranking_direction_hint
        ranking["source"] = "analytical_semantic_hint"
    if composite_bucket_rank and composite_rank.get("ranking_direction") and not ranking.get("direction"):
        ranking["direction"] = composite_rank["ranking_direction"]
        ranking["source"] = "composite_temporal_superlative"
    explicit_top_n_requested = bool(ranking.get("explicit_limit_requested"))
    if (time_grouping_detected or relationship_requested) and not explicit_top_n_requested:
        if not (composite_bucket_rank and time_grouping_detected):
            ranking["direction"] = None
            ranking["source"] = "time_series_or_relationship_override"
    limit = ranking["limit"]
    ranking_requested = bool(ranking.get("direction")) or isinstance(limit, int)
    overall_total_requested = _is_overall_total_request(question_lower)

    if ranking_requested and not dimensions and not relationship_requested:
        auto_dimension = _auto_select_ranking_dimension(
            table_meta=table_meta,
            ambiguities=ambiguities,
        )
        if auto_dimension:
            dimensions = [auto_dimension]

    filters = _normalize_filters(question, raw_intent, table_meta, ambiguities=ambiguities)
    if not filters:
        year_filter = _infer_year_filter(question_lower, table_meta)
        if year_filter:
            filters.append(year_filter)
    filter_sources = sorted(
        {
            str(filter_item.get("source") or "").strip()
            for filter_item in filters
            if isinstance(filter_item, dict) and str(filter_item.get("source") or "").strip()
        }
    )
    filter_source = ",".join(filter_sources) if filter_sources else ("intent_filters" if filters else "none")

    source_grain_matches_requested = _source_grain_matches_requested(
        table_meta=table_meta,
        time_column=time_column,
        time_granularity=time_granularity,
        time_grouping_detected=time_grouping_detected,
    )
    time_rollup_required = bool(time_grouping_detected and not source_grain_matches_requested)

    metrics = _infer_metrics(
        question=question,
        raw_intent=raw_intent,
        table_meta=table_meta,
        dimensions=dimensions,
        filters=filters,
        ranking=ranking,
        ambiguities=ambiguities,
        relationship_requested=relationship_requested,
        distribution_requested=distribution_requested,
        time_grouping_detected=time_grouping_detected,
        analytical_semantic_hints=analytical_semantic_hints,
        preserve_time_grain_metric=source_grain_matches_requested,
        locked_metric_columns=preselected_metric_columns,
        metric_lock_enabled=metric_lock_enabled,
    )
    metrics = _bind_filter_metric_context(
        question=question,
        metrics=metrics,
        filters=filters,
        dimensions=dimensions,
        table_meta=table_meta,
    )
    if not metrics:
        metrics = [{"column": "*", "aggregation": "COUNT", "alias": _metric_alias("COUNT", "*")}]

    if relationship_requested:
        dimensions = []
        ranking_requested = False
        ranking["direction"] = None
        ranking["source"] = "relationship_override"
        limit = None

    order_by = _normalize_order_by(
        raw_intent,
        table_meta,
        metric_aliases=[metric["alias"] for metric in metrics if metric.get("alias")],
    )

    if ranking["direction"] and not order_by:
        primary_metric_alias = metrics[0]["alias"]
        order_by = [{"column": primary_metric_alias, "direction": ranking["direction"]}]
        if not limit:
            limit = ranking["implied_limit"] or 1
    elif limit and not order_by and metrics:
        primary_metric_alias = metrics[0]["alias"]
        order_by = [{"column": primary_metric_alias, "direction": "DESC"}]
    if (time_grouping_detected or relationship_requested) and not explicit_top_n_requested:
        if not composite_bucket_rank:
            limit = None
    if time_grouping_detected and not ranking["direction"] and not composite_bucket_rank:
        order_by = [{"column": time_dimension_alias or "period", "direction": "ASC"}]
    if relationship_requested:
        order_by = []

    operations = _derive_operations(
        metrics=metrics,
        dimensions=dimensions,
        filters=filters,
        order_by=order_by,
        limit=limit,
        ranking_requested=bool(ranking.get("direction")) or explicit_top_n_requested,
        relationship_requested=relationship_requested,
        distribution_requested=distribution_requested,
        time_grouping_detected=time_grouping_detected,
    )
    primary_intent = _infer_primary_intent(
        operations=operations,
        relationship_requested=relationship_requested,
        distribution_requested=distribution_requested,
        time_grouping_detected=time_grouping_detected,
    )
    if time_grouping_detected:
        primary_intent = "time_series"
        if "time_grouping" not in operations:
            operations.append("time_grouping")
        if not composite_bucket_rank:
            operations = [op for op in operations if op != "ranking"]
    if relationship_requested and "comparison" not in operations:
        operations.append("comparison")
    ambiguities = _normalize_dimension_ambiguities(ambiguities)

    aggregations = {str(metric.get("aggregation") or "").upper() for metric in metrics if metric.get("aggregation")}
    if len(aggregations) == 1:
        aggregation_summary: str | None = next(iter(aggregations))
    elif len(aggregations) > 1:
        aggregation_summary = "MIXED"
    else:
        aggregation_summary = None

    return {
        "intent_type": "analytical",
        "table": unqualify_table_name(table),
        "intent": primary_intent,
        "operations": operations,
        "dimensions": dimensions,
        "metrics": metrics,
        "filters": filters,
        "aggregation": aggregation_summary,
        "ranking": {
            "direction": ranking["direction"],
            "requested": bool(ranking["direction"]) or explicit_top_n_requested or composite_bucket_rank,
            "source": ranking["source"],
        },
        "order_by": order_by,
        "limit": limit,
        "time_granularity": time_granularity,
        "time_grain_source": time_grain_source if time_grouping_detected else "none",
        "detected_time_phrase": detected_time_phrase if time_grouping_detected else "",
        "time_column": time_column,
        "time_grouping_detected": time_grouping_detected,
        "source_grain_matches_requested": source_grain_matches_requested,
        "time_rollup_required": time_rollup_required,
        "time_dimension_expression": time_dimension_expression,
        "time_dimension_alias": time_dimension_alias,
        "explicit_top_n_requested": explicit_top_n_requested,
        "ambiguities": ambiguities,
        "kpi_allowed_without_dimension": overall_total_requested,
        "row_count_requested": _is_explicit_row_count_request(question_lower),
        "analysis_mode": "relationship" if relationship_requested else "distribution" if distribution_requested else "",
        "reasoning_version": "semantic_ir_v2",
        "grouping": build_grouping_metadata(question, time_granularity=time_granularity),
        "filter_source": filter_source,
        "semantic_filters": nl_semantics.get("semantic_filters", []),
        "analytical_semantics": nl_semantics.get("analytical_semantics", []),
        "analytical_semantic_hints": analytical_semantic_hints,
        "temporal_semantics": {
            **temporal_semantics,
            "grouping": build_grouping_metadata(question, time_granularity=time_granularity),
            "composite_temporal_superlative": composite_rank,
        },
        "intent_priority": intent_priority_payload.get("intent_priority", {}),
        "semantic_reasoning": intent_priority_payload,
        "minimal_temporal_grouping_query": minimal_temporal_query,
        "composite_temporal_ranking": composite_bucket_rank,
        "selected_columns_preprocessing_high": preselected_columns,
        "metric_lock_enabled": metric_lock_enabled,
    }


def _is_overall_total_request(question_lower: str) -> bool:
    if not question_lower:
        return False
    if "overall total" in question_lower or "overall" in question_lower:
        return True
    if "in total" in question_lower and not re.search(r"\b(by|per|across|for each|in each)\b", question_lower):
        return True
    return False


def detect_time_grain(question_text: str) -> dict[str, Any]:
    normalized = str(question_text or "").strip().lower()
    if not normalized:
        return {
            "has_time_grouping": False,
            "grain": None,
            "source": "none",
            "matched_phrase": None,
        }

    for pattern, grain, source in TIME_GRAIN_DETECTION_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        return {
            "has_time_grouping": True,
            "grain": grain,
            "source": source,
            "matched_phrase": match.group(0),
        }

    for pattern in TIME_DEFAULT_GROUPING_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        return {
            "has_time_grouping": True,
            "grain": "day",
            "source": "default",
            "matched_phrase": match.group(0),
        }

    inferred_grain = infer_nl_time_granularity(normalized)
    if inferred_grain:
        return {
            "has_time_grouping": True,
            "grain": inferred_grain,
            "source": "inferred",
            "matched_phrase": None,
        }

    return {
        "has_time_grouping": False,
        "grain": None,
        "source": "none",
        "matched_phrase": None,
    }


def _infer_time_granularity(question_lower: str) -> str:
    detected = detect_time_grain(question_lower)
    return str(detected.get("grain") or "")


def _is_trend_over_time_question(question_lower: str) -> bool:
    normalized = str(question_lower or "").strip().lower()
    if not normalized:
        return False
    trend_terms = (
        r"\btrend\b",
        r"\btrends\b",
        r"\bchanged?\b",
        r"\bchange over\b",
        r"\bevolv(?:e|ed|ing)\b",
        r"\bover time\b",
        r"\bthrough time\b",
        r"\bacross time\b",
        r"\btime series\b",
        r"\bgrowth\b",
        r"\btimeline\b",
    )
    has_trend_language = any(re.search(pattern, normalized) for pattern in trend_terms)
    has_time_axis = bool(
        re.search(r"\bover\s+time\b|\bthrough\s+time\b|\bacross\s+time\b|\btime\s+series\b", normalized)
        or re.search(r"\bby\s+(?:date|time|day|week|month|quarter|year)\b", normalized)
        or re.search(r"\b(?:during|across)\s+(?:the\s+)?(?:last|past)\b", normalized)
        or re.search(r"\bacross\s+(?:months|years|weeks|days)\b", normalized)
    )
    return has_trend_language or has_time_axis


def _select_time_column(table_meta: dict[str, Any]) -> str:
    date_columns = [str(col).strip() for col in table_meta.get("date_columns", []) if str(col).strip()]
    if not date_columns:
        return ""
    ranked_dates = sorted(
        date_columns,
        key=lambda col: (_time_column_priority(col), col.lower()),
    )
    return ranked_dates[0] if ranked_dates else ""


def _time_dimension_expression(*, table_meta: dict[str, Any], column_name: str, granularity: str) -> str:
    template = TIME_GRANULARITY_EXPRESSIONS.get(granularity, "")
    if not template or not column_name:
        return ""
    column_meta = table_meta.get("column_map", {}).get(column_name, {})
    column_type = str(column_meta.get("type", "")).strip().lower()
    normalized_column = column_name
    already_to_date = normalized_column.lower().startswith("todate(")
    if (
        "string" in column_type
        or "fixedstring" in column_type
        or "varchar" in column_type
        or "char" in column_type
    ):
        normalized_column = f"toDate({column_name})" if not already_to_date else normalized_column
    elif granularity != "hour" and not already_to_date:
        normalized_column = f"toDate({column_name})"
    if granularity == "hour":
        if "string" in column_type or "fixedstring" in column_type or "varchar" in column_type or "char" in column_type:
            normalized_column = f"toDateTime({column_name})"
        elif "date" in column_type and "datetime" not in column_type and "timestamp" not in column_type:
            normalized_column = f"toDateTime({column_name})"
    return template.format(column=normalized_column)


def _source_grain_matches_requested(
    *,
    table_meta: dict[str, Any],
    time_column: str,
    time_granularity: str,
    time_grouping_detected: bool,
) -> bool:
    """
    Return true only when schema metadata explicitly declares the source grain.

    A Date column describes a value's type, not table cardinality; a fact table can
    contain many rows for the same date. Treating Date as proof of daily grain can
    silently under-aggregate results, so names and types alone are insufficient.
    """
    if not time_grouping_detected or not time_column or not time_granularity:
        return False

    column_meta = table_meta.get("column_map", {}).get(time_column, {})
    declared_grain = str(
        column_meta.get("source_grain")
        or column_meta.get("time_grain")
        or column_meta.get("grain")
        or ""
    ).strip().lower()
    return declared_grain == time_granularity


def _supports_hour_granularity(*, table_meta: dict[str, Any], column_name: str) -> bool:
    if not column_name:
        return False
    column_meta = table_meta.get("column_map", {}).get(column_name, {})
    column_type = str(column_meta.get("type", "")).strip().lower()
    if not column_type:
        return False
    return ("datetime" in column_type) or ("timestamp" in column_type) or ("time" in column_type and "date" in column_type)


def _normalize_dimension_ambiguities(ambiguities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not ambiguities:
        return []
    has_auto = any(
        isinstance(item, dict) and str(item.get("resolution", "")).strip() == "auto_selected_dimension"
        for item in ambiguities
    )
    if not has_auto:
        return ambiguities
    normalized: list[dict[str, Any]] = []
    for item in ambiguities:
        if not isinstance(item, dict):
            continue
        if str(item.get("resolution", "")).strip() == "auto_selected_dimension":
            normalized.append(item)
    return normalized


def _time_column_priority(column_name: str) -> int:
    lowered = str(column_name or "").strip().lower()
    if lowered in {"ds", "date", "timestamp", "created_at"}:
        return 0
    if lowered.endswith("_at") or lowered.endswith("_date") or lowered.endswith("_time"):
        return 1
    if any(token in lowered for token in ("date", "time", "timestamp", "day", "week", "month", "year")):
        return 2
    return 3


def _categorical_column_priority(column_name: str) -> int:
    lowered = str(column_name or "").strip().lower()
    preferred = ("region", "product", "category", "city")
    for idx, token in enumerate(preferred):
        if token == lowered or lowered.startswith(f"{token}_") or lowered.endswith(f"_{token}"):
            return idx
    if any(token in lowered for token in preferred):
        return len(preferred)
    return len(preferred) + 1


def _auto_select_ranking_dimension(
    *,
    table_meta: dict[str, Any],
    ambiguities: list[dict[str, Any]],
) -> str | None:
    date_columns = [str(col).strip() for col in table_meta.get("date_columns", []) if str(col).strip()]
    dimension_columns = [str(col).strip() for col in table_meta.get("dimension_columns", []) if str(col).strip()]

    if date_columns:
        ranked_dates = sorted(
            date_columns,
            key=lambda col: (_time_column_priority(col), col.lower()),
        )
        chosen = ranked_dates[0]
        ambiguities.append(
            {
                "type": "dimension_inference",
                "message": "Ranking requested without explicit dimension; auto-selected time dimension.",
                "candidates": ranked_dates[:3],
                "selected_dimension": chosen,
                "resolution": "auto_selected_dimension",
            }
        )
        return chosen

    if dimension_columns:
        ranked_dims = sorted(
            dimension_columns,
            key=lambda col: (_categorical_column_priority(col), col.lower()),
        )
        chosen = ranked_dims[0]
        ambiguities.append(
            {
                "type": "dimension_inference",
                "message": "Ranking requested without explicit dimension; auto-selected categorical dimension.",
                "candidates": ranked_dims[:3],
                "selected_dimension": chosen,
                "resolution": "auto_selected_dimension",
            }
        )
        return chosen

    return None
def _resolve_table(
    question: str,
    raw_intent: dict[str, Any],
    schema_metadata: dict[str, dict[str, Any]],
    *,
    ambiguities: list[dict[str, Any]],
) -> str | None:
    if len(schema_metadata.keys()) == 1:
        return next(iter(schema_metadata.keys()))

    requested = (raw_intent.get("table") or "").strip()
    if requested in schema_metadata and not is_technical_table_name(requested):
        return requested
    if requested:
        requested_unqualified = unqualify_table_name(requested).lower()
        unqualified_matches = [
            table
            for table in schema_metadata.keys()
            if unqualify_table_name(table).lower() == requested_unqualified
            and not is_technical_table_name(table)
        ]
        if len(unqualified_matches) == 1:
            return unqualified_matches[0]
        if len(unqualified_matches) > 1:
            ambiguities.append(
                {
                    "type": "table_resolution",
                    "message": f"Table name '{requested}' matched multiple schema tables.",
                    "candidates": unqualified_matches,
                    "resolution": unqualified_matches[0],
                }
            )
            return unqualified_matches[0]

    question_tokens = tokenize(question)
    referenced_columns = set()

    for metric in _iter_raw_metric_candidates(raw_intent):
        column = metric[0]
        if column:
            referenced_columns.add(column)
    for dim in raw_intent.get("dimensions", []) or []:
        if isinstance(dim, str):
            referenced_columns.add(dim)
    for flt in raw_intent.get("filters", []) or []:
        if isinstance(flt, dict) and flt.get("column"):
            referenced_columns.add(flt["column"])
    for order in raw_intent.get("order_by", []) or []:
        if isinstance(order, dict) and order.get("column"):
            referenced_columns.add(order["column"])

    scored_tables: list[tuple[str, int]] = []
    for table, table_meta in schema_metadata.items():
        score = 0
        if is_technical_table_name(table):
            score -= 25

        table_tokens = tokenize(unqualify_table_name(table))
        score += len(table_tokens & question_tokens) * 3

        for candidate in referenced_columns:
            if _resolve_column_name(candidate, table_meta["columns"]):
                score += 4

        for col in table_meta["columns"]:
            if tokenize(col["name"]) & question_tokens:
                score += 1

        if requested and requested.lower() in table.lower():
            score += 5

        scored_tables.append((table, score))

    scored_tables.sort(key=lambda item: item[1], reverse=True)
    if not scored_tables:
        return None

    if len(scored_tables) > 1 and scored_tables[0][1] == scored_tables[1][1]:
        ambiguities.append(
            {
                "type": "table_resolution",
                "message": "Multiple tables had equivalent semantic relevance.",
                "candidates": [scored_tables[0][0], scored_tables[1][0]],
                "resolution": scored_tables[0][0],
            }
        )

    return scored_tables[0][0]


def _resolve_column_name(candidate: str, columns: list[dict[str, Any]]) -> str | None:
    if not candidate:
        return None

    candidate_clean = candidate.strip()
    candidate_lower = candidate_clean.lower()

    exact = [c["name"] for c in columns if c["name"].lower() == candidate_lower]
    if exact:
        return exact[0]

    normalized_target = candidate_lower.replace(" ", "_")
    exact_normalized = [c["name"] for c in columns if c["name"].lower() == normalized_target]
    if exact_normalized:
        return exact_normalized[0]
    if normalized_target.endswith("s"):
        singular = normalized_target[:-1]
        singular_match = [c["name"] for c in columns if c["name"].lower() == singular]
        if singular_match:
            return singular_match[0]

    def _token_variants_set(raw: str) -> set[str]:
        variants: set[str] = set()
        joined = raw.lower().strip().replace(" ", "_")
        if len(joined) > 1:
            variants.add(joined)
        for part in re.findall(r"[a-z0-9_]+", joined):
            if len(part) > 1:
                variants |= metric_lexical_variants(part)
        return {v for v in variants if len(v) > 1}

    cand_variants = _token_variants_set(normalized_target)
    for col in columns:
        cn = col["name"].lower()
        if cn in cand_variants:
            return col["name"]

    target_tokens = _expand_tokens(tokenize(candidate_clean))
    best = None
    best_score = 0

    for col in columns:
        col_name = col["name"]
        col_tokens = _expand_tokens(tokenize(col_name))
        overlap = len(target_tokens & col_tokens)
        if overlap > best_score:
            best_score = overlap
            best = col_name

    return best if best_score > 0 else None


def _resolve_column_name_with_ambiguity(
    *,
    candidate: str,
    columns: list[dict[str, Any]],
    context: str,
    ambiguities: list[dict[str, Any]],
) -> str | None:
    stripped = str(candidate or "").strip()
    if not stripped:
        return None

    direct = _resolve_column_name(stripped, columns)
    if direct:
        return direct

    candidate_tokens = _expand_tokens(tokenize(stripped))
    if not candidate_tokens:
        return None

    scored: list[tuple[str, int]] = []
    for col in columns:
        overlap = len(candidate_tokens & _expand_tokens(tokenize(col["name"])))
        if overlap > 0:
            scored.append((col["name"], overlap))

    if scored:
        scored.sort(key=lambda item: item[1], reverse=True)
        if len(scored) > 1 and scored[0][1] == scored[1][1]:
            ambiguities.append(
                {
                    "type": "column_resolution",
                    "message": f"Ambiguous {context} phrase '{candidate}'.",
                    "candidates": [scored[0][0], scored[1][0]],
                    "resolution": scored[0][0],
                }
            )
            return scored[0][0]
        return scored[0][0]

    return None


def _expand_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for token in list(tokens):
        if token.endswith("ies") and len(token) > 4:
            expanded.add(token[:-3] + "y")
        if token.endswith("s") and len(token) > 3:
            expanded.add(token[:-1])
        if len(token) > 2:
            expanded |= metric_lexical_variants(token)
    return expanded


def _contains_keyword_or_phrase(question_lower: str, keyword: str) -> bool:
    normalized_question = str(question_lower or "").strip().lower()
    normalized_keyword = str(keyword or "").strip().lower()
    if not normalized_question or not normalized_keyword:
        return False
    pattern = re.compile(
        rf"(?<![a-z0-9_]){re.escape(normalized_keyword)}(?![a-z0-9_])",
        flags=re.IGNORECASE,
    )
    return bool(pattern.search(normalized_question))


def _has_any_keyword_or_phrase(question_lower: str, keywords: tuple[str, ...]) -> bool:
    return any(_contains_keyword_or_phrase(question_lower, keyword) for keyword in keywords)


def _looks_temporal_metric_column_name(column_name: str) -> bool:
    tokens = tokenize(column_name)
    if not tokens:
        return False
    expanded = _expand_tokens(tokens)
    if expanded <= TEMPORAL_BUCKET_TOKENS:
        return True
    lowered = str(column_name or "").strip().lower()
    if lowered in TEMPORAL_BUCKET_TOKENS:
        return True
    if lowered in {"created_at", "updated_at", "event_time", "event_date"}:
        return True
    return False


def _is_minimal_temporal_grouping_query(question_lower: str) -> bool:
    normalized = str(question_lower or "").strip().lower()
    if not normalized:
        return False
    if re.search(r"\b(?:by|per|group(?:ed)?\s+by|for each|in each)\s+(?:hour|day|week|month|quarter|year)\b", normalized):
        return True
    if re.search(r"\b(?:hourly|daily|weekly|monthly|quarterly|yearly|annually)\b", normalized):
        return True
    return False


def _detect_rank_direction(question_lower: str) -> str | None:
    normalized = str(question_lower or "").strip().lower()
    if not normalized:
        return None
    # Filter-threshold comparators (at least/at most) should not trigger ranking.
    normalized = re.sub(r"\b(?:at least|at most|no less than|no more than)\b", " ", normalized)
    has_desc = _has_any_keyword_or_phrase(normalized, DESC_RANK_KEYWORDS)
    has_asc = _has_any_keyword_or_phrase(normalized, ASC_RANK_KEYWORDS)
    if has_desc and has_asc:
        # In mixed phrasing (e.g. "top ... worst"), explicit low-end terms should win.
        return "ASC"
    if has_desc:
        return "DESC"
    if has_asc:
        return "ASC"
    return None


def _extract_limit(question_lower: str, raw_intent: dict[str, Any]) -> tuple[int | None, bool]:
    raw_limit = raw_intent.get("limit")
    if isinstance(raw_limit, int) and raw_limit > 0:
        return raw_limit, True

    patterns = (
        r"\btop\s+(\d+)\b",
        r"\bbottom\s+(\d+)\b",
        r"\bfirst\s+(\d+)\b",
        r"\blast\s+(\d+)\b",
        r"\b(\d+)\s+\w+\s+with\s+(?:the\s+)?(?:highest|lowest|largest|smallest|best|worst)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, question_lower)
        if match:
            value = int(match.group(1))
            if value > 0:
                return value, True
    return None, False


def _infer_ranking(*, question_lower: str, raw_intent: dict[str, Any]) -> dict[str, Any]:
    direction = _detect_rank_direction(question_lower)
    source = "query"

    raw_order = raw_intent.get("order_by") or []
    if isinstance(raw_order, list) and raw_order:
        first = raw_order[0] if isinstance(raw_order[0], dict) else {}
        raw_direction = str(first.get("direction", "")).strip().upper()
        if raw_direction in {"ASC", "DESC"}:
            direction = raw_direction
            source = "raw_intent"

    limit, explicit_limit_requested = _extract_limit(question_lower, raw_intent)
    implied_limit = 1 if direction and limit is None else None

    return {
        "direction": direction,
        "limit": limit,
        "implied_limit": implied_limit,
        "source": source,
        "explicit_limit_requested": explicit_limit_requested,
    }
def _detect_explicit_aggregation(question_lower: str) -> str | None:
    if _has_any_keyword_or_phrase(question_lower, AVG_KEYWORDS):
        return "AVG"
    if _has_any_keyword_or_phrase(question_lower, COUNT_KEYWORDS):
        return "COUNT"
    if _has_any_keyword_or_phrase(question_lower, SUM_KEYWORDS):
        return "SUM"
    if _has_any_keyword_or_phrase(question_lower, MAX_KEYWORDS):
        return "MAX"
    if _has_any_keyword_or_phrase(question_lower, MIN_KEYWORDS):
        return "MIN"
    return None


def _is_rate_like(column_name: str) -> bool:
    col_lower = (column_name or "").lower()
    return any(token in col_lower for token in RATE_LIKE_TOKENS)


def _is_avg_like(column_name: str) -> bool:
    col_lower = (column_name or "").lower()
    return any(token in col_lower for token in AVG_LIKE_TOKENS)


def _looks_additive(column_name: str) -> bool:
    col_lower = (column_name or "").lower()
    return any(token in col_lower for token in ADDITIVE_HINT_TOKENS)


def _looks_identifier_like(column_name: str) -> bool:
    col_lower = (column_name or "").lower()
    return any(token in col_lower for token in IDENTIFIER_LIKE_TOKENS)


def _is_business_metric_column(column_name: str) -> bool:
    col_lower = (column_name or "").lower()
    return any(token in col_lower for token in BUSINESS_METRIC_HINT_TOKENS)


def _is_explicit_row_count_request(question_lower: str) -> bool:
    normalized = str(question_lower or "").strip().lower()
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in ROW_COUNT_INTENT_PATTERNS)


def _aggregation_for_ranking(column_name: str, question_lower: str, has_dimensions: bool) -> str | None:
    explicit = _detect_explicit_aggregation(question_lower)
    if explicit:
        if (
            explicit == "COUNT"
            and has_dimensions
            and _is_business_metric_column(column_name)
            and not _is_explicit_row_count_request(question_lower)
        ):
            return "SUM"
        return explicit
    if _is_rate_like(column_name) or _is_avg_like(column_name):
        return "AVG"
    if has_dimensions:
        return "SUM"
    return None


def _has_grouping_intent(question_lower: str) -> bool:
    return bool(
        re.search(
            r"\b(by|per|across|for each|in each|top|bottom|highest|lowest|largest|smallest|best|worst|group\s+by)\b",
            question_lower,
        )
    )


def _metric_alias(aggregation: str | None, column: str) -> str:
    safe_column = column.replace(".", "_")
    if column == "*":
        safe_column = "rows"
    if not aggregation:
        return safe_column
    return f"{aggregation.lower()}_{safe_column}"


def _score_metric_column(column_name: str, question_tokens: set[str]) -> int:
    col_tokens = _expand_tokens(tokenize(column_name))
    question_token_variants = _expand_tokens(set(question_tokens))
    score = len(col_tokens & question_token_variants) * 4

    if "_id" in column_name.lower() or _looks_identifier_like(column_name):
        score -= 2
    if _is_rate_like(column_name):
        score += 1
    if _looks_additive(column_name):
        score += 1
    if _looks_temporal_metric_column_name(column_name):
        score -= 1

    return score


def _extract_metric_hints_from_question(question: str) -> list[str]:
    question_lower = question.lower()
    hints: list[str] = []

    for joined in extract_conjoined_metric_phrases(question):
        cleaned = _clean_metric_hint(joined)
        if cleaned:
            hints.append(cleaned)

    select_match = re.search(
        r"\b(?:show|list|display|give|compare|compared|comparing|what is|what are|which)\s+(.+?)(?:\s+\bby\b|\s+\bwhere\b|\s+\bin\b|\s+\bwith\b|$)",
        question_lower,
    )
    if select_match:
        projected_part = select_match.group(1)
        projected_part = re.sub(
            r"\b(the|a|an|all|total|overall|top\s+\d+|bottom\s+\d+|trend|relationship|between|over\s+time|"
            r"generated|produces?|produced|performing|performance|increases?|decreases?|growth)\b",
            " ",
            projected_part,
        )
        for chunk in re.split(r"\band\b|,", projected_part):
            hint = _clean_metric_hint(chunk.strip())
            if hint and hint not in {"the", "a", "an"}:
                hints.append(hint)

    # Ranking pattern: metric commonly appears after "by".
    if re.search(r"\b(?:top|bottom)\s+\d+\b", question_lower) or re.search(
        r"\b(?:highest|lowest|largest|smallest|best|worst|most|least)\b",
        question_lower,
    ):
        by_match = re.search(
            r"\bby\s+([a-z_][a-z0-9_ ]+?)(?:\s+\bwhere\b|\s+\bwith\b|\s+\bin\b|$)",
            question_lower,
        )
        if by_match:
            for chunk in re.split(r"\band\b|,", by_match.group(1)):
                hint = _clean_metric_hint(chunk.strip())
                if hint:
                    hints.append(hint)

    leading_metric_match = re.search(
        r"^\s*([a-z_][a-z0-9_ ]+?)\s+(?:by|per|across)\s+([a-z_][a-z0-9_ ]+?)(?:\s+\bwhere\b|\s+\bwith\b|\s+\bin\b|$)",
        question_lower,
    )
    if leading_metric_match and not re.search(r"^\s*(?:top|bottom)\s+\d+\b", question_lower):
        leading_metric = _clean_metric_hint(leading_metric_match.group(1).strip())
        if leading_metric:
            hints.append(leading_metric)

    rank_metric_match = re.search(
        r"\b(?:highest|lowest|largest|smallest|best|worst)\s+([a-z_][a-z0-9_ ]+)\b",
        question_lower,
    )
    if rank_metric_match:
        hint = _clean_metric_hint(rank_metric_match.group(1).strip())
        if hint:
            hints.append(hint)

    noun_phrase_match = re.search(
        r"^\s*([a-z_][a-z0-9_ ]+?)\s+(?:by|per|over|across)\s+"
        r"(?:hour|day|week|month|quarter|year|time|date)\b",
        question_lower,
    )
    if noun_phrase_match:
        noun_phrase = re.sub(
            r"\b(growth|trend|trends|increase|increases|decrease|decreases|generated|produced|performing|performance)\b",
            " ",
            noun_phrase_match.group(1),
        )
        hint = _clean_metric_hint(noun_phrase.strip())
        if hint:
            hints.append(hint)

    deduped: list[str] = []
    seen: set[str] = set()
    for hint in hints:
        key = hint.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(hint)
    return deduped


def _iter_raw_metric_candidates(raw_intent: dict[str, Any]) -> list[tuple[str, str | None]]:
    results: list[tuple[str, str | None]] = []

    for metric in raw_intent.get("metric_specs", []) or []:
        if not isinstance(metric, dict):
            continue
        column = str(metric.get("column", "")).strip()
        aggregation = str(metric.get("aggregation", "")).strip().upper() or None
        if column:
            results.append((column, aggregation))

    for metric in raw_intent.get("metrics", []) or []:
        if isinstance(metric, dict):
            column = str(metric.get("column", "")).strip()
            aggregation = str(metric.get("aggregation", "")).strip().upper() or None
            if column:
                results.append((column, aggregation))
        elif isinstance(metric, str):
            metric_clean = metric.strip()
            if metric_clean:
                results.append((metric_clean, None))

    return results


def _infer_metrics(
    *,
    question: str,
    raw_intent: dict[str, Any],
    table_meta: dict[str, Any],
    dimensions: list[str],
    filters: list[dict[str, Any]] | None,
    ranking: dict[str, Any],
    ambiguities: list[dict[str, Any]],
    relationship_requested: bool,
    distribution_requested: bool,
    time_grouping_detected: bool = False,
    analytical_semantic_hints: dict[str, Any] | None = None,
    preserve_time_grain_metric: bool = False,
    locked_metric_columns: list[str] | None = None,
    metric_lock_enabled: bool = False,
) -> list[dict[str, Any]]:
    question_lower = question.lower()
    semantic_hints = analytical_semantic_hints if isinstance(analytical_semantic_hints, dict) else {}
    semantic_operations = {
        str(op).strip().lower()
        for op in semantic_hints.get("semantic_operations", [])
        if str(op).strip()
    }
    if relationship_requested:
        relationship_metrics = _infer_relationship_metrics(
            question=question,
            table_meta=table_meta,
            ambiguities=ambiguities,
        )
        if relationship_metrics:
            return relationship_metrics

    derived_metric = _infer_derived_metric(
        question_lower=question_lower,
        table_meta=table_meta,
        ambiguities=ambiguities,
    )
    if derived_metric:
        return [derived_metric]

    question_tokens = tokenize(question)
    explicit_agg = _detect_explicit_aggregation(question_lower)
    grouping_intent = _has_grouping_intent(question_lower) or bool(dimensions)
    row_count_request = _is_explicit_row_count_request(question_lower)

    numeric_columns = table_meta["numeric_columns"]
    all_columns = table_meta["columns"]
    filter_metric_candidates = [
        str(filter_item.get("column", "")).strip()
        for filter_item in (filters or [])
        if isinstance(filter_item, dict)
        and str(filter_item.get("column", "")).strip() in numeric_columns
    ]

    if distribution_requested:
        # Distribution should project one numeric series without aggregation.
        distribution_column = None
        for hint in _extract_metric_hints_from_question(question):
            distribution_column = _resolve_column_name_with_ambiguity(
                candidate=hint,
                columns=[table_meta["column_map"][c] for c in numeric_columns],
                context="metric",
                ambiguities=ambiguities,
            )
            if distribution_column:
                break
        if not distribution_column and numeric_columns:
            scored = sorted(
                numeric_columns,
                key=lambda col: _score_metric_column(col, question_tokens),
                reverse=True,
            )
            distribution_column = scored[0]
        if distribution_column:
            return [{"column": distribution_column, "aggregation": None, "alias": distribution_column}]

    metric_candidates: list[tuple[str, str | None]] = []
    seen_columns: set[str] = set()
    locked_columns = [
        str(column).strip()
        for column in (locked_metric_columns or [])
        if str(column).strip() and str(column).strip() in numeric_columns
    ]
    locked_column_set = set(locked_columns)

    if metric_lock_enabled and locked_columns:
        for locked_column in locked_columns:
            if locked_column not in seen_columns:
                metric_candidates.append((locked_column, None))
                seen_columns.add(locked_column)

    for raw_column, raw_agg in _iter_raw_metric_candidates(raw_intent):
        resolved = _resolve_column_name_with_ambiguity(
            candidate=raw_column,
            columns=all_columns,
            context="metric",
            ambiguities=ambiguities,
        )
        if metric_lock_enabled and locked_column_set and resolved and resolved not in locked_column_set:
            continue
        if resolved and resolved not in seen_columns:
            metric_candidates.append((resolved, raw_agg))
            seen_columns.add(resolved)

    resolved_any_hints: list[str] = []
    for hint in _extract_metric_hints_from_question(question):
        resolved_numeric = _resolve_column_name_with_ambiguity(
            candidate=hint,
            columns=[table_meta["column_map"][c] for c in numeric_columns],
            context="metric",
            ambiguities=ambiguities,
        )
        resolved = resolved_numeric or _resolve_column_name_with_ambiguity(
            candidate=hint,
            columns=all_columns,
            context="metric",
            ambiguities=ambiguities,
        )
        if metric_lock_enabled and locked_column_set and resolved and resolved not in locked_column_set:
            continue
        if resolved:
            resolved_any_hints.append(resolved)
        if resolved and resolved not in seen_columns and resolved in numeric_columns:
            metric_candidates.append((resolved, None))
            seen_columns.add(resolved)

    if explicit_agg == "COUNT" and not metric_candidates:
        entity_match = re.search(r"\bhow many\s+([a-z_][a-z0-9_ ]*)\b", question_lower)
        if entity_match:
            entity = entity_match.group(1).strip().split(" ")[0]
            metric_column = _resolve_column_name(entity, all_columns)
            if metric_column:
                metric_candidates.append((metric_column, None))
        if not metric_candidates:
            metric_candidates.append(("*", "COUNT"))

    if not metric_candidates:
        if metric_lock_enabled and locked_columns:
            for locked_column in locked_columns:
                if locked_column not in seen_columns:
                    metric_candidates.append((locked_column, None))
                    seen_columns.add(locked_column)

    if not metric_candidates:
        for filter_column in filter_metric_candidates:
            if filter_column and filter_column not in seen_columns:
                if metric_lock_enabled and locked_column_set and filter_column not in locked_column_set:
                    continue
                metric_candidates.append((filter_column, None))
                seen_columns.add(filter_column)

    if not metric_candidates:
        if resolved_any_hints and explicit_agg is None:
            for resolved_hint in resolved_any_hints:
                if resolved_hint not in seen_columns:
                    metric_candidates.append((resolved_hint, None))
                    seen_columns.add(resolved_hint)
        if numeric_columns:
            numeric_fallback_pool = list(numeric_columns)
            if metric_lock_enabled and locked_columns:
                numeric_fallback_pool = [column for column in numeric_fallback_pool if column in locked_column_set]
                if not numeric_fallback_pool:
                    numeric_fallback_pool = list(locked_columns)
            if time_grouping_detected:
                non_temporal_numeric = [
                    col_name for col_name in numeric_fallback_pool if not _looks_temporal_metric_column_name(col_name)
                ]
                if non_temporal_numeric:
                    numeric_fallback_pool = non_temporal_numeric
            scored = sorted(
                numeric_fallback_pool,
                key=lambda col: _score_metric_column(col, question_tokens),
                reverse=True,
            )
            if not metric_candidates:
                metric_candidates.append((scored[0], None))
        else:
            if not metric_candidates:
                metric_candidates.append(("*", "COUNT"))

    metrics: list[dict[str, Any]] = []
    for metric_column, raw_agg in metric_candidates:
        aggregation: str | None = explicit_agg
        if preserve_time_grain_metric and aggregation == "SUM":
            aggregation = None

        if (
            aggregation == "COUNT"
            and metric_column != "*"
            and metric_column in numeric_columns
            and _is_business_metric_column(metric_column)
            and not row_count_request
        ):
            aggregation = "SUM"

        if aggregation is None and ranking.get("direction"):
            aggregation = _aggregation_for_ranking(
                metric_column,
                question_lower,
                has_dimensions=bool(dimensions),
            )

        if aggregation is None and raw_agg in VALID_AGGREGATIONS:
            aggregation = raw_agg
            if preserve_time_grain_metric and aggregation == "SUM":
                aggregation = None
            if (
                raw_agg == "SUM"
                and explicit_agg is None
                and (_is_rate_like(metric_column) or _is_avg_like(metric_column))
            ):
                aggregation = "AVG" if ranking.get("direction") else None

        if aggregation is None:
            if metric_column == "*":
                aggregation = "COUNT"
            elif _is_rate_like(metric_column) or _is_avg_like(metric_column):
                aggregation = "AVG" if ranking.get("direction") else None
            elif grouping_intent:
                if preserve_time_grain_metric and metric_column in numeric_columns:
                    aggregation = None
                elif _looks_additive(metric_column):
                    aggregation = "SUM"
                elif _looks_identifier_like(metric_column):
                    aggregation = "COUNT"
                elif metric_column in numeric_columns:
                    aggregation = "SUM"
                else:
                    aggregation = None
            else:
                aggregation = None

        if (
            time_grouping_detected
            and not preserve_time_grain_metric
            and aggregation is None
            and "distribution" not in semantic_operations
        ):
            if metric_column == "*":
                aggregation = "COUNT"
            elif metric_column in numeric_columns:
                aggregation = "AVG" if (_is_rate_like(metric_column) or _is_avg_like(metric_column)) else "SUM"
            else:
                aggregation = "COUNT"

        if (
            aggregation == "COUNT"
            and metric_column != "*"
            and metric_column in numeric_columns
            and _is_business_metric_column(metric_column)
            and not row_count_request
        ):
            aggregation = "SUM"

        if aggregation and aggregation != "COUNT" and metric_column not in numeric_columns:
            if numeric_columns:
                resolved_numeric = _resolve_column_name(
                    metric_column,
                    [table_meta["column_map"][c] for c in numeric_columns],
                )
                if resolved_numeric:
                    metric_column = resolved_numeric
                else:
                    aggregation = None
            else:
                aggregation = None

        if aggregation == "COUNT" and not metric_column:
            metric_column = "*"

        alias = _metric_alias(aggregation, metric_column)
        metrics.append({"column": metric_column, "aggregation": aggregation, "alias": alias})

    return metrics


def _bind_filter_metric_context(
    *,
    question: str,
    metrics: list[dict[str, Any]],
    filters: list[dict[str, Any]],
    dimensions: list[str],
    table_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    if not metrics or not filters:
        return metrics

    explicit_metric_hints = _extract_metric_hints_from_question(question)
    if explicit_metric_hints:
        return metrics

    numeric_columns = set(table_meta.get("numeric_columns", []))
    filter_columns = [
        str(filter_item.get("column", "")).strip()
        for filter_item in filters
        if isinstance(filter_item, dict)
        and str(filter_item.get("column", "")).strip()
    ]
    if not filter_columns:
        return metrics

    bound_column = next((column for column in filter_columns if column in numeric_columns), filter_columns[0])
    if not bound_column:
        return metrics

    existing_metric_columns = [
        str(metric.get("column", "")).strip()
        for metric in metrics
        if isinstance(metric, dict)
    ]
    if bound_column in existing_metric_columns:
        return metrics

    aggregation: str | None = None
    if dimensions:
        if bound_column in numeric_columns:
            aggregation = "SUM"
        else:
            aggregation = "COUNT"

    bound_metric = {
        "column": bound_column,
        "aggregation": aggregation,
        "alias": _metric_alias(aggregation, bound_column),
    }
    return [bound_metric, *metrics]
def _clean_dimension_phrase(phrase: str) -> str:
    tokens = [t for t in re.findall(r"[a-z0-9_]+", phrase.lower()) if t not in LANGUAGE_STOP_TOKENS]
    return " ".join(tokens[:4])


def _clean_metric_hint(phrase: str) -> str:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9_]+", str(phrase or "").lower())
        if token not in LANGUAGE_STOP_TOKENS
        and token not in {"total", "overall", "sum", "average", "avg", "mean", "number", "count"}
    ]
    return " ".join(tokens[:5])


def _extract_dimension_hints(question: str) -> list[str]:
    question_lower = question.lower()
    hints: list[str] = []

    top_entity_matches = re.findall(
        r"\b(?:top|bottom)\s+\d+\s+([a-z_][a-z0-9_ ]+?)\s+by\b",
        question_lower,
    )
    hints.extend(top_entity_matches)

    by_matches = re.findall(r"\b(?:by|per|across)\s+([a-z_][a-z0-9_ ]+)", question_lower)
    hints.extend(by_matches)

    each_matches = re.findall(r"\b(?:in each|for each)\s+([a-z_][a-z0-9_ ]+)", question_lower)
    hints.extend(each_matches)

    which_match = re.search(
        r"\b(?:which|what)\s+([a-z_][a-z0-9_ ]+?)\s+(?:has|have|with|shows|is|are)\b",
        question_lower,
    )
    if which_match:
        hints.append(which_match.group(1))

    rank_subject_match = re.search(
        r"\b([a-z_][a-z0-9_ ]+?)\s+with\s+(?:the\s+)?(?:highest|lowest|largest|smallest|best|worst)\b",
        question_lower,
    )
    if rank_subject_match:
        hints.append(rank_subject_match.group(1))

    # Keep projection-subject fallback conservative to avoid weak/over-eager dimensions.
    if not re.search(r"\b(?:by|per|across|for each|in each)\b", question_lower):
        projection_subject_match = re.search(
            r"\b(?:show|list|display|give)\s+([a-z_][a-z0-9_ ]+?)(?:\s+where\b|\s+in\b|$)",
            question_lower,
        )
        if projection_subject_match:
            hints.append(projection_subject_match.group(1))

    return [_clean_dimension_phrase(h) for h in hints if h.strip()]


def _infer_dimensions(
    question: str,
    raw_intent: dict[str, Any],
    table_meta: dict[str, Any],
    *,
    ambiguities: list[dict[str, Any]],
) -> list[str]:
    all_columns = table_meta["columns"]
    dimension_candidates = table_meta["dimension_columns"] + table_meta["date_columns"]
    resolved: list[str] = []

    for dim in raw_intent.get("dimensions", []) or []:
        if not isinstance(dim, str):
            continue
        mapped = _resolve_column_name_with_ambiguity(
            candidate=dim,
            columns=all_columns,
            context="dimension",
            ambiguities=ambiguities,
        )
        if mapped and mapped in dimension_candidates and mapped not in resolved:
            resolved.append(mapped)

    question_hints = _extract_dimension_hints(question)
    for hint in question_hints:
        normalized_hint = _clean_dimension_phrase(hint)
        mapped = _resolve_column_name_with_ambiguity(
            candidate=normalized_hint,
            columns=[table_meta["column_map"][c] for c in dimension_candidates],
            context="dimension",
            ambiguities=ambiguities,
        )
        # Avoid over-eager mapping for generic grouping words (e.g., "by order").
        if mapped:
            generic_grouping_terms = {"order", "orders", "item", "items", "record", "records", "data", "value"}
            hint_tokens = _expand_tokens(tokenize(normalized_hint))
            if len(hint_tokens) == 1:
                hint_token = next(iter(hint_tokens))
                normalized_mapped = str(mapped).strip().lower()
                if (
                    hint_token in generic_grouping_terms
                    and normalized_mapped != hint_token
                    and normalized_mapped.startswith(f"{hint_token}_")
                ):
                    ambiguities.append(
                        {
                            "type": "dimension_inference",
                            "message": (
                                f"Grouping phrase '{normalized_hint}' is ambiguous; "
                                f"skipped weak inferred dimension '{mapped}'."
                            ),
                            "candidates": [mapped],
                            "resolution": None,
                        }
                    )
                    mapped = None
        if mapped and mapped not in resolved:
            resolved.append(mapped)

    return resolved


def _normalize_numeric_filter_value(raw_value: str) -> int | float:
    if "." in raw_value:
        return float(raw_value)
    return int(raw_value)


def _filter_column_candidates(candidate_column: str) -> list[str]:
    candidate = re.sub(r"\s+", " ", str(candidate_column or "").strip())
    if not candidate:
        return []

    variants: list[str] = []
    for splitter in (" where ", " with ", " for ", " in ", " and "):
        if splitter in candidate:
            tail = candidate.split(splitter)[-1].strip()
            if tail:
                variants.append(tail)
    tokens = candidate.split(" ")
    if len(tokens) >= 3:
        variants.append(" ".join(tokens[-3:]))
    if len(tokens) >= 2:
        variants.append(" ".join(tokens[-2:]))
    variants.append(tokens[-1])
    variants.append(candidate)

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        key = variant.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(variant)
    return deduped


def _resolve_filter_column(
    candidate_column: str,
    all_columns: list[dict[str, Any]],
    column_map: dict[str, dict[str, Any]],
    *,
    require_numeric: bool,
    ambiguities: list[dict[str, Any]],
) -> str | None:
    for candidate in _filter_column_candidates(candidate_column):
        resolved = _resolve_column_name_with_ambiguity(
            candidate=candidate,
            columns=all_columns,
            context="filter",
            ambiguities=ambiguities,
        )
        if not resolved:
            continue
        if require_numeric and not column_map[resolved].get("is_numeric"):
            continue
        if not require_numeric and column_map[resolved].get("is_numeric"):
            continue
        return resolved
    return None


def _resolve_numeric_filter_column(
    *,
    candidate_column: str,
    all_columns: list[dict[str, Any]],
    column_map: dict[str, dict[str, Any]],
    preferred_numeric_columns: list[str],
    ambiguities: list[dict[str, Any]],
) -> str | None:
    preferred_column_defs = [
        column_map[column_name]
        for column_name in preferred_numeric_columns
        if column_name in column_map
    ]
    if candidate_column and preferred_column_defs:
        preferred_match = _resolve_column_name_with_ambiguity(
            candidate=candidate_column,
            columns=preferred_column_defs,
            context="filter",
            ambiguities=ambiguities,
        )
        if preferred_match and column_map.get(preferred_match, {}).get("is_numeric"):
            return preferred_match

    resolved = _resolve_filter_column(
        candidate_column,
        all_columns,
        column_map,
        require_numeric=True,
        ambiguities=ambiguities,
    )
    if resolved:
        return resolved

    if not candidate_column and len(preferred_numeric_columns) == 1:
        return preferred_numeric_columns[0]
    return None


def _numeric_filter_source_text(match: re.Match[str], *, include_column: bool = False) -> str:
    full = str(match.group(0) or "").strip()
    if include_column:
        return full
    try:
        raw_column = str(match.group(1) or "")
    except IndexError:
        raw_column = ""
    if raw_column and full.lower().startswith(raw_column.lower()):
        return full[len(raw_column):].strip()
    return full


def detect_numeric_filters(
    question_text: str,
    selected_columns: list[str],
    schema_columns: list[dict[str, Any]],
    *,
    ambiguities: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    question_lower = str(question_text or "").strip().lower()
    if not question_lower:
        return []

    ambiguity_list = ambiguities if isinstance(ambiguities, list) else []
    all_columns = [column for column in schema_columns if isinstance(column, dict)]
    column_map = {
        str(column.get("name", "")).strip(): column
        for column in all_columns
        if str(column.get("name", "")).strip()
    }
    preferred_numeric_columns = [
        str(column_name).strip()
        for column_name in selected_columns
        if str(column_name).strip()
        and str(column_name).strip() in column_map
        and bool(column_map[str(column_name).strip()].get("is_numeric"))
    ]

    filters: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for pattern in BETWEEN_FILTER_PATTERNS:
        for match in re.finditer(pattern, question_lower):
            candidate_column = match.group(1).strip()
            column = _resolve_numeric_filter_column(
                candidate_column=candidate_column,
                all_columns=all_columns,
                column_map=column_map,
                preferred_numeric_columns=preferred_numeric_columns,
                ambiguities=ambiguity_list,
            )
            if not column:
                continue
            low = _normalize_numeric_filter_value(match.group(2).strip())
            high = _normalize_numeric_filter_value(match.group(3).strip())
            fingerprint = (column, "BETWEEN", f"{low}|{high}")
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            filters.append(
                {
                    "column": column,
                    "operator": "BETWEEN",
                    "value": [low, high],
                    "source_text": _numeric_filter_source_text(match),
                    "source": "numeric_pattern",
                }
            )

    for pattern_item in NUMERIC_FILTER_PATTERNS:
        pattern = pattern_item["pattern"]
        default_operator = pattern_item["operator"]
        captures_operator = bool(pattern_item["captures_operator"])
        for match in re.finditer(pattern, question_lower):
            candidate_column = match.group(1).strip()
            if captures_operator:
                raw_operator = match.group(2).strip()
                if raw_operator in {"=>", ">="}:
                    normalized_operator = ">="
                elif raw_operator in {"=<", "<="}:
                    normalized_operator = "<="
                elif raw_operator in {"==", "="}:
                    normalized_operator = "="
                else:
                    normalized_operator = default_operator
                raw_value = match.group(3).strip()
            else:
                normalized_operator = default_operator
                raw_value = match.group(2).strip()

            column = _resolve_numeric_filter_column(
                candidate_column=candidate_column,
                all_columns=all_columns,
                column_map=column_map,
                preferred_numeric_columns=preferred_numeric_columns,
                ambiguities=ambiguity_list,
            )
            if not column:
                continue
            value = _normalize_numeric_filter_value(raw_value)
            fingerprint = (column, normalized_operator, str(value))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            filters.append(
                {
                    "column": column,
                    "operator": normalized_operator,
                    "value": value,
                    "source_text": _numeric_filter_source_text(match),
                    "source": "numeric_pattern",
                }
            )

    return filters


def _normalize_filters(
    question: str,
    raw_intent: dict[str, Any],
    table_meta: dict[str, Any],
    *,
    ambiguities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    all_columns = table_meta["columns"]
    column_map = table_meta["column_map"]
    seen: set[tuple[str, str, str]] = set()
    selected_columns = _extract_preselected_columns(raw_intent, table_meta)
    selected_numeric_columns = [
        column_name
        for column_name in selected_columns
        if column_name in column_map and bool(column_map[column_name].get("is_numeric"))
    ]

    for filter_item in raw_intent.get("filters", []) or []:
        if not isinstance(filter_item, dict):
            continue
        column = _resolve_column_name_with_ambiguity(
            candidate=str(filter_item.get("column", "") or filter_item.get("metric", "")),
            columns=all_columns,
            context="filter",
            ambiguities=ambiguities,
        )
        operator = (filter_item.get("operator") or "=").upper().strip()
        value = filter_item.get("value")

        if not column or value is None:
            continue
        if operator not in VALID_FILTER_OPERATORS:
            continue

        if operator == "BETWEEN":
            if isinstance(value, (list, tuple)) and len(value) == 2:
                value = [value[0], value[1]]
            elif isinstance(value, dict):
                low = value.get("low")
                high = value.get("high")
                if low is None or high is None:
                    continue
                value = [low, high]
            else:
                continue

        fingerprint = (column, operator, str(value))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        filters.append(
            {
                "column": column,
                "operator": operator,
                "value": value,
                "source_text": str(filter_item.get("source_text") or "").strip(),
                "source": "intent_filters",
            }
        )

    for sf in raw_intent.get("semantic_filters") or []:
        if not isinstance(sf, dict):
            continue
        hint = str(sf.get("column") or sf.get("metric") or sf.get("metric_hint") or "").strip()
        operator = str(sf.get("operator") or ">").strip().upper()
        value = sf.get("value")
        if not hint or value is None or operator not in VALID_FILTER_OPERATORS:
            continue
        column = _resolve_numeric_filter_column(
            candidate_column=hint,
            all_columns=all_columns,
            column_map=column_map,
            preferred_numeric_columns=selected_numeric_columns,
            ambiguities=ambiguities,
        )
        if not column:
            continue
        fingerprint = (column, operator, str(value))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        filters.append(
            {
                "column": column,
                "operator": operator,
                "value": value,
                "source_text": str(sf.get("source_text") or sf.get("phrase") or "").strip(),
                "source": "semantic_filters",
            }
        )

    question_lower = question.lower()
    for detected_filter in detect_numeric_filters(
        question_text=question_lower,
        selected_columns=selected_columns,
        schema_columns=all_columns,
        ambiguities=ambiguities,
    ):
        if not isinstance(detected_filter, dict):
            continue
        column = str(detected_filter.get("column") or "").strip()
        operator = str(detected_filter.get("operator") or "").strip().upper()
        value = detected_filter.get("value")
        if not column or value is None or operator not in VALID_FILTER_OPERATORS:
            continue
        fingerprint = (
            column,
            operator,
            (
                f"{value[0]}|{value[1]}"
                if operator == "BETWEEN" and isinstance(value, (list, tuple)) and len(value) == 2
                else str(value)
            ),
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        filters.append(detected_filter)

    for pattern in TEXT_FILTER_PATTERNS:
        for match in re.finditer(pattern, question_lower):
            groups = [group.strip() for group in match.groups() if group and group.strip()]
            if len(groups) < 2:
                continue
            if pattern == TEXT_FILTER_PATTERNS[2]:
                value, candidate_column = groups[0], groups[1]
            else:
                candidate_column, value = groups[0], groups[1]
            column = _resolve_filter_column(
                candidate_column,
                all_columns,
                column_map,
                require_numeric=False,
                ambiguities=ambiguities,
            )
            if not column:
                continue
            normalized_value = value.strip(" '\"")
            if not normalized_value:
                continue
            fingerprint = (column, "=", normalized_value)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            filters.append(
                {
                    "column": column,
                    "operator": "=",
                    "value": normalized_value,
                    "source_text": _numeric_filter_source_text(match, include_column=True),
                    "source": "text_pattern",
                }
            )

    for pattern in TEXT_CONTAINS_PATTERNS:
        for match in re.finditer(pattern, question_lower):
            candidate_column = match.group(1).strip()
            raw_value = match.group(2).strip()
            column = _resolve_filter_column(
                candidate_column,
                all_columns,
                column_map,
                require_numeric=False,
                ambiguities=ambiguities,
            )
            if not column:
                continue
            value = raw_value.strip(" '\"")
            if not value:
                continue
            like_value = value if "%" in value else f"%{value}%"
            fingerprint = (column, "LIKE", like_value)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            filters.append(
                {
                    "column": column,
                    "operator": "LIKE",
                    "value": like_value,
                    "source_text": _numeric_filter_source_text(match, include_column=True),
                    "source": "text_pattern",
                }
            )

    for nl_filter in extract_semantic_filters(question):
        operator = str(nl_filter.get("operator") or ">").strip().upper()
        value = nl_filter.get("value")
        hint = str(nl_filter.get("metric_hint") or nl_filter.get("left_context") or "").strip()
        if value is None or operator not in VALID_FILTER_OPERATORS:
            continue
        column = _resolve_numeric_filter_column(
            candidate_column=hint,
            all_columns=all_columns,
            column_map=column_map,
            preferred_numeric_columns=selected_numeric_columns,
            ambiguities=ambiguities,
        )
        if not column:
            continue
        fingerprint = (column, operator, str(value))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        filters.append(
            {
                "column": column,
                "operator": operator,
                "value": value,
                "source_text": str(nl_filter.get("phrase") or "").strip(),
                "source": "semantic_nl",
            }
        )

    return filters


def _infer_year_filter(question_lower: str, table_meta: dict[str, Any]) -> dict[str, Any] | None:
    year_match = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", question_lower)
    if not year_match:
        return None

    year_value = int(year_match.group(1))
    for column in table_meta["date_columns"] + table_meta["dimension_columns"]:
        column_lower = column.lower()
        if "year" in column_lower:
            return {"column": column, "operator": "=", "value": year_value}
    return None


def _normalize_order_by(
    raw_intent: dict[str, Any],
    table_meta: dict[str, Any],
    *,
    metric_aliases: list[str],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    all_columns = table_meta["columns"]
    alias_set = set(metric_aliases)

    for order in raw_intent.get("order_by", []) or []:
        if not isinstance(order, dict):
            continue

        column = order.get("column")
        direction = (order.get("direction") or "ASC").upper()
        if direction not in {"ASC", "DESC"}:
            direction = "ASC"

        if column in alias_set:
            resolved = column
        else:
            resolved = _resolve_column_name(column or "", all_columns)
        if not resolved:
            continue

        result.append({"column": resolved, "direction": direction})

    return result


def _derive_operations(
    *,
    metrics: list[dict[str, Any]],
    dimensions: list[str],
    filters: list[dict[str, Any]],
    order_by: list[dict[str, Any]],
    limit: int | None,
    ranking_requested: bool,
    relationship_requested: bool,
    distribution_requested: bool,
    time_grouping_detected: bool,
) -> list[str]:
    operations: list[str] = ["projection"]

    if any(metric.get("aggregation") for metric in metrics):
        operations.append("aggregation")
    if dimensions:
        operations.append("grouping")
    if filters:
        operations.append("filtering")
    if order_by:
        operations.append("sorting")
    if ranking_requested:
        operations.append("ranking")
    if limit:
        operations.append("limiting")
    if dimensions and len(metrics) > 1:
        operations.append("comparison")
    if relationship_requested:
        operations.append("relationship")
        if "comparison" not in operations:
            operations.append("comparison")
    if distribution_requested:
        operations.append("distribution")
    if time_grouping_detected:
        operations.append("time_grouping")
    if len(metrics) > 1:
        operations.append("multi_metric")

    return operations


def _infer_primary_intent(
    *,
    operations: list[str],
    relationship_requested: bool,
    distribution_requested: bool,
    time_grouping_detected: bool,
) -> str:
    if time_grouping_detected:
        return "time_series"
    if relationship_requested:
        return "correlation"
    if distribution_requested:
        return "distribution"
    if "ranking" in operations:
        return "ranking"
    if "aggregation" in operations and "grouping" in operations:
        return "aggregation"
    if "comparison" in operations:
        return "comparison"
    if "filtering" in operations:
        return "filtering"
    return "projection"
