from __future__ import annotations

import unittest
from unittest.mock import patch

from shared.query_planner import normalize_analytical_intent
from shared.sql_compiler import compile_sql
from shared.sql_review import review_and_correct_sql
from shared.sql_validator import validate_sql


TEST_SCHEMA = {
    "population_distribution_csv": [
        {"name": "region", "type": "String"},
        {"name": "city", "type": "String"},
        {"name": "total_population", "type": "UInt64"},
        {"name": "avg_age", "type": "Float64"},
    ]
}


class SqlSafetyTests(unittest.TestCase):
    def test_validator_blocks_destructive_sql(self):
        with self.assertRaises(ValueError):
            validate_sql("DROP TABLE users;")

    def test_validator_blocks_multi_statement_sql(self):
        with self.assertRaises(ValueError):
            validate_sql("SELECT * FROM t; SELECT * FROM t2;")

    def test_validator_accepts_read_only_select(self):
        validate_sql("SELECT city, SUM(total_population) AS sum_total_population FROM etl.population_distribution_csv GROUP BY city")


class SqlGenerationReviewTests(unittest.TestCase):
    def test_top_5_query_includes_group_order_limit(self):
        intent = normalize_analytical_intent(
            question="show top 5 cities by total population",
            raw_intent={},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        upper = sql.upper()
        self.assertIn("GROUP BY city".upper(), upper)
        self.assertIn("ORDER BY", upper)
        self.assertIn("LIMIT 5", upper)

    def test_sql_review_rejects_top_n_without_limit(self):
        reviewed = review_and_correct_sql(
            question="show top 5 cities by total population",
            schema=TEST_SCHEMA,
            generated_sql=(
                "SELECT city, SUM(total_population) AS sum_total_population "
                "FROM etl.population_distribution_csv "
                "GROUP BY city "
                "ORDER BY sum_total_population DESC"
            ),
            validated_intent={},
            extracted_intent={},
        )
        self.assertIn(reviewed["status"], {"rejected", "approved", "corrected"})
        if reviewed["status"] == "rejected":
            self.assertTrue(reviewed.get("notes"))

    def test_sql_review_keeps_ir_table_alignment_when_disabled(self):
        reviewed = review_and_correct_sql(
            question="show total population by city",
            schema=TEST_SCHEMA,
            generated_sql=(
                "SELECT city, SUM(total_population) AS sum_total_population "
                "FROM etl.population_distribution_csv GROUP BY city"
            ),
            validated_intent={
                "table": "population_distribution_csv",
                "metrics": [{"column": "total_population", "aggregation": "SUM", "alias": "sum_total_population"}],
                "dimensions": ["city"],
                "filters": [],
                "order_by": [],
                "limit": None,
            },
            extracted_intent={},
        )
        self.assertIn("population_distribution_csv", reviewed["reviewed_sql"])

    @patch("shared.sql_review._call_openrouter")
    @patch("shared.sql_review.SqlReviewConfig.from_env")
    def test_sql_review_rejection_preserves_compiler_sql(self, mock_config_from_env, mock_call_openrouter):
        mock_config_from_env.return_value = type(
            "Cfg",
            (),
            {
                "provider": "openrouter",
                "ollama_url": "",
                "ollama_model": "",
                "timeout_seconds": 5.0,
                "enabled": True,
            },
        )()
        mock_call_openrouter.return_value = (
            '{"status":"rejected","sql":"SELECT 1","reason_category":"alignment","notes":["bad alignment"]}'
        )

        generated_sql = (
            "SELECT city, SUM(total_population) AS sum_total_population "
            "FROM etl.population_distribution_csv GROUP BY city"
        )
        reviewed = review_and_correct_sql(
            question="show total population by city",
            schema=TEST_SCHEMA,
            generated_sql=generated_sql,
            validated_intent={
                "table": "population_distribution_csv",
                "metrics": [{"column": "total_population", "aggregation": "SUM", "alias": "sum_total_population"}],
                "dimensions": ["city"],
                "filters": [],
                "order_by": [],
                "limit": None,
            },
            extracted_intent={},
        )
        self.assertEqual(reviewed["status"], "approved")
        self.assertEqual(reviewed["reviewed_sql"], generated_sql)


if __name__ == "__main__":
    unittest.main()
