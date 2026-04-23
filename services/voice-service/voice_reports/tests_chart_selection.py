import unittest

from voice_reports.constants import ChartType
from voice_reports.utils import extract_upstream_chart_type, infer_chart_type


class ChartSelectionTests(unittest.TestCase):
    def test_time_series_aov_prefers_line(self):
        columns = ["period", "average_order_value"]
        rows = [
            {"period": "2026-01-01", "average_order_value": 12.1},
            {"period": "2026-01-02", "average_order_value": 14.0},
        ]
        intent = {
            "intent": "time_series",
            "time_grouping_detected": True,
            "operations": ["projection", "aggregation", "grouping", "time_grouping"],
        }
        self.assertEqual(
            infer_chart_type(columns=columns, rows=rows, intent=intent),
            ChartType.LINE,
        )

    def test_time_like_shape_prefers_line_without_time_intent(self):
        columns = ["period", "average_order_value"]
        rows = [
            {"period": "2026-01-01", "average_order_value": 12.1},
            {"period": "2026-01-02", "average_order_value": 14.0},
        ]
        intent = {"intent": "aggregation", "operations": ["projection", "aggregation"]}
        self.assertEqual(
            infer_chart_type(columns=columns, rows=rows, intent=intent),
            ChartType.LINE,
        )

    def test_relationship_prefers_scatter(self):
        columns = ["customers", "total_sales"]
        rows = [
            {"customers": 10, "total_sales": 120.0},
            {"customers": 30, "total_sales": 350.0},
        ]
        intent = {
            "intent": "correlation",
            "analysis_mode": "relationship",
            "operations": ["projection", "comparison", "relationship"],
        }
        self.assertEqual(
            infer_chart_type(columns=columns, rows=rows, intent=intent),
            ChartType.SCATTER,
        )

    def test_time_series_with_column_metadata_prefers_line(self):
        columns = [
            {"name": "period", "type": "Date"},
            {"name": "average_order_value", "type": "Float64"},
        ]
        rows = [
            {"period": "2026-01-01", "average_order_value": 12.1},
            {"period": "2026-01-02", "average_order_value": 14.0},
        ]
        intent = {"intent": "time_series", "operations": ["time_grouping"], "time_grouping_detected": True}
        self.assertEqual(
            infer_chart_type(columns=columns, rows=rows, intent=intent),
            ChartType.LINE,
        )

    def test_relationship_with_column_metadata_prefers_scatter(self):
        columns = [
            {"name": "customers", "type": "UInt32"},
            {"name": "total_sales", "type": "Float64"},
        ]
        rows = [
            {"customers": 10, "total_sales": 120.0},
            {"customers": 30, "total_sales": 350.0},
        ]
        intent = {"intent": "correlation", "analysis_mode": "relationship", "operations": ["relationship"]}
        self.assertEqual(
            infer_chart_type(columns=columns, rows=rows, intent=intent),
            ChartType.SCATTER,
        )

    def test_single_value_prefers_card(self):
        columns = ["sum_total_sales"]
        rows = [{"sum_total_sales": 1200.0}]
        intent = {"intent": "aggregation", "operations": ["projection", "aggregation"]}
        self.assertEqual(
            infer_chart_type(columns=columns, rows=rows, intent=intent),
            ChartType.CARD,
        )

    def test_single_numeric_series_prefers_histogram(self):
        columns = ["orders"]
        rows = [{"orders": 10}, {"orders": 12}, {"orders": 20}]
        intent = {"intent": "distribution", "operations": ["projection", "distribution"]}
        self.assertEqual(
            infer_chart_type(columns=columns, rows=rows, intent=intent),
            ChartType.HISTOGRAM,
        )

    def test_category_comparison_prefers_bar(self):
        columns = ["category", "sum_total_sales"]
        rows = [
            {"category": "A", "sum_total_sales": 100.0},
            {"category": "B", "sum_total_sales": 50.0},
        ]
        intent = {"intent": "ranking", "operations": ["projection", "aggregation", "grouping", "ranking"]}
        self.assertEqual(
            infer_chart_type(columns=columns, rows=rows, intent=intent),
            ChartType.BAR,
        )

    def test_global_shape_rules_cover_required_analytical_charts(self):
        cases = [
            (
                ["period", "value"],
                [{"period": "2026-01-01", "value": 1}, {"period": "2026-01-02", "value": 2}],
                {"intent": "time_series", "time_grouping_detected": True},
                ChartType.LINE,
            ),
            (
                ["x", "y"],
                [{"x": 1, "y": 2}, {"x": 2, "y": 4}],
                {"intent": "correlation", "analysis_mode": "relationship"},
                ChartType.SCATTER,
            ),
            (
                ["region", "sales"],
                [{"region": "north", "sales": 10}, {"region": "south", "sales": 20}],
                {"intent": "ranking", "operations": ["grouping", "aggregation"]},
                ChartType.BAR,
            ),
            (
                ["total_sales"],
                [{"total_sales": 30}],
                {"intent": "aggregation"},
                ChartType.CARD,
            ),
        ]
        for columns, rows, intent, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    infer_chart_type(columns=columns, rows=rows, intent=intent),
                    expected,
                )

    def test_invalid_scatter_falls_back_to_bar(self):
        columns = ["region", "sum_total_sales"]
        rows = [
            {"region": "north", "sum_total_sales": 120.0},
            {"region": "south", "sum_total_sales": 90.0},
        ]
        intent = {"intent": "correlation", "analysis_mode": "relationship", "operations": ["relationship"]}
        self.assertEqual(
            infer_chart_type(
                columns=columns,
                rows=rows,
                intent=intent,
                preferred_chart_type="scatter",
            ),
            ChartType.BAR,
        )

    def test_upstream_chart_propagation_when_valid(self):
        columns = ["period", "value"]
        rows = [
            {"period": "2026-01-01", "value": 1.0},
            {"period": "2026-01-02", "value": 2.0},
        ]
        intent = {"intent": "time_series", "time_grouping_detected": True}
        self.assertEqual(
            infer_chart_type(
                columns=columns,
                rows=rows,
                intent=intent,
                preferred_chart_type="line",
            ),
            ChartType.LINE,
        )

    def test_extract_upstream_chart_from_trace(self):
        pipeline_trace = {
            "visualization": {
                "final_output": {
                    "selected_chart_type": "scatter",
                }
            }
        }
        self.assertEqual(
            extract_upstream_chart_type(chart_config={}, pipeline_trace=pipeline_trace),
            ChartType.SCATTER,
        )

    def test_trace_chart_precedence_over_upstream_payload(self):
        pipeline_trace = {
            "visualization": {
                "final_output": {
                    "selected_chart_type": "line",
                }
            }
        }
        chart_config = {
            "upstream_chart": {"type": "bar"},
        }
        self.assertEqual(
            extract_upstream_chart_type(chart_config=chart_config, pipeline_trace=pipeline_trace),
            ChartType.LINE,
        )

    def test_extract_upstream_chart_from_payload_selected_type(self):
        chart_config = {
            "upstream_chart": {"selected_chart_type": "scatter"},
        }
        self.assertEqual(
            extract_upstream_chart_type(chart_config=chart_config, pipeline_trace={}),
            ChartType.SCATTER,
        )

    def test_extract_upstream_chart_prefers_chart_type_over_legacy_type(self):
        chart_config = {
            "upstream_chart": {"type": "table", "chart_type": "line"},
        }
        self.assertEqual(
            extract_upstream_chart_type(chart_config=chart_config, pipeline_trace={}),
            ChartType.LINE,
        )


if __name__ == "__main__":
    unittest.main()
