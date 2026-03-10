"""
Rule Condition Helpers
Provides common condition patterns for transformation rules.

Based on design.md section 3.1 and requirements US-6 (AC 6.1-6.4).

These helper functions create reusable, composable conditions for
TransformationRule objects. All conditions are pure functions that:
- Take a row (Dict[str, Any]) as input
- Return a boolean indicating if the condition is met
- Have no side effects
- Are deterministic (same input → same output)

Usage:
    from rule_conditions import field_exists, field_type, field_value_matches
    
    rule = TransformationRule(
        rule_id="trim_name",
        rule_type=RuleType.CLEAN,
        priority=1,
        condition=field_exists("name"),
        action=lambda row: {**row, "name": row["name"].strip()}
    )
"""
from typing import Dict, Any, Callable, Pattern, Set, List
import re


def always_true(row: Dict[str, Any]) -> bool:
    """
    Condition that always returns True.
    
    Use this for rules that should apply to all rows.
    
    Args:
        row: The data row
        
    Returns:
        Always True
        
    Example:
        rule = TransformationRule(
            rule_id="add_timestamp",
            condition=always_true,
            action=lambda row: {**row, "_processed_at": datetime.utcnow()}
        )
    """
    return True


def always_false(row: Dict[str, Any]) -> bool:
    """
    Condition that always returns False.
    
    Use this to temporarily disable a rule without removing it.
    
    Args:
        row: The data row
        
    Returns:
        Always False
        
    Example:
        rule = TransformationRule(
            rule_id="disabled_rule",
            condition=always_false,
            action=lambda row: row
        )
    """
    return False


def field_exists(field_name: str) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition that checks if a field exists in the row.
    
    Args:
        field_name: Name of the field to check
        
    Returns:
        Condition function that returns True if field exists
        
    Example:
        condition = field_exists("email")
        # Returns True if row has "email" key, False otherwise
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            return field_name in row
        except (TypeError, AttributeError):
            return False
    
    return condition


def field_not_exists(field_name: str) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition that checks if a field does NOT exist in the row.
    
    Args:
        field_name: Name of the field to check
        
    Returns:
        Condition function that returns True if field does not exist
        
    Example:
        condition = field_not_exists("email")
        # Returns True if row does NOT have "email" key
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            return field_name not in row
        except (TypeError, AttributeError):
            return False
    
    return condition


def field_is_null(field_name: str) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition that checks if a field value is None.
    
    Args:
        field_name: Name of the field to check
        
    Returns:
        Condition function that returns True if field is None
        
    Example:
        condition = field_is_null("middle_name")
        # Returns True if row["middle_name"] is None
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            return field_name in row and row[field_name] is None
        except (TypeError, AttributeError):
            return False
    
    return condition


def field_is_not_null(field_name: str) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition that checks if a field value is NOT None.
    
    Args:
        field_name: Name of the field to check
        
    Returns:
        Condition function that returns True if field is not None
        
    Example:
        condition = field_is_not_null("email")
        # Returns True if row["email"] is not None
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            return field_name in row and row[field_name] is not None
        except (TypeError, AttributeError):
            return False
    
    return condition


def field_type(field_name: str, expected_type: type) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition that checks if a field has a specific type.
    
    Args:
        field_name: Name of the field to check
        expected_type: Expected Python type (str, int, float, bool, etc.)
        
    Returns:
        Condition function that returns True if field has expected type
        
    Example:
        condition = field_type("age", int)
        # Returns True if row["age"] is an integer
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            return field_name in row and isinstance(row[field_name], expected_type)
        except (TypeError, AttributeError):
            return False
    
    return condition


def field_value_equals(field_name: str, expected_value: Any) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition that checks if a field equals a specific value.
    
    Args:
        field_name: Name of the field to check
        expected_value: Expected value
        
    Returns:
        Condition function that returns True if field equals expected value
        
    Example:
        condition = field_value_equals("status", "active")
        # Returns True if row["status"] == "active"
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            return field_name in row and row[field_name] == expected_value
        except (TypeError, AttributeError):
            return False
    
    return condition


def field_value_in(field_name: str, allowed_values: Set[Any]) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition that checks if a field value is in a set of allowed values.
    
    Args:
        field_name: Name of the field to check
        allowed_values: Set of allowed values
        
    Returns:
        Condition function that returns True if field value is in allowed set
        
    Example:
        condition = field_value_in("status", {"active", "pending", "completed"})
        # Returns True if row["status"] is one of the allowed values
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            return field_name in row and row[field_name] in allowed_values
        except (TypeError, AttributeError):
            return False
    
    return condition


def field_value_matches(field_name: str, pattern: str) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition that checks if a field value matches a regex pattern.
    
    Args:
        field_name: Name of the field to check
        pattern: Regular expression pattern (string)
        
    Returns:
        Condition function that returns True if field matches pattern
        
    Example:
        condition = field_value_matches("email", r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$")
        # Returns True if row["email"] matches email pattern
    """
    try:
        compiled_pattern = re.compile(pattern)
    except re.error:
        # Invalid regex pattern - return a condition that always returns False
        def condition(row: Dict[str, Any]) -> bool:
            return False
        return condition
    
    def condition(row: Dict[str, Any]) -> bool:
        try:
            if field_name not in row:
                return False
            value = row[field_name]
            if not isinstance(value, str):
                return False
            return compiled_pattern.match(value) is not None
        except (TypeError, AttributeError):
            return False
    
    return condition


def field_value_contains(field_name: str, substring: str) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition that checks if a string field contains a substring.
    
    Args:
        field_name: Name of the field to check
        substring: Substring to search for
        
    Returns:
        Condition function that returns True if field contains substring
        
    Example:
        condition = field_value_contains("description", "urgent")
        # Returns True if "urgent" is in row["description"]
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            if field_name not in row:
                return False
            value = row[field_name]
            if not isinstance(value, str):
                return False
            return substring in value
        except (TypeError, AttributeError):
            return False
    
    return condition


def field_value_range(
    field_name: str,
    min_value: Any = None,
    max_value: Any = None
) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition that checks if a field value is within a range.
    
    Args:
        field_name: Name of the field to check
        min_value: Minimum value (inclusive), None for no minimum
        max_value: Maximum value (inclusive), None for no maximum
        
    Returns:
        Condition function that returns True if field is in range
        
    Example:
        condition = field_value_range("age", min_value=18, max_value=65)
        # Returns True if 18 <= row["age"] <= 65
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            if field_name not in row:
                return False
            value = row[field_name]
            
            if min_value is not None and value < min_value:
                return False
            if max_value is not None and value > max_value:
                return False
            
            return True
        except (TypeError, AttributeError, KeyError):
            return False
    
    return condition


def all_fields_exist(field_names: List[str]) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition that checks if all specified fields exist.
    
    Args:
        field_names: List of field names to check
        
    Returns:
        Condition function that returns True if all fields exist
        
    Example:
        condition = all_fields_exist(["first_name", "last_name", "email"])
        # Returns True if all three fields exist in row
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            return all(field in row for field in field_names)
        except (TypeError, AttributeError):
            return False
    
    return condition


def any_field_exists(field_names: List[str]) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition that checks if any of the specified fields exist.
    
    Args:
        field_names: List of field names to check
        
    Returns:
        Condition function that returns True if at least one field exists
        
    Example:
        condition = any_field_exists(["phone", "mobile", "telephone"])
        # Returns True if at least one phone field exists
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            return any(field in row for field in field_names)
        except (TypeError, AttributeError):
            return False
    
    return condition


def and_conditions(*conditions: Callable[[Dict[str, Any]], bool]) -> Callable[[Dict[str, Any]], bool]:
    """
    Combine multiple conditions with AND logic.
    
    Args:
        *conditions: Variable number of condition functions
        
    Returns:
        Condition function that returns True if ALL conditions are True
        
    Example:
        condition = and_conditions(
            field_exists("email"),
            field_type("email", str),
            field_value_matches("email", r".*@.*\\..*")
        )
        # Returns True only if all three conditions are met
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            return all(cond(row) for cond in conditions)
        except (TypeError, AttributeError):
            return False
    
    return condition


def or_conditions(*conditions: Callable[[Dict[str, Any]], bool]) -> Callable[[Dict[str, Any]], bool]:
    """
    Combine multiple conditions with OR logic.
    
    Args:
        *conditions: Variable number of condition functions
        
    Returns:
        Condition function that returns True if ANY condition is True
        
    Example:
        condition = or_conditions(
            field_value_equals("status", "active"),
            field_value_equals("status", "pending")
        )
        # Returns True if status is either "active" or "pending"
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            return any(cond(row) for cond in conditions)
        except (TypeError, AttributeError):
            return False
    
    return condition


def not_condition(condition_func: Callable[[Dict[str, Any]], bool]) -> Callable[[Dict[str, Any]], bool]:
    """
    Negate a condition.
    
    Args:
        condition_func: Condition function to negate
        
    Returns:
        Condition function that returns the opposite of the input condition
        
    Example:
        condition = not_condition(field_is_null("email"))
        # Returns True if email is NOT null
    """
    def condition(row: Dict[str, Any]) -> bool:
        try:
            return not condition_func(row)
        except (TypeError, AttributeError):
            return False
    
    return condition


def custom_condition(
    predicate: Callable[[Dict[str, Any]], bool],
    safe: bool = True
) -> Callable[[Dict[str, Any]], bool]:
    """
    Wrap a custom condition function with optional error handling.
    
    Args:
        predicate: Custom condition function
        safe: If True, catch exceptions and return False; if False, let exceptions propagate
        
    Returns:
        Wrapped condition function
        
    Example:
        def complex_check(row):
            return row.get("score", 0) > row.get("threshold", 100)
        
        condition = custom_condition(complex_check, safe=True)
        # Returns False if any exception occurs during evaluation
    """
    if safe:
        def condition(row: Dict[str, Any]) -> bool:
            try:
                return predicate(row)
            except Exception:
                return False
        return condition
    else:
        return predicate
