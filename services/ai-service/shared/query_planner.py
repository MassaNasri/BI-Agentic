import re
from typing import Any

from shared.schema_utils import (
    build_table_metadata,
    is_date_type,
    is_numeric_type,
    tokenize,
    unqualify_table_name,
)


DESC_RANK_KEYWORDS = ("highest", "largest", "most", "top", "maximum", "max", "best")
ASC_RANK_KEYWORDS = ("lowest", "smallest", "least", "bottom", "minimum", "min", "worst")

AVG_KEYWORDS = ("average", "avg", "mean")
COUNT_KEYWORDS = ("count", "how many", "number of")
SUM_KEYWORDS = ("sum", "total")
MAX_KEYWORDS = ("maximum", "max")
MIN_KEYWORDS = ("minimum", "min")

VALID_AGGREGATIONS = {"SUM", "AVG", "COUNT", "MIN", "MAX"}
VALID_FILTER_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "IN", "LIKE"}

RATE_LIKE_TOKENS = ("rate", "ratio", "percent", "percentage", "pct", "share")


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
    table = _resolve_table(question, raw_intent, schema_metadata)
    if not table:
        raise ValueError("Could not resolve target table from schema")

    table_meta = schema_metadata[table]
    question_lower = question.lower()

    dimensions = _infer_dimensions(question, raw_intent, table_meta)
    rank_direction = _detect_rank_direction(question_lower)
    limit = _extract_limit(question_lower)
    if rank_direction and not limit:
        limit = 1

    metric = _infer_metric(
        question=question,
        raw_intent=raw_intent,
        table_meta=table_meta,
        rank_direction=rank_direction,
    )

    if rank_direction:
        metric["aggregation"] = _aggregation_for_ranking(metric["column"], question_lower)
        metric["alias"] = _metric_alias(metric["aggregation"], metric["column"])

    filters = _normalize_filters(raw_intent, table_meta)

    if not filters:
        year_filter = _infer_year_filter(question_lower, table_meta)
        if year_filter:
            filters.append(year_filter)

    order_by = _normalize_order_by(raw_intent, table_meta, metric_alias=metric["alias"])
    if rank_direction:
        order_by = [{"column": metric["alias"], "direction": rank_direction}]
    elif limit and not order_by:
        order_by = [{"column": metric["alias"], "direction": "DESC"}]

    return {
        "table": unqualify_table_name(table),
        "metrics": [metric],
        "dimensions": dimensions,
        "filters": filters,
        "order_by": order_by,
        "limit": limit,
    }


def _resolve_table(
    question: str,
    raw_intent: dict[str, Any],
    schema_metadata: dict[str, dict[str, Any]],
) -> str | None:
    requested = (raw_intent.get("table") or "").strip()
    if requested in schema_metadata:
        return requested
    if requested:
        requested_unqualified = unqualify_table_name(requested).lower()
        unqualified_matches = [
            table
            for table in schema_metadata.keys()
            if unqualify_table_name(table).lower() == requested_unqualified
        ]
        if len(unqualified_matches) == 1:
            return unqualified_matches[0]

    question_tokens = tokenize(question)
    referenced_columns = set()

    for metric in raw_intent.get("metrics", []) or []:
        if isinstance(metric, dict) and metric.get("column"):
            referenced_columns.add(metric["column"])
    for dim in raw_intent.get("dimensions", []) or []:
        if isinstance(dim, str):
            referenced_columns.add(dim)
    for flt in raw_intent.get("filters", []) or []:
        if isinstance(flt, dict) and flt.get("column"):
            referenced_columns.add(flt["column"])
    for order in raw_intent.get("order_by", []) or []:
        if isinstance(order, dict) and order.get("column"):
            referenced_columns.add(order["column"])

    best_table = None
    best_score = -1

    for table, table_meta in schema_metadata.items():
        score = 0
        table_tokens = tokenize(table.split(".")[-1])
        score += len(table_tokens & question_tokens) * 3

        for candidate in referenced_columns:
            if _resolve_column_name(candidate, table_meta["columns"]):
                score += 4

        for col in table_meta["columns"]:
            if tokenize(col["name"]) & question_tokens:
                score += 1

        if requested and requested.lower() in table.lower():
            score += 5

        if score > best_score:
            best_score = score
            best_table = table

    return best_table


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


def _expand_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for token in list(tokens):
        if token.endswith("ies") and len(token) > 4:
            expanded.add(token[:-3] + "y")
        if token.endswith("s") and len(token) > 3:
            expanded.add(token[:-1])
    return expanded


def _detect_rank_direction(question_lower: str) -> str | None:
    if any(keyword in question_lower for keyword in DESC_RANK_KEYWORDS):
        return "DESC"
    if any(keyword in question_lower for keyword in ASC_RANK_KEYWORDS):
        return "ASC"
    return None


def _extract_limit(question_lower: str) -> int | None:
    patterns = (
        r"\btop\s+(\d+)\b",
        r"\bbottom\s+(\d+)\b",
        r"\bfirst\s+(\d+)\b",
        r"\blast\s+(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, question_lower)
        if match:
            value = int(match.group(1))
            if value > 0:
                return value
    return None


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


def _aggregation_for_ranking(column_name: str, question_lower: str) -> str:
    explicit = _detect_explicit_aggregation(question_lower)
    if explicit:
        return explicit
    if _is_rate_like(column_name):
        return "AVG"
    # Requested semantic default: MOST/HIGHEST/LARGEST -> SUM
    return "SUM"


def _metric_alias(aggregation: str, column: str) -> str:
    safe_column = column.replace(".", "_")
    if column == "*":
        safe_column = "rows"
    return f"{aggregation.lower()}_{safe_column}"


def _score_metric_column(column_name: str, question_tokens: set[str]) -> int:
    col_tokens = tokenize(column_name)
    score = len(col_tokens & question_tokens) * 4

    if "_id" in column_name.lower():
        score -= 2

    if _is_rate_like(column_name):
        score += 1

    return score


def _infer_metric(
    *,
    question: str,
    raw_intent: dict[str, Any],
    table_meta: dict[str, Any],
    rank_direction: str | None,
) -> dict[str, str]:
    question_lower = question.lower()
    question_tokens = tokenize(question)
    explicit_agg = _detect_explicit_aggregation(question_lower)

    raw_metrics = raw_intent.get("metrics", []) or []
    numeric_columns = table_meta["numeric_columns"]
    all_columns = table_meta["columns"]

    metric_column = None
    raw_agg = None

    for metric in raw_metrics:
        if not isinstance(metric, dict):
            continue
        resolved = _resolve_column_name(metric.get("column", ""), all_columns)
        if not resolved:
            continue
        metric_column = resolved
        raw_agg = (metric.get("aggregation") or "").upper() or None
        break

    if explicit_agg == "COUNT" and metric_column is None:
        entity_match = re.search(r"\bhow many\s+([a-z_][a-z0-9_ ]*)\b", question_lower)
        if entity_match:
            entity = entity_match.group(1).strip().split(" ")[0]
            metric_column = _resolve_column_name(entity, all_columns)
        if metric_column is None:
            metric_column = "*"

    if metric_column is None:
        if not numeric_columns and explicit_agg != "COUNT":
            raise ValueError("No numeric columns available for aggregation")
        if numeric_columns:
            scored = sorted(
                numeric_columns,
                key=lambda col: _score_metric_column(col, question_tokens),
                reverse=True,
            )
            metric_column = scored[0]
        else:
            metric_column = "*"

    aggregation = explicit_agg
    if aggregation is None and rank_direction:
        aggregation = _aggregation_for_ranking(metric_column, question_lower)
    if aggregation is None:
        if raw_agg in VALID_AGGREGATIONS:
            aggregation = raw_agg
        elif metric_column == "*":
            aggregation = "COUNT"
        else:
            aggregation = "SUM"

    if aggregation != "COUNT" and metric_column not in numeric_columns:
        if metric_column == "*":
            aggregation = "COUNT"
        else:
            resolved_numeric = _resolve_column_name(metric_column, [table_meta["column_map"][c] for c in numeric_columns]) if numeric_columns else None
            if resolved_numeric:
                metric_column = resolved_numeric
            else:
                raise ValueError(
                    f"Metric column '{metric_column}' is not numeric for aggregation '{aggregation}'"
                )

    if aggregation == "COUNT" and metric_column is None:
        metric_column = "*"

    alias = _metric_alias(aggregation, metric_column)
    return {"column": metric_column, "aggregation": aggregation, "alias": alias}


def _clean_dimension_phrase(phrase: str) -> str:
    stop_tokens = {"where", "with", "that", "having", "from", "for", "in", "of"}
    tokens = [t for t in re.findall(r"[a-z0-9_]+", phrase.lower()) if t not in stop_tokens]
    return " ".join(tokens[:3])


def _extract_dimension_hints(question: str) -> list[str]:
    question_lower = question.lower()
    hints: list[str] = []

    by_matches = re.findall(r"\b(?:by|per|across)\s+([a-z_][a-z0-9_ ]+)", question_lower)
    hints.extend(by_matches)

    each_matches = re.findall(r"\b(?:in each|for each)\s+([a-z_][a-z0-9_ ]+)", question_lower)
    hints.extend(each_matches)

    which_match = re.search(r"\b(?:which|what)\s+([a-z_][a-z0-9_ ]+?)\s+(?:has|have|with|shows|is|are)\b", question_lower)
    if which_match:
        hints.append(which_match.group(1))

    return [_clean_dimension_phrase(h) for h in hints if h.strip()]


def _infer_dimensions(
    question: str,
    raw_intent: dict[str, Any],
    table_meta: dict[str, Any],
) -> list[str]:
    all_columns = table_meta["columns"]
    dimension_candidates = table_meta["dimension_columns"] + table_meta["date_columns"]
    resolved: list[str] = []

    for dim in raw_intent.get("dimensions", []) or []:
        if not isinstance(dim, str):
            continue
        mapped = _resolve_column_name(dim, all_columns)
        if mapped and mapped in dimension_candidates and mapped not in resolved:
            resolved.append(mapped)

    question_hints = _extract_dimension_hints(question)
    for hint in question_hints:
        mapped = _resolve_column_name(hint, [table_meta["column_map"][c] for c in dimension_candidates])
        if mapped and mapped not in resolved:
            resolved.append(mapped)

    return resolved


def _normalize_filters(raw_intent: dict[str, Any], table_meta: dict[str, Any]) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    all_columns = table_meta["columns"]

    for filter_item in raw_intent.get("filters", []) or []:
        if not isinstance(filter_item, dict):
            continue
        column = _resolve_column_name(filter_item.get("column", ""), all_columns)
        operator = (filter_item.get("operator") or "=").upper().strip()
        value = filter_item.get("value")

        if not column or value is None:
            continue
        if operator not in VALID_FILTER_OPERATORS:
            continue

        filters.append({"column": column, "operator": operator, "value": value})

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
    metric_alias: str,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    all_columns = table_meta["columns"]

    for order in raw_intent.get("order_by", []) or []:
        if not isinstance(order, dict):
            continue

        column = order.get("column")
        direction = (order.get("direction") or "ASC").upper()
        if direction not in {"ASC", "DESC"}:
            direction = "ASC"

        if column == metric_alias:
            resolved = metric_alias
        else:
            resolved = _resolve_column_name(column or "", all_columns)
        if not resolved:
            continue

        result.append({"column": resolved, "direction": direction})

    return result
