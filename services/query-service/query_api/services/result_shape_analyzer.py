"""Deterministic query result shape analysis."""

from __future__ import annotations

import re
from typing import Any, Iterable

from bi_platform_shared.contracts.query import (
    ColumnMetadata,
    ColumnRole,
    GenericColumnType,
    ResultShape,
    ResultShapeType,
)


_AGGREGATE_RE = re.compile(r"\b(sum|count|avg|average|min|max|median|uniq(?:Exact)?)\s*\(", re.IGNORECASE)
_ORDER_BY_RE = re.compile(
    r"\border\s+by\s+(.+?)(?:\blimit\b|\boffset\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_METRIC_HINTS = (
    "total",
    "sum",
    "count",
    "avg",
    "average",
    "mean",
    "median",
    "revenue",
    "sales",
    "profit",
    "amount",
    "cost",
    "margin",
    "metric",
    "measure",
    "frequency",
)
_TIME_NAME_HINTS = ("date", "time", "timestamp", "period", "day", "week", "month", "quarter", "year", "ds")
_CATEGORY_TYPE_SET = {GenericColumnType.STRING, GenericColumnType.BOOLEAN, GenericColumnType.UNKNOWN}


def _coerce_columns(columns: Iterable[Any]) -> list[ColumnMetadata]:
    coerced: list[ColumnMetadata] = []
    for column in columns or []:
        if isinstance(column, ColumnMetadata):
            coerced.append(column)
        elif isinstance(column, dict):
            coerced.append(ColumnMetadata.model_validate(column))
        elif str(column or "").strip():
            coerced.append(ColumnMetadata(name=str(column).strip()))
    return coerced


def _row_value(row: Any, column_name: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(column_name)
    if isinstance(row, (list, tuple)) and index < len(row):
        return row[index]
    return None


def _cardinality(rows: list[Any], columns: list[str]) -> dict[str, int]:
    output: dict[str, int] = {}
    for column_index, column_name in enumerate(columns):
        seen: set[str] = set()
        for row in rows:
            value = _row_value(row, column_name, column_index)
            if value is None:
                continue
            seen.add(str(value))
        output[column_name] = len(seen)
    return output


def _has_metric_name_hint(column_name: str) -> bool:
    lowered = str(column_name or "").strip().lower()
    return any(hint in lowered for hint in _METRIC_HINTS)


def _has_time_name_hint(column_name: str) -> bool:
    lowered = str(column_name or "").strip().lower()
    return any(hint in lowered for hint in _TIME_NAME_HINTS)


def _detect_aggregation(sql: str) -> str | None:
    found = [match.group(1).upper() for match in _AGGREGATE_RE.finditer(str(sql or ""))]
    if not found:
        return None
    deduped = list(dict.fromkeys("AVG" if item == "AVERAGE" else item for item in found))
    return ",".join(deduped)


def _normalize_order_column(raw_column: str) -> str:
    token = str(raw_column or "").strip()
    token = re.split(r"\s+", token, maxsplit=1)[0] if token else ""
    token = token.strip("`\"'")
    if "." in token:
        token = token.rsplit(".", 1)[-1].strip("`\"'")
    return token


def _detect_sort(sql: str, columns_by_lower: dict[str, str]) -> dict[str, str] | None:
    match = _ORDER_BY_RE.search(str(sql or ""))
    if not match:
        return None
    first_order = match.group(1).split(",", 1)[0].strip()
    if not first_order:
        return None
    direction_match = re.search(r"\b(asc|desc)\b", first_order, flags=re.IGNORECASE)
    direction = direction_match.group(1).upper() if direction_match else "ASC"
    column = _normalize_order_column(first_order)
    if not column:
        return None
    resolved = columns_by_lower.get(column.lower())
    if not resolved:
        return None
    return {"column": resolved, "direction": direction}


def _set_roles(
    *,
    columns: list[ColumnMetadata],
    time_field: str | None,
    category_fields: list[str],
    series_fields: list[str],
    metric_fields: list[str],
) -> None:
    category_set = set(category_fields)
    series_set = set(series_fields)
    metric_set = set(metric_fields)
    for column in columns:
        if column.name == time_field:
            column.role = ColumnRole.TIME_FIELD
        elif column.name in series_set:
            column.role = ColumnRole.SERIES_FIELD
        elif column.name in metric_set:
            column.role = ColumnRole.METRIC_FIELD
        elif column.name in category_set:
            column.role = ColumnRole.CATEGORY_FIELD
        else:
            column.role = ColumnRole.UNKNOWN


def analyze_result_shape(
    sql: str,
    columns: list[ColumnMetadata] | list[dict[str, Any]] | list[str],
    rows: list[Any],
) -> ResultShape:
    """Infer the BI shape of a result using deterministic, bounded signals."""

    metadata = _coerce_columns(columns)
    row_items = [row for row in (rows or [])]
    row_count = len(row_items)
    aggregation = _detect_aggregation(sql)
    has_aggregation = bool(aggregation)
    columns_by_lower = {column.name.lower(): column.name for column in metadata}

    time_candidates = [
        column.name
        for column in metadata
        if column.generic_type in {GenericColumnType.DATE, GenericColumnType.DATETIME}
    ]
    if not time_candidates:
        time_candidates = [
            column.name
            for column in metadata
            if column.generic_type != GenericColumnType.NUMBER and _has_time_name_hint(column.name)
        ]
    time_field = time_candidates[0] if time_candidates else None

    numeric_columns = [column.name for column in metadata if column.generic_type == GenericColumnType.NUMBER]
    non_numeric_columns = [
        column.name
        for column in metadata
        if column.name != time_field and column.generic_type in _CATEGORY_TYPE_SET
    ]

    metric_fields: list[str] = []
    for column_name in numeric_columns:
        if has_aggregation or _has_metric_name_hint(column_name) or non_numeric_columns or time_field:
            metric_fields.append(column_name)

    if not metric_fields and numeric_columns:
        metric_fields = list(numeric_columns)

    category_fields = list(non_numeric_columns)
    series_fields: list[str] = []

    if time_field and len(metric_fields) == 1 and len(category_fields) == 1:
        series_fields = [category_fields[0]]
        category_fields = []

    cardinality_columns = list(dict.fromkeys(category_fields + series_fields))
    cardinality = _cardinality(row_items, cardinality_columns)
    sort = _detect_sort(sql, columns_by_lower)

    if len(metadata) == 1 and metric_fields and row_count <= 1:
        shape_type = ResultShapeType.SINGLE_VALUE
    elif time_field and metric_fields and series_fields:
        shape_type = ResultShapeType.TIME_SERIES_GROUPED
    elif time_field and metric_fields:
        shape_type = ResultShapeType.TIME_SERIES
    elif category_fields and len(metric_fields) >= 2:
        shape_type = ResultShapeType.MULTI_METRIC
    elif category_fields and metric_fields:
        shape_type = ResultShapeType.GROUPED
    elif len(metric_fields) >= 2 and not time_field:
        shape_type = ResultShapeType.MULTI_METRIC
    else:
        shape_type = ResultShapeType.RAW

    _set_roles(
        columns=metadata,
        time_field=time_field,
        category_fields=category_fields,
        series_fields=series_fields,
        metric_fields=metric_fields,
    )

    return ResultShape(
        type=shape_type,
        time_field=time_field,
        category_fields=category_fields,
        series_fields=series_fields,
        metric_fields=metric_fields,
        aggregation=aggregation,
        sort=sort,
        cardinality=cardinality,
        row_count=row_count,
    )


__all__ = ["analyze_result_shape"]
