from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("services/ai-service"))

from shared.pipeline_guards import dataset_scope_guard, forecasting_validator, time_column_validator


class PipelineGuardTests(unittest.TestCase):
    def test_time_column_validator_rejects_technical_metadata(self):
        valid, reason = time_column_validator(
            selected_time_column="_cleaned_at",
            available_columns=["_cleaned_at", "ds", "value"],
        )
        self.assertFalse(valid)
        self.assertEqual(reason, "time_column_is_technical_metadata")

    def test_dataset_scope_guard_prefers_explicit_table_name(self):
        schema = {
            "population_distribution_csv": [{"name": "region", "type": "String"}],
            "quality_metrics": [{"name": "_loaded_at", "type": "DateTime"}],
        }
        scoped, meta = dataset_scope_guard(
            schema=schema,
            dataset_scope={"table_name": "population_distribution_csv"},
            strict=True,
        )
        self.assertEqual(list(scoped.keys()), ["population_distribution_csv"])
        self.assertEqual(meta.get("reason_for_selection"), "scope_filter_applied")

    def test_dataset_scope_guard_matches_qualified_table_binding(self):
        schema = {
            "sales_3months_realistic_csv": [{"name": "ds", "type": "Date"}],
        }
        scoped, meta = dataset_scope_guard(
            schema=schema,
            dataset_scope={"table_name": "etl.sales_3months_realistic_csv"},
            strict=True,
        )
        self.assertEqual(list(scoped.keys()), ["sales_3months_realistic_csv"])
        self.assertEqual(meta.get("selected_table"), "sales_3months_realistic_csv")

    def test_forecasting_validator_blocks_insufficient_history(self):
        valid, message = forecasting_validator(
            actual_points=1,
            minimum_points=14,
            spacing_ok=True,
            spacing_reason="ok",
        )
        self.assertFalse(valid)
        self.assertIn("Insufficient historical data for forecasting", message)

    def test_dataset_scope_guard_raises_on_mismatch_when_strict(self):
        schema = {
            "population_distribution_csv": [{"name": "region", "type": "String"}],
        }
        with self.assertRaises(ValueError):
            dataset_scope_guard(
                schema=schema,
                dataset_scope={
                    "workspace_id": "w1",
                    "dataset_id": "d1",
                    "manager_id": "m1",
                    "table_name": "sales_3months_realistic_csv",
                },
                strict=True,
            )


if __name__ == "__main__":
    unittest.main()
