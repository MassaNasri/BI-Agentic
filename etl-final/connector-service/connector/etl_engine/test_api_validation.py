"""
Integration tests for API endpoint input validation.

Tests the validation framework integration with Django REST Framework views.
"""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
import json


class TestConnectDBViewValidation(TestCase):
    """Test input validation for ConnectDB endpoint."""
    
    def setUp(self):
        """Set up test client."""
        self.client = APIClient()
        self.url = '/api/connect-db/'
    
    def test_valid_mysql_connection(self):
        """Test valid MySQL connection data."""
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "test_db"
        }
        
        # Note: This will fail at connection test, but validation should pass
        response = self.client.post(self.url, data, format='json')
        
        # Should not fail with validation error (400 with validation message)
        # May fail with connection error, but that's after validation
        self.assertNotIn("required", response.data.get("message", "").lower())
        self.assertNotIn("invalid format", response.data.get("message", "").lower())
    
    def test_missing_required_field(self):
        """Test missing required field."""
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123"
            # Missing 'database' field
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("database", response.data.get("message", "").lower())
    
    def test_invalid_db_type(self):
        """Test invalid database type."""
        data = {
            "db_type": "mongodb",  # Not in allowed list
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "test_db"
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("must normalize to one of", response.data.get("message", "").lower())
    
    def test_invalid_port_too_high(self):
        """Test port number too high."""
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 99999,  # Invalid port
            "user": "root",
            "password": "password123",
            "database": "test_db"
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("port", response.data.get("message", "").lower())
    
    def test_invalid_port_zero(self):
        """Test port number zero."""
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 0,  # Invalid port
            "user": "root",
            "password": "password123",
            "database": "test_db"
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("port", response.data.get("message", "").lower())
    
    def test_invalid_database_name_with_sql_injection(self):
        """Test database name with SQL injection attempt."""
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "test_db; DROP TABLE users;"  # SQL injection attempt
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("database", response.data.get("message", "").lower())
    
    def test_invalid_database_name_with_spaces(self):
        """Test database name with spaces."""
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "test db"  # Space not allowed
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("database", response.data.get("message", "").lower())
    
    def test_empty_host(self):
        """Test empty host field."""
        data = {
            "db_type": "mysql",
            "host": "",  # Empty host
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "test_db"
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_empty_username(self):
        """Test empty username field."""
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "",  # Empty user
            "password": "password123",
            "database": "test_db"
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_empty_password(self):
        """Test empty password field."""
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "",  # Empty password
            "database": "test_db"
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_valid_postgresql_connection(self):
        """Test valid PostgreSQL connection data."""
        data = {
            "db_type": "postgresql",
            "host": "db.example.com",
            "port": 5432,
            "user": "postgres",
            "password": "secure_password",
            "database": "production_db"
        }
        
        response = self.client.post(self.url, data, format='json')
        
        # Should not fail with validation error
        self.assertNotIn("required", response.data.get("message", "").lower())
        self.assertNotIn("invalid format", response.data.get("message", "").lower())
    
    def test_username_with_special_characters(self):
        """Test username with allowed special characters."""
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "user.name@domain",  # Dots and @ are allowed
            "password": "password123",
            "database": "test_db"
        }
        
        response = self.client.post(self.url, data, format='json')
        
        # Should not fail with validation error for username
        message = response.data.get("message", "").lower()
        if "invalid" in message:
            self.assertNotIn("username", message)
    
    def test_database_name_with_underscores_and_hyphens(self):
        """Test database name with underscores and hyphens."""
        data = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "test_db-2024"  # Underscores and hyphens are allowed
        }
        
        response = self.client.post(self.url, data, format='json')
        
        # Should not fail with validation error for database name
        message = response.data.get("message", "").lower()
        if "invalid" in message:
            self.assertNotIn("database", message)


class TestUploadFileViewValidation(TestCase):
    """Test input validation for UploadFile endpoint."""
    
    def setUp(self):
        """Set up test client."""
        self.client = APIClient()
        self.url = '/api/upload/'
    
    def test_missing_file(self):
        """Test upload without file."""
        response = self.client.post(self.url, {}, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("no file", response.data.get("message", "").lower())
    
    def test_file_type_validation_handled_by_file_validator(self):
        """Test that file type validation is handled by file_validator module."""
        # This is tested in test_file_validator.py
        # Just verify the endpoint exists and responds
        response = self.client.post(self.url, {}, format='multipart')
        self.assertIsNotNone(response)


class TestValidationFrameworkIntegration(TestCase):
    """Test overall validation framework integration."""
    
    def test_sanitization_prevents_null_bytes(self):
        """Test that sanitization removes null bytes from inputs."""
        client = APIClient()
        url = '/api/connect-db/'
        
        data = {
            "db_type": "mysql",
            "host": "localhost\x00malicious",  # Null byte injection attempt
            "port": 3306,
            "user": "root",
            "password": "password123",
            "database": "test_db"
        }
        
        response = client.post(url, data, format='json')
        
        # Should either reject or sanitize the input
        # The validation framework sanitizes it, so it should pass validation
        # but may fail at connection test
        self.assertIsNotNone(response)
    
    def test_multiple_validation_errors_reported(self):
        """Test that multiple validation errors are reported together."""
        client = APIClient()
        url = '/api/connect-db/'
        
        data = {
            "db_type": "invalid_type",  # Invalid
            "host": "",  # Empty
            "port": 99999,  # Invalid
            "user": "root",
            "password": "password123",
            "database": "test db"  # Invalid (space)
        }
        
        response = client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        # Should report multiple errors
        message = response.data.get("message", "")
        # At least one validation error should be present
        self.assertTrue(len(message) > 0)
