import unittest

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
