import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

SERVICE_PATH = Path(__file__).resolve().parents[1] / "services" / "metabase_service.py"
spec = importlib.util.spec_from_file_location("metabase_service_under_test", SERVICE_PATH)
metabase_service = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(metabase_service)
MetabaseService = metabase_service.MetabaseService


class _FakeResponse:
    status_code = 201
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _build_service_with_capture():
    service = MetabaseService()
    service._request = MagicMock(return_value=_FakeResponse({"id": 123}))
    return service


def test_scatter_payload_uses_scatter_display_and_graph_axes():
    service = _build_service_with_capture()

    result = service.create_question(
        name="scatter q",
        sql="SELECT x, y FROM t",
        visualization_settings={"display": "scatter", "numeric_columns": ["x", "y"]},
    )

    assert result == 123
    payload = service._request.call_args.kwargs["json"]
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
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "line"
    assert payload["visualization_settings"]["display"] == "line"


def test_bar_payload_stays_bar():
    service = _build_service_with_capture()

    result = service.create_question(
        name="bar q",
        sql="SELECT c, v FROM t",
        visualization_settings={"display": "bar"},
    )

    assert result == 123
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "bar"


def test_card_payload_stays_scalar():
    service = _build_service_with_capture()

    result = service.create_question(
        name="card q",
        sql="SELECT COUNT(*) AS v FROM t",
        visualization_settings={"display": "scalar"},
    )

    assert result == 123
    payload = service._request.call_args.kwargs["json"]
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
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "line"
    assert payload["visualization_settings"]["graph.dimensions"] == ["period"]
    assert payload["visualization_settings"]["graph.metrics"] == ["total_sales"]


def test_histogram_payload_uses_numeric_metric():
    service = _build_service_with_capture()

    result = service.create_question(
        name="hist q",
        sql="SELECT orders FROM t",
        visualization_settings={"display": "histogram", "numeric_columns": ["orders"]},
    )

    assert result == 123
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "histogram"
    assert payload["visualization_settings"]["graph.metrics"] == ["orders"]


def test_histogram_payload_uses_customers_metric():
    service = _build_service_with_capture()

    result = service.create_question(
        name="hist customers",
        sql="SELECT customers FROM t",
        visualization_settings={"display": "histogram", "numeric_columns": ["customers"]},
    )

    assert result == 123
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "histogram"
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
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "histogram"
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
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "histogram"
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
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "histogram"
    assert payload["visualization_settings"]["graph.metrics"] == ["category"]


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
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "histogram"
    assert payload["visualization_settings"]["graph.metrics"] == ["orders"]


def test_histogram_without_metric_context_falls_back_safely():
    service = _build_service_with_capture()

    result = service.create_question(
        name="hist invalid",
        sql="SELECT a FROM t",
        visualization_settings={"display": "histogram"},
    )

    assert result == 123
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "table"
    assert payload["visualization_settings"]["display"] == "table"
    assert payload["visualization_settings"]["fallback_applied"] is True
    assert payload["visualization_settings"]["fallback_reason"] == "invalid_histogram_shape"


def test_invalid_scatter_records_truthful_table_fallback_when_shape_unknown():
    service = _build_service_with_capture()

    result = service.create_question(
        name="scatter invalid",
        sql="SELECT region, sales FROM t",
        visualization_settings={"display": "scatter"},
    )

    assert result == 123
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "table"
    assert payload["visualization_settings"]["fallback_applied"] is True
    assert payload["visualization_settings"]["fallback_reason"] == "invalid_scatter_shape"


def test_missing_display_uses_shape_to_choose_line_not_table_for_time_series():
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
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "line"
    assert payload["visualization_settings"]["fallback_applied"] is True
    assert payload["visualization_settings"]["fallback_reason"] == "missing_requested_display"


def test_missing_display_shape_rules_cover_scatter_bar_and_scalar():
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
    for settings, expected_display, expected_dimensions, expected_metrics in cases:
        service = _build_service_with_capture()
        result = service.create_question(
            name=f"shape {expected_display}",
            sql="SELECT * FROM t",
            visualization_settings=settings,
        )

        assert result == 123
        payload = service._request.call_args.kwargs["json"]
        assert payload["display"] == expected_display
        if expected_dimensions is not None:
            assert payload["visualization_settings"]["graph.dimensions"] == expected_dimensions
        assert payload["visualization_settings"]["graph.metrics"] == expected_metrics
        assert payload["visualization_settings"]["fallback_reason"] == "missing_requested_display"


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
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "scatter"
    assert payload["visualization_settings"]["fallback_applied"] is False
