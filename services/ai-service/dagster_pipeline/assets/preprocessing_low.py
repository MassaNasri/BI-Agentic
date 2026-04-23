import time
from typing import Any

from dagster import AssetExecutionContext, asset

from dagster_pipeline import ASSET_RETRY_POLICY, pipeline_failure_hook
from preprocessing_low.preprocess_task import run_preprocess_text
from shared.pipeline_trace import make_attempt, utc_now_iso
from shared.stage_contract import stage_allows_progress


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def preprocessing_low_asset(
    context: AssetExecutionContext,
    pipeline_request_asset: dict[str, Any],
    transcription_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    if not stage_allows_progress(transcription_asset.get("status"), degraded=bool(transcription_asset.get("degraded"))):
        context.log.warning(
            "Skipping low preprocessing because transcription failed | error_type=%s",
            transcription_asset.get("error_type"),
        )
        attempts = [
            make_attempt(
                attempt_number=1,
                input_payload={"transcription_status": transcription_asset.get("status")},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="upstream_guard",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="upstream_transcription_failed",
                error_message="Low preprocessing skipped because transcription failed.",
            )
        ]
        return {
            "status": "skipped",
            "cleaned_text": "",
            "error_type": "upstream_transcription_failed",
            "action_taken": "stop",
            "detected_changes": [],
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [
                {
                    "type": "upstream_transcription_failed",
                    "message": "Low preprocessing skipped because transcription failed.",
                }
            ],
            "debug_metadata": {
                "dataset_context": {
                    "workspace_id": pipeline_request_asset.get("workspace_id"),
                    "dataset_id": pipeline_request_asset.get("dataset_id") or pipeline_request_asset.get("source_id"),
                    "manager_id": pipeline_request_asset.get("manager_id") or pipeline_request_asset.get("user_id"),
                    "table_name": pipeline_request_asset.get("table_name"),
                }
            },
        }

    result = run_preprocess_text(text=str(transcription_asset.get("text", "")))
    if "started_at" not in result:
        result["started_at"] = stage_started_at
    if "finished_at" not in result:
        result["finished_at"] = utc_now_iso()
    if "duration_ms" not in result or not result.get("duration_ms"):
        result["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
    result.setdefault("debug_metadata", {})
    result["debug_metadata"]["input_chars"] = len(str(transcription_asset.get("text", "")))
    result["debug_metadata"]["dataset_context"] = {
        "workspace_id": pipeline_request_asset.get("workspace_id"),
        "dataset_id": pipeline_request_asset.get("dataset_id") or pipeline_request_asset.get("source_id"),
        "manager_id": pipeline_request_asset.get("manager_id") or pipeline_request_asset.get("user_id"),
        "table_name": pipeline_request_asset.get("table_name"),
    }
    context.log.info(
        "Low preprocessing completed | status=%s cleaned_chars=%s",
        result.get("status"),
        len(str(result.get("cleaned_text", ""))),
    )
    return result
