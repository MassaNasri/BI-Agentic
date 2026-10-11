"""Tests for chart_type_selector deterministic path and Ollama failure handling."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in (current.parent, *current.parents):
        if (candidate / "bi_platform_shared").is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root containing bi_platform_shared")


REPO_ROOT = _resolve_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SERVICE_ROOT = REPO_ROOT / "services" / "visualization-service"
if not SERVICE_ROOT.is_dir():
    SERVICE_ROOT = REPO_ROOT
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from visualization_api.services import chart_type_selector as cts


def _base_trace(question: str) -> dict:
    return {
        "original_question": {"text": question},
        "intent_extraction": {
            "status": "success",
            "intent_type": "analytical",
            "validated_intent": {},
            "extracted_intent": {},
        },
    }


@patch.object(cts, "requests")
def test_ollama_connection_error_uses_deterministic_line(mock_requests):
    mock_requests.post.side_effect = OSError("connection refused")
    settings = {
        "dataset_columns": [
            {"name": "ds", "type": "Date"},
            {"name": "sum_sales", "type": "Float64"},
        ],
        "result_rows": [
            {"ds": "2026-01-01", "sum_sales": 10.0},
            {"ds": "2026-01-02", "sum_sales": 12.0},
        ],
        "intent": {
            "intent": "time_series",
            "operations": ["aggregation", "time_grouping"],
            "time_grouping_detected": True,
            "time_granularity": "day",
        },
    }
    trace = _base_trace("Compare total sales over time")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Compare total sales over time",
        sql="SELECT ds, SUM(sales) AS sum_sales FROM t GROUP BY ds ORDER BY ds",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    assert out["chart_type"] == "line"
    assert "ollama_error" in out["reason"]


@patch.object(cts, "requests")
def test_ollama_error_top_n_days_bar(mock_requests):
    mock_requests.post.side_effect = ConnectionError("no ollama")
    settings = {
        "dataset_columns": [
            {"name": "ds", "type": "Date"},
            {"name": "sum_orders", "type": "UInt64"},
        ],
        "result_rows": [{"ds": f"2026-01-{i:02d}", "sum_orders": i * 10} for i in range(1, 6)],
        "intent": {
            "intent": "ranking",
            "dimensions": ["ds"],
            "operations": ["aggregation", "grouping"],
        },
    }
    trace = _base_trace("Top 10 days with highest orders")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Top 10 days with highest orders",
        sql="SELECT ds, SUM(orders) AS sum_orders FROM t GROUP BY ds ORDER BY sum_orders DESC LIMIT 10",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    assert out["chart_type"] == "bar"


@patch.object(cts, "requests")
def test_ollama_error_share_pie(mock_requests):
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "month", "type": "String"},
            {"name": "share_sales", "type": "Float64"},
        ],
        "result_rows": [{"month": "2026-01", "share_sales": 0.35}, {"month": "2026-02", "share_sales": 0.65}],
        "intent": {
            "intent": "aggregation",
            "operations": ["aggregation", "share"],
            "dimensions": ["month"],
        },
    }
    trace = _base_trace("Show percentage share of sales by month")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Show percentage share of sales by month",
        sql="SELECT month, share_sales FROM t",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    # Share of a metric over a time-like dimension is a series, not a single-slice pie.
    assert out["chart_type"] == "line"


@patch.object(cts, "requests")
def test_ollama_error_relationship_scatter(mock_requests):
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "orders", "type": "UInt32"},
            {"name": "sales", "type": "Float64"},
        ],
        "result_rows": [{"orders": 10, "sales": 100.0}, {"orders": 20, "sales": 250.0}],
        "intent": {
            "intent": "correlation",
            "operations": ["projection", "relationship"],
        },
    }
    trace = _base_trace("Relationship between orders and sales")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Relationship between orders and sales",
        sql="SELECT orders, sales FROM t",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    assert out["chart_type"] == "scatter"


@patch.object(cts, "requests")
def test_ollama_error_two_metrics_over_time_line_multi(mock_requests):
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "ds", "type": "Date"},
            {"name": "customers", "type": "UInt32"},
            {"name": "orders", "type": "UInt32"},
        ],
        "result_rows": [
            {"ds": "2026-01-01", "customers": 5, "orders": 20},
            {"ds": "2026-01-02", "customers": 6, "orders": 22},
        ],
        "intent": {
            "intent": "time_series",
            "operations": ["aggregation", "time_grouping", "multi_metric"],
            "time_grouping_detected": True,
            "time_granularity": "day",
            "metrics": [
                {"column": "customers", "alias": "customers"},
                {"column": "orders", "alias": "orders"},
            ],
        },
    }
    trace = _base_trace("Compare customers and orders over time")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Compare customers and orders over time",
        sql="SELECT ds, customers, orders FROM t ORDER BY ds",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    assert out["chart_type"] == "line_multi"


def test_selector_disabled_skips_ollama_deterministic_only():
    with patch.dict("os.environ", {"VISUALIZATION_CHART_SELECTOR_ENABLED": "false"}):
        settings = {
            "dataset_columns": [
                {"name": "ds", "type": "Date"},
                {"name": "total", "type": "Float64"},
            ],
            "result_rows": [{"ds": "2026-01-01", "total": 1.0}, {"ds": "2026-01-02", "total": 2.0}],
            "intent": {
                "intent": "time_series",
                "time_grouping_detected": True,
                "time_granularity": "day",
                "operations": ["time_grouping"],
            },
        }
        trace = _base_trace("sales trend")
        trace["intent_extraction"]["validated_intent"] = settings["intent"]
        out = cts.select_chart_type_with_ollama(
            name="sales trend",
            sql="SELECT ds, SUM(x) AS total FROM t GROUP BY ds",
            requested_chart_type="",
            visualization_settings=settings,
            ai_trace=trace,
        )
        assert out["source"] == "deterministic"
        assert out["chart_type"] == "line"
        assert "chart_selector_disabled" in out["reason"]


@patch.object(cts, "requests")
def test_explicit_deterministic_mode_skips_ollama(mock_requests):
    out = cts.select_chart_type_with_ollama(
        name="Revenue over time",
        sql="SELECT month, SUM(revenue) AS revenue FROM sales GROUP BY month",
        requested_chart_type="line",
        visualization_settings={
            "selection_mode": "deterministic",
            "dataset_columns": [
                {"name": "month", "type": "Date"},
                {"name": "revenue", "type": "Float64"},
            ],
            "result_rows": [
                {"month": "2026-01-01", "revenue": 10.0},
                {"month": "2026-02-01", "revenue": 12.0},
            ],
        },
        ai_trace={},
    )

    assert out["source"] == "deterministic"
    assert out["chart_type"] == "line"
    assert "deterministic_selection_requested" in out["reason"]
    mock_requests.post.assert_not_called()


@patch.object(cts, "requests")
def test_query_execution_normalized_intent_overrides_weaker_validated_intent(mock_requests):
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "period", "type": "Date"},
            {"name": "sum_sales", "type": "Float64"},
            {"name": "sum_customers", "type": "Float64"},
        ],
        "result_rows": [
            {"period": "2026-01-01", "sum_sales": 10.0, "sum_customers": 3.0},
            {"period": "2026-01-02", "sum_sales": 12.0, "sum_customers": 4.0},
        ],
        "intent": {
            "intent": "comparison",
            "operations": ["projection", "comparison", "relationship"],
        },
    }
    trace = _base_trace("Compare sales and customers over time")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]
    trace["query_execution"] = {
        "normalized_intent": {
            "intent": "time_series",
            "operations": ["projection", "aggregation", "grouping", "time_grouping", "multi_metric"],
            "time_grouping_detected": True,
            "time_granularity": "day",
            "metrics": [{"column": "sum_sales"}, {"column": "sum_customers"}],
        }
    }

    out = cts.select_chart_type_with_ollama(
        name="Compare sales and customers over time",
        sql="SELECT period, SUM(sales) AS sum_sales, SUM(customers) AS sum_customers FROM t GROUP BY period ORDER BY period ASC",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    assert out["chart_type"] == "line_multi"


@patch.object(cts, "requests")
def test_single_winner_temporal_ranking_prefers_card(mock_requests):
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "period", "type": "Date"},
            {"name": "sum_total_sales", "type": "Float64"},
        ],
        "result_rows": [
            {"period": "2026-04-01", "sum_total_sales": 3200.0},
        ],
        "intent": {
            "intent": "time_series",
            "operations": ["aggregation", "grouping", "ranking", "limiting", "time_grouping"],
            "time_grouping_detected": True,
            "time_granularity": "month",
            "ranking": {"direction": "DESC"},
            "limit": 1,
            "dimensions": ["period"],
        },
    }
    trace = _base_trace("What month generated the highest total sales?")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="What month generated the highest total sales?",
        sql="SELECT period, SUM(total_sales) AS sum_total_sales FROM t GROUP BY period ORDER BY sum_total_sales DESC LIMIT 1",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    assert out["chart_type"] == "card"


@patch.object(cts, "requests")
def test_empty_result_forces_table_even_with_histogram_hint(mock_requests):
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "orders", "type": "UInt32"},
        ],
        "result_rows": [],
        "intent": {
            "intent": "distribution",
            "operations": ["projection", "filtering"],
            "metrics": [{"column": "orders"}],
        },
    }
    trace = _base_trace("Orders below 20")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Orders below 20",
        sql="SELECT orders FROM t WHERE orders < 20",
        requested_chart_type="histogram",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    assert out["chart_type"] == "table"
    assert "result_shape_empty_rows_table" in out["reason"]


@patch.object(cts, "requests")
def test_orders_by_day_result_shape_prefers_line(mock_requests):
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "period", "type": "Date"},
            {"name": "sum_orders", "type": "UInt64"},
        ],
        "result_rows": [
            {"period": "2026-01-01", "sum_orders": 20},
            {"period": "2026-01-02", "sum_orders": 22},
        ],
        "intent": {
            "intent": "time_series",
            "operations": ["aggregation", "grouping", "time_grouping", "sorting"],
            "time_grouping_detected": True,
            "time_granularity": "day",
        },
    }
    trace = _base_trace("Orders by day")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Orders by day",
        sql="SELECT toDate(ds) AS period, SUM(orders) AS sum_orders FROM t GROUP BY period ORDER BY period ASC",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    assert out["chart_type"] == "line"


@patch.object(cts, "requests")
def test_distribution_of_total_sales_prefers_histogram(mock_requests):
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "bin_start", "type": "Float64"},
            {"name": "frequency", "type": "UInt64"},
        ],
        "result_rows": [
            {"bin_start": 0.0, "frequency": 3},
            {"bin_start": 10.0, "frequency": 7},
            {"bin_start": 20.0, "frequency": 12},
            {"bin_start": 30.0, "frequency": 11},
            {"bin_start": 40.0, "frequency": 8},
            {"bin_start": 50.0, "frequency": 5},
            {"bin_start": 60.0, "frequency": 3},
            {"bin_start": 70.0, "frequency": 2},
            {"bin_start": 80.0, "frequency": 1},
            {"bin_start": 90.0, "frequency": 1},
        ],
        "intent": {
            "intent": "distribution",
            "analysis_mode": "distribution",
            "operations": ["distribution", "grouping", "aggregation", "sorting"],
        },
    }
    trace = _base_trace("Distribution of total sales")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Distribution of total sales",
        sql="SELECT bin_start, COUNT() AS frequency FROM t GROUP BY bin_start ORDER BY bin_start ASC",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    assert out["chart_type"] == "histogram"


@patch.object(cts, "requests")
def test_sales_by_category_prefers_bar(mock_requests):
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "category", "type": "String"},
            {"name": "sum_total_sales", "type": "Float64"},
        ],
        "result_rows": [
            {"category": "A", "sum_total_sales": 1000.0},
            {"category": "B", "sum_total_sales": 1200.0},
            {"category": "C", "sum_total_sales": 900.0},
        ],
        "intent": {
            "intent": "aggregation",
            "operations": ["aggregation", "grouping", "sorting"],
            "dimensions": ["category"],
        },
    }
    trace = _base_trace("Sales by category")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Sales by category",
        sql="SELECT category, SUM(total_sales) AS sum_total_sales FROM t GROUP BY category ORDER BY sum_total_sales DESC",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    assert out["chart_type"] == "bar"


@patch.object(cts, "requests")
def test_top_five_products_by_sales_prefers_bar(mock_requests):
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "product", "type": "String"},
            {"name": "sum_total_sales", "type": "Float64"},
        ],
        "result_rows": [
            {"product": "P1", "sum_total_sales": 2100.0},
            {"product": "P2", "sum_total_sales": 2000.0},
            {"product": "P3", "sum_total_sales": 1900.0},
            {"product": "P4", "sum_total_sales": 1850.0},
            {"product": "P5", "sum_total_sales": 1800.0},
        ],
        "intent": {
            "intent": "ranking",
            "operations": ["aggregation", "grouping", "ranking", "sorting", "limiting"],
            "ranking": {"direction": "DESC"},
            "limit": 5,
            "dimensions": ["product"],
        },
    }
    trace = _base_trace("Top 5 products by sales")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Top 5 products by sales",
        sql="SELECT product, SUM(total_sales) AS sum_total_sales FROM t GROUP BY product ORDER BY sum_total_sales DESC LIMIT 5",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    assert out["chart_type"] == "bar"


@patch.object(cts, "requests")
def test_ollama_bar_for_time_multi_metric_is_overridden_by_shape_guard(mock_requests):
    mock_response = type(
        "_Resp",
        (),
        {
            "raise_for_status": lambda self: None,
            "json": lambda self: {"response": '{"chart_type":"bar","reason":"model_preference"}'},
        },
    )()
    mock_requests.post.return_value = mock_response
    settings = {
        "dataset_columns": [
            {"name": "period", "type": "Date"},
            {"name": "sum_customers", "type": "UInt64"},
            {"name": "sum_total_sales", "type": "Float64"},
        ],
        "result_rows": [
            {"period": "2026-01-01", "sum_customers": 50, "sum_total_sales": 2000.0},
            {"period": "2026-01-02", "sum_customers": 55, "sum_total_sales": 2200.0},
            {"period": "2026-01-03", "sum_customers": 60, "sum_total_sales": 2500.0},
        ],
        "intent": {
            "intent": "time_series",
            "operations": ["projection", "aggregation", "grouping", "time_grouping", "multi_metric"],
            "time_grouping_detected": True,
            "time_granularity": "day",
        },
    }
    trace = _base_trace("Compare customers and sales over time")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Compare customers and sales over time",
        sql="SELECT period, SUM(customers) AS sum_customers, SUM(total_sales) AS sum_total_sales FROM t GROUP BY period ORDER BY period ASC",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "ollama"
    assert out["chart_type"] in {"line", "line_multi", "combo_line_bar"}
    assert out["chart_type"] != "bar"


@patch.object(cts, "requests")
def test_time_multi_metric_large_scale_gap_prefers_combo(mock_requests):
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "period", "type": "Date"},
            {"name": "sum_customers", "type": "UInt64"},
            {"name": "sum_total_sales", "type": "Float64"},
        ],
        "result_rows": [
            {"period": "2026-01-01", "sum_customers": 40, "sum_total_sales": 10000.0},
            {"period": "2026-01-02", "sum_customers": 42, "sum_total_sales": 65000.0},
            {"period": "2026-01-03", "sum_customers": 43, "sum_total_sales": 130000.0},
            {"period": "2026-01-04", "sum_customers": 41, "sum_total_sales": 180000.0},
        ],
        "intent": {
            "intent": "time_series",
            "operations": ["aggregation", "grouping", "time_grouping", "multi_metric"],
            "time_grouping_detected": True,
            "time_granularity": "day",
        },
    }
    trace = _base_trace("Compare customers and sales over time")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Compare customers and sales over time",
        sql="SELECT period, SUM(customers) AS sum_customers, SUM(total_sales) AS sum_total_sales FROM t GROUP BY period ORDER BY period ASC",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["source"] == "deterministic"
    assert out["chart_type"] == "combo_line_bar"


@patch.object(cts, "requests")
def test_temporal_phrase_suppresses_scatter_even_without_datetime_column(mock_requests):
    """
    When the question says 'over time' but the result has no datetime column
    (upstream bug lost the date axis), scatter MUST NOT be selected.
    """
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "total_sales", "type": "Float64"},
            {"name": "customers", "type": "UInt32"},
        ],
        "result_rows": [
            {"total_sales": 100.0, "customers": 10},
            {"total_sales": 200.0, "customers": 20},
        ],
        "intent": {
            "intent": "comparison",
            "operations": ["projection", "comparison", "multi_metric"],
        },
    }
    trace = _base_trace("Compare sales and customers over time")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Compare sales and customers over time",
        sql="SELECT total_sales, customers FROM t",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["chart_type"] != "scatter", (
        "scatter must not be selected when question contains 'over time'"
    )


@patch.object(cts, "requests")
def test_metric_order_invariance_chart_selection(mock_requests):
    """
    Both metric orderings with 'over time' must produce the same
    chart family (line or combo) — never scatter.
    """
    mock_requests.post.side_effect = RuntimeError("boom")

    def _make_settings(q):
        return {
            "dataset_columns": [
                {"name": "period", "type": "Date"},
                {"name": "sum_total_sales", "type": "Float64"},
                {"name": "sum_customers", "type": "Float64"},
            ],
            "result_rows": [
                {"period": "2026-01-01", "sum_total_sales": 100.0, "sum_customers": 10.0},
                {"period": "2026-01-02", "sum_total_sales": 120.0, "sum_customers": 12.0},
            ],
            "intent": {
                "intent": "time_series",
                "operations": ["projection", "aggregation", "grouping", "sorting",
                               "time_grouping", "comparison", "multi_metric"],
                "time_grouping_detected": True,
                "time_granularity": "day",
            },
        }

    q1 = "Compare sales and customers over time"
    q2 = "Compare customers and sales over time"

    for q in (q1, q2):
        settings = _make_settings(q)
        trace = _base_trace(q)
        trace["intent_extraction"]["validated_intent"] = settings["intent"]
        out = cts.select_chart_type_with_ollama(
            name=q,
            sql="SELECT period, SUM(total_sales) AS sum_total_sales, SUM(customers) AS sum_customers FROM t GROUP BY period ORDER BY period ASC",
            requested_chart_type="",
            visualization_settings=settings,
            ai_trace=trace,
        )
        assert out["chart_type"] in {"line", "line_multi", "combo_line_bar"}, (
            f"'{q}' produced {out['chart_type']} instead of line/combo"
        )
        assert out["chart_type"] != "scatter", f"'{q}' must not be scatter"


@patch.object(cts, "requests")
def test_relationship_without_temporal_still_scatter_chart(mock_requests):
    """Scatter is correct when no temporal phrase and explicit relationship."""
    mock_requests.post.side_effect = RuntimeError("boom")
    settings = {
        "dataset_columns": [
            {"name": "orders", "type": "UInt32"},
            {"name": "sales", "type": "Float64"},
        ],
        "result_rows": [
            {"orders": 10, "sales": 100.0},
            {"orders": 20, "sales": 250.0},
        ],
        "intent": {
            "intent": "correlation",
            "operations": ["projection", "relationship"],
        },
    }
    trace = _base_trace("Relationship between orders and sales")
    trace["intent_extraction"]["validated_intent"] = settings["intent"]

    out = cts.select_chart_type_with_ollama(
        name="Relationship between orders and sales",
        sql="SELECT orders, sales FROM t",
        requested_chart_type="",
        visualization_settings=settings,
        ai_trace=trace,
    )
    assert out["chart_type"] == "scatter"
