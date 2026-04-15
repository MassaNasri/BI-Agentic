import os
import re
from typing import Any

from shared.schema_utils import is_numeric_type, normalize_table_name, unqualify_table_name

VALID_AGGREGATIONS = {"SUM", "AVG", "COUNT", "MIN", "MAX"}
VALID_DIRECTIONS = {"ASC", "DESC"}
VALID_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "IN", "LIKE", "BETWEEN"}


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

    select_parts: list[str] = []
    group_by_parts: list[str] = []
    metric_aliases: dict[str, str] = {}
    alias_by_column: dict[str, list[str]] = {}
    has_aggregated_metric = False

    for dim in dimensions:
        if dim not in column_map:
            raise ValueError(f"Dimension column '{dim}' does not exist in table '{schema_table}'")
        select_parts.append(dim)
        group_by_parts.append(dim)

    for metric in metrics:
        if not isinstance(metric, dict):
            raise ValueError("Each metric in IR must be an object")

        column = metric.get("column")
        raw_aggregation = metric.get("aggregation")
        aggregation = (raw_aggregation or "").upper()
        if aggregation in {"", "NONE", "NULL"}:
            aggregation = ""
        alias = metric.get("alias") or _default_metric_alias(aggregation, column)

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

    where_clause = _build_where_clause(filters, column_map, type_cast_map)
    order_clause = _build_order_clause(order_by, column_map, metric_aliases)
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
        if column not in metric_aliases.values() and column not in column_map:
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
