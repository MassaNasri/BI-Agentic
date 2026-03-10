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


class BaseLogView(APIView):

    table_name = None  # define per child

    def get(self, request):
        try:
            sql = build_select_query(self.table_name)
            raw = SurrealClient().query(sql)
            data = LogSerializer.serialize(raw)
            return Response(make_response(True, "Logs fetched", data))
        except Exception as e:
            return Response(make_response(False, str(e)))


class ConnectionLogsView(BaseLogView):
    table_name = "connection_logs"


class SchemaLogsView(BaseLogView):
    table_name = "schema_logs"


class ExtractLogsView(BaseLogView):
    table_name = "extract_logs"


class TransformLogsView(BaseLogView):
    table_name = "transform_logs"


class LoadLogsView(BaseLogView):
    table_name = "load_logs"


class LineageQueryView(APIView):
    def get(self, request, row_id: str):
        try:
            data = LineageTracker().query_lineage(row_id)
            return Response(make_response(True, "Lineage fetched", data))
        except Exception as e:
            return Response(make_response(False, str(e)))


class QualityTrendsView(APIView):
    def get(self, request):
        try:
            host = os.getenv("CLICKHOUSE_HOST", "clickhouse")
            port = int(os.getenv("CLICKHOUSE_PORT", "9000"))
            database = os.getenv("CLICKHOUSE_DATABASE", "etl")
            user = os.getenv("CLICKHOUSE_USER", "etl_user")
            password = os.getenv("CLICKHOUSE_PASSWORD", "etl_pass123")
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
            GROUP BY day
            ORDER BY day
            """
            rows = client.execute(query)
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
        except Exception as e:
            return Response(make_response(False, str(e)))


class HealthView(APIView):
    def get(self, request):
        return Response(make_response(True, "ok", {"status": "ok"}))


class MetricsView(APIView):
    def get(self, request):
        data, content_type = render_metrics()
        return HttpResponse(data, content_type=content_type)
