"""
Unit tests for rule type factory functions.

Tests all four rule types (CLEAN, VALIDATE, TRANSFORM, ENRICH) and helper functions.

**Validates: Requirements US-6 (AC 6.1-6.4)**
"""
import pytest
from typing import Dict, Any
from .rule_types import (
    create_clean_rule,
    create_validate_rule,
    create_transform_rule,
    create_enrich_rule,
    create_field_condition,
    create_type_condition,
    create_regex_condition,
)
from .transformation_rule import TransformationRule, RuleType


# ============================================================================
# Test CLEAN Rule Type
# ============================================================================

def test_create_clean_rule_basic():
    """Test creating a basic CLEAN rule."""
    def trim_action(row: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v.strip() if isinstance(v, str) else v for k, v in row.items()}
    
    rule = create_clean_rule(
        rule_id="trim_strings_v1",
        priority=1,
        action=trim_action,
        metadata={"description": "Trim whitespace"}
    )
    
    assert isinstance(rule, TransformationRule)
    assert rule.rule_id == "trim_strings_v1"
    assert rule.rule_type == RuleType.CLEAN
    assert rule.priority == 1
    assert rule.metadata["description"] == "Trim whitespace"


def test_clean_rule_trims_whitespace():
    """Test CLEAN rule actually trims whitespace."""
    def trim_action(row: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v.strip() if isinstance(v, str) else v for k, v in row.items()}
    
    rule = create_clean_rule(
        rule_id="trim_v1",
        priority=1,
        action=trim_action
    )
    
    input_row = {"name": "  John  ", "age": 25}
    result = rule.action(input_row)
    
    assert result["name"] == "John"
    assert result["age"] == 25


def test_clean_rule_removes_nulls():
    """Test CLEAN rule removes null fields."""
    def remove_nulls_action(row: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in row.items() if v is not None}
    
    rule = create_clean_rule(
        rule_id="remove_nulls_v1",
        priority=1,
        action=remove_nulls_action
    )
    
    input_row = {"name": "John", "email": None, "age": 25}
    result = rule.action(input_row)
    
    assert "name" in result
    assert "email" not in result
    assert "age" in result


def test_clean_rule_with_condition():
    """Test CLEAN rule with condition."""
    def trim_action(row: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v.strip() if isinstance(v, str) else v for k, v in row.items()}
    
    rule = create_clean_rule(
        rule_id="trim_v1",
        priority=1,
        action=trim_action,
        condition=lambda row: "name" in row
    )
    
    # Condition is True
    assert rule.condition({"name": "John"}) is True
    
    # Condition is False
    assert rule.condition({"age": 25}) is False


# ============================================================================
# Test VALIDATE Rule Type
# ============================================================================

def test_create_validate_rule_basic():
    """Test creating a basic VALIDATE rule."""
    def validate_email_action(row: Dict[str, Any]) -> Dict[str, Any]:
        if "email" in row and "@" not in row["email"]:
            raise ValueError(f"Invalid email: {row['email']}")
        return row
    
    rule = create_validate_rule(
        rule_id="validate_email_v1",
        priority=10,
        action=validate_email_action,
        metadata={"description": "Validate email format"}
    )
    
    assert isinstance(rule, TransformationRule)
    assert rule.rule_id == "validate_email_v1"
    assert rule.rule_type == RuleType.VALIDATE
    assert rule.priority == 10


def test_validate_rule_passes_valid_data():
    """Test VALIDATE rule passes valid data unchanged."""
    def validate_age_action(row: Dict[str, Any]) -> Dict[str, Any]:
        if "age" in row and not (0 <= row["age"] <= 150):
            raise ValueError(f"Invalid age: {row['age']}")
        return row
    
    rule = create_validate_rule(
        rule_id="validate_age_v1",
        priority=10,
        action=validate_age_action
    )
    
    input_row = {"name": "John", "age": 25}
    result = rule.action(input_row)
    
    # Data should be unchanged
    assert result == input_row


def test_validate_rule_raises_on_invalid_data():
    """Test VALIDATE rule raises exception on invalid data."""
    def validate_age_action(row: Dict[str, Any]) -> Dict[str, Any]:
        if "age" in row and not (0 <= row["age"] <= 150):
            raise ValueError(f"Invalid age: {row['age']}")
        return row
    
    rule = create_validate_rule(
        rule_id="validate_age_v1",
        priority=10,
        action=validate_age_action
    )
    
    input_row = {"name": "John", "age": 200}
    
    with pytest.raises(ValueError, match="Invalid age: 200"):
        rule.action(input_row)


def test_validate_rule_does_not_modify_data():
    """Test VALIDATE rule does not modify data (only validates)."""
    def validate_email_action(row: Dict[str, Any]) -> Dict[str, Any]:
        # Validation should NOT modify data
        if "email" in row and "@" not in row["email"]:
            raise ValueError("Invalid email")
        return row
    
    rule = create_validate_rule(
        rule_id="validate_email_v1",
        priority=10,
        action=validate_email_action
    )
    
    input_row = {"email": "test@example.com", "name": "John"}
    result = rule.action(input_row)
    
    # Should return exact same data
    assert result is input_row or result == input_row


# ============================================================================
# Test TRANSFORM Rule Type
# ============================================================================

def test_create_transform_rule_basic():
    """Test creating a basic TRANSFORM rule."""
    def cast_to_int_action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if "age" in result and isinstance(result["age"], str):
            result["age"] = int(result["age"])
        return result
    
    rule = create_transform_rule(
        rule_id="cast_age_to_int_v1",
        priority=20,
        action=cast_to_int_action,
        metadata={"description": "Cast age to integer"}
    )
    
    assert isinstance(rule, TransformationRule)
    assert rule.rule_id == "cast_age_to_int_v1"
    assert rule.rule_type == RuleType.TRANSFORM
    assert rule.priority == 20


def test_transform_rule_casts_type():
    """Test TRANSFORM rule casts data types."""
    def cast_to_int_action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if "age" in result and isinstance(result["age"], str):
            result["age"] = int(result["age"])
        return result
    
    rule = create_transform_rule(
        rule_id="cast_age_v1",
        priority=20,
        action=cast_to_int_action
    )
    
    input_row = {"name": "John", "age": "25"}
    result = rule.action(input_row)
    
    assert result["age"] == 25
    assert isinstance(result["age"], int)


def test_transform_rule_is_deterministic():
    """Test TRANSFORM rule produces same output for same input."""
    def uppercase_action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if "name" in result and isinstance(result["name"], str):
            result["name"] = result["name"].upper()
        return result
    
    rule = create_transform_rule(
        rule_id="uppercase_name_v1",
        priority=20,
        action=uppercase_action
    )
    
    input_row = {"name": "john"}
    
    # Run multiple times
    result1 = rule.action(input_row)
    result2 = rule.action(input_row)
    result3 = rule.action(input_row)
    
    # Should always produce same result
    assert result1 == result2 == result3
    assert result1["name"] == "JOHN"


def test_transform_rule_converts_format():
    """Test TRANSFORM rule converts data format."""
    def format_phone_action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if "phone" in result:
            # Remove all non-digits
            digits = ''.join(c for c in str(result["phone"]) if c.isdigit())
            # Format as (XXX) XXX-XXXX
            if len(digits) == 10:
                result["phone"] = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        return result
    
    rule = create_transform_rule(
        rule_id="format_phone_v1",
        priority=20,
        action=format_phone_action
    )
    
    input_row = {"phone": "1234567890"}
    result = rule.action(input_row)
    
    assert result["phone"] == "(123) 456-7890"


# ============================================================================
# Test ENRICH Rule Type
# ============================================================================

def test_create_enrich_rule_basic():
    """Test creating a basic ENRICH rule."""
    def add_full_name_action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if "first_name" in row and "last_name" in row:
            result["full_name"] = f"{row['first_name']} {row['last_name']}"
        return result
    
    rule = create_enrich_rule(
        rule_id="add_full_name_v1",
        priority=30,
        action=add_full_name_action,
        metadata={"description": "Add full_name field"}
    )
    
    assert isinstance(rule, TransformationRule)
    assert rule.rule_id == "add_full_name_v1"
    assert rule.rule_type == RuleType.ENRICH
    assert rule.priority == 30


def test_enrich_rule_adds_field():
    """Test ENRICH rule adds new field."""
    def add_full_name_action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if "first_name" in row and "last_name" in row:
            result["full_name"] = f"{row['first_name']} {row['last_name']}"
        return result
    
    rule = create_enrich_rule(
        rule_id="add_full_name_v1",
        priority=30,
        action=add_full_name_action
    )
    
    input_row = {"first_name": "John", "last_name": "Doe"}
    result = rule.action(input_row)
    
    # Original fields preserved
    assert result["first_name"] == "John"
    assert result["last_name"] == "Doe"
    
    # New field added
    assert result["full_name"] == "John Doe"


def test_enrich_rule_adds_calculated_field():
    """Test ENRICH rule adds calculated field."""
    def add_age_group_action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if "age" in row:
            age = row["age"]
            if age < 18:
                result["age_group"] = "minor"
            elif age < 65:
                result["age_group"] = "adult"
            else:
                result["age_group"] = "senior"
        return result
    
    rule = create_enrich_rule(
        rule_id="add_age_group_v1",
        priority=30,
        action=add_age_group_action
    )
    
    input_row = {"name": "John", "age": 25}
    result = rule.action(input_row)
    
    assert result["age"] == 25  # Original preserved
    assert result["age_group"] == "adult"  # New field added


def test_enrich_rule_does_not_replace_existing():
    """Test ENRICH rule augments but doesn't replace existing data."""
    def add_metadata_action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        result["_enriched"] = True
        result["_version"] = "1.0"
        return result
    
    rule = create_enrich_rule(
        rule_id="add_metadata_v1",
        priority=30,
        action=add_metadata_action
    )
    
    input_row = {"name": "John", "age": 25}
    result = rule.action(input_row)
    
    # Original fields preserved
    assert result["name"] == "John"
    assert result["age"] == 25
    
    # New fields added
    assert result["_enriched"] is True
    assert result["_version"] == "1.0"


# ============================================================================
# Test Helper Functions
# ============================================================================

def test_create_field_condition_exists():
    """Test create_field_condition for field existence."""
    condition = create_field_condition("email", field_exists=True)
    
    assert condition({"email": "test@example.com"}) is True
    assert condition({"name": "John"}) is False


def test_create_field_condition_not_exists():
    """Test create_field_condition for field non-existence."""
    condition = create_field_condition("email", field_exists=False)
    
    assert condition({"email": "test@example.com"}) is False
    assert condition({"name": "John"}) is True


def test_create_type_condition():
    """Test create_type_condition."""
    condition = create_type_condition("age", str)
    
    assert condition({"age": "25"}) is True
    assert condition({"age": 25}) is False
    assert condition({"name": "John"}) is False


def test_create_type_condition_multiple_types():
    """Test create_type_condition with different types."""
    str_condition = create_type_condition("value", str)
    int_condition = create_type_condition("value", int)
    float_condition = create_type_condition("value", float)
    
    assert str_condition({"value": "test"}) is True
    assert int_condition({"value": 42}) is True
    assert float_condition({"value": 3.14}) is True
    
    assert str_condition({"value": 42}) is False
    assert int_condition({"value": "test"}) is False


def test_create_regex_condition():
    """Test create_regex_condition."""
    email_condition = create_regex_condition("email", r"^[^@]+@[^@]+\.[^@]+$")
    
    assert email_condition({"email": "test@example.com"}) is True
    assert email_condition({"email": "invalid"}) is False
    assert email_condition({"name": "John"}) is False


def test_create_regex_condition_phone():
    """Test create_regex_condition with phone pattern."""
    phone_condition = create_regex_condition("phone", r"^\d{3}-\d{3}-\d{4}$")
    
    assert phone_condition({"phone": "123-456-7890"}) is True
    assert phone_condition({"phone": "1234567890"}) is False
    assert phone_condition({"phone": "invalid"}) is False


# ============================================================================
# Test Rule Priority and Ordering
# ============================================================================

def test_rules_have_different_priorities():
    """Test that different rule types can have different priorities."""
    clean_rule = create_clean_rule("clean_v1", priority=1, action=lambda r: r)
    validate_rule = create_validate_rule("validate_v1", priority=10, action=lambda r: r)
    transform_rule = create_transform_rule("transform_v1", priority=20, action=lambda r: r)
    enrich_rule = create_enrich_rule("enrich_v1", priority=30, action=lambda r: r)
    
    assert clean_rule.priority < validate_rule.priority
    assert validate_rule.priority < transform_rule.priority
    assert transform_rule.priority < enrich_rule.priority


def test_rules_can_be_sorted_by_priority():
    """Test that rules can be sorted by priority."""
    rules = [
        create_enrich_rule("enrich_v1", priority=30, action=lambda r: r),
        create_clean_rule("clean_v1", priority=1, action=lambda r: r),
        create_transform_rule("transform_v1", priority=20, action=lambda r: r),
        create_validate_rule("validate_v1", priority=10, action=lambda r: r),
    ]
    
    sorted_rules = sorted(rules, key=lambda r: r.priority)
    
    assert sorted_rules[0].rule_type == RuleType.CLEAN
    assert sorted_rules[1].rule_type == RuleType.VALIDATE
    assert sorted_rules[2].rule_type == RuleType.TRANSFORM
    assert sorted_rules[3].rule_type == RuleType.ENRICH


# ============================================================================
# Test Rule Metadata
# ============================================================================

def test_rule_metadata_is_stored():
    """Test that rule metadata is properly stored."""
    metadata = {
        "description": "Test rule",
        "version": "1.0",
        "author": "test_user",
        "created_at": "2024-01-01"
    }
    
    rule = create_clean_rule(
        rule_id="test_v1",
        priority=1,
        action=lambda r: r,
        metadata=metadata
    )
    
    assert rule.metadata == metadata
    assert rule.metadata["description"] == "Test rule"
    assert rule.metadata["version"] == "1.0"


def test_rule_metadata_defaults_to_empty_dict():
    """Test that rule metadata defaults to empty dict if not provided."""
    rule = create_clean_rule(
        rule_id="test_v1",
        priority=1,
        action=lambda r: r
    )
    
    assert rule.metadata == {}


# ============================================================================
# Test Integration - Multiple Rules
# ============================================================================

def test_multiple_rules_can_be_applied_sequentially():
    """Test that multiple rules can be applied in sequence."""
    # Rule 1: Clean - trim whitespace
    def trim_action(row: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v.strip() if isinstance(v, str) else v for k, v in row.items()}
    
    clean_rule = create_clean_rule("trim_v1", priority=1, action=trim_action)
    
    # Rule 2: Transform - uppercase
    def uppercase_action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if "name" in result:
            result["name"] = result["name"].upper()
        return result
    
    transform_rule = create_transform_rule("uppercase_v1", priority=20, action=uppercase_action)
    
    # Rule 3: Enrich - add length
    def add_length_action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if "name" in result:
            result["name_length"] = len(result["name"])
        return result
    
    enrich_rule = create_enrich_rule("add_length_v1", priority=30, action=add_length_action)
    
    # Apply rules in sequence
    input_row = {"name": "  john  "}
    
    result = clean_rule.action(input_row)
    assert result["name"] == "john"
    
    result = transform_rule.action(result)
    assert result["name"] == "JOHN"
    
    result = enrich_rule.action(result)
    assert result["name"] == "JOHN"
    assert result["name_length"] == 4
