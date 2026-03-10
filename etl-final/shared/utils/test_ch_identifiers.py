import pytest

from shared.utils.ch_identifiers import (
    quote_identifier,
    quote_table_name,
    sanitize_column_name,
    sanitize_identifier,
    sanitize_identifier_map,
    sanitize_table_name,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("simple_name", "simple_name"),
        (" leading and trailing ", "leading_and_trailing"),
        ("with space", "with_space"),
        ("a); DROP TABLE x;--", "a_DROP_TABLE_x"),
        ("1abc", "c_1abc"),
        ("", "column"),
        ("اسم", "column"),
    ],
)
def test_sanitize_identifier_edge_cases(raw, expected):
    assert sanitize_identifier(raw, prefix="c", fallback="column") == expected


def test_sanitize_table_name_supports_dotted_and_normalizes_parts():
    assert sanitize_table_name("etl.orders") == "etl.orders"
    assert sanitize_table_name("etl.bad table") == "etl.bad_table"
    assert sanitize_table_name("1db.2table") == "t_1db.t_2table"


def test_quote_identifier_escapes_backticks():
    assert quote_identifier("col`name") == "`col``name`"


def test_quote_table_name_quotes_each_part():
    assert quote_table_name("etl.orders") == "`etl`.`orders`"
    assert quote_table_name("bad table") == "`bad_table`"


def test_sanitize_identifier_map_handles_collisions_stably():
    mapping = sanitize_identifier_map(["a b", "a-b", "a_b"], prefix="c")
    assert mapping["a b"] == "a_b"
    assert mapping["a-b"] == "a_b_2"
    assert mapping["a_b"] == "a_b_3"
