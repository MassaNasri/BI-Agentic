import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Expose repo root so tests can import shared package.
def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "bi_platform_shared").exists():
            return candidate
    parents = list(current.parents)
    return parents[min(4, len(parents) - 1)]


REPO_ROOT = _resolve_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SERVICE_PATH = Path(__file__).resolve().parents[1] / "services" / "metabase_service.py"
spec = importlib.util.spec_from_file_location("metabase_service_under_test", SERVICE_PATH)
metabase_service = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(metabase_service)
MetabaseService = metabase_service.MetabaseService

from bi_platform_shared.sql import sanitize_sql_for_metabase  # noqa: E402


class _FakeResponse:
    text = ""

    def __init__(self, payload, *, status_code: int = 201):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _build_service_with_capture():
    service = MetabaseService()
    service._request = MagicMock(return_value=_FakeResponse({"id": 123}))
    return service


def _first_request_payload(service: MetabaseService) -> dict:
    for call in service._request.call_args_list:
        kwargs = getattr(call, "kwargs", {}) or {}
        if isinstance(kwargs.get("json"), dict):
            return kwargs["json"]
    return {}


def test_scatter_payload_uses_scatter_display_and_graph_axes():
    service = _build_service_with_capture()

    result = service.create_question(
        name="scatter q",
        sql="SELECT x, y FROM t",
        visualization_settings={"display": "scatter", "numeric_columns": ["x", "y"]},
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "scatter"
    assert payload["visualization_settings"]["graph.dimensions"] == ["x"]
    assert payload["visualization_settings"]["graph.metrics"] == ["y"]


def test_line_payload_stays_line():
    service = _build_service_with_capture()

    result = service.create_question(
        name="line q",
        sql="SELECT d, v FROM t",
        visualization_settings={"display": "line"},
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "table"
    assert payload["visualization_settings"]["fallback_reason"] == "line_axes_unresolved"


def test_bar_payload_stays_bar():
    service = _build_service_with_capture()

    result = service.create_question(
        name="bar q",
        sql="SELECT c, v FROM t",
        visualization_settings={"display": "bar"},
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "table"
    assert payload["visualization_settings"]["fallback_reason"] == "bar_metric_unresolved"


def test_card_payload_stays_scalar():
    service = _build_service_with_capture()

    result = service.create_question(
        name="card q",
        sql="SELECT COUNT(*) AS v FROM t",
        visualization_settings={"display": "scalar"},
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "scalar"


def test_line_payload_includes_time_dimension_and_metric():
    service = _build_service_with_capture()

    result = service.create_question(
        name="line q with metadata",
        sql="SELECT period, total_sales FROM t",
        visualization_settings={
            "display": "line",
            "time_columns": ["period"],
            "numeric_columns": ["total_sales"],
        },
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "line"
    assert payload["visualization_settings"]["graph.dimensions"] == ["period"]
    assert payload["visualization_settings"]["graph.metrics"] == ["total_sales"]


def test_forecast_line_payload_adds_series_breakout_and_semantic_series_settings():
    service = _build_service_with_capture()

    result = service.create_question(
        name="forecast line",
        sql="SELECT ds, value, series_type FROM forecast_dataset",
        visualization_settings={
            "display": "line",
            "time_columns": ["ds"],
            "numeric_columns": ["value"],
            "series_type_field": "series_type",
            "series_label_field": "series_label",
            "preferred_color_role_field": "preferred_color_role",
            "forecast_available": True,
            "intent": {"columns": ["orders"]},
            "chart_series_config": [
                {
                    "series_type": "actual",
                    "series_label": "Actual",
                    "preferred_color_role": "actual",
                    "preferred_color": "#2563eb",
                    "stroke_dasharray": "",
                },
                {
                    "series_type": "forecast",
                    "series_label": "Forecast",
                    "preferred_color_role": "forecast",
                    "preferred_color": "#f97316",
                    "stroke_dasharray": "6 4",
                },
            ],
            "result_rows": [
                {
                    "ds": "2026-01-01",
                    "value": 120.0,
                    "series_type": "actual",
                    "series_label": "Actual",
                    "preferred_color_role": "actual",
                },
                {
                    "ds": "2026-01-02",
                    "value": 133.0,
                    "series_type": "forecast",
                    "series_label": "Forecast",
                    "preferred_color_role": "forecast",
                },
            ],
        },
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "line"
    viz = payload["visualization_settings"]
    assert viz["graph.dimensions"] == ["ds", "series_type"]
    assert viz["graph.metrics"] == ["value"]
    assert viz["graph.series_order_dimension"] == "series_type"
    assert viz["forecast_series_visualization_applied"] is True
    assert viz["series_settings"]["actual"]["title"] == "Actual Orders"
    assert viz["series_settings"]["actual"]["color"] == "#2563eb"
    assert viz["series_settings"]["forecast"]["title"] == "Forecasted Orders"
    assert viz["series_settings"]["forecast"]["color"] == "#f97316"
    assert viz["series_settings"]["forecast"]["stroke_dasharray"] == "6 4"


def test_analytical_line_payload_keeps_backward_compatible_shape_without_forecast_settings():
    service = _build_service_with_capture()

    result = service.create_question(
        name="standard analytical line",
        sql="SELECT period, total_sales FROM t",
        visualization_settings={
            "display": "line",
            "time_columns": ["period"],
            "numeric_columns": ["total_sales"],
            "result_rows": [
                {"period": "2026-01-01", "total_sales": 1200.0},
                {"period": "2026-01-02", "total_sales": 1300.0},
            ],
        },
    )

    assert result == 123
    payload = _first_request_payload(service)
    viz = payload["visualization_settings"]
    assert payload["display"] == "line"
    assert viz["graph.dimensions"] == ["period"]
    assert viz["graph.metrics"] == ["total_sales"]
    assert viz.get("forecast_series_visualization_applied") is None
    assert viz.get("series_settings") is None


def test_combo_payload_includes_time_dimension_and_multiple_metrics():
    service = _build_service_with_capture()

    result = service.create_question(
        name="combo q with metadata",
        sql="SELECT period, customers, total_sales FROM t",
        visualization_settings={
            "display": "combo_line_bar",
            "time_columns": ["period"],
            "numeric_columns": ["customers", "total_sales"],
        },
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "combo"
    assert payload["visualization_settings"]["graph.dimensions"] == ["period"]
    assert payload["visualization_settings"]["graph.metrics"] == ["customers", "total_sales"]


def test_combo_without_axes_falls_back_to_table():
    service = _build_service_with_capture()

    result = service.create_question(
        name="combo unresolved",
        sql="SELECT category, sales FROM t",
        visualization_settings={"display": "combo_line_bar"},
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "table"
    assert payload["visualization_settings"]["fallback_reason"] == "combo_axes_unresolved"


def test_histogram_payload_uses_numeric_metric():
    service = _build_service_with_capture()

    result = service.create_question(
        name="hist q",
        sql="SELECT orders FROM t",
        visualization_settings={"display": "histogram", "numeric_columns": ["orders"]},
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "bar"
    assert payload["visualization_settings"]["graph.metrics"] == ["orders"]


def test_histogram_payload_uses_customers_metric():
    service = _build_service_with_capture()

    result = service.create_question(
        name="hist customers",
        sql="SELECT customers FROM t",
        visualization_settings={"display": "histogram", "numeric_columns": ["customers"]},
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "bar"
    assert payload["visualization_settings"]["graph.metrics"] == ["customers"]


def test_histogram_metric_priority_prefers_numeric_columns_over_axis_hints():
    service = _build_service_with_capture()

    result = service.create_question(
        name="hist numeric priority",
        sql="SELECT total_sales FROM t",
        visualization_settings={
            "display": "histogram",
            "x_column": "total_sales",
            "numeric_columns": ["orders"],
        },
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "bar"
    assert payload["visualization_settings"]["graph.metrics"] == ["orders"]


def test_histogram_metric_uses_dataset_numeric_column_when_numeric_columns_missing():
    service = _build_service_with_capture()

    result = service.create_question(
        name="hist dataset numeric",
        sql="SELECT region, amount FROM t",
        visualization_settings={
            "display": "histogram",
            "columns": [
                {"name": "region", "type": "String"},
                {"name": "amount", "type": "Float64"},
            ],
        },
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "bar"
    assert payload["visualization_settings"]["graph.metrics"] == ["amount"]


def test_histogram_metric_falls_back_to_first_dataset_column():
    service = _build_service_with_capture()

    result = service.create_question(
        name="hist dataset first column fallback",
        sql="SELECT category FROM t",
        visualization_settings={
            "display": "histogram",
            "columns": [
                {"name": "category", "type": "String"},
            ],
        },
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "table"
    assert payload["visualization_settings"]["fallback_reason"] == "histogram_axes_unresolved"


def test_histogram_metric_uses_numeric_column_in_result_rows():
    service = _build_service_with_capture()

    result = service.create_question(
        name="hist result rows numeric",
        sql="SELECT region, orders FROM t",
        visualization_settings={
            "display": "histogram",
            "dataset_columns": [
                {"name": "region", "type": "String"},
                {"name": "orders", "type": ""},
            ],
            "result_rows": [
                {"region": "north", "orders": 12},
                {"region": "south", "orders": 23},
            ],
        },
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "bar"
    assert payload["visualization_settings"]["graph.metrics"] == ["orders"]


def test_histogram_binned_sql_maps_to_bar_with_bin_axes():
    service = _build_service_with_capture()

    result = service.create_question(
        name="hist binned",
        sql="SELECT bin_start, COUNT() AS frequency FROM t GROUP BY bin_start ORDER BY bin_start",
        visualization_settings={
            "display": "histogram",
            "dataset_columns": [
                {"name": "bin_start", "type": "Float64"},
                {"name": "frequency", "type": "UInt64"},
            ],
            "result_rows": [
                {"bin_start": 0.0, "frequency": 4},
                {"bin_start": 10.0, "frequency": 7},
            ],
        },
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "bar"
    assert payload["visualization_settings"]["graph.dimensions"] == ["bin_start"]
    assert payload["visualization_settings"]["graph.metrics"] == ["frequency"]
    assert payload["visualization_settings"]["histogram_mapped_to_bar"] is True


def test_histogram_without_metric_context_falls_back_safely():
    service = _build_service_with_capture()

    result = service.create_question(
        name="hist invalid",
        sql="SELECT a FROM t",
        visualization_settings={"display": "histogram"},
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "table"
    assert payload["visualization_settings"]["display"] == "table"
    assert payload["visualization_settings"]["fallback_applied"] is True
    assert payload["visualization_settings"]["fallback_reason"] == "histogram_axes_unresolved"


def test_empty_result_forces_table_display():
    service = _build_service_with_capture()

    result = service.create_question(
        name="empty result",
        sql="SELECT orders FROM t WHERE orders < 0",
        visualization_settings={
            "display": "line",
            "row_count": 0,
            "dataset_columns": [{"name": "orders", "type": "UInt32"}],
        },
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "table"
    assert payload["visualization_settings"]["fallback_reason"] == "empty_result_force_table"


def test_invalid_scatter_records_truthful_table_fallback_when_shape_unknown():
    service = _build_service_with_capture()

    result = service.create_question(
        name="scatter invalid",
        sql="SELECT region, sales FROM t",
        visualization_settings={"display": "scatter"},
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "table"
    assert payload["visualization_settings"]["fallback_applied"] is True
    assert payload["visualization_settings"]["fallback_reason"] == "scatter_axes_unresolved"


def test_missing_display_defaults_to_table_without_shape_rules():
    service = _build_service_with_capture()

    result = service.create_question(
        name="shape line",
        sql="SELECT period, total_sales FROM t",
        visualization_settings={
            "time_columns": ["period"],
            "numeric_columns": ["total_sales"],
            "row_count": 10,
        },
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "table"
    assert payload["visualization_settings"]["fallback_applied"] is True
    assert payload["visualization_settings"]["fallback_reason"] == "missing_selected_display"


def test_missing_display_does_not_infer_chart_type_from_shape():
    cases = [
        (
            {
                "numeric_columns": ["customers", "sales"],
                "row_count": 10,
            },
            "scatter",
            ["customers"],
            ["sales"],
        ),
        (
            {
                "category_columns": ["region"],
                "numeric_columns": ["sales"],
                "row_count": 2,
            },
            "bar",
            ["region"],
            ["sales"],
        ),
        (
            {
                "numeric_columns": ["sales"],
                "row_count": 1,
            },
            "scalar",
            None,
            ["sales"],
        ),
    ]
    for settings, _expected_display, _expected_dimensions, _expected_metrics in cases:
        service = _build_service_with_capture()
        result = service.create_question(
            name="shape without explicit display",
            sql="SELECT * FROM t",
            visualization_settings=settings,
        )

        assert result == 123
        payload = _first_request_payload(service)
        assert payload["display"] == "table"
        assert payload["visualization_settings"]["fallback_reason"] == "missing_selected_display"


def test_valid_scatter_never_silently_defaults_to_table():
    service = _build_service_with_capture()

    result = service.create_question(
        name="valid scatter",
        sql="SELECT customers, total_sales FROM t",
        visualization_settings={
            "display": "scatter",
            "numeric_columns": ["customers", "total_sales"],
            "row_count": 10,
        },
    )

    assert result == 123
    payload = _first_request_payload(service)
    assert payload["display"] == "scatter"
    assert payload["visualization_settings"]["fallback_applied"] is False


def test_validate_question_execution_treats_runtime_failed_payload_as_error():
    service = MetabaseService()
    failed_payload = {
        "status": "failed",
        "via": {"status": "failed", "error": "Code: 38. DB::Exception: CANNOT_PARSE_DATE"},
    }
    service._request = MagicMock(return_value=_FakeResponse(failed_payload, status_code=200))

    ok = service.validate_question_execution(question_id=99)

    assert ok is False
    assert service.last_error
    assert "question_execution_failed" in service.last_error
    assert "CANNOT_PARSE_DATE" in service.last_error


def test_extract_query_runtime_error_detects_failed_payload_with_http_200():
    payload = {
        "status": "failed",
        "via": {"status": "failed", "error": "embedded query failed"},
    }
    response = _FakeResponse(payload, status_code=200)

    error = MetabaseService._extract_query_runtime_error(response)

    assert error == "embedded query failed"


def test_sanitize_sql_for_metabase_removes_semicolon_and_upgrades_todate_identifier_cast():
    raw_sql = "SELECT toDate(ds) AS period, total_sales FROM etl.sales_3months_realistic_csv ORDER BY period ASC;  "
    sanitized = sanitize_sql_for_metabase(raw_sql)

    assert sanitized.endswith("ASC")
    assert ";" not in sanitized
    assert "toDate(ds)" not in sanitized
    assert "toDate(parseDateTimeBestEffortUSOrNull(toString(ds))) AS period" in sanitized
