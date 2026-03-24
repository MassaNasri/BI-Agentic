import os
import re
from typing import Any

from shared.schema_utils import is_numeric_type, normalize_table_name, unqualify_table_name

VALID_AGGREGATIONS = {"SUM", "AVG", "COUNT", "MIN", "MAX"}
VALID_DIRECTIONS = {"ASC", "DESC"}
VALID_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "IN", "LIKE"}


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

    select_parts: list[str] = []
    group_by_parts: list[str] = []
    metric_aliases: dict[str, str] = {}

    for dim in dimensions:
        if dim not in column_map:
            raise ValueError(f"Dimension column '{dim}' does not exist in table '{schema_table}'")
        select_parts.append(dim)
        group_by_parts.append(dim)

    for metric in metrics:
        if not isinstance(metric, dict):
            continue

        column = metric.get("column")
        aggregation = (metric.get("aggregation") or "").upper()
        alias = metric.get("alias") or _default_metric_alias(aggregation, column)

        if aggregation not in VALID_AGGREGATIONS:
            raise ValueError(f"Unsupported aggregation '{aggregation}'")

        if column == "*":
            if aggregation != "COUNT":
                raise ValueError("Only COUNT supports '*' metric column")
            expression = "COUNT(*)"
        else:
            if column not in column_map:
                raise ValueError(f"Metric column '{column}' does not exist in table '{schema_table}'")
            if aggregation != "COUNT" and not is_numeric_type(column_map[column].get("type", "")):
                raise ValueError(
                    f"Aggregation '{aggregation}' requires numeric column, got '{column}' ({column_map[column].get('type')})"
                )
            expression = f"{aggregation}({column})"

        select_parts.append(f"{expression} AS {alias}")
        metric_aliases[column] = alias
        metric_aliases[alias] = alias

    if not select_parts:
        raise ValueError("SQL generation failed: empty SELECT list")

    where_clause = _build_where_clause(filters, column_map)
    order_clause = _build_order_clause(order_by, column_map, metric_aliases)
    limit_clause = _build_limit_clause(limit)

    sql_parts = [
        _format_select_clause(select_parts),
        f"FROM {from_table}",
    ]
    if where_clause:
        sql_parts.append(where_clause)
    if group_by_parts:
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
    return f"{aggregation.lower()}_{safe_column}"


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


def _build_where_clause(filters: list[dict[str, Any]], column_map: dict[str, dict[str, Any]]) -> str:
    clauses = []
    for filter_item in filters:
        if not isinstance(filter_item, dict):
            continue
        column = filter_item.get("column")
        operator = (filter_item.get("operator") or "=").upper()
        value = filter_item.get("value")

        if not column or column not in column_map or value is None:
            continue
        if operator not in VALID_OPERATORS:
            continue

        if operator == "IN":
            if not isinstance(value, list):
                value = [value]
            value_sql = _format_filter_value(value)
        else:
            value_sql = _format_filter_value(value)
        clauses.append(f"{column} {operator} {value_sql}")

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
            continue
        raw_column = order_item.get("column")
        direction = (order_item.get("direction") or "ASC").upper()
        if direction not in VALID_DIRECTIONS:
            direction = "ASC"
        if not raw_column:
            continue

        column = metric_aliases.get(raw_column, raw_column)
        if column not in metric_aliases.values() and column not in column_map:
            continue
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
