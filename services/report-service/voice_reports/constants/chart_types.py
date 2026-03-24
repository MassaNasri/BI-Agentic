"""
Central chart type constants and mappings used across voice report execution.
"""

from typing import Optional


class ChartType:
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    TABLE = "table"
    KPI = "kpi"


VALID_CHART_TYPES = {
    ChartType.BAR,
    ChartType.LINE,
    ChartType.PIE,
    ChartType.TABLE,
    ChartType.KPI,
}

# Normalize legacy or external values to canonical chart types.
LEGACY_TO_CANONICAL_CHART_TYPE = {
    "grouped_bar": ChartType.BAR,
    "scalar": ChartType.KPI,
    "number": ChartType.KPI,
    "kpi": ChartType.KPI,
    "bar": ChartType.BAR,
    "line": ChartType.LINE,
    "pie": ChartType.PIE,
    "table": ChartType.TABLE,
}

# Map canonical chart types to Metabase display types.
CHART_TYPE_TO_METABASE_DISPLAY = {
    ChartType.BAR: "bar",
    ChartType.LINE: "line",
    ChartType.PIE: "pie",
    ChartType.TABLE: "table",
    ChartType.KPI: "scalar",
}


def normalize_chart_type(
    raw_chart_type: Optional[str], *, default: str = ChartType.TABLE
) -> str:
    """
    Convert potentially inconsistent chart labels into a canonical chart type.
    Unknown values are mapped to the provided default.
    """
    if not raw_chart_type:
        return default
    normalized = str(raw_chart_type).strip().lower()
    return LEGACY_TO_CANONICAL_CHART_TYPE.get(normalized, default)


def to_metabase_display(chart_type: Optional[str]) -> str:
    """
    Return a Metabase-compatible display type from a canonical/legacy chart type.
    """
    canonical_chart_type = normalize_chart_type(chart_type)
    return CHART_TYPE_TO_METABASE_DISPLAY.get(canonical_chart_type, "table")

