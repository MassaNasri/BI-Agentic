"""
Unit tests for Schema Versioning functionality.

Tests cover:
- Version comparison
- Schema evolution detection
- Backward compatibility analysis
- Semantic version parsing and comparison
- Field-level change detection
"""
import pytest
from datetime import datetime
from .schema_contract import (
    DataType,
    ConstraintType,
    Constraint,
    FieldDefinition,
    SchemaContract,
    SchemaVersionComparator
)


class TestSchemaVersionComparator:
    """Tests for SchemaVersionComparator class."""
    
    def test_no_changes(self):
        """Test comparison when schemas are identical."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False)
            ]
        )
        
        schema_v1_copy = SchemaContract(
            schema_id="user_schema",
            version="1.0.1",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False)
            ]
        )
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v1_copy)
        
        assert evolution.schema_id == "user_schema"
        assert evolution.from_version == "1.0.0"
        assert evolution.to_version == "1.0.1"
        assert evolution.change_type == "NO_CHANGE"
        assert evolution.backward_compatible is True
        assert "No changes detected" in evolution.changes
    
    def test_added_nullable_field(self):
        """Test adding a nullable field (backward compatible)."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False)
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="1.1.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False),
                FieldDefinition(name="email", type=DataType.STRING, nullable=True)
            ]
        )
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v2)
        
        assert evolution.change_type == "ADDITION"
        assert evolution.backward_compatible is True
        assert any("Added field 'email'" in change for change in evolution.changes)

    def test_added_non_nullable_field_without_default(self):
        """Test adding non-nullable field without default (breaks compatibility)."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="2.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="email", type=DataType.STRING, nullable=False)
            ]
        )
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v2)
        
        assert evolution.change_type == "ADDITION"
        assert evolution.backward_compatible is False
        assert any("WARNING" in change and "breaks backward compatibility" in change 
                   for change in evolution.changes)
    
    def test_added_non_nullable_field_with_default(self):
        """Test adding non-nullable field with default (backward compatible)."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="1.1.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(
                    name="status",
                    type=DataType.STRING,
                    nullable=False,
                    default_value="active"
                )
            ]
        )
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v2)
        
        assert evolution.change_type == "ADDITION"
        assert evolution.backward_compatible is True
    
    def test_removed_field(self):
        """Test removing a field (breaks compatibility)."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="legacy_field", type=DataType.STRING, nullable=True)
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="2.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)
            ]
        )
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v2)
        
        assert evolution.change_type == "DELETION"
        assert evolution.backward_compatible is False
        assert any("Removed field 'legacy_field'" in change for change in evolution.changes)
    
    def test_field_type_change(self):
        """Test changing field type (breaks compatibility)."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="age", type=DataType.INTEGER, nullable=False)
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="2.0.0",
            fields=[
                FieldDefinition(name="age", type=DataType.STRING, nullable=False)
            ]
        )
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v2)
        
        assert evolution.change_type == "MODIFICATION"
        assert evolution.backward_compatible is False
        assert any("type changed from integer to string" in change 
                   for change in evolution.changes)
    
    def test_field_nullable_to_non_nullable(self):
        """Test changing field from nullable to non-nullable (breaks compatibility)."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="email", type=DataType.STRING, nullable=True)
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="2.0.0",
            fields=[
                FieldDefinition(name="email", type=DataType.STRING, nullable=False)
            ]
        )
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v2)
        
        assert evolution.change_type == "MODIFICATION"
        assert evolution.backward_compatible is False
        assert any("nullable to non-nullable" in change for change in evolution.changes)
    
    def test_field_non_nullable_to_nullable(self):
        """Test changing field from non-nullable to nullable (backward compatible)."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="email", type=DataType.STRING, nullable=False)
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="1.1.0",
            fields=[
                FieldDefinition(name="email", type=DataType.STRING, nullable=True)
            ]
        )
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v2)
        
        assert evolution.change_type == "MODIFICATION"
        assert evolution.backward_compatible is True
        assert any("non-nullable to nullable" in change for change in evolution.changes)

    def test_added_constraint(self):
        """Test adding a constraint (breaks compatibility)."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="age", type=DataType.INTEGER, nullable=False)
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="2.0.0",
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
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v2)
        
        assert evolution.change_type == "MODIFICATION"
        assert evolution.backward_compatible is False
        assert any("added min constraint" in change for change in evolution.changes)
        assert any("added max constraint" in change for change in evolution.changes)
    
    def test_removed_constraint(self):
        """Test removing a constraint (backward compatible)."""
        schema_v1 = SchemaContract(
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
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="1.1.0",
            fields=[
                FieldDefinition(
                    name="age",
                    type=DataType.INTEGER,
                    nullable=False,
                    constraints=[
                        Constraint(ConstraintType.MIN, 0)
                    ]
                )
            ]
        )
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v2)
        
        assert evolution.change_type == "MODIFICATION"
        assert evolution.backward_compatible is True
        assert any("removed max constraint" in change for change in evolution.changes)
    
    def test_more_restrictive_min_constraint(self):
        """Test making MIN constraint more restrictive (breaks compatibility)."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(
                    name="age",
                    type=DataType.INTEGER,
                    nullable=False,
                    constraints=[Constraint(ConstraintType.MIN, 0)]
                )
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="2.0.0",
            fields=[
                FieldDefinition(
                    name="age",
                    type=DataType.INTEGER,
                    nullable=False,
                    constraints=[Constraint(ConstraintType.MIN, 18)]
                )
            ]
        )
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v2)
        
        assert evolution.backward_compatible is False
        assert any("min constraint changed from 0 to 18" in change 
                   for change in evolution.changes)
    
    def test_complex_schema_evolution(self):
        """Test complex schema with multiple changes."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False),
                FieldDefinition(name="legacy_field", type=DataType.STRING, nullable=True)
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="2.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=True),
                FieldDefinition(name="email", type=DataType.STRING, nullable=True)
            ]
        )
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v2)
        
        assert any("Added field 'email'" in change for change in evolution.changes)
        assert any("Removed field 'legacy_field'" in change for change in evolution.changes)
        assert any("non-nullable to nullable" in change for change in evolution.changes)
        assert evolution.backward_compatible is False
    
    def test_different_schema_ids_raises_error(self):
        """Test that comparing schemas with different IDs raises error."""
        schema1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[]
        )
        
        schema2 = SchemaContract(
            schema_id="product_schema",
            version="1.0.0",
            fields=[]
        )
        
        with pytest.raises(ValueError, match="Cannot compare schemas with different IDs"):
            SchemaVersionComparator.compare_versions(schema1, schema2)


class TestSchemaCompatibility:
    """Tests for schema compatibility checking."""
    
    def test_is_compatible_true(self):
        """Test is_compatible returns True for compatible changes."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="1.1.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="email", type=DataType.STRING, nullable=True)
            ]
        )
        
        assert SchemaVersionComparator.is_compatible(schema_v1, schema_v2) is True
    
    def test_is_compatible_false(self):
        """Test is_compatible returns False for breaking changes."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False)
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="2.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)
            ]
        )
        
        assert SchemaVersionComparator.is_compatible(schema_v1, schema_v2) is False


class TestSemanticVersioning:
    """Tests for semantic version parsing and comparison."""
    
    def test_parse_semantic_version_valid(self):
        """Test parsing valid semantic versions."""
        assert SchemaVersionComparator.parse_semantic_version("1.0.0") == (1, 0, 0)
        assert SchemaVersionComparator.parse_semantic_version("2.5.10") == (2, 5, 10)
        assert SchemaVersionComparator.parse_semantic_version("0.0.1") == (0, 0, 1)
    
    def test_parse_semantic_version_invalid(self):
        """Test parsing invalid semantic versions."""
        with pytest.raises(ValueError, match="Invalid semantic version"):
            SchemaVersionComparator.parse_semantic_version("1.0")
        
        with pytest.raises(ValueError, match="Invalid semantic version"):
            SchemaVersionComparator.parse_semantic_version("1.0.0.0")
        
        with pytest.raises(ValueError, match="Invalid semantic version"):
            SchemaVersionComparator.parse_semantic_version("invalid")
        
        with pytest.raises(ValueError, match="Invalid semantic version"):
            SchemaVersionComparator.parse_semantic_version("1.a.0")
    
    def test_compare_semantic_versions_equal(self):
        """Test comparing equal versions."""
        result = SchemaVersionComparator.compare_semantic_versions("1.0.0", "1.0.0")
        assert result == 0
    
    def test_compare_semantic_versions_less_than(self):
        """Test comparing when first version is less than second."""
        assert SchemaVersionComparator.compare_semantic_versions("1.0.0", "1.0.1") == -1
        assert SchemaVersionComparator.compare_semantic_versions("1.0.0", "1.1.0") == -1
        assert SchemaVersionComparator.compare_semantic_versions("1.0.0", "2.0.0") == -1
    
    def test_compare_semantic_versions_greater_than(self):
        """Test comparing when first version is greater than second."""
        assert SchemaVersionComparator.compare_semantic_versions("1.0.1", "1.0.0") == 1
        assert SchemaVersionComparator.compare_semantic_versions("1.1.0", "1.0.0") == 1
        assert SchemaVersionComparator.compare_semantic_versions("2.0.0", "1.0.0") == 1


class TestEvolutionRecordSerialization:
    """Tests for SchemaEvolutionRecord serialization."""
    
    def test_evolution_record_to_dict(self):
        """Test evolution record serialization."""
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)
            ]
        )
        
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="1.1.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="email", type=DataType.STRING, nullable=True)
            ]
        )
        
        evolution = SchemaVersionComparator.compare_versions(schema_v1, schema_v2)
        evolution_dict = evolution.to_dict()
        
        assert "evolution_id" in evolution_dict
        assert evolution_dict["schema_id"] == "user_schema"
        assert evolution_dict["from_version"] == "1.0.0"
        assert evolution_dict["to_version"] == "1.1.0"
        assert evolution_dict["change_type"] == "ADDITION"
        assert evolution_dict["backward_compatible"] is True
        assert isinstance(evolution_dict["changes"], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
