import time
from typing import Any

from dagster import AssetExecutionContext, asset

from dagster_pipeline import ASSET_RETRY_POLICY, pipeline_failure_hook
from intent_extraction.intent_extraction_task import run_intent_extraction_stage
from llm_app.schema_provider import get_schema
from shared.pipeline_trace import make_attempt, utc_now_iso
from shared.schema_filtering import filter_business_schema, rank_tables_for_question


def _schema_from_preprocessing_high(preprocessing_high_asset: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    schema_used = preprocessing_high_asset.get("schema_used")
    if not isinstance(schema_used, dict):
        return {}

    candidate_columns = schema_used.get("columns")
    if isinstance(candidate_columns, dict):
        schema_columns = candidate_columns
    else:
        schema_columns = schema_used

    normalized_schema: dict[str, list[dict[str, Any]]] = {}
    for table_name, columns in schema_columns.items():
        normalized_table = str(table_name).strip()
        if not normalized_table or not isinstance(columns, list):
            continue
        normalized_columns: list[dict[str, Any]] = []
        for column in columns:
            if not isinstance(column, dict):
                continue
            column_name = str(column.get("name", "")).strip()
            if not column_name:
                continue
            normalized_columns.append(
                {
                    "name": column_name,
                    "type": str(column.get("type", "")).strip(),
                }
            )
        if normalized_columns:
            normalized_schema[normalized_table] = normalized_columns
    return normalized_schema


def _resolve_selected_table_name(
    *,
    selected_table: str,
    schema_snapshot: dict[str, list[dict[str, Any]]],
) -> str:
    normalized_selected = str(selected_table or "").strip()
    if not normalized_selected:
        return ""

    normalized_suffix = normalized_selected.split(".")[-1].lower()
    for table_name in schema_snapshot.keys():
        normalized_table = str(table_name).strip()
        if not normalized_table:
            continue
        if normalized_table.lower() == normalized_selected.lower():
            return normalized_table
        if normalized_table.split(".")[-1].lower() == normalized_suffix:
            return normalized_table
    return ""


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def intent_extraction_asset(
    context: AssetExecutionContext,
    preprocessing_high_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    high_status = preprocessing_high_asset.get("status")
    if high_status != "success":
        context.log.warning(
            "Skipping intent extraction because high preprocessing did not succeed | status=%s",
            high_status,
        )
        attempts = [
            make_attempt(
                attempt_number=1,
                input_payload={"preprocessing_high_status": high_status},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="upstream_guard",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="upstream_preprocessing_high_failed",
                error_message="Intent extraction skipped due to preprocessing_high status.",
            )
        ]
        return {
            "status": "skipped",
            "intent_type": "analytical",
            "next_step": "metabase",
            "error_type": "upstream_preprocessing_high_failed",
            "action_taken": "stop",
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [
                {
                    "type": "upstream_preprocessing_high_failed",
                    "message": "Intent extraction skipped due to preprocessing_high status.",
                }
            ],
            "debug_metadata": {},
        }

    final_query = str(preprocessing_high_asset.get("final_query", "")).strip()
    if not final_query:
        context.log.error("Intent extraction input invalid: final_query is empty after high preprocessing.")
        attempts = [
            make_attempt(
                attempt_number=1,
                input_payload={"final_query": final_query},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="input_validation",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="input",
                error_message="final_query is empty after high preprocessing.",
            )
        ]
        return {
            "status": "failed",
            "intent_type": "analytical",
            "next_step": "metabase",
            "error_type": "input",
            "action_taken": "stop",
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "input", "message": "final_query is empty after high preprocessing."}],
            "debug_metadata": {},
        }

    schema_snapshot = _schema_from_preprocessing_high(preprocessing_high_asset)
    schema_source = "preprocessing_high.schema_used"
    if not schema_snapshot:
        try:
            schema_snapshot = get_schema()
            schema_source = "schema_provider.get_schema"
        except Exception as exc:  # noqa: BLE001
            context.log.error("Schema loading failed for intent extraction | error=%s", str(exc))
            attempts = [
                make_attempt(
                    attempt_number=1,
                    input_payload={"final_query": final_query},
                    output_payload={},
                    success=False,
                    retry_triggered=False,
                    model_or_method_used="schema_provider.get_schema",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type="system",
                    error_message=f"Failed to load schema: {exc}",
                )
            ]
            return {
                "status": "failed",
                "intent_type": "analytical",
                "next_step": "metabase",
                "error_type": "system",
                "action_taken": "stop",
                "message": f"Failed to load schema: {exc}",
                "attempts": attempts,
                "attempts_count": len(attempts),
                "started_at": stage_started_at,
                "finished_at": utc_now_iso(),
                "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                "warnings": [],
                "errors": [{"type": "system", "message": f"Failed to load schema: {exc}"}],
                "debug_metadata": {},
            }
    context.log.info(
        "Intent extraction schema prepared | source=%s tables=%s",
        schema_source,
        len(schema_snapshot),
    )

    schema_snapshot, schema_filter_meta = filter_business_schema(schema_snapshot)

    selected_table = str(preprocessing_high_asset.get("selected_table", "")).strip()
    selected_columns = [
        str(column).strip()
        for column in preprocessing_high_asset.get("selected_columns", [])
        if str(column).strip()
    ]
    resolved_selected_table = _resolve_selected_table_name(
        selected_table=selected_table,
        schema_snapshot=schema_snapshot,
    )
    should_scope_schema = bool(resolved_selected_table)
    if should_scope_schema:
        # Keep full table columns by default to avoid dropping semantically relevant fields.
        # Column-level narrowing is intentionally avoided unless extraction confidence is explicit.
        schema_snapshot = {resolved_selected_table: schema_snapshot.get(resolved_selected_table, [])}
        context.log.info(
            "Schema narrowed to selected table for intent extraction | table=%s selected_columns=%s",
            resolved_selected_table,
            selected_columns,
        )
    elif selected_table:
        context.log.warning(
            "Selected table could not be resolved in schema. Keeping full schema | selected_table=%s",
            selected_table,
        )
    else:
        candidate_tables = [
            str(table).strip()
            for table in preprocessing_high_asset.get("candidate_tables", [])
            if str(table).strip()
        ]
        ranked_tables = rank_tables_for_question(
            schema=schema_snapshot,
            question=final_query,
            limit=3,
            preferred_tables=candidate_tables,
        )
        if ranked_tables:
            schema_snapshot = {
                table_name: schema_snapshot[table_name]
                for table_name in ranked_tables
                if table_name in schema_snapshot
            }
            context.log.info(
                "Schema narrowed by ranked table relevance | ranked_tables=%s",
                ranked_tables,
            )

    result = run_intent_extraction_stage(
        query=final_query,
        schema=schema_snapshot,
    )
    result.setdefault("started_at", stage_started_at)
    result.setdefault("finished_at", utc_now_iso())
    if not result.get("duration_ms"):
        result["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
    result.setdefault("attempts", [])
    result["attempts_count"] = len(result.get("attempts", []))
    result.setdefault("warnings", [])
    result.setdefault("errors", [])
    result.setdefault("debug_metadata", {})
    result["debug_metadata"]["final_query"] = final_query
    result["debug_metadata"]["selected_table"] = resolved_selected_table or selected_table
    result["debug_metadata"]["selected_columns"] = selected_columns
    result["debug_metadata"]["schema_tables"] = list(schema_snapshot.keys())
    result["debug_metadata"]["schema_source"] = schema_source
    result["debug_metadata"]["schema_scoped"] = should_scope_schema
    result["debug_metadata"]["schema_filtering"] = schema_filter_meta
    context.log.info(
        "Intent extraction stage completed | status=%s intent_type=%s next_step=%s",
        result.get("status"),
        result.get("intent_type"),
        result.get("next_step"),
    )
    return result
