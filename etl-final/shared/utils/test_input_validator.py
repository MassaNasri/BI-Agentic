"""
Unit tests for input validation framework.

Tests cover:
- Field validators (required, type, length, value, pattern, enum, custom)
- Request validators
- Common validators (port, hostname, database name, username)
- Sanitization functions
- Pre-built validators
"""

import unittest
from input_validator import (
    FieldValidator,
    RequestValidator,
    ValidationError,
    validate_port,
    validate_hostname,
    validate_database_name,
    validate_username,
    sanitize_string,
    validate_json_payload_size,
    create_db_connection_validator,
)


class TestFieldValidator(unittest.TestCase):
    """Test FieldValidator class."""
    
    def test_required_field_present(self):
        """Test required field validation when field is present."""
        validator = FieldValidator("name", required=True)
        is_valid, error = validator.validate({"name": "test"})
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_required_field_missing(self):
        """Test required field validation when field is missing."""
        validator = FieldValidator("name", required=True)
        is_valid, error = validator.validate({})
        self.assertFalse(is_valid)
        self.assertIn("required", error.lower())
    
    def test_required_field_empty_string(self):
        """Test required field validation with empty string."""
        validator = FieldValidator("name", required=True)
        is_valid, error = validator.validate({"name": ""})
        self.assertFalse(is_valid)
        self.assertIn("required", error.lower())
    
    def test_type_validation_valid(self):
        """Test type validation with correct type."""
        validator = FieldValidator("age").type(int)
        is_valid, error = validator.validate({"age": 25})
        self.assertTrue(is_valid)
    
    def test_type_validation_invalid(self):
        """Test type validation with incorrect type."""
        validator = FieldValidator("age").type(int)
        is_valid, error = validator.validate({"age": "25"})
        self.assertFalse(is_valid)
        self.assertIn("type", error.lower())
    
    def test_min_length_valid(self):
        """Test minimum length validation with valid input."""
        validator = FieldValidator("password").min_length(8)
        is_valid, error = validator.validate({"password": "12345678"})
        self.assertTrue(is_valid)
    
    def test_min_length_invalid(self):
        """Test minimum length validation with invalid input."""
        validator = FieldValidator("password").min_length(8)
        is_valid, error = validator.validate({"password": "1234"})
        self.assertFalse(is_valid)
        self.assertIn("at least", error.lower())
    
    def test_max_length_valid(self):
        """Test maximum length validation with valid input."""
        validator = FieldValidator("username").max_length(20)
        is_valid, error = validator.validate({"username": "john_doe"})
        self.assertTrue(is_valid)
    
    def test_max_length_invalid(self):
        """Test maximum length validation with invalid input."""
        validator = FieldValidator("username").max_length(5)
        is_valid, error = validator.validate({"username": "john_doe"})
        self.assertFalse(is_valid)
        self.assertIn("at most", error.lower())
    
    def test_min_value_valid(self):
        """Test minimum value validation with valid input."""
        validator = FieldValidator("age").min_value(18)
        is_valid, error = validator.validate({"age": 25})
        self.assertTrue(is_valid)
    
    def test_min_value_invalid(self):
        """Test minimum value validation with invalid input."""
        validator = FieldValidator("age").min_value(18)
        is_valid, error = validator.validate({"age": 15})
        self.assertFalse(is_valid)
        self.assertIn("at least", error.lower())
    
    def test_max_value_valid(self):
        """Test maximum value validation with valid input."""
        validator = FieldValidator("age").max_value(100)
        is_valid, error = validator.validate({"age": 25})
        self.assertTrue(is_valid)
    
    def test_max_value_invalid(self):
        """Test maximum value validation with invalid input."""
        validator = FieldValidator("age").max_value(100)
        is_valid, error = validator.validate({"age": 150})
        self.assertFalse(is_valid)
        self.assertIn("at most", error.lower())
    
    def test_pattern_valid(self):
        """Test pattern validation with valid input."""
        validator = FieldValidator("email").pattern(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        is_valid, error = validator.validate({"email": "test@example.com"})
        self.assertTrue(is_valid)
    
    def test_pattern_invalid(self):
        """Test pattern validation with invalid input."""
        validator = FieldValidator("email").pattern(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        is_valid, error = validator.validate({"email": "invalid-email"})
        self.assertFalse(is_valid)
        self.assertIn("invalid format", error.lower())
    
    def test_enum_valid(self):
        """Test enum validation with valid input."""
        validator = FieldValidator("status").enum(["active", "inactive", "pending"])
        is_valid, error = validator.validate({"status": "active"})
        self.assertTrue(is_valid)
    
    def test_enum_invalid(self):
        """Test enum validation with invalid input."""
        validator = FieldValidator("status").enum(["active", "inactive", "pending"])
        is_valid, error = validator.validate({"status": "deleted"})
        self.assertFalse(is_valid)
        self.assertIn("must be one of", error.lower())
    
    def test_custom_validator_valid(self):
        """Test custom validator with valid input."""
        def is_even(value):
            return (value % 2 == 0, "Value must be even")
        
        validator = FieldValidator("number").custom(is_even)
        is_valid, error = validator.validate({"number": 4})
        self.assertTrue(is_valid)
    
    def test_custom_validator_invalid(self):
        """Test custom validator with invalid input."""
        def is_even(value):
            return (value % 2 == 0, "Value must be even")
        
        validator = FieldValidator("number").custom(is_even)
        is_valid, error = validator.validate({"number": 3})
        self.assertFalse(is_valid)
        self.assertIn("even", error.lower())
    
    def test_chained_validators(self):
        """Test multiple validators chained together."""
        validator = (
            FieldValidator("username", required=True)
            .type(str)
            .min_length(3)
            .max_length(20)
            .pattern(r'^[a-zA-Z0-9_]+$')
        )
        
        # Valid input
        is_valid, error = validator.validate({"username": "john_doe"})
        self.assertTrue(is_valid)
        
        # Invalid: too short
        is_valid, error = validator.validate({"username": "ab"})
        self.assertFalse(is_valid)
        
        # Invalid: special characters
        is_valid, error = validator.validate({"username": "john@doe"})
        self.assertFalse(is_valid)
    
    def test_optional_field_not_provided(self):
        """Test optional field when not provided."""
        validator = FieldValidator("nickname").type(str).min_length(3)
        is_valid, error = validator.validate({})
        self.assertTrue(is_valid)  # Optional field, not provided, should pass


class TestRequestValidator(unittest.TestCase):
    """Test RequestValidator class."""
    
    def test_single_field_valid(self):
        """Test request validator with single valid field."""
        validator = RequestValidator()
        validator.add_field(FieldValidator("name", required=True).type(str))
        
        is_valid, errors = validator.validate({"name": "John"})
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
    
    def test_single_field_invalid(self):
        """Test request validator with single invalid field."""
        validator = RequestValidator()
        validator.add_field(FieldValidator("name", required=True).type(str))
        
        is_valid, errors = validator.validate({})
        self.assertFalse(is_valid)
        self.assertEqual(len(errors), 1)
    
    def test_multiple_fields_all_valid(self):
        """Test request validator with multiple valid fields."""
        validator = RequestValidator()
        validator.add_field(FieldValidator("name", required=True).type(str))
        validator.add_field(FieldValidator("age", required=True).type(int).min_value(0))
        
        is_valid, errors = validator.validate({"name": "John", "age": 25})
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
    
    def test_multiple_fields_some_invalid(self):
        """Test request validator with some invalid fields."""
        validator = RequestValidator()
        validator.add_field(FieldValidator("name", required=True).type(str))
        validator.add_field(FieldValidator("age", required=True).type(int).min_value(0))
        
        is_valid, errors = validator.validate({"name": "John"})
        self.assertFalse(is_valid)
        self.assertEqual(len(errors), 1)
    
    def test_validate_or_raise_valid(self):
        """Test validate_or_raise with valid data."""
        validator = RequestValidator()
        validator.add_field(FieldValidator("name", required=True).type(str))
        
        try:
            validator.validate_or_raise({"name": "John"})
        except ValidationError:
            self.fail("validate_or_raise raised ValidationError unexpectedly")
    
    def test_validate_or_raise_invalid(self):
        """Test validate_or_raise with invalid data."""
        validator = RequestValidator()
        validator.add_field(FieldValidator("name", required=True).type(str))
        
        with self.assertRaises(ValidationError):
            validator.validate_or_raise({})


class TestCommonValidators(unittest.TestCase):
    """Test common validator functions."""
    
    def test_validate_port_valid(self):
        """Test port validation with valid ports."""
        self.assertTrue(validate_port(80)[0])
        self.assertTrue(validate_port(443)[0])
        self.assertTrue(validate_port(3306)[0])
        self.assertTrue(validate_port(65535)[0])
        self.assertTrue(validate_port("8080")[0])  # String that can be converted
    
    def test_validate_port_invalid(self):
        """Test port validation with invalid ports."""
        self.assertFalse(validate_port(0)[0])
        self.assertFalse(validate_port(-1)[0])
        self.assertFalse(validate_port(65536)[0])
        self.assertFalse(validate_port("invalid")[0])
        self.assertFalse(validate_port(None)[0])
    
    def test_validate_hostname_valid(self):
        """Test hostname validation with valid hostnames."""
        self.assertTrue(validate_hostname("localhost")[0])
        self.assertTrue(validate_hostname("127.0.0.1")[0])
        self.assertTrue(validate_hostname("example.com")[0])
        self.assertTrue(validate_hostname("sub.example.com")[0])
        self.assertTrue(validate_hostname("my-server")[0])
    
    def test_validate_hostname_invalid(self):
        """Test hostname validation with invalid hostnames."""
        self.assertFalse(validate_hostname("")[0])
        self.assertFalse(validate_hostname(None)[0])
        self.assertFalse(validate_hostname("invalid..hostname")[0])
        self.assertFalse(validate_hostname("-invalid")[0])
    
    def test_validate_database_name_valid(self):
        """Test database name validation with valid names."""
        self.assertTrue(validate_database_name("mydb")[0])
        self.assertTrue(validate_database_name("my_database")[0])
        self.assertTrue(validate_database_name("db-123")[0])
        self.assertTrue(validate_database_name("test_db_2024")[0])
    
    def test_validate_database_name_invalid(self):
        """Test database name validation with invalid names."""
        self.assertFalse(validate_database_name("")[0])
        self.assertFalse(validate_database_name(None)[0])
        self.assertFalse(validate_database_name("my database")[0])  # Space
        self.assertFalse(validate_database_name("db;DROP TABLE")[0])  # SQL injection attempt
        self.assertFalse(validate_database_name("a" * 65)[0])  # Too long
    
    def test_validate_username_valid(self):
        """Test username validation with valid usernames."""
        self.assertTrue(validate_username("john")[0])
        self.assertTrue(validate_username("john_doe")[0])
        self.assertTrue(validate_username("john.doe")[0])
        self.assertTrue(validate_username("john-doe")[0])
        self.assertTrue(validate_username("user@domain")[0])
    
    def test_validate_username_invalid(self):
        """Test username validation with invalid usernames."""
        self.assertFalse(validate_username("")[0])
        self.assertFalse(validate_username(None)[0])
        self.assertFalse(validate_username("john doe")[0])  # Space
        self.assertFalse(validate_username("john;DROP")[0])  # SQL injection attempt
        self.assertFalse(validate_username("a" * 129)[0])  # Too long


class TestSanitization(unittest.TestCase):
    """Test sanitization functions."""
    
    def test_sanitize_string_normal(self):
        """Test sanitization with normal string."""
        result = sanitize_string("  hello world  ")
        self.assertEqual(result, "hello world")
    
    def test_sanitize_string_null_bytes(self):
        """Test sanitization removes null bytes."""
        result = sanitize_string("hello\x00world")
        self.assertEqual(result, "helloworld")
    
    def test_sanitize_string_max_length(self):
        """Test sanitization truncates to max length."""
        long_string = "a" * 2000
        result = sanitize_string(long_string, max_length=100)
        self.assertEqual(len(result), 100)
    
    def test_sanitize_string_non_string(self):
        """Test sanitization converts non-strings."""
        result = sanitize_string(123)
        self.assertEqual(result, "123")


class TestPayloadValidation(unittest.TestCase):
    """Test payload validation functions."""
    
    def test_validate_json_payload_size_valid(self):
        """Test payload size validation with valid size."""
        data = {"key": "value"}
        is_valid, error = validate_json_payload_size(data, max_size_bytes=1024)
        self.assertTrue(is_valid)
    
    def test_validate_json_payload_size_invalid(self):
        """Test payload size validation with oversized payload."""
        data = {"key": "x" * 1000000}
        is_valid, error = validate_json_payload_size(data, max_size_bytes=1024)
        self.assertFalse(is_valid)
        self.assertIn("exceeds", error.lower())


class TestPreBuiltValidators(unittest.TestCase):
    """Test pre-built validators."""
    
    def test_db_connection_validator_valid(self):
        """Test database connection validator with valid data."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "mydb"
        }
        is_valid, errors = validator.validate(data)
        self.assertTrue(is_valid, f"Validation failed: {errors}")

    def test_db_connection_validator_accepts_postgresql_alias(self):
        """Test PostgreSQL alias is accepted and normalized by the validator."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "postgresql",
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "password": "password123",
            "database": "mydb"
        }
        is_valid, errors = validator.validate(data)
        self.assertTrue(is_valid, f"Validation failed: {errors}")
    
    def test_db_connection_validator_missing_field(self):
        """Test database connection validator with missing field."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123"
            # Missing 'database' field
        }
        is_valid, errors = validator.validate(data)
        self.assertFalse(is_valid)
        self.assertTrue(any("database" in err.lower() for err in errors))
    
    def test_db_connection_validator_invalid_db_type(self):
        """Test database connection validator with invalid db_type."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "mongodb",  # Not in allowed list
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "mydb"
        }
        is_valid, errors = validator.validate(data)
        self.assertFalse(is_valid)
        self.assertTrue(any("must normalize to one of" in err.lower() for err in errors))
    
    def test_db_connection_validator_invalid_port(self):
        """Test database connection validator with invalid port."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 99999,  # Invalid port
            "user": "root",
            "password": "password123",
            "database": "mydb"
        }
        is_valid, errors = validator.validate(data)
        self.assertFalse(is_valid)
        self.assertTrue(any("port" in err.lower() for err in errors))


if __name__ == '__main__':
    unittest.main()
