"""
Unit tests for TransformationRule data models.

Tests cover:
- RuleType enum
- TransformationRule validation and immutability
- TransformationResult validation
- RuleExecutionContext
- RuleExecutionRecord
"""
import pytest
from datetime import datetime
from uuid import UUID, uuid4
from transformation_rule import (
    RuleType,
    TransformationRule,
    TransformationResult,
    RuleExecutionContext,
    RuleExecutionRecord
)


class TestRuleType:
    """Tests for RuleType enum."""
    
    def test_rule_types_exist(self):
        """Test that all required rule types are defined."""
        assert RuleType.CLEAN.value == "CLEAN"
        assert RuleType.VALIDATE.value == "VALIDATE"
        assert RuleType.TRANSFORM.value == "TRANSFORM"
        assert RuleType.ENRICH.value == "ENRICH"
    
    def test_rule_type_count(self):
        """Test that exactly 4 rule types are defined."""
        assert len(RuleType) == 4


class TestTransformationRule:
    """Tests for TransformationRule data model."""
    
    def test_create_valid_rule(self):
        """Test creating a valid transformation rule."""
        rule = TransformationRule(
            rule_id="test_rule_v1",
            rule_type=RuleType.CLEAN,
            priority=1,
            condition=lambda row: True,
            action=lambda row: row,
            metadata={"description": "Test rule"}
        )
        
        assert rule.rule_id == "test_rule_v1"
        assert rule.rule_type == RuleType.CLEAN
        assert rule.priority == 1
        assert callable(rule.condition)
        assert callable(rule.action)
        assert rule.metadata["description"] == "Test rule"
    
    def test_rule_immutability(self):
        """Test that TransformationRule is immutable (frozen dataclass)."""
        rule = TransformationRule(
            rule_id="test_rule",
            rule_type=RuleType.CLEAN,
            priority=1,
            condition=lambda row: True,
            action=lambda row: row
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            rule.priority = 2
    
    def test_empty_rule_id_raises_error(self):
        """Test that empty rule_id raises ValueError."""
        with pytest.raises(ValueError, match="rule_id cannot be empty"):
            TransformationRule(
                rule_id="",
                rule_type=RuleType.CLEAN,
                priority=1,
                condition=lambda row: True,
                action=lambda row: row
            )
    
    def test_negative_priority_raises_error(self):
        """Test that negative priority raises ValueError."""
        with pytest.raises(ValueError, match="priority must be non-negative"):
            TransformationRule(
                rule_id="test_rule",
                rule_type=RuleType.CLEAN,
                priority=-1,
                condition=lambda row: True,
                action=lambda row: row
            )
    
    def test_non_callable_condition_raises_error(self):
        """Test that non-callable condition raises ValueError."""
        with pytest.raises(ValueError, match="condition must be callable"):
            TransformationRule(
                rule_id="test_rule",
                rule_type=RuleType.CLEAN,
                priority=1,
                condition="not a function",  # type: ignore
                action=lambda row: row
            )
    
    def test_non_callable_action_raises_error(self):
        """Test that non-callable action raises ValueError."""
        with pytest.raises(ValueError, match="action must be callable"):
            TransformationRule(
                rule_id="test_rule",
                rule_type=RuleType.CLEAN,
                priority=1,
                condition=lambda row: True,
                action="not a function"  # type: ignore
            )
    
    def test_default_metadata_is_empty_dict(self):
        """Test that metadata defaults to empty dict."""
        rule = TransformationRule(
            rule_id="test_rule",
            rule_type=RuleType.CLEAN,
            priority=1,
            condition=lambda row: True,
            action=lambda row: row
        )
        
        assert rule.metadata == {}
    
    def test_rule_with_all_rule_types(self):
        """Test creating rules with each rule type."""
        for rule_type in RuleType:
            rule = TransformationRule(
                rule_id=f"test_{rule_type.value.lower()}",
                rule_type=rule_type,
                priority=1,
                condition=lambda row: True,
                action=lambda row: row
            )
            assert rule.rule_type == rule_type


class TestTransformationResult:
    """Tests for TransformationResult data model."""
    
    def test_create_valid_result(self):
        """Test creating a valid transformation result."""
        original = {"name": "  John  ", "age": "30"}
        transformed = {"name": "John", "age": 30}
        
        result = TransformationResult(
            transformed_row=transformed,
            applied_rules=["trim_strings_v1", "cast_integer_v1"],
            warnings=["Age was string, converted to int"],
            errors=[],
            original_row=original,
            quality_score=0.95
        )
        
        assert result.transformed_row == transformed
        assert len(result.applied_rules) == 2
        assert "trim_strings_v1" in result.applied_rules
        assert len(result.warnings) == 1
        assert len(result.errors) == 0
        assert result.original_row == original
        assert result.quality_score == 0.95
    
    def test_default_fields_are_empty(self):
        """Test that optional fields default to empty lists."""
        result = TransformationResult(
            transformed_row={"name": "John"}
        )
        
        assert result.applied_rules == []
        assert result.warnings == []
        assert result.errors == []
        assert result.original_row is None
        assert result.quality_score is None
    
    def test_quality_score_validation_valid_range(self):
        """Test that quality scores in valid range (0.0-1.0) are accepted."""
        for score in [0.0, 0.5, 1.0]:
            result = TransformationResult(
                transformed_row={},
                quality_score=score
            )
            assert result.quality_score == score
    
    def test_quality_score_below_zero_raises_error(self):
        """Test that quality score below 0.0 raises ValueError."""
        with pytest.raises(ValueError, match="quality_score must be between 0.0 and 1.0"):
            TransformationResult(
                transformed_row={},
                quality_score=-0.1
            )
    
    def test_quality_score_above_one_raises_error(self):
        """Test that quality score above 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="quality_score must be between 0.0 and 1.0"):
            TransformationResult(
                transformed_row={},
                quality_score=1.1
            )


class TestRuleExecutionContext:
    """Tests for RuleExecutionContext data model."""
    
    def test_create_valid_context(self):
        """Test creating a valid execution context."""
        context = RuleExecutionContext(
            batch_id="batch_123",
            source_id="source_456",
            schema_version="1.0.0",
            additional_context={"env": "production"}
        )
        
        assert context.batch_id == "batch_123"
        assert context.source_id == "source_456"
        assert context.schema_version == "1.0.0"
        assert context.additional_context["env"] == "production"
        assert isinstance(context.execution_timestamp, datetime)
    
    def test_execution_timestamp_auto_generated(self):
        """Test that execution_timestamp is automatically generated."""
        before = datetime.utcnow()
        context = RuleExecutionContext(
            batch_id="batch_123",
            source_id="source_456",
            schema_version="1.0.0"
        )
        after = datetime.utcnow()
        
        assert before <= context.execution_timestamp <= after
    
    def test_default_additional_context_is_empty_dict(self):
        """Test that additional_context defaults to empty dict."""
        context = RuleExecutionContext(
            batch_id="batch_123",
            source_id="source_456",
            schema_version="1.0.0"
        )
        
        assert context.additional_context == {}


class TestRuleExecutionRecord:
    """Tests for RuleExecutionRecord data model."""
    
    def test_create_valid_record(self):
        """Test creating a valid execution record."""
        row_id = uuid4()
        changes = {
            "name": ("  John  ", "John"),
            "age": ("30", 30)
        }
        
        record = RuleExecutionRecord(
            rule_id="trim_strings_v1",
            row_id=row_id,
            success=True,
            changes_made=changes,
            execution_time_ms=1.5
        )
        
        assert isinstance(record.record_id, UUID)
        assert record.rule_id == "trim_strings_v1"
        assert record.row_id == row_id
        assert record.success is True
        assert record.changes_made == changes
        assert record.execution_time_ms == 1.5
        assert isinstance(record.execution_timestamp, datetime)
        assert record.error_message is None
    
    def test_record_id_auto_generated(self):
        """Test that record_id is automatically generated as UUID."""
        record1 = RuleExecutionRecord()
        record2 = RuleExecutionRecord()
        
        assert isinstance(record1.record_id, UUID)
        assert isinstance(record2.record_id, UUID)
        assert record1.record_id != record2.record_id
    
    def test_default_values(self):
        """Test that fields have correct default values."""
        record = RuleExecutionRecord()
        
        assert isinstance(record.record_id, UUID)
        assert record.rule_id == ""
        assert record.row_id is None
        assert isinstance(record.execution_timestamp, datetime)
        assert record.success is True
        assert record.changes_made == {}
        assert record.error_message is None
        assert record.execution_time_ms is None
    
    def test_failed_execution_record(self):
        """Test creating a record for a failed execution."""
        record = RuleExecutionRecord(
            rule_id="validate_email_v1",
            row_id=uuid4(),
            success=False,
            error_message="Invalid email format",
            execution_time_ms=0.5
        )
        
        assert record.success is False
        assert record.error_message == "Invalid email format"
        assert record.changes_made == {}


class TestIntegration:
    """Integration tests for data models working together."""
    
    def test_complete_transformation_workflow(self):
        """Test a complete transformation workflow using all data models."""
        # 1. Create a transformation rule
        rule = TransformationRule(
            rule_id="trim_strings_v1",
            rule_type=RuleType.CLEAN,
            priority=1,
            condition=lambda row: any(isinstance(v, str) for v in row.values()),
            action=lambda row: {k: v.strip() if isinstance(v, str) else v 
                               for k, v in row.items()},
            metadata={"description": "Trim whitespace", "version": "1.0.0"}
        )
        
        # 2. Create execution context
        context = RuleExecutionContext(
            batch_id="batch_123",
            source_id="source_456",
            schema_version="1.0.0"
        )
        
        # 3. Apply rule to a row
        original_row = {"name": "  John  ", "age": 30}
        transformed_row = rule.action(original_row)
        
        # 4. Create transformation result
        result = TransformationResult(
            transformed_row=transformed_row,
            applied_rules=[rule.rule_id],
            warnings=[],
            errors=[],
            original_row=original_row,
            quality_score=1.0
        )
        
        # 5. Create execution record
        record = RuleExecutionRecord(
            rule_id=rule.rule_id,
            row_id=uuid4(),
            success=True,
            changes_made={"name": ("  John  ", "John")},
            execution_time_ms=1.0
        )
        
        # Verify the workflow
        assert transformed_row["name"] == "John"
        assert result.applied_rules[0] == rule.rule_id
        assert record.rule_id == rule.rule_id
        assert context.batch_id == "batch_123"
