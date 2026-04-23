import os
import re
from typing import Any

from shared.schema_utils import is_numeric_type, normalize_table_name, unqualify_table_name

VALID_AGGREGATIONS = {"SUM", "AVG", "COUNT", "MIN", "MAX"}
VALID_DIRECTIONS = {"ASC", "DESC"}
VALID_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "IN", "LIKE", "BETWEEN"}
TIME_GRANULARITY_EXPRESSIONS = {
    "day": "toDate({column})",
    "week": "toStartOfWeek({column})",
    "month": "toStartOfMonth({column})",
    "quarter": "toStartOfQuarter({column})",
    "year": "toYear({column})",
}
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


def compile_sql(intent: dict[str, Any], schema: dict[str, list[dict[str, Any]]]) -> str:
    raw_table = intent.get("table")
    if not raw_table:
        raise ValueError("Intent is missing table name")
    default_db = os.getenv("CLICKHOUSE_DATABASE", "etl")

    from_table = _normalize_and_validate_table_name(raw_table, default_db)
    schema_table = _resolve_schema_table_name(raw_table, schema)
    if not schema_table:
        schema_table = _resolve_schema_table_name(unqualify_table_name(from_table), schema)
    if not schema_table:
        raise ValueError(f"Table '{raw_table}' does not exist in schema")

    columns = schema[schema_table]
    column_map = {col["name"]: col for col in columns}

    metrics = intent.get("metrics") or []
    if not metrics:
        raise ValueError("Intent must contain at least one metric")

    dimensions = intent.get("dimensions") or []
    filters = intent.get("filters") or []
    order_by = intent.get("order_by") or []
    limit = intent.get("limit")
    type_cast_map = _build_type_cast_map(intent.get("type_casting") or intent.get("type_casting_needed") or [])
    time_granularity = str(intent.get("time_granularity", "")).strip().lower()
    time_column = str(intent.get("time_column", "")).strip()
    time_grouping_detected = bool(intent.get("time_grouping_detected"))
    row_count_requested = bool(intent.get("row_count_requested"))
    time_dimension_alias = str(intent.get("time_dimension_alias", "")).strip() or "period"
    time_dimension_expression = str(intent.get("time_dimension_expression", "")).strip()
    explicit_top_n_requested = bool(intent.get("explicit_top_n_requested"))
    if (
        time_grouping_detected
        and time_granularity in TIME_GRANULARITY_EXPRESSIONS
        and time_column
    ):
        time_dimension_expression = _build_time_dimension_expression(
            granularity=time_granularity,
            column_name=time_column,
            column_map=column_map,
        )

    select_parts: list[str] = []
    group_by_parts: list[str] = []
    metric_aliases: dict[str, str] = {}
    dimension_aliases: dict[str, str] = {}
    alias_by_column: dict[str, list[str]] = {}
    has_aggregated_metric = False

    for dim in dimensions:
        if dim not in column_map:
            raise ValueError(f"Dimension column '{dim}' does not exist in table '{schema_table}'")
        if (
            time_grouping_detected
            and time_dimension_expression
            and time_column
            and dim == time_column
        ):
            select_parts.append(f"{time_dimension_expression} AS {time_dimension_alias}")
            group_by_parts.append(time_dimension_alias)
            dimension_aliases[time_dimension_alias] = time_dimension_alias
            continue
        select_parts.append(dim)
        group_by_parts.append(dim)
        dimension_aliases[dim] = dim

    for metric in metrics:
        if not isinstance(metric, dict):
            raise ValueError("Each metric in IR must be an object")

        column = metric.get("column")
        formula = metric.get("formula") if isinstance(metric.get("formula"), dict) else {}
        raw_aggregation = metric.get("aggregation")
        aggregation = (raw_aggregation or "").upper()
        if aggregation in {"", "NONE", "NULL"}:
            aggregation = ""
        if (
            aggregation == "COUNT"
            and not row_count_requested
            and isinstance(column, str)
            and column != "*"
            and _is_business_metric_column_name(column)
            and is_numeric_type(column_map.get(column, {}).get("type", ""))
        ):
            aggregation = "SUM"
        alias = metric.get("alias") or _default_metric_alias(aggregation, column)

        if formula:
            expression, formula_uses_aggregation = _compile_formula_expression(
                formula=formula,
                column_map=column_map,
                type_cast_map=type_cast_map,
            )
            has_aggregated_metric = has_aggregated_metric or formula_uses_aggregation
        else:
            if aggregation and aggregation not in VALID_AGGREGATIONS:
                raise ValueError(f"Unsupported aggregation '{aggregation}'")

            if column == "*":
                if aggregation not in {"COUNT", ""}:
                    raise ValueError("Only COUNT supports '*' metric column")
                expression = "COUNT(*)" if aggregation == "COUNT" else "*"
            else:
                if column not in column_map:
                    raise ValueError(f"Metric column '{column}' does not exist in table '{schema_table}'")
                cast_target = type_cast_map.get(column)
                metric_expr = _metric_expression(column=column, cast_target=cast_target)
                if aggregation and aggregation != "COUNT" and not (
                    cast_target or is_numeric_type(column_map[column].get("type", ""))
                ):
                    raise ValueError(
                        f"Aggregation '{aggregation}' requires numeric column, got '{column}' ({column_map[column].get('type')})"
                    )
                if aggregation:
                    expression = f"{aggregation}({metric_expr})"
                    has_aggregated_metric = True
                else:
                    expression = metric_expr

        if alias and alias != expression:
            select_parts.append(f"{expression} AS {alias}")
            if column:
                alias_by_column.setdefault(str(column), []).append(alias)
            metric_aliases[alias] = alias
        else:
            select_parts.append(expression)
            if column:
                alias_by_column.setdefault(str(column), []).append(str(column))
            if isinstance(column, str):
                metric_aliases[column] = column

    for column_name, aliases in alias_by_column.items():
        unique_aliases = [alias for alias in aliases if alias]
        if len(set(unique_aliases)) == 1:
            metric_aliases[column_name] = unique_aliases[0]

    if select_parts:
        deduped_select_parts: list[str] = []
        seen_select_parts: set[str] = set()
        for part in select_parts:
            if part in seen_select_parts:
                continue
            seen_select_parts.add(part)
            deduped_select_parts.append(part)
        select_parts = deduped_select_parts

    if not select_parts:
        raise ValueError("SQL generation failed: empty SELECT list")

    if has_aggregated_metric:
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            aggregation = (metric.get("aggregation") or "").upper()
            if aggregation in {"", "NONE", "NULL"}:
                column = metric.get("column")
                if column and column != "*" and column not in group_by_parts:
                    group_by_parts.append(column)

    ranking_payload = intent.get("ranking") if isinstance(intent.get("ranking"), dict) else {}
    ranking_requested = bool(str(ranking_payload.get("direction", "")).strip().upper() in VALID_DIRECTIONS)
    limit_present = isinstance(limit, int) and limit > 0
    explicit_intent = str(intent.get("intent", "")).strip().lower()
    operations = intent.get("operations") if isinstance(intent.get("operations"), list) else []
    kpi_allowed = bool(intent.get("kpi_allowed_without_dimension", False))
    if "overall" in explicit_intent:
        kpi_allowed = True

    if has_aggregated_metric and ranking_requested and limit_present and not group_by_parts and not kpi_allowed:
        inferable_dimension = _infer_groupable_dimension(columns)
        if inferable_dimension:
            raise ValueError(
                "Unsafe ranking SQL shape: aggregation with LIMIT requires GROUP BY when a dimension is inferable."
            )
    if has_aggregated_metric and limit_present and "ranking" in {str(op).lower() for op in operations} and not group_by_parts and not kpi_allowed:
        inferable_dimension = _infer_groupable_dimension(columns)
        if inferable_dimension:
            raise ValueError(
                "Unsafe ranking SQL shape: LIMIT + aggregation without GROUP BY is blocked."
            )
    if has_aggregated_metric and time_grouping_detected and time_dimension_alias not in group_by_parts:
        raise ValueError("Unsafe time-grouped SQL shape: aggregation over time requires GROUP BY transformed time dimension.")

    where_clause = _build_where_clause(filters, column_map, type_cast_map)
    if has_aggregated_metric and time_grouping_detected and time_dimension_alias:
        order_by = [{"column": time_dimension_alias, "direction": "ASC"}]
    if time_grouping_detected and not explicit_top_n_requested:
        limit = None
    order_clause = _build_order_clause(order_by, column_map, metric_aliases, dimension_aliases)
    limit_clause = _build_limit_clause(limit)

    sql_parts = [
        _format_select_clause(select_parts),
        f"FROM {from_table}",
    ]
    if where_clause:
        sql_parts.append(where_clause)
    if has_aggregated_metric and group_by_parts:
        sql_parts.append(f"GROUP BY {', '.join(group_by_parts)}")
    if order_clause:
        sql_parts.append(order_clause)
    if limit_clause:
        sql_parts.append(limit_clause)

    final_sql = "\n".join(sql_parts) + ";"
    final_sql = _normalize_clickhouse_date_casts(final_sql)
    _validate_sql_structure(final_sql)
    return final_sql


def _resolve_schema_table_name(table_name: str, schema: dict[str, list[dict[str, Any]]]) -> str | None:
    if not table_name:
        return None
    if table_name in schema:
        return table_name

    table_unqualified = unqualify_table_name(table_name).lower()
    matches = [key for key in schema.keys() if unqualify_table_name(key).lower() == table_unqualified]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous table name '{table_name}'. Matches: {', '.join(matches)}"
        )
    return None


def _normalize_and_validate_table_name(table_name: str, default_db: str) -> str:
    normalized = normalize_table_name(table_name, default_db)
    segments = [seg for seg in normalized.split(".") if seg]

    # Defensive guard against malformed db.db.table patterns.
    if len(segments) >= 3 and segments[0].lower() == segments[1].lower():
        normalized = normalize_table_name(".".join(segments[1:]), default_db)
        segments = [seg for seg in normalized.split(".") if seg]

    if len(segments) != 2:
        raise ValueError(f"Invalid table reference '{table_name}' after normalization -> '{normalized}'")
    return normalized


def _default_metric_alias(aggregation: str, column: str) -> str:
    safe_column = (column or "metric").replace(".", "_")
    if safe_column == "*":
        safe_column = "rows"
    if not aggregation:
        return safe_column
    return f"{aggregation.lower()}_{safe_column}"


def _build_type_cast_map(type_casting: list[dict[str, Any]]) -> dict[str, str]:
    cast_map: dict[str, str] = {}
    for cast_item in type_casting:
        if not isinstance(cast_item, dict):
            continue
        column = str(cast_item.get("column", "")).strip()
        target = str(cast_item.get("required_cast", "")).strip().upper()
        if not column or not target:
            continue
        cast_map[column] = target
    return cast_map


def _metric_expression(*, column: str, cast_target: str | None) -> str:
    if cast_target:
        return f"CAST({column} AS {cast_target})"
    return column


def _resolve_formula_operand_expression(
    *,
    operand: dict[str, Any],
    column_map: dict[str, dict[str, Any]],
    type_cast_map: dict[str, str],
) -> tuple[str, bool]:
    column = str(operand.get("column", "")).strip()
    if not column:
        raise ValueError("Formula operand is missing column")
    if column not in column_map:
        raise ValueError(f"Formula column '{column}' does not exist in selected table")
    aggregation = str(operand.get("aggregation", "")).strip().upper()
    cast_target = type_cast_map.get(column)
    metric_expr = _metric_expression(column=column, cast_target=cast_target)
    if aggregation:
        if aggregation not in VALID_AGGREGATIONS:
            raise ValueError(f"Unsupported aggregation '{aggregation}' in formula operand")
        if aggregation != "COUNT" and not (cast_target or is_numeric_type(column_map[column].get("type", ""))):
            raise ValueError(
                f"Aggregation '{aggregation}' requires numeric column, got '{column}' ({column_map[column].get('type')})"
            )
        return f"{aggregation}({metric_expr})", True
    return metric_expr, False


def _compile_formula_expression(
    *,
    formula: dict[str, Any],
    column_map: dict[str, dict[str, Any]],
    type_cast_map: dict[str, str],
) -> tuple[str, bool]:
    formula_type = str(formula.get("type", "")).strip().lower()
    if formula_type != "ratio":
        raise ValueError(f"Unsupported metric formula type '{formula_type}'")
    numerator = formula.get("numerator") if isinstance(formula.get("numerator"), dict) else {}
    denominator = formula.get("denominator") if isinstance(formula.get("denominator"), dict) else {}
    numerator_expr, numerator_agg = _resolve_formula_operand_expression(
        operand=numerator,
        column_map=column_map,
        type_cast_map=type_cast_map,
    )
    denominator_expr, denominator_agg = _resolve_formula_operand_expression(
        operand=denominator,
        column_map=column_map,
        type_cast_map=type_cast_map,
    )
    safe_division = bool(formula.get("safe_division", True))
    denominator_sql = f"NULLIF({denominator_expr}, 0)" if safe_division else denominator_expr
    return f"({numerator_expr} / {denominator_sql})", numerator_agg or denominator_agg


def _format_filter_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        formatted = ", ".join(_format_filter_value(v) for v in value)
        return f"({formatted})"
    value_str = str(value).replace("'", "''")
    return f"'{value_str}'"


def _build_where_clause(
    filters: list[dict[str, Any]],
    column_map: dict[str, dict[str, Any]],
    type_cast_map: dict[str, str],
) -> str:
    clauses = []
    for filter_item in filters:
        if not isinstance(filter_item, dict):
            raise ValueError("Each filter in IR must be an object")
        column = filter_item.get("column")
        operator = (filter_item.get("operator") or "=").upper()
        value = filter_item.get("value")

        if not column:
            raise ValueError("Filter is missing required field 'column'")
        if column not in column_map:
            raise ValueError(f"Filter column '{column}' does not exist in selected table")
        if value is None:
            raise ValueError(f"Filter for column '{column}' is missing a value")
        if operator not in VALID_OPERATORS:
            raise ValueError(f"Unsupported filter operator '{operator}' for column '{column}'")

        filter_expr = _metric_expression(column=column, cast_target=type_cast_map.get(column))

        if operator == "IN":
            if not isinstance(value, list):
                value = [value]
            if not value:
                raise ValueError(f"Filter column '{column}' uses IN with an empty value list")
            value_sql = _format_filter_value(value)
            clauses.append(f"{filter_expr} IN {value_sql}")
        elif operator == "BETWEEN":
            if isinstance(value, (list, tuple)) and len(value) == 2:
                low_value, high_value = value[0], value[1]
            elif isinstance(value, dict):
                low_value = value.get("low")
                high_value = value.get("high")
            else:
                raise ValueError(
                    f"Filter column '{column}' uses BETWEEN but value must be [low, high] or {{low, high}}"
                )
            if low_value is None or high_value is None:
                raise ValueError(f"Filter column '{column}' uses BETWEEN but one boundary is missing")
            low_sql = _format_filter_value(low_value)
            high_sql = _format_filter_value(high_value)
            clauses.append(f"{filter_expr} BETWEEN {low_sql} AND {high_sql}")
        else:
            value_sql = _format_filter_value(value)
            clauses.append(f"{filter_expr} {operator} {value_sql}")

    if not clauses:
        return ""
    return "WHERE " + " AND ".join(clauses)


def _build_order_clause(
    order_by: list[dict[str, Any]],
    column_map: dict[str, dict[str, Any]],
    metric_aliases: dict[str, str],
    dimension_aliases: dict[str, str],
) -> str:
    clauses = []
    for order_item in order_by:
        if not isinstance(order_item, dict):
            raise ValueError("Each ORDER BY item in IR must be an object")
        raw_column = order_item.get("column")
        direction = (order_item.get("direction") or "ASC").upper()
        if direction not in VALID_DIRECTIONS:
            direction = "ASC"
        if not raw_column:
            raise ValueError("ORDER BY item is missing required field 'column'")

        column = metric_aliases.get(raw_column, raw_column)
        if (
            column not in metric_aliases.values()
            and column not in dimension_aliases.values()
            and column not in column_map
        ):
            raise ValueError(f"ORDER BY column '{raw_column}' is not present in metrics, aliases, or table columns")
        clauses.append(f"{column} {direction}")

    if not clauses:
        return ""
    return "ORDER BY " + ", ".join(clauses)


def _build_limit_clause(limit: Any) -> str:
    if isinstance(limit, int) and limit > 0:
        return f"LIMIT {limit}"
    return ""


def _format_select_clause(select_parts: list[str]) -> str:
    if not select_parts:
        raise ValueError("SQL generation failed: empty SELECT list")
    if len(select_parts) == 1:
        return f"SELECT {select_parts[0]}"
    head = select_parts[0]
    tail = ",\n       ".join(select_parts[1:])
    return f"SELECT {head},\n       {tail}"


def _validate_sql_structure(sql: str) -> None:
    sql_upper = sql.upper()
    if not re.search(r"\bSELECT\b", sql_upper):
        raise ValueError("SQL must contain SELECT")
    if not re.search(r"\bFROM\b", sql_upper):
        raise ValueError("SQL must contain FROM")
    if "GROUP BY ;" in sql_upper or "ORDER BY ;" in sql_upper:
        raise ValueError("SQL contains empty GROUP BY/ORDER BY clause")


def _is_string_like_type(column_type: str) -> bool:
    lowered = str(column_type or "").strip().lower()
    return any(token in lowered for token in ("string", "fixedstring", "varchar", "char"))


def _is_business_metric_column_name(column_name: str) -> bool:
    lowered = str(column_name or "").strip().lower()
    return any(token in lowered for token in BUSINESS_METRIC_HINT_TOKENS)


def _normalize_clickhouse_date_casts(sql: str) -> str:
    normalized = str(sql or "").strip()
    if not normalized:
        return normalized

    previous = ""
    while normalized != previous:
        previous = normalized
        normalized = re.sub(
            r"toDate\(\s*toDate\(\s*([^)]+?)\s*\)\s*\)",
            r"toDate(\1)",
            normalized,
            flags=re.IGNORECASE,
        )

    return normalized


def _build_time_dimension_expression(
    *,
    granularity: str,
    column_name: str,
    column_map: dict[str, dict[str, Any]],
) -> str:
    template = TIME_GRANULARITY_EXPRESSIONS.get(granularity, "")
    if not template or not column_name:
        return ""
    column_type = str(column_map.get(column_name, {}).get("type", "")).strip().lower()
    base_column = column_name
    if _is_string_like_type(column_type):
        base_column = f"toDate({column_name})"
    expression = template.format(column=base_column)
    return _normalize_clickhouse_date_casts(expression)


def _infer_groupable_dimension(columns: list[dict[str, Any]]) -> str | None:
    date_candidates: list[str] = []
    categorical_candidates: list[str] = []
    for col in columns:
        name = str(col.get("name", "")).strip()
        if not name:
            continue
        col_type = str(col.get("type", "")).strip()
        lowered = name.lower()
        if lowered in {"ds", "date", "timestamp", "created_at"} or "date" in lowered or "time" in lowered:
            date_candidates.append(name)
            continue
        if not is_numeric_type(col_type):
            categorical_candidates.append(name)

    if date_candidates:
        ranked = sorted(date_candidates, key=lambda c: (0 if c.lower() in {"ds", "date", "timestamp", "created_at"} else 1, c.lower()))
        return ranked[0]

    if categorical_candidates:
        preferred = ("region", "product", "category", "city")
        ranked = sorted(
            categorical_candidates,
            key=lambda c: (
                next(
                    (
                        idx
                        for idx, token in enumerate(preferred)
                        if token == c.lower() or c.lower().startswith(f"{token}_") or c.lower().endswith(f"_{token}") or token in c.lower()
                    ),
                    len(preferred),
                ),
                c.lower(),
            ),
        )
        return ranked[0]

    return None
