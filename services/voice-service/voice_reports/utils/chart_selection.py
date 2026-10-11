from __future__ import annotations

from typing import Any

from bi_platform_shared.contracts.chart import profile_chart_shape
from voice_reports.constants import normalize_chart_type


def profile_result_shape(columns: list[Any], rows: list[Any]) -> dict[str, Any]:
    return profile_chart_shape(columns, rows)


def extract_upstream_chart_type(
    *,
    chart_config: dict[str, Any] | None,
    pipeline_trace: dict[str, Any] | None,
) -> str:
    def _normalize_if_present(value: Any) -> str:
        token = str(value or "").strip()
        if not token:
            return ""
        return normalize_chart_type(token, default="")

    chart_payload = chart_config if isinstance(chart_config, dict) else {}
    trace_payload = pipeline_trace if isinstance(pipeline_trace, dict) else {}

    visualization_stage = trace_payload.get("visualization", {}) if isinstance(trace_payload.get("visualization"), dict) else {}
    final_output = visualization_stage.get("final_output", {}) if isinstance(visualization_stage.get("final_output"), dict) else {}
    for candidate in (
        final_output.get("selected_chart_type"),
        final_output.get("chart_type"),
        (
            final_output.get("visualization_payload_preview", {})
            if isinstance(final_output.get("visualization_payload_preview"), dict)
            else {}
        ).get("chart_type"),
        (
            final_output.get("visualization_payload_preview", {})
            if isinstance(final_output.get("visualization_payload_preview"), dict)
            else {}
        ).get("type"),
        visualization_stage.get("selected_chart_type"),
        visualization_stage.get("chart_type"),
    ):
        normalized = _normalize_if_present(candidate)
        if normalized:
            return normalized

    upstream_chart = chart_payload.get("upstream_chart")
    if isinstance(upstream_chart, dict):
        candidate = (
            upstream_chart.get("selected_chart_type")
            or upstream_chart.get("chart_type")
            or upstream_chart.get("type")
        )
        normalized = _normalize_if_present(candidate)
        if normalized:
            return normalized
    return ""


def infer_chart_type(
    *,
    columns: list[Any],
    rows: list[Any],
    intent: dict[str, Any] | None,
    preferred_chart_type: str | None = None,
) -> str:
    _ = columns, rows, intent
    token = str(preferred_chart_type or "").strip()
    if not token:
        return ""
    return normalize_chart_type(token, default="")
