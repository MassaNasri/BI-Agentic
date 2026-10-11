from django.shortcuts import render

from rest_framework.views import APIView
from rest_framework.response import Response

from shared.utils.response import make_response
from shared.utils.surreal_client import SurrealClient
from shared.security.internal_auth import ETLInternalAuthentication, require_etl_scope

from .loader_logic import LoaderLogic


class TestLoaderView(APIView):
    authentication_classes = [ETLInternalAuthentication]

    def post(self, request):
        scope = require_etl_scope(request)

        config = request.data.get("config")  # ClickHouse config
        table = request.data.get("table")
        row = request.data.get("row")

        try:
            loader = LoaderLogic(config)
            loader.load_row(table, row)

            SurrealClient().insert("load_logs", {
                "table": table,
                "row": row,
                "status": "inserted"
                , **scope.as_message_fields()
            })

            return Response(make_response(True, "Row inserted successfully."))
        except Exception:
            return Response(make_response(False, "Load failed"), status=400)
