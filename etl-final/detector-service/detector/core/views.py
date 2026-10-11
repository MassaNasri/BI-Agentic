from django.shortcuts import render
from django.http import HttpResponse

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from shared.utils.kafka_consumer import KafkaMessageConsumer
from shared.utils.kafka_producer import KafkaMessageProducer
from .db_detector import detect_db_type
from .schema_extractor import SchemaExtractor
from shared.utils.surreal_client import SurrealClient
from shared.utils.response import make_response
from shared.utils.metrics import render_metrics
from shared.security.internal_auth import ETLInternalAuthentication, require_etl_scope


class RunDetectorView(APIView):
    """
    Manual trigger for schema detection service.
    """

    authentication_classes = [ETLInternalAuthentication]

    def get(self, request):
        scope = require_etl_scope(request)
        consumer = KafkaMessageConsumer("raw_data_topic")

        for msg in consumer.listen():

            try:
                if any(str(msg.get(key)) != str(value) for key, value in scope.as_message_fields().items()):
                    continue
                db_type = detect_db_type(msg)
                extractor = SchemaExtractor()

                if db_type == "mysql":
                    schema = extractor.extract_mysql(msg)
                elif db_type == "postgres":
                    schema = extractor.extract_postgres(msg)
                else:
                    return Response(make_response(False, "Unsupported DB"), status=400)

                schema.update(scope.as_message_fields())

                KafkaMessageProducer().send("schema_topic", schema)
                SurrealClient().insert_schema_log(schema)

                return Response(make_response(True, "Schema extracted", schema), status=200)

            except Exception:
                return Response(make_response(False, "Schema detection failed"), status=400)


class HealthView(APIView):
    def get(self, request):
        return Response(make_response(True, "ok", {"status": "ok"}))


class MetricsView(APIView):
    def get(self, request):
        data, content_type = render_metrics()
        return HttpResponse(data, content_type=content_type)
