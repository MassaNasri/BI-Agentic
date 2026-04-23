import importlib.util
import os
import sys
import types
import unittest


_WHISPER_VIEWS_PATH = os.path.abspath("services/ai-service/whisper_app/views.py")
_whisper_spec = importlib.util.spec_from_file_location("whisper_app_views_test", _WHISPER_VIEWS_PATH)
_whisper_module = importlib.util.module_from_spec(_whisper_spec)
assert _whisper_spec and _whisper_spec.loader

# Avoid importing heavy optional runtime dependencies during unit tests.
_transcription_stub = types.ModuleType("whisper_app.transcription_task")
_transcription_stub.whisper_transcription_preprocess_intent_flow = lambda **_: {}
sys.modules.setdefault("whisper_app.transcription_task", _transcription_stub)

_whisper_spec.loader.exec_module(_whisper_module)

_build_llm_from_pipeline = _whisper_module._build_llm_from_pipeline


class WhisperLlmChartPropagationTests(unittest.TestCase):
    def test_selected_chart_type_is_applied_to_chart_payload(self):
        payload = _build_llm_from_pipeline(
            {
                "status": "success",
                "final_route": "metabase",
                "intent_extraction": {"normalized_intent": {"intent": "time_series"}},
                "query_execution": {"sql_query": "SELECT 1"},
                "visualization": {
                    "selected_chart_type": "line",
                    "reason_chart_selected": "time_grouping_default_line",
                    "downstream_result": {"status": "pending_integration"},
                },
            }
        )
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("chart", {}).get("chart_type"), "line")
        self.assertEqual(payload.get("chart", {}).get("type"), "line")
        self.assertEqual(
            payload.get("chart", {}).get("reason_chart_selected"),
            "time_grouping_default_line",
        )


if __name__ == "__main__":
    unittest.main()
