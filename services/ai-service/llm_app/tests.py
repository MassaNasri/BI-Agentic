import unittest

from intent_extraction.routing import _build_query_builder_payload
from shared.query_planner import normalize_analytical_intent
from shared.sql_compiler import compile_sql
from shared.schema_utils import normalize_table_name


TEST_SCHEMA = {
    "population_distribution_csv": [
        {"name": "region", "type": "String", "is_numeric": False, "is_date": False, "is_dimension": True},
        {"name": "city", "type": "String", "is_numeric": False, "is_date": False, "is_dimension": True},
        {"name": "total_population", "type": "Float64", "is_numeric": True, "is_date": False, "is_dimension": False},
        {"name": "age", "type": "Float64", "is_numeric": True, "is_date": False, "is_dimension": False},
        {"name": "employment_rate", "type": "Float64", "is_numeric": True, "is_date": False, "is_dimension": False},
    ]
}


class DeterministicPlannerTests(unittest.TestCase):
    def test_highest_population(self):
        question = "Which region has the highest population?"
        raw_intent = {
            "table": "population_distribution_csv",
            "metrics": [{"column": "total_population", "aggregation": "MAX", "alias": "wrong"}],
            "dimensions": ["region"],
            "filters": [],
            "order_by": [],
            "limit": None,
        }
        intent = normalize_analytical_intent(question=question, raw_intent=raw_intent, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)

        self.assertEqual(intent["table"], "population_distribution_csv")
        self.assertEqual(intent["metrics"][0]["aggregation"], "SUM")
        self.assertEqual(intent["order_by"][0]["direction"], "DESC")
        self.assertEqual(intent["limit"], 1)
        self.assertIn("SUM(total_population) AS sum_total_population", sql)
        self.assertIn("GROUP BY region", sql)
        self.assertIn("ORDER BY sum_total_population DESC", sql)
        self.assertIn("LIMIT 1", sql)

    def test_average_age_per_region(self):
        question = "What is the average age per region?"
        raw_intent = {
            "table": "population_distribution_csv",
            "metrics": [{"column": "age", "aggregation": "SUM", "alias": None}],
            "dimensions": [],
            "filters": [],
            "order_by": [],
            "limit": None,
        }
        intent = normalize_analytical_intent(question=question, raw_intent=raw_intent, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)

        self.assertEqual(intent["metrics"][0]["aggregation"], "AVG")
        self.assertEqual(intent["dimensions"], ["region"])
        self.assertIn("AVG(age) AS avg_age", sql)
        self.assertIn("GROUP BY region", sql)

    def test_employment_rate_by_city_uses_projection_not_sum(self):
        question = "Show employment rate by city"
        raw_intent = {
            "table": "population_distribution_csv",
            "metrics": [{"column": "employment_rate", "aggregation": "SUM", "alias": None}],
            "dimensions": [],
            "filters": [],
            "order_by": [],
            "limit": None,
        }
        intent = normalize_analytical_intent(question=question, raw_intent=raw_intent, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)

        self.assertIsNone(intent["metrics"][0]["aggregation"])
        self.assertEqual(intent["dimensions"], ["city"])
        self.assertIn("employment_rate", sql)
        self.assertNotIn("SUM(employment_rate)", sql)
        self.assertNotIn("GROUP BY", sql)

    def test_count_cities_per_region(self):
        question = "How many cities are in each region?"
        raw_intent = {
            "table": "population_distribution_csv",
            "metrics": [],
            "dimensions": ["region"],
            "filters": [],
            "order_by": [],
            "limit": None,
        }
        intent = normalize_analytical_intent(question=question, raw_intent=raw_intent, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)

        self.assertEqual(intent["metrics"][0]["aggregation"], "COUNT")
        self.assertEqual(intent["metrics"][0]["column"], "city")
        self.assertIn("COUNT(city) AS count_city", sql)
        self.assertIn("GROUP BY region", sql)

    def test_lowest_employment_rate(self):
        question = "What region has the lowest employment rate?"
        raw_intent = {
            "table": "population_distribution_csv",
            "metrics": [{"column": "employment_rate", "aggregation": "MAX", "alias": None}],
            "dimensions": [],
            "filters": [],
            "order_by": [],
            "limit": None,
        }
        intent = normalize_analytical_intent(question=question, raw_intent=raw_intent, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)

        self.assertEqual(intent["metrics"][0]["aggregation"], "AVG")
        self.assertEqual(intent["dimensions"], ["region"])
        self.assertEqual(intent["order_by"][0]["direction"], "ASC")
        self.assertEqual(intent["limit"], 1)
        self.assertIn("AVG(employment_rate) AS avg_employment_rate", sql)
        self.assertIn("ORDER BY avg_employment_rate ASC", sql)

    def test_multiple_requested_metrics_are_preserved(self):
        question = "Show male and female population by region"
        schema = {
            "population_distribution_csv": [
                {"name": "region", "type": "String", "is_numeric": False, "is_date": False, "is_dimension": True},
                {"name": "male_population", "type": "Float64", "is_numeric": True, "is_date": False, "is_dimension": False},
                {"name": "female_population", "type": "Float64", "is_numeric": True, "is_date": False, "is_dimension": False},
            ]
        }
        intent = normalize_analytical_intent(question=question, raw_intent={}, schema=schema)
        sql = compile_sql(intent, schema=schema)

        metric_columns = [metric["column"] for metric in intent["metrics"]]
        self.assertEqual(metric_columns, ["male_population", "female_population"])
        self.assertIn("SUM(male_population) AS sum_male_population", sql)
        self.assertIn("SUM(female_population) AS sum_female_population", sql)
        self.assertIn("GROUP BY region", sql)

    def test_highest_population_city_ranking_without_top_keyword(self):
        question = "Show the city with the highest population"
        intent = normalize_analytical_intent(
            question=question,
            raw_intent={"table": "population_distribution_csv"},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)

        self.assertEqual(intent["dimensions"], ["city"])
        self.assertEqual(intent["order_by"][0]["direction"], "DESC")
        self.assertEqual(intent["limit"], 1)
        self.assertIn("ORDER BY sum_total_population DESC", sql)
        self.assertIn("LIMIT 1", sql)

    def test_lowest_average_age_with_explicit_limit(self):
        question = "Show the 2 regions with the lowest average age"
        intent = normalize_analytical_intent(
            question=question,
            raw_intent={"table": "population_distribution_csv"},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)

        self.assertEqual(intent["limit"], 2)
        self.assertEqual(intent["order_by"][0]["direction"], "ASC")
        self.assertIn("AVG(age) AS avg_age", sql)
        self.assertIn("ORDER BY avg_age ASC", sql)
        self.assertIn("LIMIT 2", sql)

    def test_text_filter_is_parsed_into_where_clause(self):
        question = "Show cities in the North region"
        intent = normalize_analytical_intent(
            question=question,
            raw_intent={"table": "population_distribution_csv"},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)

        self.assertTrue(any(flt["column"] == "region" for flt in intent["filters"]))
        self.assertIn("WHERE region = 'north'", sql)

    def test_numeric_filter_and_projection_combined(self):
        question = "Show total population for cities where employment rate is above 55"
        intent = normalize_analytical_intent(
            question=question,
            raw_intent={"table": "population_distribution_csv"},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)

        self.assertTrue(any(flt["column"] == "employment_rate" and flt["operator"] == ">" for flt in intent["filters"]))
        self.assertIn("WHERE employment_rate > 55", sql)
        self.assertIn("total_population", sql)

    def test_full_sql_generation_highest_population(self):
        question = "Which region has the highest population?"
        raw_intent = {
            "table": "etl.population_distribution_csv",
            "metrics": [{"column": "total_population", "aggregation": "MAX", "alias": None}],
            "dimensions": ["region"],
            "filters": [],
            "order_by": [],
            "limit": None,
        }
        intent = normalize_analytical_intent(question=question, raw_intent=raw_intent, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)

        expected_sql = (
            "SELECT region,\n"
            "       SUM(total_population) AS sum_total_population\n"
            "FROM etl.population_distribution_csv\n"
            "GROUP BY region\n"
            "ORDER BY sum_total_population DESC\n"
            "LIMIT 1;"
        )
        self.assertEqual(sql, expected_sql)

    def test_sql_compiler_repairs_duplicate_db_prefix(self):
        intent = {
            "table": "etl.etl.population_distribution_csv",
            "metrics": [{"column": "total_population", "aggregation": "SUM", "alias": "sum_total_population"}],
            "dimensions": ["region"],
            "filters": [],
            "order_by": [{"column": "sum_total_population", "direction": "DESC"}],
            "limit": 1,
        }
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        self.assertIn("FROM etl.population_distribution_csv", sql)
        self.assertNotIn("etl.etl.population_distribution_csv", sql)

    def test_table_resolution_avoids_technical_table_when_business_match_exists(self):
        schema = {
            "population_distribution_csv": [
                {"name": "city", "type": "String", "is_numeric": False, "is_date": False, "is_dimension": True},
                {"name": "total_population", "type": "Float64", "is_numeric": True, "is_date": False, "is_dimension": False},
            ],
            "population_distribution_csv_log": [
                {"name": "city", "type": "String", "is_numeric": False, "is_date": False, "is_dimension": True},
                {"name": "total_population", "type": "Float64", "is_numeric": True, "is_date": False, "is_dimension": False},
            ],
        }
        intent = normalize_analytical_intent(
            question="show total population by city",
            raw_intent={},
            schema=schema,
        )
        self.assertEqual(intent["table"], "population_distribution_csv")

    def test_semantic_ir_contains_operations_and_primary_intent(self):
        intent = normalize_analytical_intent(
            question="show top 3 cities by total population where employment rate is above 55",
            raw_intent={"table": "population_distribution_csv"},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)

        self.assertIn("intent", intent)
        self.assertIn("operations", intent)
        self.assertIn("ranking", intent)
        self.assertIn("filtering", intent["operations"])
        self.assertIn("aggregation", intent["operations"])
        self.assertEqual(intent["intent"], "ranking")
        self.assertIn("ORDER BY", sql)
        self.assertIn("LIMIT 3", sql)

    def test_raw_metric_specs_support_multi_metric_semantics(self):
        question = "Compare male and female population by region"
        schema = {
            "population_distribution_csv": [
                {"name": "region", "type": "String", "is_numeric": False, "is_date": False, "is_dimension": True},
                {"name": "male_population", "type": "Float64", "is_numeric": True, "is_date": False, "is_dimension": False},
                {"name": "female_population", "type": "Float64", "is_numeric": True, "is_date": False, "is_dimension": False},
            ]
        }
        raw_intent = {
            "table": "population_distribution_csv",
            "metric_specs": [
                {"column": "male_population", "aggregation": "SUM"},
                {"column": "female_population", "aggregation": "SUM"},
            ],
            "dimensions": ["region"],
        }
        intent = normalize_analytical_intent(question=question, raw_intent=raw_intent, schema=schema)
        sql = compile_sql(intent, schema=schema)

        metric_columns = [m["column"] for m in intent["metrics"]]
        self.assertEqual(metric_columns, ["male_population", "female_population"])
        self.assertIn("SUM(male_population) AS sum_male_population", sql)
        self.assertIn("SUM(female_population) AS sum_female_population", sql)
        self.assertIn("comparison", intent["operations"])

    def test_dimension_inference_marks_ambiguity(self):
        intent = normalize_analytical_intent(
            question="show top 3 by total population",
            raw_intent={"table": "population_distribution_csv"},
            schema=TEST_SCHEMA,
        )
        ambiguity_types = [item.get("type") for item in intent.get("ambiguities", []) if isinstance(item, dict)]
        self.assertIn("dimension_inference", ambiguity_types)
        self.assertTrue(intent["dimensions"])

    def test_between_filter_from_ir_is_compiled(self):
        intent = {
            "table": "population_distribution_csv",
            "metrics": [{"column": "total_population", "aggregation": "SUM", "alias": "sum_total_population"}],
            "dimensions": ["region"],
            "filters": [{"column": "age", "operator": "BETWEEN", "value": [18, 65]}],
            "order_by": [{"column": "sum_total_population", "direction": "DESC"}],
            "limit": 5,
        }
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        self.assertIn("WHERE age BETWEEN 18 AND 65", sql)

    def test_order_by_unknown_column_raises_error(self):
        intent = {
            "table": "population_distribution_csv",
            "metrics": [{"column": "total_population", "aggregation": "SUM", "alias": "sum_total_population"}],
            "dimensions": ["region"],
            "filters": [],
            "order_by": [{"column": "nonexistent_metric_alias", "direction": "DESC"}],
            "limit": 5,
        }
        with self.assertRaises(ValueError):
            compile_sql(intent, schema=TEST_SCHEMA)

    def test_routing_payload_preserves_metric_spec_aggregations(self):
        structured_intent = {
            "intent_type": "analytical",
            "metrics": [],
            "metric_specs": [
                {"column": "total_population", "aggregation": "SUM", "alias": "sum_total_population"},
                {"column": "age", "aggregation": "AVG", "alias": "avg_age"},
            ],
            "dimensions": ["region"],
            "filters": [],
            "time_range": "all_time",
            "aggregation": "SUM",
            "target_column": "total_population",
            "table": "population_distribution_csv",
            "order_by": [{"column": "sum_total_population", "direction": "DESC"}],
            "limit": 10,
            "ranking": {"direction": "DESC"},
            "operations": ["aggregation", "grouping", "ranking", "limiting"],
            "ambiguities": [],
        }
        payload = _build_query_builder_payload(structured_intent)
        self.assertEqual(payload["metric_specs"][0]["aggregation"], "SUM")
        self.assertEqual(payload["metric_specs"][1]["aggregation"], "AVG")


class TableNameNormalizationTests(unittest.TestCase):
    def test_normalize_unqualified_table(self):
        self.assertEqual(
            normalize_table_name("population_distribution_csv", "etl"),
            "etl.population_distribution_csv",
        )

    def test_normalize_already_qualified_default_db(self):
        self.assertEqual(
            normalize_table_name("etl.population_distribution_csv", "etl"),
            "etl.population_distribution_csv",
        )

    def test_normalize_already_qualified_other_db(self):
        self.assertEqual(
            normalize_table_name("analytics.population_distribution_csv", "etl"),
            "analytics.population_distribution_csv",
        )

    def test_normalize_duplicate_db_prefix(self):
        self.assertEqual(
            normalize_table_name("etl.etl.population_distribution_csv", "etl"),
            "etl.population_distribution_csv",
        )
