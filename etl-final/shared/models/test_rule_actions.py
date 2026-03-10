"""
Unit tests for rule action helpers.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from rule_actions import (
    trim_strings,
    trim_field,
    uppercase_strings,
    uppercase_field,
    lowercase_strings,
    lowercase_field,
    normalize_whitespace,
    normalize_whitespace_field,
    cast_to_int,
    cast_to_float,
    cast_to_bool,
    cast_to_date,
    regex_replace,
    regex_extract,
    remove_field,
    remove_null_fields,
    rename_field,
    copy_field,
    replace_value,
    default_value,
    compose_actions,
)


def test_trim_strings():
    row = {"name": "  John  ", "age": 30}
    assert trim_strings(row) == {"name": "John", "age": 30}


def test_trim_field():
    action = trim_field("name")
    assert action({"name": "  Jane  ", "city": "NYC"}) == {"name": "Jane", "city": "NYC"}


def test_uppercase_strings():
    row = {"name": "john", "age": 30}
    assert uppercase_strings(row) == {"name": "JOHN", "age": 30}


def test_uppercase_field():
    action = uppercase_field("name")
    assert action({"name": "john", "age": 30}) == {"name": "JOHN", "age": 30}


def test_lowercase_strings():
    row = {"name": "JOHN", "age": 30}
    assert lowercase_strings(row) == {"name": "john", "age": 30}


def test_lowercase_field():
    action = lowercase_field("name")
    assert action({"name": "JOHN", "age": 30}) == {"name": "john", "age": 30}


def test_normalize_whitespace():
    row = {"name": "John   Doe", "city": "New\tYork"}
    assert normalize_whitespace(row) == {"name": "John Doe", "city": "New York"}


def test_normalize_whitespace_field():
    action = normalize_whitespace_field("name")
    assert action({"name": "John   Doe", "city": "NYC"}) == {"name": "John Doe", "city": "NYC"}


def test_cast_to_int_success():
    action = cast_to_int("age")
    assert action({"age": "42"})["age"] == 42


def test_cast_to_int_on_error_null():
    action = cast_to_int("age", on_error="null")
    assert action({"age": "not-a-number"})["age"] is None


def test_cast_to_float_success():
    action = cast_to_float("price")
    assert action({"price": "19.99"})["price"] == 19.99


def test_cast_to_bool_success():
    action = cast_to_bool("active")
    assert action({"active": "yes"})["active"] is True
    assert action({"active": "no"})["active"] is False


def test_cast_to_date_success():
    action = cast_to_date("birth_date", date_format="%Y-%m-%d")
    assert action({"birth_date": "1990-01-15"})["birth_date"] == date(1990, 1, 15)


def test_cast_to_date_on_error_null():
    action = cast_to_date("birth_date", on_error="null")
    assert action({"birth_date": "invalid"})["birth_date"] is None


def test_regex_replace():
    action = regex_replace("phone", r"[^0-9]", "")
    assert action({"phone": "(555) 123-4567"})["phone"] == "5551234567"


def test_regex_extract_match():
    action = regex_extract("email", r"([^@]+)@", group=1)
    assert action({"email": "john@example.com"})["email"] == "john"


def test_regex_extract_no_match_null():
    action = regex_extract("email", r"([^@]+)@", group=1, on_no_match="null")
    assert action({"email": "invalid"})["email"] is None


def test_regex_extract_no_match_raises():
    action = regex_extract("email", r"([^@]+)@", group=1, on_no_match="raise")
    with pytest.raises(ValueError):
        action({"email": "invalid"})


def test_remove_field():
    action = remove_field("temp")
    assert action({"temp": "x", "keep": "y"}) == {"keep": "y"}


def test_remove_null_fields():
    assert remove_null_fields({"name": "John", "age": None}) == {"name": "John"}


def test_rename_field():
    action = rename_field("first_name", "given_name")
    assert action({"first_name": "John", "last_name": "Doe"}) == {"given_name": "John", "last_name": "Doe"}


def test_copy_field():
    action = copy_field("name", "full_name")
    row = {"name": {"first": "John"}}
    result = action(row)
    assert result["full_name"] == {"first": "John"}
    assert result["full_name"] is not row["name"]


def test_replace_value():
    action = replace_value("status", "N/A", None)
    assert action({"status": "N/A"})["status"] is None


def test_default_value():
    action = default_value("country", "USA")
    assert action({"name": "John"})["country"] == "USA"


def test_compose_actions_order():
    action = compose_actions(
        trim_field("name"),
        uppercase_field("name"),
    )
    assert action({"name": "  john  "})["name"] == "JOHN"
