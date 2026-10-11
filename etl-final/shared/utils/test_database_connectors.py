import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from shared.connectors import (
    ConnectorError, connector_registry, normalize_snapshot_row, safe_connector_error,
)
from shared.connectors.core import InformationSchemaConnector
from shared.security.destination_policy import DestinationPolicyError


def test_capabilities_are_registry_backed_and_snapshot_only():
    result = connector_registry.capabilities()
    assert result["mode"] == "snapshot"
    assert [item["id"] for item in result["connectors"]] == [
        "postgres", "mysql", "mariadb", "mssql", "oracle", "sqlite", "clickhouse"
    ]
    assert all(item["capabilities"]["snapshot_extraction"] for item in result["connectors"])
    assert all(not item["capabilities"]["cdc"] for item in result["connectors"])


@pytest.mark.parametrize(
    ("engine", "identifier", "expected"),
    [
        ("postgres", 'Sales "Data"', '"Sales ""Data"""'),
        ("mysql", "order`history", "`order``history`"),
        ("mariadb", "group", "`group`"),
        ("mssql", "Sales]Data", "[Sales]]Data]"),
        ("oracle", "user", '"user"'),
        ("sqlite", "Sales Data", '"Sales Data"'),
        ("clickhouse", "order", '"order"'),
    ],
)
def test_identifier_quoting(engine, identifier, expected):
    assert connector_registry.get(engine).quote_identifier(identifier) == expected


def test_dialect_specific_snapshot_queries():
    mssql, params = connector_registry.get("mssql").build_snapshot_query(
        "dbo", "order", order_by="id", offset=20, limit=10
    )
    assert "[dbo].[order]" in mssql
    assert "OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY" in mssql
    assert params == ()

    clickhouse, params = connector_registry.get("clickhouse").build_snapshot_query(
        "analytics", "events", order_by="id", limit=1000, last_pk=1000
    )
    assert 'WHERE "id" > %(last_pk)s' in clickhouse
    assert params == {"last_pk": 1000}

    oracle, params = connector_registry.get("oracle").build_snapshot_query(
        "APP", "group", order_by="ID", offset=5, limit=25
    )
    assert '"APP"."group"' in oracle
    assert "OFFSET 5 ROWS FETCH NEXT 25 ROWS ONLY" in oracle
    assert params == ()


def test_information_schema_labels_are_case_insensitive():
    assert InformationSchemaConnector._information_schema_row({
        "TABLE_SCHEMA": "p1db", "TABLE_NAME": "Sales Data", "TABLE_TYPE": "BASE TABLE"
    }) == {
        "table_schema": "p1db", "table_name": "Sales Data", "table_type": "BASE TABLE"
    }


def test_information_schema_primary_key_join_is_scoped_to_the_table():
    cursor = Mock()
    cursor.description = [("column_name",), ("data_type",)]
    cursor.fetchall.side_effect = [
        [{"column_name": "id", "data_type": "bigint", "is_nullable": "NO", "ordinal_position": 1}],
        [{"column_name": "id"}],
    ]
    connection = Mock()
    connection.cursor.return_value = cursor

    result = connector_registry.get("mysql").inspect_table(connection, "p1r_source", "customers")

    assert result["primary_key"] == ["id"]
    assert "tc.table_name = kcu.table_name" in cursor.execute.call_args_list[1].args[0]


def test_postgres_primary_key_discovery_works_for_select_only_roles(monkeypatch):
    monkeypatch.setattr(
        InformationSchemaConnector,
        "inspect_table",
        lambda self, connection, schema, table: {
            "schema": schema,
            "name": table,
            "columns": [{"column_name": "id"}],
            "primary_key": [],
        },
    )
    cursor = Mock()
    cursor.description = [("column_name",)]
    cursor.fetchall.return_value = [{"column_name": "id"}]
    connection = Mock()
    connection.cursor.return_value = cursor

    result = connector_registry.get("postgres").inspect_table(
        connection, "company_data", "customers"
    )

    assert result["primary_key"] == ["id"]
    assert "pg_catalog.pg_index" in cursor.execute.call_args.args[0]


def test_mariadb_primary_key_discovery_falls_back_to_column_flags(monkeypatch):
    monkeypatch.setattr(
        InformationSchemaConnector,
        "inspect_table",
        lambda self, connection, schema, table: {
            "schema": schema,
            "name": table,
            "columns": [{"column_name": "id"}],
            "primary_key": [],
        },
    )
    cursor = Mock()
    cursor.description = [("column_name",)]
    cursor.fetchall.return_value = [{"column_name": "id"}]
    connection = Mock()
    connection.cursor.return_value = cursor

    result = connector_registry.get("mariadb").inspect_table(
        connection, "p1r_source", "customers"
    )

    assert result["primary_key"] == ["id"]
    assert "column_key = 'PRI'" in cursor.execute.call_args.args[0]


def test_sql_server_driver_construction_requires_ca_for_encryption(monkeypatch):
    driver = SimpleNamespace(connect=Mock(return_value=object()))
    monkeypatch.setitem(sys.modules, "pytds", driver)
    connector = connector_registry.get("mssql")
    base = {
        "resolved_host": "203.0.113.5", "port": 1433, "database": "sales",
        "username": "reader", "password": "secret", "connect_timeout": 10,
        "read_timeout": 60, "encrypt": True,
    }
    with pytest.raises(ConnectorError) as caught:
        connector.connect(base)
    assert caught.value.code == "INVALID_CONFIGURATION"

    connector.connect({**base, "cafile": "/run/secrets/sqlserver-ca.pem"})
    assert driver.connect.call_args.kwargs["cafile"] == "/run/secrets/sqlserver-ca.pem"
    assert driver.connect.call_args.kwargs["validate_host"] is True


def test_oracle_thin_driver_construction_uses_supported_tcps_arguments(monkeypatch):
    driver = SimpleNamespace(connect=Mock(return_value=object()))
    monkeypatch.setitem(sys.modules, "oracledb", driver)
    connector = connector_registry.get("oracle")
    connector.connect({
        "resolved_host": "203.0.113.6", "port": 1521, "database": "FREEPDB1",
        "service_name": "FREEPDB1", "username": "reader", "password": "secret",
        "connect_timeout": 10, "read_timeout": 60, "tls": True,
        "wallet_location": "/run/secrets/oracle-wallet",
    })
    kwargs = driver.connect.call_args.kwargs
    assert kwargs["protocol"] == "tcps"
    assert kwargs["service_name"] == "FREEPDB1"
    assert kwargs["wallet_location"] == "/run/secrets/oracle-wallet"

def test_sqlite_real_discovery_introspection_and_chunking(tmp_path, monkeypatch):
    token = "sqlite_42_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.db"
    path = tmp_path / token
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE "Sales Data" (id INTEGER PRIMARY KEY, name TEXT, amount DECIMAL(18,2), note TEXT NULL)')
    connection.executemany('INSERT INTO "Sales Data" VALUES (?, ?, ?, ?)', [
        (1, "Málaga", "10.25", None),
        (2, "دمشق", "999.99", "ok"),
        (3, "東京", "0.01", None),
    ])
    connection.commit()
    connection.close()
    monkeypatch.setenv("ETL_SQLITE_ROOT", str(tmp_path))

    connector = connector_registry.get("sqlite")
    config = {"sqlite_token": token, "workspace_id": 42}
    assert connector.test_connection(config)["success"] is True
    discovered = connector.discover(config, table="Sales Data")
    assert discovered["tables"] == [{"schema": None, "name": "Sales Data", "type": "TABLE"}]
    assert discovered["table"]["primary_key"] == ["id"]
    assert [column["column_name"] for column in discovered["table"]["columns"]] == ["id", "name", "amount", "note"]

    db = connector.connect(connector.validate_configuration(config))
    try:
        chunks = list(connector.iter_rows(db, None, "Sales Data", chunk_size=2, order_by="id"))
    finally:
        db.close()
    assert [len(chunk) for chunk in chunks] == [2, 1]
    assert chunks[1][0]["name"] == "東京"
    assert chunks[0][0]["note"] is None


def test_sqlite_token_is_workspace_scoped(tmp_path, monkeypatch):
    token = "sqlite_7_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.db"
    (tmp_path / token).write_bytes(b"SQLite format 3\x00")
    monkeypatch.setenv("ETL_SQLITE_ROOT", str(tmp_path))
    with pytest.raises(ConnectorError) as caught:
        connector_registry.get("sqlite").validate_configuration({"sqlite_token": token, "workspace_id": 8})
    assert caught.value.code == "PERMISSION_DENIED"


def test_password_is_never_reflected_by_safe_error():
    secret = "super-secret-password"
    error = safe_connector_error(RuntimeError(f"authentication failed password={secret}"))
    assert error.code == "AUTHENTICATION_FAILED"
    assert secret not in error.message


@pytest.mark.parametrize(
    ("driver_message", "expected"),
    [
        ("connection to server failed: Connection refused (errno 111)", "CONNECTION_REFUSED"),
        ("could not translate host name: Name or service not known", "DNS_RESOLUTION_FAILED"),
        ("SSL certificate verify failed", "TLS_ERROR"),
    ],
)
def test_driver_failures_have_stable_safe_codes(driver_message, expected):
    error = safe_connector_error(RuntimeError(driver_message))
    assert error.code == expected
    assert driver_message not in error.message


def test_destination_resolution_failure_has_dns_code():
    error = safe_connector_error(DestinationPolicyError("Database destination could not be resolved."))
    assert error.code == "DNS_RESOLUTION_FAILED"


@pytest.mark.parametrize(
    ("driver_error", "expected"),
    [
        (RuntimeError(1045, "Access denied"), "AUTHENTICATION_FAILED"),
        (RuntimeError(1044, "Access denied to database"), "PERMISSION_DENIED"),
        (RuntimeError(1049, "Unknown database"), "DATABASE_NOT_FOUND"),
    ],
)
def test_numeric_driver_codes_disambiguate_safe_failures(driver_error, expected):
    assert safe_connector_error(driver_error).code == expected


def test_server_configuration_enforces_destination_policy(monkeypatch):
    def blocked(host, port):
        raise ConnectorError("DESTINATION_NOT_ALLOWED", "blocked")

    monkeypatch.setattr("shared.connectors.core.validate_destination", blocked)
    with pytest.raises(ConnectorError) as caught:
        connector_registry.get("postgres").validate_configuration({
            "host": "127.0.0.1", "port": 5432, "database": "app",
            "username": "reader", "password": "secret",
        })
    assert caught.value.code == "DESTINATION_NOT_ALLOWED"


def test_snapshot_value_normalization_preserves_precision_and_binary_data():
    row = normalize_snapshot_row({
        "amount": Decimal("12345678901234567890.1234"),
        "created_at": datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
        "identifier": UUID("12345678-1234-5678-1234-567812345678"),
        "payload": b"\x00\xff",
        "metadata": {"enabled": True},
        "nullable": None,
    })
    assert row["amount"] == "12345678901234567890.1234"
    assert row["created_at"] == "2026-01-02T03:04:00+00:00"
    assert row["identifier"] == "12345678-1234-5678-1234-567812345678"
    assert row["payload"] == "base64:AP8="
    assert row["metadata"] == {"enabled": True}
    assert row["nullable"] is None
