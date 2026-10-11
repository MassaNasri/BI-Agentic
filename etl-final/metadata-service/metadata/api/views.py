from django.shortcuts import render
from django.http import HttpResponse
import os

from rest_framework.views import APIView
from rest_framework.response import Response

from shared.utils.surreal_client import SurrealClient
from shared.utils.response import make_response
from shared.utils.metrics import render_metrics
from shared.utils.lineage_tracker import LineageTracker
from shared.utils.quality_metrics import QualityMetricsManager
from clickhouse_driver import Client

from .query_builder import build_select_query
from .serializers import LogSerializer
from shared.security.internal_auth import ETLInternalAuthentication, record_matches_scope, require_etl_scope


class BaseLogView(APIView):

    authentication_classes = [ETLInternalAuthentication]

    table_name = None  # define per child

    def get(self, request):
        scope = require_etl_scope(request)
        try:
            sql = build_select_query(self.table_name, scope)
            raw = SurrealClient().query(sql)
            data = [
                row for row in LogSerializer.serialize(raw)
                if record_matches_scope(row, scope)
            ]
            return Response(make_response(True, "Logs fetched", data))
        except Exception:
            return Response(make_response(False, "Metadata query failed"), status=502)


class ConnectionLogsView(BaseLogView):
    table_name = "connection_metadata"


class SchemaLogsView(BaseLogView):
    table_name = "schema_metadata"


class ExtractLogsView(BaseLogView):
    table_name = "extraction_metadata"


class TransformLogsView(BaseLogView):
    table_name = "cleaning_metadata"


class LoadLogsView(BaseLogView):
    table_name = "loading_metadata"


class LineageQueryView(APIView):
    authentication_classes = [ETLInternalAuthentication]

    def get(self, request, row_id: str):
        scope = require_etl_scope(request)
        try:
            data = LineageTracker().query_lineage(row_id)
            if not record_matches_scope(data, scope):
                return Response(make_response(False, "Lineage record not found"), status=404)
            return Response(make_response(True, "Lineage fetched", data))
        except Exception:
            return Response(make_response(False, "Lineage query failed"), status=502)


class QualityTrendsView(APIView):
    authentication_classes = [ETLInternalAuthentication]

    def get(self, request):
        scope = require_etl_scope(request)
        try:
            host = os.getenv("CLICKHOUSE_HOST", "clickhouse")
            port = int(os.getenv("CLICKHOUSE_PORT", "9000"))
            database = os.getenv("CLICKHOUSE_DATABASE", "etl")
            user = os.getenv("CLICKHOUSE_USER", "etl_user")
            password = os.getenv("CLICKHOUSE_PASSWORD", "")
            if not password:
                return Response(make_response(False, "ClickHouse credentials are not configured"), status=503)
            client = Client(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
            )
            metrics = QualityMetricsManager(client)

            query = """
            SELECT toDate(_calculated_at) AS day,
                   avg(_quality_score) AS quality,
                   avg(_completeness_score) AS completeness,
                   avg(_validity_score) AS validity,
                   avg(_consistency_score) AS consistency,
                   sum(_row_count) AS rows
            FROM quality_metrics
            WHERE workspace_id = %(workspace_id)s
              AND dataset_id = %(dataset_id)s
              AND ingestion_job_id = %(ingestion_job_id)s
            GROUP BY day
            ORDER BY day
            """
            rows = client.execute(query, scope.as_message_fields())
            data = [
                {
                    "day": str(r[0]),
                    "quality": float(r[1]),
                    "completeness": float(r[2]),
                    "validity": float(r[3]),
                    "consistency": float(r[4]),
                    "rows": int(r[5]),
                }
                for r in rows
            ]
            return Response(make_response(True, "Quality trends", data))
        except Exception:
            return Response(make_response(False, "Quality query failed"), status=502)


class HealthView(APIView):
    def get(self, request):
        return Response(make_response(True, "ok", {"status": "ok"}))


class MetricsView(APIView):
    def get(self, request):
        data, content_type = render_metrics()
        return HttpResponse(data, content_type=content_type)
