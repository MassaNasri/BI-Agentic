from unittest.mock import Mock

from shared.utils.type_mapper import TypeMapper


def test_infer_schema_from_bronze_uses_safe_identifiers_in_queries():
    client = Mock()
    client.execute.side_effect = [
        [("a b", "String"), ("1evil", "String"), ("_meta", "String")],
        [("42", "x")],
    ]
    mapper = TypeMapper()

    mapping = mapper.infer_schema_from_bronze("bad table; DROP", sample_size=10, clickhouse_client=client)

    assert "a_b" in mapping
    assert "c_1evil" in mapping
    describe_query = client.execute.call_args_list[0][0][0]
    sample_query = client.execute.call_args_list[1][0][0]
    assert describe_query == "DESCRIBE TABLE `bad_table_DROP`"
    assert "SELECT `a_b`, `c_1evil`" in sample_query
    assert "FROM `bad_table_DROP`" in sample_query
