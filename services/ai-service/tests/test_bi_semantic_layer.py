"""Tests for NL semantic operator resolution, verb normalization, and multi-metric hints."""

from __future__ import annotations

from shared.bi_semantic_layer import (
    build_analytical_semantic_hints,
    build_nl_semantic_metadata,
    extract_canonical_verbs,
    extract_conjoined_metric_phrases,
    extract_analytical_semantics,
    extract_semantic_filters,
    has_natural_comparison_language,
    predictive_metric_columns_from_query,
    schema_diagnostic_ignore_tokens,
)
from shared.query_planner import _extract_metric_hints_from_question, _normalize_filters, build_schema_metadata


def test_semantic_filters_exceeded_and_at_least():
    q = "Show days where sales exceeded 2000 and revenue at least 100"
    items = extract_semantic_filters(q)
    phrases = {x["phrase"]: x["operator"] for x in items}
    assert "exceeded" in phrases and phrases["exceeded"] == ">"
    assert "at least" in phrases and phrases["at least"] == ">="


def test_schema_ignore_contains_operator_tokens():
    q = "customers above 50"
    ign = schema_diagnostic_ignore_tokens(q)
    assert "above" in ign


def test_canonical_verbs_compared_forecasted():
    q = "Compared total sales and customers over time"
    verbs = {v["original"]: v["canonical"] for v in extract_canonical_verbs(q)}
    assert verbs.get("compared") == "compare"


def test_conjoined_metric_phrases_compare_and_versus():
    q1 = "Compare total sales and customers over time"
    hints1 = extract_conjoined_metric_phrases(q1)
    assert any("sales" in h for h in hints1)
    assert any("customers" in h for h in hints1)

    q2 = "revenue vs profit by month"
    hints2 = extract_conjoined_metric_phrases(q2)
    assert any("revenue" in h for h in hints2)
    assert any("profit" in h for h in hints2)


def test_metric_hints_include_compared_form():
    hints = _extract_metric_hints_from_question("Compared total sales and customers over time")
    joined = " ".join(hints).lower()
    assert "sales" in joined and "customers" in joined


def test_normalize_filters_nl_operators_schema():
    schema = {
        "t": [
            {"name": "total_sales", "type": "Float64"},
            {"name": "customers", "type": "UInt32"},
            {"name": "order_date", "type": "Date"},
        ]
    }
    meta = build_schema_metadata(schema)["t"]
    question = "total_sales below 20"
    amb: list = []
    filters = _normalize_filters(
        question,
        {"filters": []},
        meta,
        ambiguities=amb,
    )
    assert any(f.get("operator") == "<" and f.get("value") == 20 for f in filters)


def test_predictive_multi_metric_resolution():
    cols = [
        {"name": "ds", "type": "Date"},
        {"name": "total_sales", "type": "Float64"},
        {"name": "customers", "type": "UInt32"},
    ]
    q = "Predict sales and customers for next 30 days"
    resolved = predictive_metric_columns_from_query(q, cols, max_metrics=2)
    assert len(resolved) >= 2


def test_has_natural_comparison_language():
    assert has_natural_comparison_language("x exceeded 3")
    assert not has_natural_comparison_language("show the table")


def test_build_nl_semantic_metadata_shape():
    meta = build_nl_semantic_metadata("Orders above 20 and customers below 5")
    assert isinstance(meta.get("semantic_filters"), list)
    assert isinstance(meta.get("canonical_verbs"), list)
    assert isinstance(meta.get("analytical_semantics"), list)
    assert isinstance(meta.get("analytical_semantic_hints"), dict)
    assert "schema_diagnostic_ignore_tokens" in meta


def test_analytical_semantic_vocabulary_resolution():
    semantics = extract_analytical_semantics("What month generated the highest total sales?")
    meanings = {item.get("semantic_meaning") for item in semantics}
    assert "aggregation_contribution" in meanings
    assert "ranking_desc" in meanings


def test_analytical_semantic_hints_ranking_direction():
    hints = build_analytical_semantic_hints("Best performing quarter")
    assert hints.get("ranking_direction_hint") == "DESC"
