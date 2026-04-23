from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

_MODEL_LOCK = threading.Lock()
_MODEL: Any | None = None
_MODEL_API: str = "unknown"
_MODEL_VERSION: str = "unknown"


class TimesFMServiceError(Exception):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class _ModelBundle:
    model: Any
    api: str
    version: str


def _forecasting_root() -> Path:
    return Path(__file__).resolve().parent


def _ensure_timesfm_import_path() -> None:
    root = _forecasting_root()
    candidates = (
        root / "timesfm" / "src",
        root / "timesfm" / "v1" / "src",
        root / "timesfm",
    )
    for candidate in candidates:
        candidate_str = str(candidate)
        if candidate.exists() and candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)


def _resolve_model_source() -> str:
    model_dir = os.getenv("TIMESFM_MODEL_DIR", "").strip()
    if model_dir:
        candidate = Path(model_dir)
        if candidate.exists():
            return str(candidate)
    return os.getenv("TIMESFM_MODEL_ID", "google/timesfm-2.5-200m-pytorch").strip()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _read_timesfm_version(timesfm_module: Any) -> str:
    version_attr = getattr(timesfm_module, "__version__", None)
    if isinstance(version_attr, str) and version_attr.strip():
        return version_attr.strip()
    try:
        from importlib.metadata import version  # noqa: PLC0415

        return str(version("timesfm"))
    except Exception:
        return "unknown"


def _load_timesfm_v2_model(*, timesfm_module: Any, model_source: str) -> _ModelBundle | None:
    constructor = getattr(timesfm_module, "TimesFM_2p5_200M_torch", None)
    if constructor is None:
        try:
            from timesfm.timesfm_2p5.timesfm_2p5_torch import TimesFM_2p5_200M_torch  # noqa: PLC0415

            constructor = TimesFM_2p5_200M_torch
        except Exception:
            return None

    model = constructor.from_pretrained(
        model_source,
        local_files_only=True,
    )
    forecast_config_cls = getattr(timesfm_module, "ForecastConfig", None)
    if forecast_config_cls is not None:
        model.compile(
            forecast_config_cls(
                max_context=_int_env("TIMESFM_MAX_CONTEXT", 1024),
                max_horizon=_int_env("TIMESFM_MAX_HORIZON", 256),
                normalize_inputs=True,
                use_continuous_quantile_head=True,
                force_flip_invariance=True,
                infer_is_positive=True,
                fix_quantile_crossing=True,
            )
        )
    return _ModelBundle(model=model, api="timesfm_v2_5", version=_read_timesfm_version(timesfm_module))


def _load_timesfm_v1_model(*, timesfm_module: Any, model_source: str) -> _ModelBundle | None:
    timesfm_class = getattr(timesfm_module, "TimesFm", None)
    hparams_cls = getattr(timesfm_module, "TimesFmHparams", None)
    checkpoint_cls = getattr(timesfm_module, "TimesFmCheckpoint", None)
    if timesfm_class is None or hparams_cls is None or checkpoint_cls is None:
        return None

    hparams = hparams_cls(
        backend=os.getenv("TIMESFM_V1_BACKEND", "cpu"),
        per_core_batch_size=_int_env("TIMESFM_V1_PER_CORE_BATCH_SIZE", 32),
        horizon_len=_int_env("TIMESFM_MAX_HORIZON", 256),
    )
    checkpoint = checkpoint_cls(huggingface_repo_id=model_source)
    model = timesfm_class(hparams=hparams, checkpoint=checkpoint)
    return _ModelBundle(model=model, api="timesfm_v1", version=_read_timesfm_version(timesfm_module))


def get_model() -> Any:
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    with _MODEL_LOCK:
        global _MODEL_API, _MODEL_VERSION
        if _MODEL is not None:
            return _MODEL

        _ensure_timesfm_import_path()
        try:
            import torch  # noqa: PLC0415
            import timesfm  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            raise TimesFMServiceError(
                "timesfm_import_failed",
                "Failed to import TimesFM runtime.",
                details={"error": str(exc)},
            ) from exc

        try:
            torch.set_float32_matmul_precision("high")
        except Exception:
            pass

        model_source = _resolve_model_source()
        load_errors: list[str] = []

        try:
            bundle = _load_timesfm_v2_model(timesfm_module=timesfm, model_source=model_source)
            if bundle is not None:
                _MODEL = bundle.model
                _MODEL_API = bundle.api
                _MODEL_VERSION = bundle.version
                return _MODEL
        except Exception as exc:  # noqa: BLE001
            load_errors.append(f"timesfm_v2_5_load_failed: {exc}")

        try:
            bundle = _load_timesfm_v1_model(timesfm_module=timesfm, model_source=model_source)
            if bundle is not None:
                _MODEL = bundle.model
                _MODEL_API = bundle.api
                _MODEL_VERSION = bundle.version
                return _MODEL
        except Exception as exc:  # noqa: BLE001
            load_errors.append(f"timesfm_v1_load_failed: {exc}")

        raise TimesFMServiceError(
            "timesfm_model_load_failed",
            "Failed to initialize TimesFM model from local cache/model directory.",
            details={
                "model_source": model_source,
                "load_errors": load_errors,
            },
        )


def _default_horizon() -> int:
    return max(1, _int_env("TIMESFM_DEFAULT_HORIZON", 12))


def _forecast_with_timesfm(series: np.ndarray, horizon: int) -> dict[str, Any]:
    model = get_model()
    try:
        if _MODEL_API == "timesfm_v1":
            point_forecast, quantile_forecast = model.forecast(
                inputs=[series],
                freq=[0],
                normalize=True,
            )
            point_values = np.asarray(point_forecast)[0].astype(float).tolist()[:horizon]
            quantiles_array = np.asarray(quantile_forecast)[0].astype(float)[:horizon]
        else:
            point_forecast, quantile_forecast = model.forecast(
                horizon=horizon,
                inputs=[series],
            )
            point_values = np.asarray(point_forecast)[0].astype(float).tolist()
            quantiles_array = np.asarray(quantile_forecast)[0].astype(float)
    except Exception as exc:  # noqa: BLE001
        raise TimesFMServiceError(
            "timesfm_forecast_failed",
            "TimesFM forecast execution failed.",
            details={"error": str(exc), "api": _MODEL_API, "version": _MODEL_VERSION},
        ) from exc

    quantiles_named: dict[str, list[float]] = {}
    if quantiles_array.ndim == 2 and quantiles_array.shape[1] >= 10:
        quantiles_named = {
            "q10": quantiles_array[:, 1].tolist(),
            "q50": quantiles_array[:, 5].tolist(),
            "q90": quantiles_array[:, 9].tolist(),
        }

    return {
        "horizon": horizon,
        "point_forecast": point_values,
        "quantile_forecast": quantiles_array.tolist() if quantiles_array.size else [],
        "quantiles": quantiles_named,
        "model_status": {
            "provider": "timesfm",
            "api": _MODEL_API,
            "version": _MODEL_VERSION,
            "used_fallback": False,
            "fallback_reason": "",
        },
    }


def _forecast_with_prophet(series: np.ndarray, horizon: int) -> dict[str, Any]:
    try:
        import pandas as pd  # noqa: PLC0415
        from prophet import Prophet  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        raise TimesFMServiceError(
            "prophet_unavailable",
            "Prophet fallback is unavailable.",
            details={"error": str(exc)},
        ) from exc

    history = pd.DataFrame({"ds": pd.date_range(start="2000-01-01", periods=len(series), freq="D"), "y": series})
    model = Prophet(daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=True)
    model.fit(history)
    future = model.make_future_dataframe(periods=horizon, freq="D", include_history=False)
    forecast_df = model.predict(future)
    point_values = forecast_df["yhat"].astype(float).tolist()
    q10 = forecast_df["yhat_lower"].astype(float).tolist()
    q90 = forecast_df["yhat_upper"].astype(float).tolist()
    q50 = point_values
    quantile_forecast = [[q50[i], q10[i], q50[i], q90[i]] for i in range(len(point_values))]
    return {
        "horizon": horizon,
        "point_forecast": point_values,
        "quantile_forecast": quantile_forecast,
        "quantiles": {"q10": q10, "q50": q50, "q90": q90},
        "model_status": {
            "provider": "prophet",
            "api": "prophet",
            "version": "unknown",
            "used_fallback": True,
            "fallback_reason": "timesfm_unavailable",
        },
    }


def _forecast_with_naive(series: np.ndarray, horizon: int, *, fallback_reason: str) -> dict[str, Any]:
    if len(series) >= 2:
        slope = float((series[-1] - series[0]) / max(1, len(series) - 1))
    else:
        slope = 0.0
    last_value = float(series[-1])
    point_values = [last_value + (slope * step) for step in range(1, horizon + 1)]
    q10 = [value * 0.95 for value in point_values]
    q50 = point_values
    q90 = [value * 1.05 for value in point_values]
    quantile_forecast = [[q50[i], q10[i], q50[i], q90[i]] for i in range(len(point_values))]
    return {
        "horizon": horizon,
        "point_forecast": point_values,
        "quantile_forecast": quantile_forecast,
        "quantiles": {"q10": q10, "q50": q50, "q90": q90},
        "model_status": {
            "provider": "naive",
            "api": "naive_linear",
            "version": "n/a",
            "used_fallback": True,
            "fallback_reason": fallback_reason,
        },
    }


def forecast(values: list[float], horizon: int | None = None) -> dict[str, Any]:
    if not isinstance(values, list) or not values:
        raise TimesFMServiceError(
            "invalid_input_series",
            "TimesFM input series must be a non-empty list of numbers.",
        )

    series = np.asarray(values, dtype=float)
    if series.ndim != 1:
        raise TimesFMServiceError(
            "invalid_input_shape",
            "TimesFM expects a single 1D series.",
            details={"shape": list(series.shape)},
        )
    if not np.isfinite(series).all():
        raise TimesFMServiceError(
            "invalid_input_values",
            "Input series contains NaN or Infinity values.",
        )

    forecast_horizon = int(horizon or _default_horizon())
    if forecast_horizon <= 0:
        raise TimesFMServiceError(
            "invalid_horizon",
            "Forecast horizon must be a positive integer.",
            details={"horizon": forecast_horizon},
        )

    try:
        return _forecast_with_timesfm(series, forecast_horizon)
    except TimesFMServiceError as exc:
        try:
            prophet_output = _forecast_with_prophet(series, forecast_horizon)
            prophet_output["model_status"]["fallback_reason"] = exc.code
            return prophet_output
        except TimesFMServiceError:
            return _forecast_with_naive(series, forecast_horizon, fallback_reason=exc.code)
