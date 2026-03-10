from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient


class TestConnectorKafkaReliability(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.connect_url = "/api/connect-db/"
        self.upload_url = "/api/upload/"
        self.valid_db_payload = {
            "db_type": "postgresql",
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "password": "secret",
            "database": "analytics",
        }

    @patch.dict(
        "os.environ",
        {
            "CONNECTOR_KAFKA_SEND_RETRIES": "2",
            "CONNECTOR_KAFKA_SEND_BACKOFF_BASE": "0",
            "CONNECTOR_KAFKA_SEND_BACKOFF_MAX": "0",
        },
        clear=False,
    )
    @patch("etl_engine.views.time.sleep", return_value=None)
    @patch("etl_engine.views.SurrealClient")
    @patch("etl_engine.views.get_encryption_instance")
    @patch("etl_engine.views.test_db_connection", return_value=(True, "ok"))
    @patch("etl_engine.views.KafkaMessageProducer")
    def test_connect_db_returns_503_when_kafka_send_returns_false(
        self,
        mock_producer_cls,
        _mock_test_connection,
        mock_encryption,
        mock_surreal,
        _mock_sleep,
    ):
        mock_encryption.return_value.encrypt.return_value = "enc"
        producer = Mock()
        producer.send.return_value = False
        mock_producer_cls.return_value = producer

        response = self.client.post(self.connect_url, self.valid_db_payload, format="json")

        self.assertEqual(response.status_code, 503)
        self.assertIn("failed to publish", response.data.get("message", "").lower())
        self.assertEqual(producer.send.call_count, 2)
        mock_surreal.return_value.insert.assert_not_called()

    @patch("etl_engine.views.SurrealClient")
    @patch("etl_engine.views.get_encryption_instance")
    @patch("etl_engine.views.test_db_connection", return_value=(True, "ok"))
    @patch("etl_engine.views.KafkaMessageProducer")
    def test_postgresql_input_is_normalized_to_postgres_for_kafka_contract(
        self,
        mock_producer_cls,
        mock_test_connection,
        mock_encryption,
        mock_surreal,
    ):
        mock_encryption.return_value.encrypt.return_value = "enc"
        producer = Mock()
        producer.send.return_value = True
        mock_producer_cls.return_value = producer

        response = self.client.post(self.connect_url, self.valid_db_payload, format="json")

        self.assertEqual(response.status_code, 200)
        called_args = mock_test_connection.call_args[0]
        self.assertEqual(called_args[0], "postgres")

        first_send_args = producer.send.call_args_list[0][0]
        self.assertEqual(first_send_args[0], "connection_topic")
        self.assertEqual(first_send_args[1]["db_type"], "postgres")
        mock_surreal.return_value.insert.assert_called_once()

    @patch.dict(
        "os.environ",
        {
            "CONNECTOR_KAFKA_SEND_RETRIES": "2",
            "CONNECTOR_KAFKA_SEND_BACKOFF_BASE": "0",
            "CONNECTOR_KAFKA_SEND_BACKOFF_MAX": "0",
        },
        clear=False,
    )
    @patch("etl_engine.views.time.sleep", return_value=None)
    @patch("etl_engine.views.SurrealClient")
    @patch("etl_engine.views.get_encryption_instance")
    @patch("etl_engine.views.test_db_connection", return_value=(True, "ok"))
    @patch("etl_engine.views.KafkaMessageProducer")
    def test_connect_db_returns_503_when_kafka_send_raises(
        self,
        mock_producer_cls,
        _mock_test_connection,
        mock_encryption,
        mock_surreal,
        _mock_sleep,
    ):
        mock_encryption.return_value.encrypt.return_value = "enc"
        producer = Mock()
        producer.send.side_effect = RuntimeError("kafka down")
        mock_producer_cls.return_value = producer

        response = self.client.post(self.connect_url, self.valid_db_payload, format="json")

        self.assertEqual(response.status_code, 503)
        self.assertIn("failed to publish", response.data.get("message", "").lower())
        self.assertEqual(producer.send.call_count, 2)
        mock_surreal.return_value.insert.assert_not_called()

    @patch.dict(
        "os.environ",
        {
            "CONNECTOR_KAFKA_SEND_RETRIES": "2",
            "CONNECTOR_KAFKA_SEND_BACKOFF_BASE": "0",
            "CONNECTOR_KAFKA_SEND_BACKOFF_MAX": "0",
        },
        clear=False,
    )
    @patch("etl_engine.views.time.sleep", return_value=None)
    @patch("etl_engine.views.KafkaMessageProducer")
    @patch("etl_engine.views.SurrealClient")
    @patch("etl_engine.views.save_uploaded_file", return_value="/app/uploaded_files/data.csv")
    def test_upload_file_returns_503_when_trigger_publish_fails(
        self,
        _mock_save,
        mock_surreal,
        mock_producer_cls,
        _mock_sleep,
    ):
        producer = Mock()
        producer.send.return_value = False
        mock_producer_cls.return_value = producer

        uploaded_file = SimpleUploadedFile(
            "data.csv",
            b"id,name\n1,Alice\n",
            content_type="text/csv",
        )
        response = self.client.post(self.upload_url, {"file": uploaded_file})

        self.assertEqual(response.status_code, 503)
        self.assertIn("failed to publish", response.json().get("message", "").lower())
        self.assertEqual(producer.send.call_count, 2)
        mock_surreal.return_value.insert.assert_called_once()
