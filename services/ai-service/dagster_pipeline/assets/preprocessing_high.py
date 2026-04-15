import time
from typing import Any

from dagster import AssetExecutionContext, asset

from dagster_pipeline import ASSET_RETRY_POLICY, pipeline_failure_hook
from preprocessing_high.preprocess_high_task import run_preprocess_high
from preprocessing_high.schemas import HighPreprocessConfig
from reasoning_app.intent_classification_task import route_intent_classification
from shared.pipeline_trace import make_attempt, utc_now_iso


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def preprocessing_high_asset(
    context: AssetExecutionContext,
    pipeline_request_asset: dict[str, Any],
    preprocessing_low_asset: dict[str, Any],
    intent_classification_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    if preprocessing_low_asset.get("status") != "success":
        context.log.warning("Skipping high preprocessing because low preprocessing failed.")
        attempts = [
            make_attempt(
                attempt_number=1,
                input_payload={"preprocessing_low_status": preprocessing_low_asset.get("status")},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="upstream_guard",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="upstream_preprocessing_low_failed",
                error_message="High preprocessing skipped because low preprocessing failed.",
            )
        ]
        return {
            "status": "skipped",
            "final_query": "",
            "schema_valid": False,
            "error_type": "upstream_preprocessing_low_failed",
            "action_taken": "stop",
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [
                {
                    "type": "upstream_preprocessing_low_failed",
                    "message": "High preprocessing skipped because low preprocessing failed.",
                }
            ],
            "debug_metadata": {},
        }

    routing_result = route_intent_classification(
        cleaned_text=str(preprocessing_low_asset.get("cleaned_text", "")),
        classification_result=intent_classification_asset,
        user_id=str(pipeline_request_asset.get("user_id") or "").strip(),
    )
    context.log.info(
        "Classification gate completed | gate_status=%s next_stage=%s",
        routing_result.get("status"),
        routing_result.get("next_stage"),
    )

    if routing_result.get("status") == "rejected":
        attempts = [
            make_attempt(
                attempt_number=1,
                input_payload={"routing": routing_result},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="intent_classification_gate",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="business",
                error_message=str(routing_result.get("message", "Question rejected by classification gate.")),
            )
        ]
        return {
            "status": "rejected",
            "final_query": "",
            "schema_valid": False,
            "error_type": "business",
            "action_taken": "stop",
            "message": routing_result.get(
                "message",
                "The question is not analytical and cannot be processed.",
            ),
            "routing": routing_result,
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "business", "message": str(routing_result.get("message", ""))}],
            "debug_metadata": {"classification": routing_result.get("classification")},
        }

    if routing_result.get("status") != "routed":
        attempts = [
            make_attempt(
                attempt_number=1,
                input_payload={"routing": routing_result},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="intent_classification_gate",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="logic",
                error_message="Intent classification routing failed.",
            )
        ]
        return {
            "status": "failed",
            "final_query": "",
            "schema_valid": False,
            "error_type": "logic",
            "action_taken": "stop",
            "message": "Intent classification routing failed.",
            "routing": routing_result,
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "logic", "message": "Intent classification routing failed."}],
            "debug_metadata": {"classification": routing_result.get("classification")},
        }

    payload = routing_result.get("payload", {}) or {}
    effective_user_id = str(payload.get("user_id") or "").strip()
    if not effective_user_id:
        effective_user_id = HighPreprocessConfig.from_env().default_user_id

    result = run_preprocess_high(
        cleaned_text=str(payload.get("cleaned_text", preprocessing_low_asset.get("cleaned_text", ""))),
        user_id=effective_user_id,
    )
    result["routing"] = routing_result
    result.setdefault("started_at", stage_started_at)
    result.setdefault("finished_at", utc_now_iso())
    if not result.get("duration_ms"):
        result["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
    result.setdefault("attempts", [])
    result["attempts_count"] = len(result.get("attempts", []))
    result.setdefault("warnings", [])
    result.setdefault("errors", [])
    result.setdefault("debug_metadata", {})
    result["debug_metadata"]["classification"] = routing_result.get("classification")
    context.log.info(
        "High preprocessing completed | status=%s schema_valid=%s",
        result.get("status"),
        result.get("schema_valid"),
    )
    return result
