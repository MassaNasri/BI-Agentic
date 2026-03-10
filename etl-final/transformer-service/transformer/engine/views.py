import json
import os
from django.http import HttpResponse

from rest_framework.views import APIView
from rest_framework.response import Response

from shared.utils.kafka_producer import KafkaMessageProducer
from shared.utils.response import make_response
from shared.utils.quarantine_manager import QuarantineManager
from clickhouse_driver import Client
from shared.models.rule_yaml_parser import load_rules_from_yaml
from shared.models.rules_engine import RulesEngine
from shared.utils.metrics import render_metrics

from .transformer_service import TransformerService


class TestTransformView(APIView):
    """
    Manual test endpoint for transformation.
    """

    def post(self, request):

        table = request.data.get("table")
        row = request.data.get("row")

        try:
            service = TransformerService()
            results, stats = service.process_batch([{
                "source": request.data.get("source", "manual"),
                "batch_id": request.data.get("batch_id"),
                "data": row,
                "schema_contract": request.data.get("schema_contract"),
            }])

            result = results[0] if results else None
            if not result or result["status"] != "success":
                return Response(make_response(False, "Transformation failed", {
                    "warnings": stats.get("warnings", []),
                    "errors": stats.get("errors", []),
                }))

            cleaned = result.get("cleaned_row")
            transformed = result.get("transformed_row")
            cleaning_warnings = result.get("warnings", [])
            transform_warnings = result.get("errors", [])

            return Response(make_response(True, "Transformed", {
                "cleaned": cleaned,
                "transformed": transformed,
                "cleaning_warnings": cleaning_warnings,
                "transform_warnings": transform_warnings,
            }))
        except Exception as e:
            return Response(make_response(False, str(e)))


class QuarantineReviewView(APIView):
    """
    Review quarantined rows.
    """

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit", 100))
            offset = int(request.query_params.get("offset", 0))
            source_id = request.query_params.get("source_id")
            batch_id = request.query_params.get("batch_id")
            include_reprocessed = request.query_params.get("include_reprocessed", "false").lower() == "true"

            manager = _get_quarantine_manager()
            if not manager:
                return Response(make_response(False, "Quarantine manager unavailable"))

            rows = manager.list_quarantined(
                limit=limit,
                offset=offset,
                source_id=source_id,
                batch_id=batch_id,
                include_reprocessed=include_reprocessed,
            )

            return Response(make_response(True, "Quarantine rows", {
                "rows": rows,
                "limit": limit,
                "offset": offset,
            }))
        except Exception as e:
            return Response(make_response(False, str(e)))


class QuarantineReprocessView(APIView):
    """
    Reprocess quarantined rows.
    """

    def post(self, request):
        try:
            ids = request.data.get("ids", [])
            if not ids:
                return Response(make_response(False, "No quarantine ids provided"))

            rules_path = request.data.get("rules_path")
            schema_contract = request.data.get("schema_contract")

            manager = _get_quarantine_manager()
            if not manager:
                return Response(make_response(False, "Quarantine manager unavailable"))

            rules = []
            if rules_path:
                rules = load_rules_from_yaml(rules_path)
                errors = RulesEngine.validate_rules(rules)
                if errors:
                    return Response(make_response(False, f"Rule validation errors: {errors}"))

            service = TransformerService(default_rules=rules)
            producer = KafkaMessageProducer()

            records = manager.get_by_ids(ids)
            messages = []
            record_ids = []
            for record in records:
                original_row = record.get("_original_row")
                try:
                    row_data = json.loads(original_row) if isinstance(original_row, str) else original_row
                except Exception:
                    row_data = None
                if not row_data:
                    continue

                message = {
                    "source": record.get("_source_id", "unknown"),
                    "batch_id": record.get("_batch_id"),
                    "data": row_data,
                    "schema_contract": schema_contract,
                }
                messages.append(message)
                record_ids.append(str(record.get("_quarantine_id")))

            results, stats = service.process_batch(messages, schema_contract=schema_contract)

            reprocessed_ids = []
            for idx, result in enumerate(results):
                if result["status"] != "success":
                    continue
                clean_message = result["clean_message"]
                if producer.send("clean_rows_topic", clean_message):
                    reprocessed_ids.append(record_ids[idx])

            if reprocessed_ids:
                manager.mark_reprocessed(reprocessed_ids)

            return Response(make_response(True, "Reprocessed", {
                "reprocessed_ids": reprocessed_ids,
                "stats": stats,
            }))
        except Exception as e:
            return Response(make_response(False, str(e)))


class HealthView(APIView):
    def get(self, request):
        return Response(make_response(True, "ok", {"status": "ok"}))


class MetricsView(APIView):
    def get(self, request):
        data, content_type = render_metrics()
        return HttpResponse(data, content_type=content_type)


def _get_quarantine_manager() -> QuarantineManager | None:
    try:
        client = Client(
            host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
            port=int(os.getenv("CLICKHOUSE_PORT", "9000")),
            user=os.getenv("CLICKHOUSE_USER", "default"),
            password=os.getenv("CLICKHOUSE_PASSWORD", ""),
            database=os.getenv("CLICKHOUSE_DATABASE", "etl"),
        )
        return QuarantineManager(client)
    except Exception:
        return None
