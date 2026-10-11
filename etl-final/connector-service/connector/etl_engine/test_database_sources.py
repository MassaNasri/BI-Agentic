from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient


def _headers(workspace="7", dataset="31", job=None):
    return {
        "HTTP_X_INTERNAL_SERVICE": "query-service",
        "HTTP_X_INTERNAL_API_KEY": "internal-test-key",
        "HTTP_X_WORKSPACE_ID": workspace,
        "HTTP_X_DATASET_ID": dataset,
        "HTTP_X_INGESTION_JOB_ID": str(job or uuid4()),
    }


@override_settings(ETL_INTERNAL_API_KEY="internal-test-key")
def test_capabilities_endpoint_is_registry_backed():
    response = APIClient().get("/api/databases/capabilities/", **{
        "HTTP_X_INTERNAL_SERVICE": "query-service",
        "HTTP_X_INTERNAL_API_KEY": "internal-test-key",
    })
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]["connectors"]] == [
        "postgres", "mysql", "mariadb", "mssql", "oracle", "sqlite", "clickhouse"
    ]


@override_settings(ETL_INTERNAL_API_KEY="internal-test-key")
def test_snapshot_encrypts_password_and_publishes_selected_tables_only():
    connector = Mock(key="postgres")
    connector.validate_configuration.return_value = {
        "db_type": "postgres", "host": "db.example", "port": 5432,
        "database": "sales", "username": "reader", "password": "plain-secret",
        "resolved_host": "203.0.113.5", "workspace_id": 7,
    }
    connector.discover.return_value = {
        "tables": [{"schema": "public", "name": "order", "type": "BASE TABLE"}]
    }
    encryption = Mock()
    encryption.encrypt.return_value = "encrypted-token"
    producer = Mock()
    producer.send.return_value = True

    with patch("etl_engine.views.connector_registry.get", return_value=connector), patch(
        "etl_engine.views.get_encryption_instance", return_value=encryption
    ), patch("etl_engine.views.KafkaMessageProducer", return_value=producer):
        response = APIClient().post(
            "/api/databases/snapshot/",
            {
                "engine": "postgres",
                "configuration": {
                    "host": "db.example", "port": 5432, "database": "sales",
                    "username": "reader", "password": "plain-secret",
                },
                "tables": [{"schema": "public", "name": "order"}],
            },
            format="json",
            **_headers(),
        )

    assert response.status_code == 202
    event = producer.send.call_args.args[1]
    assert event["configuration"]["password"] == "encrypted-token"
    assert "plain-secret" not in str(event)
    assert event["selected_tables"] == [{"schema": "public", "name": "order"}]
    assert event["workspace_id"] == 7


@override_settings(ETL_INTERNAL_API_KEY="internal-test-key")
def test_database_control_endpoint_requires_tenant_scope():
    response = APIClient().post(
        "/api/databases/test/",
        {"engine": "postgres", "configuration": {}},
        format="json",
        HTTP_X_INTERNAL_SERVICE="query-service",
        HTTP_X_INTERNAL_API_KEY="internal-test-key",
    )
    assert response.status_code == 400
    assert "workspace_id" in response.json()


class DatabaseSourceTests(SimpleTestCase):
    def test_capabilities(self):
        test_capabilities_endpoint_is_registry_backed()

    def test_encrypted_snapshot_event(self):
        test_snapshot_encrypts_password_and_publishes_selected_tables_only()

    def test_scope_required(self):
        test_database_control_endpoint_requires_tenant_scope()
