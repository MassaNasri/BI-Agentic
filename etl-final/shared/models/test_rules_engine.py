"""
Unit tests for RulesEngine class.

Tests cover:
- Pure functional behavior (no side effects)
- Deterministic transformations (same input → same output)
- Rule priority ordering
- Condition evaluation
- Error handling
- Change tracking
- Quality score calculation
- Rule validation
"""
import pytest
import sys
import os
from datetime import datetime
from uuid import uuid4

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from transformation_rule import (
    RuleType,
    TransformationRule,
    TransformationResult,
    RuleExecutionContext
)
from rules_engine import RulesEngine


class TestRulesEngineBasics:
    """Basic tests for RulesEngine functionality."""
    
    def test_apply_single_rule(self):
        """Test applying a single transformation rule."""
        # Create a simple trim rule
        rule = TransformationRule(
            rule_id="trim_strings_v1",
            rule_type=RuleType.CLEAN,
            priority=1,
            condition=lambda row: any(isinstance(v, str) for v in row.values()),
            action=lambda row: {k: v.strip() if isinstance(v, str) else v 
                               for k, v in row.items()}
        )
        
        row = {"name": "  John  ", "age": 30}
        result = RulesEngine.apply_rules(row, [rule])
        
        assert result.transformed_row["name"] == "John"
        assert result.transformed_row["age"] == 30
        assert "trim_strings_v1" in result.applied_rules
        assert len(result.errors) == 0
    
    def test_apply_no_rules(self):
        """Test applying empty rule list returns unchanged row."""
        row = {"name": "John", "age": 30}
        result = RulesEngine.apply_rules(row, [])
        
        assert result.transformed_row == row
        assert len(result.applied_rules) == 0
        assert result.quality_score == 1.0
    
    def test_rule_condition_not_met(self):
        """Test that rules with unmet conditions are not applied."""
        rule = TransformationRule(
            rule_id="uppercase_name",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: "name" in row and row["name"] == "trigger",
            action=lambda row: {**row, "name": row["name"].upper()}
        )
        
        row = {"name": "John", "age": 30}
        result = RulesEngine.apply_rules(row, [rule])
        
        assert result.transformed_row["name"] == "John"  # Unchanged
        assert "uppercase_name" not in result.applied_rules


class TestRulePriority:
    """Tests for rule priority ordering."""
    
    def test_rules_applied_in_priority_order(self):
        """Test that rules are applied in priority order (lower first)."""
        rule1 = TransformationRule(
            rule_id="add_suffix",
            rule_type=RuleType.TRANSFORM,
            priority=2,
            condition=lambda row: True,
            action=lambda row: {**row, "name": row["name"] + "_suffix"}
        )
        
        rule2 = TransformationRule(
            rule_id="add_prefix",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: True,
            action=lambda row: {**row, "name": "prefix_" + row["name"]}
        )
        
        row = {"name": "John"}
        result = RulesEngine.apply_rules(row, [rule1, rule2])
        
        # rule2 (priority 1) should run first, then rule1 (priority 2)
        assert result.transformed_row["name"] == "prefix_John_suffix"
        assert result.applied_rules == ["add_prefix", "add_suffix"]
    
    def test_same_priority_maintains_list_order(self):
        """Test that rules with same priority maintain their list order."""
        rule1 = TransformationRule(
            rule_id="rule1",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: True,
            action=lambda row: {**row, "value": row.get("value", 0) + 1}
        )
        
        rule2 = TransformationRule(
            rule_id="rule2",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: True,
            action=lambda row: {**row, "value": row.get("value", 0) * 2}
        )
        
        row = {"value": 5}
        result = RulesEngine.apply_rules(row, [rule1, rule2])
        
        # (5 + 1) * 2 = 12
        assert result.transformed_row["value"] == 12
    
    def test_priority_order_with_multiple_rules(self):
        """Test priority ordering with multiple rules at different priorities."""
        rules = [
            TransformationRule(
                rule_id="priority_10",
                rule_type=RuleType.TRANSFORM,
                priority=10,
                condition=lambda row: True,
                action=lambda row: {**row, "order": row.get("order", []) + [10]}
            ),
            TransformationRule(
                rule_id="priority_1",
                rule_type=RuleType.TRANSFORM,
                priority=1,
                condition=lambda row: True,
                action=lambda row: {**row, "order": row.get("order", []) + [1]}
            ),
            TransformationRule(
                rule_id="priority_5",
                rule_type=RuleType.TRANSFORM,
                priority=5,
                condition=lambda row: True,
                action=lambda row: {**row, "order": row.get("order", []) + [5]}
            ),
            TransformationRule(
                rule_id="priority_3",
                rule_type=RuleType.TRANSFORM,
                priority=3,
                condition=lambda row: True,
                action=lambda row: {**row, "order": row.get("order", []) + [3]}
            )
        ]
        
        row = {"order": []}
        result = RulesEngine.apply_rules(row, rules)
        
        # Should execute in order: 1, 3, 5, 10
        assert result.transformed_row["order"] == [1, 3, 5, 10]
        assert result.applied_rules == ["priority_1", "priority_3", "priority_5", "priority_10"]
    
    def test_priority_zero_executes_first(self):
        """Test that priority 0 executes before all other priorities."""
        rules = [
            TransformationRule(
                rule_id="priority_5",
                rule_type=RuleType.TRANSFORM,
                priority=5,
                condition=lambda row: True,
                action=lambda row: {**row, "order": row.get("order", []) + ["5"]}
            ),
            TransformationRule(
                rule_id="priority_0",
                rule_type=RuleType.TRANSFORM,
                priority=0,
                condition=lambda row: True,
                action=lambda row: {**row, "order": row.get("order", []) + ["0"]}
            ),
            TransformationRule(
                rule_id="priority_1",
                rule_type=RuleType.TRANSFORM,
                priority=1,
                condition=lambda row: True,
                action=lambda row: {**row, "order": row.get("order", []) + ["1"]}
            )
        ]
        
        row = {"order": []}
        result = RulesEngine.apply_rules(row, rules)
        
        assert result.transformed_row["order"] == ["0", "1", "5"]
        assert result.applied_rules[0] == "priority_0"
    
    def test_priority_order_independent_of_input_order(self):
        """Test that priority determines order regardless of input list order."""
        # Create rules in reverse priority order
        rules_reversed = [
            TransformationRule(
                rule_id="rule_3",
                rule_type=RuleType.TRANSFORM,
                priority=3,
                condition=lambda row: True,
                action=lambda row: {**row, "seq": row.get("seq", "") + "C"}
            ),
            TransformationRule(
                rule_id="rule_2",
                rule_type=RuleType.TRANSFORM,
                priority=2,
                condition=lambda row: True,
                action=lambda row: {**row, "seq": row.get("seq", "") + "B"}
            ),
            TransformationRule(
                rule_id="rule_1",
                rule_type=RuleType.TRANSFORM,
                priority=1,
                condition=lambda row: True,
                action=lambda row: {**row, "seq": row.get("seq", "") + "A"}
            )
        ]
        
        # Create same rules in forward priority order
        rules_forward = [
            TransformationRule(
                rule_id="rule_1",
                rule_type=RuleType.TRANSFORM,
                priority=1,
                condition=lambda row: True,
                action=lambda row: {**row, "seq": row.get("seq", "") + "A"}
            ),
            TransformationRule(
                rule_id="rule_2",
                rule_type=RuleType.TRANSFORM,
                priority=2,
                condition=lambda row: True,
                action=lambda row: {**row, "seq": row.get("seq", "") + "B"}
            ),
            TransformationRule(
                rule_id="rule_3",
                rule_type=RuleType.TRANSFORM,
                priority=3,
                condition=lambda row: True,
                action=lambda row: {**row, "seq": row.get("seq", "") + "C"}
            )
        ]
        
        row = {"seq": ""}
        result_reversed = RulesEngine.apply_rules(row, rules_reversed)
        result_forward = RulesEngine.apply_rules(row, rules_forward)
        
        # Both should produce same result
        assert result_reversed.transformed_row["seq"] == "ABC"
        assert result_forward.transformed_row["seq"] == "ABC"
        assert result_reversed.applied_rules == result_forward.applied_rules
    
    def test_priority_with_conditional_rules(self):
        """Test that priority ordering works correctly with conditional rules."""
        rules = [
            TransformationRule(
                rule_id="high_priority_conditional",
                rule_type=RuleType.TRANSFORM,
                priority=10,
                condition=lambda row: row.get("apply_high", False),
                action=lambda row: {**row, "result": "high"}
            ),
            TransformationRule(
                rule_id="low_priority_always",
                rule_type=RuleType.TRANSFORM,
                priority=1,
                condition=lambda row: True,
                action=lambda row: {**row, "result": "low"}
            ),
            TransformationRule(
                rule_id="medium_priority_always",
                rule_type=RuleType.TRANSFORM,
                priority=5,
                condition=lambda row: True,
                action=lambda row: {**row, "result": "medium"}
            )
        ]
        
        # When high priority condition is not met
        row1 = {"apply_high": False}
        result1 = RulesEngine.apply_rules(row1, rules)
        # Low (1) runs first, then medium (5) overwrites it
        assert result1.transformed_row["result"] == "medium"
        
        # When high priority condition is met
        row2 = {"apply_high": True}
        result2 = RulesEngine.apply_rules(row2, rules)
        # Low (1), medium (5), then high (10) overwrites
        assert result2.transformed_row["result"] == "high"
    
    def test_large_priority_values(self):
        """Test that large priority values work correctly."""
        rules = [
            TransformationRule(
                rule_id="priority_1000",
                rule_type=RuleType.TRANSFORM,
                priority=1000,
                condition=lambda row: True,
                action=lambda row: {**row, "last": True}
            ),
            TransformationRule(
                rule_id="priority_1",
                rule_type=RuleType.TRANSFORM,
                priority=1,
                condition=lambda row: True,
                action=lambda row: {**row, "first": True}
            ),
            TransformationRule(
                rule_id="priority_500",
                rule_type=RuleType.TRANSFORM,
                priority=500,
                condition=lambda row: True,
                action=lambda row: {**row, "middle": True}
            )
        ]
        
        row = {}
        result = RulesEngine.apply_rules(row, rules)
        
        assert result.applied_rules == ["priority_1", "priority_500", "priority_1000"]
        assert result.transformed_row["first"] is True
        assert result.transformed_row["middle"] is True
        assert result.transformed_row["last"] is True


class TestDeterminism:
    """Tests for deterministic behavior."""
    
    def test_same_input_produces_same_output(self):
        """Test that applying rules multiple times produces identical results."""
        rules = [
            TransformationRule(
                rule_id="trim",
                rule_type=RuleType.CLEAN,
                priority=1,
                condition=lambda row: True,
                action=lambda row: {k: v.strip() if isinstance(v, str) else v 
                                   for k, v in row.items()}
            ),
            TransformationRule(
                rule_id="uppercase",
                rule_type=RuleType.TRANSFORM,
                priority=2,
                condition=lambda row: "name" in row,
                action=lambda row: {**row, "name": row["name"].upper()}
            )
        ]
        
        row = {"name": "  john  ", "age": 30}
        
        result1 = RulesEngine.apply_rules(row, rules)
        result2 = RulesEngine.apply_rules(row, rules)
        result3 = RulesEngine.apply_rules(row, rules)
        
        assert result1.transformed_row == result2.transformed_row == result3.transformed_row
        assert result1.applied_rules == result2.applied_rules == result3.applied_rules
    
    def test_original_row_not_modified(self):
        """Test that the original row is not modified (immutability)."""
        rule = TransformationRule(
            rule_id="modify",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: True,
            action=lambda row: {**row, "new_field": "added"}
        )
        
        original_row = {"name": "John"}
        original_copy = original_row.copy()
        
        result = RulesEngine.apply_rules(original_row, [rule])
        
        # Original row should be unchanged
        assert original_row == original_copy
        assert "new_field" not in original_row
        assert "new_field" in result.transformed_row


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_rule_exception_captured_in_errors(self):
        """Test that exceptions in rules are captured, not raised."""
        rule = TransformationRule(
            rule_id="failing_rule",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: True,
            action=lambda row: row["nonexistent_key"]  # Will raise KeyError
        )
        
        row = {"name": "John"}
        result = RulesEngine.apply_rules(row, [rule])
        
        # Should not raise exception
        assert len(result.errors) == 1
        assert "failing_rule" in result.errors[0]
        assert "failed" in result.errors[0]
        assert "nonexistent_key" in result.errors[0]
        assert "failing_rule" not in result.applied_rules
    
    def test_subsequent_rules_run_after_error(self):
        """Test that subsequent rules run even if a previous rule fails."""
        rule1 = TransformationRule(
            rule_id="failing_rule",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: True,
            action=lambda row: row["nonexistent"]  # Will fail
        )
        
        rule2 = TransformationRule(
            rule_id="working_rule",
            rule_type=RuleType.TRANSFORM,
            priority=2,
            condition=lambda row: True,
            action=lambda row: {**row, "processed": True}
        )
        
        row = {"name": "John"}
        result = RulesEngine.apply_rules(row, [rule1, rule2])
        
        assert len(result.errors) == 1
        assert "working_rule" in result.applied_rules
        assert result.transformed_row["processed"] is True
    
    def test_condition_exception_captured_in_warnings(self):
        """Test that exceptions in condition evaluation are captured as warnings."""
        rule = TransformationRule(
            rule_id="bad_condition_rule",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: row["nonexistent_key"] > 10,  # Will raise KeyError
            action=lambda row: {**row, "processed": True}
        )
        
        row = {"name": "John"}
        result = RulesEngine.apply_rules(row, [rule])
        
        # Should not raise exception
        assert len(result.warnings) == 1
        assert "bad_condition_rule" in result.warnings[0]
        assert "condition evaluation failed" in result.warnings[0]
        assert "bad_condition_rule" not in result.applied_rules
        assert "processed" not in result.transformed_row
    
    def test_condition_exception_does_not_stop_other_rules(self):
        """Test that condition exceptions don't prevent other rules from running."""
        rule1 = TransformationRule(
            rule_id="bad_condition",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: row["missing"] > 10,  # Will fail
            action=lambda row: {**row, "rule1": True}
        )
        
        rule2 = TransformationRule(
            rule_id="good_rule",
            rule_type=RuleType.TRANSFORM,
            priority=2,
            condition=lambda row: True,
            action=lambda row: {**row, "rule2": True}
        )
        
        row = {"name": "John"}
        result = RulesEngine.apply_rules(row, [rule1, rule2])
        
        assert len(result.warnings) == 1
        assert "bad_condition" in result.warnings[0]
        assert "good_rule" in result.applied_rules
        assert result.transformed_row["rule2"] is True
        assert "rule1" not in result.transformed_row
    
    def test_multiple_condition_failures(self):
        """Test handling of multiple condition evaluation failures."""
        rule1 = TransformationRule(
            rule_id="bad_condition_1",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: row["missing1"] > 10,
            action=lambda row: row
        )
        
        rule2 = TransformationRule(
            rule_id="bad_condition_2",
            rule_type=RuleType.TRANSFORM,
            priority=2,
            condition=lambda row: row["missing2"] > 10,
            action=lambda row: row
        )
        
        row = {"name": "John"}
        result = RulesEngine.apply_rules(row, [rule1, rule2])
        
        assert len(result.warnings) == 2
        assert any("bad_condition_1" in w for w in result.warnings)
        assert any("bad_condition_2" in w for w in result.warnings)
        assert len(result.applied_rules) == 0


class TestChangeTracking:
    """Tests for change tracking functionality."""
    
    def test_changes_detected(self):
        """Test that field changes are detected."""
        rule = TransformationRule(
            rule_id="modify_fields",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: True,
            action=lambda row: {**row, "name": "Jane", "age": 31}
        )
        
        row = {"name": "John", "age": 30}
        result = RulesEngine.apply_rules(row, [rule], track_changes=True)
        
        assert result.original_row == {"name": "John", "age": 30}
        assert result.transformed_row == {"name": "Jane", "age": 31}
    
    def test_track_changes_disabled(self):
        """Test that change tracking can be disabled."""
        rule = TransformationRule(
            rule_id="modify",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: True,
            action=lambda row: {**row, "name": "Jane"}
        )
        
        row = {"name": "John"}
        result = RulesEngine.apply_rules(row, [rule], track_changes=False)
        
        # Original row should still be preserved
        assert result.original_row == {"name": "John"}


class TestQualityScore:
    """Tests for quality score calculation."""
    
    def test_perfect_quality_score(self):
        """Test that successful transformations get high quality score."""
        rule = TransformationRule(
            rule_id="clean",
            rule_type=RuleType.CLEAN,
            priority=1,
            condition=lambda row: True,
            action=lambda row: row
        )
        
        row = {"name": "John"}
        result = RulesEngine.apply_rules(row, [rule])
        
        assert result.quality_score == 1.0
    
    def test_quality_score_with_errors(self):
        """Test that errors reduce quality score."""
        rule = TransformationRule(
            rule_id="failing",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: True,
            action=lambda row: row["nonexistent"]
        )
        
        row = {"name": "John"}
        result = RulesEngine.apply_rules(row, [rule])
        
        assert result.quality_score < 1.0
        assert result.quality_score >= 0.0


class TestRuleValidation:
    """Tests for rule validation."""
    
    def test_validate_valid_rules(self):
        """Test that valid rules pass validation."""
        rules = [
            TransformationRule(
                rule_id="rule1",
                rule_type=RuleType.CLEAN,
                priority=1,
                condition=lambda row: True,
                action=lambda row: row
            ),
            TransformationRule(
                rule_id="rule2",
                rule_type=RuleType.VALIDATE,
                priority=2,
                condition=lambda row: True,
                action=lambda row: row
            )
        ]
        
        errors = RulesEngine.validate_rules(rules)
        assert len(errors) == 0
    
    def test_validate_duplicate_rule_ids(self):
        """Test that duplicate rule IDs are detected."""
        rules = [
            TransformationRule(
                rule_id="duplicate",
                rule_type=RuleType.CLEAN,
                priority=1,
                condition=lambda row: True,
                action=lambda row: row
            ),
            TransformationRule(
                rule_id="duplicate",
                rule_type=RuleType.VALIDATE,
                priority=2,
                condition=lambda row: True,
                action=lambda row: row
            )
        ]
        
        errors = RulesEngine.validate_rules(rules)
        assert len(errors) > 0
        assert "duplicate" in errors[0].lower()
    
    def test_validate_negative_priority(self):
        """Test that TransformationRule prevents negative priority at creation."""
        # TransformationRule validates priority in __post_init__
        # So negative priorities are caught at rule creation time
        with pytest.raises(ValueError, match="priority must be non-negative"):
            TransformationRule(
                rule_id="negative_priority_rule",
                rule_type=RuleType.VALIDATE,
                priority=-5,
                condition=lambda row: True,
                action=lambda row: row
            )
    
    def test_validate_zero_priority_allowed(self):
        """Test that priority 0 is valid."""
        rules = [
            TransformationRule(
                rule_id="zero_priority",
                rule_type=RuleType.CLEAN,
                priority=0,
                condition=lambda row: True,
                action=lambda row: row
            )
        ]
        
        errors = RulesEngine.validate_rules(rules)
        assert len(errors) == 0
    
    def test_validate_rules_detects_negative_priority_if_bypassed(self):
        """Test that RulesEngine.validate_rules catches negative priorities."""
        # Create a rule with valid priority first
        rule = TransformationRule(
            rule_id="test_rule",
            rule_type=RuleType.CLEAN,
            priority=1,
            condition=lambda row: True,
            action=lambda row: row
        )
        
        # Manually modify priority to negative (bypassing __post_init__)
        # This simulates a corrupted rule or deserialization issue
        object.__setattr__(rule, 'priority', -5)
        
        errors = RulesEngine.validate_rules([rule])
        assert len(errors) > 0
        assert any("negative priority" in err.lower() for err in errors)


class TestRuleFiltering:
    """Tests for rule filtering utilities."""
    
    def test_filter_rules_by_type(self):
        """Test filtering rules by type."""
        rules = [
            TransformationRule(
                rule_id="clean1",
                rule_type=RuleType.CLEAN,
                priority=1,
                condition=lambda row: True,
                action=lambda row: row
            ),
            TransformationRule(
                rule_id="validate1",
                rule_type=RuleType.VALIDATE,
                priority=2,
                condition=lambda row: True,
                action=lambda row: row
            ),
            TransformationRule(
                rule_id="clean2",
                rule_type=RuleType.CLEAN,
                priority=3,
                condition=lambda row: True,
                action=lambda row: row
            )
        ]
        
        clean_rules = RulesEngine.filter_rules_by_type(rules, RuleType.CLEAN)
        assert len(clean_rules) == 2
        assert all(r.rule_type == RuleType.CLEAN for r in clean_rules)
    
    def test_get_rule_by_id(self):
        """Test finding a rule by ID."""
        rules = [
            TransformationRule(
                rule_id="rule1",
                rule_type=RuleType.CLEAN,
                priority=1,
                condition=lambda row: True,
                action=lambda row: row
            ),
            TransformationRule(
                rule_id="rule2",
                rule_type=RuleType.VALIDATE,
                priority=2,
                condition=lambda row: True,
                action=lambda row: row
            )
        ]
        
        found = RulesEngine.get_rule_by_id(rules, "rule2")
        assert found is not None
        assert found.rule_id == "rule2"
        
        not_found = RulesEngine.get_rule_by_id(rules, "nonexistent")
        assert not_found is None


class TestExecutionContext:
    """Tests for execution context integration."""
    
    def test_apply_rules_with_context(self):
        """Test applying rules with execution context."""
        rule = TransformationRule(
            rule_id="test_rule",
            rule_type=RuleType.CLEAN,
            priority=1,
            condition=lambda row: True,
            action=lambda row: row
        )
        
        context = RuleExecutionContext(
            batch_id="batch_123",
            source_id="source_456",
            schema_version="1.0.0"
        )
        
        row = {"name": "John"}
        result = RulesEngine.apply_rules(row, [rule], context=context)
        
        assert result.transformed_row == row
        assert "test_rule" in result.applied_rules


class TestComplexTransformations:
    """Tests for complex transformation scenarios."""
    
    def test_multi_stage_transformation(self):
        """Test a multi-stage transformation pipeline."""
        # Stage 1: Clean (trim whitespace)
        clean_rule = TransformationRule(
            rule_id="trim_strings",
            rule_type=RuleType.CLEAN,
            priority=1,
            condition=lambda row: True,
            action=lambda row: {k: v.strip() if isinstance(v, str) else v 
                               for k, v in row.items()}
        )
        
        # Stage 2: Transform (uppercase name)
        transform_rule = TransformationRule(
            rule_id="uppercase_name",
            rule_type=RuleType.TRANSFORM,
            priority=2,
            condition=lambda row: "name" in row,
            action=lambda row: {**row, "name": row["name"].upper()}
        )
        
        # Stage 3: Enrich (add full_name)
        enrich_rule = TransformationRule(
            rule_id="add_full_name",
            rule_type=RuleType.ENRICH,
            priority=3,
            condition=lambda row: "name" in row and "surname" in row,
            action=lambda row: {**row, "full_name": f"{row['name']} {row['surname']}"}
        )
        
        row = {"name": "  john  ", "surname": "  doe  "}
        result = RulesEngine.apply_rules(row, [clean_rule, transform_rule, enrich_rule])
        
        assert result.transformed_row["name"] == "JOHN"
        assert result.transformed_row["surname"] == "doe"
        assert result.transformed_row["full_name"] == "JOHN doe"
        assert len(result.applied_rules) == 3
    
    def test_conditional_transformation_chain(self):
        """Test transformation chain with conditional rules."""
        # Only apply if age is present
        age_rule = TransformationRule(
            rule_id="categorize_age",
            rule_type=RuleType.ENRICH,
            priority=1,
            condition=lambda row: "age" in row and isinstance(row["age"], int),
            action=lambda row: {
                **row,
                "age_category": "adult" if row["age"] >= 18 else "minor"
            }
        )
        
        # Only apply if email is present
        email_rule = TransformationRule(
            rule_id="validate_email",
            rule_type=RuleType.VALIDATE,
            priority=2,
            condition=lambda row: "email" in row,
            action=lambda row: {
                **row,
                "email_valid": "@" in row["email"]
            }
        )
        
        # Row with age but no email
        row1 = {"name": "John", "age": 25}
        result1 = RulesEngine.apply_rules(row1, [age_rule, email_rule])
        assert "age_category" in result1.transformed_row
        assert "email_valid" not in result1.transformed_row
        
        # Row with email but no age
        row2 = {"name": "Jane", "email": "jane@example.com"}
        result2 = RulesEngine.apply_rules(row2, [age_rule, email_rule])
        assert "age_category" not in result2.transformed_row
        assert "email_valid" in result2.transformed_row
