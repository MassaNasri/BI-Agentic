"""
Canonical chart taxonomy and chart contract.

Replaces the four separate chart-type enums that previously lived in:

    services/ai-service/shared/chart_types.py
    services/voice-service/voice_reports/constants/chart_types.py
    services/visualization-service/visualization_api/constants/chart_types.py
    services/report-service/voice_reports/constants/chart_types.py

This module is now the ONLY place a chart type is defined and the ONLY place a
``ChartContract`` is shaped. Visualization-service must not infer chart shape
on its own; it consumes the contract emitted by ai-service as-is and either
renders or rejects with HTTP 400.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bi_platform_shared.semantic.intent_priority import resolve_chart_semantics


class ChartTypeEnum(str, Enum):
    """Single canonical chart taxonomy used by every service."""

    LINE = "line"
    LINE_MULTI = "line_multi"
    BAR = "bar"
    BAR_GROUPED = "bar_grouped"
    BAR_STACKED = "bar_stacked"
    PIE = "pie"
    AREA = "area"
    SCATTER = "scatter"
    HISTOGRAM = "histogram"
    MAP = "map"
    HEATMAP = "heatmap"
    COMBO_LINE_BAR = "combo_line_bar"
    CUMULATIVE_LINE = "cumulative_line"
    CARD = "card"
    TABLE = "table"


_LEGACY_TO_CANONICAL: Dict[str, ChartTypeEnum] = {
    "line": ChartTypeEnum.LINE,
    "line_multi": ChartTypeEnum.LINE_MULTI,
    "multi_line": ChartTypeEnum.LINE_MULTI,
    "multiline": ChartTypeEnum.LINE_MULTI,
    "bar": ChartTypeEnum.BAR,
    "bar_grouped": ChartTypeEnum.BAR_GROUPED,
    "grouped_bar": ChartTypeEnum.BAR_GROUPED,
    "bar_stacked": ChartTypeEnum.BAR_STACKED,
    "stacked_bar": ChartTypeEnum.BAR_STACKED,
    "pie": ChartTypeEnum.PIE,
    "donut": ChartTypeEnum.PIE,
    "area": ChartTypeEnum.AREA,
    "scatter": ChartTypeEnum.SCATTER,
    "scatterplot": ChartTypeEnum.SCATTER,
    "bubble": ChartTypeEnum.SCATTER,
    "histogram": ChartTypeEnum.HISTOGRAM,
    "map": ChartTypeEnum.MAP,
    "heatmap": ChartTypeEnum.HEATMAP,
    "combo": ChartTypeEnum.COMBO_LINE_BAR,
    "combo_line_bar": ChartTypeEnum.COMBO_LINE_BAR,
    "line_bar_combo": ChartTypeEnum.COMBO_LINE_BAR,
    "cumulative_line": ChartTypeEnum.CUMULATIVE_LINE,
    "cumulative": ChartTypeEnum.CUMULATIVE_LINE,
    "card": ChartTypeEnum.CARD,
    "kpi": ChartTypeEnum.CARD,
    "number": ChartTypeEnum.CARD,
    "scalar": ChartTypeEnum.CARD,
    "table": ChartTypeEnum.TABLE,
}

_TO_METABASE_DISPLAY: Dict[ChartTypeEnum, str] = {
    ChartTypeEnum.LINE: "line",
    ChartTypeEnum.LINE_MULTI: "line",
    ChartTypeEnum.BAR: "bar",
    ChartTypeEnum.BAR_GROUPED: "bar",
    ChartTypeEnum.BAR_STACKED: "bar",
    ChartTypeEnum.PIE: "pie",
    ChartTypeEnum.AREA: "area",
    ChartTypeEnum.SCATTER: "scatter",
    # Native SQL cards in several Metabase versions do not consistently render
    # histogram display for custom queries. We map histogram semantics to bar
    # and rely on pre-binned SQL (bin_start, frequency) for deterministic output.
    ChartTypeEnum.HISTOGRAM: "bar",
    ChartTypeEnum.MAP: "map",
    ChartTypeEnum.HEATMAP: "table",
    ChartTypeEnum.COMBO_LINE_BAR: "combo",
    ChartTypeEnum.CUMULATIVE_LINE: "line",
    ChartTypeEnum.CARD: "scalar",
    ChartTypeEnum.TABLE: "table",
}


def normalize_chart_type(raw: Optional[str], *, default: ChartTypeEnum = ChartTypeEnum.TABLE) -> ChartTypeEnum:
    if raw is None:
        return default
    token = str(raw).strip().lower()
    if not token:
        return default
    return _LEGACY_TO_CANONICAL.get(token, default)


def to_metabase_display(chart_type: ChartTypeEnum | str) -> str:
    canonical = chart_type if isinstance(chart_type, ChartTypeEnum) else normalize_chart_type(chart_type)
    return _TO_METABASE_DISPLAY.get(canonical, "table")


def to_metabase_config(chart_type: ChartTypeEnum | str, chart_contract: "ChartContract", result_shape: Mapping[str, Any]):
    """Return full Metabase display/settings config for a canonical chart.

    Kept here as a backward-compatible discoverability shim; the pure
    implementation lives in ``contracts.viz`` to avoid service imports.
    """

    from bi_platform_shared.contracts.viz import to_metabase_config as _to_metabase_config

    return _to_metabase_config(chart_type, chart_contract, result_shape)


_TIME_COLUMN_TOKENS = ("date", "time", "timestamp", "period", "day", "week", "month", "quarter", "year", "ds")
_GEO_COLUMN_TOKENS = ("country", "state", "province", "city", "region", "lat", "latitude", "lon", "lng", "longitude")
_SHARE_KEYWORDS = ("share", "percentage", "proportion", "contribution", "composition", "percent")
_DISTRIBUTION_KEYWORDS = ("distribution", "histogram", "spread", "frequency")
_RELATIONSHIP_KEYWORDS = ("relationship", "correlation", "impact")
_CUMULATIVE_KEYWORDS = ("cumulative", "running total", "running sum", "accumulated")
_EXPLICIT_CHART_KEYWORDS: list[tuple[tuple[str, ...], ChartTypeEnum]] = [
    (("combo", "line and bar", "bar and line", "line + bar"), ChartTypeEnum.COMBO_LINE_BAR),
    (("line_multi", "multi-line", "multi line"), ChartTypeEnum.LINE_MULTI),
    (("bar_stacked", "stacked bar"), ChartTypeEnum.BAR_STACKED),
    (("bar_grouped", "grouped bar"), ChartTypeEnum.BAR_GROUPED),
    (("scatter", "scatterplot"), ChartTypeEnum.SCATTER),
    (("histogram",), ChartTypeEnum.HISTOGRAM),
    (("pie", "donut"), ChartTypeEnum.PIE),
    (("area",), ChartTypeEnum.AREA),
    (("heatmap",), ChartTypeEnum.HEATMAP),
    (("map",), ChartTypeEnum.MAP),
    (("table",), ChartTypeEnum.TABLE),
    (("card", "kpi"), ChartTypeEnum.CARD),
    (("line",), ChartTypeEnum.LINE),
    (("bar",), ChartTypeEnum.BAR),
]


def _is_numeric_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return False
        if stripped.startswith("-"):
            stripped = stripped[1:]
        return stripped.replace(".", "", 1).isdigit()
    return False


def _column_name(column: Any) -> str:
    if isinstance(column, dict):
        return str(column.get("name") or "").strip()
    return str(column or "").strip()


def _column_type(column: Any) -> str:
    if isinstance(column, dict):
        return str(column.get("type") or "").strip().lower()
    return ""


def _column_type_is_numeric(column_type: str) -> bool:
    lowered = str(column_type or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in ("int", "float", "decimal", "numeric", "double"))


def profile_chart_shape(columns: Sequence[Any] | None, rows: Sequence[Any] | None) -> Dict[str, Any]:
    normalized_rows = [row for row in (rows or []) if isinstance(row, dict)]
    column_specs: list[tuple[Any, str]] = [
        (raw_col, _column_name(raw_col))
        for raw_col in (columns or [])
        if _column_name(raw_col)
    ]
    normalized_columns = [name for _, name in column_specs]
    row_count = len(normalized_rows)
    sample_rows = normalized_rows[:100]
    numeric_columns: list[str] = []
    time_like_columns: list[str] = []
    geo_columns: list[str] = []
    category_columns: list[str] = []

    for raw_col, col_name in column_specs:
        lowered = col_name.lower()
        if _column_type_is_numeric(_column_type(raw_col)):
            numeric_columns.append(col_name)
        else:
            observed = [row.get(col_name) for row in sample_rows if col_name in row and row.get(col_name) is not None]
            if observed and all(_is_numeric_like(value) for value in observed):
                numeric_columns.append(col_name)
        if any(token in lowered for token in _TIME_COLUMN_TOKENS):
            time_like_columns.append(col_name)
        if any(token in lowered for token in _GEO_COLUMN_TOKENS):
            geo_columns.append(col_name)

    for col_name in normalized_columns:
        if col_name not in numeric_columns:
            category_columns.append(col_name)

    first_metric = numeric_columns[0] if numeric_columns else ""
    distinct_categories = 0
    if category_columns:
        first_category = category_columns[0]
        distinct_categories = len(
            {
                str(row.get(first_category)).strip()
                for row in sample_rows
                if row.get(first_category) is not None and str(row.get(first_category)).strip()
            }
        )

    return {
        "row_count": row_count,
        "columns": normalized_columns,
        "numeric_columns": numeric_columns,
        "time_like_columns": time_like_columns,
        "category_columns": category_columns,
        "geo_columns": geo_columns,
        "single_value": row_count == 1 and len(normalized_columns) == 1,
        "first_metric": first_metric,
        "distinct_categories": distinct_categories,
    }


def _shape_list(shape: Mapping[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for key in keys:
        raw_value = shape.get(key)
        if isinstance(raw_value, str):
            candidates = [raw_value]
        elif isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes, bytearray)):
            candidates = list(raw_value)
        else:
            continue
        for item in candidates:
            if isinstance(item, Mapping):
                name = str(item.get("name") or "").strip()
            else:
                name = str(item or "").strip()
            if not name:
                continue
            normalized = name.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            values.append(name)
    return values


def _shape_field_list(shape: Mapping[str, Any], key: str) -> list[str]:
    raw_value = shape.get(key)
    if isinstance(raw_value, str):
        return [raw_value] if raw_value.strip() else []
    if isinstance(raw_value, Mapping):
        name = str(raw_value.get("name") or "").strip()
        return [name] if name else []
    return _shape_list(shape, key)


def _normalized_shape_facts(shape: Mapping[str, Any]) -> Dict[str, Any]:
    row_count = int(shape.get("row_count", 0) or 0)
    result_type = str(shape.get("type") or shape.get("shape_type") or "").strip().lower()

    numeric_columns = _shape_list(shape, "metric_fields", "numeric_columns")
    time_columns = _shape_field_list(shape, "time_field") + _shape_list(
        shape,
        "datetime_columns",
        "time_like_columns",
        "time_columns",
    )
    category_columns = _shape_list(
        shape,
        "category_fields",
        "series_fields",
        "categorical_columns",
        "category_columns",
    )
    geo_columns = _shape_list(shape, "geo_columns")
    series_fields = _shape_list(shape, "series_fields")
    map_requested = bool(shape.get("map_requested") or shape.get("geo_requested"))

    deduped_time = list(dict.fromkeys(time_columns))
    deduped_category = list(dict.fromkeys(category_columns))
    deduped_numeric = list(dict.fromkeys(numeric_columns))

    cardinality = shape.get("cardinality") if isinstance(shape.get("cardinality"), Mapping) else {}
    distinct_categories = int(shape.get("distinct_categories", 0) or 0)
    if distinct_categories <= 0 and deduped_category and isinstance(cardinality, Mapping):
        raw_cardinality = cardinality.get(deduped_category[0])
        if isinstance(raw_cardinality, int):
            distinct_categories = raw_cardinality

    single_value = bool(shape.get("single_value") or result_type == "single_value")

    return {
        "row_count": row_count,
        "result_type": result_type,
        "numeric_columns": deduped_numeric,
        "time_like_columns": deduped_time,
        "category_columns": deduped_category,
        "geo_columns": geo_columns,
        "series_fields": series_fields,
        "map_requested": map_requested,
        "has_geo_coordinates": any(
            token in column.lower()
            for column in geo_columns
            for token in ("lat", "latitude", "lon", "lng", "longitude")
        ),
        "distinct_categories": distinct_categories,
        "single_value": single_value,
        "numeric_count": len(deduped_numeric),
        "time_count": len(deduped_time),
        "category_count": len(deduped_category),
        "geo_count": len(geo_columns),
        "series_count": len(series_fields),
    }


def chart_shape_support_failure(chart_type: ChartTypeEnum | str, shape: Mapping[str, Any]) -> Tuple[str, str]:
    canonical = chart_type if isinstance(chart_type, ChartTypeEnum) else normalize_chart_type(str(chart_type or ""), default=ChartTypeEnum.TABLE)
    facts = _normalized_shape_facts(shape)
    row_count = int(facts["row_count"])
    numeric_count = int(facts["numeric_count"])
    time_count = int(facts["time_count"])
    category_count = int(facts["category_count"])
    geo_count = int(facts["geo_count"])
    series_count = int(facts["series_count"])
    distinct_categories = int(facts["distinct_categories"])
    map_requested = bool(facts["map_requested"])
    has_geo_coordinates = bool(facts["has_geo_coordinates"])

    if canonical == ChartTypeEnum.CARD:
        if row_count != 1:
            return "requires_single_row", "Card needs exactly one result row."
        if numeric_count < 1:
            return "requires_numeric_metric", "Card needs a numeric metric."
    if canonical in {ChartTypeEnum.LINE, ChartTypeEnum.AREA, ChartTypeEnum.CUMULATIVE_LINE}:
        if row_count < 1:
            return "requires_rows", "Line-style charts need at least one row."
        if time_count < 1:
            return "requires_time_dimension", "Line-style charts need a time dimension."
        if numeric_count < 1:
            return "requires_numeric_metric", "Line-style charts need a numeric metric."
    if canonical in {ChartTypeEnum.LINE_MULTI, ChartTypeEnum.COMBO_LINE_BAR}:
        if row_count < 1:
            return "requires_rows", "Multi-series charts need at least one row."
        if time_count < 1:
            return "requires_time_dimension", "Multi-series charts need a time dimension."
        if numeric_count < 2 and not (numeric_count >= 1 and series_count >= 1):
            return "requires_multiple_metrics_or_series", "Multi-series charts need multiple metrics or one metric split by a series."
    if canonical == ChartTypeEnum.SCATTER:
        if row_count <= 1:
            return "requires_multiple_rows", "Scatter charts need more than one row."
        if numeric_count < 2:
            return "requires_two_numeric_metrics", "Scatter charts need at least two numeric metrics."
    if canonical == ChartTypeEnum.HISTOGRAM:
        if row_count <= 1:
            return "requires_multiple_rows", "Histogram needs more than one row."
        if numeric_count < 1:
            return "requires_numeric_metric", "Histogram needs a numeric metric."
    if canonical == ChartTypeEnum.BAR:
        if row_count < 1:
            return "requires_rows", "Bar chart needs at least one row."
        if category_count < 1 and time_count < 1:
            return "requires_category_or_time_dimension", "Bar chart needs a category or time bucket dimension."
        if numeric_count < 1:
            return "requires_numeric_metric", "Bar chart needs a numeric metric."
    if canonical in {ChartTypeEnum.BAR_GROUPED, ChartTypeEnum.BAR_STACKED}:
        if row_count < 1:
            return "requires_rows", "Grouped/stacked bar charts need at least one row."
        if category_count < 1:
            return "requires_category_dimension", "Grouped/stacked bar charts need a category dimension."
        if numeric_count < 2 and not (numeric_count >= 1 and series_count >= 1):
            return "requires_multiple_metrics_or_series", "Grouped/stacked bars need multiple metrics or one metric split by a series."
    if canonical == ChartTypeEnum.PIE:
        if row_count < 1:
            return "requires_rows", "Pie chart needs at least one row."
        if category_count < 1:
            return "requires_category_dimension", "Pie chart needs a category dimension."
        if numeric_count < 1:
            return "requires_numeric_metric", "Pie chart needs a numeric metric."
        if distinct_categories > 12:
            return "too_many_categories", "Pie chart supports up to 12 categories for readability."
    if canonical == ChartTypeEnum.MAP:
        if row_count < 1:
            return "requires_rows", "Map chart needs at least one row."
        if geo_count < 1:
            return "requires_geo_dimension", "Map chart needs a geographic column."
        if numeric_count < 1:
            return "requires_numeric_metric", "Map chart needs a numeric metric."
        if not (map_requested or has_geo_coordinates):
            return "requires_geo_intent", "Map chart needs explicit map or geo intent unless coordinates are present."
    if canonical == ChartTypeEnum.HEATMAP:
        if row_count < 1:
            return "requires_rows", "Heatmap needs at least one row."
        if category_count < 2:
            return "requires_two_dimensions", "Heatmap needs two categorical dimensions."
        if numeric_count < 1:
            return "requires_numeric_metric", "Heatmap needs a numeric metric."
    return "unsupported_shape", "This data shape does not support the requested chart type."


def is_chart_shape_supported(chart_type: ChartTypeEnum | str, shape: Mapping[str, Any]) -> bool:
    canonical = chart_type if isinstance(chart_type, ChartTypeEnum) else normalize_chart_type(str(chart_type or ""), default=ChartTypeEnum.TABLE)
    facts = _normalized_shape_facts(shape)
    row_count = int(facts["row_count"])
    numeric_count = int(facts["numeric_count"])
    time_count = int(facts["time_count"])
    category_count = int(facts["category_count"])
    geo_count = int(facts["geo_count"])
    series_count = int(facts["series_count"])
    distinct_categories = int(facts["distinct_categories"])
    single_value = bool(facts["single_value"])
    map_requested = bool(facts["map_requested"])
    has_geo_coordinates = bool(facts["has_geo_coordinates"])

    if canonical == ChartTypeEnum.CARD:
        return single_value or (row_count == 1 and numeric_count >= 1)
    if canonical in {ChartTypeEnum.LINE, ChartTypeEnum.AREA, ChartTypeEnum.CUMULATIVE_LINE}:
        return row_count >= 1 and time_count >= 1 and numeric_count >= 1
    if canonical in {ChartTypeEnum.LINE_MULTI, ChartTypeEnum.COMBO_LINE_BAR}:
        return row_count >= 1 and time_count >= 1 and (numeric_count >= 2 or (numeric_count >= 1 and series_count >= 1))
    if canonical == ChartTypeEnum.SCATTER:
        return row_count > 1 and numeric_count >= 2
    if canonical == ChartTypeEnum.HISTOGRAM:
        return row_count > 1 and numeric_count >= 1
    if canonical == ChartTypeEnum.BAR:
        return row_count >= 1 and (category_count >= 1 or time_count >= 1) and numeric_count >= 1
    if canonical in {ChartTypeEnum.BAR_GROUPED, ChartTypeEnum.BAR_STACKED}:
        return row_count >= 1 and category_count >= 1 and (numeric_count >= 2 or (numeric_count >= 1 and series_count >= 1))
    if canonical == ChartTypeEnum.PIE:
        return row_count >= 1 and category_count >= 1 and numeric_count >= 1 and (distinct_categories == 0 or distinct_categories <= 12)
    if canonical == ChartTypeEnum.MAP:
        return (
            row_count >= 1
            and geo_count >= 1
            and numeric_count >= 1
            and (map_requested or has_geo_coordinates)
        )
    if canonical == ChartTypeEnum.HEATMAP:
        return row_count >= 1 and category_count >= 2 and numeric_count >= 1
    if canonical == ChartTypeEnum.TABLE:
        return True
    return False


class ChartAlternative(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    chart_type: ChartTypeEnum
    display: str
    confidence: float = 0.0
    # Legacy alias retained for callers/tests that still read `score`.
    score: float = 0.0
    reason: str
    caveats: Optional[str] = None

    @model_validator(mode="after")
    def _sync_confidence_score(self) -> "ChartAlternative":
        confidence = float(self.confidence or self.score or 0.0)
        score = float(self.score or self.confidence or 0.0)
        if self.confidence != confidence:
            object.__setattr__(self, "confidence", confidence)
        if self.score != score:
            object.__setattr__(self, "score", score)
        return self


class ChartIncompatibility(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    chart_type: ChartTypeEnum
    reason_code: str
    reason: str


class ChartRecommendationResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    recommended: ChartAlternative
    alternatives: List[ChartAlternative] = Field(default_factory=list)
    incompatible: List[ChartIncompatibility] = Field(default_factory=list)
    # Legacy fields derived from `recommended` for old consumers.
    recommended_chart_type: Optional[ChartTypeEnum] = None
    chart_type: Optional[ChartTypeEnum] = None

    @model_validator(mode="after")
    def _sync_legacy_chart_type(self) -> "ChartRecommendationResult":
        chart_type = self.recommended.chart_type
        if self.recommended_chart_type is None:
            object.__setattr__(self, "recommended_chart_type", chart_type)
        if self.chart_type is None:
            object.__setattr__(self, "chart_type", chart_type)
        return self


def score_chart_type(chart_type: ChartTypeEnum | str, shape: Mapping[str, Any]) -> Tuple[float, str]:
    canonical = chart_type if isinstance(chart_type, ChartTypeEnum) else normalize_chart_type(str(chart_type or ""), default=ChartTypeEnum.TABLE)
    facts = _normalized_shape_facts(shape)
    row_count = int(facts["row_count"])
    numeric_count = int(facts["numeric_count"])
    time_count = int(facts["time_count"])
    category_count = int(facts["category_count"])
    series_count = int(facts["series_count"])
    result_type = str(facts["result_type"])

    if canonical == ChartTypeEnum.TABLE:
        return 0.35, "table_safe_fallback"
    if canonical == ChartTypeEnum.CARD:
        return (0.98, "single_value_card") if facts["single_value"] or row_count == 1 else (0.0, "card_not_single_value")
    if canonical == ChartTypeEnum.LINE:
        return (0.92, "time_series_single_metric") if time_count >= 1 and numeric_count == 1 else (0.78, "time_series_line")
    if canonical == ChartTypeEnum.LINE_MULTI:
        if time_count >= 1 and (numeric_count >= 2 or (numeric_count >= 1 and series_count >= 1)):
            return 0.94, "time_series_multi_metric_or_series"
    if canonical == ChartTypeEnum.COMBO_LINE_BAR:
        if time_count >= 1 and numeric_count >= 2:
            return 0.86, "time_series_multi_metric_combo_alternative"
    if canonical == ChartTypeEnum.AREA:
        if time_count >= 1 and numeric_count >= 1:
            return 0.72, "time_series_area_alternative"
    if canonical == ChartTypeEnum.CUMULATIVE_LINE:
        if time_count >= 1 and numeric_count >= 1:
            return 0.7, "time_series_cumulative_alternative"
    if canonical == ChartTypeEnum.BAR:
        if category_count >= 1 and numeric_count >= 1:
            return 0.88, "category_metric_bar"
        if time_count >= 1 and numeric_count >= 1 and result_type in {"time_series", "time_series_grouped"}:
            return 0.66, "time_metric_bar_alternative"
    if canonical in {ChartTypeEnum.BAR_GROUPED, ChartTypeEnum.BAR_STACKED}:
        if category_count >= 1 and (numeric_count >= 2 or (numeric_count >= 1 and series_count >= 1)):
            return 0.82, "category_multi_metric_or_series"
    if canonical == ChartTypeEnum.PIE:
        return 0.68, "small_category_share" if category_count >= 1 and numeric_count >= 1 else "pie_not_category_metric"
    if canonical == ChartTypeEnum.SCATTER:
        return 0.84, "two_numeric_relationship" if numeric_count >= 2 and time_count == 0 else "scatter_alternative"
    if canonical == ChartTypeEnum.HISTOGRAM:
        return 0.74, "numeric_distribution"
    if canonical == ChartTypeEnum.MAP:
        return 0.9, "geo_metric"
    if canonical == ChartTypeEnum.HEATMAP:
        return 0.76, "two_dimension_metric"
    return 0.0, "unsupported"


def recommend_chart_types(
    *,
    shape: Mapping[str, Any],
    preferred_chart_type: ChartTypeEnum | str | None = None,
    max_alternatives: int = 3,
) -> ChartRecommendationResult:
    compatible: list[ChartAlternative] = []
    incompatible: list[ChartIncompatibility] = []
    preferred = normalize_chart_type(str(preferred_chart_type or ""), default=ChartTypeEnum.TABLE)

    for chart_type in ChartTypeEnum:
        if is_chart_shape_supported(chart_type, shape):
            score, reason = score_chart_type(chart_type, shape)
            if chart_type == preferred and preferred != ChartTypeEnum.TABLE:
                score += 0.05
                reason = f"preferred_compatible|{reason}"
            compatible.append(
                ChartAlternative(
                    chart_type=chart_type,
                    display=to_metabase_display(chart_type),
                    confidence=round(min(score, 1.0), 4),
                    score=round(min(score, 1.0), 4),
                    reason=reason,
                )
            )
            continue
        reason_code, reason = chart_shape_support_failure(chart_type, shape)
        incompatible.append(
            ChartIncompatibility(
                chart_type=chart_type,
                reason_code=reason_code,
                reason=reason,
            )
        )

    compatible.sort(
        key=lambda item: (item.score, str(item.chart_type) != ChartTypeEnum.TABLE.value),
        reverse=True,
    )
    if not compatible:
        compatible = [
            ChartAlternative(
                chart_type=ChartTypeEnum.TABLE,
                display=to_metabase_display(ChartTypeEnum.TABLE),
                confidence=1.0,
                score=1.0,
                reason="table_safe_fallback",
            )
        ]
    primary = compatible[0]
    alternatives = compatible[1 : 1 + max(0, max_alternatives)]
    return ChartRecommendationResult(
        recommended=primary,
        alternatives=alternatives,
        incompatible=incompatible,
    )


def _extract_metric_count(intent_payload: Mapping[str, Any]) -> int:
    metrics = intent_payload.get("metrics", [])
    if not isinstance(metrics, list):
        return 0
    count = 0
    for metric in metrics:
        if isinstance(metric, dict):
            name = str(metric.get("alias") or metric.get("column") or metric.get("name") or "").strip()
        else:
            name = str(metric or "").strip()
        if name:
            count += 1
    return count


def _extract_dimension_count(intent_payload: Mapping[str, Any]) -> int:
    dimensions = intent_payload.get("dimensions", [])
    if not isinstance(dimensions, list):
        return 0
    return len([str(dim).strip() for dim in dimensions if str(dim).strip()])


def _explicit_chart_from_question(question: str) -> Optional[ChartTypeEnum]:
    normalized = str(question or "").strip().lower()
    if not normalized:
        return None
    for keywords, chart_type in _EXPLICIT_CHART_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return chart_type
    return None


def _has_any_keyword(text: str, keywords: Sequence[str]) -> bool:
    lowered = str(text or "").lower()
    return any(keyword in lowered for keyword in keywords)


_TOP_N_PATTERN = re.compile(r"\b(?:top|bottom)\s+(\d+)\b", flags=re.IGNORECASE)
_SUPERLATIVE_PATTERN = re.compile(
    r"\b(?:highest|lowest|largest|smallest|best|worst|maximum|minimum|peak)\b",
    flags=re.IGNORECASE,
)


def _to_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _ranking_chart_context(
    *,
    intent_payload: Mapping[str, Any],
    operations: set[str],
    question_text: str,
    primary_intent: str,
) -> dict[str, Any]:
    ranking_payload = intent_payload.get("ranking") if isinstance(intent_payload.get("ranking"), Mapping) else {}
    direction = str(ranking_payload.get("direction") or "").strip().upper()
    if direction not in {"ASC", "DESC"}:
        direction = ""

    limit = _to_int_or_none(intent_payload.get("limit"))
    if limit is None:
        limit = _to_int_or_none(ranking_payload.get("limit"))

    explicit_top_n_match = _TOP_N_PATTERN.search(question_text)
    explicit_top_n = bool(explicit_top_n_match)
    explicit_top_n_value = int(explicit_top_n_match.group(1)) if explicit_top_n_match else None

    ranking_requested = bool(
        direction
        or "ranking" in operations
        or primary_intent == "ranking"
        or bool(intent_payload.get("explicit_top_n_requested"))
        or explicit_top_n
    )

    if limit is None and explicit_top_n_value is not None:
        limit = explicit_top_n_value
    if limit is None and ranking_requested and _SUPERLATIVE_PATTERN.search(question_text) and not explicit_top_n:
        limit = 1

    single_winner = bool(ranking_requested and limit == 1)
    top_n = bool(ranking_requested and limit is not None and limit > 1)
    return {
        "ranking_requested": ranking_requested,
        "direction": direction or None,
        "limit": limit,
        "single_winner": single_winner,
        "top_n": top_n,
    }


def select_chart_type(
    *,
    intent: Optional[Mapping[str, Any]] = None,
    columns: Sequence[Any] | None = None,
    rows: Sequence[Any] | None = None,
    preferred_chart_type: Optional[str] = None,
    question: Optional[str] = None,
) -> Tuple[ChartTypeEnum, str]:
    """
    Deterministic chart selector used as the single chart-decision engine.

    Priority summary:
    1) Preserve a valid explicit preferred chart.
    2) Honor explicit chart mentions from question text.
    3) Intent semantics (forecast/time-series/relationship/distribution/share).
    4) Shape-safe fallbacks.
    """

    intent_payload = intent if isinstance(intent, Mapping) else {}
    shape = profile_chart_shape(columns, rows)
    row_count = int(shape.get("row_count", 0) or 0)
    operations = {
        str(op).strip().lower()
        for op in (intent_payload.get("operations", []) or [])
        if str(op).strip()
    }
    question_text = str(question or intent_payload.get("raw_question") or "").strip().lower()

    metric_count = _extract_metric_count(intent_payload)
    dimension_count = _extract_dimension_count(intent_payload)
    inferred_metric_count = max(metric_count, len(shape.get("numeric_columns", [])))
    inferred_dimension_count = max(dimension_count, len(shape.get("category_columns", [])))

    explicit_chart = _explicit_chart_from_question(question_text)
    preferred = normalize_chart_type(preferred_chart_type, default=ChartTypeEnum.TABLE)
    if preferred != ChartTypeEnum.TABLE and (row_count == 0 or is_chart_shape_supported(preferred, shape)):
        return preferred, "preferred_chart_preserved"

    if explicit_chart and (row_count == 0 or is_chart_shape_supported(explicit_chart, shape)):
        return explicit_chart, "explicit_chart_mention"

    intent_type = str(intent_payload.get("intent_type") or "").strip().lower()
    analysis_mode = str(intent_payload.get("analysis_mode") or "").strip().lower()
    primary_intent = str(intent_payload.get("intent") or "").strip().lower()
    time_grouping_detected = bool(intent_payload.get("time_grouping_detected"))
    time_granularity = str(intent_payload.get("time_granularity") or "").strip().lower()

    combo_requested = bool(
        "combo_line_bar" in operations
        or "mixed_comparison" in operations
        or bool(re.search(r"\b(line and bar|bar and line|line \+ bar|bar \+ line)\b", question_text))
    )
    time_series_requested = bool(
        time_grouping_detected
        or time_granularity in {"hour", "day", "week", "month", "quarter", "year"}
        or primary_intent == "time_series"
        or "time_grouping" in operations
        or _has_any_keyword(
            question_text,
            (
                "over time",
                "through time",
                "across time",
                "trend",
                "timeline",
                "by month",
                "by day",
                "by week",
                "by quarter",
                "by year",
                "monthly",
                "daily",
                "weekly",
                "growth",
            ),
        )
    )
    relationship_requested = bool(
        analysis_mode == "relationship"
        or primary_intent in {"correlation", "relationship"}
        or "relationship" in operations
        or _has_any_keyword(question_text, _RELATIONSHIP_KEYWORDS)
    )
    _chart_semantics = resolve_chart_semantics(question_text, intent_payload)
    if _chart_semantics.get("suppress_relationship_scatter"):
        relationship_requested = False
    if (
        bool(_chart_semantics.get("explicit_correlation"))
        and str(_chart_semantics.get("dominant_intent", "")).strip().lower() == "relationship"
    ):
        relationship_requested = True
        time_series_requested = False
    distribution_requested = bool(
        analysis_mode == "distribution"
        or primary_intent == "distribution"
        or "distribution" in operations
        or _has_any_keyword(question_text, _DISTRIBUTION_KEYWORDS)
    )
    share_requested = bool(
        "share" in operations
        or "contribution" in operations
        or "percent_of_total" in operations
        or _has_any_keyword(question_text, _SHARE_KEYWORDS)
    )
    stacked_requested = bool("stacked" in operations or "composition" in operations or "contribution" in operations)
    cumulative_requested = bool("cumulative" in operations or _has_any_keyword(question_text, _CUMULATIVE_KEYWORDS))
    map_requested = bool("geo" in operations or "map" in operations or explicit_chart == ChartTypeEnum.MAP)
    heatmap_requested = bool("heatmap" in operations or explicit_chart == ChartTypeEnum.HEATMAP)
    ranking_context = _ranking_chart_context(
        intent_payload=intent_payload,
        operations=operations,
        question_text=question_text,
        primary_intent=primary_intent,
    )
    ranking_grouped_result = bool(
        inferred_dimension_count >= 1
        or time_series_requested
        or bool(shape.get("category_columns"))
        or bool(shape.get("time_like_columns"))
    )

    # Intent-only mode (before query execution): pick deterministic chart from semantics.
    if row_count == 0:
        if intent_type == "predictive":
            if combo_requested:
                return ChartTypeEnum.COMBO_LINE_BAR, "predictive_combo_intent_only"
            return (
                (ChartTypeEnum.LINE_MULTI, "predictive_multi_series_intent_only")
                if inferred_metric_count >= 2
                else (ChartTypeEnum.LINE, "predictive_line_intent_only")
            )
        if ranking_context["ranking_requested"] and ranking_grouped_result:
            if ranking_context["single_winner"]:
                return ChartTypeEnum.CARD, "ranking_single_winner_card_intent_only"
            if ranking_context["top_n"]:
                return ChartTypeEnum.BAR, "ranking_top_n_bar_intent_only"
        if time_series_requested:
            if cumulative_requested:
                return ChartTypeEnum.CUMULATIVE_LINE, "time_series_cumulative_intent_only"
            if combo_requested and inferred_metric_count >= 2:
                return ChartTypeEnum.COMBO_LINE_BAR, "time_series_combo_intent_only"
            if inferred_metric_count >= 2 or "multi_metric" in operations:
                return ChartTypeEnum.LINE_MULTI, "time_series_multi_metric_intent_only"
            if inferred_metric_count >= 1:
                return ChartTypeEnum.LINE, "time_series_line_intent_only"
        if relationship_requested and inferred_metric_count >= 2:
            return ChartTypeEnum.SCATTER, "relationship_intent_only"
        if distribution_requested and inferred_metric_count >= 1:
            return ChartTypeEnum.HISTOGRAM, "distribution_intent_only"
        if share_requested and inferred_dimension_count >= 1 and inferred_metric_count >= 1:
            return ChartTypeEnum.PIE, "share_pie_intent_only"
        if map_requested and inferred_dimension_count >= 1 and inferred_metric_count >= 1:
            return ChartTypeEnum.MAP, "map_intent_only"
        if heatmap_requested and inferred_dimension_count >= 2 and inferred_metric_count >= 1:
            return ChartTypeEnum.HEATMAP, "heatmap_intent_only"
        if inferred_dimension_count >= 1 and inferred_metric_count >= 2:
            return (
                (ChartTypeEnum.BAR_STACKED, "category_stacked_intent_only")
                if stacked_requested
                else (ChartTypeEnum.BAR_GROUPED, "category_grouped_intent_only")
            )
        if inferred_dimension_count >= 1 and inferred_metric_count >= 1:
            return ChartTypeEnum.BAR, "category_bar_intent_only"
        if inferred_metric_count == 1:
            return ChartTypeEnum.CARD, "single_metric_card_intent_only"

    if intent_type == "predictive":
        if combo_requested and is_chart_shape_supported(ChartTypeEnum.COMBO_LINE_BAR, shape):
            return ChartTypeEnum.COMBO_LINE_BAR, "predictive_combo"
        if is_chart_shape_supported(ChartTypeEnum.LINE_MULTI, shape):
            return ChartTypeEnum.LINE_MULTI, "predictive_multi_series"
        if is_chart_shape_supported(ChartTypeEnum.LINE, shape):
            return ChartTypeEnum.LINE, "predictive_line_fallback"

    if combo_requested and is_chart_shape_supported(ChartTypeEnum.COMBO_LINE_BAR, shape):
        return ChartTypeEnum.COMBO_LINE_BAR, "explicit_combo_requested"

    if map_requested and is_chart_shape_supported(ChartTypeEnum.MAP, shape):
        return ChartTypeEnum.MAP, "geo_dimension_detected"

    if (heatmap_requested or (inferred_dimension_count >= 2 and inferred_metric_count >= 1 and not time_series_requested and not relationship_requested)):
        if is_chart_shape_supported(ChartTypeEnum.HEATMAP, shape):
            return ChartTypeEnum.HEATMAP, "two_dimensions_metric_heatmap"

    if distribution_requested and is_chart_shape_supported(ChartTypeEnum.HISTOGRAM, shape):
        return ChartTypeEnum.HISTOGRAM, "distribution_histogram"

    if shape.get("single_value") and is_chart_shape_supported(ChartTypeEnum.CARD, shape):
        return ChartTypeEnum.CARD, "single_value_card"

    if ranking_context["ranking_requested"] and ranking_grouped_result:
        if ranking_context["single_winner"]:
            if row_count == 1 and len(shape.get("numeric_columns", []) or []) >= 1:
                return ChartTypeEnum.CARD, "ranking_single_winner_card"
            if is_chart_shape_supported(ChartTypeEnum.CARD, shape):
                return ChartTypeEnum.CARD, "ranking_single_winner_card"
        if ranking_context["top_n"]:
            if row_count == 0 or is_chart_shape_supported(ChartTypeEnum.BAR, shape):
                return ChartTypeEnum.BAR, "ranking_top_n_bar"

    if time_series_requested:
        if cumulative_requested and is_chart_shape_supported(ChartTypeEnum.CUMULATIVE_LINE, shape):
            return ChartTypeEnum.CUMULATIVE_LINE, "time_series_cumulative"
        if combo_requested and is_chart_shape_supported(ChartTypeEnum.COMBO_LINE_BAR, shape):
            return ChartTypeEnum.COMBO_LINE_BAR, "time_series_combo"
        if (inferred_metric_count >= 2 or "multi_metric" in operations) and is_chart_shape_supported(ChartTypeEnum.LINE_MULTI, shape):
            return ChartTypeEnum.LINE_MULTI, "time_series_multi_metric"
        if is_chart_shape_supported(ChartTypeEnum.LINE, shape):
            return ChartTypeEnum.LINE, "time_series_line"

    if relationship_requested and not time_series_requested and is_chart_shape_supported(ChartTypeEnum.SCATTER, shape):
        return ChartTypeEnum.SCATTER, "relationship_scatter"

    if share_requested:
        if is_chart_shape_supported(ChartTypeEnum.PIE, shape):
            return ChartTypeEnum.PIE, "share_pie"
        if is_chart_shape_supported(ChartTypeEnum.BAR, shape):
            return ChartTypeEnum.BAR, "share_bar_fallback"

    category_comparison = inferred_dimension_count >= 1 and inferred_metric_count >= 1
    if category_comparison:
        if inferred_metric_count >= 2 and stacked_requested and is_chart_shape_supported(ChartTypeEnum.BAR_STACKED, shape):
            return ChartTypeEnum.BAR_STACKED, "category_multi_metric_stacked"
        if inferred_metric_count >= 2 and is_chart_shape_supported(ChartTypeEnum.BAR_GROUPED, shape):
            return ChartTypeEnum.BAR_GROUPED, "category_multi_metric_grouped"
        if is_chart_shape_supported(ChartTypeEnum.BAR, shape):
            return ChartTypeEnum.BAR, "category_single_metric_bar"

    if is_chart_shape_supported(ChartTypeEnum.LINE_MULTI, shape):
        return ChartTypeEnum.LINE_MULTI, "shape_fallback_line_multi"
    if is_chart_shape_supported(ChartTypeEnum.LINE, shape):
        return ChartTypeEnum.LINE, "shape_fallback_line"
    if not time_series_requested and is_chart_shape_supported(ChartTypeEnum.SCATTER, shape):
        return ChartTypeEnum.SCATTER, "shape_fallback_scatter"
    if is_chart_shape_supported(ChartTypeEnum.HISTOGRAM, shape):
        return ChartTypeEnum.HISTOGRAM, "shape_fallback_histogram"
    if is_chart_shape_supported(ChartTypeEnum.BAR, shape):
        return ChartTypeEnum.BAR, "shape_fallback_bar"
    if is_chart_shape_supported(ChartTypeEnum.CARD, shape):
        return ChartTypeEnum.CARD, "shape_fallback_card"
    return ChartTypeEnum.TABLE, "shape_fallback_table"


class ChartContract(BaseModel):
    """The single contract every service exchanges to describe a chart.

    The contract is *locked* at the boundary of ai-service. Downstream
    services (voice-service orchestration, visualization-service) must NOT
    re-infer chart shape; they may only validate structural compatibility
    against the actual query result and either render the chart or return
    HTTP 400.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    chart_type: ChartTypeEnum
    x_axis: Optional[str] = Field(default=None, description="Primary X-axis column name.")
    y_axis: Optional[List[str]] = Field(default=None, description="One or more Y-axis (measure) column names.")
    series_dimension: Optional[str] = Field(
        default=None,
        description="Optional dimension column used for grouping/series (e.g., region for bar_grouped).",
    )
    label_column: Optional[str] = Field(default=None, description="Label column for pie/card charts.")
    value_column: Optional[str] = Field(default=None, description="Value column for pie/card charts.")
    bin_column: Optional[str] = Field(default=None, description="Continuous column to bucket for histogram.")
    bin_count: Optional[int] = Field(default=None, ge=1, le=200)
    aggregations: List[str] = Field(default_factory=list)
    locked: bool = Field(
        default=True,
        description="When True, downstream services MUST NOT change chart_type.",
    )
    explicit_chart_lock: bool | None = Field(
        default=None,
        description="Alias of locked from ai-service traces; when set, overrides locked.",
    )
    chart_source: str = Field(
        default="ai_service",
        description="Service that authored the contract. Always 'ai_service' in production.",
    )
    rationale: Optional[str] = Field(
        default=None,
        description="Short human-readable reason for the chart selection (for trace).",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sync_explicit_chart_lock(self) -> "ChartContract":
        if self.explicit_chart_lock is not None:
            object.__setattr__(self, "locked", bool(self.explicit_chart_lock))
        return self

    @field_validator("chart_type", mode="before")
    @classmethod
    def _coerce_chart_type(cls, value: Any) -> Any:
        if isinstance(value, ChartTypeEnum):
            return value
        if isinstance(value, str):
            return normalize_chart_type(value).value
        return value

    @field_validator("y_axis", mode="before")
    @classmethod
    def _coerce_y_axis(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, str):
            return [value]
        return value

    def required_columns(self) -> List[str]:
        """Columns that MUST exist in the query result for this contract to render.

        Used by visualization-service for the structural compatibility check
        described in the audit's CRIT-03 fix.
        """

        cols: List[str] = []
        if self.x_axis:
            cols.append(self.x_axis)
        if self.y_axis:
            cols.extend(self.y_axis)
        if self.series_dimension:
            cols.append(self.series_dimension)
        if self.label_column:
            cols.append(self.label_column)
        if self.value_column:
            cols.append(self.value_column)
        if self.bin_column:
            cols.append(self.bin_column)
        return [c for c in dict.fromkeys(cols) if c]

    def metabase_display(self) -> str:
        return to_metabase_display(self.chart_type)


__all__ = [
    "ChartTypeEnum",
    "ChartContract",
    "ChartAlternative",
    "ChartIncompatibility",
    "ChartRecommendationResult",
    "profile_chart_shape",
    "is_chart_shape_supported",
    "chart_shape_support_failure",
    "score_chart_type",
    "recommend_chart_types",
    "select_chart_type",
    "normalize_chart_type",
    "to_metabase_display",
    "to_metabase_config",
]
