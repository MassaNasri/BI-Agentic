from __future__ import annotations

import re
from typing import Any

from shared.pipeline_guards import is_technical_column_name
from shared.schema_utils import is_date_type, is_numeric_type


_HORIZON_PATTERN = re.compile(
    r"\b(?:next|for the next|in)\s+(\d+)\s+(day|days|week|weeks|month|months|year|years)\b",
    flags=re.IGNORECASE,
)

_TIME_NAME_PRIORITY = (
    "ds",
    "date",
    "datetime",
    "timestamp",
    "order_date",
    "event_date",
    "created_at",
    "time",
)

_METADATA_TIME_EXACT = {
    "_extracted_at",
    "_loaded_at",
    "_processed_at",
    "_ingested_at",
    "_updated_at",
    "_created_at",
}

_METADATA_TIME_HINTS = (
    "_extract",
    "_load",
    "_process",
    "_ingest",
    "_lineage",
    "_pipeline",
    "_metadata",
    "_etl",
)

_TIME_NAME_HINTS = (
    "ds",
    "date",
    "datetime",
    "timestamp",
    "time",
    "_at",
)


def _tokenize(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", str(value or "").lower()))


def _resolve_horizon_and_granularity(query: str) -> tuple[int, str]:
    lowered = str(query or "").lower()
    match = _HORIZON_PATTERN.search(lowered)
    if not match:
        if "next week" in lowered:
            return 7, "day"
        if "next month" in lowered:
            return 30, "day"
        if "next year" in lowered:
            return 12, "month"
        return 7, "day"

    horizon = max(1, int(match.group(1)))
    unit = match.group(2).lower()
    if unit.startswith("week"):
        return horizon, "week"
    if unit.startswith("month"):
        return horizon, "month"
    if unit.startswith("year"):
        return horizon, "year"
    return horizon, "day"


def _best_table(schema: dict[str, list[dict[str, Any]]], query: str) -> str:
    question_tokens = _tokenize(query)
    best_table = ""
    best_score = -1
    for table_name, columns in schema.items():
        numeric_count = 0
        date_count = 0
        score = 0
        for column in columns:
            name = str(column.get("name", "")).strip()
            col_type = str(column.get("type", "")).strip()
            if is_numeric_type(col_type):
                numeric_count += 1
            if is_date_type(col_type):
                date_count += 1
            score += len(_tokenize(name) & question_tokens) * 2
        score += numeric_count
        score += date_count * 2
        if score > best_score:
            best_score = score
            best_table = table_name
    if not best_table:
        return sorted(schema.keys())[0]
    return best_table


def _is_time_like_column(column: dict[str, Any]) -> bool:
    col_type = str(column.get("type", "")).strip()
    if is_date_type(col_type):
        return True

    is_date_flag = column.get("is_date")
    if isinstance(is_date_flag, bool) and is_date_flag:
        return True

    name = str(column.get("name", "")).strip().lower()
    if not name:
        return False
    return any(hint in name for hint in _TIME_NAME_HINTS)


def _best_time_column(columns: list[dict[str, Any]]) -> str:
    candidates: list[tuple[int, int, str]] = []
    for column in columns:
        name = str(column.get("name", "")).strip()
        if not name or not _is_time_like_column(column):
            continue
        lowered = name.lower()
        if is_technical_column_name(lowered):
            continue
        if lowered in _METADATA_TIME_EXACT:
            continue
        if lowered.startswith("_") and any(hint in lowered for hint in _METADATA_TIME_HINTS):
            continue
        priority_score = 0
        for idx, preferred in enumerate(_TIME_NAME_PRIORITY):
            if lowered == preferred:
                priority_score = len(_TIME_NAME_PRIORITY) + 5 - idx
                break
            if preferred in lowered:
                priority_score = len(_TIME_NAME_PRIORITY) - idx
                break
        if lowered.startswith("_"):
            priority_score -= 3
        candidates.append((priority_score, len(name), name))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _best_metric_column(columns: list[dict[str, Any]], query: str) -> str:
    question_tokens = _tokenize(query)
    best_metric = ""
    best_score = -1
    for column in columns:
        name = str(column.get("name", "")).strip()
        col_type = str(column.get("type", "")).strip()
        if not name or not is_numeric_type(col_type):
            continue
        if is_technical_column_name(name):
            continue
        col_tokens = _tokenize(name)
        score = len(col_tokens & question_tokens) * 3
        if any(hint in name.lower() for hint in ("sales", "revenue", "profit", "amount", "total")):
            score += 2
        if score > best_score:
            best_score = score
            best_metric = name
    if best_metric:
        return best_metric
    for column in columns:
        name = str(column.get("name", "")).strip()
        col_type = str(column.get("type", "")).strip()
        if name and is_numeric_type(col_type):
            if is_technical_column_name(name):
                continue
            return name
    return ""


def parse_predictive_intent(*, query: str, schema: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if not schema:
        raise ValueError("schema is empty")

    table = _best_table(schema, query)
    columns = schema.get(table, [])
    time_column = _best_time_column(columns)
    metric = _best_metric_column(columns, query)
    horizon, granularity = _resolve_horizon_and_granularity(query)

    if not time_column:
        raise ValueError("No Date/DateTime column found for predictive intent.")
    if not metric:
        raise ValueError("No numeric metric column found for predictive intent.")

    return {
        "intent_type": "predictive",
        "intent": "forecast",
        "metrics": [metric],
        "metric_specs": [{"column": metric, "aggregation": "SUM", "alias": "value"}],
        "dimensions": [time_column],
        "filters": [],
        "time_range": "all_time",
        "aggregation": "SUM",
        "target_column": metric,
        "table": table,
        "order_by": [{"column": time_column, "direction": "ASC"}],
        "limit": None,
        "ranking": {"direction": None, "requested": False, "source": "predictive_parser"},
        "operations": ["projection", "forecasting"],
        "ambiguities": [],
        "metric": metric,
        "time_column": time_column,
        "forecast_horizon": horizon,
        "horizon": horizon,
        "granularity": granularity,
        "question_type": "predictive",
        "requires_forecast": True,
    }
