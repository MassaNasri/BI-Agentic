from __future__ import annotations

import logging
import sys
import types
import unittest
from unittest.mock import patch

if "clickhouse_connect" not in sys.modules:
    sys.modules["clickhouse_connect"] = types.SimpleNamespace(get_client=lambda **_kwargs: None)

from preprocessing_high.llm_client import validate_query_schema_usage
from preprocessing_high.schemas import HighPreprocessConfig


class _FakeLoadedSchema:
    def __init__(self, columns_by_table: dict[str, list[dict[str, str]]]) -> None:
        self.user_id = "u1"
        self.database = "etl"
        self.schema = {"tables": list(columns_by_table.keys()), "columns": columns_by_table}
        self.columns_by_name = {}
        self.date_columns_by_name = {}


def _build_loaded_schema(columns_by_table: dict[str, list[dict[str, str]]]):
    columns_by_name = {}
    date_columns_by_name = {}
    for table_name, columns in columns_by_table.items():
        for column in columns:
            name = column["name"]
            ref = type("ColumnRef", (), {"table": table_name, "name": name, "type": column.get("type", "")})()
            columns_by_name.setdefault(name.lower(), []).append(ref)
            if "date" in column.get("type", "").lower() or "time" in column.get("type", "").lower():
                date_columns_by_name.setdefault(name.lower(), []).append(ref)
    loaded = _FakeLoadedSchema(columns_by_table)
    loaded.columns_by_name = columns_by_name
    loaded.date_columns_by_name = date_columns_by_name
    return loaded


class ValidationClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = HighPreprocessConfig.from_env()
        self.logger = logging.getLogger("preprocessing_high.tests_llm_client")
        self.log_event = lambda *_args, **_kwargs: None
        self.sales_schema = _build_loaded_schema(
            {
                "sales_3months_realistic_csv": [
                    {"name": "ds", "type": "Date"},
                    {"name": "total_sales", "type": "Float64"},
                    {"name": "orders", "type": "UInt64"},
                    {"name": "customers", "type": "UInt64"},
                ]
            }
        )
        self.sales_schema_with_string_ds = _build_loaded_schema(
            {
                "sales_3months_realistic_csv": [
                    {"name": "ds", "type": "String"},
                    {"name": "total_sales", "type": "Float64"},
                    {"name": "orders", "type": "UInt64"},
                    {"name": "customers", "type": "UInt64"},
                ]
            }
        )

    @patch(
        "preprocessing_high.llm_client._call_ollama",
        return_value=
            '{"references": ['
            '{"requested":"sales","matched_table":"sales_3months_realistic_csv","matched_column":"total_sales","status":"mapped","reason":"Metric mapping."},'
            '{"requested":"highest","matched_table":"","matched_column":"","status":"invalid","reason":"Unknown token."},'
            '{"requested":"days","matched_table":"sales_3months_realistic_csv","matched_column":"ds","status":"derivable","reason":"Derived time grain."}'
            "]}",
    )
    def test_llm_invalid_analytical_word_does_not_reject_query(self, _mock_ollama):
        result = validate_query_schema_usage(
            corrected_query="what are the top 7 days with highest sales",
            loaded_schema=self.sales_schema,
            config=self.config,
            logger=self.logger,
            log_event=self.log_event,
        )
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["invalid_mappings"], [])
        matched_columns = {str(mapping.get("matched_column", "")) for mapping in result.get("mappings", [])}
        self.assertIn("total_sales", matched_columns)

    @patch("preprocessing_high.llm_client._call_ollama", return_value='{"references": []}')
    def test_week_granularity_allows_string_ds_fallback(self, _mock_ollama):
        result = validate_query_schema_usage(
            corrected_query="what is the total sales per week",
            loaded_schema=self.sales_schema_with_string_ds,
            config=self.config,
            logger=self.logger,
            log_event=self.log_event,
        )
        self.assertTrue(result["is_valid"])
        derivable_requested = {str(mapping.get("requested", "")).lower() for mapping in result.get("derivable_columns", [])}
        self.assertIn("week", derivable_requested)


if __name__ == "__main__":
    unittest.main()
