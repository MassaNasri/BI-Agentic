"""
Voice Reports Views

API endpoints for voice-driven BI system.
Orchestrates Small Whisper, ClickHouse, and Metabase.
"""


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.core.files.base import ContentFile
import logging
import os
import uuid
import requests

from .models import VoiceReport, SQLEditHistory
from .constants import ChartType, normalize_chart_type
from .services import (
    get_small_whisper_client,
    get_clickhouse_executor,
    SQLGuard,
    get_metabase_service,
    get_event_publisher,
    get_subscription_client,
    get_notification_client,
)
from .services.clickhouse_executor import sanitize_query_results
from .services.forecasting_bridge import build_forecast_payload, detect_forecast_metadata
from .services.ai_trace_service import build_ai_trace_payload
from .utils import extract_upstream_chart_type, infer_chart_type
from users.permissions import IsManager, IsAnalyst, IsExecutive

logger = logging.getLogger(__name__)
LOW_CHANGE_TYPES = {"removed_noise", "normalized", "reduced_repetition", "removed_filler_words", "removed_noise_tags", "removed_noise_tokens", "normalized_repeated_characters", "normalized_punctuation", "normalized_whitespace", "removed_control_chars", "removed_malformed_symbols", "normalized_control_chars"}
HIGH_ADJUSTMENT_TYPES = {"derived_field", "mapped_column"}
ANALYTICAL_QUESTION_TYPES = {"analytical", "predictive", "forecast", "forecasting"}
NON_ANALYTICAL_QUESTION_TYPES = {
    "conversational",
    "informational",
    "invalid_input",
    "numeric_only_input",
    "noise_input",
    "empty_input",
    "transcription_failure",
    "no_speech_detected",
}


def build_report_ai_trace(report, *, embed_url: str = "") -> dict:
    return build_ai_trace_payload(
        report_id=report.id,
        transcription=report.transcription,
        preprocessing_low=report.preprocessing_low,
        preprocessing_high=report.preprocessing_high,
        intent_json=report.intent_json,
        pipeline_trace=report.pipeline_trace,
        generated_sql=report.generated_sql,
        reviewed_sql=report.final_sql,
        query_result=report.query_result,
        execution_time_ms=report.execution_time_ms,
        row_count=report.row_count,
        chart_type=report.chart_type,
        metabase_question_id=report.metabase_question_id,
        metabase_dashboard_id=report.metabase_dashboard_id,
        embed_url=embed_url,
        chart_config=report.chart_config,
        error_message=report.error_message,
    )


def normalize_question_type(question_type: str | None) -> str:
    normalized = str(question_type or "").strip().lower()
    if normalized in {"information", "informational", "info", "non_analytical", "non-analytical"}:
        return "conversational"
    return normalized or "unknown"


def is_analytical_question_type(question_type: str | None) -> bool:
    return normalize_question_type(question_type) in ANALYTICAL_QUESTION_TYPES


def is_explicit_non_analytical_question_type(question_type: str | None) -> bool:
    return normalize_question_type(question_type) in NON_ANALYTICAL_QUESTION_TYPES


def _extract_pipeline_final_route(pipeline_trace: dict | None) -> str:
    if not isinstance(pipeline_trace, dict):
        return ""
    overall_status = pipeline_trace.get("overall_status", {})
    if isinstance(overall_status, dict):
        return str(overall_status.get("final_route", "")).strip().lower()
    return ""


def publish_kafka_event(topic, payload, key=None):
    """
    Publish workflow events without impacting API responses on broker failures.
    """
    try:
        publisher = get_event_publisher()
        publisher.publish(topic=topic, payload=payload, key=key)
    except Exception as exc:
        logger.warning("Kafka publish skipped topic=%s error=%s", topic, exc)


def normalize_chart_payload(chart_payload):
    """
    Normalize chart payloads coming from external components (e.g., Small Whisper).
    """
    if not isinstance(chart_payload, dict):
        return chart_payload
    raw_type = (
        chart_payload.get("selected_chart_type")
        or chart_payload.get("chart_type")
        or chart_payload.get("type")
    )
    normalized_type = normalize_chart_type(raw_type, default="")
    normalized_payload = dict(chart_payload)
    if not normalized_type:
        return normalized_payload
    if raw_type and raw_type != normalized_type:
        logger.info(
            "Chart type mapping applied: source=%s mapped=%s",
            raw_type,
            normalized_type,
        )
    normalized_payload["selected_chart_type"] = normalized_type
    normalized_payload["chart_type"] = normalized_type
    normalized_payload["type"] = normalized_type
    return normalized_payload


def get_user_workspace(user):
    """
    Get the user's workspace based on their role.
    
    - Manager: Returns their owned workspace
    - Analyst/Executive: Returns workspace they're a member of
    """
    if user.role == 'manager':
        # Manager owns workspace
        workspace = user.owned_workspaces.first()
        return workspace
    else:
        # Analyst or Executive is a member
        membership = user.workspace_memberships.filter(status='active').first()
        if membership:
            return membership.workspace
        return None


def get_report_embed_url(report, metabase_service=None):
    """
    Generate a fresh Metabase question embed URL for every response.
    """
    if not report.metabase_question_id:
        return ""

    metabase = metabase_service or get_metabase_service()
    embed_url = metabase.get_question_embed_url(report.metabase_question_id)
    if embed_url:
        return embed_url

    logger.warning(
        "Failed to generate dynamic embed URL for report=%s question=%s error=%s",
        report.id,
        report.metabase_question_id,
        metabase.last_error
    )
    return ""


def _service_headers_with_auth(request):
    headers = {"Content-Type": "application/json"}
    auth_header = request.META.get("HTTP_AUTHORIZATION")
    if auth_header:
        headers["Authorization"] = auth_header
    return headers


def _resolve_dataset_binding_context(
    *,
    request,
    workspace_id: str,
    manager_id: str,
    explicit_dataset_id: str = "",
    explicit_source_id: str = "",
    explicit_table_name: str = "",
) -> dict[str, str]:
    dataset_id = str(explicit_dataset_id or "").strip()
    source_id = str(explicit_source_id or "").strip()
    table_name = str(explicit_table_name or "").strip()

    if not (dataset_id and table_name):
        query_service_url = os.getenv("QUERY_SERVICE_URL", "http://query-service:8006").rstrip("/")
        try:
            response = requests.get(
                f"{query_service_url}/database/",
                headers=_service_headers_with_auth(request),
                timeout=10,
            )
            if response.status_code == status.HTTP_200_OK:
                raw_payload = response.json()
                payload = raw_payload if isinstance(raw_payload, dict) else {}
                data = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
                dataset_id = dataset_id or str(data.get("id") or "").strip()
                source_id = source_id or dataset_id
                table_name = table_name or str(data.get("clickhouse_table_name") or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to resolve ETL dataset binding from query-service: %s", exc)

    return {
        "workspace_id": str(workspace_id or "").strip(),
        "manager_id": str(manager_id or "").strip(),
        "dataset_id": dataset_id,
        "source_id": source_id or dataset_id,
        "table_name": table_name,
    }


def build_default_preprocessing_low(original_text: str = "") -> dict:
    normalized_text = str(original_text or "")
    return {
        "original_text": normalized_text,
        "cleaned_text": normalized_text,
        "changes": [],
    }


def build_default_preprocessing_high(corrected_query: str = "") -> dict:
    return {
        "corrected_query": str(corrected_query or ""),
        "term_corrections": [],
        "user_friendly_messages": [],
        "schema_used": {"tables": [], "columns": []},
        "schema_adjustments": [],
        "unresolved_terms": [],
        "unsupported_terms": [],
        "term_resolutions": [],
        "schema_validation_status": "unknown",
        "candidate_columns": {},
        "candidate_tables": [],
        "selected_table": "",
        "selected_columns": [],
        "skipped_schema_terms": [],
        "routing_decision": {},
    }


def build_default_pipeline_trace() -> dict:
    return {
        "request_metadata": {},
        "overall_status": {"status": "unknown"},
        "root_cause": {
            "root_cause_category": "unknown",
            "root_cause_detail": "",
            "analyst_recommended_fix": "",
        },
    }


def normalize_pipeline_trace(payload) -> dict:
    fallback = build_default_pipeline_trace()
    if not isinstance(payload, dict):
        return fallback
    normalized = dict(payload)
    normalized.setdefault("request_metadata", {})
    normalized.setdefault("overall_status", {"status": "unknown"})
    normalized.setdefault(
        "root_cause",
        {
            "root_cause_category": "unknown",
            "root_cause_detail": "",
            "analyst_recommended_fix": "",
        },
    )
    return normalized


def extract_pipeline_contract(
    pipeline_trace,
    *,
    confidence=None,
    confidence_breakdown=None,
    degraded=None,
) -> dict:
    trace = pipeline_trace if isinstance(pipeline_trace, dict) else {}
    overall = trace.get("overall_status", {}) if isinstance(trace.get("overall_status"), dict) else {}
    status_value = str(overall.get("status") or trace.get("status") or "").strip().lower()
    breakdown = confidence_breakdown or overall.get("confidence_breakdown") or trace.get("confidence_breakdown")
    score = confidence
    if score is None:
        score = overall.get("confidence", trace.get("confidence"))
    try:
        score = None if score is None else max(0.0, min(1.0, float(score)))
    except (TypeError, ValueError):
        score = None
    derived_degraded = degraded
    if derived_degraded is None:
        derived_degraded = status_value == "degraded" or any(
            isinstance(stage, dict)
            and (
                str(stage.get("status", "")).strip().lower() == "degraded"
                or bool(stage.get("degraded"))
            )
            for stage in trace.values()
        )
    return {
        "status": status_value or "unknown",
        "degraded": bool(derived_degraded),
        "confidence": score,
        "confidence_breakdown": breakdown if isinstance(breakdown, dict) else None,
    }


def extract_report_contract(report) -> dict:
    chart_config = report.chart_config if isinstance(report.chart_config, dict) else {}
    stored = chart_config.get("ai_contract", {}) if isinstance(chart_config.get("ai_contract"), dict) else {}
    trace_contract = extract_pipeline_contract(report.pipeline_trace)
    return {
        **trace_contract,
        **{key: value for key, value in stored.items() if value is not None},
    }


def _flatten_schema_columns(columns_payload) -> list[str]:
    flattened: list[str] = []
    if isinstance(columns_payload, dict):
        for table_name, columns in columns_payload.items():
            normalized_table = str(table_name or "").strip()
            if not isinstance(columns, list):
                continue
            for column in columns:
                if isinstance(column, dict):
                    column_name = str(column.get("name", "")).strip()
                else:
                    column_name = str(column or "").strip()
                if not column_name:
                    continue
                if normalized_table:
                    flattened.append(f"{normalized_table}.{column_name}")
                else:
                    flattened.append(column_name)
        return flattened
    if isinstance(columns_payload, list):
        return [str(column) for column in columns_payload if str(column or "").strip()]
    return flattened


def _dedupe_non_empty(values) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    if not isinstance(values, list):
        return deduped
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        signature = normalized.lower()
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(normalized)
    return deduped


def _extract_term_corrections_from_mappings(mappings) -> list[dict]:
    corrections: list[dict] = []
    if not isinstance(mappings, list):
        return corrections
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        status = str(mapping.get("status", "")).strip().lower()
        if status not in {"mapped", "derivable"}:
            continue
        requested = str(mapping.get("requested", "")).strip()
        matched_column = str(mapping.get("matched_column", "")).strip()
        matched_table = str(mapping.get("matched_table", "")).strip()
        if not requested or not matched_column:
            continue
        corrections.append(
            {
                "original": requested,
                "corrected": matched_column,
                "matched_column": f"{matched_table}.{matched_column}" if matched_table else matched_column,
            }
        )
    return corrections


def _extract_schema_adjustments_from_mappings(mappings) -> list[dict]:
    adjustments: list[dict] = []
    if not isinstance(mappings, list):
        return adjustments
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        status = str(mapping.get("status", "")).strip().lower()
        requested = str(mapping.get("requested", "")).strip()
        matched_column = str(mapping.get("matched_column", "")).strip()
        matched_table = str(mapping.get("matched_table", "")).strip()
        if status == "mapped" and requested and matched_column:
            fully_qualified = f"{matched_table}.{matched_column}" if matched_table else matched_column
            adjustments.append(
                {
                    "type": "mapped_column",
                    "description": f"Mapped '{requested}' to '{fully_qualified}'.",
                }
            )
        elif status == "derivable" and requested and matched_column:
            fully_qualified = f"{matched_table}.{matched_column}" if matched_table else matched_column
            adjustments.append(
                {
                    "type": "derived_field",
                    "description": f"Derived '{requested}' from '{fully_qualified}'.",
                }
            )
    return adjustments


def _extract_schema_usage_from_mappings(mappings) -> tuple[list[str], list[str]]:
    tables: list[str] = []
    columns: list[str] = []
    if not isinstance(mappings, list):
        return tables, columns
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        status = str(mapping.get("status", "")).strip().lower()
        if status not in {"exact", "mapped", "derivable"}:
            continue
        matched_table = str(mapping.get("matched_table", "")).strip()
        matched_column = str(mapping.get("matched_column", "")).strip()
        if matched_table:
            tables.append(matched_table)
        if matched_column:
            columns.append(f"{matched_table}.{matched_column}" if matched_table else matched_column)
    return _dedupe_non_empty(tables), _dedupe_non_empty(columns)


def normalize_preprocessing_low(payload, fallback_text: str = "") -> dict:
    fallback = build_default_preprocessing_low(fallback_text)
    if not isinstance(payload, dict):
        return fallback

    original_text = str(payload.get("original_text") or fallback_text or "").strip()
    cleaned_text = str(payload.get("cleaned_text") or original_text).strip()
    raw_changes = payload.get("changes", [])
    if not isinstance(raw_changes, list):
        raw_changes = []
    if not raw_changes:
        raw_changes = payload.get("detected_changes", [])
    normalized_changes = []
    if isinstance(raw_changes, list):
        for change in raw_changes:
            if not isinstance(change, dict):
                continue
            change_type = str(change.get("type", "normalized")).strip().lower()
            if change_type not in LOW_CHANGE_TYPES:
                change_type = "normalized"
            normalized_changes.append(
                {
                    "type": change_type,
                    "before": str(change.get("before", "")).strip(),
                    "after": str(change.get("after", "")).strip(),
                }
            )

    return {
        "original_text": original_text,
        "cleaned_text": cleaned_text,
        "changes": normalized_changes,
    }


def normalize_preprocessing_high(payload, fallback_query: str = "") -> dict:
    fallback = build_default_preprocessing_high(fallback_query)
    if not isinstance(payload, dict):
        return fallback

    corrected_query = str(
        payload.get("corrected_query")
        or payload.get("final_query")
        or fallback_query
        or ""
    ).strip()
    selected_table = str(payload.get("selected_table", "")).strip()
    selected_columns = _dedupe_non_empty(
        payload.get("selected_columns", []) if isinstance(payload.get("selected_columns"), list) else []
    )
    mappings = payload.get("mappings", []) if isinstance(payload.get("mappings"), list) else []

    term_corrections = []
    raw_corrections = payload.get("term_corrections", [])
    if isinstance(raw_corrections, list):
        for correction in raw_corrections:
            if not isinstance(correction, dict):
                continue
            original_value = (
                correction.get("original")
                or correction.get("from")
                or correction.get("source")
                or ""
            )
            corrected_value = (
                correction.get("corrected")
                or correction.get("to")
                or correction.get("target")
                or ""
            )
            term_corrections.append(
                {
                    "original": str(original_value).strip(),
                    "corrected": str(corrected_value).strip(),
                    "matched_column": str(
                        correction.get("matched_column", "") or correction.get("matched", "")
                    ).strip(),
                    "from": str(original_value).strip(),
                    "to": str(corrected_value).strip(),
                    "type": str(correction.get("type", "")).strip(),
                    "message": str(correction.get("message", "")).strip(),
                }
            )
    if not term_corrections and mappings:
        term_corrections = _extract_term_corrections_from_mappings(mappings)

    raw_schema_used = payload.get("schema_used", {})
    tables = []
    columns = []
    if isinstance(raw_schema_used, dict):
        raw_tables = raw_schema_used.get("tables", [])
        if isinstance(raw_tables, list):
            tables = _dedupe_non_empty(raw_tables)
        columns = _flatten_schema_columns(raw_schema_used.get("columns", []))

    schema_adjustments = []
    raw_adjustments = payload.get("schema_adjustments", [])
    if isinstance(raw_adjustments, list):
        for adjustment in raw_adjustments:
            if not isinstance(adjustment, dict):
                continue
            adjustment_type = str(adjustment.get("type", "mapped_column")).strip().lower()
            if adjustment_type not in HIGH_ADJUSTMENT_TYPES:
                adjustment_type = "mapped_column"
            schema_adjustments.append(
                {
                    "type": adjustment_type,
                    "description": str(adjustment.get("description", "")).strip(),
                }
            )
    if not schema_adjustments and mappings:
        schema_adjustments = _extract_schema_adjustments_from_mappings(mappings)

    if not tables and selected_table:
        tables = [selected_table]
    if not columns and selected_columns:
        columns = [
            f"{selected_table}.{column}" if selected_table else column
            for column in selected_columns
        ]

    if not tables or not columns:
        mapping_tables, mapping_columns = _extract_schema_usage_from_mappings(mappings)
        if not tables and mapping_tables:
            tables = mapping_tables
        if not columns and mapping_columns:
            columns = mapping_columns

    tables = _dedupe_non_empty(tables)
    columns = _dedupe_non_empty(columns)
    if not selected_table and len(tables) == 1:
        selected_table = tables[0]
    if not selected_columns and columns:
        selected_columns = [
            column.split(".", 1)[1]
            if selected_table and column.lower().startswith(f"{selected_table.lower()}.")
            else column.split(".")[-1]
            for column in columns
        ]
        selected_columns = _dedupe_non_empty(selected_columns)

    return {
        "corrected_query": corrected_query,
        "term_corrections": term_corrections,
        "user_friendly_messages": [
            str(message).strip()
            for message in payload.get("user_friendly_messages", [])
            if str(message).strip()
        ]
        if isinstance(payload.get("user_friendly_messages"), list)
        else [],
        "schema_used": {
            "tables": tables,
            "columns": columns,
        },
        "schema_adjustments": schema_adjustments,
        "unresolved_terms": [
            str(term).strip()
            for term in payload.get("unresolved_terms", [])
            if str(term).strip()
        ]
        if isinstance(payload.get("unresolved_terms"), list)
        else [],
        "unsupported_terms": [
            str(term).strip()
            for term in payload.get("unsupported_terms", [])
            if str(term).strip()
        ]
        if isinstance(payload.get("unsupported_terms"), list)
        else [],
        "term_resolutions": payload.get("term_resolutions", [])
        if isinstance(payload.get("term_resolutions"), list)
        else [],
        "schema_validation_status": str(payload.get("schema_validation_status", "unknown")),
        "candidate_columns": payload.get("candidate_columns", {})
        if isinstance(payload.get("candidate_columns"), dict)
        else {},
        "candidate_tables": payload.get("candidate_tables", [])
        if isinstance(payload.get("candidate_tables"), list)
        else [],
        "selected_table": selected_table,
        "selected_columns": selected_columns,
        "skipped_schema_terms": [
            str(term).strip()
            for term in payload.get("skipped_schema_terms", [])
            if str(term).strip()
        ]
        if isinstance(payload.get("skipped_schema_terms"), list)
        else [],
        "routing_decision": payload.get("routing_decision", {})
        if isinstance(payload.get("routing_decision"), dict)
        else {},
    }


class VoiceUploadView(APIView):
    """
    Upload audio file and get transcription + generated SQL from Small Whisper.
    
    Manager only.
    
    ARCHITECTURAL SEPARATION:
    - This endpoint (Main BI Backend) handles ALL authentication and user validation
    - Small Whisper Backend (port 8001) is a STATELESS AI worker
    - Small Whisper receives ONLY audio file, returns ONLY data (no user context)
    - This endpoint ALWAYS returns a valid report_id (even for conversational questions)
    """
    permission_classes = [IsAuthenticated, IsManager]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        try:
            # Validate audio file
            if 'audio' not in request.FILES:
                return Response(
                    {'success': False, 'error': 'No audio file provided'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            audio_file = request.FILES['audio']
            workspace = get_user_workspace(request.user)
            
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Enforce subscription/free-tier limits before processing any voice request.
            subscription_client = get_subscription_client()
            access_result = subscription_client.check_access(
                workspace_id=workspace.id,
                authorization_header=request.META.get('HTTP_AUTHORIZATION'),
                consume=True,
            )

            if not access_result.get('success'):
                logger.error(
                    "Subscription access check failed workspace=%s user=%s error=%s",
                    workspace.id,
                    request.user.id,
                    access_result.get('error'),
                )
                return Response(
                    {
                        'success': False,
                        'error': 'Subscription service unavailable. Please try again.',
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            if not access_result.get('allowed'):
                limit_message = 'You have reached your limit. Please subscribe.'
                return Response(
                    {
                        'success': False,
                        'error': limit_message,
                        'message': limit_message,
                        'remaining_requests': access_result.get('remaining_requests', 0),
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            
            # Save audio file
            audio_dir = f'media/workspaces/{workspace.id}/audio'
            os.makedirs(audio_dir, exist_ok=True)
            
            # Generate unique filename
            filename = f"{uuid.uuid4()}_{audio_file.name}"
            audio_path = os.path.join(audio_dir, filename)
            
            with open(audio_path, 'wb+') as destination:
                for chunk in audio_file.chunks():
                    destination.write(chunk)
            
            logger.info(f"Audio file saved: {audio_path}")
            
            # Call Small Whisper (STATELESS - no user context needed)
            whisper_client = get_small_whisper_client()
            binding_context = _resolve_dataset_binding_context(
                request=request,
                workspace_id=str(workspace.id),
                manager_id=str(request.user.id),
                explicit_dataset_id=str(request.data.get("dataset_id") or "").strip(),
                explicit_source_id=str(request.data.get("source_id") or "").strip(),
                explicit_table_name=str(request.data.get("table_name") or "").strip(),
            )
            whisper_result = whisper_client.process_audio(
                audio_file=audio_path,
                user_id=str(request.user.id),
                workspace_id=binding_context.get("workspace_id"),
                manager_id=binding_context.get("manager_id"),
                dataset_id=binding_context.get("dataset_id"),
                source_id=binding_context.get("source_id"),
                table_name=binding_context.get("table_name"),
            )
            
            if not whisper_result['success']:
                return Response(
                    {
                        'success': False,
                        'error': f"Small Whisper error: {whisper_result.get('error')}"
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            # Extract question type and SQL
            question_type = normalize_question_type(whisper_result.get('question_type', 'unknown'))
            sql = whisper_result.get('sql')
            generated_sql = whisper_result.get('generated_sql') or sql
            reviewed_sql = whisper_result.get('reviewed_sql') or sql
            is_analytical_question = is_analytical_question_type(question_type) or bool(sql)
            is_explicit_non_analytical = (
                is_explicit_non_analytical_question_type(question_type) and not bool(sql)
            )
            preprocessing_low = normalize_preprocessing_low(
                whisper_result.get("preprocessing_low"),
                fallback_text=whisper_result.get("text", ""),
            )
            preprocessing_high = normalize_preprocessing_high(
                whisper_result.get("preprocessing_high"),
                fallback_query=preprocessing_low.get("cleaned_text", ""),
            )
            pipeline_trace = normalize_pipeline_trace(whisper_result.get("pipeline_trace"))
            ai_contract = extract_pipeline_contract(
                pipeline_trace,
                confidence=whisper_result.get("confidence"),
                confidence_breakdown=whisper_result.get("confidence_breakdown"),
                degraded=whisper_result.get("degraded"),
            )
            
            # ALWAYS create a report record, even for conversational questions
            # This ensures we always return a valid report_id
            report = VoiceReport.objects.create(
                workspace=workspace,
                created_by=request.user,
                audio_file=audio_path,
                transcription=whisper_result['text'],
                intent_json=whisper_result.get('intent'),
                generated_sql=generated_sql or '',
                final_sql=reviewed_sql or '',
                preprocessing_low=preprocessing_low,
                preprocessing_high=preprocessing_high,
                pipeline_trace=pipeline_trace,
                chart_config={"ai_contract": ai_contract},
                status=(
                    VoiceReport.STATUS_PENDING
                    if (is_analytical_question and sql)
                    else VoiceReport.STATUS_UPLOADED
                ),
            )
            report.ai_trace = build_report_ai_trace(report)
            report.save(update_fields=['ai_trace', 'updated_at'])

            event_base = {
                'report_id': report.id,
                'workspace_id': workspace.id,
                'user_id': request.user.id,
                'question_type': question_type,
            }
            publish_kafka_event(
                'report.voice.received',
                {
                    **event_base,
                    'transcription': whisper_result.get('text', ''),
                },
                key=str(report.id),
            )
            if whisper_result.get('intent') is not None:
                publish_kafka_event(
                    'report.intent.generated',
                    {
                        **event_base,
                        'intent': whisper_result.get('intent'),
                    },
                    key=str(report.id),
                )
            if sql:
                publish_kafka_event(
                    'report.sql.generated',
                    {
                        **event_base,
                        'sql': sql,
                    },
                    key=str(report.id),
                )

            # Analytical questions must produce SQL. If not, surface a hard failure
            # instead of silently treating it as conversational.
            if is_analytical_question and not sql:
                analytical_error_message = whisper_result.get(
                    'message',
                    'Analytical question detected but SQL generation failed.'
                )
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = analytical_error_message
                report.ai_trace = build_report_ai_trace(report)
                report.save(update_fields=['status', 'error_message', 'ai_trace', 'updated_at'])
                logger.error(
                    "Analytical SQL generation failed for report=%s workspace=%s message=%s",
                    report.id,
                    workspace.id,
                    analytical_error_message,
                )
                return Response(
                    {
                        'success': False,
                        'id': report.id,
                        'report_id': report.id,
                        'question_type': question_type,
                        'requires_sql': True,
                        'preprocessing_low': preprocessing_low,
                        'preprocessing_high': preprocessing_high,
                        'pipeline_trace': pipeline_trace,
                        'confidence': ai_contract.get('confidence'),
                        'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                        'degraded': ai_contract.get('degraded'),
                        'overall_status': whisper_result.get('overall_status'),
                        'root_cause': whisper_result.get('root_cause'),
                        'dagster_runtime': whisper_result.get('dagster_runtime'),
                        'final_route': whisper_result.get('final_route'),
                        'final_user_message': whisper_result.get('final_user_message'),
                        'error': 'SQL generation failed for analytical question',
                        'details': analytical_error_message,
                        'status': VoiceReport.STATUS_FAILED,
                    },
                    status=status.HTTP_502_BAD_GATEWAY
                )
            
            # Handle explicit non-analytical questions (no SQL needed)
            if is_explicit_non_analytical:
                logger.info(f"Conversational question detected: {whisper_result.get('message')}")
                return Response({
                    'success': True,
                    'id': report.id,  # Always return valid report_id
                    'report_id': report.id,  # For backward compatibility
                    'transcription': whisper_result['text'],
                    'question_type': question_type,
                    'message': whisper_result.get('message', 'Question does not require data analysis'),
                    'intent': whisper_result.get('intent'),
                    'requires_sql': False,
                    'preprocessing_low': preprocessing_low,
                    'preprocessing_high': preprocessing_high,
                    'pipeline_trace': pipeline_trace,
                    'confidence': ai_contract.get('confidence'),
                    'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                    'degraded': ai_contract.get('degraded'),
                    'overall_status': whisper_result.get('overall_status'),
                    'root_cause': whisper_result.get('root_cause'),
                    'dagster_runtime': whisper_result.get('dagster_runtime'),
                    'final_route': whisper_result.get('final_route'),
                    'final_user_message': whisper_result.get('final_user_message'),
                    'status': VoiceReport.STATUS_UPLOADED
                })

            # If SQL is missing and classification is not explicitly conversational,
            # surface this as pipeline failure instead of mislabeling it as conversational.
            if not sql:
                unresolved_error_message = whisper_result.get(
                    'message',
                    'SQL was not generated because the pipeline did not produce a stable classification.'
                )
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = unresolved_error_message
                report.ai_trace = build_report_ai_trace(report)
                report.save(update_fields=['status', 'error_message', 'ai_trace', 'updated_at'])
                logger.error(
                    "Voice pipeline missing SQL without explicit conversational classification "
                    "for report=%s workspace=%s question_type=%s message=%s",
                    report.id,
                    workspace.id,
                    question_type,
                    unresolved_error_message,
                )
                return Response(
                    {
                        'success': False,
                        'id': report.id,
                        'report_id': report.id,
                        'question_type': question_type,
                        'requires_sql': bool(is_analytical_question),
                        'preprocessing_low': preprocessing_low,
                        'preprocessing_high': preprocessing_high,
                        'pipeline_trace': pipeline_trace,
                        'confidence': ai_contract.get('confidence'),
                        'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                        'degraded': ai_contract.get('degraded'),
                        'overall_status': whisper_result.get('overall_status'),
                        'root_cause': whisper_result.get('root_cause'),
                        'dagster_runtime': whisper_result.get('dagster_runtime'),
                        'final_route': whisper_result.get('final_route'),
                        'final_user_message': whisper_result.get('final_user_message'),
                        'error': 'SQL generation unavailable',
                        'details': unresolved_error_message,
                        'status': VoiceReport.STATUS_FAILED,
                    },
                    status=status.HTTP_502_BAD_GATEWAY
                )
            
            # TODO: Create history entry when ReportHistory model is added
            # ReportHistory.objects.create(
            #     report=report,
            #     action='created',
            #     performed_by=request.user,
            #     changes={
            #         'transcription': whisper_result['text'],
            #         'sql': whisper_result['sql']
            #     }
            # )
            
            logger.info(f"Voice report created: {report.id}")

            normalized_chart = normalize_chart_payload(whisper_result.get('chart'))
            if isinstance(normalized_chart, dict):
                report.chart_config = {
                    **(report.chart_config if isinstance(report.chart_config, dict) else {}),
                    "upstream_chart": normalized_chart,
                }
                report.save(update_fields=['chart_config', 'updated_at'])
            
            return Response({
                'success': True,
                'id': report.id,  # Always return valid report_id
                'report_id': report.id,  # For backward compatibility
                'transcription': whisper_result['text'],
                'question_type': question_type,
                'intent': whisper_result.get('intent'),
                'sql': sql,
                'chart': normalized_chart,
                'confidence': ai_contract.get('confidence'),
                'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                'degraded': ai_contract.get('degraded'),
                'message': 'Audio processed successfully. Ready to execute.',
                'preprocessing_low': preprocessing_low,
                'preprocessing_high': preprocessing_high,
                'pipeline_trace': pipeline_trace,
                'overall_status': whisper_result.get('overall_status'),
                'root_cause': whisper_result.get('root_cause'),
                'dagster_runtime': whisper_result.get('dagster_runtime'),
                'final_route': whisper_result.get('final_route'),
                'final_user_message': whisper_result.get('final_user_message'),
                'status': VoiceReport.STATUS_PENDING
            })
        
        except Exception as e:
            logger.error(f"Error in VoiceUploadView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class TextQueryView(APIView):
    """
    Accept pre-transcribed text and continue directly from intent detection stage.

    Manager only. This skips audio upload/transcription and reuses the same
    downstream SQL/visualization execution flow.
    """
    permission_classes = [IsAuthenticated, IsManager]

    def post(self, request):
        try:
            text = (request.data.get('text') or '').strip()
            if not text:
                return Response(
                    {'success': False, 'error': 'Text is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            requested_workspace_id = request.data.get('workspace_id')
            if (
                requested_workspace_id is not None
                and str(requested_workspace_id).strip()
                and str(requested_workspace_id) != str(workspace.id)
            ):
                return Response(
                    {'success': False, 'error': 'workspace_id does not match current user workspace'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Keep subscription consumption behavior aligned with voice uploads.
            subscription_client = get_subscription_client()
            access_result = subscription_client.check_access(
                workspace_id=workspace.id,
                authorization_header=request.META.get('HTTP_AUTHORIZATION'),
                consume=True,
            )

            if not access_result.get('success'):
                logger.error(
                    "Subscription access check failed workspace=%s user=%s error=%s",
                    workspace.id,
                    request.user.id,
                    access_result.get('error'),
                )
                return Response(
                    {
                        'success': False,
                        'error': 'Subscription service unavailable. Please try again.',
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            if not access_result.get('allowed'):
                limit_message = 'You have reached your limit. Please subscribe.'
                return Response(
                    {
                        'success': False,
                        'error': limit_message,
                        'message': limit_message,
                        'remaining_requests': access_result.get('remaining_requests', 0),
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            whisper_client = get_small_whisper_client()
            binding_context = _resolve_dataset_binding_context(
                request=request,
                workspace_id=str(workspace.id),
                manager_id=str(request.user.id),
                explicit_dataset_id=str(request.data.get("dataset_id") or "").strip(),
                explicit_source_id=str(request.data.get("source_id") or "").strip(),
                explicit_table_name=str(request.data.get("table_name") or "").strip(),
            )
            text_result = whisper_client.process_text(
                text=text,
                user_id=str(request.user.id),
                workspace_id=binding_context.get("workspace_id"),
                manager_id=binding_context.get("manager_id"),
                dataset_id=binding_context.get("dataset_id"),
                source_id=binding_context.get("source_id"),
                table_name=binding_context.get("table_name"),
            )

            if not text_result.get('success'):
                return Response(
                    {
                        'success': False,
                        'error': f"AI pipeline error: {text_result.get('error')}"
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )

            transcription_text = text_result.get('text') or text
            question_type = normalize_question_type(text_result.get('question_type', 'unknown'))
            sql = text_result.get('sql')
            generated_sql = text_result.get('generated_sql') or sql
            reviewed_sql = text_result.get('reviewed_sql') or sql
            is_analytical_question = is_analytical_question_type(question_type) or bool(sql)
            is_explicit_non_analytical = (
                is_explicit_non_analytical_question_type(question_type) and not bool(sql)
            )
            preprocessing_low = normalize_preprocessing_low(
                text_result.get("preprocessing_low"),
                fallback_text=transcription_text,
            )
            preprocessing_high = normalize_preprocessing_high(
                text_result.get("preprocessing_high"),
                fallback_query=preprocessing_low.get("cleaned_text", transcription_text),
            )
            pipeline_trace = normalize_pipeline_trace(text_result.get("pipeline_trace"))
            ai_contract = extract_pipeline_contract(
                pipeline_trace,
                confidence=text_result.get("confidence"),
                confidence_breakdown=text_result.get("confidence_breakdown"),
                degraded=text_result.get("degraded"),
            )

            report = VoiceReport(
                workspace=workspace,
                created_by=request.user,
                transcription=transcription_text,
                intent_json=text_result.get('intent'),
                generated_sql=generated_sql or '',
                final_sql=reviewed_sql or '',
                preprocessing_low=preprocessing_low,
                preprocessing_high=preprocessing_high,
                pipeline_trace=pipeline_trace,
                chart_config={"ai_contract": ai_contract},
                status=(
                    VoiceReport.STATUS_PENDING
                    if (is_analytical_question and sql)
                    else VoiceReport.STATUS_UPLOADED
                ),
            )
            report.audio_file.save(
                f"text-input/{uuid.uuid4()}.txt",
                ContentFile(transcription_text.encode('utf-8')),
                save=False
            )
            report.ai_trace = build_report_ai_trace(report)
            report.save()

            event_base = {
                'report_id': report.id,
                'workspace_id': workspace.id,
                'user_id': request.user.id,
                'question_type': question_type,
            }
            publish_kafka_event(
                'report.text.received',
                {
                    **event_base,
                    'transcription': transcription_text,
                },
                key=str(report.id),
            )
            if text_result.get('intent') is not None:
                publish_kafka_event(
                    'report.intent.generated',
                    {
                        **event_base,
                        'intent': text_result.get('intent'),
                    },
                    key=str(report.id),
                )
            if sql:
                publish_kafka_event(
                    'report.sql.generated',
                    {
                        **event_base,
                        'sql': sql,
                    },
                    key=str(report.id),
                )

            if is_analytical_question and not sql:
                analytical_error_message = text_result.get(
                    'message',
                    'Analytical question detected but SQL generation failed.'
                )
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = analytical_error_message
                report.ai_trace = build_report_ai_trace(report)
                report.save(update_fields=['status', 'error_message', 'ai_trace', 'updated_at'])
                logger.error(
                    "Analytical SQL generation failed for text report=%s workspace=%s message=%s",
                    report.id,
                    workspace.id,
                    analytical_error_message,
                )
                return Response(
                    {
                        'success': False,
                        'id': report.id,
                        'report_id': report.id,
                        'question_type': question_type,
                        'requires_sql': True,
                        'preprocessing_low': preprocessing_low,
                        'preprocessing_high': preprocessing_high,
                        'pipeline_trace': pipeline_trace,
                        'confidence': ai_contract.get('confidence'),
                        'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                        'degraded': ai_contract.get('degraded'),
                        'overall_status': text_result.get('overall_status'),
                        'root_cause': text_result.get('root_cause'),
                        'dagster_runtime': text_result.get('dagster_runtime'),
                        'final_route': text_result.get('final_route'),
                        'final_user_message': text_result.get('final_user_message'),
                        'error': 'SQL generation failed for analytical question',
                        'details': analytical_error_message,
                        'status': VoiceReport.STATUS_FAILED,
                    },
                    status=status.HTTP_502_BAD_GATEWAY
                )

            if is_explicit_non_analytical:
                return Response({
                    'success': True,
                    'id': report.id,
                    'report_id': report.id,
                    'transcription': transcription_text,
                    'question_type': question_type,
                    'message': text_result.get('message', 'Question does not require data analysis'),
                    'intent': text_result.get('intent'),
                    'requires_sql': False,
                    'preprocessing_low': preprocessing_low,
                    'preprocessing_high': preprocessing_high,
                    'pipeline_trace': pipeline_trace,
                    'confidence': ai_contract.get('confidence'),
                    'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                    'degraded': ai_contract.get('degraded'),
                    'overall_status': text_result.get('overall_status'),
                    'root_cause': text_result.get('root_cause'),
                    'dagster_runtime': text_result.get('dagster_runtime'),
                    'final_route': text_result.get('final_route'),
                    'final_user_message': text_result.get('final_user_message'),
                    'status': VoiceReport.STATUS_UPLOADED
                })

            if not sql:
                unresolved_error_message = text_result.get(
                    'message',
                    'SQL was not generated because the pipeline did not produce a stable classification.'
                )
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = unresolved_error_message
                report.ai_trace = build_report_ai_trace(report)
                report.save(update_fields=['status', 'error_message', 'ai_trace', 'updated_at'])
                logger.error(
                    "Text pipeline missing SQL without explicit conversational classification "
                    "for report=%s workspace=%s question_type=%s message=%s",
                    report.id,
                    workspace.id,
                    question_type,
                    unresolved_error_message,
                )
                return Response(
                    {
                        'success': False,
                        'id': report.id,
                        'report_id': report.id,
                        'question_type': question_type,
                        'requires_sql': bool(is_analytical_question),
                        'preprocessing_low': preprocessing_low,
                        'preprocessing_high': preprocessing_high,
                        'pipeline_trace': pipeline_trace,
                        'confidence': ai_contract.get('confidence'),
                        'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                        'degraded': ai_contract.get('degraded'),
                        'overall_status': text_result.get('overall_status'),
                        'root_cause': text_result.get('root_cause'),
                        'dagster_runtime': text_result.get('dagster_runtime'),
                        'final_route': text_result.get('final_route'),
                        'final_user_message': text_result.get('final_user_message'),
                        'error': 'SQL generation unavailable',
                        'details': unresolved_error_message,
                        'status': VoiceReport.STATUS_FAILED,
                    },
                    status=status.HTTP_502_BAD_GATEWAY
                )

            normalized_chart = normalize_chart_payload(text_result.get('chart'))
            if isinstance(normalized_chart, dict):
                report.chart_config = {
                    **(report.chart_config if isinstance(report.chart_config, dict) else {}),
                    "upstream_chart": normalized_chart,
                }
                report.save(update_fields=['chart_config', 'updated_at'])

            return Response({
                'success': True,
                'id': report.id,
                'report_id': report.id,
                'transcription': transcription_text,
                'question_type': question_type,
                'intent': text_result.get('intent'),
                'sql': sql,
                'chart': normalized_chart,
                'confidence': ai_contract.get('confidence'),
                'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                'degraded': ai_contract.get('degraded'),
                'message': 'Text processed successfully. Ready to execute.',
                'preprocessing_low': preprocessing_low,
                'preprocessing_high': preprocessing_high,
                'pipeline_trace': pipeline_trace,
                'overall_status': text_result.get('overall_status'),
                'root_cause': text_result.get('root_cause'),
                'dagster_runtime': text_result.get('dagster_runtime'),
                'final_route': text_result.get('final_route'),
                'final_user_message': text_result.get('final_user_message'),
                'status': VoiceReport.STATUS_PENDING
            })
        except Exception as e:
            logger.error(f"Error in TextQueryView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class QueryExecuteView(APIView):
    """
    Execute SQL query on ClickHouse and create Metabase visualization.
    
    Manager and Analyst can execute.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request, report_id):
        try:
            # Validate report_id is not None/undefined
            if report_id is None:
                logger.error("QueryExecuteView called with None report_id")
                return Response(
                    {'success': False, 'error': 'Invalid report_id: report_id cannot be null or undefined'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get report
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace
            )
            
            # Validate report has SQL to execute
            if not report.final_sql or not report.final_sql.strip():
                logger.warning(f"Report {report_id} has no SQL to execute")
                return Response(
                    {'success': False, 'error': 'This report does not contain a SQL query. It may be a conversational question.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate permissions
            if request.user.role not in ['manager', 'analyst']:
                return Response(
                    {'success': False, 'error': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Get SQL (final_sql may be edited by analyst)
            sql_to_execute = report.final_sql
            
            # Validate SQL with SQL Guard
            guard = SQLGuard(
                workspace_database=os.getenv('CLICKHOUSE_DATABASE', 'etl')
            )
            
            is_valid, error_msg, clean_sql = guard.validate_and_sanitize(sql_to_execute)
            
            if not is_valid:
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = f"SQL validation failed: {error_msg}"
                report.ai_trace = build_report_ai_trace(report)
                report.save()
                
                return Response(
                    {'success': False, 'error': error_msg},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report.sql_validated = True
            report.final_sql = clean_sql
            report.status = VoiceReport.STATUS_PROCESSING
            report.error_message = ''
            report.save()
            
            # Execute through Query Service (REST), with local fallback for resilience.
            query_result = self._execute_query_with_query_service(request, clean_sql)

            if not query_result.get('success'):
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = query_result.get('error', 'Query execution failed')
                report.ai_trace = build_report_ai_trace(report)
                report.save()

                logger.error(
                    "Query execution failed for report %s: %s",
                    report.id,
                    query_result.get('error')
                )

                return Response(
                    {
                        'success': False,
                        'error': 'Query execution failed',
                        'details': query_result.get('error', 'query_service_failure')
                    },
                    status=status.HTTP_502_BAD_GATEWAY
                )
            
            base_columns = query_result.get('columns', [])
            base_rows = sanitize_query_results(query_result.get('rows', []))
            visualization_sql = clean_sql
            visualization_columns = base_columns
            visualization_rows = base_rows
            chart_config = dict(report.chart_config) if isinstance(report.chart_config, dict) else {}
            chart_config.pop("forecasting", None)

            forecast_request = detect_forecast_metadata(
                intent=report.intent_json if isinstance(report.intent_json, dict) else {},
                question_type=(
                    (report.intent_json or {}).get("question_type")
                    if isinstance(report.intent_json, dict)
                    else None
                ),
                final_route=_extract_pipeline_final_route(report.pipeline_trace),
            )
            if forecast_request.get("requires_forecast"):
                forecast_payload = None
                try:
                    forecast_payload = build_forecast_payload(
                        columns=base_columns,
                        rows=base_rows,
                        intent=report.intent_json if isinstance(report.intent_json, dict) else {},
                    )
                except Exception as forecast_error:  # noqa: BLE001
                    forecast_code = str(getattr(forecast_error, "code", "forecasting_failed"))
                    forecast_message = str(getattr(forecast_error, "message", str(forecast_error)))
                    forecast_details = getattr(forecast_error, "details", {})
                    structured_error = {
                        "code": forecast_code,
                        "message": forecast_message,
                        "details": forecast_details if isinstance(forecast_details, dict) else {},
                    }
                    chart_config["forecasting"] = {
                        "enabled": True,
                        "status": "failed",
                        "request": forecast_request,
                        "error": structured_error,
                        "forecast_status": "failed",
                        "reason": forecast_message or forecast_code,
                        "fallback": "analytical_only",
                    }
                    visualization_sql = clean_sql
                    visualization_columns = base_columns
                    visualization_rows = base_rows

                if forecast_payload is not None:
                    forecast_meta = forecast_payload.get("meta", {}) if isinstance(forecast_payload.get("meta"), dict) else {}
                    forecast_available = bool(forecast_meta.get("forecast_available", False))
                    visualization_sql = forecast_payload["sql"]
                    visualization_columns = forecast_payload["columns"]
                    visualization_rows = sanitize_query_results(forecast_payload["rows"])
                    chart_config["forecasting"] = {
                        "enabled": True,
                        "status": "success" if forecast_available else "degraded",
                        "request": forecast_request,
                        "meta": forecast_meta,
                        "forecast_status": "success" if forecast_available else "degraded",
                        "degraded": not forecast_available,
                        "degradation_reason": "" if forecast_available else str(forecast_meta.get("fallback_reason", "forecast_unavailable")),
                        "chart_series_config": forecast_meta.get("chart_series_config", []),
                        "forecast_available": forecast_available,
                    }
            else:
                chart_config.pop("forecasting", None)

            # Save query/forecast dataset.
            ai_contract = extract_report_contract(report)
            if chart_config.get("forecasting", {}).get("status") == "failed":
                prior_confidence = ai_contract.get("confidence")
                ai_contract = {
                    **ai_contract,
                    "degraded": True,
                    "status": "degraded",
                    "confidence": (
                        min(float(prior_confidence), 0.6)
                        if isinstance(prior_confidence, (int, float))
                        else prior_confidence
                    ),
                }
            chart_config["ai_contract"] = ai_contract
            report.query_result = {
                'columns': visualization_columns,
                'rows': visualization_rows,
            }
            report.execution_time_ms = query_result['execution_time_ms']
            report.row_count = len(visualization_rows)
            report.chart_config = chart_config
            report.status = VoiceReport.STATUS_EXECUTED
            report.ai_trace = build_report_ai_trace(report)
            logger.info(
                "ClickHouse result ready for report %s: base_columns=%s base_row_count=%s visualized_row_count=%s",
                report.id,
                len(base_columns),
                query_result['row_count'],
                len(visualization_rows),
            )

            # ðŸ”’ NaN-SAFE: Catch JSON serialization errors during save
            try:
                report.save()
            except (ValueError, TypeError) as json_error:
                logger.error(f"JSON serialization error when saving report {report.id}: {json_error}")
                visualization_rows = sanitize_query_results(visualization_rows)
                report.query_result = {
                    'columns': visualization_columns,
                    'rows': visualization_rows
                }
                try:
                    report.save()
                except Exception as final_error:
                    report.status = VoiceReport.STATUS_FAILED
                    report.error_message = f"Data serialization error: {str(final_error)}"
                    report.ai_trace = build_report_ai_trace(report)
                    report.save()
                    return Response(
                        {
                            'success': False,
                            'error': 'Failed to save query results: invalid numeric values detected',
                            'details': str(final_error)
                        },
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

            publish_kafka_event(
                'report.query.executed',
                {
                    'report_id': report.id,
                    'workspace_id': report.workspace_id,
                    'user_id': request.user.id,
                    'row_count': len(visualization_rows),
                    'source_row_count': query_result.get('row_count', 0),
                    'execution_time_ms': query_result.get('execution_time_ms', 0),
                },
                key=str(report.id),
            )
            
            # Infer chart type
            upstream_chart_type = extract_upstream_chart_type(
                chart_config=report.chart_config if isinstance(report.chart_config, dict) else {},
                pipeline_trace=report.pipeline_trace if isinstance(report.pipeline_trace, dict) else {},
            )
            chart_type = (
                ChartType.LINE
                if forecast_request.get("requires_forecast")
                and chart_config.get("forecasting", {}).get("status") in {"success", "degraded"}
                else self._infer_chart_type(
                    visualization_columns,
                    visualization_rows,
                    report.intent_json,
                    preferred_chart_type=upstream_chart_type,
                )
            )
            report.chart_type = chart_type
            chart_config["selected_chart_type"] = chart_type
            chart_config["chart_type"] = chart_type
            chart_config["reason_chart_selected"] = (
                "forecast_actual_overlay"
                if chart_config.get("forecasting", {}).get("forecast_available")
                else (
                    "historical_only_forecast_fallback"
                    if chart_config.get("forecasting", {}).get("enabled")
                    else upstream_chart_type or "shape_and_intent_inference"
                )
            )
            report.chart_config = chart_config
            chart_settings = self._build_visualization_settings(report, chart_type)
            axes_dimensions = chart_settings.get("graph.dimensions", [])
            axes_metrics = chart_settings.get("graph.metrics", [])
            chart_config["x_axis"] = axes_dimensions[0] if axes_dimensions else ""
            chart_config["y_axis"] = axes_metrics[0] if axes_metrics else ""
            
            # Create visualization through Visualization Service.
            visualization_result = self._create_visualization_with_service(
                request=request,
                report=report,
                sql=visualization_sql,
                chart_type=chart_type,
                visualization_settings=chart_settings,
            )
            if not visualization_result.get('success'):
                return self._metabase_failure_response(
                    report=report,
                    chart_type=chart_type,
                    row_count=len(visualization_rows),
                    execution_time_ms=query_result['execution_time_ms'],
                    failure_reason=visualization_result.get('failure_reason', 'visualization_service_failed'),
                    details=visualization_result.get('error'),
                    http_status=visualization_result.get('http_status', status.HTTP_502_BAD_GATEWAY),
                    clear_question=visualization_result.get('clear_question', True),
                )

            question_id = visualization_result.get('question_id')
            dashboard_id = visualization_result.get('dashboard_id')
            embed_url = visualization_result.get('embed_url', '')
            report.metabase_question_id = question_id
            report.metabase_dashboard_id = dashboard_id
            
            # TODO: Save chart inference when ChartInference model is added
            # ChartInference.objects.create(
            #     report=report,
            #     inferred_type=chart_type,
            #     column_analysis={
            #         'columns': query_result['columns'],
            #         'row_count': query_result['row_count']
            #     },
            #     confidence_score=0.85
            # )
            
            report.chart_type = chart_type
            report.status = VoiceReport.STATUS_VISUALIZATION_CREATED
            report.error_message = ''
            report.embed_url = ''
            chart_config["metabase"] = {
                "question_id": question_id,
                "dashboard_id": dashboard_id,
                "display": visualization_result.get("display") or chart_type,
                "fallback_applied": bool(visualization_result.get("fallback_applied")),
                "fallback_reason": visualization_result.get("fallback_reason", ""),
            }
            metabase_settings = visualization_result.get("visualization_settings", {})
            if isinstance(metabase_settings, dict):
                dimensions = metabase_settings.get("graph.dimensions", [])
                metrics = metabase_settings.get("graph.metrics", [])
                if isinstance(dimensions, list) and dimensions:
                    chart_config["x_axis"] = dimensions[0]
                if isinstance(metrics, list) and metrics:
                    chart_config["y_axis"] = metrics[0]
            report.chart_config = chart_config
            report.ai_trace = build_report_ai_trace(report, embed_url=embed_url)
            report.save()

            publish_kafka_event(
                'report.visualization.ready',
                {
                    'report_id': report.id,
                    'workspace_id': report.workspace_id,
                    'user_id': request.user.id,
                    'metabase_question_id': question_id,
                    'metabase_dashboard_id': dashboard_id,
                },
                key=str(report.id),
            )

            notification_client = get_notification_client()
            workspace_owner = report.workspace.owner if report.workspace else None
            owner_email = workspace_owner.email if workspace_owner else None
            owner_name = workspace_owner.name if workspace_owner else None
            notification_result = notification_client.send_event(
                event_type='workspace_report_created',
                event_key=f"report-created:{report.id}",
                payload={
                    'workspace_id': report.workspace_id,
                    'workspace_name': report.workspace.name if report.workspace else None,
                    'owner_email': owner_email,
                    'owner_name': owner_name,
                    'recipient_emails': [owner_email] if owner_email else [],
                    'report_id': report.id,
                    'created_by_user_id': request.user.id,
                    'created_by_name': request.user.name,
                },
            )
            if not notification_result.get('success'):
                logger.warning(
                    "workspace_report_created notification dispatch failed report=%s workspace=%s error=%s",
                    report.id,
                    report.workspace_id,
                    notification_result.get('error'),
                )
            
            # TODO: Create history entry when ReportHistory model is added
            # ReportHistory.objects.create(
            #     report=report,
            #     action='executed',
            #     performed_by=request.user,
            #     changes={
            #         'row_count': query_result['row_count'],
            #         'execution_time_ms': query_result['execution_time_ms'],
            #         'chart_type': chart_type
            #     }
            # )
            
            logger.info(f"Report {report.id} executed successfully")
            
            response_payload = {
                'success': True,
                'report_id': report.id,
                'row_count': len(visualization_rows),
                'execution_time_ms': query_result['execution_time_ms'],
                'chart_type': chart_type,
                'status': report.status,
                'embed_url': embed_url,
                'metabase_question_id': question_id,
                'confidence': ai_contract.get('confidence'),
                'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                'degraded': ai_contract.get('degraded'),
            }
            if isinstance(chart_config.get("forecasting"), dict):
                response_payload['forecasting'] = chart_config.get("forecasting")
            return Response(response_payload)
        
        except Exception as e:
            logger.error(f"Error in QueryExecuteView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _metabase_failure_response(
        self,
        *,
        report,
        chart_type,
        row_count,
        execution_time_ms,
        failure_reason,
        http_status,
        details=None,
        clear_question=True
    ):
        """Persist visualization failure and return a structured API error."""
        logger.error(
            "Metabase visualization failed for report %s: reason=%s details=%s",
            report.id,
            failure_reason,
            details
        )
        report.status = VoiceReport.STATUS_FAILED
        report.error_message = (
            f"metabase_visualization_failed: {failure_reason}"
            if not details
            else f"metabase_visualization_failed: {failure_reason} ({details})"
        )
        report.embed_url = ''
        if clear_question:
            report.metabase_question_id = None
            report.metabase_dashboard_id = None
        report.ai_trace = build_report_ai_trace(report)
        report.save()

        response_payload = {
            'success': False,
            'error': 'metabase_visualization_failed',
            'report_id': report.id,
            'row_count': row_count,
            'execution_time_ms': execution_time_ms,
            'chart_type': chart_type,
        }
        if details:
            response_payload['details'] = details

        return Response(response_payload, status=http_status)
    
    def _infer_chart_type(self, columns, rows, intent, preferred_chart_type: str = ""):
        """Infer a render-safe chart using intent + result shape, preserving valid upstream choices."""
        resolved = infer_chart_type(
            columns=columns if isinstance(columns, list) else [],
            rows=rows if isinstance(rows, list) else [],
            intent=intent if isinstance(intent, dict) else {},
            preferred_chart_type=preferred_chart_type,
        )
        return normalize_chart_type(resolved, default=ChartType.TABLE)
    
    def _service_headers(self, request):
        headers = {'Content-Type': 'application/json'}
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if auth_header:
            headers['Authorization'] = auth_header
        return headers

    def _response_error_message(self, response, default):
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload.get('error') or payload.get('message') or default
        except Exception:
            pass
        return (response.text or default)[:500]

    def _execute_query_with_query_service(self, request, clean_sql):
        query_service_url = os.getenv('QUERY_SERVICE_URL', 'http://query-service:8006').rstrip('/')
        payload = {
            'sql': clean_sql,
            'workspace_database': os.getenv('CLICKHOUSE_DATABASE', 'etl'),
        }

        try:
            response = requests.post(
                f'{query_service_url}/query/execute/',
                json=payload,
                headers=self._service_headers(request),
                timeout=120,
            )
            if response.status_code == status.HTTP_200_OK:
                result = response.json()
                if result.get('success'):
                    return result
                return {
                    'success': False,
                    'error': result.get('error', 'query_service_execution_failed'),
                }

            return {
                'success': False,
                'error': self._response_error_message(response, 'query_service_execution_failed'),
            }
        except requests.RequestException as exc:
            logger.warning("Query service unavailable, using local fallback: %s", exc)

        # Fallback keeps behavior stable if query-service is temporarily unavailable.
        try:
            executor = get_clickhouse_executor()
            return executor.execute_query(clean_sql)
        except Exception as exc:
            return {
                'success': False,
                'error': f'query_service_and_fallback_failed: {exc}',
            }

    def _build_visualization_settings(self, report, chart_type):
        query_result = report.query_result if isinstance(report.query_result, dict) else {}
        columns_payload = query_result.get('columns', []) if isinstance(query_result.get('columns', []), list) else []
        rows_payload = query_result.get('rows', []) if isinstance(query_result.get('rows', []), list) else []
        intent_payload = report.intent_json if isinstance(report.intent_json, dict) else {}

        def _is_numeric_like(value):
            if isinstance(value, bool):
                return False
            if isinstance(value, (int, float)):
                return True
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    return False
                if stripped.startswith('-'):
                    stripped = stripped[1:]
                return stripped.replace('.', '', 1).isdigit()
            return False

        def _type_is_numeric(column_type):
            lowered = str(column_type or '').strip().lower()
            if not lowered:
                return False
            return any(token in lowered for token in ('int', 'float', 'double', 'decimal', 'numeric'))

        column_names = []
        column_specs = []
        for column in columns_payload:
            if isinstance(column, dict):
                name = str(column.get('name', '')).strip()
                col_type = str(column.get('type', '')).strip()
            else:
                name = str(column or '').strip()
                col_type = ''
            if name:
                column_names.append(name)
                column_specs.append({'name': name, 'type': col_type, 'is_numeric': _type_is_numeric(col_type)})

        numeric_columns = []
        for index, name in enumerate(column_names):
            column_spec = column_specs[index] if index < len(column_specs) else {}
            if column_spec.get('is_numeric'):
                numeric_columns.append(name)
                continue
            sample_values = [row.get(name) for row in rows_payload[:25] if isinstance(row, dict) and row.get(name) is not None]
            if sample_values and all(_is_numeric_like(value) for value in sample_values):
                numeric_columns.append(name)

        time_columns = [
            name for name in column_names
            if any(token in name.lower() for token in ('date', 'time', 'period', 'day', 'week', 'month', 'year'))
        ]
        categorical_columns = [name for name in column_names if name not in numeric_columns]
        normalized_chart_type = normalize_chart_type(chart_type, default=ChartType.TABLE)
        chart_config = report.chart_config if isinstance(report.chart_config, dict) else {}
        forecasting_config = chart_config.get("forecasting", {}) if isinstance(chart_config.get("forecasting"), dict) else {}
        forecast_meta = forecasting_config.get("meta", {}) if isinstance(forecasting_config.get("meta"), dict) else {}

        metrics_from_intent = []
        for metric in (intent_payload.get("metrics", []) or []):
            if isinstance(metric, dict):
                metric_name = str(metric.get("alias") or metric.get("column") or "").strip()
            else:
                metric_name = str(metric or "").strip()
            if metric_name:
                metrics_from_intent.append(metric_name)
        dimensions_from_intent = [
            str(dim).strip()
            for dim in (intent_payload.get("dimensions", []) or [])
            if str(dim).strip()
        ]
        preferred_metric = next((metric for metric in metrics_from_intent if metric in column_names), "")
        preferred_dimension = next((dim for dim in dimensions_from_intent if dim in column_names), "")

        settings = {
            'display': normalized_chart_type,
            'chart_type': normalized_chart_type,
            'numeric_columns': numeric_columns,
            'time_columns': time_columns,
            'category_columns': categorical_columns,
            'row_count': len(rows_payload),
            'dataset_columns': column_specs,
            'result_rows': [row for row in rows_payload[:100] if isinstance(row, dict)],
            'reason_chart_selected': chart_config.get('reason_chart_selected', ''),
        }
        if forecasting_config:
            settings['forecast_available'] = bool(forecasting_config.get('forecast_available'))
            settings['forecasting_status'] = forecasting_config.get('status', '')
            settings['series_type_field'] = 'series_type'
            settings['series_label_field'] = 'series_label'
            settings['preferred_color_role_field'] = 'preferred_color_role'
            settings['chart_series_config'] = (
                forecasting_config.get('chart_series_config')
                if isinstance(forecasting_config.get('chart_series_config'), list)
                else forecast_meta.get('chart_series_config', [])
            )
            settings['forecast_start_date'] = forecast_meta.get('forecast_start_date', '')
            settings['forecast_boundary_index'] = forecast_meta.get('actual_points', None)

        if normalized_chart_type == ChartType.SCATTER:
            x_axis = preferred_dimension if preferred_dimension in numeric_columns else ""
            y_axis = preferred_metric if preferred_metric in numeric_columns else ""
            if not x_axis and len(numeric_columns) >= 1:
                x_axis = numeric_columns[0]
            if not y_axis and len(numeric_columns) >= 2:
                y_axis = numeric_columns[1]
            if not y_axis and len(numeric_columns) >= 1:
                y_axis = numeric_columns[0]
            if x_axis and y_axis:
                if x_axis == y_axis and len(numeric_columns) >= 2:
                    y_axis = numeric_columns[1]
                settings['graph.dimensions'] = [x_axis]
                settings['graph.metrics'] = [y_axis]
        elif normalized_chart_type == ChartType.LINE:
            time_dimension = preferred_dimension if preferred_dimension in time_columns else ""
            metric_column = preferred_metric if preferred_metric in numeric_columns else ""
            if not time_dimension and time_columns:
                time_dimension = time_columns[0]
            if not metric_column and numeric_columns:
                metric_column = numeric_columns[0]
            if time_dimension and metric_column:
                settings['graph.dimensions'] = [time_dimension]
                settings['graph.metrics'] = [metric_column]
                if forecasting_config and 'series_type' in column_names:
                    settings['graph.breakout'] = ['series_type']
        elif normalized_chart_type == ChartType.HISTOGRAM:
            metric_column = preferred_metric if preferred_metric in numeric_columns else ""
            if not metric_column and numeric_columns:
                metric_column = numeric_columns[0]
            if metric_column:
                settings['graph.metrics'] = [metric_column]
        elif normalized_chart_type == ChartType.BAR:
            dimension_column = preferred_dimension if preferred_dimension in categorical_columns else ""
            metric_column = preferred_metric if preferred_metric in numeric_columns else ""
            if not dimension_column and categorical_columns:
                dimension_column = categorical_columns[0]
            if not metric_column and numeric_columns:
                metric_column = numeric_columns[0]
            if dimension_column and metric_column:
                settings['graph.dimensions'] = [dimension_column]
                settings['graph.metrics'] = [metric_column]
        return settings

    def _create_visualization_with_service(self, request, report, sql, chart_type, visualization_settings=None):
        visualization_service_url = os.getenv(
            'VISUALIZATION_SERVICE_URL',
            'http://visualization-service:8007'
        ).rstrip('/')
        headers = self._service_headers(request)
        visualization_settings = (
            visualization_settings
            if isinstance(visualization_settings, dict)
            else self._build_visualization_settings(report, chart_type)
        )
        logger.info(
            "chart_selected=%s fallback_applied=%s report_id=%s",
            chart_type,
            False,
            report.id,
        )
        try:
            question_response = requests.post(
                f'{visualization_service_url}/visualization/question/create/',
                json={
                    'name': f"Voice Report #{report.id}: {report.transcription[:50]}",
                    'sql': sql,
                    'chart_type': chart_type,
                    'visualization_settings': visualization_settings,
                },
                headers=headers,
                timeout=120,
            )
        except requests.RequestException as exc:
            return {
                'success': False,
                'failure_reason': 'question_creation_failed',
                'error': f'visualization_service_unavailable: {exc}',
                'http_status': status.HTTP_502_BAD_GATEWAY,
            }
        if question_response.status_code != status.HTTP_200_OK:
            return {
                'success': False,
                'failure_reason': 'question_creation_failed',
                'error': self._response_error_message(question_response, 'question_creation_failed'),
                'http_status': status.HTTP_502_BAD_GATEWAY,
            }

        question_payload = question_response.json()
        question_id = question_payload.get('question_id')
        if not question_id:
            return {
                'success': False,
                'failure_reason': 'question_creation_failed',
                'error': 'visualization_service_missing_question_id',
                'http_status': status.HTTP_502_BAD_GATEWAY,
            }
        logger.info(
            "chart_sent_to_metabase=%s report_id=%s question_id=%s",
            visualization_settings.get('display'),
            report.id,
            question_id,
        )
        result_metadata = {
            'display': question_payload.get('display') or visualization_settings.get('display'),
            'fallback_applied': bool(question_payload.get('fallback_applied')),
            'fallback_reason': question_payload.get('fallback_reason', ''),
            'visualization_settings': visualization_settings,
        }

        dashboard_id = self._get_or_create_dashboard(
            workspace=report.workspace,
            visualization_service_url=visualization_service_url,
            headers=headers,
        )

        if dashboard_id:
            try:
                requests.post(
                    f'{visualization_service_url}/visualization/dashboard/add-question/',
                    json={'question_id': question_id, 'dashboard_id': dashboard_id},
                    headers=headers,
                    timeout=60,
                )
            except requests.RequestException as exc:
                logger.warning(
                    "Failed adding question %s to dashboard %s: %s",
                    question_id,
                    dashboard_id,
                    exc
                )

        try:
            embed_response = requests.get(
                f'{visualization_service_url}/visualization/question/{question_id}/embed-url/',
                headers=headers,
                timeout=60,
            )
        except requests.RequestException as exc:
            return {
                'success': False,
                'failure_reason': 'embed_generation_failed',
                'error': f'visualization_service_unavailable: {exc}',
                'http_status': status.HTTP_502_BAD_GATEWAY,
                'clear_question': False,
            }
        if embed_response.status_code != status.HTTP_200_OK:
            return {
                'success': False,
                'failure_reason': 'embed_generation_failed',
                'error': self._response_error_message(embed_response, 'embed_generation_failed'),
                'http_status': status.HTTP_502_BAD_GATEWAY,
                'clear_question': False,
            }

        embed_payload = embed_response.json()
        embed_url = embed_payload.get('embed_url')
        if not embed_url:
            return {
                'success': False,
                'failure_reason': 'embed_generation_failed',
                'error': 'visualization_service_missing_embed_url',
                'http_status': status.HTTP_502_BAD_GATEWAY,
                'clear_question': False,
            }

        return {
            'success': True,
            'question_id': question_id,
            'dashboard_id': dashboard_id,
            'embed_url': embed_url,
            **result_metadata,
        }

    def _get_or_create_dashboard(self, workspace, visualization_service_url, headers):
        """Get an existing workspace dashboard ID or create one through visualization service."""
        existing_report = VoiceReport.objects.filter(
            workspace=workspace,
            metabase_dashboard_id__isnull=False
        ).first()
        if existing_report:
            return existing_report.metabase_dashboard_id
        try:
            response = requests.post(
                f'{visualization_service_url}/visualization/dashboard/create/',
                json={
                    'name': f'Workspace {workspace.id} - Voice Reports',
                    'description': f'Voice-driven reports for {workspace.name}',
                },
                headers=headers,
                timeout=120,
            )
        except requests.RequestException as exc:
            logger.warning(
                "Failed to create dashboard for workspace=%s due to connectivity error=%s",
                workspace.id,
                exc
            )
            return None
        if response.status_code != status.HTTP_200_OK:
            logger.warning(
                "Failed to create dashboard for workspace=%s error=%s",
                workspace.id,
                self._response_error_message(response, 'dashboard_creation_failed')
            )
            return None

        payload = response.json()
        return payload.get('dashboard_id')


class SQLEditView(APIView):
    """
    Edit SQL query (Analyst only).
    """
    permission_classes = [IsAuthenticated, IsAnalyst]
    
    def put(self, request, report_id):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace
            )
            
            new_sql = request.data.get('sql')
            
            if not new_sql:
                return Response(
                    {'success': False, 'error': 'SQL is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate new SQL
            guard = SQLGuard(
                workspace_database=os.getenv('CLICKHOUSE_DATABASE', 'default')
            )
            
            is_valid, error_msg, clean_sql = guard.validate_and_sanitize(new_sql)
            
            if not is_valid:
                return Response(
                    {'success': False, 'error': error_msg},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Save old SQL for history
            old_sql = report.final_sql
            
            # Update report
            report.final_sql = clean_sql
            report.sql_edited = True
            report.edited_by = request.user
            report.sql_validated = True
            report.status = VoiceReport.STATUS_PENDING  # Needs re-execution
            report.ai_trace = build_report_ai_trace(report)
            report.save()
            
            # TODO: Create history entry when ReportHistory model is added
            # ReportHistory.objects.create(
            #     report=report,
            #     action='sql_edited',
            #     performed_by=request.user,
            #     changes={
            #         'old_sql': old_sql,
            #         'new_sql': clean_sql
            #     }
            # )
            
            logger.info(f"Report {report.id} SQL edited by analyst {request.user.email}")
            
            return Response({
                'success': True,
                'report_id': report.id,
                'sql': clean_sql,
                'message': 'SQL updated successfully. Ready to re-execute.'
            })
        
        except Exception as e:
            logger.error(f"Error in SQLEditView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ReportListView(APIView):
    """
    List all reports for workspace.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            reports = VoiceReport.objects.filter(
                workspace=workspace
            ).order_by('-created_at')
            
            # Filter by role
            if request.user.role == 'manager':
                # Manager sees only their own reports
                reports = reports.filter(created_by=request.user)
            # Analyst and Executive see all workspace reports
            
            metabase = get_metabase_service()
            data = []
            for report in reports:
                embed_url = get_report_embed_url(report, metabase_service=metabase)
                ai_contract = extract_report_contract(report)
                data.append({
                    'id': report.id,
                    'transcription': report.transcription,
                    'status': report.status,
                    'created_at': report.created_at,
                    'created_by': report.created_by.email,
                    'chart_type': report.chart_type,
                    'row_count': report.row_count,
                    'execution_time_ms': report.execution_time_ms,
                    'sql': report.final_sql,
                    'embed_url': embed_url,
                    'metabase_question_id': report.metabase_question_id,
                    'confidence': ai_contract.get('confidence'),
                    'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                    'degraded': ai_contract.get('degraded'),
                    'can_edit': request.user.role == 'analyst'
                })
            logger.info(
                "Report list loaded for user=%s workspace=%s count=%s",
                request.user.id,
                workspace.id,
                len(data)
            )
            
            return Response({
                'success': True,
                'reports': data,
                'count': len(data)
            })
        
        except Exception as e:
            logger.error(f"Error in ReportListView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ReportDetailView(APIView):
    """
    Get detailed report information.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, report_id):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace
            )
            
            # TODO: Get history when ReportHistory model is added
            # history = ReportHistory.objects.filter(report=report).order_by('-timestamp')
            # history_data = [{
            #     'action': h.action,
            #     'performed_by': h.performed_by.email,
            #     'timestamp': h.timestamp,
            #     'changes': h.changes
            # } for h in history]
            history_data = []  # Placeholder until ReportHistory is added
            embed_url = get_report_embed_url(report)
            preprocessing_low = normalize_preprocessing_low(
                report.preprocessing_low,
                fallback_text=report.transcription,
            )
            preprocessing_high = normalize_preprocessing_high(
                report.preprocessing_high,
                fallback_query=preprocessing_low.get("cleaned_text", report.transcription),
            )
            pipeline_trace = normalize_pipeline_trace(report.pipeline_trace)
            ai_contract = extract_report_contract(report)
            ai_trace = build_report_ai_trace(report, embed_url=embed_url)
            if report.ai_trace != ai_trace:
                report.ai_trace = ai_trace
                report.save(update_fields=['ai_trace', 'updated_at'])
            
            return Response({
                'success': True,
                'report': {
                    'id': report.id,
                    'transcription': report.transcription,
                    'intent': report.intent_json,
                    'generated_sql': report.generated_sql,
                    'final_sql': report.final_sql,
                    'status': report.status,
                    'sql_validated': report.sql_validated,
                    'sql_edited': report.sql_edited,
                    'query_result': report.query_result,
                    'row_count': report.row_count,
                    'execution_time_ms': report.execution_time_ms,
                    'chart_type': report.chart_type,
                    'metabase_question_id': report.metabase_question_id,
                    'metabase_dashboard_id': report.metabase_dashboard_id,
                    'embed_url': embed_url,
                    'preprocessing_low': preprocessing_low,
                    'preprocessing_high': preprocessing_high,
                    'pipeline_trace': pipeline_trace,
                    'ai_trace': ai_trace,
                    'confidence': ai_contract.get('confidence'),
                    'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                    'degraded': ai_contract.get('degraded'),
                    'overall_status': pipeline_trace.get('overall_status'),
                    'root_cause': pipeline_trace.get('root_cause'),
                    'error_message': report.error_message,
                    'created_at': report.created_at,
                    'created_by': report.created_by.email,
                    'edited_by': report.edited_by.email if report.edited_by else None,
                    'history': history_data
                }
            })
        
        except Exception as e:
            logger.error(f"Error in ReportDetailView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request, report_id):
        """Delete report (Manager only)."""
        if request.user.role != 'manager':
            return Response(
                {'success': False, 'error': 'Only managers can delete reports'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace,
                created_by=request.user  # Can only delete own reports
            )
            
            report.delete()
            
            logger.info(f"Report {report_id} deleted by {request.user.email}")
            
            return Response({
                'success': True,
                'message': 'Report deleted successfully'
            })
        
        except Http404:
            return Response(
                {'success': False, 'error': 'Report not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error deleting report: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WorkspaceDashboardView(APIView):
    """
    Get workspace dashboard for embedded viewing (Executive).
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get dashboard ID from any report
            report = VoiceReport.objects.filter(
                workspace=workspace,
                metabase_dashboard_id__isnull=False
            ).first()
            
            if not report:
                return Response({
                    'success': False,
                    'error': 'No dashboard available yet. Create some reports first.'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Generate fresh JWT embed URL for dashboard.
            metabase = get_metabase_service()
            embed_url = metabase.get_dashboard_embed_url(
                dashboard_id=report.metabase_dashboard_id
            )
            if not embed_url:
                return Response({
                    'success': False,
                    'error': metabase.last_error or 'Failed to generate dashboard embed URL'
                }, status=status.HTTP_502_BAD_GATEWAY)
            
            return Response({
                'success': True,
                'dashboard_url': embed_url,
                'dashboard_id': report.metabase_dashboard_id
            })
        
        except Exception as e:
            logger.error(f"Error in WorkspaceDashboardView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DashboardStatsView(APIView):
    """
    Return dashboard counters for the current user scope.
    """
    permission_classes = [IsAuthenticated]

    SUCCESS_STATUSES = (
        VoiceReport.STATUS_VISUALIZATION_CREATED,
        VoiceReport.STATUS_EXECUTED,
        VoiceReport.STATUS_COMPLETED,  # legacy
    )

    PROCESSING_STATUSES = (
        VoiceReport.STATUS_PENDING,
        VoiceReport.STATUS_PROCESSING,
        VoiceReport.STATUS_PENDING_EXECUTION,  # legacy
        VoiceReport.STATUS_EXECUTING,  # legacy
    )

    def get(self, request):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            reports = VoiceReport.objects.filter(workspace=workspace)

            # Preserve list visibility semantics:
            # managers only see their own reports; others see workspace reports.
            if request.user.role == 'manager':
                reports = reports.filter(created_by=request.user)

            total_reports = reports.count()
            completed_reports = reports.filter(status__in=self.SUCCESS_STATUSES).count()
            failed_reports = reports.filter(status=VoiceReport.STATUS_FAILED).count()
            processing_reports = reports.filter(status__in=self.PROCESSING_STATUSES).count()
            total_rows = reports.aggregate(
                total_rows=Coalesce(Sum('row_count'), 0)
            )['total_rows']

            payload = {
                'success': True,
                'total_reports': total_reports,
                'completed_reports': completed_reports,
                'failed_reports': failed_reports,
                'processing_reports': processing_reports,
                'total_rows': int(total_rows or 0),
            }
            logger.info(
                "Dashboard stats loaded for user=%s workspace=%s payload=%s",
                request.user.id,
                workspace.id,
                payload
            )
            return Response(payload)
        except Exception as e:
            logger.error("Error in DashboardStatsView: %s", e, exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class HealthCheckView(APIView):
    """
    Health check for all services.
    """
    permission_classes = []  # Public endpoint
    
    def get(self, request):
        """Check connectivity to Small Whisper, ClickHouse, and Metabase."""
        health = {
            'small_whisper': False,
            'clickhouse': False,
            'metabase': False
        }
        
        # Check Small Whisper
        try:
            whisper_client = get_small_whisper_client()
            response = requests.get(f"{whisper_client.base_url}/health/", timeout=5)
            health['small_whisper'] = response.status_code == 200
        except:
            pass
        
        # Check ClickHouse
        try:
            executor = get_clickhouse_executor()
            health['clickhouse'] = executor.test_connection()
        except:
            pass
        
        # Check Metabase
        try:
            metabase = get_metabase_service()
            health['metabase'] = metabase.authenticate()
        except:
            pass
        
        all_healthy = all(health.values())
        
        return Response({
            'success': all_healthy,
            'services': health,
            'message': 'All services healthy' if all_healthy else 'Some services unavailable'
        }, status=status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE)

