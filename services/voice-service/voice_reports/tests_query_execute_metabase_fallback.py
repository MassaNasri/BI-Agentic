import os
import sys
import types
import unittest
from unittest.mock import patch
from pathlib import Path

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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(VOICE_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(VOICE_SERVICE_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")

import django

django.setup()

from voice_reports.views import QueryExecuteView


class _FakeReport:
    def __init__(self):
        self.id = 224
        self.status = "processing"
        self.error_message = ""
        self.embed_url = "old-url"
        self.metabase_question_id = 99
        self.metabase_dashboard_id = 11
        self.chart_config = {"ai_contract": {"confidence": 0.92, "confidence_breakdown": {"classification": 0.9}}}

    def save(self):
        return None


class QueryExecuteMetabaseFallbackTests(unittest.TestCase):
    def test_common_metabase_transport_and_auth_failures_preserve_existing_metadata(self):
        cases = (
            ("401", "metabase_authentication_failed", 502),
            ("timeout", "request timed out", 504),
            ("refused", "connection refused", 503),
            ("5xx", "service unavailable", 502),
            ("malformed", "invalid response missing id", 502),
        )

        for label, details, http_status in cases:
            with self.subTest(label=label):
                view = QueryExecuteView()
                report = _FakeReport()
                with patch("voice_reports.views.build_report_ai_trace", return_value={"trace": "ok"}):
                    response = view._metabase_failure_response(
                        report=report,
                        chart_type="line_multi",
                        row_count=90,
                        execution_time_ms=209,
                        failure_reason="question_creation_failed",
                        details=details,
                        http_status=http_status,
                        clear_question=True,
                    )

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.data.get("degraded"))
                self.assertEqual(report.metabase_question_id, 99)
                self.assertEqual(report.metabase_dashboard_id, 11)
                self.assertEqual(report.embed_url, "old-url")

    def test_transient_metabase_outage_is_degraded_success(self):
        view = QueryExecuteView()
        report = _FakeReport()

        with patch("voice_reports.views.build_report_ai_trace", return_value={"trace": "ok"}):
            response = view._metabase_failure_response(
                report=report,
                chart_type="line_multi",
                row_count=90,
                execution_time_ms=209,
                failure_reason="question_creation_failed",
                details="metabase_unavailable",
                http_status=502,
                clear_question=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.get("success"))
        self.assertTrue(response.data.get("degraded"))
        self.assertEqual(response.data.get("status"), "executed")
        self.assertEqual(report.status, "executed")
        self.assertEqual(report.error_message, "")
        self.assertEqual(report.embed_url, "old-url")
        self.assertEqual(report.metabase_question_id, 99)
        self.assertEqual(report.metabase_dashboard_id, 11)
        self.assertEqual(report.chart_config.get("metabase_status"), "unavailable")
        self.assertEqual(report.chart_config.get("render_status"), "degraded")

    def test_non_transient_visualization_failure_stays_hard_failure(self):
        view = QueryExecuteView()
        report = _FakeReport()

        with patch("voice_reports.views.build_report_ai_trace", return_value={"trace": "ok"}):
            response = view._metabase_failure_response(
                report=report,
                chart_type="scatter",
                row_count=12,
                execution_time_ms=120,
                failure_reason="question_execution_failed",
                details="invalid_chart_contract",
                http_status=502,
                clear_question=True,
            )

        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.data.get("success"))
        self.assertEqual(response.data.get("error"), "metabase_visualization_failed")
        self.assertEqual(report.status, "failed")
        self.assertIn("question_execution_failed", report.error_message)


if __name__ == "__main__":
    unittest.main()
