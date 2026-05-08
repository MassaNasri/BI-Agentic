import uuid
import json
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.utils import ProgrammingError
from django.utils import timezone

from voice_reports.domain import statuses
from voice_reports.models import VoicePipelineJob, VoiceReport


def _adapt_json_param(value: Any) -> Any:
    if value is None:
        return None
    adapted = connection.ops.adapt_json_value(value, DjangoJSONEncoder)
    # Some legacy driver/backend combinations can return raw dict/list here,
    # which psycopg cannot bind directly in raw cursor.execute.
    if isinstance(adapted, (dict, list)):
        return json.dumps(value, cls=DjangoJSONEncoder)
    return adapted


def _is_missing_user_email_column_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "voice_pipeline_jobs" in message
        and "user_email" in message
        and ("does not exist" in message or "undefinedcolumn" in message)
    )


def _insert_pipeline_job_legacy_schema(
    *,
    report: VoiceReport,
    input_type: str,
    original_question: str,
    trace_payload: dict[str, Any],
) -> VoicePipelineJob:
    job_uuid = uuid.uuid4()
    now = timezone.now()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO voice_pipeline_jobs (
                job_id,
                report_id,
                workspace_id,
                user_id,
                status,
                current_stage,
                input_type,
                original_question,
                cleaned_question,
                generated_sql,
                execution_result_summary,
                visualization_id,
                progress,
                retry_count,
                error_code,
                error_message,
                trace,
                created_at,
                updated_at,
                completed_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING id
            """,
            [
                job_uuid,
                int(report.id),
                str(report.workspace_id or "").strip(),
                str(report.created_by_id or "").strip(),
                statuses.PENDING,
                statuses.PENDING,
                input_type,
                str(original_question or ""),
                "",
                "",
                None,
                "",
                0,
                0,
                "",
                "",
                _adapt_json_param(trace_payload),
                now,
                now,
                None,
            ],
        )
        row = cursor.fetchone()

    job_id = int(row[0]) if row else 0
    if not job_id:
        raise RuntimeError("Legacy pipeline job insert did not return an ID")
    return VoicePipelineJob.objects.only(
        "id",
        "job_id",
        "report_id",
        "workspace_id",
        "user_id",
        "status",
        "current_stage",
        "input_type",
        "original_question",
        "progress",
        "trace",
        "created_at",
        "updated_at",
        "completed_at",
    ).get(id=job_id)


def create_pipeline_job(*, report: VoiceReport, input_type: str, original_question: str = "", payload: dict[str, Any] | None = None) -> VoicePipelineJob:
    trace_payload = payload or {}
    try:
        return VoicePipelineJob.objects.create(
            job_id=uuid.uuid4(),
            report=report,
            workspace_id=str(report.workspace_id or "").strip(),
            user_id=str(report.created_by_id or "").strip(),
            user_email=str(getattr(report, "created_by_email", "") or "").strip(),
            input_type=input_type,
            original_question=original_question,
            status=statuses.PENDING,
            current_stage=statuses.PENDING,
            progress=0,
            trace=trace_payload,
        )
    except ProgrammingError as exc:
        if not _is_missing_user_email_column_error(exc):
            raise
        return _insert_pipeline_job_legacy_schema(
            report=report,
            input_type=input_type,
            original_question=original_question,
            trace_payload=trace_payload,
        )


def mark_job_stage(job: VoicePipelineJob, *, status: str, stage: str, progress: int, error_code: str = "", error_message: str = "") -> VoicePipelineJob:
    job.status = status
    job.current_stage = stage
    job.progress = max(0, min(100, int(progress)))
    if error_code:
        job.error_code = error_code
    if error_message:
        job.error_message = error_message
    if status in {statuses.COMPLETED, statuses.FAILED, statuses.PARTIAL}:
        job.completed_at = timezone.now()
    job.save()
    return job
