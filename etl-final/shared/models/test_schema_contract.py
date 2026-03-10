"""
Unit tests for Schema Contract data models.

Tests cover:
- Data type validation
- Constraint validation
- Field definition validation
- Schema contract validation
- Serialization/deserialization
- Schema evolution tracking
"""
import pytest
from datetime import datetime
from uuid import UUID
from .schema_contract import (
    DataType,
    ConstraintType,
    Constraint,
    FieldDefinition,
    SchemaContract,
    ValidationResult,
    SchemaEvolutionRecord
)


class TestConstraint:
    """Tests for Constraint class."""
    
    def test_min_constraint_numeric(self):
        """Test MIN constraint on numeric values."""
        constraint = Constraint(
            constraint_type=ConstraintType.MIN,
            value=10
        )
        
        # Valid
        is_valid, error = constraint.validate(15, "age")
        assert is_valid
        assert error is None
        
        # Invalid
        is_valid, error = constraint.validate(5, "age")
        assert not is_valid
        assert "age must be >= 10" in error
    
    def test_min_constraint_string_length(self):
        """Test MIN constraint on string length."""
        constraint = Constraint(
            constraint_type=ConstraintType.MIN,
            value=5
        )
        
        # Valid
        is_valid, error = constraint.validate("hello", "name")
        assert is_valid
        
        # Invalid
        is_valid, error = constraint.validate("hi", "name")
        assert not is_valid
        assert "name must be >= 5" in error
    
    def test_max_constraint_numeric(self):
        """Test MAX constraint on numeric values."""
        constraint = Constraint(
            constraint_type=ConstraintType.MAX,
            value=100
        )
        
        # Valid
        is_valid, error = constraint.validate(50, "score")
        assert is_valid
        
        # Invalid
        is_valid, error = constraint.validate(150, "score")
        assert not is_valid
        assert "score must be <= 100" in error
    
    def test_regex_constraint(self):
        """Test REGEX constraint."""
        constraint = Constraint(
            constraint_type=ConstraintType.REGEX,
            value=r'^[A-Z]{3}-\d{4}$'
        )
        
        # Valid
        is_valid, error = constraint.validate("ABC-1234", "code")
        assert is_valid
        
        # Invalid
        is_valid, error = constraint.validate("abc-1234", "code")
        assert not is_valid
        assert "does not match pattern" in error
    
    def test_enum_constraint(self):
        """Test ENUM constraint."""
        constraint = Constraint(
            constraint_type=ConstraintType.ENUM,
            value=["active", "inactive", "pending"]
        )
        
        # Valid
        is_valid, error = constraint.validate("active", "status")
        assert is_valid
        
        # Invalid
        is_valid, error = constraint.validate("deleted", "status")
        assert not is_valid
        assert "must be one of" in error
    
    def test_format_email_constraint(self):
        """Test FORMAT constraint for email."""
        constraint = Constraint(
            constraint_type=ConstraintType.FORMAT,
            value="email"
        )
        
        # Valid
        is_valid, error = constraint.validate("user@example.com", "email")
        assert is_valid
        
        # Invalid
        is_valid, error = constraint.validate("not-an-email", "email")
        assert not is_valid
        assert "valid email" in error
    
    def test_format_url_constraint(self):
        """Test FORMAT constraint for URL."""
        constraint = Constraint(
            constraint_type=ConstraintType.FORMAT,
            value="url"
        )
        
        # Valid
        is_valid, error = constraint.validate("https://example.com", "website")
        assert is_valid
        
        # Invalid
        is_valid, error = constraint.validate("not-a-url", "website")
        assert not is_valid
        assert "valid URL" in error
    
    def test_range_constraint(self):
        """Test RANGE constraint."""
        constraint = Constraint(
            constraint_type=ConstraintType.RANGE,
            value=[0, 100]
        )
        
        # Valid
        is_valid, error = constraint.validate(50, "percentage")
        assert is_valid
        
        # Invalid - below range
        is_valid, error = constraint.validate(-10, "percentage")
        assert not is_valid
        assert "between 0 and 100" in error
        
        # Invalid - above range
        is_valid, error = constraint.validate(150, "percentage")
        assert not is_valid
    
    def test_custom_error_message(self):
        """Test custom error messages."""
        constraint = Constraint(
            constraint_type=ConstraintType.MIN,
            value=18,
            error_message="Must be at least 18 years old"
        )
        
        is_valid, error = constraint.validate(15, "age")
        assert not is_valid
        assert error == "Must be at least 18 years old"


class TestFieldDefinition:
    """Tests for FieldDefinition class."""
    
    def test_string_type_validation(self):
        """Test STRING type validation."""
        field = FieldDefinition(name="name", type=DataType.STRING)
        
        # Valid
        is_valid, error = field.validate_type("John Doe")
        assert is_valid
        
        # Invalid
        is_valid, error = field.validate_type(123)
        assert not is_valid
        assert "must be string" in error
    
    def test_integer_type_validation(self):
        """Test INTEGER type validation."""
        field = FieldDefinition(name="age", type=DataType.INTEGER)
        
        # Valid
        is_valid, error = field.validate_type(25)
        assert is_valid
        
        # Invalid - float
        is_valid, error = field.validate_type(25.5)
        assert not is_valid
        
        # Invalid - boolean (special case)
        is_valid, error = field.validate_type(True)
        assert not is_valid
    
    def test_float_type_validation(self):
        """Test FLOAT type validation."""
        field = FieldDefinition(name="price", type=DataType.FLOAT)
        
        # Valid - float
        is_valid, error = field.validate_type(19.99)
        assert is_valid
        
        # Valid - integer (can be coerced)
        is_valid, error = field.validate_type(20)
        assert is_valid
        
        # Invalid - boolean
        is_valid, error = field.validate_type(True)
        assert not is_valid
    
    def test_boolean_type_validation(self):
        """Test BOOLEAN type validation."""
        field = FieldDefinition(name="active", type=DataType.BOOLEAN)
        
        # Valid
        is_valid, error = field.validate_type(True)
        assert is_valid
        
        is_valid, error = field.validate_type(False)
        assert is_valid
        
        # Invalid
        is_valid, error = field.validate_type("true")
        assert not is_valid
    
    def test_date_type_validation(self):
        """Test DATE type validation."""
        field = FieldDefinition(name="birth_date", type=DataType.DATE)
        
        # Valid - datetime object
        is_valid, error = field.validate_type(datetime.now())
        assert is_valid
        
        # Valid - ISO date string
        is_valid, error = field.validate_type("2024-01-15")
        assert is_valid
        
        # Invalid - bad format
        is_valid, error = field.validate_type("15/01/2024")
        assert not is_valid
    
    def test_timestamp_type_validation(self):
        """Test TIMESTAMP type validation."""
        field = FieldDefinition(name="created_at", type=DataType.TIMESTAMP)
        
        # Valid - datetime object
        is_valid, error = field.validate_type(datetime.now())
        assert is_valid
        
        # Valid - ISO timestamp string
        is_valid, error = field.validate_type("2024-01-15T10:30:00Z")
        assert is_valid
        
        # Invalid
        is_valid, error = field.validate_type("not a timestamp")
        assert not is_valid
    
    def test_array_type_validation(self):
        """Test ARRAY type validation."""
        field = FieldDefinition(name="tags", type=DataType.ARRAY)
        
        # Valid
        is_valid, error = field.validate_type(["tag1", "tag2"])
        assert is_valid
        
        # Invalid
        is_valid, error = field.validate_type("not an array")
        assert not is_valid
    
    def test_object_type_validation(self):
        """Test OBJECT type validation."""
        field = FieldDefinition(name="metadata", type=DataType.OBJECT)
        
        # Valid
        is_valid, error = field.validate_type({"key": "value"})
        assert is_valid
        
        # Invalid
        is_valid, error = field.validate_type("not an object")
        assert not is_valid
    
    def test_nullable_field(self):
        """Test nullable field validation."""
        field = FieldDefinition(name="optional", type=DataType.STRING, nullable=True)
        
        # Valid - None is allowed
        is_valid, errors = field.validate(None)
        assert is_valid
        assert len(errors) == 0
    
    def test_non_nullable_field(self):
        """Test non-nullable field validation."""
        field = FieldDefinition(name="required", type=DataType.STRING, nullable=False)
        
        # Invalid - None not allowed
        is_valid, errors = field.validate(None)
        assert not is_valid
        assert len(errors) > 0
        assert "cannot be null" in errors[0]
    
    def test_field_with_constraints(self):
        """Test field validation with multiple constraints."""
        field = FieldDefinition(
            name="username",
            type=DataType.STRING,
            nullable=False,
            constraints=[
                Constraint(ConstraintType.MIN, 3),
                Constraint(ConstraintType.MAX, 20),
                Constraint(ConstraintType.REGEX, r'^[a-zA-Z0-9_]+$')
            ]
        )
        
        # Valid
        is_valid, errors = field.validate("john_doe")
        assert is_valid
        
        # Invalid - too short
        is_valid, errors = field.validate("ab")
        assert not is_valid
        
        # Invalid - invalid characters
        is_valid, errors = field.validate("john@doe")
        assert not is_valid


class TestSchemaContract:
    """Tests for SchemaContract class."""
    
    def test_create_schema_contract(self):
        """Test creating a schema contract."""
        schema = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False),
                FieldDefinition(name="email", type=DataType.STRING, nullable=False)
            ],
            description="User data schema"
        )
        
        assert schema.schema_id == "user_schema"
        assert schema.version == "1.0.0"
        assert len(schema.fields) == 3
    
    def test_get_field(self):
        """Test getting field by name."""
        schema = SchemaContract(
            schema_id="test",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER),
                FieldDefinition(name="name", type=DataType.STRING)
            ]
        )
        
        field = schema.get_field("name")
        assert field is not None
        assert field.name == "name"
        
        field = schema.get_field("nonexistent")
        assert field is None
    
    def test_get_required_fields(self):
        """Test getting required fields."""
        schema = SchemaContract(
            schema_id="test",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False),
                FieldDefinition(name="email", type=DataType.STRING, nullable=True)
            ]
        )
        
        required = schema.get_required_fields()
        assert "id" in required
        assert "name" in required
        assert "email" not in required
    
    def test_validate_row_success(self):
        """Test successful row validation."""
        schema = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False),
                FieldDefinition(name="age", type=DataType.INTEGER, nullable=True)
            ]
        )
        
        row = {
            "id": 1,
            "name": "John Doe",
            "age": 30
        }
        
        result = schema.validate_row(row)
        assert result.is_valid
        assert len(result.violations) == 0
        assert result.quality_score > 0.9
    
    def test_validate_row_missing_required_field(self):
        """Test validation with missing required field."""
        schema = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False)
            ]
        )
        
        row = {
            "id": 1
            # Missing 'name'
        }
        
        result = schema.validate_row(row)
        assert not result.is_valid
        assert len(result.violations) > 0
        assert any("name" in v and "missing" in v for v in result.violations)
    
    def test_validate_row_type_mismatch(self):
        """Test validation with type mismatch."""
        schema = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="age", type=DataType.INTEGER, nullable=True)
            ]
        )
        
        row = {
            "id": 1,
            "age": "thirty"  # Should be integer
        }
        
        result = schema.validate_row(row)
        assert not result.is_valid
        assert len(result.violations) > 0
        assert any("age" in v and "integer" in v for v in result.violations)
    
    def test_validate_row_constraint_violation(self):
        """Test validation with constraint violation."""
        schema = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(
                    name="age",
                    type=DataType.INTEGER,
                    nullable=False,
                    constraints=[
                        Constraint(ConstraintType.MIN, 0),
                        Constraint(ConstraintType.MAX, 150)
                    ]
                )
            ]
        )
        
        row = {"age": 200}  # Exceeds max
        
        result = schema.validate_row(row)
        assert not result.is_valid
        assert len(result.violations) > 0
    
    def test_validate_row_unknown_field_warning(self):
        """Test validation with unknown field (should warn, not error)."""
        schema = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)
            ]
        )
        
        row = {
            "id": 1,
            "unknown_field": "value"
        }
        
        result = schema.validate_row(row)
        assert result.is_valid  # Unknown fields don't fail validation
        assert len(result.warnings) > 0
        assert any("unknown_field" in w for w in result.warnings)
    
    def test_schema_serialization(self):
        """Test schema contract serialization to dict."""
        schema = SchemaContract(
            schema_id="test_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(
                    name="id",
                    type=DataType.INTEGER,
                    nullable=False,
                    constraints=[Constraint(ConstraintType.MIN, 1)]
                )
            ],
            description="Test schema"
        )
        
        schema_dict = schema.to_dict()
        
        assert schema_dict["schema_id"] == "test_schema"
        assert schema_dict["version"] == "1.0.0"
        assert len(schema_dict["fields"]) == 1
        assert schema_dict["fields"][0]["name"] == "id"
    
    def test_schema_deserialization(self):
        """Test schema contract deserialization from dict."""
        schema_dict = {
            "schema_id": "test_schema",
            "version": "1.0.0",
            "description": "Test schema",
            "created_at": datetime.utcnow().isoformat(),
            "created_by": "test_user",
            "fields": [
                {
                    "name": "id",
                    "type": "integer",
                    "nullable": False,
                    "description": "User ID",
                    "default_value": None,
                    "constraints": [
                        {
                            "type": "min",
                            "value": 1,
                            "error_message": None,
                            "severity": "error"
                        }
                    ],
                    "metadata": {}
                }
            ],
            "constraints": [],
            "metadata": {}
        }
        
        schema = SchemaContract.from_dict(schema_dict)
        
        assert schema.schema_id == "test_schema"
        assert schema.version == "1.0.0"
        assert len(schema.fields) == 1
        assert schema.fields[0].name == "id"
        assert schema.fields[0].type == DataType.INTEGER
        assert len(schema.fields[0].constraints) == 1


class TestValidationResult:
    """Tests for ValidationResult class."""
    
    def test_create_validation_result(self):
        """Test creating a validation result."""
        result = ValidationResult(
            is_valid=True,
            violations=[],
            warnings=["Minor issue"],
            quality_score=0.95,
            field_scores={"id": 1.0, "name": 0.9},
            schema_id="test_schema",
            schema_version="1.0.0"
        )
        
        assert result.is_valid
        assert result.quality_score == 0.95
        assert len(result.warnings) == 1
    
    def test_validation_result_serialization(self):
        """Test validation result serialization."""
        result = ValidationResult(
            is_valid=False,
            violations=["Field 'age' is required"],
            warnings=[],
            quality_score=0.5,
            schema_id="user_schema",
            schema_version="1.0.0"
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["is_valid"] is False
        assert len(result_dict["violations"]) == 1
        assert result_dict["quality_score"] == 0.5


class TestSchemaEvolutionRecord:
    """Tests for SchemaEvolutionRecord class."""
    
    def test_create_evolution_record(self):
        """Test creating a schema evolution record."""
        record = SchemaEvolutionRecord(
            schema_id="user_schema",
            from_version="1.0.0",
            to_version="1.1.0",
            changes=["Added field 'phone'"],
            change_type="ADDITION",
            backward_compatible=True,
            created_by="admin"
        )
        
        assert record.schema_id == "user_schema"
        assert record.from_version == "1.0.0"
        assert record.to_version == "1.1.0"
        assert record.backward_compatible
    
    def test_evolution_record_serialization(self):
        """Test evolution record serialization."""
        record = SchemaEvolutionRecord(
            schema_id="user_schema",
            from_version="1.0.0",
            to_version="2.0.0",
            changes=["Removed field 'legacy_id'"],
            change_type="DELETION",
            backward_compatible=False
        )
        
        record_dict = record.to_dict()
        
        assert record_dict["schema_id"] == "user_schema"
        assert record_dict["backward_compatible"] is False
        assert "evolution_id" in record_dict


class TestComplexScenarios:
    """Tests for complex validation scenarios."""
    
    def test_email_validation_schema(self):
        """Test schema with email validation."""
        schema = SchemaContract(
            schema_id="contact_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(
                    name="email",
                    type=DataType.STRING,
                    nullable=False,
                    constraints=[
                        Constraint(ConstraintType.FORMAT, "email")
                    ]
                )
            ]
        )
        
        # Valid email
        result = schema.validate_row({"email": "user@example.com"})
        assert result.is_valid
        
        # Invalid email
        result = schema.validate_row({"email": "not-an-email"})
        assert not result.is_valid
    
    def test_nested_constraints(self):
        """Test field with multiple constraints."""
        schema = SchemaContract(
            schema_id="product_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(
                    name="price",
                    type=DataType.FLOAT,
                    nullable=False,
                    constraints=[
                        Constraint(ConstraintType.MIN, 0.01),
                        Constraint(ConstraintType.MAX, 999999.99)
                    ]
                ),
                FieldDefinition(
                    name="sku",
                    type=DataType.STRING,
                    nullable=False,
                    constraints=[
                        Constraint(ConstraintType.REGEX, r'^[A-Z]{3}-\d{6}$')
                    ]
                )
            ]
        )
        
        # Valid product
        result = schema.validate_row({
            "price": 19.99,
            "sku": "ABC-123456"
        })
        assert result.is_valid
        
        # Invalid price
        result = schema.validate_row({
            "price": -5.00,
            "sku": "ABC-123456"
        })
        assert not result.is_valid
        
        # Invalid SKU format
        result = schema.validate_row({
            "price": 19.99,
            "sku": "invalid"
        })
        assert not result.is_valid
    
    def test_quality_score_calculation(self):
        """Test quality score calculation with partial validation."""
        schema = SchemaContract(
            schema_id="test_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="field1", type=DataType.STRING, nullable=False),
                FieldDefinition(name="field2", type=DataType.STRING, nullable=True),
                FieldDefinition(name="field3", type=DataType.STRING, nullable=True)
            ]
        )
        
        # All fields present and valid
        result = schema.validate_row({
            "field1": "value1",
            "field2": "value2",
            "field3": "value3"
        })
        assert result.quality_score == 1.0
        
        # Missing optional fields
        result = schema.validate_row({
            "field1": "value1"
        })
        assert result.is_valid
        assert result.quality_score < 1.0  # Reduced due to missing optional fields


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
