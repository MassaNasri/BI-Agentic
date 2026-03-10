"""
Rule Actions - Concrete action functions for transformation rules.

This module provides pure, deterministic action functions that can be used
with TransformationRule. All actions are:
- Pure functions (no side effects)
- Deterministic (same input → same output)
- Composable (can be chained together)
- Testable (easy to unit test)

Action Categories:
- String operations: trim, uppercase, lowercase, normalize_whitespace
- Type casting: to_int, to_float, to_bool, to_date
- Regex operations: regex_replace, regex_extract
- Field operations: remove_field, rename_field, copy_field
- Value operations: replace_value, default_value

**Validates: Requirements US-6 (AC 6.1-6.4)**
"""
from typing import Dict, Any, Optional, Callable, Pattern, Union
import re
from datetime import datetime, date
from copy import deepcopy


# ============================================================================
# String Operations
# ============================================================================

def trim_strings(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trim whitespace from all string fields.
    
    Args:
        row: Input data row
        
    Returns:
        Row with trimmed string values
        
    Example:
        >>> trim_strings({"name": "  John  ", "age": 30})
        {"name": "John", "age": 30}
    """
    result = {}
    for key, value in row.items():
        if isinstance(value, str):
            result[key] = value.strip()
        else:
            result[key] = value
    return result


def trim_field(field_name: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that trims whitespace from a specific field.
    
    Args:
        field_name: Name of the field to trim
        
    Returns:
        Action function
        
    Example:
        >>> action = trim_field("name")
        >>> action({"name": "  John  ", "age": 30})
        {"name": "John", "age": 30}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if field_name in result and isinstance(result[field_name], str):
            result[field_name] = result[field_name].strip()
        return result
    return action


def uppercase_strings(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert all string fields to uppercase.
    
    Args:
        row: Input data row
        
    Returns:
        Row with uppercase string values
        
    Example:
        >>> uppercase_strings({"name": "john", "age": 30})
        {"name": "JOHN", "age": 30}
    """
    result = {}
    for key, value in row.items():
        if isinstance(value, str):
            result[key] = value.upper()
        else:
            result[key] = value
    return result


def uppercase_field(field_name: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that converts a specific field to uppercase.
    
    Args:
        field_name: Name of the field to convert
        
    Returns:
        Action function
        
    Example:
        >>> action = uppercase_field("name")
        >>> action({"name": "john", "age": 30})
        {"name": "JOHN", "age": 30}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if field_name in result and isinstance(result[field_name], str):
            result[field_name] = result[field_name].upper()
        return result
    return action


def lowercase_strings(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert all string fields to lowercase.
    
    Args:
        row: Input data row
        
    Returns:
        Row with lowercase string values
        
    Example:
        >>> lowercase_strings({"name": "JOHN", "age": 30})
        {"name": "john", "age": 30}
    """
    result = {}
    for key, value in row.items():
        if isinstance(value, str):
            result[key] = value.lower()
        else:
            result[key] = value
    return result


def lowercase_field(field_name: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that converts a specific field to lowercase.
    
    Args:
        field_name: Name of the field to convert
        
    Returns:
        Action function
        
    Example:
        >>> action = lowercase_field("name")
        >>> action({"name": "JOHN", "age": 30})
        {"name": "john", "age": 30}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if field_name in result and isinstance(result[field_name], str):
            result[field_name] = result[field_name].lower()
        return result
    return action


def normalize_whitespace(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize whitespace in all string fields (multiple spaces -> single space).
    
    Args:
        row: Input data row
        
    Returns:
        Row with normalized whitespace
        
    Example:
        >>> normalize_whitespace({"name": "John   Doe", "age": 30})
        {"name": "John Doe", "age": 30}
    """
    result = {}
    for key, value in row.items():
        if isinstance(value, str):
            # Replace multiple whitespace with single space
            result[key] = re.sub(r'\s+', ' ', value)
        else:
            result[key] = value
    return result


def normalize_whitespace_field(field_name: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that normalizes whitespace in a specific field.
    
    Args:
        field_name: Name of the field to normalize
        
    Returns:
        Action function
        
    Example:
        >>> action = normalize_whitespace_field("name")
        >>> action({"name": "John   Doe", "age": 30})
        {"name": "John Doe", "age": 30}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if field_name in result and isinstance(result[field_name], str):
            result[field_name] = re.sub(r'\s+', ' ', result[field_name])
        return result
    return action


# ============================================================================
# Type Casting Operations
# ============================================================================

def cast_to_int(field_name: str, on_error: str = "raise") -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that casts a field to integer.
    
    Args:
        field_name: Name of the field to cast
        on_error: Error handling strategy ("raise", "skip", "null")
        
    Returns:
        Action function
        
    Example:
        >>> action = cast_to_int("age")
        >>> action({"name": "John", "age": "30"})
        {"name": "John", "age": 30}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if field_name in result:
            try:
                value = result[field_name]
                if isinstance(value, int):
                    return result
                if isinstance(value, str):
                    value = value.strip()
                result[field_name] = int(value)
            except (ValueError, TypeError) as e:
                if on_error == "raise":
                    raise ValueError(f"Cannot cast field '{field_name}' to int: {e}")
                elif on_error == "null":
                    result[field_name] = None
                # on_error == "skip": keep original value
        return result
    return action


def cast_to_float(field_name: str, on_error: str = "raise") -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that casts a field to float.
    
    Args:
        field_name: Name of the field to cast
        on_error: Error handling strategy ("raise", "skip", "null")
        
    Returns:
        Action function
        
    Example:
        >>> action = cast_to_float("price")
        >>> action({"item": "Book", "price": "19.99"})
        {"item": "Book", "price": 19.99}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if field_name in result:
            try:
                value = result[field_name]
                if isinstance(value, float):
                    return result
                if isinstance(value, str):
                    value = value.strip()
                result[field_name] = float(value)
            except (ValueError, TypeError) as e:
                if on_error == "raise":
                    raise ValueError(f"Cannot cast field '{field_name}' to float: {e}")
                elif on_error == "null":
                    result[field_name] = None
                # on_error == "skip": keep original value
        return result
    return action


def cast_to_bool(field_name: str, on_error: str = "raise") -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that casts a field to boolean.
    
    Recognizes: true/false, yes/no, 1/0, on/off (case-insensitive)
    
    Args:
        field_name: Name of the field to cast
        on_error: Error handling strategy ("raise", "skip", "null")
        
    Returns:
        Action function
        
    Example:
        >>> action = cast_to_bool("active")
        >>> action({"name": "John", "active": "yes"})
        {"name": "John", "active": True}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if field_name in result:
            try:
                value = result[field_name]
                if isinstance(value, bool):
                    return result
                if isinstance(value, str):
                    normalized = value.strip().lower()
                    if normalized in ['true', 'yes', '1', 'on', 't', 'y']:
                        result[field_name] = True
                    elif normalized in ['false', 'no', '0', 'off', 'f', 'n', '']:
                        result[field_name] = False
                    else:
                        raise ValueError(f"Cannot convert '{value}' to boolean")
                elif isinstance(value, (int, float)):
                    result[field_name] = bool(value)
                else:
                    raise ValueError(f"Cannot convert type {type(value)} to boolean")
            except (ValueError, TypeError) as e:
                if on_error == "raise":
                    raise ValueError(f"Cannot cast field '{field_name}' to bool: {e}")
                elif on_error == "null":
                    result[field_name] = None
                # on_error == "skip": keep original value
        return result
    return action


def cast_to_date(
    field_name: str,
    date_format: str = "%Y-%m-%d",
    on_error: str = "raise"
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that casts a field to date.
    
    Args:
        field_name: Name of the field to cast
        date_format: Date format string (default: YYYY-MM-DD)
        on_error: Error handling strategy ("raise", "skip", "null")
        
    Returns:
        Action function
        
    Example:
        >>> action = cast_to_date("birth_date")
        >>> action({"name": "John", "birth_date": "1990-01-15"})
        {"name": "John", "birth_date": date(1990, 1, 15)}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if field_name in result:
            try:
                value = result[field_name]
                if isinstance(value, date):
                    return result
                if isinstance(value, str):
                    value = value.strip()
                    result[field_name] = datetime.strptime(value, date_format).date()
                else:
                    raise ValueError(f"Cannot convert type {type(value)} to date")
            except (ValueError, TypeError) as e:
                if on_error == "raise":
                    raise ValueError(f"Cannot cast field '{field_name}' to date: {e}")
                elif on_error == "null":
                    result[field_name] = None
                # on_error == "skip": keep original value
        return result
    return action


# ============================================================================
# Regex Operations
# ============================================================================

def regex_replace(
    field_name: str,
    pattern: str,
    replacement: str,
    flags: int = 0
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that replaces text matching a regex pattern.
    
    Args:
        field_name: Name of the field to process
        pattern: Regular expression pattern
        replacement: Replacement string
        flags: Regex flags (e.g., re.IGNORECASE)
        
    Returns:
        Action function
        
    Example:
        >>> action = regex_replace("phone", r"[^0-9]", "")
        >>> action({"name": "John", "phone": "(555) 123-4567"})
        {"name": "John", "phone": "5551234567"}
    """
    compiled_pattern = re.compile(pattern, flags)
    
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if field_name in result and isinstance(result[field_name], str):
            result[field_name] = compiled_pattern.sub(replacement, result[field_name])
        return result
    return action


def regex_extract(
    field_name: str,
    pattern: str,
    group: int = 0,
    on_no_match: str = "skip"
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that extracts text matching a regex pattern.
    
    Args:
        field_name: Name of the field to process
        pattern: Regular expression pattern
        group: Capture group to extract (0 = entire match)
        on_no_match: What to do if no match ("skip", "null", "raise")
        
    Returns:
        Action function
        
    Example:
        >>> action = regex_extract("email", r"([^@]+)@", group=1)
        >>> action({"email": "john@example.com"})
        {"email": "john"}
    """
    compiled_pattern = re.compile(pattern)
    
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if field_name in result and isinstance(result[field_name], str):
            match = compiled_pattern.search(result[field_name])
            if match:
                result[field_name] = match.group(group)
            elif on_no_match == "null":
                result[field_name] = None
            elif on_no_match == "raise":
                raise ValueError(f"Pattern '{pattern}' did not match field '{field_name}'")
            # on_no_match == "skip": keep original value
        return result
    return action


# ============================================================================
# Field Operations
# ============================================================================

def remove_field(field_name: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that removes a field from the row.
    
    Args:
        field_name: Name of the field to remove
        
    Returns:
        Action function
        
    Example:
        >>> action = remove_field("temp_field")
        >>> action({"name": "John", "temp_field": "delete me"})
        {"name": "John"}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        result.pop(field_name, None)
        return result
    return action


def remove_null_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove all fields with null/None values.
    
    Args:
        row: Input data row
        
    Returns:
        Row with null fields removed
        
    Example:
        >>> remove_null_fields({"name": "John", "age": None, "city": "NYC"})
        {"name": "John", "city": "NYC"}
    """
    return {k: v for k, v in row.items() if v is not None}


def rename_field(
    old_name: str,
    new_name: str
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that renames a field.
    
    Args:
        old_name: Current field name
        new_name: New field name
        
    Returns:
        Action function
        
    Example:
        >>> action = rename_field("first_name", "given_name")
        >>> action({"first_name": "John", "last_name": "Doe"})
        {"given_name": "John", "last_name": "Doe"}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if old_name in result:
            result[new_name] = result.pop(old_name)
        return result
    return action


def copy_field(
    source_name: str,
    dest_name: str
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that copies a field to a new name.
    
    Args:
        source_name: Source field name
        dest_name: Destination field name
        
    Returns:
        Action function
        
    Example:
        >>> action = copy_field("name", "full_name")
        >>> action({"name": "John Doe", "age": 30})
        {"name": "John Doe", "full_name": "John Doe", "age": 30}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if source_name in result:
            result[dest_name] = deepcopy(result[source_name])
        return result
    return action


# ============================================================================
# Value Operations
# ============================================================================

def replace_value(
    field_name: str,
    old_value: Any,
    new_value: Any
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that replaces a specific value in a field.
    
    Args:
        field_name: Name of the field to check
        old_value: Value to replace
        new_value: Replacement value
        
    Returns:
        Action function
        
    Example:
        >>> action = replace_value("status", "N/A", None)
        >>> action({"name": "John", "status": "N/A"})
        {"name": "John", "status": None}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if field_name in result and result[field_name] == old_value:
            result[field_name] = new_value
        return result
    return action


def default_value(
    field_name: str,
    default: Any
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Create an action that sets a default value if field is missing or None.
    
    Args:
        field_name: Name of the field to check
        default: Default value to use
        
    Returns:
        Action function
        
    Example:
        >>> action = default_value("country", "USA")
        >>> action({"name": "John"})
        {"name": "John", "country": "USA"}
    """
    def action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row.copy()
        if field_name not in result or result[field_name] is None:
            result[field_name] = default
        return result
    return action


# ============================================================================
# Composite Actions
# ============================================================================

def compose_actions(*actions: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Compose multiple actions into a single action.
    
    Actions are applied left-to-right (first action first).
    
    Args:
        *actions: Variable number of action functions
        
    Returns:
        Composed action function
        
    Example:
        >>> action = compose_actions(
        ...     trim_field("name"),
        ...     uppercase_field("name")
        ... )
        >>> action({"name": "  john  "})
        {"name": "JOHN"}
    """
    def composed_action(row: Dict[str, Any]) -> Dict[str, Any]:
        result = row
        for action in actions:
            result = action(result)
        return result
    return composed_action
