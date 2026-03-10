from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from shared.utils.kafka_schema_validator import KafkaSchemaValidator


class TestRunExtractorView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/run/"

    @patch("engine.views.SurrealClient")
    @patch("engine.views.KafkaMessageProducer")
    @patch("engine.views.RowExtractor")
    @patch("engine.views.DBConnector")
    def test_run_extractor_emits_schema_conformant_batch_messages(
        self,
        mock_db_connector_cls,
        mock_row_extractor_cls,
        mock_producer_cls,
        _mock_surreal_cls,
    ):
        connection = Mock()
        mock_db_connector_cls.return_value.connect.return_value = connection

        extractor = Mock()
        extractor.extract_rows.return_value = iter(
            [
                ("users", {"id": 1, "name": "Alice"}),
                ("users", {"id": 2, "name": "Bob"}),
            ]
        )
        mock_row_extractor_cls.return_value = extractor

        producer = Mock()
        producer.send.return_value = True
        mock_producer_cls.return_value = producer

        payload = {
            "config": {
                "db_type": "postgresql",
                "host": "localhost",
                "user": "postgres",
                "password": "secret",
                "database": "analytics",
                "port": 5432,
            },
            "schema": {"users": {"columns": ["id", "name"]}},
        }
        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 200)
        connect_cfg = mock_db_connector_cls.return_value.connect.call_args[0][0]
        self.assertEqual(connect_cfg["db_type"], "postgres")

        send_calls = [call for call in producer.send.call_args_list if call[0][0] == "extracted_rows_topic"]
        self.assertGreaterEqual(len(send_calls), 1)
        message = send_calls[0][0][1]
        self.assertIn("rows", message)
        self.assertNotIn("row", message)
        self.assertEqual(message["row_count"], len(message["rows"]))

        is_valid, error = KafkaSchemaValidator.validate_message("extracted_rows_topic", message)
        self.assertTrue(is_valid, error)

