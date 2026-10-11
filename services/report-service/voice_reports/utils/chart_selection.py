from __future__ import annotations

from typing import Any

from bi_platform_shared.contracts.chart import profile_chart_shape, select_chart_type
from voice_reports.constants import ChartType, normalize_chart_type


def profile_result_shape(columns: list[Any], rows: list[Any]) -> dict[str, Any]:
    return profile_chart_shape(columns, rows)


def infer_chart_type(
    *,
    columns: list[Any],
    rows: list[Any],
    intent: dict[str, Any] | None,
    preferred_chart_type: str | None = None,
) -> str:
    chart_type, _reason = select_chart_type(
        intent=intent if isinstance(intent, dict) else {},
        columns=columns if isinstance(columns, list) else [],
        rows=rows if isinstance(rows, list) else [],
        preferred_chart_type=preferred_chart_type,
    )
    return normalize_chart_type(chart_type.value, default=ChartType.TABLE)

