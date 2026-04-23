from __future__ import annotations

from typing import Any

try:
    from forecasting.pipeline import ForecastingError, build_forecast_dataset
except ModuleNotFoundError as exc:
    raise RuntimeError(
        "Forecasting module not found. Check PYTHONPATH and container mount."
    ) from exc


def run_forecasting_handler(payload: dict[str, Any]) -> dict[str, Any]:
    historical_data = payload.get("historical_data", {}) if isinstance(payload, dict) else {}
    intent = payload.get("intent", {}) if isinstance(payload, dict) else {}

    columns = historical_data.get("columns", []) if isinstance(historical_data, dict) else []
    rows = historical_data.get("rows", []) if isinstance(historical_data, dict) else []
    horizon = None
    if isinstance(intent, dict):
        horizon = intent.get("forecast_horizon")

    try:
        result = build_forecast_dataset(
            columns=columns,
            rows=rows,
            intent=intent if isinstance(intent, dict) else {},
            horizon=horizon,
        )
        forecast_meta = result.get("meta", {}) if isinstance(result.get("meta"), dict) else {}
        forecast_available = bool(forecast_meta.get("forecast_available", False))
        visualization_mode = str(forecast_meta.get("visualization_mode", "")).strip() or (
            "historical_plus_forecast" if forecast_available else "historical_only"
        )
        fallback_reason = str(forecast_meta.get("fallback_reason", "")).strip()
        chart_series_config = (
            forecast_meta.get("chart_series_config", [])
            if isinstance(forecast_meta.get("chart_series_config"), list)
            else []
        )
        visualization_payload = {
            "chart_type": "line",
            "mode": visualization_mode,
            "series": result.get("rows", []),
            "series_type_field": "series_type",
            "series_label_field": "series_label",
            "preferred_color_role_field": "preferred_color_role",
            "chart_series_config": chart_series_config,
            "message": "" if forecast_available else "Forecast unavailable",
            "reason_chart_selected": (
                "Forecast line chart with actual vs forecast"
                if forecast_available
                else "Historical-only chart because forecast is unavailable"
            ),
            "reason_chart_not_generated": "",
            "forecast_available": forecast_available,
            "fallback_reason": fallback_reason,
        }
        return {
            "status": "degraded" if not forecast_available else "success",
            "degraded": not forecast_available,
            "degradation_reason": fallback_reason if not forecast_available else "",
            "next_step": "forecasting",
            "forecast_dataset": {
                "columns": result["columns"],
                "rows": result["rows"],
            },
            "forecast_sql": result["sql"],
            "forecast_meta": forecast_meta,
            "visualization_mode": visualization_mode,
            "visualization_payload": visualization_payload,
        }
    except ForecastingError as exc:
        fallback_rows = [
            {
                "ds": str(row.get("ds")),
                "value": row.get("value"),
                "series_type": "actual",
                "series_label": "Actual",
                "preferred_color_role": "actual",
            }
            for row in rows
            if isinstance(row, dict) and row.get("ds") is not None and row.get("value") is not None
        ]
        chart_series_config = [
            {
                "series_type": "actual",
                "series_label": "Actual",
                "preferred_color_role": "actual",
                "preferred_color": "#2563eb",
                "stroke_dasharray": "",
            }
        ]
        return {
            "status": "degraded",
            "degraded": True,
            "degradation_reason": exc.code,
            "next_step": "forecasting",
            "error": exc.to_dict(),
            "forecast_dataset": {
                "columns": ["ds", "value", "series_type", "series_label", "preferred_color_role"],
                "rows": fallback_rows,
            },
            "forecast_sql": "",
            "forecast_meta": {
                "forecast_available": False,
                "visualization_mode": "historical_only",
                "forecast_unavailable_label": "Forecast unavailable",
                "fallback_reason": exc.code,
                "forecasting_model_status": {
                    "provider": "none",
                    "used_fallback": True,
                    "fallback_reason": exc.code,
                },
                "chart_series_config": chart_series_config,
            },
            "visualization_mode": "historical_only",
            "visualization_payload": {
                "chart_type": "line",
                "mode": "historical_only",
                "series": fallback_rows,
                "series_type_field": "series_type",
                "series_label_field": "series_label",
                "preferred_color_role_field": "preferred_color_role",
                "chart_series_config": chart_series_config,
                "message": "Forecast unavailable",
                "reason_chart_selected": "Historical-only chart because forecast failed",
                "reason_chart_not_generated": "",
                "forecast_available": False,
                "fallback_reason": exc.code,
            },
        }
