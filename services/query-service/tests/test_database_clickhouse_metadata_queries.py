from unittest.mock import Mock

from database.utils import ClickHouseClient, quote_clickhouse_string


def test_clickhouse_string_literal_uses_sql_quotes_and_escapes_content():
    assert quote_clickhouse_string("etl") == "'etl'"
    assert quote_clickhouse_string("a'b\\c") == "'a\\'b\\\\c'"


def test_table_exists_uses_string_literals_not_identifier_quotes():
    client = ClickHouseClient()
    client.execute_query = Mock(return_value={"success": True, "data": "1"})

    result = client.table_exists("etl", "sales")

    assert result == {"success": True, "exists": True}
    query = client.execute_query.call_args.args[0]
    assert "database = 'etl'" in query
    assert "name = 'sales'" in query


def test_table_listing_uses_a_clickhouse_string_literal():
    client = ClickHouseClient()
    client.execute_query = Mock(
        return_value={"success": True, "data": '{"name":"sales"}\n'}
    )

    result = client.get_all_tables("etl")

    assert result == {"success": True, "tables": ["sales"]}
    assert "database = 'etl'" in client.execute_query.call_args.args[0]
