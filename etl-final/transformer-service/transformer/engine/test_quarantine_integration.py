"""
Integration tests for quarantine behavior using real ClickHouse.
"""
import os
import sys
from uuid import uuid4

import pytest
from clickhouse_driver import Client

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
TRANSFORMER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, TRANSFORMER_DIR)

from shared.models import SchemaContract, FieldDefinition, DataType
from shared.utils.quarantine_manager import QuarantineManager
from engine.transformer_service import TransformerService


def is_clickhouse_available():
    try:
        host = os.getenv("CLICKHOUSE_HOST", "localhost")
        port = int(os.getenv("CLICKHOUSE_PORT", 9000))
        client = Client(host=host, port=port)
        client.execute("SELECT 1")
        return True
    except Exception:
        return False


requires_clickhouse = pytest.mark.skipif(
    not is_clickhouse_available(),
    reason="ClickHouse not available. Set CLICKHOUSE_HOST to run integration tests."
)


@requires_clickhouse
def test_invalid_rows_are_quarantined():
    host = os.getenv("CLICKHOUSE_HOST", "localhost")
    port = int(os.getenv("CLICKHOUSE_PORT", 9000))
    database = f"etl_quarantine_test_{uuid4().hex[:8]}"

    admin_client = Client(host=host, port=port)
    admin_client.execute(f"CREATE DATABASE IF NOT EXISTS {database}")

    client = Client(host=host, port=port, database=database)
    quarantine_manager = QuarantineManager(client)

    schema = SchemaContract(
        schema_id="user_schema",
        version="1.0.0",
        fields=[
            FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
            FieldDefinition(name="email", type=DataType.STRING, nullable=False),
        ],
    )

    service = TransformerService(
        quarantine_manager=quarantine_manager,
        drop_invalid=False,
    )

    messages = [
        {
            "source": "users",
            "batch_id": "batch_1",
            "data": {"id": 1, "email": "valid@example.com"},
        },
        {
            "source": "users",
            "batch_id": "batch_1",
            "data": {"id": None, "email": None},
        },
    ]

    results, stats = service.process_batch(messages, schema_contract=schema)

    assert stats["quarantined"] == 1
    assert stats["failed"] >= 1

    quarantined_rows = quarantine_manager.list_quarantined(limit=10)
    assert len(quarantined_rows) == 1
    assert quarantined_rows[0]["_source_id"] == "users"

    success_rows = [r for r in results if r["status"] == "success"]
    failed_rows = [r for r in results if r["status"] != "success"]

    assert len(success_rows) == 1
    assert len(failed_rows) == 1
    assert failed_rows[0]["clean_message"] is None

    client.execute("DROP TABLE IF EXISTS quarantine")
    client.execute(f"DROP DATABASE IF EXISTS {database}")
