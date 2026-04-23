import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dagster_pipeline.jobs import run_full_ai_pipeline
from shared.internal_api_auth import require_internal_api_key


def _load_forecasting_symbols():
    try:
        from forecasting.pipeline import ForecastingError, build_forecast_dataset, detect_forecast_request
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Forecasting module not found. Check PYTHONPATH and container mount."
        ) from exc
    return ForecastingError, build_forecast_dataset, detect_forecast_request


@csrf_exempt
@require_internal_api_key
def intent_test_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    question = (data.get("question") or "").strip()
    if not question:
        return JsonResponse({"error": "No question provided"}, status=400)
    user_id = (data.get("user_id") or "").strip()
    manager_id = (data.get("manager_id") or "").strip()
    dataset_id = (data.get("dataset_id") or "").strip()
    source_id = (data.get("source_id") or "").strip()
    workspace_id = (data.get("workspace_id") or "").strip()
    report_id = (data.get("report_id") or "").strip()
    table_name = (data.get("table_name") or "").strip()

    pipeline_result = run_full_ai_pipeline(
        text=question,
        user_id=(user_id or None),
        manager_id=(manager_id or user_id or None),
        dataset_id=(dataset_id or None),
        source_id=(source_id or None),
        workspace_id=(workspace_id or None),
        report_id=(report_id or None),
        table_name=(table_name or None),
    )

    preprocess_low = (
        pipeline_result.get("preprocess", {})
        if isinstance(pipeline_result.get("preprocess"), dict)
        else {}
    )
    preprocess_high = (
        pipeline_result.get("preprocess_high", {})
        if isinstance(pipeline_result.get("preprocess_high"), dict)
        else {}
    )
    query_execution = (
        pipeline_result.get("query_execution", {})
        if isinstance(pipeline_result.get("query_execution"), dict)
        else {}
    )
    visualization = (
        pipeline_result.get("visualization", {})
        if isinstance(pipeline_result.get("visualization"), dict)
        else {}
    )
    forecasting = (
        pipeline_result.get("forecasting", {})
        if isinstance(pipeline_result.get("forecasting"), dict)
        else {}
    )
    final_route = str(pipeline_result.get("final_route", "")).strip().lower()
    selected_chart_type = str(visualization.get("selected_chart_type", "")).strip().lower()
    reason_chart_selected = str(visualization.get("reason_chart_selected", "")).strip()
    chart_payload = visualization.get("downstream_result")
    if selected_chart_type:
        base_payload = chart_payload if isinstance(chart_payload, dict) else {}
        chart_payload = {
            **base_payload,
            "type": selected_chart_type,
            "chart_type": selected_chart_type,
            "reason_chart_selected": reason_chart_selected or str(base_payload.get("reason_chart_selected", "")).strip(),
        }
    if final_route == "forecasting" and not chart_payload:
        downstream = forecasting.get("downstream_result", {}) if isinstance(forecasting.get("downstream_result"), dict) else {}
        chart_payload = downstream.get("visualization_payload")
    intent = (
        pipeline_result.get("intent_extraction", {})
        if isinstance(pipeline_result.get("intent_extraction"), dict)
        else {}
    )

    if str(pipeline_result.get("status", "")).strip().lower() in {"success", "degraded"}:
        normalized_intent = (
            query_execution.get("normalized_intent", {})
            if isinstance(query_execution.get("normalized_intent"), dict)
            else {}
        )
        classification_payload = (
            pipeline_result.get("intent", {})
            if isinstance(pipeline_result.get("intent"), dict)
            else {}
        )
        route_name = str(pipeline_result.get("final_route", "")).strip().lower()
        if isinstance(normalized_intent, dict):
            normalized_intent = {
                **normalized_intent,
                "question_type": (
                    str(classification_payload.get("question_type") or "").strip().lower()
                    or ("predictive" if route_name == "forecasting" else "analytical")
                ),
                "requires_forecast": bool(
                    classification_payload.get("requires_forecast")
                    or route_name == "forecasting"
                    or str(normalized_intent.get("intent_type", "")).strip().lower() == "predictive"
                ),
            }
        validated_intent = (
            intent.get("validated_intent", {})
            if isinstance(intent.get("validated_intent"), dict)
            else {}
        )
        payload = {
            "error": False,
            "intent": normalized_intent or validated_intent,
            "validated_intent": validated_intent,
            "sql": query_execution.get("sql_query", ""),
            "generated_sql": query_execution.get("generated_sql", query_execution.get("sql_query", "")),
            "reviewed_sql": query_execution.get("reviewed_sql", query_execution.get("sql_query", "")),
            "sql_review": query_execution.get("sql_review", {}),
            "chart": chart_payload,
            "confidence": pipeline_result.get(
                "confidence",
                (
                    pipeline_result.get("intent", {})
                    if isinstance(pipeline_result.get("intent"), dict)
                    else {}
                ).get("confidence", 0.5),
            ),
            "confidence_breakdown": pipeline_result.get("confidence_breakdown"),
            "raw_intent": intent.get("extracted_intent", {}),
            "preprocessing_low": preprocess_low,
            "preprocessing_high": preprocess_high,
            "pipeline_trace": pipeline_result.get("pipeline_trace"),
            "overall_status": pipeline_result.get("overall_status"),
            "root_cause": pipeline_result.get("root_cause"),
            "dagster_runtime": pipeline_result.get("dagster_runtime"),
            "final_route": pipeline_result.get("final_route"),
            "final_user_message": pipeline_result.get("final_user_message"),
        }
        return JsonResponse(payload)

    payload = {
        "error": True,
        "error_code": pipeline_result.get("stage", "pipeline_failed"),
        "message": pipeline_result.get("message", "Pipeline failed."),
        "stage": pipeline_result.get("stage", "pipeline"),
        "retryable": False,
        "details": pipeline_result,
        "preprocessing_low": preprocess_low,
        "preprocessing_high": preprocess_high,
        "pipeline_trace": pipeline_result.get("pipeline_trace"),
        "overall_status": pipeline_result.get("overall_status"),
        "root_cause": pipeline_result.get("root_cause"),
        "dagster_runtime": pipeline_result.get("dagster_runtime"),
        "final_route": pipeline_result.get("final_route"),
        "final_user_message": pipeline_result.get("final_user_message"),
    }
    if payload.get("error"):
        return JsonResponse(payload, status=422)
    return JsonResponse(payload)


@csrf_exempt
@require_internal_api_key
def forecast_detect_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    try:
        _, _, detect_forecast_request = _load_forecasting_symbols()
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=500)

    intent = data.get("intent", {})
    question_type = data.get("question_type")
    final_route = data.get("final_route")
    request_meta = detect_forecast_request(
        intent=intent if isinstance(intent, dict) else {},
        question_type=str(question_type or "").strip() or None,
        final_route=str(final_route or "").strip() or None,
    )
    return JsonResponse(
        {
            "requires_forecast": bool(request_meta.requires_forecast),
            "question_type": str(request_meta.question_type),
            "reason": str(request_meta.reason),
        }
    )


@csrf_exempt
@require_internal_api_key
def forecast_dataset_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    try:
        ForecastingError, build_forecast_dataset, _ = _load_forecasting_symbols()
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=500)

    columns = data.get("columns", [])
    rows = data.get("rows", [])
    intent = data.get("intent", {})
    horizon = data.get("horizon")

    try:
        result = build_forecast_dataset(
            columns=columns if isinstance(columns, list) else [],
            rows=rows if isinstance(rows, list) else [],
            intent=intent if isinstance(intent, dict) else {},
            horizon=horizon,
        )
        return JsonResponse(result)
    except ForecastingError as exc:
        return JsonResponse({"error": exc.to_dict()}, status=422)
