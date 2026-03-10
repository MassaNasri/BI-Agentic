from unittest.mock import Mock

from shared.utils.clickhouse_schemas import ClickHouseSchemaManager


def test_table_exists_uses_quoted_sanitized_identifier():
    client = Mock()
    client.execute.return_value = [(1,)]
    manager = ClickHouseSchemaManager(client)

    ok = manager.table_exists("bad table;DROP")

    assert ok is True
    query = client.execute.call_args[0][0]
    assert query == "EXISTS TABLE `bad_table_DROP`"


def test_get_table_schema_uses_quoted_sanitized_identifier():
    client = Mock()
    client.execute.return_value = [("_id", "String")]
    manager = ClickHouseSchemaManager(client)

    schema = manager.get_table_schema("etl.bad table")

    assert schema == [("_id", "String")]
    query = client.execute.call_args[0][0]
    assert query == "DESCRIBE TABLE `etl`.`bad_table`"


def test_create_quarantine_table_sanitizes_table_name():
    client = Mock()
    manager = ClickHouseSchemaManager(client)

    ok = manager.create_quarantine_table("q; DROP TABLE x; --")

    assert ok is True
    query = client.execute.call_args[0][0]
    assert "CREATE TABLE IF NOT EXISTS `q_DROP_TABLE_x`" in query
