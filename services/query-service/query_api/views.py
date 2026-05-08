<<<<<<< HEAD
﻿from rest_framework import status
=======
"""query-service HTTP views (Phase 7 / CRIT-05).

Phase 7 of the audit removes the legacy hardcoded ``workspace_database = "etl"``
fallback and forces every internal entry point (``/query/validate/``,
``/query/execute/``) to:

1. REQUIRE a ``workspace_id`` in the request body.
2. Resolve the workspace's ClickHouse database via
   :func:`resolve_workspace_clickhouse_db`.
3. Bind that database into ``SQLGuard`` so cross-tenant table references are
   rejected with HTTP 403 instead of being silently re-routed.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from rest_framework import status
from rest_framework.authentication import SessionAuthentication
>>>>>>> c791036 (final update)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

<<<<<<< HEAD
from query_api.services import SQLGuard, get_clickhouse_executor, sanitize_query_results
=======
from query_api.authentication import ServiceInternalTokenAuthentication
from query_api.application.query_execution import execute_sql_payload
from query_api.jwt_authentication import QueryJWTAuthentication
from query_api.services import (
    SQLGuard,
    WorkspaceClickhouseDbResolutionError,
    get_clickhouse_executor,
    resolve_workspace_clickhouse_db,
)
from query_api.sql_parser import ensure_sql_parser_ready

logger = logging.getLogger(__name__)


def _resolution_error_response(exc: WorkspaceClickhouseDbResolutionError) -> Response:
    """Map a workspace-resolution error to a stable HTTP response."""

    return Response(
        {
            "success": False,
            "error": str(exc),
            "error_code": exc.code,
        },
        status=int(exc.http_status or status.HTTP_400_BAD_REQUEST),
    )
>>>>>>> c791036 (final update)


class QueryHealthView(APIView):
    permission_classes = []

    def get(self, request):
<<<<<<< HEAD
        executor = get_clickhouse_executor()
        return Response(
            {
                'success': executor.test_connection(),
                'service': 'query-service',
=======
        executor = None
        clickhouse_ok = False
        clickhouse_error = ""
        try:
            executor = get_clickhouse_executor()
            clickhouse_ok = bool(executor.test_connection())
        except Exception as exc:
            clickhouse_error = str(exc)
            logger.warning("query_health_clickhouse_unavailable error=%s", clickhouse_error)
        parser_status = ensure_sql_parser_ready(strict=False)
        return Response(
            {
                "success": clickhouse_ok,
                "service": "query-service",
                "sql_parser": parser_status.parser,
                "sql_parser_available": parser_status.available,
                "clickhouse_ready": clickhouse_ok,
                "clickhouse_error": clickhouse_error,
>>>>>>> c791036 (final update)
            },
            status=status.HTTP_200_OK,
        )


class QueryValidateInternalView(APIView):
<<<<<<< HEAD
=======
    """Validate a SQL string against the per-workspace ClickHouse database.

    Phase 7 / CRIT-05: ``workspace_id`` is mandatory; the legacy ``"etl"``
    fallback is gone. The response carries the resolved database name so the
    caller can verify it received the expected tenant.
    """

    authentication_classes = [
        ServiceInternalTokenAuthentication,
        QueryJWTAuthentication,
        SessionAuthentication,
    ]
>>>>>>> c791036 (final update)
    permission_classes = [IsAuthenticated]

    def post(self, request):
        sql = request.data.get('sql', '')
        workspace_database = request.data.get('workspace_database') or 'etl'

        guard = SQLGuard(workspace_database=workspace_database)
        is_valid, error_msg, clean_sql = guard.validate_and_sanitize(sql)

        if not is_valid:
            return Response(
                {
                    'success': False,
                    'error': error_msg,
                    'sql': clean_sql,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                'success': True,
                'sql': clean_sql,
            },
            status=status.HTTP_200_OK,
        )


class QueryExecuteInternalView(APIView):
<<<<<<< HEAD
=======
    """Execute a SQL statement against the per-workspace ClickHouse database.

    Phase 7 / CRIT-05: ``workspace_id`` is required. We resolve the
    ClickHouse database here, replace the previous client-supplied
    ``workspace_database`` field with the canonical value, then delegate to
    :func:`execute_sql_payload`.
    """

    authentication_classes = [
        ServiceInternalTokenAuthentication,
        QueryJWTAuthentication,
        SessionAuthentication,
    ]
>>>>>>> c791036 (final update)
    permission_classes = [IsAuthenticated]

    def post(self, request):
        sql = request.data.get('sql', '')
        workspace_database = request.data.get('workspace_database') or 'etl'

        guard = SQLGuard(workspace_database=workspace_database)
        is_valid, error_msg, clean_sql = guard.validate_and_sanitize(sql)

        if not is_valid:
            return Response(
                {
                    'success': False,
                    'error': error_msg,
                    'sql': clean_sql,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        executor = get_clickhouse_executor()
        result = executor.execute_query(clean_sql)

        if not result.get('success'):
            return Response(
                {
                    'success': False,
                    'error': result.get('error', 'query_failed'),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        rows = sanitize_query_results(result.get('rows', []))
        return Response(
            {
                'success': True,
                'sql': clean_sql,
                'rows': rows,
                'columns': result.get('columns', []),
                'row_count': result.get('row_count', 0),
                'execution_time_ms': result.get('execution_time_ms', 0),
            },
            status=status.HTTP_200_OK,
        )
