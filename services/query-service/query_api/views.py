from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from datetime import timedelta

from query_api.application.query_execution import execute_sql_payload
from query_api.services import SQLGuard, get_clickhouse_executor, sanitize_query_results
from query_api.services.workspace_db_resolver import (
    WorkspaceClickhouseDbResolutionError,
    WorkspaceDatasetBindingError,
    resolve_workspace_clickhouse_db,
    resolve_workspace_dataset_binding,
)
from database.models import AuthorizedQueryDefinition


class WorkspaceRequestScopeError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = int(http_status)


def _authorized_workspace_id(request) -> int:
    claim_value = getattr(request.user, "workspace_id", None)
    try:
        claim_workspace_id = int(claim_value)
    except (TypeError, ValueError) as exc:
        raise WorkspaceRequestScopeError(
            "workspace_claim_missing",
            "Authenticated token is missing a valid workspace claim.",
            http_status=status.HTTP_401_UNAUTHORIZED,
        ) from exc

    requested_value = request.data.get("workspace_id")
    if requested_value not in (None, "", b""):
        try:
            requested_workspace_id = int(requested_value)
        except (TypeError, ValueError) as exc:
            raise WorkspaceRequestScopeError(
                "workspace_id_invalid",
                "workspace_id must be a positive integer.",
                http_status=status.HTTP_400_BAD_REQUEST,
            ) from exc
        if requested_workspace_id != claim_workspace_id:
            raise WorkspaceRequestScopeError(
                "workspace_scope_mismatch",
                "Requested workspace does not match the authenticated workspace.",
                http_status=status.HTTP_403_FORBIDDEN,
            )
    return claim_workspace_id


def _workspace_scope_error_response(exc: WorkspaceRequestScopeError) -> Response:
    return Response(
        {
            "success": False,
            "error": str(exc),
            "error_code": exc.code.upper(),
            "code": exc.code,
        },
        status=exc.http_status,
    )


class QueryHealthView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        try:
            executor = get_clickhouse_executor()
            success = bool(executor.test_connection())
            payload = {
                'success': success,
                'service': 'query-service',
            }
        except Exception as exc:
            payload = {
                'success': False,
                'service': 'query-service',
                'error': str(exc),
            }

        return Response(payload, status=status.HTTP_200_OK)


class QueryValidateInternalView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        sql = request.data.get('sql', '')
        try:
            workspace_id = _authorized_workspace_id(request)
        except WorkspaceRequestScopeError as exc:
            return _workspace_scope_error_response(exc)
        try:
            workspace_database = resolve_workspace_clickhouse_db(workspace_id).clickhouse_db
        except WorkspaceClickhouseDbResolutionError as exc:
            return Response(
                {'success': False, 'error': str(exc), 'error_code': exc.code},
                status=exc.http_status,
            )

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
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            workspace_id = _authorized_workspace_id(request)
        except WorkspaceRequestScopeError as exc:
            return _workspace_scope_error_response(exc)
        payload = dict(request.data)
        payload["workspace_id"] = workspace_id
        result, http_status = execute_sql_payload(payload)
        return Response(result, status=http_status)


class QueryDefinitionCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            workspace_id = _authorized_workspace_id(request)
            binding = resolve_workspace_dataset_binding(
                workspace_id,
                dataset_id=request.data.get('dataset_id'),
                verify_physical=False,
            )
        except WorkspaceRequestScopeError as exc:
            return _workspace_scope_error_response(exc)
        except WorkspaceDatasetBindingError as exc:
            return Response({'success': False, 'error': str(exc)}, status=int(exc.http_status))
        except Exception:
            return Response(
                {'success': False, 'error': 'Dataset authorization dependency failed.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        guard = SQLGuard(workspace_database=binding.clickhouse_db)
        valid, error, clean_sql = guard.validate_and_sanitize(request.data.get('sql', ''))
        if not valid:
            return Response({'success': False, 'error': error}, status=status.HTTP_400_BAD_REQUEST)
        definition = AuthorizedQueryDefinition.objects.create(
            workspace_id=workspace_id,
            dataset_id=binding.dataset_id,
            normalized_sql=clean_sql,
            creator_id=str(getattr(request.user, 'id', '') or ''),
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        return Response(
            {'success': True, 'query_definition_id': str(definition.id), 'expires_at': definition.expires_at},
            status=status.HTTP_201_CREATED,
        )


class QueryDefinitionVisualizationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, definition_id):
        try:
            workspace_id = _authorized_workspace_id(request)
        except WorkspaceRequestScopeError as exc:
            return _workspace_scope_error_response(exc)
        definition = AuthorizedQueryDefinition.objects.filter(
            id=definition_id,
            workspace_id=workspace_id,
            validation_status='approved',
            expires_at__gt=timezone.now(),
        ).first()
        if definition is None:
            return Response(
                {'success': False, 'error': 'Authorized query definition not found or expired.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({
            'success': True,
            'query_definition_id': str(definition.id),
            'workspace_id': definition.workspace_id,
            'dataset_id': definition.dataset_id,
            'sql': definition.normalized_sql,
            'expires_at': definition.expires_at,
        })
