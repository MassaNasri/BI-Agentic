"""
Rule Type Implementations - Concrete rule builders for each type.

This module provides factory functions and concrete implementations for each
of the four rule types: CLEAN, VALIDATE, TRANSFORM, and ENRICH.

Each rule type has specific semantics:
- CLEAN: Remove/fix data quality issues (nulls, whitespace, duplicates)
- VALIDATE: Check data meets constraints (return errors, don't modify)
- TRANSFORM: Convert data types or formats (deterministic conversions)
- ENRICH: Add derived fields or external data (augment, don't replace)

**Validates: Requirements US-6 (AC 6.1-6.4)**
"""
from typing import Dict, Any, Callable, Optional, List, Pattern
import re
from .transformation_rule import TransformationRule, RuleType


# ============================================================================
# CLEAN Rule Type - Data Quality Fixes
# ============================================================================
# Semantics: Remove or fix data quality issues without changing meaning
# - Remove null/empty values
# - Trim whitespace
# - Normalize whitespace
# - Remove duplicates
# - Fix encoding issues
# ============================================================================

def create_clean_rule(
    rule_id: str,
    priority: int,
    action: Callable[[Dict[str, Any]], Dict[str, Any]],
    condition: Callable[[Dict[str, Any]], bool] = lambda row: True,
    metadata: Optional[Dict[str, Any]] = None
) -> TransformationRule:
    """
    Create a CLEAN type rule.
    
    CLEAN rules fix data quality issues without changing the semantic meaning.
    They remove or fix issues like nulls, whitespace, encoding problems, etc.
    
    Examples:
        - Remove null fields
        - Trim whitespace from strings
        - Normalize whitespace (multiple spaces -> single space)
        - Fix encoding issues (UTF-8 normalization)
        - Remove duplicate spaces
    
    Args:
        rule_id: Unique identifier for the rule (e.g., "trim_strings_v1")
        priority: Execution priority (lower numbers execute first)
        action: Function that cleans the row data
        condition: Function that determines if rule applies (default: always)
        metadata: Additional metadata (description, version, author, etc.)
    
    Returns:
        TransformationRule configured as CLEAN type
    
    Example:
        >>> def trim_action(row):
        ...     return {k: v.strip() if isinstance(v, str) else v 
        ...             for k, v in row.items()}
        >>> rule = create_clean_rule(
        ...     rule_id="trim_strings_v1",
        ...     priority=1,
        ...     action=trim_action,
        ...     metadata={"description": "Trim whitespace from all string fields"}
        ... )
    """
    return TransformationRule(
        rule_id=rule_id,
        rule_type=RuleType.CLEAN,
        priority=priority,
        condition=condition,
        action=action,
        metadata=metadata or {}
    )


# ============================================================================
# VALIDATE Rule Type - Data Constraint Checking
# ============================================================================
# Semantics: Check data meets constraints, return errors, DON'T modify data
# - Type validation
# - Range validation
# - Format validation (regex)
# - Business rule validation
# - Referential integrity checks
# ============================================================================

def create_validate_rule(
    rule_id: str,
    priority: int,
    action: Callable[[Dict[str, Any]], Dict[str, Any]],
    condition: Callable[[Dict[str, Any]], bool] = lambda row: True,
    metadata: Optional[Dict[str, Any]] = None
) -> TransformationRule:
    """
    Create a VALIDATE type rule.
    
    VALIDATE rules check that data meets constraints and return errors.
    They should NOT modify the data - only validate and report issues.
    
    Examples:
        - Check email format matches regex
        - Verify age is within valid range (0-150)
        - Ensure required fields are present
        - Validate foreign key references exist
        - Check data type correctness
    
    Args:
        rule_id: Unique identifier for the rule (e.g., "validate_email_v1")
        priority: Execution priority (lower numbers execute first)
        action: Function that validates the row (should not modify data)
        condition: Function that determines if rule applies (default: always)
        metadata: Additional metadata (description, validation_type, etc.)
    
    Returns:
        TransformationRule configured as VALIDATE type
    
    Example:
        >>> def validate_email_action(row):
        ...     # Validation rules should NOT modify data
        ...     # They should raise exceptions or return error indicators
        ...     if 'email' in row:
        ...         email = row['email']
        ...         if not re.match(r'^[^@]+@[^@]+\\.[^@]+$', email):
        ...             raise ValueError(f"Invalid email format: {email}")
        ...     return row  # Return unchanged
        >>> rule = create_validate_rule(
        ...     rule_id="validate_email_v1",
        ...     priority=10,
        ...     action=validate_email_action,
        ...     metadata={"description": "Validate email format"}
        ... )
    """
    return TransformationRule(
        rule_id=rule_id,
        rule_type=RuleType.VALIDATE,
        priority=priority,
        condition=condition,
        action=action,
        metadata=metadata or {}
    )


# ============================================================================
# TRANSFORM Rule Type - Data Type/Format Conversion
# ============================================================================
# Semantics: Convert data types or formats (deterministic conversions)
# - Type casting (string -> int, string -> date)
# - Format conversion (date formats, number formats)
# - Unit conversion (miles -> km, USD -> EUR)
# - Case conversion (uppercase, lowercase, title case)
# - Encoding conversion
# ============================================================================

def create_transform_rule(
    rule_id: str,
    priority: int,
    action: Callable[[Dict[str, Any]], Dict[str, Any]],
    condition: Callable[[Dict[str, Any]], bool] = lambda row: True,
    metadata: Optional[Dict[str, Any]] = None
) -> TransformationRule:
    """
    Create a TRANSFORM type rule.
    
    TRANSFORM rules convert data types or formats in a deterministic way.
    Same input always produces same output. No external data dependencies.
    
    Examples:
        - Cast string to integer
        - Convert date format (MM/DD/YYYY -> YYYY-MM-DD)
        - Convert units (miles -> kilometers)
        - Change case (uppercase, lowercase, title case)
        - Parse JSON strings into objects
    
    Args:
        rule_id: Unique identifier for the rule (e.g., "cast_to_int_v1")
        priority: Execution priority (lower numbers execute first)
        action: Function that transforms the row data
        condition: Function that determines if rule applies (default: always)
        metadata: Additional metadata (description, transformation_type, etc.)
    
    Returns:
        TransformationRule configured as TRANSFORM type
    
    Example:
        >>> def cast_to_int_action(row):
        ...     result = row.copy()
        ...     if 'age' in result and isinstance(result['age'], str):
        ...         result['age'] = int(result['age'])
        ...     return result
        >>> rule = create_transform_rule(
        ...     rule_id="cast_age_to_int_v1",
        ...     priority=20,
        ...     action=cast_to_int_action,
        ...     condition=lambda row: 'age' in row,
        ...     metadata={"description": "Cast age field to integer"}
        ... )
    """
    return TransformationRule(
        rule_id=rule_id,
        rule_type=RuleType.TRANSFORM,
        priority=priority,
        condition=condition,
        action=action,
        metadata=metadata or {}
    )


# ============================================================================
# ENRICH Rule Type - Data Augmentation
# ============================================================================
# Semantics: Add derived fields or external data (augment, don't replace)
# - Add calculated fields
# - Add lookup data from external sources
# - Add derived metrics
# - Add timestamps/metadata
# - Add geolocation data
# ============================================================================

def create_enrich_rule(
    rule_id: str,
    priority: int,
    action: Callable[[Dict[str, Any]], Dict[str, Any]],
    condition: Callable[[Dict[str, Any]], bool] = lambda row: True,
    metadata: Optional[Dict[str, Any]] = None
) -> TransformationRule:
    """
    Create an ENRICH type rule.
    
    ENRICH rules add new fields or augment existing data without replacing it.
    They can add calculated fields, lookup external data, or derive metrics.
    
    Examples:
        - Add full_name from first_name + last_name
        - Add country_name lookup from country_code
        - Add age_group derived from age
        - Add processing_timestamp
        - Add geolocation data from IP address
    
    Args:
        rule_id: Unique identifier for the rule (e.g., "add_full_name_v1")
        priority: Execution priority (lower numbers execute first)
        action: Function that enriches the row with additional data
        condition: Function that determines if rule applies (default: always)
        metadata: Additional metadata (description, enrichment_source, etc.)
    
    Returns:
        TransformationRule configured as ENRICH type
    
    Example:
        >>> def add_full_name_action(row):
        ...     result = row.copy()
        ...     if 'first_name' in row and 'last_name' in row:
        ...         result['full_name'] = f"{row['first_name']} {row['last_name']}"
        ...     return result
        >>> rule = create_enrich_rule(
        ...     rule_id="add_full_name_v1",
        ...     priority=30,
        ...     action=add_full_name_action,
        ...     condition=lambda row: 'first_name' in row and 'last_name' in row,
        ...     metadata={"description": "Add full_name field"}
        ... )
    """
    return TransformationRule(
        rule_id=rule_id,
        rule_type=RuleType.ENRICH,
        priority=priority,
        condition=condition,
        action=action,
        metadata=metadata or {}
    )


# ============================================================================
# Helper Functions - Common Rule Patterns
# ============================================================================

def create_field_condition(field_name: str, field_exists: bool = True) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition function that checks if a field exists.
    
    Args:
        field_name: Name of the field to check
        field_exists: If True, check field exists; if False, check field doesn't exist
    
    Returns:
        Condition function
    
    Example:
        >>> condition = create_field_condition('email', field_exists=True)
        >>> condition({'email': 'test@example.com'})
        True
        >>> condition({'name': 'John'})
        False
    """
    if field_exists:
        return lambda row: field_name in row
    else:
        return lambda row: field_name not in row


def create_type_condition(field_name: str, expected_type: type) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition function that checks if a field has a specific type.
    
    Args:
        field_name: Name of the field to check
        expected_type: Expected Python type (str, int, float, bool, etc.)
    
    Returns:
        Condition function
    
    Example:
        >>> condition = create_type_condition('age', str)
        >>> condition({'age': '25'})
        True
        >>> condition({'age': 25})
        False
    """
    return lambda row: field_name in row and isinstance(row[field_name], expected_type)


def create_regex_condition(field_name: str, pattern: str) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a condition function that checks if a field matches a regex pattern.
    
    Args:
        field_name: Name of the field to check
        pattern: Regular expression pattern
    
    Returns:
        Condition function
    
    Example:
        >>> condition = create_regex_condition('email', r'^[^@]+@[^@]+\\.[^@]+$')
        >>> condition({'email': 'test@example.com'})
        True
        >>> condition({'email': 'invalid'})
        False
    """
    compiled_pattern = re.compile(pattern)
    return lambda row: (
        field_name in row 
        and isinstance(row[field_name], str) 
        and compiled_pattern.match(row[field_name]) is not None
    )
