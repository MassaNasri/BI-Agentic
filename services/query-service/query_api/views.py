from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from query_api.services import SQLGuard, get_clickhouse_executor, sanitize_query_results


class QueryHealthView(APIView):
    permission_classes = []

    def get(self, request):
        executor = get_clickhouse_executor()
        return Response(
            {
                'success': executor.test_connection(),
                'service': 'query-service',
            },
            status=status.HTTP_200_OK,
        )


class QueryValidateInternalView(APIView):
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
