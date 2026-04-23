from __future__ import annotations

from typing import Any

from shared.stage_contract import normalize_stage_status


def clamp_confidence(value: Any, default: float = 0.5) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    return max(0.0, min(1.0, numeric))


def stage_confidence(
    payload: dict[str, Any] | None,
    *,
    base_success: float = 0.9,
    base_degraded: float = 0.62,
    base_failed: float = 0.0,
) -> float:
    if not isinstance(payload, dict):
        return base_failed
    if "confidence" in payload:
        return clamp_confidence(payload.get("confidence"))

    status = normalize_stage_status(payload.get("status"), degraded=bool(payload.get("degraded")))
    if status == "success":
        score = base_success
    elif status == "degraded":
        score = base_degraded
    elif status in {"failed", "rejected", "skipped"}:
        score = base_failed
    else:
        score = min(base_degraded, 0.5)

    if payload.get("deferred") or payload.get("degraded"):
        score -= 0.12
    if payload.get("warnings"):
        score -= min(0.12, 0.03 * len(payload.get("warnings", [])))
    if payload.get("errors"):
        score -= min(0.2, 0.05 * len(payload.get("errors", [])))
    return clamp_confidence(score)


def preprocessing_low_confidence(payload: dict[str, Any] | None) -> float:
    score = stage_confidence(payload, base_success=0.92, base_degraded=0.7)
    if not isinstance(payload, dict):
        return score
    debug = payload.get("debug_metadata", {}) if isinstance(payload.get("debug_metadata"), dict) else {}
    if debug.get("llm_fallback_used"):
        score -= 0.08
    cleaned = str(payload.get("cleaned_text", "")).strip()
    if not cleaned:
        score -= 0.35
    return clamp_confidence(score)


def schema_confidence(payload: dict[str, Any] | None) -> float:
    score = stage_confidence(payload, base_success=0.9, base_degraded=0.55)
    if not isinstance(payload, dict):
        return score
    if payload.get("schema_valid") is False:
        score -= 0.35
    if payload.get("deferred"):
        score -= 0.18
    invalid_count = len(payload.get("invalid_mappings", []) or [])
    unresolved_count = len(payload.get("unresolved_terms", []) or [])
    unsupported_count = len(payload.get("unsupported_terms", []) or [])
    score -= min(0.3, 0.06 * (invalid_count + unresolved_count + unsupported_count))
    return clamp_confidence(score)


def forecasting_confidence(payload: dict[str, Any] | None) -> float:
    if not isinstance(payload, dict) or str(payload.get("status", "")).strip().lower() == "skipped":
        return 1.0
    score = stage_confidence(payload, base_success=0.9, base_degraded=0.55)
    downstream = payload.get("downstream_result", {}) if isinstance(payload.get("downstream_result"), dict) else {}
    meta = downstream.get("forecast_meta", {}) if isinstance(downstream.get("forecast_meta"), dict) else {}
    if meta and not bool(meta.get("forecast_available", False)):
        score -= 0.2
    return clamp_confidence(score)


def pipeline_confidence(
    *,
    preprocessing_low: dict[str, Any] | None = None,
    classification: dict[str, Any] | None = None,
    preprocessing_high: dict[str, Any] | None = None,
    intent_extraction: dict[str, Any] | None = None,
    query_execution: dict[str, Any] | None = None,
    visualization: dict[str, Any] | None = None,
    forecasting: dict[str, Any] | None = None,
) -> dict[str, Any]:
    components = {
        "preprocessing_low": preprocessing_low_confidence(preprocessing_low),
        "classification": stage_confidence(classification, base_success=0.88, base_degraded=0.6),
        "schema": schema_confidence(preprocessing_high),
        "intent_extraction": stage_confidence(intent_extraction, base_success=0.86, base_degraded=0.58),
        "query_execution": stage_confidence(query_execution, base_success=0.9, base_degraded=0.55),
        "visualization": stage_confidence(visualization, base_success=0.88, base_degraded=0.58),
        "forecasting": forecasting_confidence(forecasting),
    }
    weights = {
        "preprocessing_low": 0.12,
        "classification": 0.18,
        "schema": 0.22,
        "intent_extraction": 0.16,
        "query_execution": 0.16,
        "visualization": 0.08,
        "forecasting": 0.08,
    }
    aggregate = sum(components[name] * weights[name] for name in components)
    return {
        "score": clamp_confidence(aggregate),
        "components": components,
        "weights": weights,
    }
