from __future__ import annotations

import re
from typing import Any

from voice_reports.constants import ChartType, normalize_chart_type


_TIME_COLUMN_TOKENS = ("date", "time", "timestamp", "period", "day", "week", "month", "quarter", "year")
_RELATIONSHIP_INTENTS = {"correlation", "relationship"}


def _is_numeric_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", value.strip()))
    return False


def _column_name(column: Any) -> str:
    if isinstance(column, dict):
        return str(column.get("name") or "").strip()
    return str(column or "").strip()


def _column_type(column: Any) -> str:
    if isinstance(column, dict):
        return str(column.get("type") or "").strip().lower()
    return ""


def _type_is_numeric(column_type: str) -> bool:
    lowered = str(column_type or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in ("int", "float", "decimal", "numeric", "double"))


def profile_result_shape(columns: list[Any], rows: list[Any]) -> dict[str, Any]:
    column_specs = [
        (raw_col, _column_name(raw_col))
        for raw_col in (columns or [])
        if _column_name(raw_col)
    ]
    normalized_columns = [name for _, name in column_specs]
    sample_rows = [row for row in (rows or []) if isinstance(row, dict)][:25]
    row_count = len(rows or [])
    numeric_columns: list[str] = []
    time_like_columns: list[str] = []

    for raw_column, col in column_specs:
        lowered = col.lower()
        if any(token in lowered for token in _TIME_COLUMN_TOKENS):
            time_like_columns.append(col)
        if _type_is_numeric(_column_type(raw_column)):
            numeric_columns.append(col)
            continue
        observed = [row.get(col) for row in sample_rows if col in row and row.get(col) is not None]
        if observed and all(_is_numeric_like(value) for value in observed):
            numeric_columns.append(col)

    has_category_value_shape = bool(
        row_count >= 1
        and len(numeric_columns) >= 1
        and len(normalized_columns) > len(numeric_columns)
    )
    return {
        "row_count": row_count,
        "columns": normalized_columns,
        "numeric_columns": numeric_columns,
        "time_like_columns": time_like_columns,
        "single_value": row_count == 1 and len(normalized_columns) == 1,
        "has_category_value_shape": has_category_value_shape,
    }


def infer_chart_type(
    *,
    columns: list[Any],
    rows: list[Any],
    intent: dict[str, Any] | None,
    preferred_chart_type: str | None = None,
) -> str:
    intent_payload = intent if isinstance(intent, dict) else {}
    intent_name = str(intent_payload.get("intent", "")).strip().lower()
    analysis_mode = str(intent_payload.get("analysis_mode", "")).strip().lower()
    time_grouping_detected = bool(intent_payload.get("time_grouping_detected"))
    operations = {
        str(op).strip().lower()
        for op in (intent_payload.get("operations", []) or [])
        if str(op).strip()
    }
    shape = profile_result_shape(columns=columns, rows=rows)
    row_count = shape["row_count"]
    numeric_count = len(shape["numeric_columns"])
    time_count = len(shape["time_like_columns"])
    has_category_value_shape = bool(shape.get("has_category_value_shape"))
    single_value = bool(shape["single_value"])

    if row_count == 0:
        return ChartType.TABLE

    def _supports(chart_type: str) -> bool:
        normalized = normalize_chart_type(chart_type, default="")
        if not normalized:
            return False
        if normalized == ChartType.CARD:
            return single_value
        if normalized == ChartType.LINE:
            return row_count > 1 and time_count >= 1 and numeric_count >= 1
        if normalized == ChartType.SCATTER:
            return row_count > 1 and numeric_count >= 2 and not has_category_value_shape
        if normalized == ChartType.HISTOGRAM:
            return row_count > 1 and numeric_count >= 1 and not has_category_value_shape
        if normalized == ChartType.BAR:
            return row_count >= 1 and has_category_value_shape
        if normalized == ChartType.TABLE:
            return True
        return False

    relationship_requested = (
        analysis_mode == "relationship"
        or intent_name in _RELATIONSHIP_INTENTS
        or "relationship" in operations
    )
    time_series_requested = (
        intent_name == "time_series"
        or time_grouping_detected
        or "time_grouping" in operations
    )
    distribution_requested = (
        analysis_mode == "distribution"
        or intent_name == "distribution"
        or "distribution" in operations
    )
    category_comparison_requested = (
        intent_name in {"comparison", "ranking"}
        or "comparison" in operations
        or "grouping" in operations
    )

    preferred_normalized = normalize_chart_type(preferred_chart_type, default="")
    if preferred_normalized and _supports(preferred_normalized):
        return preferred_normalized

    if relationship_requested and _supports(ChartType.SCATTER):
        return ChartType.SCATTER
    if time_series_requested and _supports(ChartType.LINE):
        return ChartType.LINE
    if distribution_requested and _supports(ChartType.HISTOGRAM):
        return ChartType.HISTOGRAM
    if category_comparison_requested and _supports(ChartType.BAR):
        return ChartType.BAR
    if single_value and _supports(ChartType.CARD):
        return ChartType.CARD

    if _supports(ChartType.LINE):
        return ChartType.LINE
    if _supports(ChartType.SCATTER):
        return ChartType.SCATTER
    if has_category_value_shape and _supports(ChartType.BAR):
        return ChartType.BAR
    if _supports(ChartType.HISTOGRAM):
        return ChartType.HISTOGRAM
    if _supports(ChartType.CARD):
        return ChartType.CARD
    return ChartType.TABLE
