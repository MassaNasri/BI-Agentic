"""
Shared forecasting modules for TimesFM integration.
"""

try:
    from forecasting.pipeline import (
        ForecastingError,
        build_forecast_dataset,
        detect_forecast_request,
    )
    from forecasting.timesfm_service import forecast, get_model
except ModuleNotFoundError as exc:
    raise RuntimeError(
        "Forecasting module not found. Check PYTHONPATH and container mount."
    ) from exc

__all__ = [
    "ForecastingError",
    "build_forecast_dataset",
    "detect_forecast_request",
    "forecast",
    "get_model",
]
