import unittest

from voice_reports.utils import normalize_sql_table_references, normalize_table_name


class TableNameNormalizationTests(unittest.TestCase):
    def test_normalize_unqualified(self):
        self.assertEqual(
            normalize_table_name("population_distribution_csv", "etl"),
            "etl.population_distribution_csv",
        )

    def test_normalize_qualified_same_db(self):
        self.assertEqual(
            normalize_table_name("etl.population_distribution_csv", "etl"),
            "etl.population_distribution_csv",
        )

    def test_normalize_qualified_other_db(self):
        self.assertEqual(
            normalize_table_name("analytics.population_distribution_csv", "etl"),
            "analytics.population_distribution_csv",
        )

    def test_normalize_multi_dot_duplicate_db(self):
        self.assertEqual(
            normalize_table_name("etl.etl.population_distribution_csv", "etl"),
            "etl.population_distribution_csv",
        )

    def test_normalize_sql_references(self):
        sql = (
            "SELECT region, SUM(total_population) AS sum_total_population "
            "FROM etl.etl.population_distribution_csv "
            "GROUP BY region"
        )
        normalized = normalize_sql_table_references(sql, "etl")
        self.assertIn("FROM etl.population_distribution_csv", normalized)
        self.assertNotIn("etl.etl.population_distribution_csv", normalized)

if __name__ == "__main__":
    unittest.main()
