import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")
os.environ.setdefault("APP_ENV", "test")

import django

django.setup()

from database.serializers import DatabaseSerializer
from database.utils import cleanup_database


def test_serializer_exposes_imported_tables_without_physical_names():
    database = SimpleNamespace(
        id=31,
        manager=11,
        manager_name="Manager",
        manager_email="manager@example.com",
        filename="postgres:public.orders",
        file_size=0,
        file_path="",
        source_kind="database",
        source_engine="postgres",
        source_tables=[{
            "id": "safe-token",
            "schema": "public",
            "name": "orders",
            "destination_table": "w7_d31_sales_public_orders",
            "status": "completed",
            "row_count": 8,
            "column_count": 4,
        }],
        row_count=8,
        column_count=4,
        columns_schema={},
        workspace_id=7,
        clickhouse_table_name="w7_d31_sales_public_orders",
        clickhouse_database="etl",
        upload_date="2026-10-11T00:00:00Z",
        etl_status="completed",
        etl_message="done",
    )
    payload = DatabaseSerializer(database).data
    assert payload["source_tables"] == [{
        "id": "safe-token",
        "schema": "public",
        "name": "orders",
        "status": "completed",
        "row_count": 8,
        "column_count": 4,
    }]
    assert "destination_table" not in payload["source_tables"][0]


def test_cleanup_drops_every_imported_destination_once():
    database = SimpleNamespace(
        clickhouse_database="etl",
        clickhouse_table_name="table_one",
        source_tables=[
            {"destination_table": "table_one"},
            {"destination_table": "table_two"},
        ],
    )
    clickhouse = Mock()
    clickhouse.drop_table.return_value = {"success": True}
    with patch("database.utils.ClickHouseClient", return_value=clickhouse):
        result = cleanup_database(database)
    assert result["clickhouse_dropped"] is True
    assert [call.args for call in clickhouse.drop_table.call_args_list] == [
        ("etl", "table_one"),
        ("etl", "table_two"),
    ]
