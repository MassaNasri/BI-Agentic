"""
Voice Reports Views

API endpoints for voice-driven BI system.
Orchestrates Small Whisper, the authoritative Query service, and Metabase.
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
from django.conf import settings
import logging
import os
import time
import uuid
from urllib.parse import urlsplit
import requests
from bi_platform_shared.sql import sanitize_sql_for_metabase
from bi_platform_shared.uploads import validate_upload, UploadRejected, AUDIO_MAX_BYTES
from bi_platform_shared.contracts.chart import (
    chart_shape_support_failure as shared_chart_shape_support_failure,
    is_chart_shape_supported,
    profile_chart_shape,
)
from bi_platform_shared.contracts.viz import (
    VisualizationSpec,
    VisualizationSpecError,
    build_visualization_spec,
    transform_visualization_spec,
)

from .models import VoiceReport, SQLEditHistory
from .constants import (
    ChartType,
    VALID_CHART_TYPES,
    LEGACY_TO_CANONICAL_CHART_TYPE,
    normalize_chart_type,
    to_metabase_display,
)
from .services import (
    get_small_whisper_client,
    SQLGuard,
    get_metabase_service,
    get_jwt_service,
    get_event_publisher,
    get_subscription_client,
    get_notification_client,
)
from .services.clickhouse_executor import sanitize_query_results
from .services.forecasting_bridge import build_forecast_payload, detect_forecast_metadata
from .services.ai_trace_service import build_ai_trace_payload
from .infrastructure.auth_context import extract_identity_context, require_authorized_workspace
from .infrastructure.workspace_client import get_workspace_client
from users.permissions import IsManager, IsAnalyst, IsExecutive

logger = logging.getLogger(__name__)
LOW_CHANGE_TYPES = {"removed_noise", "normalized", "reduced_repetition", "removed_filler_words", "removed_noise_tags", "removed_noise_tokens", "normalized_repeated_characters", "normalized_punctuation", "normalized_whitespace", "removed_control_chars", "removed_malformed_symbols", "normalized_control_chars", "semantic_preservation_rejected"}
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
EMBED_TOKEN_REFRESH_LEEWAY_SECONDS = int(os.getenv("METABASE_EMBED_REFRESH_LEEWAY_SECONDS", "300"))
MANUAL_CHART_SWITCH_ROLES = {"manager", "analyst"}
CHART_TYPE_CATALOG = (
    {"type": ChartType.LINE, "label": "Line", "icon": "line"},
    {"type": ChartType.LINE_MULTI, "label": "Multi Line", "icon": "line-multi"},
    {"type": ChartType.BAR, "label": "Bar", "icon": "bar"},
    {"type": ChartType.BAR_GROUPED, "label": "Grouped Bar", "icon": "bar-grouped"},
    {"type": ChartType.BAR_STACKED, "label": "Stacked Bar", "icon": "bar-stacked"},
    {"type": ChartType.PIE, "label": "Pie", "icon": "pie"},
    {"type": ChartType.AREA, "label": "Area", "icon": "area"},
    {"type": ChartType.SCATTER, "label": "Scatter", "icon": "scatter"},
    {"type": ChartType.HISTOGRAM, "label": "Histogram", "icon": "histogram"},
    {"type": ChartType.MAP, "label": "Map", "icon": "map"},
    {"type": ChartType.HEATMAP, "label": "Heatmap", "icon": "heatmap"},
    {"type": ChartType.COMBO_LINE_BAR, "label": "Combo", "icon": "combo-line-bar"},
    {"type": ChartType.CUMULATIVE_LINE, "label": "Cumulative Line", "icon": "cumulative-line"},
    {"type": ChartType.CARD, "label": "Card", "icon": "card"},
    {"type": ChartType.TABLE, "label": "Table", "icon": "table"},
)


def _actor_role(request, identity) -> str:
    return str(identity.role or getattr(request.user, "role", "") or "").strip().lower()


def _normalize_requested_chart_type(raw_chart_type: str) -> str:
    token = str(raw_chart_type or "").strip().lower()
    if not token:
        return ""
    if token in VALID_CHART_TYPES:
        return token
    return str(LEGACY_TO_CANONICAL_CHART_TYPE.get(token, "")).strip().lower()


def _resolve_report_chart_type(report: VoiceReport) -> str:
    chart_config = report.chart_config if isinstance(report.chart_config, dict) else {}
    raw_chart_type = (
        report.chart_type
        or chart_config.get("selected_chart_type")
        or chart_config.get("chart_type")
        or chart_config.get("requested_chart_type")
        or ChartType.TABLE
    )
    return normalize_chart_type(raw_chart_type, default=ChartType.TABLE)


def _chart_shape_support_failure(chart_type: str, shape: dict) -> tuple[str, str]:
    return shared_chart_shape_support_failure(chart_type, shape)


def _chart_capability_item(chart_spec: dict, *, shape: dict, selected_chart_type: str) -> dict:
    chart_type = str(chart_spec.get("type") or "").strip()
    supported = bool(is_chart_shape_supported(chart_type, shape))
    reason_code, reason = ("", "") if supported else _chart_shape_support_failure(chart_type, shape)
    return {
        "type": chart_type,
        "label": str(chart_spec.get("label") or chart_type),
        "icon": str(chart_spec.get("icon") or ""),
        "metabase_display": to_metabase_display(chart_type),
        "supported": supported,
        "selected": chart_type == selected_chart_type,
        "unsupported_reason_code": reason_code,
        "unsupported_reason": reason,
    }


def _report_query_metadata(report: VoiceReport) -> dict:
    query_result = report.query_result if isinstance(report.query_result, dict) else {}
    chart_config = report.chart_config if isinstance(report.chart_config, dict) else {}
    columns = query_result.get("columns") if isinstance(query_result.get("columns"), list) else []
    rows = query_result.get("rows") if isinstance(query_result.get("rows"), list) else []
    result_shape = query_result.get("result_shape") if isinstance(query_result.get("result_shape"), dict) else {}
    if not result_shape and isinstance(chart_config.get("result_shape"), dict):
        result_shape = chart_config["result_shape"]
    profiled_shape = profile_chart_shape(columns, rows)
    if not result_shape:
        result_shape = profiled_shape
    if not str(result_shape.get("type") or "").strip():
        # Historical reports stored the chart profiler shape, while the newer
        # VisualizationSpec contract expects the canonical ResultShape fields.
        # Adapt in memory so old rows render without a data migration.
        metric_fields = list(profiled_shape.get("numeric_columns") or [])
        time_fields = list(profiled_shape.get("time_like_columns") or [])
        category_fields = [
            field
            for field in list(profiled_shape.get("category_columns") or [])
            if field not in time_fields
        ]
        time_field = time_fields[0] if time_fields else None
        series_fields = []
        if time_field and len(category_fields) == 1:
            series_fields = list(category_fields)
            category_fields = []

        if profiled_shape.get("single_value"):
            shape_type = "single_value"
        elif time_field and metric_fields and series_fields:
            shape_type = "time_series_grouped"
        elif time_field and metric_fields:
            shape_type = "time_series"
        elif category_fields and len(metric_fields) >= 2:
            shape_type = "multi_metric"
        elif category_fields and metric_fields:
            shape_type = "grouped"
        elif len(metric_fields) >= 2:
            shape_type = "multi_metric"
        else:
            shape_type = "raw"

        result_shape = {
            **result_shape,
            "type": shape_type,
            "time_field": time_field,
            "category_fields": category_fields,
            "series_fields": series_fields,
            "metric_fields": metric_fields,
            "row_count": int(profiled_shape.get("row_count", len(rows)) or 0),
        }
    return {
        "columns": columns,
        "rows": rows,
        "result_shape": result_shape,
    }


def _load_or_derive_visualization_spec(report: VoiceReport, *, chart_type: str | None = None) -> VisualizationSpec:
    requested_type = normalize_chart_type(chart_type or _resolve_report_chart_type(report), default=ChartType.TABLE)
    if isinstance(report.visualization_spec, dict):
        try:
            spec = VisualizationSpec.model_validate(report.visualization_spec)
            if normalize_chart_type(str(spec.chart_type), default=ChartType.TABLE) == requested_type:
                return spec
        except Exception:
            logger.warning("Stored visualization_spec could not be validated for report=%s", report.id)

    query_metadata = _report_query_metadata(report)
    chart_config = report.chart_config if isinstance(report.chart_config, dict) else {}
    recommendation = (
        chart_config.get("chart_recommendation")
        if isinstance(chart_config.get("chart_recommendation"), dict)
        else None
    )
    return build_visualization_spec(
        chart_type=requested_type,
        result_shape=query_metadata["result_shape"],
        columns=query_metadata["columns"],
        recommendation_metadata=recommendation,
    )


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
    normalized_payload = dict(chart_payload)
    if not str(raw_type or "").strip():
        return normalized_payload
    normalized_type = normalize_chart_type(raw_type, default="")
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


def get_user_workspace_id(request) -> str:
    """
    Resolve workspace through workspace-service over HTTP.
    """
    identity = extract_identity_context(request)
    context = require_authorized_workspace(get_workspace_client().resolve(
        request=request, workspace_hint=identity.workspace_hint, user_id=identity.user_id,
    ))
    return str(context.workspace_id or "").strip()


def _extract_embed_token(embed_url: str) -> str:
    if not embed_url:
        return ""
    parsed = urlsplit(embed_url)
    path = str(parsed.path or "").strip().strip("/")
    parts = path.split("/")
    if len(parts) < 3:
        return ""
    if parts[-2] not in {"question", "dashboard"}:
        return ""
    return str(parts[-1] or "").strip()


def _is_cached_embed_token_fresh(embed_url: str) -> bool:
    token = _extract_embed_token(embed_url)
    if not token:
        return False
    payload = get_jwt_service().verify_token(token)
    if not isinstance(payload, dict):
        return False
    try:
        exp = int(payload.get("exp") or 0)
    except (TypeError, ValueError):
        return False
    return exp > int(time.time()) + max(0, EMBED_TOKEN_REFRESH_LEEWAY_SECONDS)


def get_report_embed_url(report, metabase_service=None):
    """
    Return a stable Metabase question embed URL.

    Strategy:
    - Reuse cached URL while JWT token is still fresh.
    - Regenerate only when missing/expired.
    - Persist regenerated URL to avoid token churn and iframe reload loops.
    """
    cached_embed_url = str(getattr(report, "embed_url", "") or "").strip()
    if not report.metabase_question_id:
        return cached_embed_url

    if cached_embed_url and _is_cached_embed_token_fresh(cached_embed_url):
        return cached_embed_url

    metabase = metabase_service or get_metabase_service()
    embed_url = metabase.get_question_embed_url(report.metabase_question_id)
    if embed_url:
        if embed_url != cached_embed_url:
            try:
                report.embed_url = embed_url
                report.save(update_fields=["embed_url", "updated_at"])
            except Exception as persist_error:
                logger.warning(
                    "Failed to persist refreshed embed URL report=%s error=%s",
                    getattr(report, "id", None),
                    persist_error,
                )
        return embed_url

    logger.warning(
        "Failed to generate embed URL report=%s question=%s error=%s",
        report.id,
        report.metabase_question_id,
        metabase.last_error
    )
    return cached_embed_url


def _recover_visualization_for_report(request, report) -> None:
    """
    Best-effort recovery for reports that executed successfully but are missing
    Metabase identifiers due to transient visualization outages.
    """
    if report.metabase_question_id:
        return
    if str(report.status or "").strip().lower() not in {
        VoiceReport.STATUS_EXECUTED,
        VoiceReport.STATUS_VISUALIZATION_CREATED,
        VoiceReport.STATUS_COMPLETED,
    }:
        return
    if not str(report.final_sql or "").strip():
        return

    query_result = report.query_result if isinstance(report.query_result, dict) else {}
    rows_payload = query_result.get("rows") if isinstance(query_result.get("rows"), list) else []
    columns_payload = query_result.get("columns") if isinstance(query_result.get("columns"), list) else []
    if not rows_payload:
        return

    executor = QueryExecuteView()
    chart_type = ""
    chart_settings = executor._build_visualization_settings(report, "")

    visualization_result = executor._create_visualization_with_service(
        request=request,
        report=report,
        sql=report.final_sql,
        chart_type="",
        visualization_settings=chart_settings,
    )
    if not visualization_result.get("success"):
        logger.warning(
            "Visualization recovery skipped for report=%s reason=%s details=%s",
            report.id,
            visualization_result.get("failure_reason"),
            visualization_result.get("error"),
        )
        return

    question_id = visualization_result.get("question_id")
    dashboard_id = visualization_result.get("dashboard_id")
    embed_url = str(visualization_result.get("embed_url") or "")
    final_chart_type = normalize_chart_type(
        str(visualization_result.get("chart_type") or visualization_result.get("display") or "").strip(),
        default=chart_type or ChartType.TABLE,
    )

    report.metabase_question_id = question_id
    report.metabase_dashboard_id = dashboard_id
    report.embed_url = embed_url
    report.chart_type = final_chart_type
    report.status = VoiceReport.STATUS_VISUALIZATION_CREATED
    report.error_message = ""
    chart_config = dict(report.chart_config) if isinstance(report.chart_config, dict) else {}
    chart_config["requested_chart_type"] = chart_type
    chart_config["selected_chart_type"] = final_chart_type
    chart_config["chart_type"] = final_chart_type
    chart_config["chart_hint_from_ai"] = visualization_result.get("chart_hint_from_ai") or chart_config.get("chart_hint_from_ai", "")
    chart_config["chart_type_selected_by_visualization_service"] = visualization_result.get("chart_type_selected_by_visualization_service") or final_chart_type
    chart_config["reason_chart_selected"] = "visualization_service_ollama_selector"
    chart_config["metabase"] = {
        "question_id": question_id,
        "dashboard_id": dashboard_id,
        "display": visualization_result.get("metabase_display") or visualization_result.get("display") or final_chart_type,
        "card_display": visualization_result.get("metabase_card_display"),
        "fallback_applied": bool(visualization_result.get("fallback_applied")),
        "fallback_reason": visualization_result.get("fallback_reason", ""),
    }
    chart_config["metabase_visualization_settings"] = (
        visualization_result.get("metabase_visualization_settings")
        if isinstance(visualization_result.get("metabase_visualization_settings"), dict)
        else {}
    )
    chart_config["chart_selection_reason"] = str(visualization_result.get("chart_selection_reason") or "")
    chart_config["result_shape"] = visualization_result.get("result_shape") if isinstance(visualization_result.get("result_shape"), dict) else {}
    visualization_spec = (
        visualization_result.get("visualization_spec")
        if isinstance(visualization_result.get("visualization_spec"), dict)
        else {}
    )
    if visualization_spec:
        chart_config["visualization_spec"] = visualization_spec
        report.visualization_spec = visualization_spec
    chart_config["metabase_status"] = "up"
    chart_config["render_status"] = "success"
    chart_config["visualization_status"] = "success"
    if "metabase_error" in chart_config:
        chart_config.pop("metabase_error", None)
    if "user_message" in chart_config:
        chart_config.pop("user_message", None)

    report.chart_config = chart_config
    report.ai_trace = build_report_ai_trace(report, embed_url=embed_url)
    report.save(
        update_fields=[
            "metabase_question_id",
            "metabase_dashboard_id",
            "embed_url",
            "chart_type",
            "status",
            "error_message",
            "chart_config",
            "visualization_spec",
            "ai_trace",
            "updated_at",
        ]
    )
    logger.info(
        "Recovered visualization for report=%s question_id=%s dashboard_id=%s",
        report.id,
        question_id,
        dashboard_id,
    )


def _voice_report_safe_queryset():
    # Transitional shared-schema compatibility:
    # some environments have not applied the migration that adds
    # created_by_email/edited_by_email yet.
    return VoiceReport.objects.only(
        "id",
        "workspace_id",
        "created_by_id",
        "edited_by_id",
        "transcription",
        "intent_json",
        "generated_sql",
        "final_sql",
        "status",
        "sql_validated",
        "sql_edited",
        "query_result",
        "row_count",
        "execution_time_ms",
        "chart_type",
        "chart_config",
        "visualization_spec",
        "metabase_question_id",
        "metabase_dashboard_id",
        "embed_url",
        "error_message",
        "preprocessing_low",
        "preprocessing_high",
        "pipeline_trace",
        "ai_trace",
        "created_at",
        "updated_at",
    )


def _service_headers_with_auth(request):
    headers = {"Content-Type": "application/json"}
    auth_header = request.META.get("HTTP_AUTHORIZATION")
    if auth_header:
        headers["Authorization"] = auth_header
    return headers


class DatasetBindingResolutionError(Exception):
    """A safe, structured failure returned by the dataset authority."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 422,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "dataset_binding_invalid")
        self.http_status = int(http_status)
        self.details = dict(details or {})


def _dataset_binding_error_response(exc: DatasetBindingResolutionError) -> Response:
    return Response(
        {
            "success": False,
            "code": exc.code,
            "category": "data_source",
            "error": str(exc),
            "message": str(exc),
            "details": exc.details,
        },
        status=exc.http_status,
    )


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

    query_service_url = os.getenv("QUERY_SERVICE_URL", "http://query-service:8006").rstrip("/")
    params = {
        "workspace_id": str(workspace_id or "").strip(),
    }
    if dataset_id:
        params["dataset_id"] = dataset_id
    if table_name:
        params["table_name"] = table_name

    try:
        response = requests.get(
            f"{query_service_url}/database/",
            headers=_service_headers_with_auth(request),
            params=params,
            timeout=10,
        )
    except requests.Timeout as exc:
        raise DatasetBindingResolutionError(
            "dataset_authority_timeout",
            "Dataset validation timed out. Please try again.",
            http_status=503,
        ) from exc
    except requests.RequestException as exc:
        raise DatasetBindingResolutionError(
            "dataset_authority_unavailable",
            "Dataset validation is temporarily unavailable. Please try again.",
            http_status=503,
        ) from exc

    try:
        raw_payload = response.json()
    except ValueError as exc:
        raise DatasetBindingResolutionError(
            "dataset_authority_invalid_response",
            "Dataset validation returned an invalid response.",
            http_status=502,
        ) from exc

    payload = raw_payload if isinstance(raw_payload, dict) else {}
    if response.status_code != status.HTTP_200_OK or not payload.get("success"):
        error_status = int(response.status_code)
        if error_status < 400 or error_status >= 600:
            error_status = 502
        raise DatasetBindingResolutionError(
            str(payload.get("code") or "dataset_binding_invalid"),
            str(payload.get("message") or payload.get("error") or "Dataset binding is invalid."),
            http_status=error_status,
            details=payload.get("details") if isinstance(payload.get("details"), dict) else {},
        )

    data = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
    resolved_dataset_id = str(data.get("id") or "").strip()
    resolved_table_name = str(explicit_table_name or "").strip()
    resolved_workspace_id = str(data.get("workspace_id") or "").strip()
    if (
        not resolved_dataset_id
        or not resolved_table_name
        or resolved_workspace_id != str(workspace_id or "").strip()
    ):
        raise DatasetBindingResolutionError(
            "dataset_authority_invalid_response",
            "Dataset validation returned incomplete or mismatched metadata.",
            http_status=502,
        )

    return {
        "workspace_id": str(workspace_id or "").strip(),
        "manager_id": str(data.get("manager") or manager_id or "").strip(),
        "dataset_id": resolved_dataset_id,
        "source_id": source_id or resolved_dataset_id,
        "table_name": resolved_table_name,
    }


def build_default_preprocessing_low(original_text: str = "") -> dict:
    normalized_text = str(original_text or "")
    return {
        "original_sentence": normalized_text,
        "original_text": normalized_text,
        "cleaned_sentence": normalized_text,
        "cleaned_text": normalized_text,
        "changes": [],
        "preserved_terms": [],
        "semantic_terms": [],
        "semantic_preservation": {},
        "filter_operators": [],
        "rejected_changes": [],
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


def _redact_private_trace_paths(value):
    """Keep AI diagnostics without exposing transient server file locations."""
    if isinstance(value, dict):
        return {
            key: (
                '[redacted]'
                if str(key).lower().endswith(('_path', 'path'))
                else _redact_private_trace_paths(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_private_trace_paths(item) for item in value]
    if isinstance(value, str) and any(
        marker in value for marker in ('/app/private_uploads/', '/tmp/', 'biavora-audio-')
    ):
        return '[redacted]'
    return value


def normalize_pipeline_trace(payload) -> dict:
    fallback = build_default_pipeline_trace()
    if not isinstance(payload, dict):
        return fallback
    normalized = _redact_private_trace_paths(payload)
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
        "original_sentence": str(payload.get("original_sentence") or original_text),
        "original_text": original_text,
        "cleaned_sentence": str(payload.get("cleaned_sentence") or cleaned_text),
        "cleaned_text": cleaned_text,
        "changes": normalized_changes,
        "preserved_terms": _dedupe_non_empty(payload.get("preserved_terms", [])),
        "semantic_terms": payload.get("semantic_terms", []) if isinstance(payload.get("semantic_terms"), list) else [],
        "semantic_preservation": payload.get("semantic_preservation", {}) if isinstance(payload.get("semantic_preservation"), dict) else {},
        "filter_operators": payload.get("filter_operators", []) if isinstance(payload.get("filter_operators"), list) else [],
        "rejected_changes": payload.get("rejected_changes", []) if isinstance(payload.get("rejected_changes"), list) else [],
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
            try:
                extension = validate_upload(audio_file, 'audio')
            except UploadRejected as exc:
                return Response({'success': False, 'error': str(exc)}, status=400)
            identity = extract_identity_context(request)
            workspace_id = get_user_workspace_id(request)
            actor_user_id = str(identity.user_id or getattr(request.user, "id", "") or "").strip()
            actor_user_email = str(identity.email or getattr(request.user, "email", "") or "").strip()

            if not actor_user_id:
                return Response(
                    {'success': False, 'error': 'Invalid user context'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            if not workspace_id:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                binding_context = _resolve_dataset_binding_context(
                    request=request,
                    workspace_id=workspace_id,
                    manager_id=actor_user_id,
                    explicit_dataset_id=str(request.data.get("dataset_id") or "").strip(),
                    explicit_source_id=str(request.data.get("source_id") or "").strip(),
                    explicit_table_name=str(request.data.get("table_name") or "").strip(),
                )
            except DatasetBindingResolutionError as exc:
                return _dataset_binding_error_response(exc)

            # Enforce subscription/free-tier limits before processing any voice request.
            subscription_client = get_subscription_client()
            access_result = subscription_client.check_access(
                workspace_id=workspace_id,
                authorization_header=request.META.get('HTTP_AUTHORIZATION'),
                consume=True,
            )

            if not access_result.get('success'):
                logger.error(
                    "Subscription access check failed workspace=%s user=%s error=%s",
                    workspace_id,
                    actor_user_id,
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
            audio_dir = os.path.join(settings.PRIVATE_UPLOAD_ROOT, str(int(workspace_id)))
            os.makedirs(audio_dir, mode=0o700, exist_ok=True)
            
            # Generate unique filename
            filename = f"{uuid.uuid4().hex}{extension}"
            audio_path = os.path.join(audio_dir, filename)
            
            fd = os.open(audio_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, 'wb') as destination:
                    total = 0
                    for chunk in audio_file.chunks():
                        total += len(chunk)
                        if total > AUDIO_MAX_BYTES:
                            raise UploadRejected('Audio upload exceeds size limit.')
                        destination.write(chunk)
            except Exception as exc:
                os.unlink(audio_path)
                if isinstance(exc, UploadRejected):
                    return Response({'success': False, 'error': str(exc)}, status=400)
                raise
            
            logger.info(f"Audio file saved: {audio_path}")
            
            # Call Small Whisper (STATELESS - no user context needed)
            whisper_client = get_small_whisper_client()
            try:
                whisper_result = whisper_client.process_audio(
                    audio_file=audio_path,
                    user_id=actor_user_id,
                    workspace_id=binding_context.get("workspace_id"),
                    manager_id=binding_context.get("manager_id"),
                    dataset_id=binding_context.get("dataset_id"),
                    source_id=binding_context.get("source_id"),
                    table_name=binding_context.get("table_name"),
                )
            finally:
                os.unlink(audio_path)

            whisper_result = _redact_private_trace_paths(whisper_result)
            
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
                workspace_id=workspace_id,
                dataset_id=int(binding_context["dataset_id"]),
                created_by_id=actor_user_id,
                created_by_email=actor_user_email,
                audio_file='',
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
                'workspace_id': workspace_id,
                'user_id': actor_user_id,
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
                    workspace_id,
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
                    workspace_id,
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
            logger.error("Voice upload failed error_type=%s", type(e).__name__)
            return Response(
                {'success': False, 'error': 'Voice processing failed.'},
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

            identity = extract_identity_context(request)
            workspace_id = get_user_workspace_id(request)
            actor_user_id = str(identity.user_id or getattr(request.user, "id", "") or "").strip()
            actor_user_email = str(identity.email or getattr(request.user, "email", "") or "").strip()

            if not actor_user_id:
                return Response(
                    {'success': False, 'error': 'Invalid user context'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            if not workspace_id:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            requested_workspace_id = request.data.get('workspace_id')
            if (
                requested_workspace_id is not None
                and str(requested_workspace_id).strip()
                and str(requested_workspace_id) != workspace_id
            ):
                return Response(
                    {'success': False, 'error': 'workspace_id does not match current user workspace'},
                    status=status.HTTP_403_FORBIDDEN
                )

            try:
                binding_context = _resolve_dataset_binding_context(
                    request=request,
                    workspace_id=workspace_id,
                    manager_id=actor_user_id,
                    explicit_dataset_id=str(request.data.get("dataset_id") or "").strip(),
                    explicit_source_id=str(request.data.get("source_id") or "").strip(),
                    explicit_table_name=str(request.data.get("table_name") or "").strip(),
                )
            except DatasetBindingResolutionError as exc:
                return _dataset_binding_error_response(exc)

            # Keep subscription consumption behavior aligned with voice uploads.
            subscription_client = get_subscription_client()
            access_result = subscription_client.check_access(
                workspace_id=workspace_id,
                authorization_header=request.META.get('HTTP_AUTHORIZATION'),
                consume=True,
            )

            if not access_result.get('success'):
                logger.error(
                    "Subscription access check failed workspace=%s user=%s error=%s",
                    workspace_id,
                    actor_user_id,
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
            text_result = whisper_client.process_text(
                text=text,
                user_id=actor_user_id,
                workspace_id=binding_context.get("workspace_id"),
                manager_id=binding_context.get("manager_id"),
                dataset_id=binding_context.get("dataset_id"),
                source_id=binding_context.get("source_id"),
                table_name=binding_context.get("table_name"),
            )
            text_result = _redact_private_trace_paths(text_result)

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
                workspace_id=workspace_id,
                dataset_id=int(binding_context["dataset_id"]),
                created_by_id=actor_user_id,
                created_by_email=actor_user_email,
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
                'workspace_id': workspace_id,
                'user_id': actor_user_id,
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
                    workspace_id,
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
                    workspace_id,
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
            
            # Resolve scope and actor context.
            identity = extract_identity_context(request)
            workspace_id = get_user_workspace_id(request)
            actor_user_id = str(identity.user_id or getattr(request.user, "id", "") or "").strip()
            actor_role = str(identity.role or getattr(request.user, "role", "") or "").strip().lower()
            actor_name = str(getattr(request.user, "name", "") or identity.email or actor_user_id or "unknown").strip()

            if not workspace_id:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace_id=workspace_id
            )
            
            # Validate report has SQL to execute
            if not report.final_sql or not report.final_sql.strip():
                logger.warning(f"Report {report_id} has no SQL to execute")
                return Response(
                    {'success': False, 'error': 'This report does not contain a SQL query. It may be a conversational question.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate permissions
            if actor_role not in ['manager', 'analyst']:
                return Response(
                    {'success': False, 'error': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Get SQL (final_sql may be edited by analyst)
            sql_to_execute = report.final_sql
            
            # Query is the sole authorization and SQL enforcement boundary.
            clean_sql = sql_to_execute.strip()
            report.status = VoiceReport.STATUS_PROCESSING
            report.error_message = ''
            report.save()
            
            query_result = self._execute_query_with_query_service(
                request,
                clean_sql,
                dataset_id=report.dataset_id,
            )

            if not query_result.get('success'):
                query_error = (
                    query_result.get('error')
                    or query_result.get('error_message')
                    or 'Query execution failed'
                )
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = str(query_error)
                report.ai_trace = build_report_ai_trace(report)
                report.save()

                logger.error(
                    "Query execution failed for report %s: %s",
                    report.id,
                    query_error
                )

                return Response(
                    {
                        'success': False,
                        'error': 'Query execution failed',
                        'details': str(query_error),
                        'error_code': query_result.get('error_code') or 'INTERNAL_ERROR',
                        'retryable': bool(query_result.get('retryable')),
                    },
                    status=int(query_result.get('http_status') or status.HTTP_502_BAD_GATEWAY),
                )

            report.sql_validated = True
            report.final_sql = str(query_result.get('sql') or clean_sql)
            
            base_columns = query_result.get('columns', [])
            base_column_names = (
                query_result.get('column_names')
                if isinstance(query_result.get('column_names'), list)
                else []
            )
            if not base_column_names:
                base_column_names = [
                    str(column.get("name") or "").strip() if isinstance(column, dict) else str(column or "").strip()
                    for column in base_columns
                    if (str(column.get("name") or "").strip() if isinstance(column, dict) else str(column or "").strip())
                ]
            base_column_types = (
                query_result.get('column_types')
                if isinstance(query_result.get('column_types'), list)
                else []
            )
            base_rows = sanitize_query_results(query_result.get('rows', []))
            visualization_sql = clean_sql
            visualization_columns = base_columns
            visualization_column_names = base_column_names
            visualization_column_types = base_column_types
            visualization_result_shape = (
                query_result.get("result_shape")
                if isinstance(query_result.get("result_shape"), dict)
                else None
            )
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
                        columns=base_column_names,
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
                    visualization_column_names = base_column_names
                    visualization_column_types = base_column_types
                    visualization_result_shape = (
                        query_result.get("result_shape")
                        if isinstance(query_result.get("result_shape"), dict)
                        else None
                    )
                    visualization_rows = base_rows

                if forecast_payload is not None:
                    forecast_meta = forecast_payload.get("meta", {}) if isinstance(forecast_payload.get("meta"), dict) else {}
                    forecast_available = bool(forecast_meta.get("forecast_available", False))
                    visualization_sql = forecast_payload["sql"]
                    visualization_columns = forecast_payload["columns"]
                    visualization_column_names = [
                        str(column.get("name") or "").strip() if isinstance(column, dict) else str(column or "").strip()
                        for column in visualization_columns
                        if (str(column.get("name") or "").strip() if isinstance(column, dict) else str(column or "").strip())
                    ]
                    visualization_column_types = []
                    visualization_result_shape = None
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
                'column_names': visualization_column_names,
                'column_types': visualization_column_types,
                'result_shape': visualization_result_shape,
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

            # 🔒 NaN-SAFE: Catch JSON serialization errors during save
            try:
                report.save()
            except (ValueError, TypeError) as json_error:
                logger.error(f"JSON serialization error when saving report {report.id}: {json_error}")
                visualization_rows = sanitize_query_results(visualization_rows)
                report.query_result = {
                    'columns': visualization_columns,
                    'column_names': visualization_column_names,
                    'column_types': visualization_column_types,
                    'result_shape': visualization_result_shape,
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
                    'user_id': actor_user_id,
                    'row_count': len(visualization_rows),
                    'source_row_count': query_result.get('row_count', 0),
                    'execution_time_ms': query_result.get('execution_time_ms', 0),
                },
                key=str(report.id),
            )
            
            # Chart selection is delegated exclusively to visualization-service/chart_type_selector.
            chart_type = ""
            chart_contract_hint = ""
            if isinstance(chart_config.get("chart_contract"), dict):
                contract_payload = chart_config.get("chart_contract") or {}
                chart_contract_hint = str(
                    contract_payload.get("chart_type")
                    or contract_payload.get("selected_chart_type")
                    or contract_payload.get("final_chart_type")
                    or contract_payload.get("type")
                    or ""
                ).strip()
            if not chart_contract_hint:
                chart_contract_hint = str(chart_config.get("requested_chart_type") or "").strip()
            # Keep the last known-good chart metadata until the replacement
            # visualization is fully created. A transient Metabase failure
            # must not erase a working report's display contract.
            chart_config["requested_chart_type"] = chart_type
            chart_config["chart_hint_from_ai"] = normalize_chart_type(chart_contract_hint, default="") if chart_contract_hint else ""
            chart_config["reason_chart_selected"] = "deferred_to_visualization_service_chart_type_selector"
            report.chart_config = chart_config
            chart_settings = self._build_visualization_settings(report, "")
            axes_dimensions = chart_settings.get("graph.dimensions", [])
            axes_metrics = chart_settings.get("graph.metrics", [])
            chart_config["x_axis"] = axes_dimensions[0] if axes_dimensions else ""
            chart_config["y_axis"] = axes_metrics[0] if axes_metrics else ""
            
            # Create visualization through Visualization Service.
            visualization_result = self._create_visualization_with_service(
                request=request,
                report=report,
                sql=visualization_sql,
                chart_type="",
                visualization_settings=chart_settings,
            )
            if not visualization_result.get('success'):
                return self._metabase_failure_response(
                    report=report,
                    chart_type=chart_type or ChartType.TABLE,
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
            final_chart_type = normalize_chart_type(
                str(visualization_result.get("chart_type") or visualization_result.get("display") or "").strip(),
                default=chart_type or ChartType.TABLE,
            )
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
            
            report.chart_type = final_chart_type
            report.status = VoiceReport.STATUS_VISUALIZATION_CREATED
            report.error_message = ''
            report.embed_url = embed_url
            chart_config["requested_chart_type"] = chart_type
            chart_config["selected_chart_type"] = final_chart_type
            chart_config["chart_type"] = final_chart_type
            chart_config["chart_hint_from_ai"] = visualization_result.get("chart_hint_from_ai") or chart_config.get("chart_hint_from_ai", "")
            chart_config["chart_type_selected_by_visualization_service"] = visualization_result.get("chart_type_selected_by_visualization_service") or final_chart_type
            chart_config["reason_chart_selected"] = "visualization_service_ollama_selector"
            chart_config["metabase"] = {
                "question_id": question_id,
                "dashboard_id": dashboard_id,
                "display": visualization_result.get("metabase_display") or visualization_result.get("display") or final_chart_type,
                "card_display": visualization_result.get("metabase_card_display"),
                "fallback_applied": bool(visualization_result.get("fallback_applied")),
                "fallback_reason": visualization_result.get("fallback_reason", ""),
            }
            chart_config["metabase_status"] = "available"
            chart_config["render_status"] = "rendered"
            chart_config["visualization_status"] = "ready"
            chart_config.pop("metabase_error", None)
            chart_config.pop("user_message", None)
            chart_config["chart_selection_reason"] = str(visualization_result.get("chart_selection_reason") or "")
            chart_config["result_shape"] = visualization_result.get("result_shape") if isinstance(visualization_result.get("result_shape"), dict) else {}
            visualization_spec = (
                visualization_result.get("visualization_spec")
                if isinstance(visualization_result.get("visualization_spec"), dict)
                else {}
            )
            if visualization_spec:
                chart_config["visualization_spec"] = visualization_spec
                report.visualization_spec = visualization_spec
            chart_config["metabase_visualization_settings"] = (
                visualization_result.get("metabase_visualization_settings")
                if isinstance(visualization_result.get("metabase_visualization_settings"), dict)
                else {}
            )
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
                    'user_id': actor_user_id,
                    'metabase_question_id': question_id,
                    'metabase_dashboard_id': dashboard_id,
                },
                key=str(report.id),
            )

            notification_client = get_notification_client()
            notification_result = notification_client.send_event(
                event_type='workspace_report_created',
                event_key=f"report-created:{report.id}",
                payload={
                    'workspace_id': report.workspace_id,
                    'workspace_name': None,
                    'owner_email': None,
                    'owner_name': None,
                    'recipient_emails': [],
                    'report_id': report.id,
                    'created_by_user_id': actor_user_id,
                    'created_by_name': actor_name,
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
                'chart_type': report.chart_type,
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
        if self._is_transient_visualization_outage(
            failure_reason=failure_reason,
            details=details,
            http_status=http_status,
        ):
            logger.warning(
                "Metabase visualization degraded for report %s: reason=%s details=%s",
                report.id,
                failure_reason,
                details,
            )
            chart_config = dict(report.chart_config) if isinstance(report.chart_config, dict) else {}
            metabase_config = dict(chart_config.get("metabase")) if isinstance(chart_config.get("metabase"), dict) else {}
            metabase_config.update(
                {
                    "question_id": report.metabase_question_id,
                    "dashboard_id": report.metabase_dashboard_id,
                    "display": chart_type,
                    "fallback_applied": True,
                    "fallback_reason": str(failure_reason or "metabase_unavailable"),
                }
            )
            chart_config["metabase"] = metabase_config
            chart_config["metabase_status"] = "unavailable"
            chart_config["render_status"] = "degraded"
            chart_config["visualization_status"] = "degraded"
            chart_config["user_message"] = "Chart configuration is ready but Metabase is temporarily unavailable."
            if details:
                chart_config["metabase_error"] = str(details)

            report.status = VoiceReport.STATUS_EXECUTED
            report.error_message = ""
            # A transient visualization outage must not erase a previously
            # working Metabase card/dashboard. Keeping those identifiers lets
            # existing reports continue rendering while a new visualization
            # is retried later.
            report.chart_config = chart_config
            report.ai_trace = build_report_ai_trace(report)
            report.save()

            ai_contract = chart_config.get("ai_contract") if isinstance(chart_config.get("ai_contract"), dict) else {}
            response_payload = {
                "success": True,
                "degraded": True,
                "degraded_reason": "metabase_unavailable",
                "metabase_status": "unavailable",
                "message": "Query executed successfully, but Metabase is unavailable right now.",
                "report_id": report.id,
                "row_count": row_count,
                "execution_time_ms": execution_time_ms,
                "chart_type": chart_type,
                "status": report.status,
                "embed_url": str(report.embed_url or ""),
                "metabase_question_id": report.metabase_question_id,
            }
            if ai_contract:
                response_payload["confidence"] = ai_contract.get("confidence")
                response_payload["confidence_breakdown"] = ai_contract.get("confidence_breakdown")
            return Response(response_payload, status=status.HTTP_200_OK)

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

    def _is_transient_visualization_outage(self, *, failure_reason, details, http_status):
        normalized_reason = str(failure_reason or "").strip().lower()
        normalized_details = str(details or "").strip().lower()
        try:
            normalized_status = int(http_status or 0)
        except (TypeError, ValueError):
            normalized_status = 0

        outage_markers = (
            "metabase_unavailable",
            "visualization_service_unavailable",
            "service unavailable",
            "connection aborted",
            "remote end closed",
            "bad gateway",
            "timed out",
            "timeout",
        )
        if any(marker in normalized_reason for marker in outage_markers):
            return True
        if any(marker in normalized_details for marker in outage_markers):
            return True
        return normalized_status in {502, 503, 504} and normalized_reason in {
            "question_creation_failed",
            "embed_generation_failed",
            "visualization_service_failed",
        }
    
    def _infer_chart_type(self, columns, rows, intent, preferred_chart_type: str = ""):
        """Chart type decisions are centralized in visualization-service."""
        _ = columns, rows, intent
        token = str(preferred_chart_type or "").strip()
        if not token:
            return ""
        return normalize_chart_type(token, default="")
    
    def _service_headers(self, request):
        headers = {'Content-Type': 'application/json'}
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if auth_header:
            headers['Authorization'] = auth_header
        request_id = str(
            getattr(request, 'request_id', '')
            or request.META.get('HTTP_X_REQUEST_ID', '')
            or ''
        ).strip()
        if request_id:
            headers['X-Request-ID'] = request_id
        return headers

    def _response_error_message(self, response, default):
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload.get('error') or payload.get('message') or default
        except Exception:
            pass
        return (response.text or default)[:500]

    def _execute_query_with_query_service(self, request, clean_sql, *, dataset_id=None):
        query_service_url = os.getenv('QUERY_SERVICE_URL', 'http://query-service:8006').rstrip('/')
        if dataset_id in (None, '', b''):
            return {
                'success': False,
                'error': 'Report is missing its authorized logical dataset binding.',
                'error_code': 'FORBIDDEN_DATASET',
                'retryable': False,
                'http_status': status.HTTP_409_CONFLICT,
            }
        payload = {
            'sql': clean_sql,
            'workspace_id': get_user_workspace_id(request),
            'dataset_id': dataset_id,
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
                if not isinstance(result, dict):
                    return {
                        'success': False,
                        'error': 'query_service_invalid_response',
                    }
                # QueryResponse requires ``success``. During rolling upgrades,
                # accept the older status-only response so existing reports do
                # not fail while query-service and voice-service versions differ.
                if 'success' not in result:
                    result['success'] = str(result.get('status') or '').lower() in {
                        'success',
                        'completed',
                    }
                if result.get('success'):
                    return result
                return {
                    'success': False,
                    'error': (
                        result.get('error')
                        or result.get('error_message')
                        or 'query_service_execution_failed'
                    ),
                    'error_code': result.get('error_code') or 'INTERNAL_ERROR',
                    'retryable': bool(result.get('retryable')),
                    'http_status': response.status_code,
                }

            try:
                error_payload = response.json()
            except ValueError:
                error_payload = {}
            return {
                'success': False,
                'error': self._response_error_message(response, 'query_service_execution_failed'),
                'error_code': (
                    error_payload.get('error_code')
                    if isinstance(error_payload, dict)
                    else None
                ) or 'INTERNAL_ERROR',
                'retryable': bool(
                    error_payload.get('retryable')
                    if isinstance(error_payload, dict)
                    else response.status_code >= 500
                ),
                'http_status': response.status_code,
            }
        except requests.RequestException as exc:
            logger.warning(
                "Query service unavailable; analytical execution failed closed: %s",
                type(exc).__name__,
            )
            return {
                'success': False,
                'error': 'query_service_unavailable',
                'error_code': 'CLICKHOUSE_UNAVAILABLE',
                'retryable': True,
                'http_status': status.HTTP_503_SERVICE_UNAVAILABLE,
            }
        except Exception as exc:
            logger.warning(
                "Query service returned an invalid execution response: %s",
                type(exc).__name__,
            )
            return {
                'success': False,
                'error': 'query_service_invalid_response',
                'error_code': 'INTERNAL_ERROR',
                'retryable': True,
                'http_status': status.HTTP_502_BAD_GATEWAY,
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
        raw_chart_type = str(chart_type or "").strip()
        normalized_chart_type = normalize_chart_type(raw_chart_type, default="") if raw_chart_type else ""
        chart_config = report.chart_config if isinstance(report.chart_config, dict) else {}
        chart_contract = chart_config.get("chart_contract") if isinstance(chart_config.get("chart_contract"), dict) else {}
        chart_hint_from_ai_raw = (
            chart_config.get("requested_chart_type")
            or chart_contract.get("chart_type")
            or chart_contract.get("selected_chart_type")
            or chart_contract.get("final_chart_type")
            or chart_contract.get("type")
            or ""
        )
        chart_hint_from_ai = normalize_chart_type(str(chart_hint_from_ai_raw).strip(), default="") if str(chart_hint_from_ai_raw).strip() else ""
        forecasting_config = chart_config.get("forecasting", {}) if isinstance(chart_config.get("forecasting"), dict) else {}
        forecast_meta = forecasting_config.get("meta", {}) if isinstance(forecasting_config.get("meta"), dict) else {}

        settings = {
            'numeric_columns': numeric_columns,
            'time_columns': time_columns,
            'category_columns': categorical_columns,
            'row_count': len(rows_payload),
            'dataset_columns': column_specs,
            'result_rows': [row for row in rows_payload[:100] if isinstance(row, dict)],
            'intent': intent_payload,
            'query_columns': column_names,
            'reason_chart_selected': chart_config.get('reason_chart_selected', ''),
        }
        if isinstance(query_result.get("result_shape"), dict):
            settings["result_shape"] = query_result["result_shape"]
        if chart_hint_from_ai:
            settings["chart_hint_from_ai"] = chart_hint_from_ai
        if normalized_chart_type:
            settings['display'] = normalized_chart_type
            settings['chart_type'] = normalized_chart_type
        if isinstance(chart_config.get("chart_contract"), dict):
            x_axis = str(chart_contract.get("x_axis") or chart_config.get("x_axis") or "").strip()
            raw_y_axis = chart_contract.get("y_axis") or chart_config.get("y_axis")
            y_axis = []
            if isinstance(raw_y_axis, list):
                y_axis = [str(item).strip() for item in raw_y_axis if str(item).strip()]
            elif str(raw_y_axis or "").strip():
                y_axis = [str(raw_y_axis).strip()]
            if x_axis:
                settings["graph.dimensions"] = [x_axis]
            if y_axis:
                settings["graph.metrics"] = y_axis
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
        sanitized_sql = sanitize_sql_for_metabase(sql)
        logger.info("Metabase SQL pipeline authorized report_id=%s sql_len=%s", report.id, len(sanitized_sql))
        ai_trace_payload = report.ai_trace if isinstance(report.ai_trace, dict) else {}
        if not ai_trace_payload:
            ai_trace_payload = build_report_ai_trace(report)
        query_result = report.query_result if isinstance(report.query_result, dict) else {}
        dataset_id = report.dataset_id or query_result.get('dataset_id')
        try:
            definition_response = requests.post(
                f"{os.getenv('QUERY_SERVICE_URL', 'http://query-service:8006').rstrip('/')}/query/definitions/",
                json={
                    'sql': sanitized_sql,
                    'workspace_id': report.workspace_id,
                    'dataset_id': dataset_id,
                },
                headers=headers,
                timeout=(3, 15),
            )
        except requests.RequestException as exc:
            return {
                'success': False,
                'failure_reason': 'query_authorization_failed',
                'error': f'query_service_unavailable: {type(exc).__name__}',
                'http_status': status.HTTP_503_SERVICE_UNAVAILABLE,
            }
        if definition_response.status_code != status.HTTP_201_CREATED:
            return {
                'success': False,
                'failure_reason': 'query_authorization_failed',
                'error': self._response_error_message(definition_response, 'query_authorization_failed'),
                'http_status': definition_response.status_code,
            }
        query_definition_id = str(definition_response.json().get('query_definition_id') or '')
        if not query_definition_id:
            return {
                'success': False,
                'failure_reason': 'query_authorization_failed',
                'error': 'query_service_missing_definition_id',
                'http_status': status.HTTP_502_BAD_GATEWAY,
            }
        try:
            question_response = requests.post(
                f'{visualization_service_url}/visualization/question/create/',
                json={
                    'name': f"Voice Report #{report.id}: {report.transcription[:50]}",
                    'query_definition_id': query_definition_id,
                    'chart_type': chart_type,
                    'visualization_settings': visualization_settings,
                    'ai_trace': ai_trace_payload,
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
        logger.info(
            "Visualization service question response report_id=%s payload=%s",
            report.id,
            question_payload,
        )
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
            'chart_hint_from_ai': question_payload.get('chart_hint_from_ai') or visualization_settings.get('chart_hint_from_ai') or chart_type,
            'chart_type_selected_by_visualization_service': question_payload.get('chart_type_selected_by_visualization_service') or question_payload.get('chart_type') or question_payload.get('display') or chart_type,
            'chart_type': question_payload.get('chart_type') or question_payload.get('display') or chart_type,
            'display': question_payload.get('display') or visualization_settings.get('display'),
            'metabase_display': question_payload.get('metabase_display') or question_payload.get('display') or visualization_settings.get('display'),
            'metabase_card_display': question_payload.get('metabase_card_display'),
            'fallback_applied': bool(question_payload.get('fallback_applied')),
            'fallback_reason': question_payload.get('fallback_reason', ''),
            'chart_selection_reason': question_payload.get('chart_selection_reason', ''),
            'metabase_visualization_settings': question_payload.get('metabase_visualization_settings', {}),
            'result_shape': question_payload.get('result_shape', {}),
            'visualization_spec': (
                question_payload.get('visualization_spec')
                if isinstance(question_payload.get('visualization_spec'), dict)
                else {}
            ),
            'visualization_settings': visualization_settings,
        }

        dashboard_id = self._get_or_create_dashboard(
            workspace_id=report.workspace_id,
            visualization_service_url=visualization_service_url,
            headers=headers,
        )

        dashboard_id = self._attach_question_to_dashboard(
            workspace_id=report.workspace_id,
            question_id=question_id,
            dashboard_id=dashboard_id,
            visualization_service_url=visualization_service_url,
            headers=headers,
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

    def _get_or_create_dashboard(self, workspace_id, visualization_service_url, headers):
        """Get an existing workspace dashboard ID or create one through visualization service."""
        existing_report = VoiceReport.objects.filter(
            workspace_id=workspace_id,
            metabase_dashboard_id__isnull=False
        ).order_by('-id').first()
        if existing_report:
            return existing_report.metabase_dashboard_id
        return self._create_workspace_dashboard(
            workspace_id=workspace_id,
            visualization_service_url=visualization_service_url,
            headers=headers,
        )

    def _create_workspace_dashboard(self, workspace_id, visualization_service_url, headers):
        """Create a new workspace dashboard through visualization service."""
        try:
            response = requests.post(
                f'{visualization_service_url}/visualization/dashboard/create/',
                json={
                    'name': f'Workspace {workspace_id} - Voice Reports',
                    'description': f'Voice-driven reports for workspace {workspace_id}',
                },
                headers=headers,
                timeout=120,
            )
        except requests.RequestException as exc:
            logger.warning(
                "Failed to create dashboard for workspace=%s due to connectivity error=%s",
                workspace_id,
                exc
            )
            return None
        if response.status_code != status.HTTP_200_OK:
            logger.warning(
                "Failed to create dashboard for workspace=%s error=%s",
                workspace_id,
                self._response_error_message(response, 'dashboard_creation_failed')
            )
            return None

        payload = response.json() if response.content else {}
        dashboard_id = payload.get('dashboard_id') if isinstance(payload, dict) else None
        if not dashboard_id:
            logger.warning("Dashboard create succeeded but no dashboard_id was returned for workspace=%s", workspace_id)
            return None
        return dashboard_id

    def _try_add_question_to_dashboard(self, question_id, dashboard_id, visualization_service_url, headers):
        """Attempt to attach a question to a dashboard and return True on success."""
        try:
            response = requests.post(
                f'{visualization_service_url}/visualization/dashboard/add-question/',
                json={'question_id': question_id, 'dashboard_id': dashboard_id},
                headers=headers,
                timeout=60,
            )
        except requests.RequestException as exc:
            logger.warning(
                "Failed adding question %s to dashboard %s due to connectivity error=%s",
                question_id,
                dashboard_id,
                exc
            )
            return False

        if response.status_code == status.HTTP_200_OK:
            return True

        logger.warning(
            "Failed adding question %s to dashboard %s status=%s error=%s",
            question_id,
            dashboard_id,
            response.status_code,
            self._response_error_message(response, 'add_to_dashboard_failed')
        )
        return False

    def _attach_question_to_dashboard(
        self,
        workspace_id,
        question_id,
        dashboard_id,
        visualization_service_url,
        headers,
    ):
        """
        Attach question to dashboard with one recovery attempt.
        If existing dashboard is stale/invalid, create a new one and retry once.
        """
        if not dashboard_id:
            return None
        if self._try_add_question_to_dashboard(
            question_id=question_id,
            dashboard_id=dashboard_id,
            visualization_service_url=visualization_service_url,
            headers=headers,
        ):
            return dashboard_id

        replacement_dashboard_id = self._create_workspace_dashboard(
            workspace_id=workspace_id,
            visualization_service_url=visualization_service_url,
            headers=headers,
        )
        if not replacement_dashboard_id or replacement_dashboard_id == dashboard_id:
            return dashboard_id

        if self._try_add_question_to_dashboard(
            question_id=question_id,
            dashboard_id=replacement_dashboard_id,
            visualization_service_url=visualization_service_url,
            headers=headers,
        ):
            logger.info(
                "Recovered dashboard attachment by creating a new dashboard old=%s new=%s workspace=%s question=%s",
                dashboard_id,
                replacement_dashboard_id,
                workspace_id,
                question_id,
            )
            return replacement_dashboard_id
        return dashboard_id


class SQLEditView(APIView):
    """
    Edit SQL query (Analyst only).
    """
    permission_classes = [IsAuthenticated, IsAnalyst]
    
    def put(self, request, report_id):
        try:
            identity = extract_identity_context(request)
            workspace_id = get_user_workspace_id(request)
            if not workspace_id:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(_voice_report_safe_queryset(), id=report_id, workspace_id=workspace_id)
            
            new_sql = request.data.get('sql')
            
            if not new_sql:
                return Response(
                    {'success': False, 'error': 'SQL is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate new SQL
            # This is syntax-only feedback; Query re-authorizes the logical
            # dataset and exact table set before any execution.
            guard = SQLGuard()
            
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
            report.edited_by_id = str(identity.user_id or "").strip() or None
            report.sql_validated = True
            report.status = VoiceReport.STATUS_PENDING  # Needs re-execution
            report.ai_trace = build_report_ai_trace(report)
            report.save(
                update_fields=[
                    "final_sql",
                    "sql_edited",
                    "edited_by_id",
                    "sql_validated",
                    "status",
                    "ai_trace",
                    "updated_at",
                ]
            )
            
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
            
            logger.info(
                "Report %s SQL edited by analyst %s",
                report.id,
                identity.email or identity.user_id or "unknown",
            )
            
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
            identity = extract_identity_context(request)
            workspace_id = get_user_workspace_id(request)
            if not workspace_id:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            reports = VoiceReport.objects.filter(
                workspace_id=workspace_id
            ).order_by('-created_at')
            
            # Filter by role
            if identity.role == 'manager' and identity.user_id:
                # Manager sees only their own reports
                reports = reports.filter(created_by_id=identity.user_id)
            # Analyst and Executive see all workspace reports

            lite_mode = str(request.query_params.get('lite', '') or '').strip().lower() in {
                '1', 'true', 'yes', 'on'
            }
            include_embed_raw = request.query_params.get('include_embed')
            if include_embed_raw is None:
                include_embed = False
            else:
                include_embed = str(include_embed_raw).strip().lower() in {'1', 'true', 'yes', 'on'}

            metabase = get_metabase_service() if include_embed else None
            data = []
            for report in reports:
                report_payload = {
                    'id': report.id,
                    'title': report.title,
                    'transcription': report.transcription,
                    'status': report.status,
                    'created_at': report.created_at,
                    'created_by': report.created_by_email or report.created_by_id,
                    'chart_type': report.chart_type,
                    'row_count': report.row_count,
                    'execution_time_ms': report.execution_time_ms,
                    'can_edit': identity.role == 'analyst'
                }
                if not lite_mode:
                    embed_url = get_report_embed_url(report, metabase_service=metabase) if include_embed else ''
                    ai_contract = extract_report_contract(report)
                    report_payload.update({
                        'sql': report.final_sql,
                        'embed_url': embed_url,
                        'metabase_question_id': report.metabase_question_id,
                        'confidence': ai_contract.get('confidence'),
                        'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                        'degraded': ai_contract.get('degraded'),
                    })
                data.append(report_payload)
            logger.info(
                "Report list loaded for user=%s workspace=%s count=%s",
                identity.user_id,
                workspace_id,
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
            workspace_id = get_user_workspace_id(request)
            if not workspace_id:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(_voice_report_safe_queryset(), id=report_id, workspace_id=workspace_id)
            _recover_visualization_for_report(request, report)
            
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
            try:
                visualization_spec = _load_or_derive_visualization_spec(report).model_dump(mode="json")
            except Exception as spec_error:
                logger.warning(
                    "Could not derive visualization spec for report=%s error=%s",
                    report.id,
                    spec_error,
                )
                visualization_spec = (
                    report.visualization_spec
                    if isinstance(report.visualization_spec, dict)
                    else {}
                )
            if report.ai_trace != ai_trace:
                report.ai_trace = ai_trace
                report.save(update_fields=['ai_trace', 'updated_at'])
            
            return Response({
                'success': True,
                'report': {
                    'id': report.id,
                    'title': report.title,
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
                    'chart_config': (
                        report.chart_config
                        if isinstance(report.chart_config, dict)
                        else {}
                    ),
                    'visualization_spec': visualization_spec,
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
                    'created_by': report.created_by_id,
                    'edited_by': report.edited_by_id,
                    'history': history_data
                }
            })

        except Http404:
            # A scoped miss includes the cross-tenant case. Preserve the
            # non-disclosing 404 contract instead of converting it to a 500.
            return Response(
                {'success': False, 'error': 'Report not found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.error(f"Error in ReportDetailView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request, report_id):
        """Delete report (Manager only)."""
        identity = extract_identity_context(request)
        if identity.role != 'manager':
            return Response(
                {'success': False, 'error': 'Only managers can delete reports'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            workspace_id = get_user_workspace_id(request)
            if not workspace_id:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                _voice_report_safe_queryset(),
                id=report_id,
                workspace_id=workspace_id,
                created_by_id=identity.user_id,  # Can only delete own reports
            )
            
            report.delete()
            
            logger.info("Report %s deleted by %s", report_id, identity.email or identity.user_id or "unknown")
            
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


class ReportChartTypeCapabilitiesView(APIView):
    """
    Return all chart types with support diagnostics for a report result shape.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, report_id):
        try:
            identity = extract_identity_context(request)
            role = _actor_role(request, identity)
            if role not in MANUAL_CHART_SWITCH_ROLES:
                return Response(
                    {'success': False, 'error': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )

            workspace_id = get_user_workspace_id(request)
            if not workspace_id:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            report = get_object_or_404(_voice_report_safe_queryset(), id=report_id, workspace_id=workspace_id)
            query_result = report.query_result if isinstance(report.query_result, dict) else {}
            columns_payload = query_result.get("columns", []) if isinstance(query_result.get("columns"), list) else []
            rows_payload = query_result.get("rows", []) if isinstance(query_result.get("rows"), list) else []
            shape = profile_chart_shape(columns_payload, rows_payload)
            selected_chart_type = _resolve_report_chart_type(report)

            capabilities = [
                _chart_capability_item(spec, shape=shape, selected_chart_type=selected_chart_type)
                for spec in CHART_TYPE_CATALOG
            ]
            supported_count = len([item for item in capabilities if item.get("supported")])

            return Response(
                {
                    "success": True,
                    "report_id": report.id,
                    "selected_chart_type": selected_chart_type,
                    "shape": {
                        "row_count": int(shape.get("row_count", 0) or 0),
                        "column_count": len(shape.get("columns", []) or []),
                        "numeric_count": len(shape.get("numeric_columns", []) or []),
                        "time_like_count": len(shape.get("time_like_columns", []) or []),
                        "category_count": len(shape.get("category_columns", []) or []),
                        "geo_count": len(shape.get("geo_columns", []) or []),
                    },
                    "supported_count": supported_count,
                    "total_count": len(capabilities),
                    "chart_types": capabilities,
                }
            )
        except Http404:
            return Response(
                {'success': False, 'error': 'Report not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as exc:
            logger.error("Error loading chart capabilities report=%s: %s", report_id, exc, exc_info=True)
            return Response(
                {'success': False, 'error': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ReportChartTypeSwitchView(APIView):
    """
    Switch a report visualization to another supported chart type without re-executing SQL.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, report_id):
        try:
            identity = extract_identity_context(request)
            role = _actor_role(request, identity)
            if role not in MANUAL_CHART_SWITCH_ROLES:
                return Response(
                    {'success': False, 'error': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )

            workspace_id = get_user_workspace_id(request)
            if not workspace_id:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            report = get_object_or_404(_voice_report_safe_queryset(), id=report_id, workspace_id=workspace_id)
            requested_raw = request.data.get("chart_type")
            requested_chart_type = _normalize_requested_chart_type(requested_raw)
            if not requested_chart_type:
                return Response(
                    {
                        "success": False,
                        "error": "Invalid chart_type",
                        "details": "Use one of the canonical chart types supported by this API.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not report.metabase_question_id:
                return Response(
                    {
                        "success": False,
                        "error": "visualization_not_ready",
                        "details": "This report does not have a Metabase question yet. Execute the report first.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            if not str(report.final_sql or "").strip():
                return Response(
                    {
                        "success": False,
                        "error": "missing_sql",
                        "details": "This report does not contain SQL required to update visualization.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            query_metadata = _report_query_metadata(report)
            columns_payload = query_metadata["columns"]
            shape = query_metadata["result_shape"]
            if not is_chart_shape_supported(requested_chart_type, shape):
                reason_code, reason = _chart_shape_support_failure(requested_chart_type, shape)
                return Response(
                    {
                        "success": False,
                        "error": "chart_type_incompatible",
                        "error_code": "chart_type_incompatible",
                        "message": reason,
                        "chart_type": requested_chart_type,
                        "requested_chart_type": requested_chart_type,
                        "unsupported_reason_code": reason_code,
                        "unsupported_reason": reason,
                        "compatible_chart_types": [
                            spec["type"]
                            for spec in CHART_TYPE_CATALOG
                            if is_chart_shape_supported(spec["type"], shape)
                        ],
                    },
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )

            previous_chart_type = _resolve_report_chart_type(report)
            if previous_chart_type == requested_chart_type:
                try:
                    current_spec = _load_or_derive_visualization_spec(report, chart_type=requested_chart_type)
                    current_spec_payload = current_spec.model_dump(mode="json")
                except Exception:
                    current_spec_payload = report.visualization_spec if isinstance(report.visualization_spec, dict) else {}
                return Response(
                    {
                        "success": True,
                        "report_id": report.id,
                        "chart_type": requested_chart_type,
                        "previous_chart_type": previous_chart_type,
                        "message": "Chart type is already applied.",
                        "embed_url": str(report.embed_url or ""),
                        "visualization_spec": current_spec_payload,
                    }
                )

            try:
                current_spec = _load_or_derive_visualization_spec(report, chart_type=previous_chart_type)
                new_spec = transform_visualization_spec(
                    current_spec,
                    requested_chart_type,
                    result_shape=shape,
                    columns=columns_payload,
                )
            except VisualizationSpecError as exc:
                payload = exc.to_dict()
                payload.update(
                    {
                        "success": False,
                        "error": payload.get("error_code") or "chart_type_incompatible",
                        "chart_type": previous_chart_type,
                    }
                )
                return Response(payload, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

            visualization_settings = dict(new_spec.metabase_config.visualization_settings)

            metabase = get_metabase_service()
            if not metabase.authenticate():
                return Response(
                    {
                        "success": False,
                        "error": "metabase_authentication_failed",
                        "details": metabase.last_error or "metabase_unavailable",
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            updated = metabase.update_question(
                card_id=int(report.metabase_question_id),
                name=f"Voice Report #{report.id}: {str(report.transcription or '')[:50]}",
                sql=report.final_sql,
                visualization_settings=visualization_settings,
            )
            if not updated:
                return Response(
                    {
                        "success": False,
                        "error": "metabase_update_failed",
                        "details": metabase.last_error or "update_question_failed",
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            chart_config = dict(report.chart_config) if isinstance(report.chart_config, dict) else {}
            chart_config["requested_chart_type"] = requested_chart_type
            chart_config["selected_chart_type"] = requested_chart_type
            chart_config["chart_type"] = requested_chart_type
            chart_config["chart_type_selected_by_visualization_service"] = requested_chart_type
            chart_config["reason_chart_selected"] = "manual_user_switch"
            chart_config["chart_selection_reason"] = "manual_user_switch"
            chart_config["result_shape"] = shape
            chart_config["chart_contract"] = new_spec.chart_contract.model_dump(mode="json")
            chart_config["field_assignments"] = dict(new_spec.field_assignments)
            chart_config["visualization_spec"] = new_spec.model_dump(mode="json")
            chart_config["metabase_visualization_settings"] = (
                metabase.last_visualization_settings
                if isinstance(getattr(metabase, "last_visualization_settings", None), dict)
                else visualization_settings
            )
            chart_config["metabase_status"] = "up"
            chart_config["render_status"] = "success"
            chart_config["visualization_status"] = "success"

            metabase_config = dict(chart_config.get("metabase")) if isinstance(chart_config.get("metabase"), dict) else {}
            metabase_config["question_id"] = int(report.metabase_question_id)
            metabase_config["dashboard_id"] = report.metabase_dashboard_id
            metabase_config["display"] = new_spec.metabase_config.display
            metabase_config["card_display"] = getattr(metabase, "last_metabase_display", None) or new_spec.metabase_config.display
            metabase_config["fallback_applied"] = bool(getattr(metabase, "last_fallback_applied", False))
            metabase_config["fallback_reason"] = str(getattr(metabase, "last_fallback_reason", "") or "")
            chart_config["metabase"] = metabase_config
            if "metabase_error" in chart_config:
                chart_config.pop("metabase_error", None)
            if "user_message" in chart_config:
                chart_config.pop("user_message", None)

            report.chart_type = requested_chart_type
            report.status = VoiceReport.STATUS_VISUALIZATION_CREATED
            report.error_message = ""
            report.chart_config = chart_config
            report.visualization_spec = new_spec.model_dump(mode="json")
            report.ai_trace = build_report_ai_trace(report, embed_url=str(report.embed_url or ""))
            report.save(
                update_fields=[
                    "chart_type",
                    "status",
                    "error_message",
                    "chart_config",
                    "visualization_spec",
                    "ai_trace",
                    "updated_at",
                ]
            )

            return Response(
                {
                    "success": True,
                    "report_id": report.id,
                    "previous_chart_type": previous_chart_type,
                    "chart_type": requested_chart_type,
                    "metabase_display": new_spec.metabase_config.display,
                    "chart_contract": new_spec.chart_contract.model_dump(mode="json"),
                    "visualization_spec": new_spec.model_dump(mode="json"),
                    "metabase_visualization_settings": chart_config["metabase_visualization_settings"],
                    "embed_url": str(report.embed_url or ""),
                    "message": "Chart type updated successfully.",
                }
            )
        except Http404:
            return Response(
                {'success': False, 'error': 'Report not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as exc:
            logger.error("Error switching chart type report=%s: %s", report_id, exc, exc_info=True)
            return Response(
                {'success': False, 'error': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AITraceDetailView(APIView):
    """
    Return normalized AI trace payload for one report.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, report_id):
        try:
            workspace_id = get_user_workspace_id(request)
            if not workspace_id:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            report = get_object_or_404(
                _voice_report_safe_queryset(),
                id=report_id,
                workspace_id=workspace_id,
            )
            embed_url = get_report_embed_url(report)
            ai_trace = build_report_ai_trace(report, embed_url=embed_url)
            if report.ai_trace != ai_trace:
                report.ai_trace = ai_trace
                report.save(update_fields=['ai_trace', 'updated_at'])

            return Response(
                {
                    'success': True,
                    'report_id': report.id,
                    'ai_trace': ai_trace,
                }
            )
        except Http404:
            return Response(
                {'success': False, 'error': 'Report not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error("Error loading AI trace report=%s: %s", report_id, e, exc_info=True)
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
            workspace_id = get_user_workspace_id(request)
            if not workspace_id:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get dashboard ID from any report
            report = VoiceReport.objects.filter(
                workspace_id=workspace_id,
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
            identity = extract_identity_context(request)
            workspace_id = get_user_workspace_id(request)
            if not workspace_id:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            reports = VoiceReport.objects.filter(workspace_id=workspace_id)

            # Preserve list visibility semantics:
            # managers only see their own reports; others see workspace reports.
            if identity.role == 'manager' and identity.user_id:
                reports = reports.filter(created_by_id=identity.user_id)

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
                identity.user_id,
                workspace_id,
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
        """Check connectivity to Small Whisper, Query, and Metabase."""
        health = {
            'small_whisper': False,
            'query': False,
            'metabase': False
        }
        
        # Check Small Whisper
        try:
            whisper_client = get_small_whisper_client()
            response = requests.get(f"{whisper_client.base_url}/health/", timeout=5)
            health['small_whisper'] = response.status_code == 200
        except:
            pass
        
        # Voice has no ClickHouse client or credential; Query owns that boundary.
        try:
            query_service_url = os.getenv('QUERY_SERVICE_URL', 'http://query-service:8006').rstrip('/')
            response = requests.get(f"{query_service_url}/health/", timeout=5)
            health['query'] = response.status_code == 200
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

