"""Tests for temporal priority, grouping metadata, composite superlatives, and metric variants."""

from __future__ import annotations

import sys
from pathlib import Path

AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (AI_SERVICE_ROOT, REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.bi_temporal_semantics import (
    analyze_temporal_intent,
    build_grouping_metadata,
    detect_composite_temporal_superlative,
    explicit_correlation_language,
    has_explicit_temporal_phrase,
    infer_nl_time_granularity,
    metric_lexical_variants,
    should_treat_as_relationship_scatter,
    temporal_priority_over_relationship,
)
from bi_platform_shared.semantic.intent_priority import build_intent_priority_payload
from shared.query_planner import _infer_time_granularity, _resolve_column_name, normalize_analytical_intent


def test_temporal_priority_suppresses_compare_scatter():
    q = "Compare sales and customers over time"
    assert temporal_priority_over_relationship(q)
    assert not should_treat_as_relationship_scatter(q)
    sem = analyze_temporal_intent(q)
    assert sem["intent_family"] == "time_series"
    payload = build_intent_priority_payload(q)
    assert payload["temporal_dominance_enforced"] is True
    assert payload["suppress_relationship_scatter"] is True


def test_explicit_correlation_keeps_relationship():
    q = "Show the scatter plot of correlation between sales and customers over time"
    assert explicit_correlation_language(q)
    assert should_treat_as_relationship_scatter(q)


def test_infer_nl_granularity_by_month():
    assert infer_nl_time_granularity("revenue by month") == "month"
    assert _infer_time_granularity("orders by day") == "day"


def test_grouping_metadata():
    meta = build_grouping_metadata("sales by quarter", time_granularity="quarter")
    assert meta["time_unit"] == "quarter"
    assert meta["group_by_required"] is True


def test_composite_superlative_what_month():
    r = detect_composite_temporal_superlative(
        "What month generated the highest total sales?"
    )
    assert r["active"] and r["time_granularity"] == "month" and r["ranking_direction"] == "DESC"


def test_metric_lexical_variants_singular_plural():
    v = metric_lexical_variants("customer")
    assert "customers" in v
    assert "customer" in v


def test_resolve_column_plural_schema():
    cols = [{"name": "customers", "type": "UInt32"}, {"name": "total_sales", "type": "Float64"}]
    assert _resolve_column_name("customer", cols) == "customers"


def test_normalize_time_series_over_compare_schema():
    schema = {
        "t": [
            {"name": "ds", "type": "Date"},
            {"name": "total_sales", "type": "Float64"},
            {"name": "customers", "type": "UInt32"},
        ]
    }
    out = normalize_analytical_intent(
        question="Compare sales and customers over time",
        raw_intent={"metrics": ["total_sales", "customers"], "dimensions": [], "filters": []},
        schema=schema,
    )
    assert out["intent"] == "time_series"
    assert out["time_grouping_detected"] is True
    assert out.get("temporal_semantics", {}).get("intent_family") == "time_series"
    assert out["analysis_mode"] != "relationship"


def test_has_explicit_temporal_phrase_positive():
    assert has_explicit_temporal_phrase("Compare sales and customers over time")
    assert has_explicit_temporal_phrase("Compare customers and sales over time")
    assert has_explicit_temporal_phrase("Compare customers and sales over   time")
    assert has_explicit_temporal_phrase("Compare customers and sales over\ttime")
    assert has_explicit_temporal_phrase("Show trend of revenue")
    assert has_explicit_temporal_phrase("Revenue daily")
    assert has_explicit_temporal_phrase("Orders by month")
    assert has_explicit_temporal_phrase("Sales across time")
    assert has_explicit_temporal_phrase("time series of orders")


def test_has_explicit_temporal_phrase_negative():
    assert not has_explicit_temporal_phrase("Relationship between sales and customers")
    assert not has_explicit_temporal_phrase("Total sales")
    assert not has_explicit_temporal_phrase("Show top 5 products")
    assert not has_explicit_temporal_phrase("")


def test_metric_order_invariance_both_questions_time_series():
    """Both orderings must classify as time_series, not relationship."""
    schema = {
        "t": [
            {"name": "ds", "type": "Date"},
            {"name": "total_sales", "type": "Float64"},
            {"name": "customers", "type": "UInt32"},
        ]
    }
    q1 = "Compare sales and customers over time"
    q2 = "Compare customers and sales over time"

    out1 = normalize_analytical_intent(
        question=q1,
        raw_intent={"metrics": ["total_sales", "customers"], "dimensions": [], "filters": []},
        schema=schema,
    )
    out2 = normalize_analytical_intent(
        question=q2,
        raw_intent={"metrics": ["customers", "total_sales"], "dimensions": [], "filters": []},
        schema=schema,
    )

    assert out1["intent"] == "time_series"
    assert out2["intent"] == "time_series"
    assert out1["time_grouping_detected"] is True
    assert out2["time_grouping_detected"] is True
    assert out1["analysis_mode"] != "relationship"
    assert out2["analysis_mode"] != "relationship"
    assert "relationship" not in out1.get("operations", [])
    assert "relationship" not in out2.get("operations", [])

    metrics_a = sorted(m.get("column") for m in out1.get("metrics", []))
    metrics_b = sorted(m.get("column") for m in out2.get("metrics", []))
    assert metrics_a == metrics_b


def test_normalize_semantic_plan_final_enforces_temporal():
    """normalize_semantic_plan_final must fix a broken LLM plan with temporal phrase."""
    from intent_extraction.llm_extractor import normalize_semantic_plan_final

    schema = {
        "t": [
            {"name": "ds", "type": "Date"},
            {"name": "total_sales", "type": "Float64"},
            {"name": "customers", "type": "UInt32"},
        ]
    }
    bad_plan = {
        "intent_type": "analytical",
        "intent": "comparison",
        "metrics": ["total_sales", "customers"],
        "metric_specs": [
            {"column": "total_sales", "aggregation": None, "alias": None},
            {"column": "customers", "aggregation": None, "alias": None},
        ],
        "dimensions": [],
        "filters": [],
        "operations": ["projection", "relationship", "comparison", "multi_metric"],
        "analysis_mode": "relationship",
    }

    fixed = normalize_semantic_plan_final(
        question="Compare sales and customers over time",
        plan=bad_plan,
        schema=schema,
    )

    assert "time_grouping" in fixed["operations"]
    assert "aggregation" in fixed["operations"]
    assert "grouping" in fixed["operations"]
    assert "sorting" in fixed["operations"]
    assert "relationship" not in fixed["operations"]
    assert fixed.get("intent") != "correlation"
    assert fixed.get("analysis_mode", "") != "relationship"
    assert "ds" in fixed.get("dimensions", [])
    for spec in fixed.get("metric_specs", []):
        assert spec.get("aggregation") == "SUM"


def test_normalize_semantic_plan_final_preserves_non_temporal():
    """Without temporal phrase, normalize_semantic_plan_final is a no-op."""
    from intent_extraction.llm_extractor import normalize_semantic_plan_final

    schema = {"t": [{"name": "ds", "type": "Date"}, {"name": "x", "type": "Float64"}]}
    plan = {
        "intent": "correlation",
        "operations": ["projection", "relationship"],
        "analysis_mode": "relationship",
    }
    result = normalize_semantic_plan_final(
        question="Relationship between sales and customers",
        plan=plan,
        schema=schema,
    )
    assert result["intent"] == "correlation"
    assert "relationship" in result["operations"]


def test_normalize_semantic_plan_final_preserves_explicit_correlation():
    """Explicit correlation language keeps scatter even with temporal phrase."""
    from intent_extraction.llm_extractor import normalize_semantic_plan_final

    schema = {"t": [{"name": "ds", "type": "Date"}, {"name": "x", "type": "Float64"}]}
    plan = {
        "intent": "correlation",
        "operations": ["projection", "relationship"],
        "analysis_mode": "relationship",
    }
    result = normalize_semantic_plan_final(
        question="scatter plot of correlation between sales and customers over time",
        plan=plan,
        schema=schema,
    )
    assert result["intent"] == "correlation"
    assert "relationship" in result["operations"]
