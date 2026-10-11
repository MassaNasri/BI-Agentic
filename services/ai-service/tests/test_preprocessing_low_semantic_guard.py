from __future__ import annotations

import os
import sys
import types
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

if "dagster" not in sys.modules:
    dagster_stub = types.ModuleType("dagster")

    class _AssetExecutionContext:
        def __init__(self):
            self.log = type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})()

    def _asset(*args, **kwargs):
        def decorator(fn):
            return fn

        return decorator

    class _RetryPolicy:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    def _failure_hook(fn):
        return fn

    dagster_stub.AssetExecutionContext = _AssetExecutionContext
    dagster_stub.HookContext = object
    dagster_stub.RetryPolicy = _RetryPolicy
    dagster_stub.asset = _asset
    dagster_stub.failure_hook = _failure_hook
    sys.modules["dagster"] = dagster_stub


from preprocessing_low.preprocess_task import run_preprocess_text

_PREPROCESSING_LOW_ASSET_PATH = SERVICE_ROOT / "dagster_pipeline" / "assets" / "preprocessing_low.py"
_asset_spec = importlib.util.spec_from_file_location("preprocessing_low_asset_test_module", _PREPROCESSING_LOW_ASSET_PATH)
assert _asset_spec and _asset_spec.loader
_asset_module = importlib.util.module_from_spec(_asset_spec)
_asset_spec.loader.exec_module(_asset_module)
preprocessing_low_asset = _asset_module.preprocessing_low_asset


class _FakeContext:
    log = type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})()


class PreprocessingLowSemanticGuardTests(unittest.TestCase):
    def _assert_preserved(self, cleaned_text: str, required_terms: list[str]) -> None:
        normalized = f" {cleaned_text.lower()} "
        for term in required_terms:
            self.assertIn(term.lower(), normalized)

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", side_effect=lambda text, **_: text)
    def test_preserves_semantic_bi_terms_across_question_categories(self, _mock_llm):
        cases = [
            (
                "Compare total sales and customers over time",
                ["compare", "total sales", "customers", "over time"],
            ),
            (
                "Compare total sales and orders by month",
                ["compare", "total sales", "orders", "by month"],
            ),
            (
                "Show the top 10 days with the highest number of orders",
                ["top 10", "days", "highest", "orders"],
            ),
            (
                "List all days where total sales exceeded 2000",
                ["days", "total sales", "exceeded", "2000"],
            ),
            (
                "Predict total sales for the next 30 days",
                ["predict", "total sales", "next 30 days"],
            ),
            (
                "What is the relationship between total sales and orders?",
                ["relationship", "between", "total sales", "orders"],
            ),
            (
                "Show percentage share of total sales by month",
                ["percentage", "share", "total sales", "by month"],
            ),
            (
                "Show distribution of total sales",
                ["distribution", "total sales"],
            ),
            (
                "Show orders from January to March",
                ["orders", "from", "january", "to", "march"],
            ),
            (
                "What is the average order count by week?",
                ["average", "order count", "by week"],
            ),
            (
                "What month generated the highest total sales?",
                ["month", "highest", "total sales"],
            ),
            (
                "please can you show me the total sales by month",
                ["total sales", "by month"],
            ),
        ]

        for question, required_terms in cases:
            with self.subTest(question=question):
                result = run_preprocess_text(question)
                self.assertEqual(result["status"], "success")
                self._assert_preserved(result["cleaned_text"], required_terms)
                self.assertEqual(result["original_sentence"], question)
                self.assertTrue(result["semantic_preservation"]["semantic_preservation_passed"])
                self.assertFalse(result["semantic_preservation"]["missing_semantic_terms"])

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", return_value="sales comparison")
    def test_rejects_llm_cleaning_that_removes_semantic_terms(self, _mock_llm):
        question = "Compare total sales and customers over time"

        result = run_preprocess_text(question)

        self.assertEqual(result["status"], "success")
        self.assertNotEqual(result["cleaned_text"], "sales comparison")
        self._assert_preserved(result["cleaned_text"], ["compare", "total sales", "customers", "over time"])
        rejected = result.get("rejected_changes", [])
        self.assertTrue(rejected)
        self.assertEqual(rejected[0]["type"], "semantic_preservation_rejected")
        self.assertIn("customers", rejected[0]["missing_terms"])
        self.assertIn("over time", rejected[0]["missing_terms"])
        warning_types = {warning.get("type") for warning in result.get("warnings", [])}
        self.assertIn("semantic_preservation_rejected", warning_types)
        self.assertEqual(result["debug_metadata"]["rejected_changes"], rejected)
        self.assertTrue(result["attempts"][-1]["validation_result"]["semantic_preservation_rejected"])
        self.assertIn("missing_terms", result["attempts"][-1]["validation_result"]["semantic_preservation"])

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", side_effect=lambda text, **_: text)
    def test_filter_operator_terms_are_preserved_and_mapped_in_metadata(self, _mock_llm):
        result = run_preprocess_text("List all days where total sales exceeded 2000")

        self._assert_preserved(result["cleaned_text"], ["days", "total sales", "exceeded", "2000"])
        self.assertIn({"term": "exceeded", "operator": ">"}, result["filter_operators"])

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", return_value="highest total sales")
    def test_rejects_dropping_superlative_grouping_dimension(self, _mock_llm):
        question = "What month generated the highest total sales?"

        result = run_preprocess_text(question)

        self.assertNotEqual(result["cleaned_text"], "highest total sales")
        self._assert_preserved(result["cleaned_text"], ["month", "highest", "total sales"])
        missing_terms = result["rejected_changes"][0]["missing_terms"]
        self.assertIn("month", missing_terms)

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", return_value="total sales and orders")
    def test_dagster_asset_exposes_rejected_semantic_normalization_metadata(self, _mock_llm):
        result = preprocessing_low_asset(
            _FakeContext(),
            pipeline_request_asset={"workspace_id": "w1", "dataset_id": "d1"},
            transcription_asset={"status": "success", "text": "Compare total sales and orders by month"},
        )

        self.assertEqual(result["status"], "success")
        self._assert_preserved(result["cleaned_text"], ["compare", "total sales", "orders", "by month"])
        self.assertTrue(result["rejected_changes"])
        self.assertIn("by month", result["rejected_changes"][0]["missing_terms"])
        self.assertIn("semantic_preservation", result["debug_metadata"])
        self.assertEqual(result["debug_metadata"]["dataset_context"]["dataset_id"], "d1")


if __name__ == "__main__":
    unittest.main()
