from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests

from bi_platform_shared.contracts.chart import (
    is_chart_shape_supported,
    recommend_chart_types,
    select_chart_type as shared_select_chart_type,
)
from visualization_api.constants import ChartType, normalize_chart_type, to_metabase_display

logger = logging.getLogger(__name__)

SUPPORTED_CHART_TYPES: tuple[str, ...] = (
    ChartType.LINE,
    ChartType.LINE_MULTI,
    ChartType.BAR,
    ChartType.BAR_GROUPED,
    ChartType.BAR_STACKED,
    ChartType.PIE,
    ChartType.AREA,
    ChartType.SCATTER,
    ChartType.HISTOGRAM,
    ChartType.MAP,
    ChartType.HEATMAP,
    ChartType.COMBO_LINE_BAR,
    ChartType.CUMULATIVE_LINE,
    ChartType.CARD,
    ChartType.TABLE,
)

_SELECTOR_TOKEN_HINTS = {
    *SUPPORTED_CHART_TYPES,
    "scalar",
    "kpi",
    "number",
    "combo",
    "grouped_bar",
    "stacked_bar",
    "multi_line",
}

DEFAULT_CHART_TYPE = ChartType.TABLE

_TIME_COLUMN_HINTS = ("date", "time", "timestamp", "period", "day", "week", "month", "quarter", "year", "ds")
_GEO_COLUMN_HINTS = ("country", "state", "province", "city", "region", "lat", "latitude", "lon", "lng", "longitude")
_SHARE_KEYWORDS = ("share", "percentage", "proportion", "contribution", "composition", "percent")
_DISTRIBUTION_KEYWORDS = ("distribution", "histogram", "spread", "frequency")
_RANKING_KEYWORDS = ("highest", "lowest", "top", "bottom", "most", "least", "maximum", "minimum", "best", "worst")
_TIME_KEYWORDS = (
    "over time",
    "across time",
    "through time",
    "time series",
    "trend",
    "timeline",
    "by day",
    "per day",
    "each day",
    "daily",
    "by week",
    "per week",
    "each week",
    "weekly",
    "by month",
    "per month",
    "each month",
    "monthly",
    "by year",
    "per year",
    "each year",
    "yearly",
    "annually",
    "over days",
    "over weeks",
    "over months",
    "over years",
    "across days",
    "across weeks",
    "across months",
    "across years",
)


def _is_numeric_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return False
        if token.startswith("-"):
            token = token[1:]
        return token.replace(".", "", 1).isdigit()
    return False


def _is_datetime_like(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    token = value.strip()
    if not token:
        return False
    return bool(
        re.match(r"^\d{4}-\d{2}-\d{2}", token)
        or re.match(r"^\d{4}/\d{2}/\d{2}", token)
        or re.match(r"^\d{4}-\d{2}$", token)
        or re.match(r"^\d{4}$", token)
    )


def _column_name(column: Any) -> str:
    if isinstance(column, dict):
        return str(column.get("name") or "").strip()
    return str(column or "").strip()


def _column_type(column: Any) -> str:
    if isinstance(column, dict):
        return str(column.get("type") or "").strip().lower()
    return ""


def _column_semantic_type(column: Any, rows: list[dict[str, Any]]) -> str:
    name = _column_name(column)
    if not name:
        return "unknown"
    lowered = name.lower()
    ctype = _column_type(column)
    if any(token in ctype for token in ("date", "time", "timestamp")):
        return "datetime"
    if any(token in lowered for token in _TIME_COLUMN_HINTS):
        return "datetime"
    if "bool" in ctype:
        return "boolean"
    if any(token in ctype for token in ("int", "float", "double", "decimal", "numeric")):
        return "numeric"

    observed = [row.get(name) for row in rows[:50] if isinstance(row, dict) and name in row and row.get(name) is not None]
    if observed:
        if all(_is_numeric_like(value) for value in observed):
            return "numeric"
        if all(isinstance(value, bool) for value in observed):
            return "boolean"
        if all(_is_datetime_like(value) for value in observed):
            return "datetime"
    return "categorical"


def _distinct_values_count(rows: list[dict[str, Any]], column_name: str, *, cap: int = 500) -> int:
    seen: set[str] = set()
    for row in rows[:cap]:
        if not isinstance(row, dict):
            continue
        value = row.get(column_name)
        if value is None:
            continue
        token = str(value).strip()
        if token:
            seen.add(token)
    return len(seen)


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _time_series_scale_ratio(rows: list[dict[str, Any]], numeric_columns: list[str]) -> float:
    if len(numeric_columns) < 2:
        return 1.0
    ranges: list[float] = []
    for column_name in numeric_columns:
        observed = []
        for row in rows[:500]:
            if not isinstance(row, dict):
                continue
            value = row.get(column_name)
            if _is_numeric_like(value):
                observed.append(float(value))
        if not observed:
            continue
        ranges.append(max(observed) - min(observed))
    non_zero_ranges = [value for value in ranges if value > 0]
    if len(non_zero_ranges) < 2:
        return 1.0
    return max(non_zero_ranges) / max(min(non_zero_ranges), 1e-9)


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = str(text or "").strip().lower()
    return any(keyword in lowered for keyword in keywords)


def _build_result_shape(
    *,
    columns: list[Any],
    rows: list[dict[str, Any]],
    intent: dict[str, Any],
    sql: str,
) -> dict[str, Any]:
    normalized_columns: list[dict[str, Any]] = []
    numeric_columns: list[str] = []
    datetime_columns: list[str] = []
    categorical_columns: list[str] = []
    boolean_columns: list[str] = []
    geo_columns: list[str] = []

    for raw_column in columns:
        name = _column_name(raw_column)
        if not name:
            continue
        semantic_type = _column_semantic_type(raw_column, rows)
        normalized_columns.append({"name": name, "semantic_type": semantic_type})
        lowered = name.lower()
        if semantic_type == "numeric":
            numeric_columns.append(name)
        elif semantic_type == "datetime":
            datetime_columns.append(name)
        elif semantic_type == "boolean":
            boolean_columns.append(name)
        else:
            categorical_columns.append(name)
        if any(token in lowered for token in _GEO_COLUMN_HINTS):
            geo_columns.append(name)

    operations = {
        str(op).strip().lower()
        for op in (intent.get("operations") or [])
        if str(op).strip()
    }
    sql_lower = str(sql or "").strip().lower()
    question_text = str(intent.get("raw_question") or "").strip().lower()
    map_requested = bool(
        "geo" in operations
        or "map" in operations
        or "geographic" in question_text
        or "geospatial" in question_text
        or re.search(r"\bmap\b", question_text)
    )
    has_grouping = bool(
        "grouping" in operations
        or "time_grouping" in operations
        or "group by" in sql_lower
    )
    has_aggregation = bool(
        "aggregation" in operations
        or bool(re.search(r"\b(sum|avg|count|min|max)\s*\(", sql_lower))
    )

    return {
        "row_count": len(rows),
        "columns": normalized_columns,
        "numeric_columns": numeric_columns,
        "datetime_columns": datetime_columns,
        "categorical_columns": categorical_columns,
        "boolean_columns": boolean_columns,
        "geo_columns": geo_columns,
        "map_requested": map_requested,
        "has_time_column": bool(datetime_columns),
        "has_grouping": has_grouping,
        "has_aggregation": has_aggregation,
    }


def _names_from_shape(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        return [name] if name else []
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
            else:
                name = str(item or "").strip()
            if name:
                names.append(name)
        return list(dict.fromkeys(names))
    return []


def _merge_semantic_result_shape(
    *,
    local_shape: dict[str, Any],
    upstream_shape: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(upstream_shape, dict) or not upstream_shape:
        return local_shape

    merged = dict(local_shape)
    merged["semantic_result_shape"] = upstream_shape
    if int(upstream_shape.get("row_count") or 0) > 0:
        merged["row_count"] = int(upstream_shape.get("row_count") or 0)
    if str(upstream_shape.get("type") or "").strip():
        merged["type"] = str(upstream_shape.get("type") or "").strip()
    if isinstance(upstream_shape.get("cardinality"), dict):
        merged["cardinality"] = upstream_shape["cardinality"]

    metric_fields = _names_from_shape(upstream_shape.get("metric_fields"))
    time_fields = _names_from_shape(upstream_shape.get("time_field")) + _names_from_shape(
        upstream_shape.get("time_fields")
    )
    category_fields = _names_from_shape(upstream_shape.get("category_fields"))
    series_fields = _names_from_shape(upstream_shape.get("series_fields"))

    if metric_fields:
        merged["numeric_columns"] = list(dict.fromkeys(metric_fields + list(merged.get("numeric_columns") or [])))
        merged["metric_fields"] = metric_fields
    if time_fields:
        merged["datetime_columns"] = list(dict.fromkeys(time_fields + list(merged.get("datetime_columns") or [])))
        merged["time_field"] = time_fields[0]
        merged["has_time_column"] = True
    if category_fields or series_fields:
        merged["categorical_columns"] = list(
            dict.fromkeys(category_fields + series_fields + list(merged.get("categorical_columns") or []))
        )
        merged["category_fields"] = category_fields
        merged["series_fields"] = series_fields
    return merged


def _shape_first_chart_selection(
    *,
    intent: dict[str, Any],
    result_shape: dict[str, Any],
    rows: list[dict[str, Any]],
    question: str,
) -> tuple[str | None, str]:
    row_count = int(result_shape.get("row_count") or 0)
    numeric_columns = result_shape.get("numeric_columns") or []
    datetime_columns = result_shape.get("datetime_columns") or []
    categorical_columns = result_shape.get("categorical_columns") or []
    geo_columns = result_shape.get("geo_columns") or []
    numeric_count = len(numeric_columns)
    datetime_count = len(datetime_columns)
    categorical_count = len(categorical_columns)

    question_lower = str(question or "").strip().lower()
    operations = {
        str(op).strip().lower()
        for op in (intent.get("operations") or [])
        if str(op).strip()
    }
    ranking_payload = intent.get("ranking") if isinstance(intent.get("ranking"), dict) else {}
    ranking_direction = str(ranking_payload.get("direction") or "").strip().upper()
    ranking_requested = bool(
        ranking_direction in {"ASC", "DESC"}
        or "ranking" in operations
        or _has_keyword(question_lower, _RANKING_KEYWORDS)
    )
    limit_value = _safe_int(intent.get("limit"))
    single_winner_requested = bool(ranking_requested and limit_value == 1)
    distribution_requested = bool(
        "distribution" in operations
        or str(intent.get("analysis_mode") or "").strip().lower() == "distribution"
        or str(intent.get("intent") or "").strip().lower() == "distribution"
        or _has_keyword(question_lower, _DISTRIBUTION_KEYWORDS)
    )
    share_requested = bool(
        "share" in operations
        or "contribution" in operations
        or "percent_of_total" in operations
        or _has_keyword(question_lower, _SHARE_KEYWORDS)
    )
    relationship_requested = bool(
        "relationship" in operations
        or str(intent.get("analysis_mode") or "").strip().lower() == "relationship"
        or str(intent.get("intent") or "").strip().lower() in {"relationship", "correlation"}
        or _has_keyword(question_lower, ("relationship", "correlation"))
    )
    time_requested = bool(
        result_shape.get("has_time_column")
        or bool(intent.get("time_grouping_detected"))
        or str(intent.get("time_granularity") or "").strip().lower() in {"hour", "day", "week", "month", "quarter", "year"}
        or "time_grouping" in operations
        or _has_keyword(question_lower, _TIME_KEYWORDS)
    )

    if row_count == 0:
        return ChartType.TABLE, "result_shape_empty_rows_table"

    if row_count == 1:
        if numeric_count == 1 and datetime_count == 0 and categorical_count == 0:
            return ChartType.CARD, "result_shape_single_value_card"
        if numeric_count >= 1 and (datetime_count >= 1 or categorical_count >= 1 or bool(single_winner_requested)):
            return ChartType.CARD, "result_shape_single_row_label_metric_card"
        return ChartType.TABLE, "result_shape_single_row_table"

    if result_shape.get("map_requested") and geo_columns and numeric_count >= 1:
        return ChartType.MAP, "result_shape_geo_map"

    if time_requested and datetime_count >= 1 and numeric_count >= 2:
        scale_ratio = _time_series_scale_ratio(rows, numeric_columns)
        if scale_ratio >= 25:
            return ChartType.COMBO_LINE_BAR, "result_shape_time_multi_metric_combo_scale_gap"
        return ChartType.LINE_MULTI, "result_shape_time_multi_metric_line"
    if time_requested and datetime_count >= 1 and numeric_count == 1:
        if ranking_requested and row_count <= 7:
            return ChartType.BAR, "result_shape_time_single_metric_small_ranking_bar"
        return ChartType.LINE, "result_shape_time_single_metric_line"

    if ranking_requested and (categorical_count >= 1 or datetime_count >= 1) and numeric_count >= 1:
        if single_winner_requested and row_count == 1:
            return ChartType.CARD, "result_shape_ranking_single_winner_card"
        return ChartType.BAR, "result_shape_ranking_bar"

    if relationship_requested and numeric_count >= 2 and datetime_count == 0:
        if not _has_keyword(question_lower, _TIME_KEYWORDS):
            return ChartType.SCATTER, "result_shape_relationship_scatter"

    if distribution_requested and numeric_count >= 1:
        if row_count >= 10:
            return ChartType.HISTOGRAM, "result_shape_distribution_histogram"
        return ChartType.TABLE, "result_shape_distribution_small_table"

    if share_requested and categorical_count >= 1 and numeric_count >= 1:
        first_category = categorical_columns[0]
        distinct_categories = _distinct_values_count(rows, first_category)
        if 0 < distinct_categories <= 5:
            return ChartType.PIE, "result_shape_share_pie"
        return ChartType.BAR, "result_shape_share_bar"

    if numeric_count >= 2 and datetime_count == 0:
        if not _has_keyword(question_lower, _TIME_KEYWORDS):
            return ChartType.SCATTER, "result_shape_two_numeric_scatter"

    if categorical_count >= 1 and numeric_count >= 1:
        return ChartType.BAR, "result_shape_category_bar"

    if numeric_count == 1 and row_count > 1:
        return ChartType.TABLE, "result_shape_single_numeric_list_table"

    return None, ""


def _merge_intent_for_chart_selection(
    visualization_settings: dict[str, Any],
    ai_trace: dict[str, Any],
    *,
    name: str,
) -> dict[str, Any]:
    """
    Build a single intent mapping for deterministic chart selection.
    Prefers pipeline validated intent from ai_trace, then merges report-level intent
    from visualization_settings (voice-service passes intent_json here).
    """
    merged: dict[str, Any] = {}
    settings_intent = visualization_settings.get("intent")
    if isinstance(settings_intent, dict):
        merged.update(settings_intent)

    intent_extraction = ai_trace.get("intent_extraction")
    if isinstance(intent_extraction, dict):
        validated = intent_extraction.get("validated_intent")
        if isinstance(validated, dict):
            merged.update(validated)
        normalized_intent = intent_extraction.get("normalized_intent")
        if isinstance(normalized_intent, dict):
            merged.update(normalized_intent)
        extracted = intent_extraction.get("extracted_intent")
        if isinstance(extracted, dict):
            for key, value in extracted.items():
                merged.setdefault(key, value)
        itype = str(intent_extraction.get("intent_type") or "").strip()
        if itype and not str(merged.get("intent_type") or "").strip():
            merged["intent_type"] = itype

    # Prefer the latest normalized intent produced after semantic conflict
    # resolution and SQL planning when available.
    query_execution = ai_trace.get("query_execution")
    if isinstance(query_execution, dict):
        normalized_from_execution = query_execution.get("normalized_intent")
        if isinstance(normalized_from_execution, dict):
            merged.update(normalized_from_execution)
        final_output = query_execution.get("final_output")
        if isinstance(final_output, dict):
            normalized_from_stage = final_output.get("normalized_intent")
            if isinstance(normalized_from_stage, dict):
                merged.update(normalized_from_stage)

    routing = ai_trace.get("routing")
    if isinstance(routing, dict):
        if not str(merged.get("intent_type") or "").strip():
            merged.setdefault("intent_type", str(routing.get("next_step") or "").strip())

    original = ai_trace.get("original_question")
    if isinstance(original, dict):
        text = str(original.get("text") or "").strip()
        if text:
            merged.setdefault("raw_question", text)
    if not str(merged.get("raw_question") or "").strip():
        merged["raw_question"] = str(name or "").strip()

    return merged


def _columns_and_rows_from_settings(settings: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    columns: list[Any] = []
    dataset_columns = settings.get("dataset_columns")
    if isinstance(dataset_columns, list) and dataset_columns:
        columns = [col for col in dataset_columns if isinstance(col, dict) and str(col.get("name") or "").strip()]
    if not columns:
        raw_cols = settings.get("columns") or settings.get("result_columns") or settings.get("query_columns")
        if isinstance(raw_cols, list):
            for col in raw_cols:
                if isinstance(col, dict) and str(col.get("name") or "").strip():
                    columns.append(col)
                elif isinstance(col, str) and col.strip():
                    columns.append({"name": col.strip(), "type": ""})

    rows: list[dict[str, Any]] = []
    for key in ("result_rows", "rows", "data_rows"):
        candidate = settings.get(key)
        if isinstance(candidate, list) and candidate:
            rows = [row for row in candidate if isinstance(row, dict)]
            break

    return columns, rows


def _deterministic_chart_selection(
    *,
    name: str,
    sql: str,
    requested_chart_type: str,
    visualization_settings: dict[str, Any],
    ai_trace: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    merged_intent = _merge_intent_for_chart_selection(
        visualization_settings,
        ai_trace,
        name=name,
    )
    columns, rows = _columns_and_rows_from_settings(visualization_settings)
    question = str(merged_intent.get("raw_question") or name or "").strip()
    result_shape = _build_result_shape(
        columns=columns,
        rows=rows,
        intent=merged_intent,
        sql=sql,
    )
    result_shape = _merge_semantic_result_shape(
        local_shape=result_shape,
        upstream_shape=visualization_settings.get("result_shape")
        if isinstance(visualization_settings.get("result_shape"), dict)
        else None,
    )

    shape_chart_type, shape_reason = _shape_first_chart_selection(
        intent=merged_intent,
        result_shape=result_shape,
        rows=rows,
        question=question,
    )
    if shape_chart_type:
        return shape_chart_type, shape_reason, result_shape

    # Final fallback: shared deterministic selector with NO upstream chart-type
    # override. visualization-service is the final authority.
    chart_enum, reason = shared_select_chart_type(
        intent=merged_intent,
        columns=columns,
        rows=rows,
        preferred_chart_type=None,
        question=question,
    )
    _ = requested_chart_type
    return chart_enum.value, f"shared_selector_fallback|{reason}", result_shape


def _selection_payload(
    chart_type: str,
    *,
    reason: str,
    source: str,
    model: str | None = None,
    raw_chart_type: str | None = None,
    result_shape: dict[str, Any] | None = None,
    chart_hint_from_ai: str | None = None,
    chart_recommendation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = normalize_chart_type(chart_type, default=DEFAULT_CHART_TYPE)
    if resolved not in SUPPORTED_CHART_TYPES:
        resolved = DEFAULT_CHART_TYPE
    payload: dict[str, Any] = {
        "chart_type": resolved,
        "display": to_metabase_display(resolved),
        "reason": reason,
        "source": source,
        "chart_type_selected_by_visualization_service": resolved,
    }
    if model:
        payload["model"] = model
    if raw_chart_type is not None:
        payload["raw_chart_type"] = raw_chart_type
    if result_shape is not None:
        payload["result_shape"] = result_shape
    if chart_hint_from_ai is not None:
        payload["chart_hint_from_ai"] = chart_hint_from_ai
    if isinstance(chart_recommendation, dict):
        payload["chart_recommendation"] = chart_recommendation
        payload["recommended_chart_type"] = chart_recommendation.get("recommended_chart_type")
        payload["alternatives"] = chart_recommendation.get("alternatives", [])
        payload["incompatible_chart_types"] = chart_recommendation.get("incompatible", [])
        recommended = chart_recommendation.get("recommended")
        compatible_entries = []
        if isinstance(recommended, dict):
            compatible_entries.append(recommended)
        compatible_entries.extend(
            item
            for item in chart_recommendation.get("alternatives", [])
            if isinstance(item, dict)
        )
        payload["compatible_chart_types"] = [
            str(item.get("chart_type") or "")
            for item in compatible_entries
            if isinstance(item, dict) and str(item.get("chart_type") or "").strip()
        ]
    return payload


def _build_chart_recommendation_payload(
    *,
    result_shape: dict[str, Any],
    requested_chart_type: str,
    deterministic_type: str,
) -> dict[str, Any]:
    recommendation = recommend_chart_types(
        shape=result_shape,
        preferred_chart_type=requested_chart_type or deterministic_type,
        max_alternatives=3,
    ).model_dump(mode="json")
    recommended = recommendation.get("recommended") if isinstance(recommendation.get("recommended"), dict) else {}
    alternatives = [
        item
        for item in recommendation.get("alternatives", [])
        if isinstance(item, dict) and str(item.get("chart_type") or "").strip()
    ]
    if deterministic_type and is_chart_shape_supported(deterministic_type, result_shape):
        deterministic_entry = {
            "chart_type": deterministic_type,
            "display": to_metabase_display(deterministic_type),
            "confidence": 1.0,
            "score": 1.0,
            "reason": "deterministic_selected_compatible",
        }
        previous_recommended = recommended if str(recommended.get("chart_type") or "").strip() else {}
        alternatives = [
            previous_recommended,
            *[
                item
                for item in alternatives
                if str(item.get("chart_type") or "").strip() != deterministic_type
            ],
        ] if previous_recommended and str(previous_recommended.get("chart_type") or "").strip() != deterministic_type else alternatives
        alternatives = [
            item
            for item in alternatives
            if isinstance(item, dict) and str(item.get("chart_type") or "").strip() != deterministic_type
        ]
        recommendation["recommended"] = deterministic_entry
        recommendation["recommended_chart_type"] = deterministic_type
        recommendation["chart_type"] = deterministic_type
    recommendation["alternatives"] = alternatives[:3]
    return recommendation


def _env_bool(name: str, default: bool) -> bool:
    token = str(os.getenv(name, str(default))).strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _safe_json_dumps(payload: Any, *, fallback: str = "{}") -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return fallback


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(truncated)"


def _extract_json_object(raw: str) -> dict[str, Any]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        payload = json.loads(raw[start : end + 1])
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _extract_chart_token(raw: str) -> str:
    raw_payload = _extract_json_object(raw)
    if raw_payload:
        for key in ("chart_type", "type", "chart"):
            candidate = str(raw_payload.get(key) or "").strip()
            if candidate:
                return candidate

    lowered = str(raw or "").strip().lower()
    if not lowered:
        return ""
    token_pattern = "|".join(sorted(re.escape(token) for token in _SELECTOR_TOKEN_HINTS))
    match = re.search(rf"\b({token_pattern})\b", lowered)
    return match.group(1) if match else ""


def _build_selector_prompt(
    *,
    name: str,
    sql: str,
    requested_chart_type: str,
    visualization_settings: dict[str, Any],
    ai_trace: dict[str, Any],
    allowed_chart_types: tuple[str, ...],
    chart_recommendation: dict[str, Any],
    max_trace_chars: int,
    max_settings_chars: int,
) -> str:
    allowed_list = ", ".join(allowed_chart_types or SUPPORTED_CHART_TYPES)
    compact_trace = _truncate(_safe_json_dumps(ai_trace, fallback="{}"), max_trace_chars)
    compact_settings = _truncate(_safe_json_dumps(visualization_settings, fallback="{}"), max_settings_chars)
    compact_recommendation = _safe_json_dumps(chart_recommendation, fallback="{}")

    return (
        "You are a chart-type selector for Metabase.\n"
        f"Allowed chart_type values only: {allowed_list}\n\n"
        "Task:\n"
        "1) Read the full AI trace and visualization metadata.\n"
        "2) Pick exactly one chart_type from the allowed list.\n"
        "3) Prefer charts that match time dimensions, categories, and numeric measures in the SQL and metadata.\n"
        "4) Avoid table unless the user explicitly asked for a raw grid or the result is purely tabular.\n\n"
        "Output format:\n"
        "Return strict JSON only with this schema:\n"
        "{\"chart_type\":\"<one_allowed_value>\",\"reason\":\"short_reason\"}\n"
        "Do not return markdown.\n\n"
        f"Question Name: {name}\n"
        f"Requested Chart Type (hint only): {requested_chart_type}\n"
        f"SQL:\n{sql}\n\n"
        f"Compatible Chart Recommendation JSON:\n{compact_recommendation}\n\n"
        f"Visualization Settings JSON:\n{compact_settings}\n\n"
        f"AI Trace JSON:\n{compact_trace}\n"
    )


def select_chart_type_with_ollama(
    *,
    name: str,
    sql: str,
    requested_chart_type: str,
    visualization_settings: dict[str, Any] | None,
    ai_trace: dict[str, Any] | None,
) -> dict[str, Any]:
    settings_payload = visualization_settings if isinstance(visualization_settings, dict) else {}
    trace_payload = ai_trace if isinstance(ai_trace, dict) else {}

    deterministic_type, deterministic_reason, result_shape = _deterministic_chart_selection(
        name=name,
        sql=sql,
        requested_chart_type=requested_chart_type,
        visualization_settings=settings_payload,
        ai_trace=trace_payload,
    )
    raw_hint = str(requested_chart_type or "").strip()
    chart_hint_from_ai = normalize_chart_type(raw_hint, default=DEFAULT_CHART_TYPE) if raw_hint else ""
    chart_recommendation = _build_chart_recommendation_payload(
        result_shape=result_shape,
        requested_chart_type=raw_hint,
        deterministic_type=deterministic_type,
    )
    recommended = chart_recommendation.get("recommended") if isinstance(chart_recommendation.get("recommended"), dict) else {}
    compatible_entries = []
    if recommended:
        compatible_entries.append(recommended)
    compatible_entries.extend(
        item
        for item in chart_recommendation.get("alternatives", [])
        if isinstance(item, dict)
    )
    compatible_types = tuple(
        str(item.get("chart_type") or "").strip()
        for item in compatible_entries
        if isinstance(item, dict) and str(item.get("chart_type") or "").strip()
    ) or (ChartType.TABLE,)
    if deterministic_type not in compatible_types:
        deterministic_type = str(chart_recommendation.get("recommended_chart_type") or ChartType.TABLE)
        deterministic_reason = f"incompatible_deterministic_replaced|{deterministic_reason}"

    selection_mode = str(settings_payload.get("selection_mode") or "").strip().lower()
    if selection_mode == "deterministic":
        return _selection_payload(
            deterministic_type,
            reason=f"deterministic_selection_requested|{deterministic_reason}",
            source="deterministic",
            result_shape=result_shape,
            chart_hint_from_ai=chart_hint_from_ai,
            chart_recommendation=chart_recommendation,
        )

    if not _env_bool("VISUALIZATION_CHART_SELECTOR_ENABLED", True):
        return _selection_payload(
            deterministic_type,
            reason=f"chart_selector_disabled|{deterministic_reason}",
            source="deterministic",
            result_shape=result_shape,
            chart_hint_from_ai=chart_hint_from_ai,
            chart_recommendation=chart_recommendation,
        )

    ollama_url = str(
        os.getenv("VISUALIZATION_CHART_SELECTOR_OLLAMA_URL", "http://localhost:11434/api/generate")
    ).strip()
    ollama_model = str(
        os.getenv("VISUALIZATION_CHART_SELECTOR_OLLAMA_MODEL", "gemma3:1b")
    ).strip()
    timeout_seconds = _env_int("VISUALIZATION_CHART_SELECTOR_TIMEOUT_SECONDS", 30)
    max_trace_chars = _env_int("VISUALIZATION_CHART_SELECTOR_MAX_AI_TRACE_CHARS", 50000)
    max_settings_chars = _env_int("VISUALIZATION_CHART_SELECTOR_MAX_SETTINGS_CHARS", 15000)

    prompt = _build_selector_prompt(
        name=name,
        sql=sql,
        requested_chart_type=requested_chart_type,
        visualization_settings=settings_payload,
        ai_trace=trace_payload,
        allowed_chart_types=compatible_types,
        chart_recommendation=chart_recommendation,
        max_trace_chars=max_trace_chars,
        max_settings_chars=max_settings_chars,
    )

    try:
        response = requests.post(
            ollama_url,
            json={
                "model": ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        response_payload = response.json()
        raw_output = str(response_payload.get("response") or "").strip()
    except Exception as exc:
        logger.warning(
            "Ollama chart selection failed; using deterministic chart_type=%s (%s): %s",
            deterministic_type,
            deterministic_reason,
            exc,
        )
        return _selection_payload(
            deterministic_type,
            reason=f"ollama_error:{exc}|{deterministic_reason}",
            source="deterministic",
            result_shape=result_shape,
            chart_hint_from_ai=chart_hint_from_ai,
            chart_recommendation=chart_recommendation,
        )

    extracted_token = _extract_chart_token(raw_output)
    if not extracted_token:
        logger.warning(
            "Ollama returned no chart token; using deterministic chart_type=%s (%s)",
            deterministic_type,
            deterministic_reason,
        )
        return _selection_payload(
            deterministic_type,
            reason=f"ollama_empty_response|{deterministic_reason}",
            source="deterministic",
            raw_chart_type="",
            result_shape=result_shape,
            chart_hint_from_ai=chart_hint_from_ai,
            chart_recommendation=chart_recommendation,
        )

    normalized = normalize_chart_type(extracted_token, default=DEFAULT_CHART_TYPE)
    resolved = normalized if normalized in compatible_types else deterministic_type
    if resolved not in compatible_types:
        resolved = deterministic_type
    if normalized not in compatible_types:
        logger.warning(
            "Ollama chart token %r unsupported or incompatible; coerced to deterministic chart_type=%s (%s)",
            extracted_token,
            deterministic_type,
            deterministic_reason,
        )
    reason_payload = _extract_json_object(raw_output)
    reason = str(reason_payload.get("reason") or "").strip() if reason_payload else ""

    # Hard guard: shape-first deterministic result remains authoritative for
    # strong structural signals (especially time series). This prevents model
    # drift from turning multi-metric time-series into bars.
    if str(deterministic_reason).startswith("result_shape_") and resolved != deterministic_type:
        resolved = deterministic_type
        reason = f"ollama_overridden_by_shape|{deterministic_reason}"

    return _selection_payload(
        resolved,
        reason=reason or "selected_by_ollama",
        source="ollama",
        model=ollama_model,
        raw_chart_type=extracted_token,
        result_shape=result_shape,
        chart_hint_from_ai=chart_hint_from_ai,
        chart_recommendation=chart_recommendation,
    )
