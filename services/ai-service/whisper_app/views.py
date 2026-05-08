import logging
import os
import tempfile

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from shared.internal_api_auth import require_internal_api_key
from whisper_app.transcription_task import whisper_transcription_preprocess_intent_flow

logger = logging.getLogger(__name__)


def _build_reasoning_from_pipeline(pipeline_result: dict) -> dict:
    status = str(pipeline_result.get("status", "")).strip().lower()
    intent_stage = pipeline_result.get("intent", {}) if isinstance(pipeline_result.get("intent"), dict) else {}
    routing_stage = pipeline_result.get("routing", {}) if isinstance(pipeline_result.get("routing"), dict) else {}
    classification = str(intent_stage.get("classification", "")).strip().lower()
    question_type = classification or ("analytical" if status in {"success", "degraded"} else "error")
    route = str(routing_stage.get("next_step", "")).strip().lower()

    needs_sql = classification in {"analytical", "predictive", "forecast", "forecasting"} or status in {"success", "degraded"}
    needs_chart = needs_sql and route in {"metabase", "forecasting"}
    message = str(
        pipeline_result.get("final_user_message")
        or pipeline_result.get("message")
        or ""
    ).strip()

    return {
        "question_type": question_type or "unknown",
        "needs_sql": bool(needs_sql),
        "needs_chart": bool(needs_chart),
        "message": message,
    }


def _build_llm_from_pipeline(pipeline_result: dict) -> dict | None:
    if str(pipeline_result.get("status", "")).strip().lower() not in {"success", "degraded"}:
        return None

    query_execution = (
        pipeline_result.get("query_execution", {})
        if isinstance(pipeline_result.get("query_execution"), dict)
        else {}
    )
    intent_extraction = (
        pipeline_result.get("intent_extraction", {})
        if isinstance(pipeline_result.get("intent_extraction"), dict)
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
    return {
        "intent": intent_extraction.get("normalized_intent") or query_execution.get("normalized_intent", {}),
        "sql": query_execution.get("sql_query", ""),
        "generated_sql": query_execution.get("generated_sql", query_execution.get("sql_query", "")),
        "reviewed_sql": query_execution.get("reviewed_sql", query_execution.get("sql_query", "")),
        "sql_review": query_execution.get("sql_review", {}),
        "chart": chart_payload,
        "confidence": float(
            pipeline_result.get(
                "confidence",
                (
                    pipeline_result.get("intent", {})
                    if isinstance(pipeline_result.get("intent"), dict)
                    else {}
                ).get("confidence", 0.5),
            )
        ),
        "confidence_breakdown": pipeline_result.get("confidence_breakdown"),
        "columns": query_execution.get("referenced_columns", []),
    }


@csrf_exempt
@require_internal_api_key
def transcribe_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    audio_file = request.FILES.get("audio")
    if not audio_file:
        return JsonResponse({"error": "No audio file provided"}, status=400)
    user_id = (request.POST.get("user_id") or "").strip()
    manager_id = (request.POST.get("manager_id") or "").strip()
    dataset_id = (request.POST.get("dataset_id") or "").strip()
    source_id = (request.POST.get("source_id") or "").strip()
    workspace_id = (request.POST.get("workspace_id") or "").strip()
    report_id = (request.POST.get("report_id") or "").strip()
    table_name = (request.POST.get("table_name") or "").strip()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        for chunk in audio_file.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        pipeline_result = whisper_transcription_preprocess_intent_flow(
            audio_path=tmp_path,
            user_id=(user_id or None),
            manager_id=(manager_id or user_id or None),
            dataset_id=(dataset_id or None),
            source_id=(source_id or None),
            workspace_id=(workspace_id or None),
            report_id=(report_id or None),
            table_name=(table_name or None),
        )
        transcription_payload = (  
            pipeline_result.get("transcription", {})
            if isinstance(pipeline_result.get("transcription"), dict)
            else {}
        )
        text_result = str(transcription_payload.get("text", "")).strip()
        reasoning_result = _build_reasoning_from_pipeline(pipeline_result)
        llm_result = _build_llm_from_pipeline(pipeline_result)
        preprocessing_low = (
            pipeline_result.get("preprocess", {})
            if isinstance(pipeline_result.get("preprocess"), dict)
            else {}
        )
        preprocessing_high = (
            pipeline_result.get("preprocess_high", {})
            if isinstance(pipeline_result.get("preprocess_high"), dict)
            else {}
        )
    except Exception as exc:
        logger.exception("Whisper transcription pipeline failed")
        return JsonResponse({"error": str(exc)}, status=500)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return JsonResponse(
        {
            "text": text_result,
            "reasoning": reasoning_result,
            "llm": llm_result,
            "confidence": pipeline_result.get("confidence"),
            "confidence_breakdown": pipeline_result.get("confidence_breakdown"),
            "degraded": str(pipeline_result.get("status", "")).strip().lower() == "degraded",
            "preprocessing_low": preprocessing_low,
            "preprocessing_high": preprocessing_high,
            "pipeline_trace": pipeline_result.get("pipeline_trace"),
            "overall_status": pipeline_result.get("overall_status"),
            "root_cause": pipeline_result.get("root_cause"),
            "dagster_runtime": pipeline_result.get("dagster_runtime"),
            "final_route": pipeline_result.get("final_route"),
            "final_user_message": pipeline_result.get("final_user_message"),
        }
    )
