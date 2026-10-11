"""End-to-end checks for intent priority, filter bridging, and composite temporal ranking."""

from __future__ import annotations

from bi_platform_shared.contracts.chart import ChartTypeEnum, select_chart_type
from bi_platform_shared.semantic.intent_priority import build_intent_priority_payload

from shared.input_classifier import classify_input
from shared.query_planner import normalize_analytical_intent
from shared.sql_compiler import compile_sql


def test_intent_priority_payload_shape():
    p = build_intent_priority_payload("Compare revenue and cost over time")
    assert p["dominant_intent"] == "time_series"
    assert p["intent_priority"]["time_series"] > p["intent_priority"]["relationship"]
    assert p["suppress_relationship_scatter"] is True


def test_intent_priority_none_when_no_temporal_or_relationship_signal():
    p = build_intent_priority_payload("Show table rows")
    assert p["dominant_intent"] == "none"
    assert p["intent_priority"]["time_series"] == 0.0
    assert p["intent_priority"]["relationship"] == 0.0


def test_chart_compare_over_time_not_scatter_intent_only():
    intent = {
        "raw_question": "Compare sales and customers over time",
        "metrics": [{"column": "total_sales"}, {"column": "customers"}],
        "operations": ["comparison", "multi_metric"],
        "intent": "comparison",
    }
    chart, reason = select_chart_type(intent=intent, columns=[], rows=[], question=intent["raw_question"])
    assert chart == ChartTypeEnum.LINE_MULTI
    assert "time_series" in reason


def test_temporal_compare_metric_order_permutations_are_stable():
    scenarios = (
        "Compare sales and customers over time",
        "Compare customers and sales over time",
        "Compare revenue and profit over time",
        "Compare profit and revenue over time",
    )
    for question in scenarios:
        intent = {
            "raw_question": question,
            "metrics": [{"column": "metric_a"}, {"column": "metric_b"}],
            "operations": ["comparison", "multi_metric"],
            "intent": "comparison",
        }
        chart, reason = select_chart_type(intent=intent, columns=[], rows=[], question=question)
        assert chart == ChartTypeEnum.LINE_MULTI
        assert "time_series" in reason


def test_explicit_correlation_with_temporal_words_keeps_scatter_path():
    schema = {
        "t": [
            {"name": "ds", "type": "Date"},
            {"name": "customers", "type": "UInt32"},
            {"name": "total_sales", "type": "Float64"},
        ]
    }
    out = normalize_analytical_intent(
        question="Relationship between sales and customers over time",
        raw_intent={"table": "t", "metrics": [], "dimensions": [], "filters": []},
        schema=schema,
    )
    assert out.get("intent") == "correlation"
    assert out.get("time_grouping_detected") is False
    chart, _ = select_chart_type(
        intent=out,
        columns=[],
        rows=[],
        question="Relationship between sales and customers over time",
    )
    assert chart == ChartTypeEnum.SCATTER


def test_semantic_filters_bridge_to_sql_where():
    schema = {
        "t": [
            {"name": "ds", "type": "Date"},
            {"name": "customers", "type": "UInt32"},
            {"name": "total_sales", "type": "Float64"},
        ]
    }
    out = normalize_analytical_intent(
        question="Customers above 50 by month",
        raw_intent={"metrics": ["customers"], "dimensions": [], "filters": []},
        schema=schema,
    )
    cols = {f["column"] for f in out["filters"]}
    assert "customers" in cols
    sql = compile_sql(out, schema=schema)
    assert "customers" in sql.lower() and "50" in sql


def test_orders_by_day_forces_grouped_aggregation():
    schema = {
        "t": [
            {"name": "ds", "type": "Date"},
            {"name": "orders", "type": "UInt32"},
        ]
    }
    out = normalize_analytical_intent(
        question="Orders by day",
        raw_intent={"metrics": ["orders"], "dimensions": [], "filters": []},
        schema=schema,
    )
    sql = compile_sql(out, schema=schema).upper()
    assert out["time_grouping_detected"] is True
    assert "GROUP BY PERIOD" in sql
    assert "SUM(ORDERS)" in sql


def test_minimal_temporal_phrases_route_as_analytical_and_group():
    schema = {
        "t": [
            {"name": "order_date", "type": "Date"},
            {"name": "customers", "type": "UInt32"},
            {"name": "revenue", "type": "Float64"},
        ]
    }
    scenarios = (
        ("Customers yearly", "SUM(CUSTOMERS)"),
        ("Revenue monthly", "SUM(REVENUE)"),
    )
    for question, metric_snippet in scenarios:
        classification = classify_input(raw_text=question, cleaned_text=question)
        assert classification.get("classification") == "analytical"
        intent = normalize_analytical_intent(
            question=question,
            raw_intent={"table": "t", "metrics": [], "dimensions": [], "filters": []},
            schema=schema,
        )
        sql = compile_sql(intent, schema=schema).upper()
        assert intent["time_grouping_detected"] is True
        assert "GROUP BY PERIOD" in sql
        assert metric_snippet in sql


def test_filter_only_short_queries_classify_as_analytical():
    scenarios = (
        "Orders below 20",
        "Customers above 50",
        "Revenue > 1000",
        "Profit less than 0",
        "Quantity at least 5",
    )
    for question in scenarios:
        classification = classify_input(raw_text=question, cleaned_text=question)
        assert classification.get("classification") == "analytical"


def test_composite_highest_month_sql_order_and_limit():
    schema = {
        "t": [
            {"name": "ds", "type": "Date"},
            {"name": "total_sales", "type": "Float64"},
        ]
    }
    out = normalize_analytical_intent(
        question="What month had the highest total sales?",
        raw_intent={"metrics": ["total_sales"], "dimensions": [], "filters": []},
        schema=schema,
    )
    assert out.get("composite_temporal_ranking") is True
    sql = compile_sql(out, schema=schema)
    assert "GROUP BY" in sql
    assert "LIMIT 1" in sql.upper() or "LIMIT\n1" in sql.upper().replace(" ", "")
    chart, _ = select_chart_type(intent=out, columns=[], rows=[], question="What month had the highest total sales?")
    assert chart == ChartTypeEnum.CARD


def test_best_performing_quarter_is_desc_and_uses_business_metric():
    schema = {
        "t": [
            {"name": "ds", "type": "Date"},
            {"name": "quarter", "type": "UInt8"},
            {"name": "total_sales", "type": "Float64"},
        ]
    }
    out = normalize_analytical_intent(
        question="Best performing quarter",
        raw_intent={"metrics": [], "dimensions": [], "filters": []},
        schema=schema,
    )
    sql = compile_sql(out, schema=schema).upper()
    assert out.get("ranking", {}).get("direction") == "DESC"
    assert "SUM(TOTAL_SALES)" in sql
    assert "ORDER BY SUM_TOTAL_SALES DESC" in sql
    assert "LIMIT 1" in sql
    chart, _ = select_chart_type(intent=out, columns=[], rows=[], question="Best performing quarter")
    assert chart == ChartTypeEnum.CARD


def test_top_n_grouped_ranking_prefers_bar():
    schema = {
        "t": [
            {"name": "customer_id", "type": "String"},
            {"name": "revenue", "type": "Float64"},
        ]
    }
    out = normalize_analytical_intent(
        question="Top 10 customers by revenue",
        raw_intent={"metrics": ["revenue"], "dimensions": ["customer_id"], "filters": []},
        schema=schema,
    )
    chart, _ = select_chart_type(intent=out, columns=[], rows=[], question="Top 10 customers by revenue")
    assert chart == ChartTypeEnum.BAR


def test_growth_trend_binds_customers_metric_not_year_bucket():
    schema = {
        "t": [
            {"name": "ds", "type": "Date"},
            {"name": "year", "type": "UInt16"},
            {"name": "customers", "type": "UInt32"},
            {"name": "total_sales", "type": "Float64"},
        ]
    }
    out = normalize_analytical_intent(
        question="Customer growth trend by year",
        raw_intent={"metrics": [], "dimensions": [], "filters": []},
        schema=schema,
    )
    metric_columns = [m.get("column") for m in out.get("metrics", []) if isinstance(m, dict)]
    assert "customers" in metric_columns
    assert "year" not in metric_columns
    assert out.get("time_grouping_detected") is True


def test_semantic_filters_fallback_bridge_into_sql_compiler():
    schema = {
        "t": [
            {"name": "customers", "type": "UInt32"},
        ]
    }
    sql = compile_sql(
        {
            "table": "t",
            "metrics": [{"column": "customers", "aggregation": None, "alias": "customers"}],
            "dimensions": [],
            "filters": [],
            "semantic_filters": [{"metric": "customers", "operator": ">", "value": 50}],
            "order_by": [],
            "limit": None,
            "time_grouping_detected": False,
        },
        schema=schema,
    )
    assert "WHERE customers > 50" in sql
