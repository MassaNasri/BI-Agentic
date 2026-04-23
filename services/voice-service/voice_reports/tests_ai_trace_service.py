import unittest
import sys
import types

if "clickhouse_connect" not in sys.modules:
    sys.modules["clickhouse_connect"] = types.SimpleNamespace(get_client=lambda **_kwargs: None)
if "jwt" not in sys.modules:
    sys.modules["jwt"] = types.SimpleNamespace(encode=lambda *_args, **_kwargs: "")

from voice_reports.services.ai_trace_service import build_ai_trace_payload


class AITraceServiceTests(unittest.TestCase):
    def test_classification_error_is_cleared_when_preprocessing_high_succeeds_with_corrections(self):
        trace = build_ai_trace_payload(
            report_id=10,
            transcription="How do customers impact totol sales?",
            preprocessing_low={"cleaned_text": "How do customers impact totol sales?"},
            preprocessing_high={
                "status": "success",
                "final_query": "How do customers relationship total sales?",
                "term_corrections": [{"from": "totol", "to": "total_sales", "type": "fuzzy_phrase"}],
                "user_friendly_messages": ["Corrected 'totol' to 'total_sales'."],
            },
            intent_json={"intent_type": "analytical"},
            pipeline_trace={
                "classification": {
                    "status": "failed",
                    "final_output": {"message": "temporary upstream issue"},
                    "errors": [{"type": "system", "message": "temporary upstream issue"}],
                },
                "preprocessing_high": {
                    "status": "success",
                    "final_output": {"final_query": "How do customers relationship total sales?"},
                    "errors": [],
                },
            },
            generated_sql="SELECT customers, total_sales FROM sales_3months_realistic_csv",
            reviewed_sql="SELECT customers, total_sales FROM sales_3months_realistic_csv",
            query_result={"columns": ["customers", "total_sales"], "rows": [{"customers": 10, "total_sales": 100.0}]},
            execution_time_ms=12,
            row_count=1,
            chart_type="scatter",
            metabase_question_id=1,
            metabase_dashboard_id=2,
            embed_url="",
            chart_config={},
            error_message="",
        )

        self.assertFalse(bool(trace["classification"]["error"]))
        self.assertIn("term_corrections", trace["preprocessing_high"])
        self.assertTrue(trace["preprocessing_high"]["term_corrections"])


if __name__ == "__main__":
    unittest.main()
