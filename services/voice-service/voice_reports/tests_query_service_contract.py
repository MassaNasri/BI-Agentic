from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

if "clickhouse_connect" not in sys.modules:
    sys.modules["clickhouse_connect"] = types.SimpleNamespace(get_client=lambda **_kwargs: None)
if "jwt" not in sys.modules:
    sys.modules["jwt"] = types.SimpleNamespace(encode=lambda *_args, **_kwargs: "")

def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "bi_platform_shared").exists():
            return candidate
    parents = list(current.parents)
    return parents[min(3, len(parents) - 1)]


REPO_ROOT = _resolve_repo_root()
VOICE_SERVICE_ROOT = REPO_ROOT / "services" / "voice-service"
if not VOICE_SERVICE_ROOT.exists():
    VOICE_SERVICE_ROOT = REPO_ROOT
for path in (REPO_ROOT, VOICE_SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")

import django

django.setup()

from voice_reports.views import (
    DatasetBindingResolutionError,
    QueryExecuteView,
    _report_query_metadata,
    _resolve_dataset_binding_context,
)
from voice_reports.services.event_bus import KafkaEventPublisher


class QueryServiceContractTests(unittest.TestCase):
    def test_dataset_binding_uses_query_service_authority_even_when_explicit(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "success": True,
            "data": {
                "id": 4,
                "manager": 4,
                "workspace_id": 3,
                "clickhouse_table_name": "sales",
            },
        }
        request = Mock()
        request.META = {"HTTP_AUTHORIZATION": "Bearer test"}

        with patch("voice_reports.views.requests.get", return_value=response) as get:
            binding = _resolve_dataset_binding_context(
                request=request,
                workspace_id="3",
                manager_id="4",
                explicit_dataset_id="4",
                explicit_table_name="sales",
            )

        self.assertEqual(binding["dataset_id"], "4")
        self.assertEqual(binding["table_name"], "sales")
        self.assertEqual(get.call_args.kwargs["params"]["workspace_id"], "3")
        self.assertEqual(get.call_args.kwargs["params"]["dataset_id"], "4")

    def test_dataset_binding_propagates_structured_missing_metadata(self):
        response = Mock()
        response.status_code = 422
        response.json.return_value = {
            "success": False,
            "code": "dataset_metadata_missing",
            "category": "data_source",
            "message": "Workspace 2 has no uploaded dataset.",
            "details": {"workspace_id": 2},
        }
        request = Mock()
        request.META = {}

        with (
            patch("voice_reports.views.requests.get", return_value=response),
            self.assertRaises(DatasetBindingResolutionError) as raised,
        ):
            _resolve_dataset_binding_context(
                request=request,
                workspace_id="2",
                manager_id="3",
            )

        self.assertEqual(raised.exception.code, "dataset_metadata_missing")
        self.assertEqual(raised.exception.http_status, 422)

    def test_dataset_binding_rejects_malformed_authority_response(self):
        response = Mock()
        response.status_code = 200
        response.json.side_effect = ValueError("not json")
        request = Mock()
        request.META = {}

        with (
            patch("voice_reports.views.requests.get", return_value=response),
            self.assertRaises(DatasetBindingResolutionError) as raised,
        ):
            _resolve_dataset_binding_context(
                request=request,
                workspace_id="3",
                manager_id="4",
            )

        self.assertEqual(raised.exception.code, "dataset_authority_invalid_response")
        self.assertEqual(raised.exception.http_status, 502)

    def test_default_kafka_topics_cover_text_report_events(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(KafkaEventPublisher, "_initialize"),
        ):
            publisher = KafkaEventPublisher()

        self.assertIn("report.text.received", publisher.required_topics)

    def test_legacy_chart_profile_is_adapted_to_canonical_result_shape(self):
        report = types.SimpleNamespace(
            query_result={
                "columns": [
                    {"name": "period", "type": "Date"},
                    {"name": "total_sales", "type": "Float64"},
                ],
                "rows": [
                    {"period": "2026-01-01", "total_sales": 10.0},
                    {"period": "2026-01-02", "total_sales": 12.0},
                ],
                "result_shape": {
                    "row_count": 2,
                    "numeric_columns": ["total_sales"],
                    "time_like_columns": ["period"],
                    "category_columns": ["period"],
                },
            },
            chart_config={},
        )

        metadata = _report_query_metadata(report)

        self.assertEqual(metadata["result_shape"]["type"], "time_series")
        self.assertEqual(metadata["result_shape"]["time_field"], "period")
        self.assertEqual(metadata["result_shape"]["metric_fields"], ["total_sales"])

    def test_status_only_success_is_accepted_during_rolling_upgrade(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "status": "success",
            "rows": [{"total": 3}],
            "columns": ["total"],
        }
        request = Mock()
        request.META = {}

        with (
            patch("voice_reports.views.requests.post", return_value=response),
            patch("voice_reports.views.get_user_workspace_id", return_value="1"),
        ):
            result = QueryExecuteView()._execute_query_with_query_service(
                request,
                "SELECT count() AS total",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "success")

    def test_null_error_is_normalized_to_non_empty_failure_message(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "success": False,
            "status": "failed",
            "error": None,
            "error_message": None,
        }
        request = Mock()
        request.META = {}

        with (
            patch("voice_reports.views.requests.post", return_value=response),
            patch("voice_reports.views.get_user_workspace_id", return_value="1"),
        ):
            result = QueryExecuteView()._execute_query_with_query_service(
                request,
                "SELECT count() AS total",
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "query_service_execution_failed")


if __name__ == "__main__":
    unittest.main()
