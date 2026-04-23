from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

MAX_TRACE_SAMPLE_ROWS = 10
ANALYTICAL_TYPES = {"analytical", "predictive", "forecast", "forecasting"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _safe_list(payload: Any) -> list[Any]:
    return payload if isinstance(payload, list) else []


def _normalize_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"success", "completed", "done", "approved", "passed", "routed"}:
        return "success"
    if normalized in {"degraded", "fallback", "partial"}:
        return "degraded"
    if normalized in {"failed", "error", "rejected"}:
        return "error"
    if normalized in {"skipped", "not_started", "pending", "unknown", ""}:
        return "skipped"
    return "warning"


def _sample_rows(rows: Any, limit: int = MAX_TRACE_SAMPLE_ROWS) -> list[dict[str, Any]]:
    sampled: list[dict[str, Any]] = []
    for row in _safe_list(rows)[: max(1, min(limit, MAX_TRACE_SAMPLE_ROWS))]:
        if isinstance(row, dict):
            sampled.append(row)
    return sampled


def _extract_stage(trace: dict[str, Any], stage_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    stage_payload = _safe_dict(trace.get(stage_name))
    final_output = _safe_dict(stage_payload.get("final_output"))
    return stage_payload, final_output


def _normalize_question_type(
    intent_json: dict[str, Any],
    classification_final: dict[str, Any],
    routing_final: dict[str, Any],
    forecasting_payload: dict[str, Any],
) -> str:
    candidates = [
        intent_json.get("question_type"),
        classification_final.get("question_type"),
        classification_final.get("classification"),
        routing_final.get("intent_type"),
        routing_final.get("next_step"),
    ]
    normalized_candidates = [str(candidate or "").strip().lower() for candidate in candidates]
    if any(candidate in {"predictive", "forecast", "forecasting"} for candidate in normalized_candidates):
        return "predictive"
    if any(candidate == "analytical" for candidate in normalized_candidates):
        return "analytical"
    if any(candidate in {"conversational", "informational", "invalid_input", "noise_input", "empty_input"} for candidate in normalized_candidates):
        return "non_analytical"

    if forecasting_payload.get("enabled") and forecasting_payload.get("request", {}).get("requires_forecast"):
        return "predictive"

    return "analytical" if intent_json else "non_analytical"


def _extract_forecasting(
    *,
    chart_config: dict[str, Any],
    query_result: dict[str, Any],
    question_type: str,
) -> dict[str, Any] | None:
    forecasting_payload = _safe_dict(chart_config.get("forecasting"))
    request_payload = _safe_dict(forecasting_payload.get("request"))
    meta_payload = _safe_dict(forecasting_payload.get("meta"))
    error_payload = _safe_dict(forecasting_payload.get("error"))

    requires_forecast = bool(
        request_payload.get("requires_forecast")
        or question_type == "predictive"
    )

    if not requires_forecast:
        return None

    rows = _safe_list(query_result.get("rows"))
    actual_rows = [row for row in rows if isinstance(row, dict) and row.get("series_type") == "actual"]
    forecast_rows = [row for row in rows if isinstance(row, dict) and row.get("series_type") == "forecast"]

    frequency_seconds = meta_payload.get("frequency_seconds")
    granularity = ""
    if isinstance(frequency_seconds, int) and frequency_seconds > 0:
        if frequency_seconds % 86400 == 0:
            days = frequency_seconds // 86400
            granularity = "daily" if days == 1 else f"{days}-day"
        elif frequency_seconds % 3600 == 0:
            hours = frequency_seconds // 3600
            granularity = "hourly" if hours == 1 else f"{hours}-hour"
        else:
            granularity = f"{frequency_seconds}-second"

    status = str(forecasting_payload.get("status") or "skipped").strip().lower()
    normalized_status = "success" if status == "success" else ("failed" if status == "failed" else "skipped")

    validation_notes: list[str] = []
    if normalized_status == "failed":
        message = str(error_payload.get("message") or "").strip()
        code = str(error_payload.get("code") or "").strip()
        if message:
            validation_notes.append(message)
        if code:
            validation_notes.append(f"code: {code}")
        details = _safe_dict(error_payload.get("details"))
        if details:
            validation_notes.append(f"details: {details}")

    return {
        "requires_forecast": True,
        "forecast_status": normalized_status,
        "fallback": str(forecasting_payload.get("fallback") or ""),
        "reason": str(forecasting_payload.get("reason") or ""),
        "detected_time_column": str(meta_payload.get("time_column") or ""),
        "detected_value_column": str(meta_payload.get("value_column") or ""),
        "horizon": int(meta_payload.get("horizon") or request_payload.get("horizon") or 0) or None,
        "granularity": granularity,
        "validation_notes": validation_notes,
        "model_used": "TimesFM",
        "historical_series_sample": _sample_rows(actual_rows),
        "forecast_output_sample": _sample_rows(forecast_rows),
        "merged_dataset_sample": _sample_rows(rows),
    }


def _collect_errors(
    *,
    trace: dict[str, Any],
    report_error_message: str,
    forecasting_trace: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    stage_names = [
        "classification",
        "input_validation",
        "preprocessing_low",
        "routing",
        "preprocessing_high",
        "intent_extraction",
        "predictive_intent",
        "sql_generation",
        "sql_review",
        "query_execution",
        "forecasting",
        "visualization",
    ]
    for stage_name in stage_names:
        stage_payload = _safe_dict(trace.get(stage_name))
        for error in _safe_list(stage_payload.get("errors")):
            if not isinstance(error, dict):
                continue
            collected.append(
                {
                    "stage": stage_name,
                    "message": str(error.get("message") or "Unknown error").strip(),
                    "type": str(error.get("type") or "unknown").strip(),
                    "fallback_applied": False,
                }
            )

    if forecasting_trace and forecasting_trace.get("forecast_status") == "failed":
        notes = _safe_list(forecasting_trace.get("validation_notes"))
        collected.append(
            {
                "stage": "forecasting",
                "message": str(notes[0] if notes else "Forecasting failed").strip(),
                "type": "forecasting_error",
                "fallback_applied": True,
            }
        )

    normalized_error_message = str(report_error_message or "").strip()
    lowered_error_message = normalized_error_message.lower()
    looks_like_error = any(
        token in lowered_error_message
        for token in ("error", "failed", "failure", "exception", "timeout", "unavailable", "invalid")
    )
    if normalized_error_message and looks_like_error:
        collected.append(
            {
                "stage": "execution",
                "message": normalized_error_message,
                "type": "runtime_error",
                "fallback_applied": False,
            }
        )

    return collected


def _extract_preprocessing_corrections(preprocess_high: dict[str, Any]) -> list[dict[str, str]]:
    explicit = _safe_list(preprocess_high.get("term_corrections"))
    normalized: list[dict[str, str]] = []

    for item in explicit:
        if not isinstance(item, dict):
            continue
        source = str(item.get("from") or item.get("source") or "").strip()
        target = str(item.get("to") or item.get("target") or "").strip()
        if not source or not target or source == target:
            continue
        normalized.append({"from": source, "to": target, "type": str(item.get("type") or "").strip()})

    if normalized:
        return normalized

    for item in _safe_list(preprocess_high.get("term_resolutions")):
        if not isinstance(item, dict):
            continue
        status = str(item.get("resolution_status") or "").strip().lower()
        if status not in {"corrected_typo", "semantic_match"}:
            continue
        source = str(item.get("term") or "").strip()
        target = str(item.get("matched_column") or "").strip()
        if not source or not target or source == target:
            continue
        normalized.append({"from": source, "to": target, "type": status})

    return normalized


def build_ai_trace_payload(
    *,
    report_id: int | None,
    transcription: str,
    preprocessing_low: dict[str, Any] | None,
    preprocessing_high: dict[str, Any] | None,
    intent_json: dict[str, Any] | None,
    pipeline_trace: dict[str, Any] | None,
    generated_sql: str,
    reviewed_sql: str,
    query_result: dict[str, Any] | None,
    execution_time_ms: int | None,
    row_count: int | None,
    chart_type: str,
    metabase_question_id: int | None,
    metabase_dashboard_id: int | None,
    embed_url: str,
    chart_config: dict[str, Any] | None,
    error_message: str,
) -> dict[str, Any]:
    normalized_pre_low = _safe_dict(preprocessing_low)
    normalized_pre_high = _safe_dict(preprocessing_high)
    normalized_intent = _safe_dict(intent_json)
    normalized_trace = _safe_dict(pipeline_trace)
    normalized_result = _safe_dict(query_result)
    normalized_chart_config = _safe_dict(chart_config)

    classification_stage, classification_final = _extract_stage(normalized_trace, "classification")
    if not classification_stage:
        classification_stage, classification_final = _extract_stage(normalized_trace, "input_validation")
    intent_stage, intent_final = _extract_stage(normalized_trace, "intent_extraction")
    if not intent_stage:
        intent_stage, intent_final = _extract_stage(normalized_trace, "analytical_intent")
    routing_stage, routing_final = _extract_stage(normalized_trace, "routing")
    pre_high_stage, pre_high_final = _extract_stage(normalized_trace, "preprocessing_high")
    predictive_stage, predictive_final = _extract_stage(normalized_trace, "predictive_intent")
    sql_generation_stage, sql_generation_final = _extract_stage(normalized_trace, "sql_generation")
    sql_review_stage, sql_review_final = _extract_stage(normalized_trace, "sql_review")
    query_execution_stage, query_execution_final = _extract_stage(normalized_trace, "query_execution")
    visualization_stage, _ = _extract_stage(normalized_trace, "visualization")

    question_type = _normalize_question_type(
        normalized_intent,
        classification_final,
        routing_final,
        _safe_dict(normalized_chart_config.get("forecasting")),
    )
    requires_forecast = bool(
        classification_final.get("requires_forecast")
        or normalized_intent.get("requires_forecast")
        or str(routing_final.get("next_step") or "").strip().lower() == "forecasting"
        or question_type == "predictive"
    )
    if requires_forecast:
        question_type = "predictive"
    is_analytical = question_type in {"analytical", "predictive"}
    preprocessing_high_status = _normalize_status(pre_high_stage.get("status") or "skipped")
    preprocessing_high_failed = preprocessing_high_status == "error"

    extracted_intent = _safe_dict(intent_final.get("extracted_intent")) or normalized_intent
    validated_intent = _safe_dict(intent_final.get("validated_intent"))

    columns = [str(column) for column in _safe_list(normalized_result.get("columns")) if str(column).strip()]
    rows = _safe_list(normalized_result.get("rows"))
    sampled_rows = _sample_rows(rows)
    normalized_row_count = int(row_count or len(rows))

    forecasting_trace = _extract_forecasting(
        chart_config=normalized_chart_config,
        query_result=normalized_result,
        question_type=question_type,
    )

    sql_review_notes = sql_review_final.get("sql_review_notes")
    if not isinstance(sql_review_notes, list):
        sql_review_notes = _safe_list(_safe_dict(sql_review_final.get("sql_review")).get("notes"))
    sql_review_notes = [str(note) for note in sql_review_notes if str(note).strip()]
    preprocessing_corrections = _extract_preprocessing_corrections(normalized_pre_high)
    classification_status = _normalize_status(classification_stage.get("status") or "unknown")
    classification_error = classification_status == "error"
    # If high preprocessing succeeded (including typo recovery), do not mark classification as an error.
    if preprocessing_high_status == "success":
        classification_error = False

    trace = {
        "report_id": report_id,
        "stage_order": [
            "original_question",
            "preprocessing_low",
            "classification",
            "routing",
            "preprocessing_high",
            "predictive_intent",
            "intent_extraction",
            "sql",
            "execution",
            "forecasting",
            "visualization",
        ],
        "original_question": {
            "text": str(transcription or ""),
            "status": "success",
        },
        "preprocessing_low": {
            "status": _normalize_status(_safe_dict(normalized_trace.get("preprocessing_low")).get("status") or "success"),
            "original_text": str(normalized_pre_low.get("original_text") or transcription or ""),
            "cleaned_text": str(normalized_pre_low.get("cleaned_text") or transcription or ""),
            "detected_changes": _safe_list(normalized_pre_low.get("changes") or normalized_pre_low.get("detected_changes")),
        },
        "classification": {
            "status": classification_status,
            "is_analytical": bool(is_analytical),
            "is_predictive": bool(question_type == "predictive"),
            "error": classification_error,
            "error_reason": str(
                classification_stage.get("message")
                or classification_final.get("message")
                or (pre_high_stage.get("message") if preprocessing_high_failed else "")
                or (pre_high_final.get("message") if preprocessing_high_failed else "")
                or ""
            ),
            "question_type": question_type,
            "requires_forecast": requires_forecast,
            "confidence": classification_final.get("confidence") or normalized_intent.get("confidence") or None,
            "reasoning": str(
                classification_final.get("reason")
                or classification_final.get("message")
                or normalized_intent.get("classification_reason")
                or ""
            ),
        },
        "routing": {
            "status": _normalize_status(routing_stage.get("status") or "unknown"),
            "route": str(
                routing_final.get("classification_route")
                or _safe_dict(normalized_pre_high.get("routing_decision")).get("route")
                or ("forecasting" if question_type == "predictive" else "analytical")
            ),
            "next_step": str(routing_final.get("next_step") or ""),
            "reason": str(routing_final.get("route_reason") or routing_final.get("reason") or ""),
            "fallback_route": str(routing_final.get("fallback_route") or ""),
            "message": str(_safe_dict(routing_stage).get("message") or ""),
        },
        "preprocessing_high": {
            "status": preprocessing_high_status,
            "corrected_query": str(normalized_pre_high.get("corrected_query") or normalized_pre_high.get("final_query") or ""),
            "corrections": preprocessing_corrections,
            "term_corrections": _safe_list(normalized_pre_high.get("term_corrections")),
            "skipped_schema_terms": _safe_list(normalized_pre_high.get("skipped_schema_terms")),
            "schema_used": _safe_dict(normalized_pre_high.get("schema_used")),
            "selected_table": str(normalized_pre_high.get("selected_table") or ""),
            "selected_columns": [
                str(column)
                for column in _safe_list(normalized_pre_high.get("selected_columns"))
                if str(column).strip()
            ],
            "routing_decision": _safe_dict(normalized_pre_high.get("routing_decision")),
            "skipped_reason": (
                "predictive_route_selected"
                if question_type == "predictive"
                else str(pre_high_stage.get("message") or "")
            ),
            "user_friendly_messages": _safe_list(normalized_pre_high.get("user_friendly_messages")),
        },
        "predictive_intent": {
            "status": (
                _normalize_status(predictive_stage.get("status") or intent_stage.get("status") or "unknown")
                if question_type == "predictive"
                else "skipped"
            ),
            "intent_type": str(
                predictive_final.get("intent_type")
                or intent_final.get("intent_type")
                or normalized_intent.get("intent_type")
                or ""
            ),
            "metric": str(
                predictive_final.get("metric")
                or extracted_intent.get("metric")
                or validated_intent.get("metric")
                or ""
            ),
            "time_column": str(
                predictive_final.get("time_column")
                or extracted_intent.get("time_column")
                or validated_intent.get("time_column")
                or ""
            ),
            "horizon": (
                predictive_final.get("horizon")
                or extracted_intent.get("horizon")
                or extracted_intent.get("forecast_horizon")
            ),
            "granularity": str(
                predictive_final.get("granularity")
                or extracted_intent.get("granularity")
                or ""
            ),
            "skipped_reason": "" if question_type == "predictive" else "analytical_route_selected",
        },
        "intent_extraction": {
            "status": _normalize_status(intent_stage.get("status") or routing_stage.get("status") or "unknown"),
            "intent_type": str(routing_final.get("intent_type") or intent_final.get("intent_type") or normalized_intent.get("intent_type") or ""),
            "extracted_intent": extracted_intent,
            "validated_intent": validated_intent,
            "routing_decision": {
                "next_step": str(routing_final.get("next_step") or ""),
                "reason": str(routing_final.get("route_reason") or routing_final.get("reason") or ""),
                "fallback_route": str(routing_final.get("fallback_route") or ""),
            },
            "ambiguities": _safe_list(validated_intent.get("ambiguities")),
        },
        "sql": {
            "status": _normalize_status(sql_review_stage.get("status") or sql_generation_stage.get("status") or "unknown"),
            "generated_sql": str(generated_sql or sql_generation_final.get("generated_sql") or ""),
            "reviewed_sql": str(reviewed_sql or sql_review_final.get("reviewed_sql") or ""),
            "sql_review_notes": sql_review_notes,
            "historical_sql_only": bool(_safe_dict(sql_generation_final).get("historical_sql_only")),
        },
        "execution": {
            "status": _normalize_status(query_execution_stage.get("status") or "unknown"),
            "execution_time_ms": int(execution_time_ms or 0) if execution_time_ms is not None else None,
            "row_count": normalized_row_count,
            "columns": columns,
            "sample_rows": sampled_rows,
        },
        "visualization": {
            "status": _normalize_status(visualization_stage.get("status") or "unknown"),
            "chart_type": str(chart_type or _safe_dict(visualization_stage.get("final_output")).get("selected_chart_type") or ""),
            "metabase_question_id": metabase_question_id,
            "metabase_dashboard_id": metabase_dashboard_id,
            "embed_url": str(embed_url or ""),
        },
        "errors": [],
        "meta": {
            "sample_limit": MAX_TRACE_SAMPLE_ROWS,
            "generated_at": _now_iso(),
        },
    }

    if forecasting_trace:
        trace["forecasting"] = forecasting_trace

    trace["errors"] = _collect_errors(
        trace=normalized_trace,
        report_error_message=error_message,
        forecasting_trace=forecasting_trace,
    )

    return trace
