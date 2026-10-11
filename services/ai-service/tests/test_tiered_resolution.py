from __future__ import annotations

import sys
import types
from pathlib import Path

if "clickhouse_connect" not in sys.modules:
    clickhouse_stub = types.ModuleType("clickhouse_connect")
    clickhouse_stub.get_client = lambda *args, **kwargs: None
    sys.modules["clickhouse_connect"] = clickhouse_stub

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from preprocessing_high.diagnostics import build_schema_resolution_diagnostics  # noqa: E402
from preprocessing_high.llm_client import (  # noqa: E402
    _build_validation_prompt,
    build_deterministic_schema_validation_result,
)
from preprocessing_high.schema_loader import ColumnReference, LoadedUserSchema  # noqa: E402


def _loaded_schema() -> LoadedUserSchema:
    schema = {
        "tables": ["sales_fact"],
        "columns": {
            "sales_fact": [
                {"name": "city", "type": "LowCardinality(String)"},
                {"name": "region", "type": "String"},
                {"name": "product_name", "type": "String"},
                {"name": "product_category", "type": "String"},
                {"name": "order_date", "type": "Date"},
                {"name": "total_sales", "type": "Float64"},
                {"name": "revenue", "type": "Float64"},
            ]
        },
    }
    refs = {
        column["name"]: [ColumnReference(table="sales_fact", name=column["name"], type=column["type"])]
        for column in schema["columns"]["sales_fact"]
    }
    return LoadedUserSchema(
        user_id="u1",
        database="etl",
        schema=schema,
        columns_by_name=refs,
        date_columns_by_name={"order_date": refs["order_date"]},
    )


def _candidate(value: str, column: str) -> dict:
    return {
        "value": value,
        "normalized_value": value.casefold(),
        "table": "sales_fact",
        "column": column,
        "clickhouse_type": "String",
    }


def _diagnostics(query: str, value_index: dict | None = None, validation_result: dict | None = None) -> dict:
    loaded_schema = _loaded_schema()
    validation = validation_result or build_deterministic_schema_validation_result(
        corrected_query=query,
        loaded_schema=loaded_schema,
    )
    return build_schema_resolution_diagnostics(
        original_query=query,
        corrected_query=query,
        loaded_schema=loaded_schema,
        validation_result=validation,
        value_index=value_index,
    )


def test_city_value_is_not_rejected_as_missing_column():
    diagnostics = _diagnostics(
        "Show total sales in Damascus.",
        {"damascus": [_candidate("Damascus", "city")]},
    )

    assert diagnostics["schema_validation_status"] == "valid_with_value_matches"
    assert diagnostics["value_matches"][0]["column"] == "city"
    assert diagnostics["unresolved_terms"] == []
    assert any(term.get("classification") == "value_reference" for term in diagnostics["terms"])


def test_multi_word_and_arabic_values_are_preserved_and_matched():
    diagnostics = _diagnostics(
        "Show revenue for Samsung Galaxy in دمشق",
        {
            "samsung galaxy": [_candidate("Samsung Galaxy", "product_name")],
            "دمشق": [_candidate("دمشق", "city")],
        },
    )

    matched_values = {candidate["value"] for candidate in diagnostics["value_matches"]}
    assert matched_values == {"Samsung Galaxy", "دمشق"}
    assert diagnostics["schema_validation_status"] == "valid_with_value_matches"


def test_analytical_terms_are_not_missing_columns():
    diagnostics = _diagnostics("Show monthly sales trend by region")

    assert "trend" not in diagnostics["unresolved_terms"]
    assert "monthly" not in diagnostics["unresolved_terms"]
    assert diagnostics["schema_validation_status"] in {"valid", "valid_with_llm_assist"}


def test_unknown_term_is_uncertain_and_preserved_for_intent():
    diagnostics = _diagnostics("Show sales for blorp")

    unresolved = [
        term
        for term in diagnostics["terms"]
        if str(term.get("term") or "").strip().lower() == "blorp"
    ]
    assert diagnostics["schema_validation_status"] == "degraded_uncertain"
    assert diagnostics["unresolved_terms"] == ["blorp"]
    assert unresolved
    assert unresolved[0]["classification"] == "uncertain"
    assert unresolved[0]["resolution_status"] == "unresolved"
    assert unresolved[0]["must_preserve_for_intent"] is True
    assert "does not exist" not in unresolved[0]["reason"].lower()


def test_value_match_overrides_invalid_llm_classification_without_other_unresolved_terms():
    diagnostics = _diagnostics(
        "Show revenue for Samsung",
        {"samsung": [_candidate("Samsung", "product_name")]},
        validation_result={
            "is_valid": False,
            "missing_column": "Samsung",
            "mappings": [
                {
                    "requested": "Samsung",
                    "matched_table": "",
                    "matched_column": "",
                    "status": "invalid",
                    "reason": "LLM treated a value as a column.",
                }
            ],
            "derivable_columns": [],
            "invalid_mappings": [],
        },
    )

    assert diagnostics["schema_validation_status"] == "valid_with_value_matches"
    assert diagnostics["value_matches"][0]["value"] == "Samsung"


def test_llm_validation_prompt_receives_value_match_candidates():
    prompt = _build_validation_prompt(
        corrected_query="Show total sales in Damascus",
        loaded_schema=_loaded_schema(),
        value_index={"damascus": [_candidate("Damascus", "city")]},
    )

    assert "Indexed value matches" in prompt
    assert "Damascus" in prompt
    assert "city" in prompt
