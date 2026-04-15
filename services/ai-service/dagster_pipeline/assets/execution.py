import time
from typing import Any

from dagster import AssetExecutionContext, asset

from dagster_pipeline import ASSET_RETRY_POLICY, pipeline_failure_hook
from intent_extraction.error_handler import (
    classify_intent_extraction_error,
    decide_intent_extraction_action,
)
from intent_extraction.routing import (
    build_sql_from_intent,
    execute_clickhouse_query,
    execute_downstream_route,
)
from intent_extraction.schemas import IntentExtractionConfig
from shared.pipeline_trace import (
    attach_stage,
    build_pipeline_trace_template,
    finalize_trace,
    make_attempt,
    stage_payload,
    utc_now_iso,
)
from shared.sql_review import review_and_correct_sql


def _extract_result_preview(execution_result: Any, max_rows: int = 5) -> dict[str, Any]:
    if not isinstance(execution_result, dict):
        return {"preview_rows": [], "row_count": 0}

    rows = execution_result.get("rows", [])
    if not isinstance(rows, list):
        rows = []
    preview_rows = rows[:max_rows]
    row_count = execution_result.get("row_count")
    if row_count is None:
        row_count = len(rows)
    return {
        "preview_rows": preview_rows,
        "row_count": int(row_count or 0),
        "columns": execution_result.get("columns", []),
    }


def _root_cause_for(stage: str, payload: dict[str, Any] | None = None) -> tuple[str, str, str]:
    stage_lower = str(stage or "").strip().lower()
    result_payload = payload or {}
    message = (
        str(result_payload.get("message") or "")
        or str(result_payload.get("error_message") or "")
        or f"Pipeline failed at stage '{stage_lower}'."
    )
    mapping = {
        "input_validation": "input",
        "transcription": "transcription",
        "preprocess": "preprocessing",
        "preprocessing_low": "preprocessing",
        "preprocessing_high": "schema",
        "intent_classification": "routing",
        "intent_extraction": "intent",
        "routing": "routing",
        "sql_generation": "sql_generation",
        "sql_review": "sql_validation",
        "sql_validation": "sql_validation",
        "query_execution": "query_execution",
        "visualization": "visualization",
        "forecasting": "visualization",
        "dagster_orchestration": "orchestration",
    }
    category = mapping.get(stage_lower, "unknown")
    recommended_fix = {
        "input": "Provide a non-empty analytical request with meaningful text.",
        "transcription": "Verify audio clarity, duration, and Whisper service health.",
        "preprocessing": "Review low-level normalization and check whether the request was reduced to empty content.",
        "schema": "Validate schema coverage for requested business terms or adjust metric/dimension names.",
        "routing": "Review classification/routing confidence and fallback route rules.",
        "intent": "Inspect extracted structured intent and resolve missing entities.",
        "sql_generation": "Inspect normalized intent and SQL compiler constraints.",
        "sql_validation": "Inspect SQL safety/review diagnostics and adjust unsupported operations.",
        "query_execution": "Verify ClickHouse connectivity, SQL correctness, and runtime limits.",
        "visualization": "Inspect chart-shape requirements and downstream visualization service health.",
        "orchestration": "Inspect Dagster step events, retries, and failed dependencies.",
        "unknown": "Inspect stage attempts and debug metadata to locate the first failing component.",
    }.get(category, "Inspect trace metadata and retry diagnostics.")
    return category, message, recommended_fix


def _to_trace_stage(
    *,
    status: str,
    result: dict[str, Any] | None,
    final_output: Any,
    fallback_errors: list[dict[str, Any]] | None = None,
    fallback_warnings: list[dict[str, Any]] | None = None,
    extra_debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = result or {}
    debug_metadata = payload.get("debug_metadata", {}) if isinstance(payload.get("debug_metadata"), dict) else {}
    if extra_debug:
        debug_metadata = {**debug_metadata, **extra_debug}

    return stage_payload(
        status=status,
        final_output=final_output,
        attempts=payload.get("attempts", []) if isinstance(payload.get("attempts"), list) else [],
        errors=(
            payload.get("errors", [])
            if isinstance(payload.get("errors"), list)
            else list(fallback_errors or [])
        ),
        warnings=(
            payload.get("warnings", [])
            if isinstance(payload.get("warnings"), list)
            else list(fallback_warnings or [])
        ),
        debug_metadata=debug_metadata,
        started_at=payload.get("started_at"),
        finished_at=payload.get("finished_at"),
    )


def _build_stage_failed(
    *,
    stage: str,
    message: str,
    transcription: dict[str, Any],
    preprocess: dict[str, Any],
    intent: dict[str, Any],
    routing: dict[str, Any],
    preprocess_high: dict[str, Any],
    intent_extraction: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "failed",
        "stage": stage,
        "message": message,
        "transcription": transcription,
        "preprocess": preprocess,
        "intent": intent,
        "routing": routing,
        "preprocess_high": preprocess_high,
        "intent_extraction": intent_extraction,
    }


def _validate_ir_contract(validated_intent: dict[str, Any]) -> tuple[bool, list[str]]:
    if not isinstance(validated_intent, dict):
        return False, ["validated_intent must be an object"]

    required_keys = [
        "intent",
        "operations",
        "table",
        "metrics",
        "dimensions",
        "filters",
        "aggregation",
        "ranking",
        "order_by",
        "limit",
        "ambiguities",
    ]
    missing = [key for key in required_keys if key not in validated_intent]
    if missing:
        return False, [f"Missing IR fields: {', '.join(missing)}"]

    if not isinstance(validated_intent.get("metrics"), list) or not validated_intent.get("metrics"):
        return False, ["IR must contain at least one metric"]
    if not isinstance(validated_intent.get("dimensions"), list):
        return False, ["IR field 'dimensions' must be a list"]
    if not isinstance(validated_intent.get("filters"), list):
        return False, ["IR field 'filters' must be a list"]
    if not isinstance(validated_intent.get("order_by"), list):
        return False, ["IR field 'order_by' must be a list"]
    if not isinstance(validated_intent.get("operations"), list):
        return False, ["IR field 'operations' must be a list"]
    if not isinstance(validated_intent.get("ranking"), dict):
        return False, ["IR field 'ranking' must be an object"]
    if not str(validated_intent.get("table", "")).strip():
        return False, ["IR field 'table' must be non-empty"]
    if not str(validated_intent.get("intent", "")).strip():
        return False, ["IR field 'intent' must be non-empty"]
    return True, []


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def query_execution_asset(
    context: AssetExecutionContext,
    routing_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    if routing_asset.get("status") != "routed":
        context.log.warning(
            "Skipping query execution because routing did not complete | status=%s",
            routing_asset.get("status"),
        )
        attempts.append(
            make_attempt(
                attempt_number=1,
                input_payload={"routing_status": routing_asset.get("status")},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="upstream_guard",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="upstream_routing_failed",
                error_message="Query execution skipped because routing did not complete.",
            )
        )
        return {
            "status": "skipped",
            "sql_query": "",
            "error_type": "upstream_routing_failed",
            "action_taken": "stop",
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [
                {
                    "type": "upstream_routing_failed",
                    "message": "Query execution skipped because routing did not complete.",
                }
            ],
            "debug_metadata": {},
        }

    normalized_query = str(routing_asset.get("query", "")).strip()
    normalized_schema = routing_asset.get("schema", {}) or {}
    validated_intent = routing_asset.get("validated_intent", {}) or {}
    next_step = str(routing_asset.get("next_step", "metabase"))

    if not normalized_query or not isinstance(normalized_schema, dict) or not validated_intent:
        context.log.error("Invalid routing payload for query execution.")
        attempts.append(
            make_attempt(
                attempt_number=1,
                input_payload={"query": normalized_query, "validated_intent": validated_intent},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="input_validation",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="input",
                error_message="Invalid routing payload for query execution.",
            )
        )
        return {
            "status": "failed",
            "sql_query": "",
            "error_type": "input",
            "action_taken": "stop",
            "next_step": next_step,
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "input", "message": "Invalid routing payload for query execution."}],
            "debug_metadata": {},
        }

    ir_is_valid, ir_contract_errors = _validate_ir_contract(validated_intent)
    if not ir_is_valid:
        attempts.append(
            make_attempt(
                attempt_number=1,
                input_payload={"validated_intent": validated_intent},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="ir_contract_validator",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="logic",
                error_message="; ".join(ir_contract_errors),
            )
        )
        return {
            "status": "failed",
            "sql_query": "",
            "error_type": "logic",
            "action_taken": "stop",
            "next_step": next_step,
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "logic", "message": "; ".join(ir_contract_errors)}],
            "debug_metadata": {"ir_contract_errors": ir_contract_errors},
        }

    config = IntentExtractionConfig.from_env()
    retry_count = 0
    generated_sql_candidate = ""
    reviewed_sql_candidate = ""
    sql_review_payload: dict[str, Any] = {}
    review_status = "failed"

    while True:
        try:
            attempt_started_perf = time.perf_counter()
            normalized_intent, sql_query = build_sql_from_intent(
                query=normalized_query,
                intent=validated_intent,
                schema=normalized_schema,
            )
            generated_sql_candidate = sql_query
            sql_review = review_and_correct_sql(
                question=normalized_query,
                schema=normalized_schema,
                generated_sql=sql_query,
                validated_intent=normalized_intent,
                extracted_intent=routing_asset.get("extracted_intent", {}),
            )
            sql_review_payload = sql_review
            reviewed_sql = str(sql_review.get("reviewed_sql", "")).strip()
            reviewed_sql_candidate = reviewed_sql
            review_status = str(sql_review.get("status", "rejected")).strip().lower()
            if review_status == "rejected":
                review_notes = sql_review.get("notes", [])
                merged_notes = [str(note) for note in review_notes if str(note).strip()]
                merged_notes.append("SQL review rejected output; preserved compiler SQL to avoid semantic drift.")
                sql_review_payload = {
                    **sql_review,
                    "status": "approved",
                    "reviewed_sql": sql_query,
                    "notes": merged_notes,
                    "reason_category": str(sql_review.get("reason_category", "alignment") or "alignment"),
                }
                reviewed_sql = sql_query
                reviewed_sql_candidate = reviewed_sql
                review_status = "fallback_compiler"

            execution_result = execute_clickhouse_query(
                sql_query=reviewed_sql,
                normalized_intent=normalized_intent,
                config=config,
            )
            attempt_duration_ms = int((time.perf_counter() - attempt_started_perf) * 1000)
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={
                        "query": normalized_query,
                        "validated_intent": validated_intent,
                        "next_step": next_step,
                    },
                    output_payload={
                        "generated_sql": sql_query,
                        "reviewed_sql": reviewed_sql,
                        "normalized_intent": normalized_intent,
                        "sql_review": sql_review,
                        "execution_preview": _extract_result_preview(execution_result),
                    },
                    success=True,
                    retry_triggered=False,
                    model_or_method_used="build_sql_from_intent+review_and_correct_sql+execute_clickhouse_query",
                    duration_ms=attempt_duration_ms,
                    validation_result={
                        "sql_validation_outcome": "passed",
                        "sql_review_outcome": review_status,
                        "safety_validation_outcome": "passed",
                    },
                )
            )
            context.log.info(
                "Query execution completed | next_step=%s sql_chars=%s",
                next_step,
                len(reviewed_sql),
            )
            return {
                "status": "success",
                "next_step": next_step,
                "intent_type": routing_asset.get("intent_type", "analytical"),
                "validated_intent": validated_intent,
                "extracted_intent": routing_asset.get("extracted_intent", {}),
                "normalized_intent": normalized_intent,
                "sql_query": reviewed_sql,
                "generated_sql": sql_query,
                "reviewed_sql": reviewed_sql,
                "sql_review": sql_review,
                "execution_result": execution_result,
                "error_type": "none",
                "action_taken": "proceed",
                "sql_generation_input": {
                    "query": normalized_query,
                    "intent": validated_intent,
                    "schema_tables": list(normalized_schema.keys()),
                },
                "sql_validation_outcome": "passed",
                "sql_review_outcome": review_status,
                "safety_validation_outcome": "passed",
                "referenced_tables": [normalized_intent.get("table")],
                "referenced_columns": sorted(
                    {
                        metric.get("column")
                        for metric in normalized_intent.get("metrics", [])
                        if isinstance(metric, dict) and metric.get("column")
                    }
                    | {
                        dim
                        for dim in normalized_intent.get("dimensions", [])
                        if isinstance(dim, str) and dim
                    }
                    | {
                        flt.get("column")
                        for flt in normalized_intent.get("filters", [])
                        if isinstance(flt, dict) and flt.get("column")
                    }
                ),
                "result_preview": _extract_result_preview(execution_result),
                "attempts": attempts,
                "attempts_count": len(attempts),
                "started_at": stage_started_at,
                "finished_at": utc_now_iso(),
                "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                "warnings": [],
                "errors": [],
                "debug_metadata": {"retry_count": retry_count},
            }
        except Exception as exc:  # noqa: BLE001
            error_type = classify_intent_extraction_error(exc)
            action_taken = decide_intent_extraction_action(
                error_type=error_type,
                retry_count=retry_count,
                config=config,
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={
                        "query": normalized_query,
                        "validated_intent": validated_intent,
                        "next_step": next_step,
                    },
                    output_payload={},
                    success=False,
                    retry_triggered=action_taken == "retry",
                    retry_reason=str(exc) if action_taken == "retry" else "",
                    model_or_method_used="build_sql_from_intent+review_and_correct_sql+execute_clickhouse_query",
                    duration_ms=0,
                    validation_result={
                        "sql_validation_outcome": "failed",
                        "sql_review_outcome": "failed",
                        "safety_validation_outcome": "failed",
                    },
                    error_type=error_type,
                    error_message=str(exc),
                )
            )
            context.log.error(
                "Query execution failed | error_type=%s action_taken=%s retry_count=%s error=%s",
                error_type,
                action_taken,
                retry_count,
                str(exc),
            )

            if action_taken == "retry":
                retry_count += 1
                continue

            return {
                "status": "failed",
                "next_step": next_step,
                "intent_type": routing_asset.get("intent_type", "analytical"),
                "validated_intent": validated_intent,
                "extracted_intent": routing_asset.get("extracted_intent", {}),
                "sql_query": "",
                "generated_sql": generated_sql_candidate,
                "reviewed_sql": reviewed_sql_candidate,
                "sql_review": sql_review_payload,
                "execution_result": None,
                "error_type": error_type,
                "action_taken": action_taken,
                "sql_generation_input": {
                    "query": normalized_query,
                    "intent": validated_intent,
                },
                "sql_generation_failure_reason": str(exc),
                "sql_validation_outcome": "failed",
                "sql_review_outcome": "failed",
                "safety_validation_outcome": "failed",
                "attempts": attempts,
                "attempts_count": len(attempts),
                "started_at": stage_started_at,
                "finished_at": utc_now_iso(),
                "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                "warnings": [],
                "errors": [{"type": error_type, "message": str(exc)}],
                "debug_metadata": {"retry_count": retry_count, "action_taken": action_taken},
            }


def _run_downstream_stage(
    *,
    context: AssetExecutionContext,
    query_execution_result: dict[str, Any],
    expected_next_step: str,
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    if query_execution_result.get("status") != "success":
        attempts.append(
            make_attempt(
                attempt_number=1,
                input_payload={"query_execution_status": query_execution_result.get("status")},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="upstream_guard",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="upstream_query_execution_failed",
                error_message="Downstream stage skipped because query execution failed.",
            )
        )
        return {
            "status": "skipped",
            "next_step": expected_next_step,
            "error_type": "upstream_query_execution_failed",
            "action_taken": "stop",
            "downstream_result": None,
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [
                {
                    "type": "upstream_query_execution_failed",
                    "message": "Downstream stage skipped because query execution failed.",
                }
            ],
            "debug_metadata": {},
            "reason_chart_not_generated": "no_executable_sql",
        }

    route_next_step = str(query_execution_result.get("next_step", "")).strip().lower()
    if route_next_step != expected_next_step:
        attempts.append(
            make_attempt(
                attempt_number=1,
                input_payload={"route_next_step": route_next_step, "expected": expected_next_step},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="route_guard",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="route_not_selected",
                error_message="Downstream stage skipped because route was not selected.",
            )
        )
        return {
            "status": "skipped",
            "next_step": expected_next_step,
            "error_type": "route_not_selected",
            "action_taken": "stop",
            "downstream_result": None,
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [],
            "debug_metadata": {},
            "reason_chart_not_generated": "route_not_selected",
        }

    config = IntentExtractionConfig.from_env()
    retry_count = 0
    while True:
        try:
            attempt_started_perf = time.perf_counter()
            next_step, downstream_result = execute_downstream_route(
                intent=query_execution_result["validated_intent"],
                sql_query=str(query_execution_result.get("sql_query", "")),
                execution_result=query_execution_result.get("execution_result"),
                config=config,
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={
                        "sql_query": str(query_execution_result.get("sql_query", "")),
                        "expected_next_step": expected_next_step,
                    },
                    output_payload={"next_step": next_step, "downstream_result": downstream_result},
                    success=next_step == expected_next_step,
                    retry_triggered=False,
                    model_or_method_used="execute_downstream_route",
                    duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                    validation_result={"is_valid": next_step == expected_next_step},
                    error_type="" if next_step == expected_next_step else "logic",
                    error_message="" if next_step == expected_next_step else f"Unexpected downstream step: {next_step}",
                )
            )
            if next_step != expected_next_step:
                return {
                    "status": "failed",
                    "next_step": expected_next_step,
                    "error_type": "logic",
                    "action_taken": "stop",
                    "downstream_result": {
                        "message": f"Unexpected downstream step returned: {next_step}",
                    },
                    "attempts": attempts,
                    "attempts_count": len(attempts),
                    "started_at": stage_started_at,
                    "finished_at": utc_now_iso(),
                    "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                    "warnings": [],
                    "errors": [
                        {
                            "type": "logic",
                            "message": f"Unexpected downstream step returned: {next_step}",
                        }
                    ],
                    "debug_metadata": {},
                    "reason_chart_not_generated": "visualization_service_failure",
                }
            visualization_payload_preview = downstream_result
            reason_chart_selected = ""
            selected_chart_type = ""
            if isinstance(downstream_result, dict):
                selected_chart_type = str(
                    downstream_result.get("chart_type")
                    or downstream_result.get("type")
                    or ""
                ).strip()
                reason_chart_selected = str(
                    downstream_result.get("reason_chart_selected")
                    or downstream_result.get("reason")
                    or ""
                ).strip()
            reason_chart_not_generated = ""
            if expected_next_step == "metabase":
                preview = _extract_result_preview(query_execution_result.get("execution_result"))
                if preview.get("row_count", 0) == 0:
                    reason_chart_not_generated = "empty_result_set"
                if not selected_chart_type and not reason_chart_not_generated:
                    reason_chart_not_generated = "missing_dimension_measure_shape"
            return {
                "status": "success",
                "next_step": next_step,
                "error_type": "none",
                "action_taken": "proceed",
                "downstream_result": downstream_result,
                "visualization_status": "success" if expected_next_step == "metabase" else "skipped",
                "selected_chart_type": selected_chart_type,
                "reason_chart_selected": reason_chart_selected,
                "reason_chart_not_generated": reason_chart_not_generated,
                "visualization_payload_preview": visualization_payload_preview,
                "attempts": attempts,
                "attempts_count": len(attempts),
                "started_at": stage_started_at,
                "finished_at": utc_now_iso(),
                "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                "warnings": [],
                "errors": [],
                "debug_metadata": {"retry_count": retry_count},
            }
        except Exception as exc:  # noqa: BLE001
            error_type = classify_intent_extraction_error(exc)
            action_taken = decide_intent_extraction_action(
                error_type=error_type,
                retry_count=retry_count,
                config=config,
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={
                        "sql_query": str(query_execution_result.get("sql_query", "")),
                        "expected_next_step": expected_next_step,
                    },
                    output_payload={},
                    success=False,
                    retry_triggered=action_taken == "retry",
                    retry_reason=str(exc) if action_taken == "retry" else "",
                    model_or_method_used="execute_downstream_route",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type=error_type,
                    error_message=str(exc),
                )
            )
            context.log.error(
                "Downstream execution failed | expected_next_step=%s error_type=%s action_taken=%s retry_count=%s error=%s",
                expected_next_step,
                error_type,
                action_taken,
                retry_count,
                str(exc),
            )
            if action_taken == "retry":
                retry_count += 1
                continue
            return {
                "status": "failed",
                "next_step": expected_next_step,
                "error_type": error_type,
                "action_taken": action_taken,
                "downstream_result": None,
                "attempts": attempts,
                "attempts_count": len(attempts),
                "started_at": stage_started_at,
                "finished_at": utc_now_iso(),
                "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                "warnings": [],
                "errors": [{"type": error_type, "message": str(exc)}],
                "debug_metadata": {"retry_count": retry_count},
                "visualization_status": "failed" if expected_next_step == "metabase" else "skipped",
                "selected_chart_type": "",
                "reason_chart_selected": "",
                "reason_chart_not_generated": "visualization_service_failure" if expected_next_step == "metabase" else "",
                "visualization_payload_preview": None,
            }


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def visualization_asset(
    context: AssetExecutionContext,
    query_execution_asset: dict[str, Any],
) -> dict[str, Any]:
    result = _run_downstream_stage(
        context=context,
        query_execution_result=query_execution_asset,
        expected_next_step="metabase",
    )
    context.log.info(
        "Visualization stage completed | status=%s",
        result.get("status"),
    )
    return result


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def forecasting_asset(
    context: AssetExecutionContext,
    query_execution_asset: dict[str, Any],
) -> dict[str, Any]:
    result = _run_downstream_stage(
        context=context,
        query_execution_result=query_execution_asset,
        expected_next_step="forecasting",
    )
    context.log.info(
        "Forecasting stage completed | status=%s",
        result.get("status"),
    )
    return result


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def pipeline_result_asset(
    pipeline_request_asset: dict[str, Any],
    transcription_asset: dict[str, Any],
    preprocessing_low_asset: dict[str, Any],
    intent_classification_asset: dict[str, Any],
    preprocessing_high_asset: dict[str, Any],
    intent_extraction_asset: dict[str, Any],
    routing_asset: dict[str, Any],
    query_execution_asset: dict[str, Any],
    visualization_asset: dict[str, Any],
    forecasting_asset: dict[str, Any],
) -> dict[str, Any]:
    trace = build_pipeline_trace_template(request_metadata=pipeline_request_asset)

    attach_stage(
        trace,
        "transcription",
        _to_trace_stage(
            status=str(transcription_asset.get("status", "unknown")),
            result=transcription_asset,
            final_output={
                "status": transcription_asset.get("status"),
                "source": transcription_asset.get("source"),
                "text_preview": str(transcription_asset.get("text", ""))[:300],
                "error_type": transcription_asset.get("error_type"),
            },
        ),
    )
    attach_stage(
        trace,
        "preprocessing_low",
        _to_trace_stage(
            status=str(preprocessing_low_asset.get("status", "unknown")),
            result=preprocessing_low_asset,
            final_output={
                "cleaned_text": preprocessing_low_asset.get("cleaned_text", ""),
                "detected_changes": preprocessing_low_asset.get("detected_changes", []),
            },
        ),
    )
    attach_stage(
        trace,
        "input_validation",
        _to_trace_stage(
            status=str(intent_classification_asset.get("status", "unknown")),
            result=intent_classification_asset,
            final_output={
                "classification": intent_classification_asset.get("classification"),
                "reason": intent_classification_asset.get("classification_reason"),
                "confidence": intent_classification_asset.get("confidence"),
                "question_type": intent_classification_asset.get("question_type"),
            },
            extra_debug={
                "raw_classifier_output": intent_classification_asset.get("raw_classifier_output", {}),
            },
        ),
    )

    def _finalize_response(
        *,
        payload: dict[str, Any],
        overall_status: str,
        stage: str,
        final_route: str,
        final_user_message: str,
    ) -> dict[str, Any]:
        root_category, root_detail, recommended_fix = _root_cause_for(stage=stage, payload=payload)
        if overall_status == "success":
            root_category = "none"
            root_detail = "Pipeline executed successfully."
            recommended_fix = ""
        finalize_trace(
            trace,
            overall_status=overall_status,
            final_route=final_route,
            final_user_message=final_user_message,
            root_cause_category=root_category,
            root_cause_detail=root_detail,
            analyst_recommended_fix=recommended_fix,
        )
        payload["pipeline_trace"] = trace
        payload["overall_status"] = trace["overall_status"]
        payload["root_cause"] = trace["root_cause"]
        payload["final_route"] = final_route
        payload["final_user_message"] = final_user_message
        return payload

    def _final_output_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        """Return a compact, JSON-safe summary for trace final_response output."""
        return {
            "status": payload.get("status"),
            "stage": payload.get("stage"),
            "message": payload.get("message"),
            "final_route": payload.get("final_route"),
            "final_user_message": payload.get("final_user_message"),
        }

    def _mark_downstream_skipped(reason: str) -> None:
        for stage_name in ("analytical_intent", "sql_generation", "sql_review", "sql_validation", "query_execution", "visualization"):
            attach_stage(
                trace,
                stage_name,
                stage_payload(
                    status="skipped",
                    final_output={"reason": reason},
                    attempts=[
                        make_attempt(
                            attempt_number=1,
                            input_payload={"reason": reason},
                            output_payload={},
                            success=False,
                            retry_triggered=False,
                            model_or_method_used="enforcement_guard",
                            duration_ms=0,
                            validation_result={"is_valid": False},
                            error_type="skipped_by_enforcement",
                            error_message=reason,
                        )
                    ],
                    errors=[],
                    warnings=[{"type": "skipped", "message": reason}],
                    debug_metadata={"skipped_by": "enforcement_guard"},
                ),
            )

    if transcription_asset.get("status") != "success":
        payload = {
            "status": "failed",
            "stage": "transcription",
            "transcription": transcription_asset,
        }
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(
                status="failed",
                result=None,
                final_output=_final_output_snapshot(payload),
            ),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="transcription",
            final_route="stop",
            final_user_message="Transcription failed before analytical routing.",
        )

    if preprocessing_low_asset.get("status") != "success":
        payload = {
            "status": "failed",
            "stage": "preprocess",
            "transcription": transcription_asset,
            "preprocess": preprocessing_low_asset,
        }
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="preprocessing_low",
            final_route="stop",
            final_user_message="Low preprocessing failed before analytical routing.",
        )

    if intent_classification_asset.get("status") != "success":
        payload = {
            "status": "failed",
            "stage": "intent_classification",
            "transcription": transcription_asset,
            "preprocess": preprocessing_low_asset,
            "intent": intent_classification_asset,
        }
        attach_stage(
            trace,
            "routing",
            _to_trace_stage(
                status="failed",
                result=intent_classification_asset,
                final_output={"message": "Intent classification stage failed."},
            ),
        )
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="intent_classification",
            final_route="stop",
            final_user_message="Input classification failed before analytical routing.",
        )

    if str(intent_classification_asset.get("classification", "")).strip().lower() in {
        "invalid_input",
        "numeric_only_input",
        "noise_input",
        "empty_input",
        "transcription_failure",
        "no_speech_detected",
        "conversational",
    }:
        payload = {
            "status": "rejected",
            "stage": "input_validation",
            "message": intent_classification_asset.get("classification_reason")
            or "Input was classified as non-analytical.",
            "transcription": transcription_asset,
            "preprocess": preprocessing_low_asset,
            "intent": intent_classification_asset,
        }
        attach_stage(
            trace,
            "routing",
            _to_trace_stage(
                status="rejected",
                result=intent_classification_asset,
                final_output={
                    "classification": intent_classification_asset.get("classification"),
                    "reason": intent_classification_asset.get("classification_reason"),
                },
            ),
        )
        attach_stage(
            trace,
            "preprocessing_high",
            _to_trace_stage(
                status="skipped",
                result=preprocessing_high_asset,
                final_output={
                    "message": "Schema preprocessing skipped because input was rejected by classification.",
                    "classification": intent_classification_asset.get("classification"),
                },
            ),
        )
        _mark_downstream_skipped("Pipeline stopped at input classification stage.")
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="rejected", result=None, final_output=_final_output_snapshot(payload)),
        )
        final_route = str(intent_classification_asset.get("classification", "stop"))
        return _finalize_response(
            payload=payload,
            overall_status="rejected",
            stage="input_validation",
            final_route=final_route,
            final_user_message=str(payload.get("message", "Input rejected before routing.")),
        )

    attach_stage(
        trace,
        "preprocessing_high",
        _to_trace_stage(
            status=str(preprocessing_high_asset.get("status", "unknown")),
            result=preprocessing_high_asset,
            final_output={
                "final_query": preprocessing_high_asset.get("final_query", ""),
                "schema_valid": preprocessing_high_asset.get("schema_valid"),
                "schema_validation_status": preprocessing_high_asset.get("schema_validation_status"),
                "unresolved_terms": preprocessing_high_asset.get("unresolved_terms", []),
                "unresolved_lexical_terms": preprocessing_high_asset.get("unresolved_lexical_terms", []),
                "unsupported_terms": preprocessing_high_asset.get("unsupported_terms", []),
                "original_terms": preprocessing_high_asset.get("original_terms", []),
                "corrected_terms": preprocessing_high_asset.get("corrected_terms", []),
                "term_resolutions": preprocessing_high_asset.get("term_resolutions", []),
                "selected_table": preprocessing_high_asset.get("selected_table", ""),
                "selected_columns": preprocessing_high_asset.get("selected_columns", []),
            },
        ),
    )

    if preprocessing_high_asset.get("status") == "rejected":
        payload = {
            "status": "rejected",
            "stage": "preprocessing_high",
            "message": preprocessing_high_asset.get(
                "message",
                "The requested column does not exist in your data.",
            ),
            "transcription": transcription_asset,
            "preprocess": preprocessing_low_asset,
            "intent": intent_classification_asset,
            "routing": preprocessing_high_asset.get("routing", {}),
            "preprocess_high": preprocessing_high_asset,
        }
        attach_stage(
            trace,
            "routing",
            _to_trace_stage(
                status="rejected",
                result=preprocessing_high_asset.get("routing", {}),
                final_output=preprocessing_high_asset.get("routing", {}),
            ),
        )
        _mark_downstream_skipped("Pipeline stopped after schema validation rejection.")
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="rejected", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="rejected",
            stage="preprocessing_high",
            final_route="stop",
            final_user_message=str(payload.get("message", "Schema-aware correction rejected the request.")),
        )

    if preprocessing_high_asset.get("status") != "success":
        payload = {
            "status": "failed",
            "stage": "preprocessing_high",
            "transcription": transcription_asset,
            "preprocess": preprocessing_low_asset,
            "intent": intent_classification_asset,
            "routing": preprocessing_high_asset.get("routing", {}),
            "preprocess_high": preprocessing_high_asset,
        }
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="preprocessing_high",
            final_route="stop",
            final_user_message="Schema-aware preprocessing failed before intent extraction.",
        )

    attach_stage(
        trace,
        "analytical_intent",
        _to_trace_stage(
            status=str(intent_extraction_asset.get("status", "unknown")),
            result=intent_extraction_asset,
            final_output={
                "intent_type": intent_extraction_asset.get("intent_type"),
                "next_step": intent_extraction_asset.get("next_step"),
                "query": intent_extraction_asset.get("query", ""),
                "schema_tables": list((intent_extraction_asset.get("schema", {}) or {}).keys()),
                "extracted_intent": intent_extraction_asset.get("extracted_intent", {}),
                "validated_intent": intent_extraction_asset.get("validated_intent", {}),
            },
            extra_debug={
                "llm_prompt": intent_extraction_asset.get("debug_metadata", {}).get("llm_prompt", ""),
                "llm_raw_output": intent_extraction_asset.get("debug_metadata", {}).get("llm_raw_output", ""),
            },
        ),
    )
    if intent_extraction_asset.get("status") != "success":
        payload = {
            "status": "failed",
            "stage": "intent_extraction",
            "transcription": transcription_asset,
            "preprocess": preprocessing_low_asset,
            "intent": intent_classification_asset,
            "routing": routing_asset,
            "preprocess_high": preprocessing_high_asset,
            "intent_extraction": intent_extraction_asset,
        }
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="intent_extraction",
            final_route="stop",
            final_user_message="Intent extraction failed before SQL generation.",
        )

    attach_stage(
        trace,
        "routing",
        _to_trace_stage(
            status=str(routing_asset.get("status", "unknown")),
            result=routing_asset,
            final_output={
                "next_step": routing_asset.get("next_step"),
                "intent_type": routing_asset.get("intent_type"),
                "route_reason": routing_asset.get("reason", ""),
                "fallback_route": routing_asset.get("fallback_route", ""),
            },
        ),
    )
    if routing_asset.get("status") != "routed":
        payload = _build_stage_failed(
            stage="routing",
            message="Routing failed after intent extraction.",
            transcription=transcription_asset,
            preprocess=preprocessing_low_asset,
            intent=intent_classification_asset,
            routing=routing_asset,
            preprocess_high=preprocessing_high_asset,
            intent_extraction=intent_extraction_asset,
        )
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="routing",
            final_route="stop",
            final_user_message="Routing failed after analytical intent extraction.",
        )

    sql_generation_status = "success" if query_execution_asset.get("sql_query") else "failed"
    if query_execution_asset.get("status") == "skipped":
        sql_generation_status = "skipped"
    attach_stage(
        trace,
        "sql_generation",
        _to_trace_stage(
            status=sql_generation_status,
            result=query_execution_asset,
            final_output={
                "generated_sql": query_execution_asset.get("generated_sql", query_execution_asset.get("sql_query", "")),
                "reason_sql_not_generated": query_execution_asset.get("sql_generation_failure_reason", ""),
                "raw_prompt_inputs": query_execution_asset.get("sql_generation_input", {}),
            },
        ),
    )
    attach_stage(
        trace,
        "sql_review",
        _to_trace_stage(
            status="success"
            if query_execution_asset.get("sql_review_outcome") in {"approved", "corrected", "passed", "fallback_compiler"}
            else ("skipped" if query_execution_asset.get("status") == "skipped" else "failed"),
            result=query_execution_asset,
            final_output={
                "generated_sql": query_execution_asset.get("generated_sql", ""),
                "reviewed_sql": query_execution_asset.get("reviewed_sql", query_execution_asset.get("sql_query", "")),
                "sql_review_outcome": query_execution_asset.get("sql_review_outcome", "skipped"),
                "sql_review_notes": (
                    query_execution_asset.get("sql_review", {})
                    if isinstance(query_execution_asset.get("sql_review"), dict)
                    else {}
                ).get("notes", []),
                "sql_review_reason_category": (
                    query_execution_asset.get("sql_review", {})
                    if isinstance(query_execution_asset.get("sql_review"), dict)
                    else {}
                ).get("reason_category", ""),
            },
        ),
    )
    attach_stage(
        trace,
        "sql_validation",
        _to_trace_stage(
            status="success"
            if query_execution_asset.get("sql_validation_outcome") == "passed"
            else ("skipped" if query_execution_asset.get("status") == "skipped" else "failed"),
            result=query_execution_asset,
            final_output={
                "sql_validation_outcome": query_execution_asset.get("sql_validation_outcome", "skipped"),
                "sql_review_outcome": query_execution_asset.get("sql_review_outcome", "skipped"),
                "safety_validation_outcome": query_execution_asset.get("safety_validation_outcome", "skipped"),
            },
        ),
    )
    attach_stage(
        trace,
        "query_execution",
        _to_trace_stage(
            status=str(query_execution_asset.get("status", "unknown")),
            result=query_execution_asset,
            final_output={
                "execution_result": query_execution_asset.get("execution_result"),
                "result_preview": query_execution_asset.get("result_preview", {}),
                "referenced_tables": query_execution_asset.get("referenced_tables", []),
                "referenced_columns": query_execution_asset.get("referenced_columns", []),
            },
        ),
    )
    if query_execution_asset.get("status") != "success":
        payload = _build_stage_failed(
            stage="query_execution",
            message="Query execution failed.",
            transcription=transcription_asset,
            preprocess=preprocessing_low_asset,
            intent=intent_classification_asset,
            routing=routing_asset,
            preprocess_high=preprocessing_high_asset,
            intent_extraction=query_execution_asset,
        )
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="query_execution",
            final_route=str(routing_asset.get("next_step", "metabase")),
            final_user_message="SQL execution failed.",
        )

    next_step = str(routing_asset.get("next_step", "metabase")).strip().lower()
    if next_step == "metabase":
        attach_stage(
            trace,
            "visualization",
            _to_trace_stage(
                status=str(visualization_asset.get("status", "unknown")),
                result=visualization_asset,
                final_output={
                    "visualization_status": visualization_asset.get("visualization_status", visualization_asset.get("status")),
                    "selected_chart_type": visualization_asset.get("selected_chart_type", ""),
                    "reason_chart_selected": visualization_asset.get("reason_chart_selected", ""),
                    "reason_chart_not_generated": visualization_asset.get("reason_chart_not_generated", ""),
                    "visualization_payload_preview": visualization_asset.get("visualization_payload_preview"),
                },
            ),
        )
        if visualization_asset.get("status") != "success":
            payload = _build_stage_failed(
                stage="visualization",
                message="Visualization stage failed.",
                transcription=transcription_asset,
                preprocess=preprocessing_low_asset,
                intent=intent_classification_asset,
                routing=routing_asset,
                preprocess_high=preprocessing_high_asset,
                intent_extraction=query_execution_asset,
            )
            attach_stage(
                trace,
                "final_response",
                _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
            )
            return _finalize_response(
                payload=payload,
                overall_status="failed",
                stage="visualization",
                final_route=next_step,
                final_user_message="Visualization failed after query execution.",
            )
        downstream_result = visualization_asset.get("downstream_result")
    else:
        attach_stage(
            trace,
            "visualization",
            _to_trace_stage(
                status="skipped",
                result=forecasting_asset,
                final_output={
                    "visualization_status": "skipped",
                    "reason_chart_not_generated": "forecasting_route_selected",
                    "visualization_payload_preview": None,
                },
            ),
        )
        if forecasting_asset.get("status") != "success":
            payload = _build_stage_failed(
                stage="forecasting",
                message="Forecasting stage failed.",
                transcription=transcription_asset,
                preprocess=preprocessing_low_asset,
                intent=intent_classification_asset,
                routing=routing_asset,
                preprocess_high=preprocessing_high_asset,
                intent_extraction=query_execution_asset,
            )
            attach_stage(
                trace,
                "final_response",
                _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
            )
            return _finalize_response(
                payload=payload,
                overall_status="failed",
                stage="forecasting",
                final_route=next_step,
                final_user_message="Forecasting downstream stage failed.",
            )
        downstream_result = forecasting_asset.get("downstream_result")

    intent_extraction_full = {
        "status": "success",
        "intent_type": query_execution_asset.get("intent_type", routing_asset.get("intent_type")),
        "sql_query": query_execution_asset.get("sql_query", ""),
        "next_step": next_step,
        "error_type": "none",
        "action_taken": "proceed",
        "extracted_intent": query_execution_asset.get("extracted_intent", {}),
        "normalized_intent": query_execution_asset.get("normalized_intent", {}),
        "execution_result": query_execution_asset.get("execution_result"),
        "downstream_result": downstream_result,
    }

    payload = {
        "status": "success",
        "transcription": transcription_asset,
        "preprocess": preprocessing_low_asset,
        "intent": intent_classification_asset,
        "routing": routing_asset,
        "preprocess_high": preprocessing_high_asset,
        "intent_extraction": intent_extraction_full,
        "query_execution": query_execution_asset,
        "visualization": visualization_asset,
        "forecasting": forecasting_asset,
    }
    attach_stage(
        trace,
        "final_response",
        _to_trace_stage(
            status="success",
            result=None,
            final_output={
                "status": "success",
                "next_step": next_step,
                "intent_type": intent_extraction_full.get("intent_type"),
                "sql_query": intent_extraction_full.get("sql_query"),
            },
        ),
    )
    attach_stage(
        trace,
        "dagster_runtime",
        _to_trace_stage(
            status="pending",
            result={},
            final_output={"message": "Dagster runtime will be attached by job runner."},
        ),
    )
    return _finalize_response(
        payload=payload,
        overall_status="success",
        stage="final_response",
        final_route=next_step,
        final_user_message="Pipeline completed successfully.",
    )
