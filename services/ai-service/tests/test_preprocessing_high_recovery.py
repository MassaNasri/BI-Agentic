from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch

if "clickhouse_connect" not in sys.modules:
    clickhouse_stub = types.ModuleType("clickhouse_connect")

    def _get_client(*args, **kwargs):
        raise RuntimeError("clickhouse client is not available in unit tests")

    clickhouse_stub.get_client = _get_client
    sys.modules["clickhouse_connect"] = clickhouse_stub

sys.path.insert(0, os.path.abspath("services/ai-service"))

from preprocessing_high.llm_client import build_deterministic_schema_validation_result
from preprocessing_high.diagnostics import build_schema_resolution_diagnostics
from preprocessing_high.preprocess_high_task import (
    _apply_business_term_normalization,
    _apply_fuzzy_phrase_corrections,
    _apply_fuzzy_token_corrections,
    run_preprocess_high,
)
from preprocessing_high.schema_loader import LoadedUserSchema


def _loaded_schema_fixture() -> LoadedUserSchema:
    schema = {
        "tables": ["sales_fact"],
        "columns": {
            "sales_fact": [
                {"name": "customers", "type": "UInt32"},
                {"name": "orders", "type": "UInt32"},
                {"name": "order_date", "type": "Date"},
                {"name": "total_sales", "type": "Float64"},
            ]
        },
    }
    return LoadedUserSchema(
        user_id="u1",
        database="etl",
        schema=schema,
        columns_by_name={
            "customers": [],
            "orders": [],
            "order_date": [],
            "total_sales": [],
        },
        date_columns_by_name={"order_date": []},
    )


class PreprocessHighRecoveryTests(unittest.TestCase):
    def test_fuzzy_phrase_correction_maps_totol_sales_to_total_sales(self):
        corrected, corrections = _apply_fuzzy_phrase_corrections(
            query="How do customers impact totol sales?",
            loaded_schema=_loaded_schema_fixture(),
        )
        self.assertIn("total_sales", corrected)
        self.assertTrue(
            any(
                str(item.get("from", "")).strip().lower() == "totol sales"
                and str(item.get("to", "")).strip().lower() == "total_sales"
                for item in corrections
            )
        )

    def test_fuzzy_token_correction_maps_custmers_to_customers(self):
        corrected, corrections = _apply_fuzzy_token_corrections(
            query="How many custmers per day?",
            loaded_schema=_loaded_schema_fixture(),
        )
        self.assertIn("customers", corrected)
        self.assertTrue(
            any(
                str(item.get("from", "")).strip().lower() == "custmers"
                and str(item.get("to", "")).strip().lower() == "customers"
                for item in corrections
            )
        )

    def test_semantic_normalization_maps_impact_to_relationship(self):
        corrected, corrections = _apply_business_term_normalization("How do customers impact total sales?")
        self.assertIn("relationship", corrected.lower())
        self.assertTrue(
            any(
                str(item.get("from", "")).strip().lower() == "impact"
                and str(item.get("to", "")).strip().lower() == "relationship"
                for item in corrections
            )
        )

    def test_common_question_words_are_not_unresolved_schema_terms(self):
        diagnostics = build_schema_resolution_diagnostics(
            original_query="Which days had the highest number of customers?",
            corrected_query="Which days had the highest number of customers?",
            loaded_schema=_loaded_schema_fixture(),
            validation_result=build_deterministic_schema_validation_result(
                corrected_query="Which days had the highest number of customers?",
                loaded_schema=_loaded_schema_fixture(),
            ),
        )
        self.assertNotIn("had", diagnostics.get("unresolved_terms", []))
        self.assertNotIn("which", diagnostics.get("unresolved_terms", []))
        self.assertNotIn("highest", diagnostics.get("unresolved_terms", []))
        self.assertFalse(diagnostics.get("unresolved_terms"))

    @patch("preprocessing_high.preprocess_high_task.load_user_schema")
    @patch("preprocessing_high.preprocess_high_task.correct_query_terms")
    @patch("preprocessing_high.preprocess_high_task.validate_query_schema_usage")
    def test_run_preprocess_high_recovers_typo_without_rejection(
        self,
        mock_validate_query_schema_usage,
        mock_correct_query_terms,
        mock_load_user_schema,
    ):
        loaded_schema = _loaded_schema_fixture()
        mock_load_user_schema.return_value = loaded_schema
        mock_correct_query_terms.side_effect = lambda **kwargs: kwargs["query"]
        mock_validate_query_schema_usage.side_effect = lambda **kwargs: build_deterministic_schema_validation_result(
            corrected_query=kwargs["corrected_query"],
            loaded_schema=kwargs["loaded_schema"],
        )

        result = run_preprocess_high(
            cleaned_text="How do customers impact totol sales?",
            user_id="u1",
            route="analytical",
            dataset_scope={"workspace_id": "w1", "dataset_id": "d1", "manager_id": "m1", "table_name": "sales_fact"},
        )

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("error_type"), "none")
        self.assertIn("total_sales", str(result.get("final_query", "")).lower())
        self.assertFalse(result.get("unresolved_terms"))
        self.assertTrue(
            any(
                str(item.get("from", "")).strip().lower() in {"totol", "totol sales"}
                and str(item.get("to", "")).strip().lower() in {"total", "total_sales"}
                for item in result.get("term_corrections", [])
                if isinstance(item, dict)
            )
        )
        self.assertTrue(
            any(
                "corrected" in str(message).lower()
                for message in result.get("user_friendly_messages", [])
            )
        )

    @patch("preprocessing_high.preprocess_high_task.load_user_schema")
    @patch("preprocessing_high.preprocess_high_task.correct_query_terms")
    @patch("preprocessing_high.preprocess_high_task.validate_query_schema_usage")
    @patch("preprocessing_high.preprocess_high_task.build_schema_resolution_diagnostics")
    def test_deferred_schema_validation_is_degraded_and_schema_invalid(
        self,
        mock_build_schema_resolution_diagnostics,
        mock_validate_query_schema_usage,
        mock_correct_query_terms,
        mock_load_user_schema,
    ):
        loaded_schema = _loaded_schema_fixture()
        mock_load_user_schema.return_value = loaded_schema
        mock_correct_query_terms.side_effect = lambda **kwargs: kwargs["query"]
        mock_validate_query_schema_usage.return_value = {
            "is_valid": False,
            "missing_column": "revenue",
            "mappings": [],
            "derivable_columns": [],
            "invalid_mappings": [],
        }
        mock_build_schema_resolution_diagnostics.return_value = {
            "schema_validation_status": "invalid_unresolved_terms",
            "unresolved_terms": ["revenue"],
            "unsupported_terms": [],
            "original_terms": ["revenue"],
            "corrected_terms": ["revenue"],
            "term_resolutions": [],
            "candidate_columns": {"revenue": ["total_sales"]},
            "candidate_tables": ["sales_fact"],
            "selected_table": "sales_fact",
            "selected_columns": ["total_sales"],
            "unresolved_lexical_terms": ["revenue"],
        }

        result = run_preprocess_high(
            cleaned_text="Show revenue by day",
            user_id="u1",
            route="analytical",
            dataset_scope={"workspace_id": "w1", "dataset_id": "d1", "manager_id": "m1", "table_name": "sales_fact"},
        )

        self.assertEqual(result.get("status"), "degraded")
        self.assertFalse(result.get("schema_valid"))
        self.assertTrue(result.get("degraded"))
        self.assertTrue(result.get("deferred"))
        self.assertEqual(result.get("degradation_reason"), "schema_validation_deferred")


if __name__ == "__main__":
    unittest.main()
