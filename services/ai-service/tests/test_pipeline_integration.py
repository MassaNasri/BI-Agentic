import os
import sys
import types
import importlib.util
import unittest
from unittest.mock import patch


if "dagster" not in sys.modules:
    dagster_stub = types.ModuleType("dagster")

    class _RetryPolicy:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _AssetExecutionContext:
        def __init__(self):
            self.log = type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None, "error": lambda *a, **k: None})()

    def _asset(*args, **kwargs):
        def decorator(fn):
            return fn

        return decorator

    def _failure_hook(fn):
        return fn

    dagster_stub.RetryPolicy = _RetryPolicy
    dagster_stub.AssetExecutionContext = _AssetExecutionContext
    dagster_stub.HookContext = object
    dagster_stub.Config = object
    dagster_stub.asset = _asset
    dagster_stub.failure_hook = _failure_hook
    sys.modules["dagster"] = dagster_stub

if "clickhouse_connect" not in sys.modules:
    clickhouse_stub = types.ModuleType("clickhouse_connect")

    def _get_client(*args, **kwargs):
        raise RuntimeError("clickhouse client is not available in unit tests")

    clickhouse_stub.get_client = _get_client
    sys.modules["clickhouse_connect"] = clickhouse_stub

sys.path.insert(0, os.path.abspath("services/ai-service"))

_EXECUTION_PATH = os.path.abspath("services/ai-service/dagster_pipeline/assets/execution.py")
_execution_spec = importlib.util.spec_from_file_location("dagster_pipeline_assets_execution_test", _EXECUTION_PATH)
assert _execution_spec and _execution_spec.loader
_execution_module = importlib.util.module_from_spec(_execution_spec)
_execution_spec.loader.exec_module(_execution_module)

pipeline_result_asset = _execution_module.pipeline_result_asset
query_execution_asset = _execution_module.query_execution_asset


class _FakeLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class _FakeContext:
    def __init__(self):
        self.log = _FakeLogger()


class PipelineIntegrationTests(unittest.TestCase):
    def test_pipeline_result_does_not_double_reject_when_preprocess_high_is_success(self):
        payload = pipeline_result_asset(
            pipeline_request_asset={"request_id": "r1", "text": "show cities in north region"},
            transcription_asset={"status": "success", "text": "show cities in north region"},
            preprocessing_low_asset={"status": "success", "cleaned_text": "show cities in north region"},
            intent_classification_asset={
                "status": "success",
                "classification": "analytical",
                "classification_reason": "rule_based_analytical_detection",
                "confidence": 0.92,
                "question_type": "analytical",
            },
            preprocessing_high_asset={
                "status": "success",
                "schema_valid": True,
                "schema_validation_status": "invalid_unresolved_terms",
                "final_query": "show cities in north region",
                "unresolved_terms": ["dummy"],
                "routing": {"status": "routed"},
            },
            intent_extraction_asset={
                "status": "success",
                "intent_type": "analytical",
                "next_step": "metabase",
                "query": "show cities in north region",
                "schema": {"population_distribution_csv": [{"name": "city", "type": "String"}]},
                "extracted_intent": {},
                "validated_intent": {
                    "intent": "filtering",
                    "operations": ["projection", "filtering"],
                    "table": "population_distribution_csv",
                    "metrics": [{"column": "city", "aggregation": None, "alias": "city"}],
                    "dimensions": ["city"],
                    "filters": [{"column": "region", "operator": "=", "value": "north"}],
                    "aggregation": None,
                    "ranking": {"direction": None, "requested": False, "source": "validation"},
                    "order_by": [],
                    "limit": None,
                    "ambiguities": [],
                },
            },
            routing_asset={
                "status": "routed",
                "next_step": "metabase",
                "intent_type": "analytical",
                "query": "show cities in north region",
                "schema": {"population_distribution_csv": [{"name": "city", "type": "String"}]},
            },
            query_execution_asset={
                "status": "success",
                "next_step": "metabase",
                "intent_type": "analytical",
                "sql_query": "SELECT city FROM etl.population_distribution_csv;",
                "generated_sql": "SELECT city FROM etl.population_distribution_csv;",
                "reviewed_sql": "SELECT city FROM etl.population_distribution_csv;",
                "sql_review": {"notes": ["ok"], "reason_category": "alignment"},
                "sql_review_outcome": "approved",
                "sql_validation_outcome": "passed",
                "safety_validation_outcome": "passed",
                "execution_result": {"rows": [{"city": "north_city"}], "row_count": 1, "columns": ["city"]},
                "result_preview": {"row_count": 1},
                "referenced_tables": ["population_distribution_csv"],
                "referenced_columns": ["city", "region"],
            },
            visualization_asset={
                "status": "success",
                "visualization_status": "success",
                "selected_chart_type": "bar",
                "reason_chart_selected": "categorical comparison",
                "reason_chart_not_generated": "",
                "visualization_payload_preview": {"chart_type": "bar"},
                "downstream_result": {"chart_type": "bar"},
            },
            forecasting_asset={"status": "skipped", "next_step": "forecasting"},
        )
        self.assertEqual(payload.get("status"), "success")

    @patch.object(_execution_module, "execute_clickhouse_query")
    @patch.object(_execution_module, "review_and_correct_sql")
    @patch.object(_execution_module, "build_sql_from_intent")
    def test_query_execution_falls_back_to_compiler_sql_when_review_rejects(
        self,
        mock_build_sql,
        mock_review,
        mock_execute,
    ):
        normalized_intent = {
            "intent": "ranking",
            "operations": ["projection", "aggregation", "grouping", "ranking", "limiting"],
            "table": "population_distribution_csv",
            "metrics": [{"column": "total_population", "aggregation": "SUM", "alias": "sum_total_population"}],
            "dimensions": ["city"],
            "filters": [],
            "aggregation": "SUM",
            "ranking": {"direction": "DESC", "requested": True, "source": "query"},
            "order_by": [{"column": "sum_total_population", "direction": "DESC"}],
            "limit": 5,
            "ambiguities": [],
        }
        sql = (
            "SELECT city, SUM(total_population) AS sum_total_population "
            "FROM etl.population_distribution_csv GROUP BY city ORDER BY sum_total_population DESC LIMIT 5;"
        )
        mock_build_sql.return_value = (normalized_intent, sql)
        mock_review.return_value = {
            "status": "rejected",
            "reviewed_sql": "SELECT 1;",
            "notes": ["bad review"],
            "reason_category": "alignment",
        }
        mock_execute.return_value = {
            "rows": [{"city": "x", "sum_total_population": 1}],
            "row_count": 1,
            "columns": ["city", "sum_total_population"],
        }

        result = query_execution_asset(
            context=_FakeContext(),
            routing_asset={
                "status": "routed",
                "next_step": "metabase",
                "intent_type": "analytical",
                "query": "show top 5 cities by population",
                "schema": {
                    "population_distribution_csv": [
                        {"name": "city", "type": "String"},
                        {"name": "total_population", "type": "Float64"},
                    ]
                },
                "validated_intent": normalized_intent,
                "extracted_intent": {},
            },
        )

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("sql_query"), sql)
        self.assertEqual(result.get("generated_sql"), sql)
        self.assertEqual(result.get("reviewed_sql"), sql)
        self.assertEqual(result.get("sql_review_outcome"), "fallback_compiler")


if __name__ == "__main__":
    unittest.main()
