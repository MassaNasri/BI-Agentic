"""
Unit Tests for Kafka Schema Validator
Tests schema validation for all Kafka topics with various valid and invalid messages.
"""
import pytest

from shared.utils.kafka_schema_validator import KafkaSchemaValidator, FieldValidator, ValidationError


class TestFieldValidator:
    """Test individual field validation logic."""
    
    def test_validate_type_string(self):
        """Test string type validation."""
        is_valid, error = FieldValidator.validate_type("hello", "string")
        assert is_valid is True
        assert error is None
        
        is_valid, error = FieldValidator.validate_type(123, "string")
        assert is_valid is False
        assert "Expected string" in error
    
    def test_validate_type_integer(self):
        """Test integer type validation."""
        is_valid, error = FieldValidator.validate_type(42, "integer")
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_type(3.14, "integer")
        assert is_valid is False
        
        # Boolean should not be considered integer
        is_valid, error = FieldValidator.validate_type(True, "integer")
        assert is_valid is False
    
    def test_validate_type_float(self):
        """Test float type validation."""
        is_valid, error = FieldValidator.validate_type(3.14, "float")
        assert is_valid is True
        
        # Integers should be accepted as floats
        is_valid, error = FieldValidator.validate_type(42, "float")
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_type("not a number", "float")
        assert is_valid is False
    
    def test_validate_type_boolean(self):
        """Test boolean type validation."""
        is_valid, error = FieldValidator.validate_type(True, "boolean")
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_type(False, "boolean")
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_type(1, "boolean")
        assert is_valid is False
    
    def test_validate_type_dict(self):
        """Test dict type validation."""
        is_valid, error = FieldValidator.validate_type({"key": "value"}, "dict")
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_type([], "dict")
        assert is_valid is False
    
    def test_validate_type_list(self):
        """Test list type validation."""
        is_valid, error = FieldValidator.validate_type([1, 2, 3], "list")
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_type({}, "list")
        assert is_valid is False
    
    def test_validate_type_any(self):
        """Test 'any' type accepts all values."""
        is_valid, error = FieldValidator.validate_type("string", "any")
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_type(123, "any")
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_type(None, "any")
        assert is_valid is True
    
    def test_validate_constraints_min_max(self):
        """Test min/max constraints for numbers."""
        is_valid, error = FieldValidator.validate_constraints(50, {"min": 0, "max": 100})
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_constraints(-5, {"min": 0})
        assert is_valid is False
        assert "less than minimum" in error
        
        is_valid, error = FieldValidator.validate_constraints(150, {"max": 100})
        assert is_valid is False
        assert "exceeds maximum" in error
    
    def test_validate_constraints_length(self):
        """Test min_length/max_length constraints."""
        is_valid, error = FieldValidator.validate_constraints("hello", {"min_length": 3, "max_length": 10})
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_constraints("hi", {"min_length": 3})
        assert is_valid is False
        assert "less than minimum" in error
        
        is_valid, error = FieldValidator.validate_constraints("very long string", {"max_length": 5})
        assert is_valid is False
        assert "exceeds maximum" in error
    
    def test_validate_constraints_pattern(self):
        """Test regex pattern constraint."""
        is_valid, error = FieldValidator.validate_constraints(
            "test@example.com", 
            {"pattern": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"}
        )
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_constraints(
            "invalid-email", 
            {"pattern": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"}
        )
        assert is_valid is False
        assert "does not match pattern" in error
    
    def test_validate_constraints_enum(self):
        """Test enum constraint."""
        is_valid, error = FieldValidator.validate_constraints("file", {"enum": ["file", "database"]})
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_constraints("invalid", {"enum": ["file", "database"]})
        assert is_valid is False
        assert "not in allowed values" in error
    
    def test_validate_constraints_not_empty(self):
        """Test not_empty constraint."""
        is_valid, error = FieldValidator.validate_constraints("hello", {"not_empty": True})
        assert is_valid is True
        
        is_valid, error = FieldValidator.validate_constraints("", {"not_empty": True})
        assert is_valid is False
        assert "cannot be empty" in error
        
        is_valid, error = FieldValidator.validate_constraints([], {"not_empty": True})
        assert is_valid is False
        
        is_valid, error = FieldValidator.validate_constraints({}, {"not_empty": True})
        assert is_valid is False


class TestConnectionTopicValidation:
    """Test validation for connection_topic messages."""
    
    def test_valid_file_connection(self):
        """Test valid file connection message."""
        message = {
            "type": "file",
            "filename": "test.csv",
            "path": "/uploads/test.csv",
            "size": 1024
        }
        is_valid, error = KafkaSchemaValidator.validate_message("connection_topic", message)
        assert is_valid is True
        assert error is None
    
    def test_valid_database_connection(self):
        """Test valid database connection message."""
        message = {
            "type": "database",
            "db_type": "mysql",
            "host": "localhost",
            "user": "admin",
            "password": "secret",
            "database": "testdb",
            "port": 3306
        }
        is_valid, error = KafkaSchemaValidator.validate_message("connection_topic", message)
        assert is_valid is True
        assert error is None
    
    def test_missing_type_field(self):
        """Test message missing required 'type' field."""
        message = {
            "filename": "test.csv"
        }
        is_valid, error = KafkaSchemaValidator.validate_message("connection_topic", message)
        assert is_valid is False
        assert "Missing required field: type" in error
    
    def test_invalid_type_value(self):
        """Test message with invalid type value."""
        message = {
            "type": "invalid_type"
        }
        is_valid, error = KafkaSchemaValidator.validate_message("connection_topic", message)
        assert is_valid is False
        assert "not in allowed values" in error
    
    def test_file_missing_required_fields(self):
        """Test file connection missing required fields."""
        message = {
            "type": "file",
            "filename": "test.csv"
            # Missing 'path' and 'size'
        }
        is_valid, error = KafkaSchemaValidator.validate_message("connection_topic", message)
        assert is_valid is False
        assert "Missing required field" in error
    
    def test_database_missing_required_fields(self):
        """Test database connection missing required fields."""
        message = {
            "type": "database",
            "host": "localhost"
            # Missing other required fields
        }
        is_valid, error = KafkaSchemaValidator.validate_message("connection_topic", message)
        assert is_valid is False
        assert "Missing required field" in error
    
    def test_invalid_port_range(self):
        """Test database connection with invalid port."""
        message = {
            "type": "database",
            "db_type": "mysql",
            "host": "localhost",
            "user": "admin",
            "password": "secret",
            "database": "testdb",
            "port": 99999  # Invalid port
        }
        is_valid, error = KafkaSchemaValidator.validate_message("connection_topic", message)
        assert is_valid is False
        assert "exceeds maximum" in error
    
    def test_invalid_db_type(self):
        """Test database connection with invalid db_type."""
        message = {
            "type": "database",
            "db_type": "mongodb",  # Not in enum
            "host": "localhost",
            "user": "admin",
            "password": "secret",
            "database": "testdb",
            "port": 3306
        }
        is_valid, error = KafkaSchemaValidator.validate_message("connection_topic", message)
        assert is_valid is False
        assert "not in allowed values" in error


class TestSchemaTopicValidation:
    """Test validation for schema_topic messages."""
    
    def test_valid_schema_message(self):
        """Test valid schema message."""
        message = {
            "source": "test.csv",
            "type": "file",
            "columns": ["id", "name", "email"],
            "dtypes": {"id": "int64", "name": "object", "email": "object"},
            "row_count": 100
        }
        is_valid, error = KafkaSchemaValidator.validate_message("schema_topic", message)
        assert is_valid is True
        assert error is None
    
    def test_missing_required_fields(self):
        """Test schema message missing required fields."""
        message = {
            "source": "test.csv"
            # Missing 'type' and 'columns'
        }
        is_valid, error = KafkaSchemaValidator.validate_message("schema_topic", message)
        assert is_valid is False
        assert "Missing required field" in error
    
    def test_empty_columns_list(self):
        """Test schema message with empty columns list."""
        message = {
            "source": "test.csv",
            "type": "file",
            "columns": []  # Empty list
        }
        is_valid, error = KafkaSchemaValidator.validate_message("schema_topic", message)
        assert is_valid is False
        assert "cannot be empty" in error
    
    def test_invalid_type_value(self):
        """Test schema message with invalid type."""
        message = {
            "source": "test.csv",
            "type": "api",  # Invalid type
            "columns": ["id", "name"]
        }
        is_valid, error = KafkaSchemaValidator.validate_message("schema_topic", message)
        assert is_valid is False
        assert "not in allowed values" in error


class TestExtractedRowsTopicValidation:
    """Test validation for extracted_rows_topic messages."""
    
    def test_valid_extracted_row(self):
        """Test valid extracted row message."""
        message = {
            "source": "test.csv",
            "row_id": 1,
            "data": {"id": 1, "name": "John", "email": "john@example.com"}
        }
        is_valid, error = KafkaSchemaValidator.validate_message("extracted_rows_topic", message)
        assert is_valid is True
        assert error is None
    
    def test_valid_with_batch_metadata(self):
        """Test valid extracted row with batch metadata."""
        message = {
            "source": "test.csv",
            "row_id": 1,
            "data": {"id": 1, "name": "John"},
            "batch_id": "batch_123",
            "extracted_at": "2024-01-01T00:00:00Z"
        }
        is_valid, error = KafkaSchemaValidator.validate_message("extracted_rows_topic", message)
        assert is_valid is True
        assert error is None
    
    def test_missing_source(self):
        """Test extracted row missing source field."""
        message = {
            "row_id": 1,
            "data": {"id": 1}
        }
        is_valid, error = KafkaSchemaValidator.validate_message("extracted_rows_topic", message)
        assert is_valid is False
        assert "Missing required field: source" in error
    
    def test_missing_data(self):
        """Test extracted row missing data field."""
        message = {
            "source": "test.csv",
            "row_id": 1
        }
        is_valid, error = KafkaSchemaValidator.validate_message("extracted_rows_topic", message)
        assert is_valid is False
        assert "Missing required field: data" in error
    
    def test_empty_data_dict(self):
        """Test extracted row with empty data dict."""
        message = {
            "source": "test.csv",
            "row_id": 1,
            "data": {}  # Empty dict
        }
        is_valid, error = KafkaSchemaValidator.validate_message("extracted_rows_topic", message)
        assert is_valid is False
        assert "cannot be empty" in error
    
    def test_invalid_data_type(self):
        """Test extracted row with non-dict data."""
        message = {
            "source": "test.csv",
            "row_id": 1,
            "data": "not a dict"
        }
        is_valid, error = KafkaSchemaValidator.validate_message("extracted_rows_topic", message)
        assert is_valid is False
        assert "Expected dict" in error


class TestCleanRowsTopicValidation:
    """Test validation for clean_rows_topic messages."""
    
    def test_valid_clean_row(self):
        """Test valid clean row message."""
        message = {
            "source": "test.csv",
            "row_id": 1,
            "data": {"id": 1, "name": "John", "email": "john@example.com"}
        }
        is_valid, error = KafkaSchemaValidator.validate_message("clean_rows_topic", message)
        assert is_valid is True
        assert error is None
    
    def test_valid_with_quality_metadata(self):
        """Test valid clean row with quality metadata."""
        message = {
            "source": "test.csv",
            "row_id": 1,
            "data": {"id": 1, "name": "John"},
            "batch_id": "batch_123",
            "cleaned_at": "2024-01-01T00:00:00Z",
            "quality_score": 0.95,
            "warnings": ["Trimmed whitespace"]
        }
        is_valid, error = KafkaSchemaValidator.validate_message("clean_rows_topic", message)
        assert is_valid is True
        assert error is None
    
    def test_invalid_quality_score_range(self):
        """Test clean row with quality score out of range."""
        message = {
            "source": "test.csv",
            "data": {"id": 1},
            "quality_score": 1.5  # > 1.0
        }
        is_valid, error = KafkaSchemaValidator.validate_message("clean_rows_topic", message)
        assert is_valid is False
        assert "exceeds maximum" in error
    
    def test_empty_data_rejected(self):
        """Test clean row with empty data is rejected."""
        message = {
            "source": "test.csv",
            "data": {}
        }
        is_valid, error = KafkaSchemaValidator.validate_message("clean_rows_topic", message)
        assert is_valid is False
        assert "cannot be empty" in error


class TestLoadRowsTopicValidation:
    """Test validation for load_rows_topic messages."""
    
    def test_valid_success_status(self):
        """Test valid load success message."""
        message = {
            "source": "test.csv",
            "table": "test_table",
            "status": "success",
            "row_count": 100,
            "batch_id": "batch_123"
        }
        is_valid, error = KafkaSchemaValidator.validate_message("load_rows_topic", message)
        assert is_valid is True
        assert error is None
    
    def test_valid_error_status(self):
        """Test valid load error message."""
        message = {
            "source": "test.csv",
            "status": "error",
            "error": "Connection timeout"
        }
        is_valid, error = KafkaSchemaValidator.validate_message("load_rows_topic", message)
        assert is_valid is True
        assert error is None
    
    def test_missing_error_field_on_error_status(self):
        """Test error status without error field."""
        message = {
            "source": "test.csv",
            "status": "error"
            # Missing 'error' field
        }
        is_valid, error = KafkaSchemaValidator.validate_message("load_rows_topic", message)
        assert is_valid is False
        assert "Missing required field 'error'" in error
    
    def test_invalid_status_value(self):
        """Test load message with invalid status."""
        message = {
            "source": "test.csv",
            "status": "pending"  # Not in enum
        }
        is_valid, error = KafkaSchemaValidator.validate_message("load_rows_topic", message)
        assert is_valid is False
        assert "not in allowed values" in error
    
    def test_negative_row_count(self):
        """Test load message with negative row count."""
        message = {
            "source": "test.csv",
            "status": "success",
            "row_count": -5
        }
        is_valid, error = KafkaSchemaValidator.validate_message("load_rows_topic", message)
        assert is_valid is False
        assert "less than minimum" in error


class TestMetadataTopicValidation:
    """Test validation for metadata_topic messages."""
    
    def test_valid_metadata_message(self):
        """Test valid metadata message."""
        message = {
            "event_type": "extraction_started",
            "timestamp": "2024-01-01T00:00:00Z",
            "source": "test.csv",
            "data": {"rows": 100}
        }
        is_valid, error = KafkaSchemaValidator.validate_message("metadata_topic", message)
        assert is_valid is True
        assert error is None
    
    def test_missing_required_fields(self):
        """Test metadata message missing required fields."""
        message = {
            "source": "test.csv"
            # Missing 'event_type' and 'timestamp'
        }
        is_valid, error = KafkaSchemaValidator.validate_message("metadata_topic", message)
        assert is_valid is False
        assert "Missing required field" in error
    
    def test_empty_event_type(self):
        """Test metadata message with empty event_type."""
        message = {
            "event_type": "",
            "timestamp": "2024-01-01T00:00:00Z"
        }
        is_valid, error = KafkaSchemaValidator.validate_message("metadata_topic", message)
        assert is_valid is False
        assert "cannot be empty" in error


class TestSchemaUtilities:
    """Test utility methods of KafkaSchemaValidator."""
    
    def test_get_schema(self):
        """Test retrieving schema for a topic."""
        schema = KafkaSchemaValidator.get_schema("connection_topic")
        assert schema is not None
        assert "required_fields" in schema
        assert "fields" in schema
    
    def test_get_schema_unknown_topic(self):
        """Test retrieving schema for unknown topic."""
        schema = KafkaSchemaValidator.get_schema("unknown_topic")
        assert schema is None
    
    def test_list_topics(self):
        """Test listing all topics with schemas."""
        topics = KafkaSchemaValidator.list_topics()
        assert isinstance(topics, list)
        assert "connection_topic" in topics
        assert "schema_topic" in topics
        assert "extracted_rows_topic" in topics
        assert "clean_rows_topic" in topics
        assert "load_rows_topic" in topics
        assert "metadata_topic" in topics
    
    def test_unknown_topic_allows_message(self):
        """Test that unknown topics allow messages through."""
        message = {"any": "data"}
        is_valid, error = KafkaSchemaValidator.validate_message("unknown_topic", message)
        assert is_valid is True
        assert error is None


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_none_values_in_optional_fields(self):
        """Test that None values are allowed in optional fields."""
        message = {
            "source": "test.csv",
            "row_id": None,  # Optional field with None
            "data": {"id": 1}
        }
        is_valid, error = KafkaSchemaValidator.validate_message("extracted_rows_topic", message)
        assert is_valid is True
    
    def test_none_value_in_required_field(self):
        """Test that None values are rejected in required fields."""
        message = {
            "source": None,  # Required field with None
            "data": {"id": 1}
        }
        is_valid, error = KafkaSchemaValidator.validate_message("extracted_rows_topic", message)
        assert is_valid is False
        assert "cannot be None" in error
    
    def test_extra_fields_allowed(self):
        """Test that extra fields not in schema are allowed."""
        message = {
            "source": "test.csv",
            "data": {"id": 1},
            "extra_field": "extra_value",  # Not in schema
            "another_extra": 123
        }
        is_valid, error = KafkaSchemaValidator.validate_message("extracted_rows_topic", message)
        assert is_valid is True
    
    def test_boundary_port_values(self):
        """Test boundary values for port numbers."""
        # Minimum valid port
        message = {
            "type": "database",
            "db_type": "mysql",
            "host": "localhost",
            "user": "admin",
            "password": "secret",
            "database": "testdb",
            "port": 1
        }
        is_valid, error = KafkaSchemaValidator.validate_message("connection_topic", message)
        assert is_valid is True
        
        # Maximum valid port
        message["port"] = 65535
        is_valid, error = KafkaSchemaValidator.validate_message("connection_topic", message)
        assert is_valid is True
        
        # Below minimum
        message["port"] = 0
        is_valid, error = KafkaSchemaValidator.validate_message("connection_topic", message)
        assert is_valid is False
        
        # Above maximum
        message["port"] = 65536
        is_valid, error = KafkaSchemaValidator.validate_message("connection_topic", message)
        assert is_valid is False
    
    def test_boundary_quality_scores(self):
        """Test boundary values for quality scores."""
        # Minimum valid score
        message = {
            "source": "test.csv",
            "data": {"id": 1},
            "quality_score": 0.0
        }
        is_valid, error = KafkaSchemaValidator.validate_message("clean_rows_topic", message)
        assert is_valid is True
        
        # Maximum valid score
        message["quality_score"] = 1.0
        is_valid, error = KafkaSchemaValidator.validate_message("clean_rows_topic", message)
        assert is_valid is True
        
        # Below minimum
        message["quality_score"] = -0.1
        is_valid, error = KafkaSchemaValidator.validate_message("clean_rows_topic", message)
        assert is_valid is False
        
        # Above maximum
        message["quality_score"] = 1.1
        is_valid, error = KafkaSchemaValidator.validate_message("clean_rows_topic", message)
        assert is_valid is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
