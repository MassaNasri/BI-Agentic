
import re
from typing import Any

from shared.schema_filtering import is_technical_table_name
from shared.schema_utils import (
    build_table_metadata,
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

VALID_AGGREGATIONS = {"SUM", "AVG", "COUNT", "MIN", "MAX"}
VALID_FILTER_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "IN", "LIKE", "BETWEEN"}

RATE_LIKE_TOKENS = ("rate", "ratio", "percent", "percentage", "pct", "share")
AVG_LIKE_TOKENS = ("avg", "average", "mean", "median")
ADDITIVE_HINT_TOKENS = ("total", "count", "population", "amount", "sales", "revenue", "cost", "profit")
IDENTIFIER_LIKE_TOKENS = ("id", "code", "uuid", "key", "number", "num")

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


def build_schema_metadata(schema: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for table, columns in schema.items():
        normalized_columns = []
        for col in columns:
            col_type = col.get("type", "")
            normalized_columns.append(
                {
                    "name": col["name"],
                    "type": col_type,
                    "is_numeric": col.get("is_numeric", is_numeric_type(col_type)),
                    "is_date": col.get("is_date", is_date_type(col_type)),
                    "is_dimension": col.get(
                        "is_dimension",
                        not is_numeric_type(col_type) and not is_date_type(col_type),
                    ),
                }
            )
        metadata[table] = build_table_metadata(normalized_columns)
    return metadata


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

    table = _resolve_table(question, raw_intent, schema_metadata, ambiguities=ambiguities)
    if not table:
        raise ValueError("Could not resolve target table from schema")

    table_meta = schema_metadata[table]
    question_lower = question.lower()

    dimensions = _infer_dimensions(question, raw_intent, table_meta, ambiguities=ambiguities)

    ranking = _infer_ranking(question_lower=question_lower, raw_intent=raw_intent)
    limit = ranking["limit"]

    filters = _normalize_filters(question, raw_intent, table_meta, ambiguities=ambiguities)
    if not filters:
        year_filter = _infer_year_filter(question_lower, table_meta)
        if year_filter:
            filters.append(year_filter)

    metrics = _infer_metrics(
        question=question,
        raw_intent=raw_intent,
        table_meta=table_meta,
        dimensions=dimensions,
        ranking=ranking,
        ambiguities=ambiguities,
    )
    if not metrics:
        metrics = [{"column": "*", "aggregation": "COUNT", "alias": _metric_alias("COUNT", "*")}]

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

    operations = _derive_operations(metrics=metrics, dimensions=dimensions, filters=filters, order_by=order_by, limit=limit)
    primary_intent = _infer_primary_intent(operations)

    aggregations = {str(metric.get("aggregation") or "").upper() for metric in metrics if metric.get("aggregation")}
    if len(aggregations) == 1:
        aggregation_summary: str | None = next(iter(aggregations))
    elif len(aggregations) > 1:
        aggregation_summary = "MIXED"
    else:
        aggregation_summary = None

    return {
        "table": unqualify_table_name(table),
        "intent": primary_intent,
        "operations": operations,
        "dimensions": dimensions,
        "metrics": metrics,
        "filters": filters,
        "aggregation": aggregation_summary,
        "ranking": {
            "direction": ranking["direction"],
            "requested": bool(ranking["direction"]),
            "source": ranking["source"],
        },
        "order_by": order_by,
        "limit": limit,
        "ambiguities": ambiguities,
        "reasoning_version": "semantic_ir_v1",
    }
def _resolve_table(
    question: str,
    raw_intent: dict[str, Any],
    schema_metadata: dict[str, dict[str, Any]],
    *,
    ambiguities: list[dict[str, Any]],
) -> str | None:
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
    candidate_tokens = _expand_tokens(tokenize(candidate))
    if not candidate_tokens:
        return _resolve_column_name(candidate, columns)

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

    return _resolve_column_name(candidate, columns)


def _expand_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for token in list(tokens):
        if token.endswith("ies") and len(token) > 4:
            expanded.add(token[:-3] + "y")
        if token.endswith("s") and len(token) > 3:
            expanded.add(token[:-1])
    return expanded


def _detect_rank_direction(question_lower: str) -> str | None:
    has_desc = any(keyword in question_lower for keyword in DESC_RANK_KEYWORDS)
    has_asc = any(keyword in question_lower for keyword in ASC_RANK_KEYWORDS)
    if has_desc and has_asc:
        # In mixed phrasing (e.g. "top ... worst"), explicit low-end terms should win.
        return "ASC"
    if has_desc:
        return "DESC"
    if has_asc:
        return "ASC"
    return None


def _extract_limit(question_lower: str, raw_intent: dict[str, Any]) -> int | None:
    raw_limit = raw_intent.get("limit")
    if isinstance(raw_limit, int) and raw_limit > 0:
        return raw_limit

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
                return value
    return None


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

    limit = _extract_limit(question_lower, raw_intent)
    implied_limit = 1 if direction and limit is None else None

    return {
        "direction": direction,
        "limit": limit,
        "implied_limit": implied_limit,
        "source": source,
    }
def _detect_explicit_aggregation(question_lower: str) -> str | None:
    if any(k in question_lower for k in AVG_KEYWORDS):
        return "AVG"
    if any(k in question_lower for k in COUNT_KEYWORDS):
        return "COUNT"
    if any(k in question_lower for k in SUM_KEYWORDS):
        return "SUM"
    if any(k in question_lower for k in MAX_KEYWORDS):
        return "MAX"
    if any(k in question_lower for k in MIN_KEYWORDS):
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


def _aggregation_for_ranking(column_name: str, question_lower: str, has_dimensions: bool) -> str | None:
    explicit = _detect_explicit_aggregation(question_lower)
    if explicit:
        return explicit
    if _is_rate_like(column_name) or _is_avg_like(column_name):
        return "AVG"
    if has_dimensions:
        return "SUM"
    return None


def _has_grouping_intent(question_lower: str) -> bool:
    return bool(
        re.search(
            r"\b(by|per|across|for each|in each|top|bottom|highest|lowest|largest|smallest|best|worst)\b",
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
    col_tokens = tokenize(column_name)
    score = len(col_tokens & question_tokens) * 4

    if "_id" in column_name.lower() or _looks_identifier_like(column_name):
        score -= 2
    if _is_rate_like(column_name):
        score += 1
    if _looks_additive(column_name):
        score += 1

    return score


def _extract_metric_hints_from_question(question: str) -> list[str]:
    question_lower = question.lower()
    hints: list[str] = []

    select_match = re.search(
        r"\b(?:show|list|display|give|what is|what are|which)\s+(.+?)(?:\s+\bby\b|\s+\bwhere\b|\s+\bin\b|\s+\bwith\b|$)",
        question_lower,
    )
    if select_match:
        projected_part = select_match.group(1)
        projected_part = re.sub(
            r"\b(the|a|an|all|total|overall|top\s+\d+|bottom\s+\d+)\b",
            " ",
            projected_part,
        )
        for chunk in re.split(r"\band\b|,", projected_part):
            hint = chunk.strip()
            if hint and hint not in {"the", "a", "an"}:
                hints.append(hint)

    by_match = re.search(
        r"\bby\s+([a-z_][a-z0-9_ ]+?)(?:\s+\bwhere\b|\s+\bwith\b|\s+\bin\b|$)",
        question_lower,
    )
    if by_match:
        hints.extend(h.strip() for h in re.split(r"\band\b|,", by_match.group(1)) if h.strip())

    rank_metric_match = re.search(
        r"\b(?:highest|lowest|largest|smallest|best|worst)\s+([a-z_][a-z0-9_ ]+)\b",
        question_lower,
    )
    if rank_metric_match:
        hints.append(rank_metric_match.group(1).strip())

    return hints


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
    ranking: dict[str, Any],
    ambiguities: list[dict[str, Any]],
) -> list[dict[str, str | None]]:
    question_lower = question.lower()
    question_tokens = tokenize(question)
    explicit_agg = _detect_explicit_aggregation(question_lower)
    grouping_intent = _has_grouping_intent(question_lower) or bool(dimensions)

    numeric_columns = table_meta["numeric_columns"]
    all_columns = table_meta["columns"]

    metric_candidates: list[tuple[str, str | None]] = []
    seen_columns: set[str] = set()

    for raw_column, raw_agg in _iter_raw_metric_candidates(raw_intent):
        resolved = _resolve_column_name_with_ambiguity(
            candidate=raw_column,
            columns=all_columns,
            context="metric",
            ambiguities=ambiguities,
        )
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
                metric_candidates.append((metric_column, "COUNT"))
        if not metric_candidates:
            metric_candidates.append(("*", "COUNT"))

    if not metric_candidates:
        if resolved_any_hints and explicit_agg is None:
            for resolved_hint in resolved_any_hints:
                if resolved_hint not in seen_columns:
                    metric_candidates.append((resolved_hint, None))
                    seen_columns.add(resolved_hint)
        if numeric_columns:
            scored = sorted(
                numeric_columns,
                key=lambda col: _score_metric_column(col, question_tokens),
                reverse=True,
            )
            if not metric_candidates:
                metric_candidates.append((scored[0], None))
        else:
            if not metric_candidates:
                metric_candidates.append(("*", "COUNT"))

    metrics: list[dict[str, str | None]] = []
    for metric_column, raw_agg in metric_candidates:
        aggregation: str | None = explicit_agg

        if aggregation is None and ranking.get("direction"):
            aggregation = _aggregation_for_ranking(
                metric_column,
                question_lower,
                has_dimensions=bool(dimensions),
            )

        if aggregation is None and raw_agg in VALID_AGGREGATIONS:
            aggregation = raw_agg
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
                if _looks_additive(metric_column):
                    aggregation = "SUM"
                elif _looks_identifier_like(metric_column):
                    aggregation = "COUNT"
                elif metric_column in numeric_columns:
                    aggregation = "SUM"
                else:
                    aggregation = None
            else:
                aggregation = None

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
def _clean_dimension_phrase(phrase: str) -> str:
    stop_tokens = {"where", "with", "that", "having", "from", "for", "in", "of", "the"}
    tokens = [t for t in re.findall(r"[a-z0-9_]+", phrase.lower()) if t not in stop_tokens]
    return " ".join(tokens[:4])


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
        mapped = _resolve_column_name_with_ambiguity(
            candidate=hint,
            columns=[table_meta["column_map"][c] for c in dimension_candidates],
            context="dimension",
            ambiguities=ambiguities,
        )
        if mapped and mapped not in resolved:
            resolved.append(mapped)

    if not resolved and _has_grouping_intent(question.lower()) and dimension_candidates:
        fallback_dimension = dimension_candidates[0]
        resolved.append(fallback_dimension)
        ambiguities.append(
            {
                "type": "dimension_inference",
                "message": "Grouping intent detected without explicit dimension; applied safe default.",
                "candidates": dimension_candidates[:3],
                "resolution": fallback_dimension,
            }
        )

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

    for filter_item in raw_intent.get("filters", []) or []:
        if not isinstance(filter_item, dict):
            continue
        column = _resolve_column_name_with_ambiguity(
            candidate=str(filter_item.get("column", "")),
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
        filters.append({"column": column, "operator": operator, "value": value})

    question_lower = question.lower()

    for pattern in BETWEEN_FILTER_PATTERNS:
        for match in re.finditer(pattern, question_lower):
            candidate_column = match.group(1).strip()
            column = _resolve_filter_column(
                candidate_column,
                all_columns,
                column_map,
                require_numeric=True,
                ambiguities=ambiguities,
            )
            if not column:
                continue
            low = _normalize_numeric_filter_value(match.group(2).strip())
            high = _normalize_numeric_filter_value(match.group(3).strip())
            low_fingerprint = (column, ">=", str(low))
            high_fingerprint = (column, "<=", str(high))
            if low_fingerprint not in seen:
                seen.add(low_fingerprint)
                filters.append({"column": column, "operator": ">=", "value": low})
            if high_fingerprint not in seen:
                seen.add(high_fingerprint)
                filters.append({"column": column, "operator": "<=", "value": high})

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
            column = _resolve_filter_column(
                candidate_column,
                all_columns,
                column_map,
                require_numeric=True,
                ambiguities=ambiguities,
            )
            if not column:
                continue
            value = _normalize_numeric_filter_value(raw_value)
            fingerprint = (column, normalized_operator, str(value))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            filters.append({"column": column, "operator": normalized_operator, "value": value})

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
            filters.append({"column": column, "operator": "=", "value": normalized_value})

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
            filters.append({"column": column, "operator": "LIKE", "value": like_value})

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
) -> list[str]:
    operations: list[str] = ["projection"]

    if any(metric.get("aggregation") for metric in metrics):
        operations.append("aggregation")
    if dimensions:
        operations.append("grouping")
    if filters:
        operations.append("filtering")
    if order_by:
        operations.append("ranking")
    if limit:
        operations.append("limiting")
    if dimensions and len(metrics) > 1:
        operations.append("comparison")

    return operations


def _infer_primary_intent(operations: list[str]) -> str:
    if "ranking" in operations:
        return "ranking"
    if "aggregation" in operations and "grouping" in operations:
        return "aggregation"
    if "filtering" in operations:
        return "filtering"
    return "projection"
