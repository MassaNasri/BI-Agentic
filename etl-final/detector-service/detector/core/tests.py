import uuid
from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APITestCase


@override_settings(ETL_INTERNAL_API_KEY="detector-test-key")
class DetectorApiTests(APITestCase):
    def _auth_headers(self, **extra):
        headers = {
            "HTTP_X_INTERNAL_SERVICE": "query-service",
            "HTTP_X_INTERNAL_API_KEY": "detector-test-key",
        }
        headers.update(extra)
        return headers

    def test_health_is_public_and_reports_ok(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["status"], "ok")

    def test_detector_rejects_unauthenticated_requests(self):
        response = self.client.get("/api/run-detector/")

        self.assertEqual(response.status_code, 403)

    def test_detector_requires_complete_tenant_scope(self):
        response = self.client.get("/api/run-detector/", **self._auth_headers())

        self.assertEqual(response.status_code, 400)
        self.assertIn("workspace_id", response.data)

    @patch("core.views.SurrealClient")
    @patch("core.views.KafkaMessageProducer")
    @patch("core.views.SchemaExtractor")
    @patch("core.views.detect_db_type", return_value="postgres")
    @patch("core.views.KafkaMessageConsumer")
    def test_detector_preserves_scope_in_schema_event(
        self,
        consumer_class,
        _detect_db_type,
        extractor_class,
        producer_class,
        surreal_class,
    ):
        job_id = uuid.uuid4()
        scope = {
            "workspace_id": 7,
            "dataset_id": "orders-2026",
            "ingestion_job_id": str(job_id),
        }
        raw_message = {**scope, "connection_type": "postgres"}
        consumer_class.return_value.listen.return_value = iter([raw_message])
        extractor_class.return_value.extract_postgres.return_value = {
            "tables": [{"name": "orders"}]
        }

        response = self.client.get(
            "/api/run-detector/",
            **self._auth_headers(
                HTTP_X_WORKSPACE_ID="7",
                HTTP_X_DATASET_ID="orders-2026",
                HTTP_X_INGESTION_JOB_ID=str(job_id),
            ),
        )

        self.assertEqual(response.status_code, 200)
        producer = producer_class.return_value
        producer.send.assert_called_once()
        topic, event = producer.send.call_args.args
        self.assertEqual(topic, "schema_topic")
        self.assertEqual({key: event[key] for key in scope}, scope)
        surreal_class.return_value.insert_schema_log.assert_called_once_with(event)
