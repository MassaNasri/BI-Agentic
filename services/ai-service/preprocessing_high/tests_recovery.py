from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

if "clickhouse_connect" not in sys.modules:
    sys.modules["clickhouse_connect"] = types.SimpleNamespace(get_client=lambda **_kwargs: None)

from preprocessing_high.preprocess_high_task import run_preprocess_high


class RecoveryFlowTests(unittest.TestCase):
    def _loaded_schema(self):
        return types.SimpleNamespace(
            schema={
                "tables": ["sales_3months_realistic_csv"],
                "columns": {
                    "sales_3months_realistic_csv": [
                        {"name": "customers", "type": "UInt64"},
                        {"name": "total_sales", "type": "Float64"},
                        {"name": "ds", "type": "Date"},
                    ]
                },
            }
        )

    def _fake_validation(self, corrected_query: str, **_kwargs):
        lowered = str(corrected_query).lower()
        if "totol" in lowered:
            return {
                "is_valid": False,
                "missing_column": "totol",
                "mappings": [],
                "derivable_columns": [],
                "invalid_mappings": [{"requested": "totol", "status": "invalid"}],
            }
        return {
            "is_valid": True,
            "missing_column": "",
            "mappings": [{"requested": "total", "matched_column": "total_sales", "status": "mapped"}],
            "derivable_columns": [],
            "invalid_mappings": [],
        }

    def _fake_diagnostics(self, corrected_query: str, **_kwargs):
        lowered = str(corrected_query).lower()
        if "totol" in lowered:
            return {
                "unresolved_terms": ["totol"],
                "unresolved_lexical_terms": ["totol"],
                "unsupported_terms": [],
                "schema_validation_status": "invalid_unresolved_terms",
                "term_resolutions": [],
                "candidate_columns": {"totol": ["total_sales"]},
            }
        return {
            "unresolved_terms": [],
            "unresolved_lexical_terms": [],
            "unsupported_terms": [],
            "schema_validation_status": "valid",
            "term_resolutions": [],
            "candidate_columns": {},
        }

    def _fake_fuzzy_tokens(self, *, query: str, target_terms=None, **_kwargs):
        targeted = {str(term).strip().lower() for term in (target_terms or set()) if str(term).strip()}
        if "totol" in targeted and "totol" in str(query).lower():
            corrected = str(query).replace("totol", "total")
            return corrected, [{"type": "typo", "from": "totol", "to": "total", "message": "Corrected 'totol' to 'total'."}]
        return str(query), []

    @patch("preprocessing_high.preprocess_high_task.correct_query_terms", side_effect=lambda **kwargs: kwargs["query"])
    @patch("preprocessing_high.preprocess_high_task._apply_fuzzy_phrase_corrections", side_effect=lambda **kwargs: (kwargs["query"], []))
    @patch("preprocessing_high.preprocess_high_task._apply_fuzzy_token_corrections")
    @patch("preprocessing_high.preprocess_high_task.build_schema_resolution_diagnostics")
    @patch("preprocessing_high.preprocess_high_task.validate_query_schema_usage")
    @patch("preprocessing_high.preprocess_high_task.load_user_schema")
    def test_unresolved_terms_are_recovered_with_targeted_retry(
        self,
        load_schema_mock,
        validate_mock,
        diagnostics_mock,
        fuzzy_token_mock,
        _fuzzy_phrase_mock,
        _correct_query_mock,
    ):
        load_schema_mock.return_value = self._loaded_schema()
        validate_mock.side_effect = self._fake_validation
        diagnostics_mock.side_effect = self._fake_diagnostics
        fuzzy_token_mock.side_effect = self._fake_fuzzy_tokens

        result = run_preprocess_high(
            cleaned_text="How do customers impact totol sales?",
            user_id="manager_1",
            route="analytical",
            dataset_scope={
                "workspace_id": "w1",
                "dataset_id": "d1",
                "manager_id": "m1",
                "table_name": "sales_3months_realistic_csv",
            },
        )

        self.assertEqual(result["status"], "success")
        self.assertNotIn("totol", str(result.get("final_query", "")).lower())
        self.assertIn("term_corrections", result)
        self.assertTrue(
            any(str(item.get("from", "")).lower() == "totol" for item in result.get("term_corrections", []))
        )
        self.assertEqual(result.get("unresolved_terms", []), [])


if __name__ == "__main__":
    unittest.main()
