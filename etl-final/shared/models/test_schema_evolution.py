"""
Tests for Schema Evolution Detection module.

Tests cover:
- Schema inference from data samples
- Schema evolution detection
- Alert generation and management
- Confidence score calculation
"""
import pytest
from datetime import datetime
from typing import Dict, List, Any

from .schema_evolution import (
    SchemaInferenceEngine,
    SchemaEvolutionDetector,
    SchemaInferenceResult,
    SchemaChangeAlert
)
from .schema_contract import (
    SchemaContract,
    FieldDefinition,
    DataType,
    ConstraintType,
    Constraint
)


class TestSchemaInferenceEngine:
    """Tests for SchemaInferenceEngine class."""
    
    def test_infer_schema_basic(self):
        """Test basic schema inference from simple data."""
        engine = SchemaInferenceEngine(min_sample_size=10)
        
        rows = [
            {"id": 1, "name": "Alice", "age": 30},
            {"id": 2, "name": "Bob", "age": 25},
            {"id": 3, "name": "Charlie", "age": 35}
        ]
        
        result = engine.infer_schema(rows, "user_schema", "1.0.0")
        
        assert isinstance(result, SchemaInferenceResult)
        assert result.inferred_schema.schema_id == "user_schema"
        assert result.inferred_schema.version == "1.0.0"
        assert len(result.inferred_schema.fields) == 3
        assert result.sample_size == 3
        assert 0.0 <= result.confidence_score <= 1.0
    
    def test_infer_schema_with_nulls(self):
        """Test schema inference with null values."""
        engine = SchemaInferenceEngine()
        
        rows = [
            {"id": 1, "name": "Alice", "email": "alice@example.com"},
            {"id": 2, "name": "Bob", "email": None},
            {"id": 3, "name": "Charlie", "email": "charlie@example.com"}
        ]
        
        result = engine.infer_schema(rows, "user_schema")
        
        # Find email field
        email_field = next(f for f in result.inferred_schema.fields if f.name == "email")
        
        assert email_field.nullable is True
        assert result.field_statistics["email"]["null_count"] == 1
        assert result.field_statistics["email"]["non_null_count"] == 2
    
    def test_infer_data_types(self):
        """Test inference of different data types."""
        engine = SchemaInferenceEngine()
        
        rows = [
            {
                "int_field": 42,
                "float_field": 3.14,
                "str_field": "hello",
                "bool_field": True,
                "list_field": [1, 2, 3],
                "dict_field": {"key": "value"}
            }
        ]
        
        result = engine.infer_schema(rows, "test_schema")
        
        field_map = {f.name: f for f in result.inferred_schema.fields}
        
        assert field_map["int_field"].type == DataType.INTEGER
        assert field_map["float_field"].type == DataType.FLOAT
        assert field_map["str_field"].type == DataType.STRING
        assert field_map["bool_field"].type == DataType.BOOLEAN
        assert field_map["list_field"].type == DataType.ARRAY
        assert field_map["dict_field"].type == DataType.OBJECT
    
    def test_infer_date_timestamp_types(self):
        """Test inference of date and timestamp types from strings."""
        engine = SchemaInferenceEngine()
        
        rows = [
            {
                "date_field": "2024-01-15",
                "timestamp_field": "2024-01-15T10:30:00Z"
            }
        ] * 100  # Need enough samples for reliable inference
        
        result = engine.infer_schema(rows, "test_schema")
        
        field_map = {f.name: f for f in result.inferred_schema.fields}
        
        assert field_map["date_field"].type == DataType.DATE
        assert field_map["timestamp_field"].type == DataType.TIMESTAMP
    
    def test_infer_constraints_numeric(self):
        """Test inference of MIN/MAX constraints for numeric fields."""
        engine = SchemaInferenceEngine()
        
        rows = [
            {"age": 25},
            {"age": 30},
            {"age": 35}
        ]
        
        result = engine.infer_schema(rows, "test_schema")
        
        age_field = result.inferred_schema.fields[0]
        
        # Should have MIN and MAX constraints
        constraint_types = {c.constraint_type for c in age_field.constraints}
        assert ConstraintType.MIN in constraint_types
        assert ConstraintType.MAX in constraint_types
    
    def test_infer_constraints_enum(self):
        """Test inference of ENUM constraint for low cardinality fields."""
        engine = SchemaInferenceEngine()
        
        rows = [
            {"status": "active"},
            {"status": "inactive"},
            {"status": "active"},
            {"status": "pending"}
        ]
        
        result = engine.infer_schema(rows, "test_schema")
        
        status_field = result.inferred_schema.fields[0]
        
        # Should have ENUM constraint (only 3 unique values)
        enum_constraints = [c for c in status_field.constraints if c.constraint_type == ConstraintType.ENUM]
        assert len(enum_constraints) == 1
        assert set(enum_constraints[0].value) == {"active", "inactive", "pending"}
    
    def test_infer_schema_empty_data(self):
        """Test that inference fails with empty data."""
        engine = SchemaInferenceEngine()
        
        with pytest.raises(ValueError, match="Cannot infer schema from empty dataset"):
            engine.infer_schema([], "test_schema")
    
    def test_infer_schema_small_sample_warning(self):
        """Test warning for small sample size."""
        engine = SchemaInferenceEngine(min_sample_size=100)
        
        rows = [{"id": i} for i in range(10)]
        
        result = engine.infer_schema(rows, "test_schema")
        
        assert len(result.warnings) > 0
        assert "below recommended minimum" in result.warnings[0]
    
    def test_confidence_score_calculation(self):
        """Test confidence score calculation."""
        engine = SchemaInferenceEngine(min_sample_size=10)
        
        # High confidence: large sample, consistent types, no nulls
        good_rows = [{"id": i, "name": f"user{i}"} for i in range(100)]
        good_result = engine.infer_schema(good_rows, "good_schema")
        
        # Low confidence: small sample, mixed types, many nulls
        bad_rows = [
            {"id": 1, "value": "string"},
            {"id": 2, "value": 123},
            {"id": None, "value": None}
        ]
        bad_result = engine.infer_schema(bad_rows, "bad_schema")
        
        assert good_result.confidence_score > bad_result.confidence_score
    
    def test_field_statistics_collection(self):
        """Test collection of field statistics."""
        engine = SchemaInferenceEngine()
        
        rows = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": None}
        ]
        
        result = engine.infer_schema(rows, "test_schema")
        
        # Check statistics for 'name' field
        name_stats = result.field_statistics["name"]
        assert name_stats["present_count"] == 3
        assert name_stats["null_count"] == 1
        assert name_stats["non_null_count"] == 2
        assert name_stats["unique_count"] == 2


class TestSchemaEvolutionDetector:
    """Tests for SchemaEvolutionDetector class."""
    
    def test_detect_no_evolution(self):
        """Test detection when schema hasn't changed."""
        # Use inference engine that doesn't infer constraints
        class SimpleInferenceEngine(SchemaInferenceEngine):
            def _infer_constraints(self, stats, data_type):
                return []
        
        detector = SchemaEvolutionDetector(inference_engine=SimpleInferenceEngine())
        
        # Create current schema
        current_schema = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False)
            ]
        )
        
        # New data matches current schema
        new_data = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"}
        ]
        
        alert = detector.detect_evolution(current_schema, new_data)
        
        assert alert is None
    
    def test_detect_field_addition(self):
        """Test detection of new field addition."""
        # Use inference engine that doesn't infer constraints
        class SimpleInferenceEngine(SchemaInferenceEngine):
            def _infer_constraints(self, stats, data_type):
                return []
        
        detector = SchemaEvolutionDetector(inference_engine=SimpleInferenceEngine())
        
        # Current schema has 2 fields
        current_schema = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False)
            ]
        )
        
        # New data has additional field
        new_data = [
            {"id": 1, "name": "Alice", "email": "alice@example.com"},
            {"id": 2, "name": "Bob", "email": "bob@example.com"}
        ]
        
        alert = detector.detect_evolution(current_schema, new_data)
        
        assert alert is not None
        assert alert.schema_id == "user_schema"
        assert alert.old_version == "1.0.0"
        assert alert.evolution_record.change_type == "ADDITION"
        assert "email" in str(alert.evolution_record.changes)
    
    def test_detect_field_removal(self):
        """Test detection of field removal."""
        detector = SchemaEvolutionDetector()
        
        # Current schema has 3 fields
        current_schema = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False),
                FieldDefinition(name="email", type=DataType.STRING, nullable=False)
            ]
        )
        
        # New data missing email field
        new_data = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"}
        ]
        
        alert = detector.detect_evolution(current_schema, new_data)
        
        assert alert is not None
        assert alert.evolution_record.change_type == "DELETION"
        assert not alert.evolution_record.backward_compatible
        assert alert.severity == "ERROR"
    
    def test_detect_type_change(self):
        """Test detection of field type change."""
        detector = SchemaEvolutionDetector()
        
        # Current schema has integer age
        current_schema = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="age", type=DataType.INTEGER, nullable=False)
            ]
        )
        
        # New data has string age
        new_data = [
            {"id": 1, "age": "30"},
            {"id": 2, "age": "25"}
        ]
        
        alert = detector.detect_evolution(current_schema, new_data)
        
        assert alert is not None
        assert alert.evolution_record.change_type == "MODIFICATION"
        assert not alert.evolution_record.backward_compatible
    
    def test_auto_versioning_backward_compatible(self):
        """Test automatic version calculation for backward compatible changes."""
        # Use inference engine that doesn't infer constraints
        class SimpleInferenceEngine(SchemaInferenceEngine):
            def _infer_constraints(self, stats, data_type):
                return []
        
        detector = SchemaEvolutionDetector(inference_engine=SimpleInferenceEngine())
        
        current_schema = SchemaContract(
            schema_id="user_schema",
            version="1.2.3",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)
            ]
        )
        
        # Add nullable field (backward compatible)
        new_data = [
            {"id": 1, "email": "alice@example.com"},
            {"id": 2, "email": None}
        ]
        
        alert = detector.detect_evolution(current_schema, new_data, auto_version=True)
        
        assert alert is not None
        assert alert.new_version == "1.3.0"  # Minor version bump
        assert alert.evolution_record.backward_compatible
    
    def test_auto_versioning_breaking_change(self):
        """Test automatic version calculation for breaking changes."""
        detector = SchemaEvolutionDetector()
        
        current_schema = SchemaContract(
            schema_id="user_schema",
            version="1.2.3",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="email", type=DataType.STRING, nullable=False)
            ]
        )
        
        # Remove field (breaking change)
        new_data = [
            {"id": 1},
            {"id": 2}
        ]
        
        alert = detector.detect_evolution(current_schema, new_data, auto_version=True)
        
        assert alert is not None
        assert alert.new_version == "2.0.0"  # Major version bump
        assert not alert.evolution_record.backward_compatible
    
    def test_severity_determination(self):
        """Test alert severity determination."""
        # Use inference engine that doesn't infer constraints
        class SimpleInferenceEngine(SchemaInferenceEngine):
            def _infer_constraints(self, stats, data_type):
                return []
        
        detector = SchemaEvolutionDetector(inference_engine=SimpleInferenceEngine())
        
        base_schema = SchemaContract(
            schema_id="test_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)
            ]
        )
        
        # INFO: Backward compatible addition
        data_addition = [{"id": 1, "new_field": "value"}]
        alert_info = detector.detect_evolution(base_schema, data_addition)
        assert alert_info.severity == "INFO"
        
        # ERROR: Breaking change (field removal)
        schema_with_field = SchemaContract(
            schema_id="test_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="required_field", type=DataType.STRING, nullable=False)
            ]
        )
        data_removal = [{"id": 1}]
        alert_error = detector.detect_evolution(schema_with_field, data_removal)
        assert alert_error.severity == "ERROR"
    
    def test_alert_history(self):
        """Test alert history tracking."""
        detector = SchemaEvolutionDetector()
        
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)]
        )
        
        # Generate multiple alerts
        data1 = [{"id": 1, "field1": "value"}]
        alert1 = detector.detect_evolution(schema_v1, data1)
        
        data2 = [{"id": 1, "field1": "value", "field2": "value"}]
        alert2 = detector.detect_evolution(schema_v1, data2)
        
        history = detector.get_alert_history()
        assert len(history) == 2
        assert alert1 in history
        assert alert2 in history
    
    def test_alert_history_filtering(self):
        """Test filtering of alert history."""
        detector = SchemaEvolutionDetector()
        
        schema1 = SchemaContract(
            schema_id="schema1",
            version="1.0.0",
            fields=[FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)]
        )
        
        schema2 = SchemaContract(
            schema_id="schema2",
            version="1.0.0",
            fields=[FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)]
        )
        
        # Generate alerts for different schemas
        detector.detect_evolution(schema1, [{"id": 1, "new_field": "value"}])
        detector.detect_evolution(schema2, [{"id": 1, "new_field": "value"}])
        
        # Filter by schema_id
        schema1_alerts = detector.get_alert_history(schema_id="schema1")
        assert len(schema1_alerts) == 1
        assert schema1_alerts[0].schema_id == "schema1"
    
    def test_acknowledge_alert(self):
        """Test alert acknowledgment."""
        detector = SchemaEvolutionDetector()
        
        schema = SchemaContract(
            schema_id="test_schema",
            version="1.0.0",
            fields=[FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)]
        )
        
        alert = detector.detect_evolution(schema, [{"id": 1, "new_field": "value"}])
        
        assert alert.acknowledged is False
        
        success = detector.acknowledge_alert(alert.alert_id)
        assert success is True
        assert alert.acknowledged is True
    
    def test_acknowledge_nonexistent_alert(self):
        """Test acknowledging non-existent alert."""
        detector = SchemaEvolutionDetector()
        
        success = detector.acknowledge_alert("nonexistent-id")
        assert success is False
    
    def test_clear_alert_history(self):
        """Test clearing alert history."""
        detector = SchemaEvolutionDetector()
        
        schema = SchemaContract(
            schema_id="test_schema",
            version="1.0.0",
            fields=[FieldDefinition(name="id", type=DataType.INTEGER, nullable=False)]
        )
        
        detector.detect_evolution(schema, [{"id": 1, "new_field": "value"}])
        assert len(detector.get_alert_history()) == 1
        
        detector.clear_alert_history()
        assert len(detector.get_alert_history()) == 0


class TestSchemaChangeAlert:
    """Tests for SchemaChangeAlert class."""
    
    def test_alert_creation(self):
        """Test creating a schema change alert."""
        from .schema_contract import SchemaEvolutionRecord
        
        evolution_record = SchemaEvolutionRecord(
            schema_id="test_schema",
            from_version="1.0.0",
            to_version="1.1.0",
            changes=["Added field 'email'"],
            change_type="ADDITION",
            backward_compatible=True
        )
        
        alert = SchemaChangeAlert(
            alert_id="alert-123",
            schema_id="test_schema",
            old_version="1.0.0",
            new_version="1.1.0",
            evolution_record=evolution_record,
            severity="INFO"
        )
        
        assert alert.alert_id == "alert-123"
        assert alert.schema_id == "test_schema"
        assert alert.old_version == "1.0.0"
        assert alert.new_version == "1.1.0"
        assert alert.severity == "INFO"
        assert alert.acknowledged is False
    
    def test_alert_to_dict(self):
        """Test converting alert to dictionary."""
        from .schema_contract import SchemaEvolutionRecord
        
        evolution_record = SchemaEvolutionRecord(
            schema_id="test_schema",
            from_version="1.0.0",
            to_version="1.1.0",
            changes=["Added field 'email'"],
            change_type="ADDITION",
            backward_compatible=True
        )
        
        alert = SchemaChangeAlert(
            alert_id="alert-123",
            schema_id="test_schema",
            old_version="1.0.0",
            new_version="1.1.0",
            evolution_record=evolution_record,
            severity="INFO"
        )
        
        alert_dict = alert.to_dict()
        
        assert alert_dict["alert_id"] == "alert-123"
        assert alert_dict["schema_id"] == "test_schema"
        assert alert_dict["severity"] == "INFO"
        assert "evolution_record" in alert_dict
        assert "detected_at" in alert_dict


class TestIntegration:
    """Integration tests for schema evolution detection."""
    
    def test_end_to_end_evolution_detection(self):
        """Test complete workflow of schema evolution detection."""
        # Use inference engine that doesn't infer constraints
        class SimpleInferenceEngine(SchemaInferenceEngine):
            def _infer_constraints(self, stats, data_type):
                return []
        
        # Step 1: Create initial schema
        initial_schema = SchemaContract(
            schema_id="product_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False),
                FieldDefinition(name="price", type=DataType.FLOAT, nullable=False)
            ]
        )
        
        # Step 2: Simulate new data with additional field
        new_data = [
            {"id": 1, "name": "Product A", "price": 19.99, "category": "Electronics"},
            {"id": 2, "name": "Product B", "price": 29.99, "category": "Books"},
            {"id": 3, "name": "Product C", "price": 39.99, "category": "Electronics"}
        ]
        
        # Step 3: Detect evolution
        detector = SchemaEvolutionDetector(inference_engine=SimpleInferenceEngine())
        alert = detector.detect_evolution(initial_schema, new_data, auto_version=True)
        
        # Step 4: Verify results
        assert alert is not None
        assert alert.schema_id == "product_schema"
        assert alert.old_version == "1.0.0"
        assert alert.new_version == "1.1.0"  # Minor version bump
        assert alert.evolution_record.backward_compatible
        assert alert.severity == "INFO"
        assert "category" in str(alert.evolution_record.changes)
        
        # Step 5: Acknowledge alert
        detector.acknowledge_alert(alert.alert_id)
        assert alert.acknowledged is True
    
    def test_multiple_evolution_cycles(self):
        """Test multiple cycles of schema evolution."""
        # Use inference engine that doesn't infer constraints
        class SimpleInferenceEngine(SchemaInferenceEngine):
            def _infer_constraints(self, stats, data_type):
                return []
        
        detector = SchemaEvolutionDetector(inference_engine=SimpleInferenceEngine())
        
        # Version 1.0.0
        schema_v1 = SchemaContract(
            schema_id="user_schema",
            version="1.0.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False)
            ]
        )
        
        # Evolution 1: Add email field (1.0.0 -> 1.1.0)
        data_v2 = [
            {"id": 1, "name": "Alice", "email": "alice@example.com"}
        ]
        alert1 = detector.detect_evolution(schema_v1, data_v2, auto_version=True)
        assert alert1.new_version == "1.1.0"
        
        # Evolution 2: Add phone field (1.1.0 -> 1.2.0)
        schema_v2 = SchemaContract(
            schema_id="user_schema",
            version="1.1.0",
            fields=[
                FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                FieldDefinition(name="name", type=DataType.STRING, nullable=False),
                FieldDefinition(name="email", type=DataType.STRING, nullable=True)
            ]
        )
        
        data_v3 = [
            {"id": 1, "name": "Alice", "email": "alice@example.com", "phone": "123-456-7890"}
        ]
        alert2 = detector.detect_evolution(schema_v2, data_v3, auto_version=True)
        assert alert2.new_version == "1.2.0"
        
        # Verify history
        history = detector.get_alert_history(schema_id="user_schema")
        assert len(history) == 2
