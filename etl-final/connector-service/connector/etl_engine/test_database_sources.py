import os
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
                "integration_source_id": "f462c858-f0dd-4e7e-b484-495e21f4ef02",
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
    assert event["integration_source_id"] == "f462c858-f0dd-4e7e-b484-495e21f4ef02"
    assert event["source_id"] == str(event["dataset_id"])


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


@override_settings(ETL_INTERNAL_API_KEY="internal-test-key")
def test_snapshot_rejects_invalid_integration_source_id():
    response = APIClient().post(
        "/api/databases/snapshot/",
        {"integration_source_id": "other-workspace-source", "engine": "postgres", "configuration": {}, "tables": [{"name": "orders"}]},
        format="json",
        **_headers(),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CONFIGURATION"


@override_settings(ETL_INTERNAL_API_KEY="internal-test-key")
def test_v2_snapshot_event_has_opaque_ref_and_no_reusable_ciphertext():
    job = uuid4()
    source_id = str(uuid4())
    reference = {
        "source_id": source_id, "workspace_id": 7, "dataset_id": "31",
        "job_id": str(job), "credential_id": str(uuid4()), "credential_version": 2,
    }
    connector = Mock(key="postgres")
    connector.validate_configuration.return_value = {
        "host": "db.example", "port": 5432, "database": "sales", "username": "reader",
        "password": "plain-secret", "resolved_host": "8.8.8.8", "workspace_id": 7,
    }
    connector.discover.return_value = {"tables": [{"schema": "public", "name": "orders"}]}
    producer = Mock()
    producer.send.return_value = True
    with patch("etl_engine.views.resolve_source_execution", return_value=(
        "postgres", {"host": "db.example", "password": "plain-secret"}, "direct_secure_internet", 3,
    )), patch("etl_engine.views.connector_registry.get", return_value=connector), patch(
        "etl_engine.views.KafkaMessageProducer", return_value=producer,
    ):
        response = APIClient().post(
            "/api/databases/snapshot/",
            {"credential_ref": reference, "integration_source_id": source_id,
             "tables": [{"schema": "public", "name": "orders"}]},
            format="json", **_headers(job=job),
        )
    assert response.status_code == 202
    event = producer.send.call_args.args[1]
    assert event["contract_version"] == 2
    assert event["credential_ref"] == reference
    assert event["configuration_version"] == 3
    assert "password" not in event["configuration"]
    assert "plain-secret" not in str(event)
    assert "_password_encrypted" not in str(event)


@override_settings(ETL_INTERNAL_API_KEY="internal-test-key")
def test_production_rejects_both_legacy_database_publishers_before_kafka():
    with patch.dict(os.environ, {"APP_ENV": "production"}), patch(
        "etl_engine.views.KafkaMessageProducer"
    ) as producer:
        snapshot = APIClient().post(
            "/api/databases/snapshot/",
            {"engine": "postgres", "configuration": {"password": "synthetic-test-only"},
             "tables": [{"schema": "public", "name": "orders"}]},
            format="json", **_headers(),
        )
        legacy = APIClient().post(
            "/api/connect-db/", {"db_type": "postgres", "password": "synthetic-test-only"},
            format="json", **_headers(),
        )
    assert snapshot.status_code == 403
    assert legacy.status_code == 410
    producer.assert_not_called()


class DatabaseSourceTests(SimpleTestCase):
    def test_capabilities(self):
        test_capabilities_endpoint_is_registry_backed()

    def test_encrypted_snapshot_event(self):
        test_snapshot_encrypts_password_and_publishes_selected_tables_only()

    def test_invalid_integration_source_id(self):
        test_snapshot_rejects_invalid_integration_source_id()

    def test_scope_required(self):
        test_database_control_endpoint_requires_tenant_scope()

    def test_v2_event(self):
        test_v2_snapshot_event_has_opaque_ref_and_no_reusable_ciphertext()

    def test_production_v1_publishers(self):
        test_production_rejects_both_legacy_database_publishers_before_kafka()
