from __future__ import annotations

import logging
from typing import Any

from bi_platform_shared.contracts.chart import select_chart_type

logger = logging.getLogger(__name__)


def recommend_chart(intent: dict, data: dict | None = None) -> dict:
    """
    Chart selection is delegated to visualization-service.
    """
    _ = data
    payload: dict[str, Any] = {
        "reason_chart_selected": "deferred_to_visualization_service_chart_type_selector",
    }
    chart_type, reason = select_chart_type(
        intent=intent if isinstance(intent, dict) else {},
        columns=(data or {}).get("columns", []) if isinstance(data, dict) else [],
        rows=(data or {}).get("rows", []) if isinstance(data, dict) else [],
        preferred_chart_type=(intent or {}).get("chart_type") if isinstance(intent, dict) else None,
        question=(intent or {}).get("raw_question") if isinstance(intent, dict) else None,
    )
    payload["type"] = chart_type.value
    payload["chart_type"] = chart_type.value
    payload["chart_selection_reason"] = reason

    if str(intent.get("intent_type", "")).strip().lower() == "predictive":
        payload.setdefault("mode", "actual_plus_predicted")
        payload.setdefault("series_type_field", "series_type")
        payload.setdefault("series_label_field", "series_label")
        payload.setdefault("preferred_color_role_field", "preferred_color_role")

    logger.info(
        "Chart recommendation deferred to visualization-service chart_type_selector",
    )
    return payload
