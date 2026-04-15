import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dagster_pipeline.jobs import run_full_ai_pipeline


@csrf_exempt
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

    pipeline_result = run_full_ai_pipeline(text=question, user_id=(user_id or None))

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
    intent = (
        pipeline_result.get("intent_extraction", {})
        if isinstance(pipeline_result.get("intent_extraction"), dict)
        else {}
    )

    if str(pipeline_result.get("status", "")).strip().lower() == "success":
        normalized_intent = (
            query_execution.get("normalized_intent", {})
            if isinstance(query_execution.get("normalized_intent"), dict)
            else {}
        )
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
            "chart": visualization.get("downstream_result"),
            "confidence": (
                pipeline_result.get("intent", {})
                if isinstance(pipeline_result.get("intent"), dict)
                else {}
            ).get("confidence", 0.5),
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
