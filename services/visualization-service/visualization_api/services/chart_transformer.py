"""Deterministic chart transformation layer for visualization-service."""

from __future__ import annotations

from typing import Any, Mapping

from bi_platform_shared.contracts.chart import ChartTypeEnum, normalize_chart_type
from bi_platform_shared.contracts.viz import (
    VisualizationSpec,
    VisualizationSpecError,
    build_visualization_spec,
    transform_visualization_spec,
)


class ChartTransformationError(ValueError):
    """User-safe chart transformation failure."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "chart_type_incompatible",
        requested_chart_type: str = "",
        compatible_chart_types: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.requested_chart_type = requested_chart_type
        self.compatible_chart_types = compatible_chart_types or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "requested_chart_type": self.requested_chart_type,
            "compatible_chart_types": self.compatible_chart_types,
        }


def _raise_transform_error(exc: VisualizationSpecError, target_chart_type: ChartTypeEnum) -> None:
    raise ChartTransformationError(
        str(exc),
        error_code=exc.error_code,
        requested_chart_type=exc.requested_chart_type or target_chart_type.value,
        compatible_chart_types=exc.compatible_chart_types,
    ) from exc


def transform_chart(
    current_spec: VisualizationSpec | Mapping[str, Any],
    target_chart_type: ChartTypeEnum | str,
    query_metadata: Mapping[str, Any] | None = None,
    user_context: dict[str, Any] | None = None,
) -> VisualizationSpec:
    """Return a complete new VisualizationSpec for a compatible target chart."""

    target = target_chart_type if isinstance(target_chart_type, ChartTypeEnum) else normalize_chart_type(str(target_chart_type or ""))
    metadata = query_metadata if isinstance(query_metadata, Mapping) else {}
    result_shape = metadata.get("result_shape") if isinstance(metadata.get("result_shape"), Mapping) else None
    columns = metadata.get("columns") if isinstance(metadata.get("columns"), list) else None
    _ = user_context

    try:
        return transform_visualization_spec(
            current_spec,
            target,
            result_shape=result_shape,
            columns=columns,
        )
    except VisualizationSpecError as exc:
        _raise_transform_error(exc, target)


def build_initial_visualization_spec(
    *,
    chart_type: ChartTypeEnum | str,
    query_metadata: Mapping[str, Any],
    recommendation_metadata: Mapping[str, Any] | None = None,
) -> VisualizationSpec:
    """Build the first spec after recommendation and query execution."""

    result_shape = query_metadata.get("result_shape") if isinstance(query_metadata.get("result_shape"), Mapping) else {}
    columns = query_metadata.get("columns") if isinstance(query_metadata.get("columns"), list) else None
    try:
        return build_visualization_spec(
            chart_type=chart_type,
            result_shape=result_shape,
            columns=columns,
            recommendation_metadata=recommendation_metadata,
        )
    except VisualizationSpecError as exc:
        target = chart_type if isinstance(chart_type, ChartTypeEnum) else normalize_chart_type(str(chart_type or ""))
        _raise_transform_error(exc, target)


__all__ = [
    "ChartTransformationError",
    "build_initial_visualization_spec",
    "transform_chart",
]
