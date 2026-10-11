import unittest
import sys
from pathlib import Path

AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
for path in (AI_SERVICE_ROOT, REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from shared.query_planner import normalize_analytical_intent
from shared.sql_compiler import compile_sql


TABLE_NAME = "etl.sales_3months_realistic_csv"
TEST_SCHEMA = {
    TABLE_NAME: [
        {"name": "ds", "type": "Date"},
        {"name": "orders", "type": "UInt32"},
        {"name": "customers", "type": "UInt32"},
        {"name": "total_sales", "type": "Float64"},
        {"name": "category", "type": "String"},
        {"name": "product", "type": "String"},
    ]
}


class BIGeneralizedSemanticsPipelineTests(unittest.TestCase):
    def _plan(self, question: str, raw_intent: dict | None = None) -> dict:
        payload = {"table": TABLE_NAME}
        if isinstance(raw_intent, dict):
            payload.update(raw_intent)
        return normalize_analytical_intent(
            question=question,
            raw_intent=payload,
            schema=TEST_SCHEMA,
        )

    def _sql(self, intent: dict) -> str:
        return compile_sql(intent, schema=TEST_SCHEMA)

    def test_orders_by_day_detects_time_grouping_and_sql_shape(self):
        intent = self._plan("Orders by day")
        sql = self._sql(intent)

        self.assertTrue(intent.get("time_grouping_detected"))
        self.assertEqual(intent.get("time_granularity"), "day")
        self.assertEqual(intent.get("time_grain_source"), "explicit")
        self.assertEqual(intent.get("detected_time_phrase"), "by day")
        self.assertIn("projection", intent.get("operations", []))
        self.assertIn("aggregation", intent.get("operations", []))
        self.assertIn("grouping", intent.get("operations", []))
        self.assertIn("time_grouping", intent.get("operations", []))
        self.assertIn("sorting", intent.get("operations", []))
        self.assertIn("toDate(ds) AS period", sql)
        self.assertIn("SUM(orders) AS sum_orders", sql)
        self.assertIn("GROUP BY period", sql)
        self.assertIn("ORDER BY period ASC", sql)

    def test_total_sales_by_month_groups_and_orders_by_period(self):
        intent = self._plan("Total sales by month")
        sql = self._sql(intent)

        self.assertTrue(intent.get("time_grouping_detected"))
        self.assertEqual(intent.get("time_granularity"), "month")
        self.assertIn("toStartOfMonth(toDate(ds)) AS period", sql)
        self.assertIn("SUM(total_sales) AS sum_total_sales", sql)
        self.assertIn("GROUP BY period", sql)
        self.assertIn("ORDER BY period ASC", sql)

    def test_highest_month_sales_uses_desc_and_limit_one(self):
        intent = self._plan("What month generated the highest total sales?")
        sql = self._sql(intent)

        self.assertTrue(intent.get("time_grouping_detected"))
        self.assertEqual(intent.get("time_granularity"), "month")
        self.assertIn("toStartOfMonth(toDate(ds)) AS period", sql)
        self.assertIn("SUM(total_sales) AS sum_total_sales", sql)
        self.assertIn("GROUP BY period", sql)
        self.assertIn("ORDER BY sum_total_sales DESC", sql)
        self.assertIn("LIMIT 1", sql)

    def test_compare_two_metrics_over_time_keeps_both_metrics(self):
        intent = self._plan("Compare sales and customers over time")
        sql = self._sql(intent)

        metric_columns = [str(metric.get("column")) for metric in intent.get("metrics", []) if isinstance(metric, dict)]
        self.assertIn("total_sales", metric_columns)
        self.assertIn("customers", metric_columns)
        self.assertEqual(intent.get("time_grain_source"), "default")
        self.assertIn("GROUP BY period", sql)
        self.assertIn("SUM(total_sales) AS sum_total_sales", sql)
        self.assertIn("SUM(customers) AS sum_customers", sql)
        self.assertIn("ORDER BY period ASC", sql)

    def test_relationship_between_numeric_measures_stays_projection(self):
        intent = self._plan("Relationship between total_sales and customers")
        sql = self._sql(intent)

        self.assertEqual(intent.get("analysis_mode"), "relationship")
        self.assertIn("SELECT total_sales,", sql)
        self.assertIn("customers", sql)
        self.assertNotIn("GROUP BY", sql)
        self.assertNotIn("SUM(", sql)

    def test_customers_above_50_preserves_locked_metric_and_filter(self):
        intent = self._plan(
            "Customers above 50",
            raw_intent={
                "metrics": [{"column": "total_sales"}],
                "selected_columns_preprocessing_high": ["customers"],
            },
        )
        sql = self._sql(intent)

        metric_columns = [str(metric.get("column")) for metric in intent.get("metrics", []) if isinstance(metric, dict)]
        self.assertIn("customers", metric_columns)
        self.assertNotIn("total_sales", metric_columns)
        self.assertTrue(any(str(f.get("column")) == "customers" and str(f.get("operator")) == ">" for f in intent.get("filters", [])))
        self.assertTrue(any("above" in str(f.get("source_text", "")).lower() for f in intent.get("filters", [])))
        self.assertEqual(intent.get("filter_source"), "numeric_pattern")
        self.assertIn("WHERE customers > 50", sql)
        self.assertIn("SELECT customers", sql)

    def test_orders_below_20_keeps_numeric_filter(self):
        intent = self._plan("Orders below 20")
        sql = self._sql(intent)

        self.assertTrue(any(str(f.get("column")) == "orders" and str(f.get("operator")) == "<" for f in intent.get("filters", [])))
        self.assertIn("WHERE orders < 20", sql)
        self.assertIn("SELECT orders", sql)

    def test_between_filter_compiles_to_between_clause(self):
        intent = self._plan("Customers between 20 and 50")
        sql = self._sql(intent)

        self.assertTrue(any(str(f.get("operator")) == "BETWEEN" for f in intent.get("filters", [])))
        self.assertIn("WHERE customers BETWEEN 20 AND 50", sql)

    def test_distribution_of_total_sales_uses_binned_sql(self):
        intent = self._plan("Distribution of total sales")
        sql = self._sql(intent)

        self.assertEqual(intent.get("intent"), "distribution")
        self.assertIn("AS bin_start", sql)
        self.assertIn("COUNT() AS frequency", sql)
        self.assertIn("GROUP BY bin_start", sql)
        self.assertIn("ORDER BY bin_start ASC", sql)

    def test_sales_by_category_uses_grouped_bar_sql_shape(self):
        intent = self._plan("Sales by category")
        sql = self._sql(intent)

        self.assertIn("category", intent.get("dimensions", []))
        self.assertIn("SUM(total_sales) AS sum_total_sales", sql)
        self.assertIn("GROUP BY category", sql)

    def test_top_5_products_by_sales_orders_desc_and_limits(self):
        intent = self._plan("Top 5 products by sales")
        sql = self._sql(intent)

        self.assertIn("product", intent.get("dimensions", []))
        self.assertIn("SUM(total_sales) AS sum_total_sales", sql)
        self.assertIn("GROUP BY product", sql)
        self.assertIn("ORDER BY sum_total_sales DESC", sql)
        self.assertIn("LIMIT 5", sql)


    def test_compare_metrics_over_time_order_invariant(self):
        """Both metric orderings must produce equivalent time-series plans."""
        intent_a = self._plan("Compare sales and customers over time")
        intent_b = self._plan("Compare customers and sales over time")

        self.assertTrue(intent_a.get("time_grouping_detected"))
        self.assertTrue(intent_b.get("time_grouping_detected"))
        self.assertEqual(intent_a.get("intent"), intent_b.get("intent"))
        self.assertEqual(intent_a.get("time_granularity"), intent_b.get("time_granularity"))
        self.assertEqual(intent_a.get("analysis_mode"), intent_b.get("analysis_mode"))
        # Both should have same metric set (order may differ)
        metrics_a = sorted(m.get("column") for m in intent_a.get("metrics", []))
        metrics_b = sorted(m.get("column") for m in intent_b.get("metrics", []))
        self.assertEqual(metrics_a, metrics_b)

        sql_a = self._sql(intent_a)
        sql_b = self._sql(intent_b)
        # Both must have GROUP BY period, not scatter
        self.assertIn("GROUP BY period", sql_a)
        self.assertIn("GROUP BY period", sql_b)
        self.assertNotIn("scatter", intent_a.get("analysis_mode", ""))
        self.assertNotIn("scatter", intent_b.get("analysis_mode", ""))

    def test_compare_over_time_not_scatter(self):
        """'Compare X and Y over time' must not produce scatter/relationship."""
        intent = self._plan("Compare sales and customers over time")
        self.assertNotEqual(intent.get("analysis_mode"), "relationship")
        self.assertNotEqual(intent.get("intent"), "correlation")
        self.assertNotIn("relationship", intent.get("operations", []))

    def test_relationship_without_temporal_stays_scatter(self):
        """Without temporal phrase, relationship between metrics -> scatter."""
        intent = self._plan("Relationship between total_sales and customers")
        self.assertEqual(intent.get("analysis_mode"), "relationship")
        self.assertEqual(intent.get("intent"), "correlation")
        self.assertIn("relationship", intent.get("operations", []))
        self.assertFalse(intent.get("time_grouping_detected"))

    def test_highest_month_produces_ranking_with_limit(self):
        """'highest' must trigger ranking DESC LIMIT 1."""
        intent = self._plan("What month generated the highest total sales?")
        self.assertEqual(intent["ranking"]["direction"], "DESC")
        self.assertTrue(intent["ranking"]["requested"])
        self.assertEqual(intent["limit"], 1)
        self.assertIn("ranking", intent.get("operations", []))
        self.assertIn("limiting", intent.get("operations", []))

    def test_orders_below_20_filter_preserved_even_with_bad_llm(self):
        """Filter detection must work even with empty raw_intent from LLM."""
        intent = self._plan(
            "Orders below 20",
            raw_intent={"metrics": [], "filters": [], "operations": ["projection"]},
        )
        sql = self._sql(intent)
        self.assertTrue(any(
            f.get("column") == "orders" and f.get("operator") == "<" and f.get("value") == 20
            for f in intent.get("filters", [])
        ))
        self.assertIn("WHERE orders < 20", sql)

    def test_orders_by_day_time_grain_explicit(self):
        """'by day' must produce explicit time grain."""
        intent = self._plan("Orders by day")
        self.assertTrue(intent.get("time_grouping_detected"))
        self.assertEqual(intent.get("time_granularity"), "day")
        self.assertEqual(intent.get("time_grain_source"), "explicit")

    def test_semantic_plan_has_required_fields(self):
        """Every normalized intent must have core SemanticQueryPlan fields."""
        intent = self._plan("Compare sales and customers over time")
        required_keys = [
            "intent_type", "table", "intent", "operations", "dimensions",
            "metrics", "filters", "ranking", "order_by", "limit",
            "time_granularity", "time_grain_source", "time_grouping_detected",
        ]
        for key in required_keys:
            self.assertIn(key, intent, f"Missing key: {key}")


    def test_metric_order_invariance_full_equivalence(self):
        """
        'Compare sales and customers over time' and
        'Compare customers and sales over time'
        must produce fully equivalent semantic plans, SQL shape, and chart family.
        Neither may produce scatter or relationship.
        """
        intent_a = self._plan("Compare sales and customers over time")
        intent_b = self._plan("Compare customers and sales over time")

        self.assertTrue(intent_a.get("time_grouping_detected"), "Q1 must have time_grouping")
        self.assertTrue(intent_b.get("time_grouping_detected"), "Q2 must have time_grouping")

        self.assertEqual(intent_a["intent"], intent_b["intent"])
        self.assertEqual(intent_a["time_granularity"], intent_b["time_granularity"])
        self.assertEqual(intent_a.get("analysis_mode", ""), intent_b.get("analysis_mode", ""))

        metrics_a = sorted(m.get("column") for m in intent_a.get("metrics", []))
        metrics_b = sorted(m.get("column") for m in intent_b.get("metrics", []))
        self.assertEqual(metrics_a, metrics_b)
        self.assertIn("total_sales", metrics_a)
        self.assertIn("customers", metrics_a)

        ops_a = set(intent_a.get("operations", []))
        ops_b = set(intent_b.get("operations", []))
        self.assertEqual(ops_a, ops_b)
        for required_op in ("aggregation", "grouping", "sorting", "time_grouping"):
            self.assertIn(required_op, ops_a, f"Q1 missing {required_op}")
            self.assertIn(required_op, ops_b, f"Q2 missing {required_op}")
        self.assertNotIn("relationship", ops_a)
        self.assertNotIn("relationship", ops_b)

        sql_a = self._sql(intent_a)
        sql_b = self._sql(intent_b)
        for sql_label, sql in (("Q1", sql_a), ("Q2", sql_b)):
            self.assertIn("toDate(ds) AS period", sql, f"{sql_label} missing toDate(ds)")
            self.assertIn("SUM(total_sales)", sql, f"{sql_label} missing SUM(total_sales)")
            self.assertIn("SUM(customers)", sql, f"{sql_label} missing SUM(customers)")
            self.assertIn("GROUP BY period", sql, f"{sql_label} missing GROUP BY")
            self.assertIn("ORDER BY period ASC", sql, f"{sql_label} missing ORDER BY")

    def test_relationship_without_temporal_still_scatter(self):
        """
        'Relationship between sales and customers' (no temporal phrase)
        must remain scatter/relationship — the temporal override must NOT
        suppress explicit relationship semantics.
        """
        intent = self._plan("Relationship between total_sales and customers")
        self.assertEqual(intent.get("analysis_mode"), "relationship")
        self.assertEqual(intent.get("intent"), "correlation")
        self.assertFalse(intent.get("time_grouping_detected"))
        self.assertIn("relationship", intent.get("operations", []))

        sql = self._sql(intent)
        self.assertNotIn("GROUP BY", sql)
        self.assertNotIn("SUM(", sql)


if __name__ == "__main__":
    unittest.main()
