"""
Integration tests for silver layer writes using real ClickHouse.
"""
import os
import sys
from uuid import uuid4

import pytest
from clickhouse_driver import Client

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'shared'))

from loader_logic import LoaderLogic


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
def test_silver_layer_batch_insert():
    host = os.getenv("CLICKHOUSE_HOST", "localhost")
    port = int(os.getenv("CLICKHOUSE_PORT", 9000))
    database = f"etl_silver_test_{uuid4().hex[:8]}"

    init_client = Client(host=host, port=port)
    init_client.execute(f"CREATE DATABASE IF NOT EXISTS {database}")

    loader = LoaderLogic({
        "host": host,
        "port": port,
        "database": database,
    })

    table_name = f"silver_test_{uuid4().hex[:8]}"
    columns = {
        "_row_id": "String",
        "_batch_id": "String",
        "_cleaned_at": "String",
        "_quality_score": "Float32",
        "name": "String",
        "age": "String",
    }

    loader.client.create_table(table_name, columns)

    rows = [
        {
            "_row_id": str(uuid4()),
            "_batch_id": "batch_1",
            "_cleaned_at": "2026-02-22T00:00:00Z",
            "_quality_score": 0.95,
            "name": "Alice",
            "age": "30",
        },
        {
            "_row_id": str(uuid4()),
            "_batch_id": "batch_1",
            "_cleaned_at": "2026-02-22T00:00:00Z",
            "_quality_score": 0.90,
            "name": "Bob",
            "age": "25",
        },
    ]

    inserted = loader.load_batch(table_name, rows, batch_size=100)
    assert inserted == 2

    client = Client(host=host, port=port, database=database)
    count = client.execute(f"SELECT COUNT(*) FROM {table_name}")[0][0]
    assert count == 2

    client.execute(f"DROP TABLE IF EXISTS {table_name}")
    client.execute(f"DROP DATABASE IF EXISTS {database}")
