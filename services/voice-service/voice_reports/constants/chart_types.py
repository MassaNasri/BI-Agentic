"""
Voice-service compatibility wrapper around the canonical shared chart contract.
"""

from __future__ import annotations

from typing import Optional

from bi_platform_shared.contracts.chart import (
    ChartTypeEnum,
    normalize_chart_type as _normalize_chart_type_shared,
    to_metabase_display as _to_metabase_display_shared,
)


class ChartType:
    LINE = ChartTypeEnum.LINE.value
    LINE_MULTI = ChartTypeEnum.LINE_MULTI.value
    BAR = ChartTypeEnum.BAR.value
    BAR_GROUPED = ChartTypeEnum.BAR_GROUPED.value
    BAR_STACKED = ChartTypeEnum.BAR_STACKED.value
    PIE = ChartTypeEnum.PIE.value
    AREA = ChartTypeEnum.AREA.value
    SCATTER = ChartTypeEnum.SCATTER.value
    HISTOGRAM = ChartTypeEnum.HISTOGRAM.value
    MAP = ChartTypeEnum.MAP.value
    HEATMAP = ChartTypeEnum.HEATMAP.value
    COMBO_LINE_BAR = ChartTypeEnum.COMBO_LINE_BAR.value
    CUMULATIVE_LINE = ChartTypeEnum.CUMULATIVE_LINE.value
    CARD = ChartTypeEnum.CARD.value
    TABLE = ChartTypeEnum.TABLE.value
    # Legacy alias retained for backward compatibility.
    KPI = CARD


VALID_CHART_TYPES = {chart.value for chart in ChartTypeEnum}

LEGACY_TO_CANONICAL_CHART_TYPE = {
    legacy: canonical.value
    for legacy, canonical in {
        "grouped_bar": ChartTypeEnum.BAR_GROUPED,
        "scalar": ChartTypeEnum.CARD,
        "number": ChartTypeEnum.CARD,
        "kpi": ChartTypeEnum.CARD,
        "card": ChartTypeEnum.CARD,
        "bar": ChartTypeEnum.BAR,
        "line": ChartTypeEnum.LINE,
        "line_multi": ChartTypeEnum.LINE_MULTI,
        "multi_line": ChartTypeEnum.LINE_MULTI,
        "pie": ChartTypeEnum.PIE,
        "table": ChartTypeEnum.TABLE,
        "scatter": ChartTypeEnum.SCATTER,
        "histogram": ChartTypeEnum.HISTOGRAM,
        "map": ChartTypeEnum.MAP,
        "heatmap": ChartTypeEnum.HEATMAP,
        "combo": ChartTypeEnum.COMBO_LINE_BAR,
        "combo_line_bar": ChartTypeEnum.COMBO_LINE_BAR,
        "cumulative_line": ChartTypeEnum.CUMULATIVE_LINE,
    }.items()
}

CHART_TYPE_TO_METABASE_DISPLAY = {
    chart.value: _to_metabase_display_shared(chart)
    for chart in ChartTypeEnum
}


def normalize_chart_type(raw_chart_type: Optional[str], *, default: str = ChartType.TABLE) -> str:
    default_enum = _normalize_chart_type_shared(default, default=ChartTypeEnum.TABLE)
    return _normalize_chart_type_shared(raw_chart_type, default=default_enum).value


def to_metabase_display(chart_type: Optional[str]) -> str:
    return _to_metabase_display_shared(chart_type or ChartType.TABLE)

