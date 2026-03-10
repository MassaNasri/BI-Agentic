"""
Input validation framework for all API endpoints.

Provides comprehensive validation for:
- Request data validation (required fields, types, formats)
- Parameter validation (ranges, patterns, enums)
- Payload size limits
- Schema validation
- Sanitization of inputs

Design principles:
- Declarative validation rules
- Reusable validators
- Clear error messages
- Security-focused (prevent injection, XSS, etc.)
"""

import re
from typing import Any, Dict, List, Optional, Tuple, Callable, Union
from enum import Enum

try:
    from .db_type_utils import canonical_db_types, normalize_db_type
except ImportError:  # pragma: no cover - compatibility for direct module imports in legacy tests
    from db_type_utils import canonical_db_types, normalize_db_type

class ValidationError(Exception):
    """Raised when validation fails."""
    
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class ValidationType(Enum):
    """Types of validation rules."""
    REQUIRED = "required"
    TYPE = "type"
    MIN_LENGTH = "min_length"
    MAX_LENGTH = "max_length"
    MIN_VALUE = "min_value"
    MAX_VALUE = "max_value"
    PATTERN = "pattern"
    ENUM = "enum"
    CUSTOM = "custom"


class FieldValidator:
    """
    Validator for a single field.
    
    Supports multiple validation rules applied in sequence.
    """
    
    def __init__(self, field_name: str, required: bool = False):
        self.field_name = field_name
        self.required = required
        self.rules: List[Tuple[ValidationType, Any]] = []
        
        if required:
            self.rules.append((ValidationType.REQUIRED, True))
    
    def type(self, expected_type: type) -> 'FieldValidator':
        """Validate field type."""
        self.rules.append((ValidationType.TYPE, expected_type))
        return self
    
    def min_length(self, length: int) -> 'FieldValidator':
        """Validate minimum string/list length."""
        self.rules.append((ValidationType.MIN_LENGTH, length))
        return self
    
    def max_length(self, length: int) -> 'FieldValidator':
        """Validate maximum string/list length."""
        self.rules.append((ValidationType.MAX_LENGTH, length))
        return self
    
    def min_value(self, value: Union[int, float]) -> 'FieldValidator':
        """Validate minimum numeric value."""
        self.rules.append((ValidationType.MIN_VALUE, value))
        return self
    
    def max_value(self, value: Union[int, float]) -> 'FieldValidator':
        """Validate maximum numeric value."""
        self.rules.append((ValidationType.MAX_VALUE, value))
        return self
    
    def pattern(self, regex: str) -> 'FieldValidator':
        """Validate against regex pattern."""
        self.rules.append((ValidationType.PATTERN, regex))
        return self
    
    def enum(self, allowed_values: List[Any]) -> 'FieldValidator':
        """Validate against allowed values."""
        self.rules.append((ValidationType.ENUM, allowed_values))
        return self
    
    def custom(self, validator_func: Callable[[Any], Tuple[bool, str]]) -> 'FieldValidator':
        """
        Add custom validation function.
        
        Args:
            validator_func: Function that takes value and returns (is_valid, error_message)
        """
        self.rules.append((ValidationType.CUSTOM, validator_func))
        return self
    
    def validate(self, data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate field against all rules.
        
        Args:
            data: Dictionary containing the field to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        value = data.get(self.field_name)
        
        for rule_type, rule_value in self.rules:
            is_valid, error_msg = self._apply_rule(rule_type, rule_value, value)
            if not is_valid:
                return False, error_msg
        
        return True, None
    
    def _apply_rule(self, rule_type: ValidationType, rule_value: Any, value: Any) -> Tuple[bool, str]:
        """Apply a single validation rule."""
        
        if rule_type == ValidationType.REQUIRED:
            if value is None or value == "":
                return False, f"Field '{self.field_name}' is required"
        
        # Skip other validations if value is None/empty and field is not required
        if value is None or value == "":
            return True, ""
        
        if rule_type == ValidationType.TYPE:
            if not isinstance(value, rule_value):
                return False, f"Field '{self.field_name}' must be of type {rule_value.__name__}"
        
        elif rule_type == ValidationType.MIN_LENGTH:
            if len(value) < rule_value:
                return False, f"Field '{self.field_name}' must have at least {rule_value} characters"
        
        elif rule_type == ValidationType.MAX_LENGTH:
            if len(value) > rule_value:
                return False, f"Field '{self.field_name}' must have at most {rule_value} characters"
        
        elif rule_type == ValidationType.MIN_VALUE:
            if value < rule_value:
                return False, f"Field '{self.field_name}' must be at least {rule_value}"
        
        elif rule_type == ValidationType.MAX_VALUE:
            if value > rule_value:
                return False, f"Field '{self.field_name}' must be at most {rule_value}"
        
        elif rule_type == ValidationType.PATTERN:
            if not re.match(rule_value, str(value)):
                return False, f"Field '{self.field_name}' has invalid format"
        
        elif rule_type == ValidationType.ENUM:
            if value not in rule_value:
                return False, f"Field '{self.field_name}' must be one of: {', '.join(map(str, rule_value))}"
        
        elif rule_type == ValidationType.CUSTOM:
            is_valid, error_msg = rule_value(value)
            if not is_valid:
                return False, error_msg
        
        return True, ""


class RequestValidator:
    """
    Validator for entire request payload.
    
    Combines multiple field validators and provides unified validation.
    """
    
    def __init__(self):
        self.validators: List[FieldValidator] = []
    
    def add_field(self, validator: FieldValidator) -> 'RequestValidator':
        """Add a field validator."""
        self.validators.append(validator)
        return self
    
    def validate(self, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate entire request data.
        
        Args:
            data: Request data dictionary
            
        Returns:
            Tuple of (is_valid, list_of_error_messages)
        """
        errors = []
        
        for validator in self.validators:
            is_valid, error_msg = validator.validate(data)
            if not is_valid:
                errors.append(error_msg)
        
        return len(errors) == 0, errors
    
    def validate_or_raise(self, data: Dict[str, Any]) -> None:
        """
        Validate and raise ValidationError if invalid.
        
        Args:
            data: Request data dictionary
            
        Raises:
            ValidationError: If validation fails
        """
        is_valid, errors = self.validate(data)
        if not is_valid:
            raise ValidationError("validation", "; ".join(errors))


# Common validators

def validate_port(port: Any) -> Tuple[bool, str]:
    """Validate port number (1-65535)."""
    try:
        port_int = int(port)
        if 1 <= port_int <= 65535:
            return True, ""
        return False, "Port must be between 1 and 65535"
    except (ValueError, TypeError):
        return False, "Port must be a valid integer"


def validate_hostname(hostname: str) -> Tuple[bool, str]:
    """Validate hostname or IP address."""
    if not hostname or not isinstance(hostname, str):
        return False, "Hostname must be a non-empty string"
    
    # Allow localhost
    if hostname.lower() in ['localhost', '127.0.0.1', '::1']:
        return True, ""
    
    # Check for consecutive dots
    if '..' in hostname:
        return False, "Invalid hostname format"
    
    # Basic hostname validation (alphanumeric, dots, hyphens)
    hostname_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-\.]{0,253}[a-zA-Z0-9])?$'
    if re.match(hostname_pattern, hostname):
        return True, ""
    
    return False, "Invalid hostname format"


def validate_database_name(db_name: str) -> Tuple[bool, str]:
    """Validate database name (alphanumeric, underscores, hyphens)."""
    if not db_name or not isinstance(db_name, str):
        return False, "Database name must be a non-empty string"
    
    # Prevent SQL injection: only allow safe characters
    safe_pattern = r'^[a-zA-Z0-9_\-]+$'
    if not re.match(safe_pattern, db_name):
        return False, "Database name can only contain letters, numbers, underscores, and hyphens"
    
    if len(db_name) > 64:
        return False, "Database name must be at most 64 characters"
    
    return True, ""


def validate_username(username: str) -> Tuple[bool, str]:
    """Validate username (alphanumeric, underscores, hyphens, dots)."""
    if not username or not isinstance(username, str):
        return False, "Username must be a non-empty string"
    
    # Allow common username characters
    safe_pattern = r'^[a-zA-Z0-9_\-\.@]+$'
    if not re.match(safe_pattern, username):
        return False, "Username contains invalid characters"
    
    if len(username) > 128:
        return False, "Username must be at most 128 characters"
    
    return True, ""


def validate_db_type(db_type: Any) -> Tuple[bool, str]:
    """
    Validate DB type using canonical normalization aliases.
    """
    normalized = normalize_db_type(str(db_type) if db_type is not None else None)
    if normalized is None:
        allowed = ", ".join(canonical_db_types())
        return False, f"db_type must normalize to one of: {allowed}"
    return True, ""


def sanitize_string(value: str, max_length: int = 1000) -> str:
    """
    Sanitize string input to prevent injection attacks.
    
    Args:
        value: Input string
        max_length: Maximum allowed length
        
    Returns:
        Sanitized string
    """
    if not isinstance(value, str):
        return str(value)
    
    # Truncate to max length
    value = value[:max_length]
    
    # Remove null bytes
    value = value.replace('\x00', '')
    
    # Strip leading/trailing whitespace
    value = value.strip()
    
    return value


def validate_json_payload_size(data: Dict[str, Any], max_size_bytes: int = 10485760) -> Tuple[bool, str]:
    """
    Validate JSON payload size.
    
    Args:
        data: Request data dictionary
        max_size_bytes: Maximum allowed size in bytes (default: 10MB)
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    import json
    
    try:
        payload_size = len(json.dumps(data).encode('utf-8'))
        if payload_size > max_size_bytes:
            max_mb = max_size_bytes / (1024 * 1024)
            actual_mb = payload_size / (1024 * 1024)
            return False, f"Payload size {actual_mb:.2f}MB exceeds maximum allowed size of {max_mb:.2f}MB"
        return True, ""
    except Exception as e:
        return False, f"Failed to validate payload size: {str(e)}"


# Pre-built validators for common use cases

def create_file_upload_validator() -> RequestValidator:
    """Create validator for file upload endpoint."""
    return RequestValidator()
    # Note: File validation is handled separately by file_validator.py


def create_db_connection_validator() -> RequestValidator:
    """Create validator for database connection endpoint."""
    validator = RequestValidator()
    
    validator.add_field(
        FieldValidator("db_type", required=True)
        .type(str)
        .custom(validate_db_type)
    )
    
    validator.add_field(
        FieldValidator("host", required=True)
        .type(str)
        .min_length(1)
        .max_length(255)
        .custom(validate_hostname)
    )
    
    validator.add_field(
        FieldValidator("port", required=True)
        .custom(validate_port)
    )
    
    validator.add_field(
        FieldValidator("user", required=True)
        .type(str)
        .min_length(1)
        .max_length(128)
        .custom(validate_username)
    )
    
    validator.add_field(
        FieldValidator("password", required=True)
        .type(str)
        .min_length(1)
        .max_length(256)
    )
    
    validator.add_field(
        FieldValidator("database", required=True)
        .type(str)
        .min_length(1)
        .max_length(64)
        .custom(validate_database_name)
    )
    
    return validator
