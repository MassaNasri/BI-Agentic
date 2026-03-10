"""
Integration tests for input validation framework (standalone, no Django required).

Tests the validation framework in isolation without Django dependencies.
"""

import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from shared.utils.input_validator import (
    FieldValidator,
    RequestValidator,
    ValidationError,
    create_db_connection_validator,
    validate_port,
    validate_hostname,
    validate_database_name,
    validate_username,
    sanitize_string,
    validate_json_payload_size,
)


class TestDatabaseConnectionValidation(unittest.TestCase):
    """Test database connection validation scenarios."""
    
    def test_valid_mysql_connection(self):
        """Test valid MySQL connection data passes validation."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "test_db"
        }
        
        is_valid, errors = validator.validate(data)
        self.assertTrue(is_valid, f"Validation failed: {errors}")
        self.assertEqual(len(errors), 0)
    
    def test_sql_injection_in_database_name(self):
        """Test that SQL injection attempts in database name are rejected."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "test_db; DROP TABLE users;"
        }
        
        is_valid, errors = validator.validate(data)
        self.assertFalse(is_valid)
        self.assertTrue(any("database" in err.lower() for err in errors))
    
    def test_invalid_port_number(self):
        """Test that invalid port numbers are rejected."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 99999,  # Invalid
            "user": "root",
            "password": "password123",
            "database": "test_db"
        }
        
        is_valid, errors = validator.validate(data)
        self.assertFalse(is_valid)
        self.assertTrue(any("port" in err.lower() for err in errors))
    
    def test_missing_required_field(self):
        """Test that missing required fields are detected."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123"
            # Missing 'database'
        }
        
        is_valid, errors = validator.validate(data)
        self.assertFalse(is_valid)
        self.assertTrue(any("database" in err.lower() for err in errors))
    
    def test_invalid_database_type(self):
        """Test that invalid database types are rejected."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "mongodb",  # Not in allowed list
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "test_db"
        }
        
        is_valid, errors = validator.validate(data)
        self.assertFalse(is_valid)
        self.assertTrue(any("must normalize to one of" in err.lower() for err in errors))
    
    def test_multiple_validation_errors(self):
        """Test that multiple validation errors are reported."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "invalid_type",
            "host": "",
            "port": 99999,
            "user": "root",
            "password": "password123",
            "database": "test db"  # Space not allowed
        }
        
        is_valid, errors = validator.validate(data)
        self.assertFalse(is_valid)
        # Should have multiple errors
        self.assertGreater(len(errors), 1)


class TestSecurityValidation(unittest.TestCase):
    """Test security-focused validation."""
    
    def test_null_byte_injection_prevention(self):
        """Test that null bytes are removed from inputs."""
        malicious_input = "localhost\x00malicious"
        sanitized = sanitize_string(malicious_input)
        
        self.assertNotIn('\x00', sanitized)
        self.assertEqual(sanitized, "localhostmalicious")
    
    def test_sql_injection_in_username(self):
        """Test that SQL injection attempts in username are rejected."""
        is_valid, error = validate_username("admin; DROP TABLE users;")
        self.assertFalse(is_valid)
    
    def test_xss_attempt_in_database_name(self):
        """Test that XSS attempts in database name are rejected."""
        is_valid, error = validate_database_name("<script>alert('xss')</script>")
        self.assertFalse(is_valid)
    
    def test_path_traversal_in_database_name(self):
        """Test that path traversal attempts are rejected."""
        is_valid, error = validate_database_name("../../etc/passwd")
        self.assertFalse(is_valid)
    
    def test_command_injection_in_hostname(self):
        """Test that command injection attempts in hostname are rejected."""
        is_valid, error = validate_hostname("localhost; rm -rf /")
        self.assertFalse(is_valid)


class TestPayloadSizeValidation(unittest.TestCase):
    """Test payload size validation."""
    
    def test_small_payload_accepted(self):
        """Test that small payloads are accepted."""
        data = {"key": "value"}
        is_valid, error = validate_json_payload_size(data, max_size_bytes=1024)
        self.assertTrue(is_valid)
    
    def test_large_payload_rejected(self):
        """Test that oversized payloads are rejected."""
        data = {"key": "x" * 1000000}
        is_valid, error = validate_json_payload_size(data, max_size_bytes=1024)
        self.assertFalse(is_valid)
        self.assertIn("exceeds", error.lower())


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""
    
    def test_empty_string_in_required_field(self):
        """Test that empty strings in required fields are rejected."""
        validator = FieldValidator("name", required=True)
        is_valid, error = validator.validate({"name": ""})
        self.assertFalse(is_valid)
    
    def test_whitespace_only_in_required_field(self):
        """Test that whitespace-only strings are sanitized."""
        input_str = "   "
        sanitized = sanitize_string(input_str)
        self.assertEqual(sanitized, "")
    
    def test_very_long_string_truncation(self):
        """Test that very long strings are truncated."""
        long_string = "a" * 2000
        sanitized = sanitize_string(long_string, max_length=100)
        self.assertEqual(len(sanitized), 100)
    
    def test_unicode_characters_in_database_name(self):
        """Test that unicode characters in database name are rejected."""
        is_valid, error = validate_database_name("test_db_中文")
        self.assertFalse(is_valid)
    
    def test_port_as_string(self):
        """Test that port numbers as strings are accepted."""
        is_valid, error = validate_port("3306")
        self.assertTrue(is_valid)
    
    def test_port_boundary_values(self):
        """Test port number boundary values."""
        # Minimum valid port
        self.assertTrue(validate_port(1)[0])
        
        # Maximum valid port
        self.assertTrue(validate_port(65535)[0])
        
        # Just below minimum
        self.assertFalse(validate_port(0)[0])
        
        # Just above maximum
        self.assertFalse(validate_port(65536)[0])


class TestValidationChaining(unittest.TestCase):
    """Test chaining multiple validation rules."""
    
    def test_complex_validation_chain(self):
        """Test complex validation with multiple chained rules."""
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
        
        # Too short
        is_valid, error = validator.validate({"username": "ab"})
        self.assertFalse(is_valid)
        
        # Too long
        is_valid, error = validator.validate({"username": "a" * 25})
        self.assertFalse(is_valid)
        
        # Invalid characters
        is_valid, error = validator.validate({"username": "john@doe"})
        self.assertFalse(is_valid)


class TestRealWorldScenarios(unittest.TestCase):
    """Test real-world usage scenarios."""
    
    def test_postgresql_connection(self):
        """Test PostgreSQL connection validation."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "postgresql",
            "host": "db.example.com",
            "port": 5432,
            "user": "postgres",
            "password": "secure_password_123!@#",
            "database": "production_db"
        }
        
        is_valid, errors = validator.validate(data)
        self.assertTrue(is_valid, f"Validation failed: {errors}")
    
    def test_localhost_connection(self):
        """Test localhost connection validation."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "mysql",
            "host": "127.0.0.1",
            "port": 3306,
            "user": "root",
            "password": "root",
            "database": "local_dev"
        }
        
        is_valid, errors = validator.validate(data)
        self.assertTrue(is_valid, f"Validation failed: {errors}")
    
    def test_remote_connection_with_subdomain(self):
        """Test remote connection with subdomain."""
        validator = create_db_connection_validator()
        data = {
            "db_type": "postgresql",
            "host": "db.prod.example.com",
            "port": 5432,
            "user": "app_user",
            "password": "complex_password_123",
            "database": "app_database"
        }
        
        is_valid, errors = validator.validate(data)
        self.assertTrue(is_valid, f"Validation failed: {errors}")


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
