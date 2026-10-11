from __future__ import annotations

import sys
from pathlib import Path

import pytest

def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in (current.parent, *current.parents):
        if (candidate / "bi_platform_shared").is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root containing bi_platform_shared")


REPO_ROOT = _resolve_repo_root()
SERVICE_ROOT = REPO_ROOT / "services" / "visualization-service"
if not SERVICE_ROOT.is_dir():
    SERVICE_ROOT = REPO_ROOT
for path in (REPO_ROOT, SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from bi_platform_shared.contracts.viz import (  # noqa: E402
    VisualizationSpec,
    VisualizationSpecError,
    build_visualization_spec,
    transform_visualization_spec,
)
from visualization_api.services.chart_transformer import ChartTransformationError, transform_chart  # noqa: E402


def test_time_series_spec_builds_complete_metabase_config_and_round_trips():
    spec = build_visualization_spec(
        chart_type="line",
        result_shape={
            "type": "time_series",
            "row_count": 3,
            "time_field": "period",
            "metric_fields": ["sum_sales"],
        },
        columns=[
            {"name": "period", "type": "Date"},
            {"name": "sum_sales", "type": "Float64"},
        ],
    )

    payload = spec.model_dump(mode="json")
    round_tripped = VisualizationSpec.model_validate(payload)

    assert payload["chart_type"] == "line"
    assert payload["field_assignments"]["x_axis"] == "period"
    assert payload["field_assignments"]["y_axis"] == ["sum_sales"]
    assert payload["metabase_config"]["display"] == "line"
    assert payload["metabase_config"]["visualization_settings"]["graph.dimensions"] == ["period"]
    assert payload["metabase_config"]["visualization_settings"]["graph.metrics"] == ["sum_sales"]
    assert round_tripped.chart_type == "line"


def test_transform_preserves_created_at_and_rebuilds_settings_for_target_chart():
    current = build_visualization_spec(
        chart_type="line",
        result_shape={
            "type": "time_series",
            "row_count": 3,
            "time_field": "period",
            "metric_fields": ["sum_sales"],
        },
        columns=[
            {"name": "period", "type": "Date"},
            {"name": "sum_sales", "type": "Float64"},
        ],
    )

    transformed = transform_visualization_spec(
        current,
        "bar",
        columns=[
            {"name": "period", "type": "Date"},
            {"name": "sum_sales", "type": "Float64"},
        ],
    )

    assert transformed.chart_type == "bar"
    assert transformed.created_at == current.created_at
    assert transformed.metabase_config.display == "bar"
    assert transformed.metabase_config.visualization_settings["graph.dimensions"] == ["period"]
    assert transformed.metabase_config.visualization_settings["graph.metrics"] == ["sum_sales"]
    assert transformed.metabase_config.visualization_settings["stackable.stack_type"] is None


def test_incompatible_transform_returns_compatible_chart_types():
    with pytest.raises(VisualizationSpecError) as exc_info:
        build_visualization_spec(
            chart_type="scatter",
            result_shape={
                "type": "single_value",
                "row_count": 1,
                "metric_fields": ["total_sales"],
            },
            columns=[{"name": "total_sales", "type": "Float64"}],
        )

    payload = exc_info.value.to_dict()
    assert payload["error_code"] == "chart_type_incompatible"
    assert payload["requested_chart_type"] == "scatter"
    assert "card" in payload["compatible_chart_types"]
    assert "scatter" not in payload["compatible_chart_types"]


def test_service_transformer_wraps_visualization_spec_errors_for_api_payloads():
    current = build_visualization_spec(
        chart_type="card",
        result_shape={
            "type": "single_value",
            "row_count": 1,
            "metric_fields": ["total_sales"],
        },
        columns=[{"name": "total_sales", "type": "Float64"}],
    ).model_dump(mode="json")

    with pytest.raises(ChartTransformationError) as exc_info:
        transform_chart(current, "scatter")

    payload = exc_info.value.to_dict()
    assert payload["error_code"] == "chart_type_incompatible"
    assert payload["requested_chart_type"] == "scatter"
    assert "card" in payload["compatible_chart_types"]


def test_histogram_spec_maps_to_metabase_bar_with_explicit_histogram_settings():
    spec = build_visualization_spec(
        chart_type="histogram",
        result_shape={
            "type": "multi_metric",
            "row_count": 20,
            "metric_fields": ["bin_start", "frequency"],
        },
        columns=[
            {"name": "bin_start", "type": "Float64"},
            {"name": "frequency", "type": "UInt64"},
        ],
    )

    settings = spec.metabase_config.visualization_settings
    assert spec.metabase_config.display == "bar"
    assert settings["histogram_mapped_to_bar"] is True
    assert settings["histogram_dimension"] == "bin_start"
    assert settings["histogram_metric"] == "frequency"
