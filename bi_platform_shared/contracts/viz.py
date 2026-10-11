"""Shared visualization-state contracts.

These contracts intentionally stay service-agnostic. They describe the complete
state needed to render or switch a chart, while concrete Metabase API calls stay
inside visualization/voice service adapters.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bi_platform_shared.contracts.chart import (
    ChartContract,
    ChartRecommendationResult,
    ChartTypeEnum,
    is_chart_shape_supported,
    normalize_chart_type,
    to_metabase_display,
)
from bi_platform_shared.contracts.query import ColumnMetadata, ColumnRole, GenericColumnType, ResultShape


class VisualizationSpecError(ValueError):
    """Raised when a visualization spec cannot be built safely."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "visualization_spec_invalid",
        requested_chart_type: str | None = None,
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


class MetabaseConfig(BaseModel):
    """Metabase display plus complete visualization settings."""

    model_config = ConfigDict(extra="ignore")

    display: str
    visualization_settings: Dict[str, Any] = Field(default_factory=dict)


class VisualizationSpec(BaseModel):
    """Complete serializable chart state from recommendation through switching."""

    model_config = ConfigDict(use_enum_values=True, extra="ignore")

    schema_version: int = 1
    chart_type: ChartTypeEnum
    chart_contract: ChartContract
    result_shape: ResultShape
    field_assignments: Dict[str, Any] = Field(default_factory=dict)
    metabase_config: MetabaseConfig
    recommendation_metadata: Optional[ChartRecommendationResult] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("chart_type", mode="before")
    @classmethod
    def _coerce_chart_type(cls, value: Any) -> Any:
        if isinstance(value, ChartTypeEnum):
            return value
        if isinstance(value, str):
            return normalize_chart_type(value).value
        return value

    @model_validator(mode="after")
    def _sync_timestamps(self) -> "VisualizationSpec":
        now = datetime.now(timezone.utc)
        if self.created_at is None:
            object.__setattr__(self, "created_at", now)
        if self.updated_at is None:
            object.__setattr__(self, "updated_at", now)
        return self


def _shape_dict(result_shape: ResultShape | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(result_shape, ResultShape):
        return result_shape.model_dump(mode="json")
    if isinstance(result_shape, Mapping):
        return dict(result_shape)
    return {}


def _as_result_shape(result_shape: ResultShape | Mapping[str, Any]) -> ResultShape:
    if isinstance(result_shape, ResultShape):
        return result_shape
    if not isinstance(result_shape, Mapping):
        raise VisualizationSpecError("Result shape metadata is required for chart transformation.")
    return ResultShape.model_validate(result_shape)


def _metadata_columns(columns: List[ColumnMetadata] | List[Mapping[str, Any]] | None) -> list[ColumnMetadata]:
    normalized: list[ColumnMetadata] = []
    for item in columns or []:
        try:
            normalized.append(item if isinstance(item, ColumnMetadata) else ColumnMetadata.model_validate(item))
        except Exception:
            continue
    return normalized


def _append_unique(values: list[str], candidates: list[str]) -> list[str]:
    seen = {value.lower() for value in values}
    for candidate in candidates:
        cleaned = str(candidate or "").strip()
        if cleaned and cleaned.lower() not in seen:
            values.append(cleaned)
            seen.add(cleaned.lower())
    return values


def _columns_by_role(
    result_shape: ResultShape | Mapping[str, Any],
    columns: List[ColumnMetadata] | List[Mapping[str, Any]] | None = None,
) -> dict[str, list[str]]:
    shape = _shape_dict(result_shape)
    metadata = _metadata_columns(columns)

    metrics = [str(v).strip() for v in shape.get("metric_fields", []) or [] if str(v).strip()]
    categories = [str(v).strip() for v in shape.get("category_fields", []) or [] if str(v).strip()]
    series = [str(v).strip() for v in shape.get("series_fields", []) or [] if str(v).strip()]
    times: list[str] = []
    if str(shape.get("time_field") or "").strip():
        times.append(str(shape.get("time_field")).strip())

    for column in metadata:
        if column.role == ColumnRole.METRIC_FIELD or column.generic_type == GenericColumnType.NUMBER:
            _append_unique(metrics, [column.name])
        elif column.role == ColumnRole.TIME_FIELD or column.generic_type in {GenericColumnType.DATE, GenericColumnType.DATETIME}:
            _append_unique(times, [column.name])
        elif column.role in {ColumnRole.CATEGORY_FIELD, ColumnRole.SERIES_FIELD} or column.generic_type == GenericColumnType.STRING:
            _append_unique(categories, [column.name])
        if column.role == ColumnRole.SERIES_FIELD:
            _append_unique(series, [column.name])

    _append_unique(categories, series)
    return {
        "time": times,
        "metric": metrics,
        "category": categories,
        "series": series,
        "all": _append_unique([], times + categories + metrics),
    }


def compatible_chart_types(result_shape: ResultShape | Mapping[str, Any]) -> list[str]:
    shape = _shape_dict(result_shape)
    return [chart.value for chart in ChartTypeEnum if is_chart_shape_supported(chart, shape)]


def build_field_assignments(
    chart_type: ChartTypeEnum | str,
    result_shape: ResultShape | Mapping[str, Any],
    columns: List[ColumnMetadata] | List[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assign result fields to canonical chart slots from semantic roles."""

    canonical = chart_type if isinstance(chart_type, ChartTypeEnum) else normalize_chart_type(str(chart_type or ""))
    roles = _columns_by_role(result_shape, columns)
    time_fields = roles["time"]
    metric_fields = roles["metric"]
    category_fields = roles["category"]
    series_fields = roles["series"]

    def first(values: list[str]) -> Optional[str]:
        return values[0] if values else None

    assignments: dict[str, Any] = {"columns": roles["all"]}
    if canonical == ChartTypeEnum.TABLE:
        return assignments
    if canonical == ChartTypeEnum.CARD:
        assignments["value_column"] = first(metric_fields)
        assignments["label_column"] = first(category_fields)
        return assignments
    if canonical in {ChartTypeEnum.LINE, ChartTypeEnum.AREA, ChartTypeEnum.CUMULATIVE_LINE}:
        assignments["x_axis"] = first(time_fields)
        assignments["y_axis"] = metric_fields[:1]
        return assignments
    if canonical in {ChartTypeEnum.LINE_MULTI, ChartTypeEnum.COMBO_LINE_BAR}:
        assignments["x_axis"] = first(time_fields)
        assignments["y_axis"] = metric_fields[: max(1, min(3, len(metric_fields)))]
        assignments["series_dimension"] = first(series_fields)
        return assignments
    if canonical == ChartTypeEnum.BAR:
        assignments["x_axis"] = first(category_fields) or first(time_fields)
        assignments["y_axis"] = metric_fields[:1]
        return assignments
    if canonical in {ChartTypeEnum.BAR_GROUPED, ChartTypeEnum.BAR_STACKED}:
        assignments["x_axis"] = first(category_fields)
        assignments["y_axis"] = metric_fields[: max(1, min(3, len(metric_fields)))]
        assignments["series_dimension"] = first(series_fields) or (category_fields[1] if len(category_fields) > 1 else None)
        return assignments
    if canonical == ChartTypeEnum.PIE:
        assignments["label_column"] = first(category_fields)
        assignments["value_column"] = first(metric_fields)
        return assignments
    if canonical == ChartTypeEnum.SCATTER:
        assignments["x_axis"] = metric_fields[0] if len(metric_fields) >= 1 else None
        assignments["y_axis"] = metric_fields[1:2]
        return assignments
    if canonical == ChartTypeEnum.HISTOGRAM:
        bin_column = first(category_fields) or first(time_fields) or first(metric_fields)
        assignments["bin_column"] = bin_column
        metric = next((field for field in metric_fields if field != bin_column), None)
        assignments["y_axis"] = [metric] if metric else []
        return assignments
    if canonical == ChartTypeEnum.MAP:
        assignments["label_column"] = first(category_fields)
        assignments["value_column"] = first(metric_fields)
        return assignments
    if canonical == ChartTypeEnum.HEATMAP:
        assignments["x_axis"] = category_fields[0] if len(category_fields) >= 1 else None
        assignments["series_dimension"] = category_fields[1] if len(category_fields) >= 2 else None
        assignments["value_column"] = first(metric_fields)
        return assignments
    return assignments


def build_chart_contract(
    chart_type: ChartTypeEnum | str,
    result_shape: ResultShape | Mapping[str, Any],
    columns: List[ColumnMetadata] | List[Mapping[str, Any]] | None = None,
    *,
    rationale: str = "visualization_spec",
) -> ChartContract:
    canonical = chart_type if isinstance(chart_type, ChartTypeEnum) else normalize_chart_type(str(chart_type or ""))
    shape = _shape_dict(result_shape)
    if canonical != ChartTypeEnum.TABLE and not is_chart_shape_supported(canonical, shape):
        raise VisualizationSpecError(
            f"{canonical.value} is not compatible with this result shape.",
            error_code="chart_type_incompatible",
            requested_chart_type=canonical.value,
            compatible_chart_types=compatible_chart_types(shape),
        )

    assignments = build_field_assignments(canonical, result_shape, columns)
    return ChartContract(
        chart_type=canonical,
        x_axis=assignments.get("x_axis"),
        y_axis=assignments.get("y_axis"),
        series_dimension=assignments.get("series_dimension"),
        label_column=assignments.get("label_column"),
        value_column=assignments.get("value_column"),
        bin_column=assignments.get("bin_column"),
        locked=True,
        chart_source="visualization_spec",
        rationale=rationale,
        metadata={"field_assignments": assignments},
    )


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value or "").strip()]


def to_metabase_config(
    chart_type: ChartTypeEnum | str,
    chart_contract: ChartContract | Mapping[str, Any],
    result_shape: ResultShape | Mapping[str, Any],
) -> MetabaseConfig:
    """Build full Metabase display/settings from canonical chart state."""

    canonical = chart_type if isinstance(chart_type, ChartTypeEnum) else normalize_chart_type(str(chart_type or ""))
    contract = chart_contract if isinstance(chart_contract, ChartContract) else ChartContract.model_validate(chart_contract)
    display = to_metabase_display(canonical)
    shape = _shape_dict(result_shape)
    y_axis = _clean_list(contract.y_axis)

    settings: dict[str, Any] = {
        "chart_type": canonical.value,
        "display": display,
        "result_shape": shape,
        "field_assignments": dict(contract.metadata.get("field_assignments") or {}),
    }

    if canonical == ChartTypeEnum.TABLE:
        return MetabaseConfig(display="table", visualization_settings=settings)
    if canonical == ChartTypeEnum.CARD:
        metric = contract.value_column or (y_axis[0] if y_axis else None)
        if metric:
            settings["scalar.field"] = metric
            settings["graph.metrics"] = [metric]
        return MetabaseConfig(display=display, visualization_settings=settings)
    if canonical in {ChartTypeEnum.LINE, ChartTypeEnum.AREA, ChartTypeEnum.CUMULATIVE_LINE}:
        if contract.x_axis:
            settings["graph.dimensions"] = [contract.x_axis]
        if y_axis:
            settings["graph.metrics"] = y_axis
        settings["graph.x_axis.scale"] = "timeseries"
        if canonical == ChartTypeEnum.CUMULATIVE_LINE:
            settings["graph.y_axis.cumulative"] = True
        return MetabaseConfig(display=display, visualization_settings=settings)
    if canonical in {ChartTypeEnum.LINE_MULTI, ChartTypeEnum.COMBO_LINE_BAR}:
        dimensions = [contract.x_axis] if contract.x_axis else []
        if contract.series_dimension:
            dimensions.append(contract.series_dimension)
            settings["graph.series_order_dimension"] = contract.series_dimension
        if dimensions:
            settings["graph.dimensions"] = dimensions
        if y_axis:
            settings["graph.metrics"] = y_axis
        settings["graph.x_axis.scale"] = "timeseries"
        return MetabaseConfig(display=display, visualization_settings=settings)
    if canonical == ChartTypeEnum.BAR:
        if contract.x_axis:
            settings["graph.dimensions"] = [contract.x_axis]
        if y_axis:
            settings["graph.metrics"] = y_axis[:1]
        settings["stackable.stack_type"] = None
        return MetabaseConfig(display=display, visualization_settings=settings)
    if canonical in {ChartTypeEnum.BAR_GROUPED, ChartTypeEnum.BAR_STACKED}:
        dimensions = [contract.x_axis] if contract.x_axis else []
        if contract.series_dimension:
            dimensions.append(contract.series_dimension)
        if dimensions:
            settings["graph.dimensions"] = dimensions
        if y_axis:
            settings["graph.metrics"] = y_axis
        settings["stackable.stack_type"] = "stacked" if canonical == ChartTypeEnum.BAR_STACKED else None
        return MetabaseConfig(display=display, visualization_settings=settings)
    if canonical == ChartTypeEnum.PIE:
        if contract.label_column:
            settings["pie.dimension"] = contract.label_column
            settings["graph.dimensions"] = [contract.label_column]
        if contract.value_column:
            settings["pie.metric"] = contract.value_column
            settings["graph.metrics"] = [contract.value_column]
        settings["pie.show_legend"] = True
        settings["pie.percent_visibility"] = "inside"
        return MetabaseConfig(display=display, visualization_settings=settings)
    if canonical == ChartTypeEnum.SCATTER:
        if contract.x_axis:
            settings["graph.dimensions"] = [contract.x_axis]
        if y_axis:
            settings["graph.metrics"] = y_axis[:1]
        return MetabaseConfig(display=display, visualization_settings=settings)
    if canonical == ChartTypeEnum.HISTOGRAM:
        if contract.bin_column:
            settings["graph.dimensions"] = [contract.bin_column]
            settings["histogram_dimension"] = contract.bin_column
        metric = y_axis[0] if y_axis else "frequency"
        settings["graph.metrics"] = [metric]
        settings["histogram_metric"] = metric
        settings["histogram_mapped_to_bar"] = True
        settings["graph.x_axis.scale"] = "histogram"
        return MetabaseConfig(display=display, visualization_settings=settings)
    if canonical == ChartTypeEnum.MAP:
        if contract.label_column:
            settings["map.dimension"] = contract.label_column
            settings["graph.dimensions"] = [contract.label_column]
        if contract.value_column:
            settings["map.metric"] = contract.value_column
            settings["graph.metrics"] = [contract.value_column]
        return MetabaseConfig(display=display, visualization_settings=settings)
    if canonical == ChartTypeEnum.HEATMAP:
        rows = [contract.series_dimension] if contract.series_dimension else []
        columns = [contract.x_axis] if contract.x_axis else []
        values = [contract.value_column] if contract.value_column else []
        settings["pivot_table.column_split"] = {
            "rows": rows,
            "columns": columns,
            "values": values,
        }
        if columns or rows:
            settings["graph.dimensions"] = columns + rows
        if values:
            settings["graph.metrics"] = values
        settings["heatmap_mapped_to_table"] = True
        return MetabaseConfig(display=display, visualization_settings=settings)
    return MetabaseConfig(display=display, visualization_settings=settings)


def build_visualization_spec(
    *,
    chart_type: ChartTypeEnum | str,
    result_shape: ResultShape | Mapping[str, Any],
    columns: List[ColumnMetadata] | List[Mapping[str, Any]] | None = None,
    recommendation_metadata: ChartRecommendationResult | Mapping[str, Any] | None = None,
    existing_created_at: datetime | None = None,
) -> VisualizationSpec:
    shape_model = _as_result_shape(result_shape)
    contract = build_chart_contract(chart_type, shape_model, columns)
    metabase_config = to_metabase_config(chart_type, contract, shape_model)
    recommendation = None
    if isinstance(recommendation_metadata, ChartRecommendationResult):
        recommendation = recommendation_metadata
    elif isinstance(recommendation_metadata, Mapping):
        try:
            recommendation = ChartRecommendationResult.model_validate(recommendation_metadata)
        except Exception:
            recommendation = None
    return VisualizationSpec(
        chart_type=contract.chart_type,
        chart_contract=contract,
        result_shape=shape_model,
        field_assignments=dict(contract.metadata.get("field_assignments") or {}),
        metabase_config=metabase_config,
        recommendation_metadata=recommendation,
        created_at=existing_created_at,
        updated_at=datetime.now(timezone.utc),
    )


def transform_visualization_spec(
    current_spec: VisualizationSpec | Mapping[str, Any],
    target_chart_type: ChartTypeEnum | str,
    *,
    result_shape: ResultShape | Mapping[str, Any] | None = None,
    columns: List[ColumnMetadata] | List[Mapping[str, Any]] | None = None,
) -> VisualizationSpec:
    spec = current_spec if isinstance(current_spec, VisualizationSpec) else VisualizationSpec.model_validate(current_spec)
    target = target_chart_type if isinstance(target_chart_type, ChartTypeEnum) else normalize_chart_type(str(target_chart_type or ""))
    shape = result_shape if result_shape is not None else spec.result_shape
    return build_visualization_spec(
        chart_type=target,
        result_shape=shape,
        columns=columns,
        recommendation_metadata=spec.recommendation_metadata,
        existing_created_at=spec.created_at,
    )


__all__ = [
    "MetabaseConfig",
    "VisualizationSpec",
    "VisualizationSpecError",
    "build_chart_contract",
    "build_field_assignments",
    "build_visualization_spec",
    "compatible_chart_types",
    "to_metabase_config",
    "transform_visualization_spec",
]
