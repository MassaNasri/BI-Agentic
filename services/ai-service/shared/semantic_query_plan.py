"""
Canonical SemanticQueryPlan contract.

Normalizes the output of normalize_analytical_intent into the standard
contract format used for downstream SQL compilation, chart selection,
and Metabase rendering.

This module does NOT change any logic - it provides a typed view over
the existing intent dict produced by query_planner.normalize_analytical_intent.
"""

from __future__ import annotations

from typing import Any


def build_semantic_query_plan(
    *,
    question: str,
    normalized_intent: dict[str, Any],
) -> dict[str, Any]:
    """
    Build a canonical SemanticQueryPlan from a normalized_intent dict.

    This is a projection/normalization layer, not a logic layer.
    All reasoning is done by normalize_analytical_intent before this point.
    """
    intent_type = str(normalized_intent.get("intent_type") or "analytical").strip().lower()
    primary_intent = str(normalized_intent.get("intent") or "projection").strip().lower()
    analysis_mode = str(normalized_intent.get("analysis_mode") or "").strip().lower()

    metrics_raw = normalized_intent.get("metrics") or []
    metric_columns = [
        str(m.get("column") or "").strip()
        for m in metrics_raw
        if isinstance(m, dict) and str(m.get("column") or "").strip()
    ]

    dimensions = [
        str(d).strip()
        for d in (normalized_intent.get("dimensions") or [])
        if str(d).strip()
    ]

    time_grouping_detected = bool(normalized_intent.get("time_grouping_detected"))
    time_granularity = str(normalized_intent.get("time_granularity") or "").strip().lower()
    time_grain_source = str(normalized_intent.get("time_grain_source") or "none").strip().lower()
    detected_time_phrase = str(normalized_intent.get("detected_time_phrase") or "").strip()

    filters = [
        {
            "column": str(f.get("column") or "").strip(),
            "operator": str(f.get("operator") or "").strip(),
            "value": f.get("value"),
            "source_text": str(f.get("source_text") or "").strip(),
            "source": str(f.get("source") or "").strip(),
        }
        for f in (normalized_intent.get("filters") or [])
        if isinstance(f, dict) and str(f.get("column") or "").strip()
    ]

    ranking_payload = normalized_intent.get("ranking") if isinstance(normalized_intent.get("ranking"), dict) else {}
    ranking_direction = str(ranking_payload.get("direction") or "").strip().upper()
    ranking_enabled = bool(ranking_direction in {"ASC", "DESC"} or ranking_payload.get("requested"))

    limit = normalized_intent.get("limit")
    if isinstance(limit, int) and limit > 0:
        pass
    else:
        limit = None

    operations = [
        str(op).strip().lower()
        for op in (normalized_intent.get("operations") or [])
        if str(op).strip()
    ]

    comparison = "comparison" in operations or "multi_metric" in operations
    relationship = analysis_mode == "relationship" or "relationship" in operations
    distribution = analysis_mode == "distribution" or "distribution" in operations

    chart_hint = _infer_chart_hint(
        primary_intent=primary_intent,
        time_grouping_detected=time_grouping_detected,
        relationship=relationship,
        distribution=distribution,
        ranking_enabled=ranking_enabled,
        limit=limit,
        num_metrics=len(metric_columns),
        has_filters=bool(filters),
    )

    return {
        "intent": intent_type,
        "metrics": metric_columns,
        "dimensions": dimensions,
        "time": {
            "enabled": time_grouping_detected,
            "grain": time_granularity or None,
            "source": time_grain_source,
            "matched_phrase": detected_time_phrase or None,
        },
        "filters": filters,
        "ranking": {
            "enabled": ranking_enabled,
            "direction": ranking_direction.lower() if ranking_direction else None,
            "limit": limit,
            "metric": (
                str(metrics_raw[0].get("alias") or "").strip()
                if metrics_raw and isinstance(metrics_raw[0], dict) and ranking_enabled
                else None
            ),
            "source": str(ranking_payload.get("source") or "").strip() or None,
        },
        "comparison": comparison,
        "relationship": relationship,
        "distribution": distribution,
        "operations": operations,
        "chart_hint": chart_hint,
        "confidence": _compute_confidence(normalized_intent),
        "provenance": {
            "model_used": bool(normalized_intent.get("reasoning_version")),
            "deterministic_postprocessing_applied": True,
            "conflicts_resolved": _extract_conflicts(normalized_intent),
        },
    }


def _infer_chart_hint(
    *,
    primary_intent: str,
    time_grouping_detected: bool,
    relationship: bool,
    distribution: bool,
    ranking_enabled: bool,
    limit: int | None,
    num_metrics: int,
    has_filters: bool,
) -> str:
    if distribution:
        return "histogram"
    if relationship:
        return "scatter"
    if time_grouping_detected:
        if ranking_enabled and limit == 1:
            return "card"
        if num_metrics >= 2:
            return "combo_line_bar"
        return "line"
    if ranking_enabled:
        if limit == 1:
            return "card"
        return "bar"
    if has_filters and not time_grouping_detected and not ranking_enabled:
        return "table"
    if primary_intent == "aggregation":
        return "bar"
    return "table"


def _compute_confidence(normalized_intent: dict[str, Any]) -> float:
    base = 0.85
    if normalized_intent.get("time_grouping_detected"):
        base += 0.05
    if normalized_intent.get("filters"):
        base += 0.03
    if normalized_intent.get("metric_lock_enabled"):
        base += 0.02
    return min(1.0, round(base, 2))


def _extract_conflicts(normalized_intent: dict[str, Any]) -> list[str]:
    conflicts: list[str] = []
    reasoning = normalized_intent.get("semantic_reasoning") if isinstance(normalized_intent.get("semantic_reasoning"), dict) else {}
    if reasoning.get("suppress_relationship_scatter"):
        conflicts.append("temporal_suppressed_relationship_scatter")
    if normalized_intent.get("composite_temporal_ranking"):
        conflicts.append("composite_temporal_ranking_active")
    return conflicts
