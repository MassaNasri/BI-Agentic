from __future__ import annotations

import os
import sys
import types
import importlib.util
import unittest


if "dagster" not in sys.modules:
    dagster_stub = types.ModuleType("dagster")

    class _RetryPolicy:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _AssetExecutionContext:
        def __init__(self):
            self.log = type(
                "L",
                (),
                {
                    "info": lambda *a, **k: None,
                    "warning": lambda *a, **k: None,
                    "error": lambda *a, **k: None,
                },
            )()

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

_INTENT_EXTRACTION_PATH = os.path.abspath("services/ai-service/dagster_pipeline/assets/intent_extraction.py")
_intent_extraction_spec = importlib.util.spec_from_file_location(
    "dagster_pipeline_assets_intent_extraction_final_hardening_test",
    _INTENT_EXTRACTION_PATH,
)
assert _intent_extraction_spec and _intent_extraction_spec.loader
_intent_extraction_module = importlib.util.module_from_spec(_intent_extraction_spec)
_intent_extraction_spec.loader.exec_module(_intent_extraction_module)
intent_extraction_asset = _intent_extraction_module.intent_extraction_asset
from shared.confidence import pipeline_confidence, schema_confidence


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


class FinalSystemHardeningTests(unittest.TestCase):
    def test_schema_invalid_analytical_query_blocks_sql_generation(self):
        result = intent_extraction_asset(
            context=_FakeContext(),
            preprocessing_high_asset={
                "status": "degraded",
                "degraded": True,
                "schema_valid": False,
                "schema_validation_status": "invalid_unresolved_terms",
                "final_query": "show revenue by nonexistent_region",
                "unresolved_terms": ["nonexistent_region"],
                "dataset_scope": {
                    "workspace_id": "w1",
                    "dataset_id": "d1",
                    "manager_id": "m1",
                    "table_name": "sales_fact",
                },
                "routing": {"route": "analytical"},
            },
        )

        self.assertEqual(result.get("status"), "rejected")
        self.assertEqual(result.get("error_type"), "schema_mismatch")
        self.assertEqual(result.get("validated_intent"), {})
        self.assertFalse(result.get("debug_metadata", {}).get("sql_generation_allowed"))
        self.assertLess(result.get("confidence", 1.0), 0.5)

    def test_confidence_penalizes_schema_deferred_and_forecast_fallback(self):
        high = {
            "status": "degraded",
            "degraded": True,
            "schema_valid": False,
            "deferred": True,
            "unresolved_terms": ["regionn"],
        }
        score = schema_confidence(high)
        self.assertLess(score, 0.5)

        aggregate = pipeline_confidence(
            preprocessing_low={"status": "success", "confidence": 0.9},
            classification={"status": "success", "confidence": 0.88},
            preprocessing_high=high,
            intent_extraction={"status": "degraded", "degraded": True},
            query_execution={"status": "success"},
            visualization={"status": "success"},
            forecasting={
                "status": "degraded",
                "degraded": True,
                "downstream_result": {"forecast_meta": {"forecast_available": False}},
            },
        )
        self.assertGreaterEqual(aggregate.get("score", 0), 0.0)
        self.assertLess(aggregate.get("score", 1), 0.8)
        self.assertIn("schema", aggregate.get("components", {}))


if __name__ == "__main__":
    unittest.main()
