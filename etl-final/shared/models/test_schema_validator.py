"""
Unit tests for SchemaValidator class.

Tests cover:
- Single row validation
- Batch validation
- Invalid row filtering
- Valid row filtering
- Schema caching
- Quality score aggregation
- Error handling
"""
import pytest
from .schema_validator import SchemaValidator, BatchValidationResult
from .schema_contract import (
    SchemaContract,
    FieldDefinition,
    DataType,
    Constraint,
    ConstraintType
)


@pytest.fixture
def simple_schema():
    """Create a simple schema for testing."""
    return SchemaContract(
        schema_id="test_schema",
        version="1.0.0",
        fields=[
            FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
            FieldDefinition(name="name", type=DataType.STRING, nullable=False),
            FieldDefinition(name="email", type=DataType.STRING, nullable=True)
        ],
        description="Simple test schema"
    )


@pytest.fixture
def complex_schema():
    """Create a complex schema with constraints for testing."""
    return SchemaContract(
        schema_id="user_schema",
        version="1.0.0",
        fields=[
            FieldDefinition(
                name="id",
                type=DataType.INTEGER,
                nullable=False,
                constraints=[Constraint(ConstraintType.MIN, 1)]
            ),
            FieldDefinition(
                name="username",
                type=DataType.STRING,
                nullable=False,
                constraints=[
                    Constraint(ConstraintType.MIN, 3),
                    Constraint(ConstraintType.MAX, 20),
                    Constraint(ConstraintType.REGEX, r'^[a-zA-Z0-9_]+$')
                ]
            ),
            FieldDefinition(
                name="email",
                type=DataType.STRING,
                nullable=False,
                constraints=[
                    Constraint(ConstraintType.FORMAT, "email")
                ]
            ),
            FieldDefinition(
                name="age",
                type=DataType.INTEGER,
                nullable=True,
                constraints=[
                    Constraint(ConstraintType.MIN, 0),
                    Constraint(ConstraintType.MAX, 150)
                ]
            )
        ],
        description="Complex user schema with constraints"
    )


@pytest.fixture
def validator():
    """Create a SchemaValidator instance."""
    return SchemaValidator(cache_schemas=True)


class TestSchemaValidatorBasics:
    """Tests for basic SchemaValidator functionality."""
    
    def test_validator_initialization(self):
        """Test validator initialization."""
        validator = SchemaValidator(cache_schemas=True)
        assert validator.cache_schemas is True
        assert len(validator._schema_cache) == 0
        
        validator_no_cache = SchemaValidator(cache_schemas=False)
        assert validator_no_cache.cache_schemas is False
    
    def test_validate_valid_row(self, validator, simple_schema):
        """Test validation of a valid row."""
        row = {
            "id": 1,
            "name": "John Doe",
            "email": "john@example.com"
        }
        
        result = validator.validate(row, simple_schema)
        
        assert result.is_valid
        assert len(result.violations) == 0
        assert result.quality_score > 0.9
        assert result.schema_id == "test_schema"
        assert result.schema_version == "1.0.0"
    
    def test_validate_invalid_row_missing_required(self, validator, simple_schema):
        """Test validation of row with missing required field."""
        row = {
            "id": 1
            # Missing 'name' which is required
        }
        
        result = validator.validate(row, simple_schema)
        
        assert not result.is_valid
        assert len(result.violations) > 0
        assert any("name" in v and "missing" in v for v in result.violations)
    
    def test_validate_invalid_row_type_mismatch(self, validator, simple_schema):
        """Test validation of row with type mismatch."""
        row = {
            "id": "not_an_integer",
            "name": "John Doe"
        }
        
        result = validator.validate(row, simple_schema)
        
        assert not result.is_valid
        assert len(result.violations) > 0
        assert any("id" in v and "integer" in v for v in result.violations)
    
    def test_validate_row_with_null_optional_field(self, validator, simple_schema):
        """Test validation of row with null optional field."""
        row = {
            "id": 1,
            "name": "John Doe",
            "email": None
        }
        
        result = validator.validate(row, simple_schema)
        
        assert result.is_valid
        assert len(result.violations) == 0


class TestBatchValidation:
    """Tests for batch validation functionality."""
    
    def test_validate_batch_all_valid(self, validator, simple_schema):
        """Test batch validation with all valid rows."""
        rows = [
            {"id": 1, "name": "Alice", "email": "alice@example.com"},
            {"id": 2, "name": "Bob", "email": "bob@example.com"},
            {"id": 3, "name": "Charlie", "email": "charlie@example.com"}
        ]
        
        result = validator.validate_batch(rows, simple_schema)
        
        assert isinstance(result, BatchValidationResult)
        assert result.total_rows == 3
        assert result.valid_rows == 3
        assert result.invalid_rows == 0
        assert result.overall_quality_score > 0.9
        assert len(result.validation_results) == 3
        assert result.schema_id == "test_schema"
    
    def test_validate_batch_all_invalid(self, validator, simple_schema):
        """Test batch validation with all invalid rows."""
        rows = [
            {"id": "not_int", "name": "Alice"},
            {"id": "also_not_int", "name": "Bob"},
            {"id": "still_not_int", "name": "Charlie"}
        ]
        
        result = validator.validate_batch(rows, simple_schema)
        
        assert result.total_rows == 3
        assert result.valid_rows == 0
        assert result.invalid_rows == 3
        assert result.overall_quality_score <= 0.5
        assert len(result.validation_results) == 3
    
    def test_validate_batch_mixed_validity(self, validator, simple_schema):
        """Test batch validation with mixed valid/invalid rows."""
        rows = [
            {"id": 1, "name": "Alice", "email": "alice@example.com"},  # Valid
            {"id": "not_int", "name": "Bob"},  # Invalid - type mismatch
            {"id": 3, "name": "Charlie"},  # Valid
            {"id": 4}  # Invalid - missing name
        ]
        
        result = validator.validate_batch(rows, simple_schema)
        
        assert result.total_rows == 4
        assert result.valid_rows == 2
        assert result.invalid_rows == 2
        assert 0.4 < result.overall_quality_score < 0.8
        assert len(result.validation_results) == 4
    
    def test_validate_batch_empty(self, validator, simple_schema):
        """Test batch validation with empty list."""
        rows = []
        
        result = validator.validate_batch(rows, simple_schema)
        
        assert result.total_rows == 0
        assert result.valid_rows == 0
        assert result.invalid_rows == 0
        assert result.overall_quality_score == 0.0
        assert len(result.validation_results) == 0
    
    def test_validate_batch_stop_on_first_error(self, validator, simple_schema):
        """Test batch validation with stop_on_first_error flag."""
        rows = [
            {"id": 1, "name": "Alice"},  # Valid
            {"id": "not_int", "name": "Bob"},  # Invalid
            {"id": 3, "name": "Charlie"},  # Would be valid but not reached
            {"id": 4, "name": "Dave"}  # Would be valid but not reached
        ]
        
        result = validator.validate_batch(
            rows,
            simple_schema,
            stop_on_first_error=True
        )
        
        # Should stop after second row (first error)
        assert result.total_rows == 4
        assert result.valid_rows == 1
        assert result.invalid_rows == 1
        assert len(result.validation_results) == 2  # Only first 2 rows processed


class TestConstraintValidation:
    """Tests for validation with complex constraints."""
    
    def test_validate_with_min_constraint(self, validator, complex_schema):
        """Test validation with MIN constraint."""
        # Valid - meets minimum
        row = {
            "id": 1,
            "username": "john_doe",
            "email": "john@example.com",
            "age": 25
        }
        result = validator.validate(row, complex_schema)
        assert result.is_valid
        
        # Invalid - below minimum
        row = {
            "id": 0,  # Below min of 1
            "username": "john_doe",
            "email": "john@example.com"
        }
        result = validator.validate(row, complex_schema)
        assert not result.is_valid
    
    def test_validate_with_max_constraint(self, validator, complex_schema):
        """Test validation with MAX constraint."""
        # Valid - within maximum
        row = {
            "id": 1,
            "username": "john_doe",
            "email": "john@example.com",
            "age": 100
        }
        result = validator.validate(row, complex_schema)
        assert result.is_valid
        
        # Invalid - exceeds maximum
        row = {
            "id": 1,
            "username": "john_doe",
            "email": "john@example.com",
            "age": 200  # Above max of 150
        }
        result = validator.validate(row, complex_schema)
        assert not result.is_valid
    
    def test_validate_with_regex_constraint(self, validator, complex_schema):
        """Test validation with REGEX constraint."""
        # Valid - matches pattern
        row = {
            "id": 1,
            "username": "john_doe_123",
            "email": "john@example.com"
        }
        result = validator.validate(row, complex_schema)
        assert result.is_valid
        
        # Invalid - doesn't match pattern
        row = {
            "id": 1,
            "username": "john@doe",  # @ not allowed
            "email": "john@example.com"
        }
        result = validator.validate(row, complex_schema)
        assert not result.is_valid
    
    def test_validate_with_format_constraint(self, validator, complex_schema):
        """Test validation with FORMAT constraint (email)."""
        # Valid - proper email format
        row = {
            "id": 1,
            "username": "john_doe",
            "email": "john.doe@example.com"
        }
        result = validator.validate(row, complex_schema)
        assert result.is_valid
        
        # Invalid - improper email format
        row = {
            "id": 1,
            "username": "john_doe",
            "email": "not-an-email"
        }
        result = validator.validate(row, complex_schema)
        assert not result.is_valid
    
    def test_validate_multiple_constraint_violations(self, validator, complex_schema):
        """Test validation with multiple constraint violations."""
        row = {
            "id": 0,  # Below min
            "username": "ab",  # Too short
            "email": "invalid",  # Invalid format
            "age": 200  # Above max
        }
        
        result = validator.validate(row, complex_schema)
        
        assert not result.is_valid
        assert len(result.violations) >= 4  # At least 4 violations


class TestFilteringMethods:
    """Tests for invalid/valid row filtering methods."""
    
    def test_get_invalid_rows(self, validator, simple_schema):
        """Test filtering invalid rows from batch."""
        rows = [
            {"id": 1, "name": "Alice"},  # Valid
            {"id": "not_int", "name": "Bob"},  # Invalid
            {"id": 3, "name": "Charlie"},  # Valid
            {"id": 4}  # Invalid - missing name
        ]
        
        invalid_rows = validator.get_invalid_rows(rows, simple_schema)
        
        assert len(invalid_rows) == 2
        
        # Check first invalid row
        idx, row, result = invalid_rows[0]
        assert idx == 1
        assert row["name"] == "Bob"
        assert not result.is_valid
        
        # Check second invalid row
        idx, row, result = invalid_rows[1]
        assert idx == 3
        assert "name" not in row
        assert not result.is_valid
    
    def test_get_valid_rows(self, validator, simple_schema):
        """Test filtering valid rows from batch."""
        rows = [
            {"id": 1, "name": "Alice"},  # Valid
            {"id": "not_int", "name": "Bob"},  # Invalid
            {"id": 3, "name": "Charlie"},  # Valid
            {"id": 4}  # Invalid
        ]
        
        valid_rows = validator.get_valid_rows(rows, simple_schema)
        
        assert len(valid_rows) == 2
        
        # Check first valid row
        idx, row, result = valid_rows[0]
        assert idx == 0
        assert row["name"] == "Alice"
        assert result.is_valid
        
        # Check second valid row
        idx, row, result = valid_rows[1]
        assert idx == 2
        assert row["name"] == "Charlie"
        assert result.is_valid
    
    def test_get_invalid_rows_all_valid(self, validator, simple_schema):
        """Test filtering when all rows are valid."""
        rows = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Charlie"}
        ]
        
        invalid_rows = validator.get_invalid_rows(rows, simple_schema)
        
        assert len(invalid_rows) == 0
    
    def test_get_valid_rows_all_invalid(self, validator, simple_schema):
        """Test filtering when all rows are invalid."""
        rows = [
            {"id": "not_int"},
            {"name": "Bob"},  # Missing id
            {}  # Missing everything
        ]
        
        valid_rows = validator.get_valid_rows(rows, simple_schema)
        
        assert len(valid_rows) == 0


class TestSchemaCaching:
    """Tests for schema caching functionality."""
    
    def test_cache_schema(self, validator, simple_schema):
        """Test caching a schema."""
        assert len(validator._schema_cache) == 0
        
        validator.cache_schema(simple_schema)
        
        assert len(validator._schema_cache) == 1
        cache_key = f"{simple_schema.schema_id}:{simple_schema.version}"
        assert cache_key in validator._schema_cache
    
    def test_get_cached_schema(self, validator, simple_schema):
        """Test retrieving a cached schema."""
        validator.cache_schema(simple_schema)
        
        cached = validator.get_cached_schema(
            simple_schema.schema_id,
            simple_schema.version
        )
        
        assert cached is not None
        assert cached.schema_id == simple_schema.schema_id
        assert cached.version == simple_schema.version
    
    def test_get_cached_schema_not_found(self, validator):
        """Test retrieving a non-existent cached schema."""
        cached = validator.get_cached_schema("nonexistent", "1.0.0")
        
        assert cached is None
    
    def test_clear_cache(self, validator, simple_schema, complex_schema):
        """Test clearing the schema cache."""
        validator.cache_schema(simple_schema)
        validator.cache_schema(complex_schema)
        
        assert len(validator._schema_cache) == 2
        
        validator.clear_cache()
        
        assert len(validator._schema_cache) == 0
    
    def test_cache_disabled(self, simple_schema):
        """Test validator with caching disabled."""
        validator = SchemaValidator(cache_schemas=False)
        
        validator.cache_schema(simple_schema)
        
        # Cache should remain empty
        assert len(validator._schema_cache) == 0
        
        cached = validator.get_cached_schema(
            simple_schema.schema_id,
            simple_schema.version
        )
        assert cached is None
    
    def test_get_cache_stats(self, validator, simple_schema, complex_schema):
        """Test getting cache statistics."""
        stats = validator.get_cache_stats()
        
        assert stats["enabled"] is True
        assert stats["cached_schemas"] == 0
        assert len(stats["schema_keys"]) == 0
        
        validator.cache_schema(simple_schema)
        validator.cache_schema(complex_schema)
        
        stats = validator.get_cache_stats()
        
        assert stats["cached_schemas"] == 2
        assert len(stats["schema_keys"]) == 2


class TestBatchValidationResult:
    """Tests for BatchValidationResult class."""
    
    def test_batch_result_to_dict(self, validator, simple_schema):
        """Test BatchValidationResult serialization."""
        rows = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"}
        ]
        
        result = validator.validate_batch(rows, simple_schema)
        result_dict = result.to_dict()
        
        assert result_dict["total_rows"] == 2
        assert result_dict["valid_rows"] == 2
        assert result_dict["invalid_rows"] == 0
        assert "overall_quality_score" in result_dict
        assert "validated_at" in result_dict
        assert "schema_id" in result_dict
        assert "schema_version" in result_dict
        assert "validation_results" in result_dict
        assert len(result_dict["validation_results"]) == 2


class TestQualityScores:
    """Tests for quality score calculation."""
    
    def test_quality_score_perfect(self, validator, simple_schema):
        """Test quality score for perfect row."""
        row = {
            "id": 1,
            "name": "Alice",
            "email": "alice@example.com"
        }
        
        result = validator.validate(row, simple_schema)
        
        assert result.quality_score == 1.0
    
    def test_quality_score_missing_optional(self, validator, simple_schema):
        """Test quality score with missing optional field."""
        row = {
            "id": 1,
            "name": "Alice"
            # Missing optional 'email'
        }
        
        result = validator.validate(row, simple_schema)
        
        assert result.is_valid
        assert result.quality_score < 1.0  # Reduced due to missing optional
    
    def test_quality_score_invalid(self, validator, simple_schema):
        """Test quality score for invalid row."""
        row = {
            "id": "not_int",
            "name": "Alice"
        }
        
        result = validator.validate(row, simple_schema)
        
        assert not result.is_valid
        assert result.quality_score <= 0.5
    
    def test_batch_quality_score_aggregation(self, validator, simple_schema):
        """Test batch quality score aggregation."""
        rows = [
            {"id": 1, "name": "Alice", "email": "alice@example.com"},  # 1.0
            {"id": 2, "name": "Bob"},  # < 1.0 (missing optional)
            {"id": "not_int", "name": "Charlie"}  # Low score (invalid)
        ]
        
        result = validator.validate_batch(rows, simple_schema)
        
        # Overall score should be average of individual scores
        individual_scores = [r.quality_score for r in result.validation_results]
        expected_avg = sum(individual_scores) / len(individual_scores)
        
        assert abs(result.overall_quality_score - expected_avg) < 0.01


class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_validate_empty_row(self, validator, simple_schema):
        """Test validation of empty row."""
        row = {}
        
        result = validator.validate(row, simple_schema)
        
        assert not result.is_valid
        assert len(result.violations) > 0
    
    def test_validate_row_with_extra_fields(self, validator, simple_schema):
        """Test validation of row with extra unknown fields."""
        row = {
            "id": 1,
            "name": "Alice",
            "email": "alice@example.com",
            "unknown_field": "value",
            "another_unknown": 123
        }
        
        result = validator.validate(row, simple_schema)
        
        # Should be valid but with warnings
        assert result.is_valid
        assert len(result.warnings) > 0
    
    def test_validate_batch_single_row(self, validator, simple_schema):
        """Test batch validation with single row."""
        rows = [{"id": 1, "name": "Alice"}]
        
        result = validator.validate_batch(rows, simple_schema)
        
        assert result.total_rows == 1
        assert result.valid_rows == 1
        assert len(result.validation_results) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
