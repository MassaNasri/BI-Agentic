"""Authoritative logical-dataset analytical query execution."""

from __future__ import annotations

import logging
import os
import time
from typing import Any
from uuid import uuid4

from django.conf import settings

from query_api.resource_policy import QueryResourcePolicy, build_workspace_query_id
from query_api.services import (
    SQLGuard,
    WorkspaceDatasetBinding,
    WorkspaceDatasetBindingError,
    get_clickhouse_executor,
    resolve_workspace_dataset_binding,
    sanitize_query_results,
)
from query_api.services.workspace_concurrency import (
    WorkspaceConcurrencyLimitExceeded,
    WorkspaceConcurrencyUnavailable,
    workspace_query_lease,
)

logger = logging.getLogger(__name__)

_CLIENT_PHYSICAL_FIELDS = {
    "workspace_database",
    "database_name",
    "clickhouse_database",
    "physical_table_name",
}


def _failed_payload(
    *,
    sql: str,
    error: str,
    error_code: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": False,
        "status": "failed",
        "sql": sql,
        "rows": [],
        "columns": [],
        "column_names": [],
        "column_types": [],
        "row_count": 0,
        "scanned_rows": None,
        "bytes_read": None,
        "output_bytes": None,
        "empty_result": False,
        "execution_time_ms": 0,
        "aborted_due_to_timeout": error_code == "QUERY_TIMEOUT",
        "settings_applied": {},
        "pagination": None,
        "error": error,
        "error_code": error_code,
        "error_message": error,
        "result_shape": None,
        "retryable": error_code in {
            "QUERY_TIMEOUT",
            "QUERY_CANCELLED",
            "CLICKHOUSE_UNAVAILABLE",
            "INTERNAL_ERROR",
        },
    }
    if extra:
        payload.update(extra)
    return payload


def _policy() -> QueryResourcePolicy:
    configured = getattr(settings, "QUERY_RESOURCE_POLICY", None)
    return configured if isinstance(configured, QueryResourcePolicy) else QueryResourcePolicy.from_environment()


def _binding_failure(
    payload: dict[str, Any],
    exc: WorkspaceDatasetBindingError,
) -> tuple[dict[str, Any], int]:
    if exc.code == "dataset_id_required":
        code, message, http_status = (
            "FORBIDDEN_DATASET",
            "A logical dataset_id is required for analytical queries.",
            400,
        )
    elif exc.code == "dataset_not_ready":
        code, message, http_status = (
            "FORBIDDEN_DATASET",
            "The authorized dataset is not ready for analytical queries.",
            409,
        )
    elif exc.code == "dataset_source_unavailable":
        code, message, http_status = (
            "CLICKHOUSE_UNAVAILABLE",
            "The analytical data service is temporarily unavailable.",
            503,
        )
    else:
        code, message, http_status = (
            "FORBIDDEN_DATASET",
            "The requested dataset is not authorized for this workspace.",
            403,
        )
    return (
        _failed_payload(
            sql=str(payload.get("sql") or "").strip(),
            error=message,
            error_code=code,
        ),
        http_status,
    )


def resolve_authorized_query_binding(
    payload: dict[str, Any],
) -> tuple[WorkspaceDatasetBinding | None, dict[str, Any] | None, int]:
    for field in _CLIENT_PHYSICAL_FIELDS:
        if payload.get(field) not in (None, "", b""):
            return (
                None,
                _failed_payload(
                    sql=str(payload.get("sql") or "").strip(),
                    error="Physical storage identifiers are not accepted by the query API.",
                    error_code="VALIDATION_REJECTED",
                ),
                400,
            )
    try:
        binding = resolve_workspace_dataset_binding(
            payload.get("workspace_id"),
            dataset_id=payload.get("dataset_id"),
            table_name=payload.get("table_name"),
            verify_physical=False,
            require_dataset_id=True,
        )
    except WorkspaceDatasetBindingError as exc:
        failed, http_status = _binding_failure(payload, exc)
        return None, failed, http_status
    except Exception as exc:
        logger.error("query_binding_dependency_failed error_type=%s", type(exc).__name__)
        return (
            None,
            _failed_payload(
                sql=str(payload.get("sql") or "").strip(),
                error="Dataset authorization is temporarily unavailable.",
                error_code="INTERNAL_ERROR",
            ),
            503,
        )

    if not binding.allowed_tables:
        return (
            None,
            _failed_payload(
                sql=str(payload.get("sql") or "").strip(),
                error="The authorized dataset has no queryable table binding.",
                error_code="FORBIDDEN_DATASET",
            ),
            403,
        )
    return binding, None, 200


def validate_sql_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], int, WorkspaceDatasetBinding | None]:
    sql = str(payload.get("sql") or "").strip()
    binding, failure, failure_status = resolve_authorized_query_binding(payload)
    if failure is not None or binding is None:
        return failure or {}, failure_status, None

    guard = SQLGuard(
        workspace_database=binding.clickhouse_db,
        allowed_tables=binding.allowed_tables,
        require_allowed_tables=True,
    )
    is_valid, error_msg, clean_sql = guard.validate_and_sanitize(sql)
    if not is_valid:
        forbidden = error_msg.startswith(
            ("database_mismatch", "cross_db_violation", "unauthorized_table")
        )
        error_code = "FORBIDDEN_DATASET" if forbidden else "VALIDATION_REJECTED"
        return (
            _failed_payload(
                sql=clean_sql,
                error=(
                    "The query references a table outside the authorized dataset."
                    if forbidden
                    else error_msg
                ),
                error_code=error_code,
                extra={"workspace_id": binding.workspace_id, "dataset_id": binding.dataset_id},
            ),
            403 if forbidden else 400,
            binding,
        )
    return (
        {
            "success": True,
            "status": "validated",
            "sql": clean_sql,
            "workspace_id": binding.workspace_id,
            "dataset_id": binding.dataset_id,
        },
        200,
        binding,
    )


def _executor_failure_status(error_code: str) -> int:
    return {
        "VALIDATION_REJECTED": 400,
        "FORBIDDEN_DATASET": 403,
        "QUERY_TIMEOUT": 504,
        "QUERY_LIMIT_EXCEEDED": 422,
        "QUERY_CANCELLED": 409,
        "CLICKHOUSE_UNAVAILABLE": 503,
        "INTERNAL_ERROR": 500,
    }.get(error_code, 500)


def _audit(
    *,
    request_id: str,
    binding: WorkspaceDatasetBinding,
    outcome: str,
    duration_ms: int,
    rows: int,
    output_bytes: int | None,
    error_code: str | None,
) -> None:
    logger.info(
        "analytical_query request_id=%s workspace_id=%s dataset_id=%s outcome=%s "
        "duration_ms=%s rows=%s output_bytes=%s error_code=%s service_version=%s",
        request_id,
        binding.workspace_id,
        binding.dataset_id,
        outcome,
        duration_ms,
        rows,
        output_bytes,
        error_code or "",
        os.getenv("SERVICE_VERSION", "foundation-a"),
    )


def execute_sql_payload(
    payload: dict[str, Any],
    *,
    lease_factory=None,
) -> tuple[dict[str, Any], int]:
    started = time.monotonic()
    validation, http_status, binding = validate_sql_payload(payload)
    if http_status != 200 or binding is None:
        return validation, http_status

    resource_policy = _policy()
    try:
        page, page_size, _offset = resource_policy.page_options(
            page=payload.get("page"),
            page_size=payload.get("page_size"),
        )
    except ValueError as exc:
        return (
            _failed_payload(
                sql=validation["sql"],
                error=str(exc),
                error_code="VALIDATION_REJECTED",
                extra={"workspace_id": binding.workspace_id, "dataset_id": binding.dataset_id},
            ),
            400,
        )

    request_id = str(payload.get("request_id") or uuid4()).strip()
    query_id = build_workspace_query_id(binding.workspace_id, request_id)
    lease = lease_factory or workspace_query_lease
    try:
        with lease(binding.workspace_id, resource_policy.workspace_concurrency):
            executor = get_clickhouse_executor()
            result = executor.execute_query(
                validation["sql"],
                workspace_database=binding.clickhouse_db,
                policy=resource_policy,
                page=page,
                page_size=page_size,
                query_id=query_id,
            )
    except WorkspaceConcurrencyLimitExceeded:
        result = {
            "success": False,
            "error": "The workspace has reached its concurrent query limit.",
            "error_code": "QUERY_LIMIT_EXCEEDED",
        }
        http_status = 429
    except WorkspaceConcurrencyUnavailable as exc:
        logger.error("query_concurrency_unavailable error_type=%s", type(exc).__name__)
        result = {
            "success": False,
            "error": "Query admission control is temporarily unavailable.",
            "error_code": "INTERNAL_ERROR",
        }
        http_status = 503
    except Exception as exc:
        logger.error("query_executor_unavailable error_type=%s", type(exc).__name__)
        result = {
            "success": False,
            "error": "The analytical data service is temporarily unavailable.",
            "error_code": "CLICKHOUSE_UNAVAILABLE",
        }
        http_status = 503

    duration_ms = int((time.monotonic() - started) * 1000)
    if not result.get("success"):
        error_code = str(result.get("error_code") or "INTERNAL_ERROR").upper()
        if http_status == 200:
            http_status = _executor_failure_status(error_code)
        failure = _failed_payload(
            sql=validation["sql"],
            error=str(result.get("error") or "Query execution failed."),
            error_code=error_code,
            extra={
                "workspace_id": binding.workspace_id,
                "dataset_id": binding.dataset_id,
                "request_id": request_id,
                "query_id": query_id,
                "execution_time_ms": int(result.get("execution_time_ms") or duration_ms),
                "output_bytes": result.get("output_bytes"),
                "settings_applied": dict(result.get("settings_applied") or {}),
                "sql_hash": result.get("sql_hash"),
            },
        )
        _audit(
            request_id=request_id,
            binding=binding,
            outcome="failed",
            duration_ms=duration_ms,
            rows=0,
            output_bytes=failure.get("output_bytes"),
            error_code=error_code,
        )
        return failure, http_status

    rows = sanitize_query_results(result.get("rows", []))
    row_count = int(result.get("row_count", len(rows)) or 0)
    response = {
        "success": True,
        "status": "success",
        "sql": validation["sql"],
        "rows": rows,
        "columns": result.get("columns", []),
        "column_names": result.get("column_names", []),
        "column_types": result.get("column_types", []) or [],
        "row_count": row_count,
        "scanned_rows": result.get("scanned_rows"),
        "bytes_read": result.get("bytes_read"),
        "output_bytes": result.get("output_bytes"),
        "empty_result": row_count == 0,
        "execution_time_ms": int(result.get("execution_time_ms", duration_ms) or 0),
        "aborted_due_to_timeout": False,
        "settings_applied": dict(result.get("settings_applied") or {}),
        "sql_hash": result.get("sql_hash"),
        "request_id": request_id,
        "query_id": result.get("query_id") or query_id,
        "workspace_id": binding.workspace_id,
        "dataset_id": binding.dataset_id,
        "pagination": result.get("pagination"),
        "truncated": bool((result.get("pagination") or {}).get("truncated")),
        "error": None,
        "error_code": None,
        "error_message": None,
        "retryable": False,
        "result_shape": result.get("result_shape"),
    }
    _audit(
        request_id=request_id,
        binding=binding,
        outcome="success",
        duration_ms=duration_ms,
        rows=row_count,
        output_bytes=response.get("output_bytes"),
        error_code=None,
    )
    return response, 200


__all__ = [
    "execute_sql_payload",
    "resolve_authorized_query_binding",
    "validate_sql_payload",
]
