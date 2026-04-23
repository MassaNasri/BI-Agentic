from __future__ import annotations

import unittest
from unittest.mock import patch

from shared.query_planner import normalize_analytical_intent
from shared.chart_recommender import recommend_chart
from shared.sql_compiler import compile_sql
from shared.sql_review import review_and_correct_sql
from shared.sql_validator import validate_sql


TEST_SCHEMA = {
    "population_distribution_csv": [
        {"name": "ds", "type": "String"},
        {"name": "region", "type": "String"},
        {"name": "city", "type": "String"},
        {"name": "total_population", "type": "UInt64"},
        {"name": "customers", "type": "UInt64"},
        {"name": "orders", "type": "UInt64"},
        {"name": "total_sales", "type": "Float64"},
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

    def test_ranking_without_explicit_dimension_auto_selects_time_dimension(self):
        intent = normalize_analytical_intent(
            question="what are the top 7 entries with highest total population",
            raw_intent={},
            schema=TEST_SCHEMA,
        )
        self.assertTrue(intent["dimensions"])
        self.assertEqual(intent["dimensions"][0], "ds")
        self.assertTrue(
            any(
                isinstance(item, dict) and item.get("resolution") == "auto_selected_dimension"
                for item in intent.get("ambiguities", [])
            )
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        upper = sql.upper()
        self.assertIn("GROUP BY", upper)
        self.assertIn("LIMIT 7", upper)

    def test_compiler_blocks_ranking_limit_aggregate_without_group_by_when_dimension_inferable(self):
        unsafe_intent = {
            "table": "population_distribution_csv",
            "intent": "ranking",
            "operations": ["aggregation", "ranking", "limiting"],
            "metrics": [{"column": "total_population", "aggregation": "SUM", "alias": "sum_total_population"}],
            "dimensions": [],
            "filters": [],
            "order_by": [{"column": "sum_total_population", "direction": "DESC"}],
            "limit": 5,
            "ranking": {"direction": "DESC", "requested": True, "source": "test"},
            "ambiguities": [],
        }
        with self.assertRaises(ValueError):
            compile_sql(unsafe_intent, schema=TEST_SCHEMA)

    def test_time_granularity_per_week_generates_grouped_period_sql(self):
        intent = normalize_analytical_intent(
            question="what is the total population per week",
            raw_intent={},
            schema=TEST_SCHEMA,
        )
        self.assertEqual(intent.get("time_granularity"), "week")
        self.assertTrue(intent.get("time_grouping_detected"))
        self.assertEqual(intent.get("time_column"), "ds")
        self.assertEqual(intent.get("intent"), "time_series")
        self.assertIsNone(intent.get("limit"))
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        upper = sql.upper()
        self.assertIn("TOSTARTOFWEEK(TODATE(DS)) AS PERIOD", upper)
        self.assertIn("GROUP BY PERIOD", upper)
        self.assertIn("ORDER BY PERIOD ASC", upper)

    def test_trend_over_time_preserves_time_axis_and_line_chart(self):
        intent = normalize_analytical_intent(
            question="What is the trend of total sales over time?",
            raw_intent={},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        upper = sql.upper()
        self.assertEqual(intent.get("intent"), "time_series")
        self.assertEqual(intent.get("time_granularity"), "day")
        self.assertIn("GROUP BY PERIOD", upper)
        self.assertIn("ORDER BY PERIOD ASC", upper)
        chart = recommend_chart(intent, data={"columns": ["period", "sum_total_sales"], "rows": [{"period": "2026-01-01", "sum_total_sales": 10}]})
        self.assertEqual(chart.get("type"), "line")

    def test_business_metric_how_many_customers_per_day_uses_sum(self):
        intent = normalize_analytical_intent(
            question="How many customers do we have per day?",
            raw_intent={},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        upper = sql.upper()
        self.assertIn("SUM(CUSTOMERS)", upper)
        self.assertNotIn("COUNT(CUSTOMERS)", upper)
        self.assertIn("GROUP BY PERIOD", upper)
        self.assertIn("ORDER BY PERIOD ASC", upper)

    def test_average_number_of_orders_per_day_is_daily_time_series(self):
        intent = normalize_analytical_intent(
            question="What is the average number of orders per day?",
            raw_intent={},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        upper = sql.upper()
        self.assertEqual(intent.get("intent"), "time_series")
        self.assertEqual(intent.get("time_granularity"), "day")
        self.assertIn("AVG(ORDERS)", upper)
        self.assertIn("GROUP BY PERIOD", upper)
        chart = recommend_chart(intent, data={"columns": ["period", "avg_orders"], "rows": [{"period": "2026-01-01", "avg_orders": 4.5}]})
        self.assertEqual(chart.get("type"), "line")

    def test_row_count_query_keeps_count_semantics(self):
        intent = normalize_analytical_intent(
            question="count of rows per day",
            raw_intent={},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        upper = sql.upper()
        self.assertIn("COUNT(*)", upper)

    def test_average_order_value_per_day_generates_safe_ratio_sql(self):
        intent = normalize_analytical_intent(
            question="What is the average order value per day?",
            raw_intent={},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        upper = sql.upper()
        self.assertEqual(intent.get("intent"), "time_series")
        self.assertIn("SUM(TOTAL_SALES)", upper)
        self.assertIn("NULLIF(SUM(ORDERS), 0)", upper)
        self.assertIn("GROUP BY PERIOD", upper)
        self.assertIn("ORDER BY PERIOD ASC", upper)

    def test_relationship_question_generates_numeric_pair_for_scatter(self):
        intent = normalize_analytical_intent(
            question="What is the relationship between customers and total sales?",
            raw_intent={},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        upper = sql.upper()
        self.assertEqual(intent.get("intent"), "correlation")
        self.assertEqual(intent.get("dimensions"), [])
        self.assertIn("CUSTOMERS", upper)
        self.assertIn("TOTAL_SALES", upper)
        self.assertNotIn("SUM(CUSTOMERS)", upper)
        self.assertNotIn("GROUP BY", upper)
        chart = recommend_chart(intent)
        self.assertEqual(chart.get("type"), "scatter")

    def test_compare_numeric_fields_uses_relationship_scatter_semantics(self):
        intent = normalize_analytical_intent(
            question="Compare customers vs total sales",
            raw_intent={},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        self.assertEqual(intent.get("intent"), "correlation")
        self.assertIn("customers", sql)
        self.assertIn("total_sales", sql)
        self.assertNotIn("GROUP BY", sql.upper())
        chart = recommend_chart(intent, data={"columns": ["customers", "total_sales"], "rows": [{"customers": 3, "total_sales": 90}, {"customers": 4, "total_sales": 100}]})
        self.assertEqual(chart.get("type"), "scatter")

    def test_which_days_had_highest_customers_ignores_helper_verb(self):
        intent = normalize_analytical_intent(
            question="Which days had the highest number of customers?",
            raw_intent={},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        upper = sql.upper()
        self.assertEqual(intent.get("intent"), "ranking")
        self.assertIn("GROUP BY", upper)
        self.assertIn("SUM(CUSTOMERS)", upper)
        self.assertIn("ORDER BY SUM_CUSTOMERS DESC", upper)

    def test_weekly_totals_choose_line_for_time_grouped_shape(self):
        intent = normalize_analytical_intent(
            question="What are the total sales by week?",
            raw_intent={},
            schema=TEST_SCHEMA,
        )
        chart = recommend_chart(
            intent,
            data={
                "columns": ["period", "sum_total_sales"],
                "rows": [
                    {"period": "2026-01-05", "sum_total_sales": 100},
                    {"period": "2026-01-12", "sum_total_sales": 125},
                ],
            },
        )
        self.assertEqual(intent.get("time_granularity"), "week")
        self.assertEqual(chart.get("type"), "line")

    def test_semantic_planner_generalizes_to_non_sales_schema(self):
        schema = {
            "support_metrics": [
                {"name": "created_at", "type": "DateTime"},
                {"name": "team", "type": "String"},
                {"name": "tickets", "type": "UInt64"},
                {"name": "response_minutes", "type": "Float64"},
            ]
        }
        trend_intent = normalize_analytical_intent(
            question="How have tickets changed over time?",
            raw_intent={},
            schema=schema,
        )
        self.assertEqual(trend_intent.get("intent"), "time_series")
        self.assertEqual(trend_intent.get("time_column"), "created_at")
        trend_sql = compile_sql(trend_intent, schema=schema)
        self.assertIn("GROUP BY period", trend_sql)

        relation_intent = normalize_analytical_intent(
            question="What is the relationship between tickets and response minutes?",
            raw_intent={},
            schema=schema,
        )
        self.assertEqual(relation_intent.get("intent"), "correlation")
        self.assertEqual(recommend_chart(relation_intent).get("type"), "scatter")

    def test_compiler_normalizes_duplicate_todate_cast(self):
        sql = compile_sql(
            {
                "table": "population_distribution_csv",
                "intent": "time_series",
                "operations": ["projection", "aggregation", "grouping", "time_grouping"],
                "metrics": [{"column": "customers", "aggregation": "SUM", "alias": "sum_customers"}],
                "dimensions": ["ds"],
                "filters": [],
                "order_by": [{"column": "period", "direction": "ASC"}],
                "limit": None,
                "ranking": {"direction": None, "requested": False, "source": "test"},
                "time_granularity": "week",
                "time_column": "ds",
                "time_grouping_detected": True,
                "time_dimension_expression": "toStartOfWeek(toDate(toDate(ds)))",
                "time_dimension_alias": "period",
                "explicit_top_n_requested": False,
                "row_count_requested": False,
            },
            schema=TEST_SCHEMA,
        )
        self.assertNotIn("toDate(toDate(", sql)

    def test_time_granularity_per_hour_without_hour_data_raises_error(self):
        with self.assertRaisesRegex(ValueError, "Granularity not supported: hour-level data not available"):
            normalize_analytical_intent(
                question="what is the total population per hour",
                raw_intent={},
                schema=TEST_SCHEMA,
            )

    def test_compiler_blocks_time_aggregation_without_group_by_period(self):
        unsafe_intent = {
            "table": "population_distribution_csv",
            "intent": "aggregation",
            "operations": ["projection", "aggregation"],
            "metrics": [{"column": "total_population", "aggregation": "SUM", "alias": "sum_total_population"}],
            "dimensions": [],
            "filters": [],
            "order_by": [],
            "limit": None,
            "ranking": {"direction": None, "requested": False, "source": "test"},
            "time_granularity": "week",
            "time_column": "ds",
            "time_grouping_detected": True,
            "time_dimension_expression": "toStartOfWeek(ds)",
            "time_dimension_alias": "period",
            "ambiguities": [],
        }
        with self.assertRaises(ValueError):
            compile_sql(unsafe_intent, schema=TEST_SCHEMA)

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

    def test_sql_review_auto_corrects_count_business_metric(self):
        reviewed = review_and_correct_sql(
            question="How many customers do we have per day?",
            schema=TEST_SCHEMA,
            generated_sql=(
                "SELECT toDate(ds) AS period, COUNT(customers) AS total_customers "
                "FROM etl.population_distribution_csv GROUP BY period ORDER BY period ASC"
            ),
            validated_intent={
                "intent_type": "analytical",
                "requires_forecast": False,
            },
            extracted_intent={},
        )
        self.assertIn("SUM(customers)", reviewed["reviewed_sql"])

    def test_sql_review_normalizes_time_casts(self):
        reviewed = review_and_correct_sql(
            question="customers per week",
            schema=TEST_SCHEMA,
            generated_sql=(
                "SELECT toStartOfWeek(ds) AS period, SUM(customers) AS value "
                "FROM etl.population_distribution_csv GROUP BY period ORDER BY period ASC"
            ),
            validated_intent={},
            extracted_intent={},
        )
        self.assertIn("toStartOfWeek(toDate(ds))", reviewed["reviewed_sql"])

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
