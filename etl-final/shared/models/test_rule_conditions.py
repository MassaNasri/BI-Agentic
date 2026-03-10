"""
Unit tests for rule condition helpers.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from rule_conditions import (
    always_true,
    always_false,
    field_exists,
    field_not_exists,
    field_is_null,
    field_is_not_null,
    field_type,
    field_value_equals,
    field_value_in,
    field_value_matches,
    field_value_contains,
    field_value_range,
    all_fields_exist,
    any_field_exists,
    and_conditions,
    or_conditions,
    not_condition,
    custom_condition,
)


def test_always_true_false():
    assert always_true({"a": 1}) is True
    assert always_false({"a": 1}) is False


def test_field_exists_not_exists():
    cond = field_exists("email")
    assert cond({"email": "a@b.com"}) is True
    assert cond({"name": "John"}) is False

    cond = field_not_exists("email")
    assert cond({"name": "John"}) is True
    assert cond({"email": "a@b.com"}) is False


def test_field_is_null_not_null():
    assert field_is_null("middle")({"middle": None}) is True
    assert field_is_null("middle")({"middle": "x"}) is False
    assert field_is_not_null("middle")({"middle": "x"}) is True
    assert field_is_not_null("middle")({"middle": None}) is False


def test_field_type():
    assert field_type("age", int)({"age": 30}) is True
    assert field_type("age", int)({"age": "30"}) is False


def test_field_value_equals_in():
    assert field_value_equals("status", "active")({"status": "active"}) is True
    assert field_value_equals("status", "active")({"status": "inactive"}) is False

    cond = field_value_in("status", {"active", "pending"})
    assert cond({"status": "active"}) is True
    assert cond({"status": "inactive"}) is False


def test_field_value_matches_contains():
    cond = field_value_matches("email", r"^[^@]+@[^@]+\.[^@]+$")
    assert cond({"email": "john@example.com"}) is True
    assert cond({"email": "invalid"}) is False

    cond = field_value_contains("desc", "urgent")
    assert cond({"desc": "urgent item"}) is True
    assert cond({"desc": "normal item"}) is False


def test_field_value_range():
    cond = field_value_range("age", min_value=18, max_value=65)
    assert cond({"age": 30}) is True
    assert cond({"age": 10}) is False
    assert cond({"age": 70}) is False


def test_all_any_fields_exist():
    cond = all_fields_exist(["a", "b"])
    assert cond({"a": 1, "b": 2}) is True
    assert cond({"a": 1}) is False

    cond = any_field_exists(["a", "b"])
    assert cond({"a": 1}) is True
    assert cond({"c": 3}) is False


def test_and_or_not_conditions():
    cond = and_conditions(field_exists("a"), field_exists("b"))
    assert cond({"a": 1, "b": 2}) is True
    assert cond({"a": 1}) is False

    cond = or_conditions(field_exists("a"), field_exists("b"))
    assert cond({"a": 1}) is True
    assert cond({"c": 3}) is False

    cond = not_condition(field_exists("a"))
    assert cond({"a": 1}) is False
    assert cond({"b": 2}) is True


def test_custom_condition_safe():
    def predicate(row):
        return row["missing"] > 0

    cond = custom_condition(predicate, safe=True)
    assert cond({"a": 1}) is False

    cond_unsafe = custom_condition(predicate, safe=False)
    try:
        cond_unsafe({"a": 1})
        raised = False
    except Exception:
        raised = True
    assert raised is True
