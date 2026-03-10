"""
Transformation Rules Engine - Pure Functional Implementation
"""
from typing import Dict, List, Any, Optional
import time
from uuid import UUID, uuid4
from copy import deepcopy

try:
    from .transformation_rule import (
        TransformationRule,
        TransformationResult,
        RuleExecutionContext,
        RuleExecutionRecord,
        RuleType
    )
except ImportError:  # Fallback for direct module execution
    from transformation_rule import (
        TransformationRule,
        TransformationResult,
        RuleExecutionContext,
        RuleExecutionRecord,
        RuleType
    )


class RulesEngine:
    @staticmethod
    def apply_rules(row: Dict[str, Any], rules: List[TransformationRule], context: Optional[RuleExecutionContext] = None, track_changes: bool = True) -> TransformationResult:
        original_row = deepcopy(row)
        current_row = deepcopy(row)
        applied_rules = []
        warnings = []
        errors = []
        
        sorted_rules = sorted(rules, key=lambda r: r.priority)
        
        for rule in sorted_rules:
            try:
                if not rule.condition(current_row):
                    continue
                
                start_time = time.perf_counter()
                before_row = deepcopy(current_row) if track_changes else None
                transformed_row = rule.action(current_row)
                execution_time_ms = (time.perf_counter() - start_time) * 1000
                
                changes_made = {}
                if track_changes and before_row:
                    changes_made = RulesEngine._detect_changes(before_row, transformed_row)
                
                current_row = transformed_row
                applied_rules.append(rule.rule_id)
                
            except Exception as e:
                error_msg = f"Rule '{rule.rule_id}' failed: {str(e)}"
                errors.append(error_msg)
        
        quality_score = RulesEngine._calculate_quality_score(applied_rules, errors, warnings)
        
        return TransformationResult(
            transformed_row=current_row,
            applied_rules=applied_rules,
            warnings=warnings,
            errors=errors,
            original_row=original_row,
            quality_score=quality_score
        )
    
    @staticmethod
    def _detect_changes(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, tuple]:
        changes = {}
        all_keys = set(before.keys()) | set(after.keys())
        for key in all_keys:
            before_val = before.get(key)
            after_val = after.get(key)
            if before_val != after_val:
                changes[key] = (before_val, after_val)
        return changes
    
    @staticmethod
    def _calculate_quality_score(applied_rules: List[str], errors: List[str], warnings: List[str]) -> float:
        score = 1.0
        if errors:
            score -= 0.5 * min(len(errors) / 10.0, 1.0)
        if warnings:
            score -= 0.2 * min(len(warnings) / 10.0, 1.0)
        return max(0.0, min(1.0, score))
    
    @staticmethod
    def validate_rules(rules: List[TransformationRule]) -> List[str]:
        errors = []
        rule_ids = [r.rule_id for r in rules]
        duplicates = [rid for rid in rule_ids if rule_ids.count(rid) > 1]
        if duplicates:
            errors.append(f"Duplicate rule IDs found: {set(duplicates)}")
        for rule in rules:
            if not rule.rule_id:
                errors.append("Rule with empty rule_id found")
            if rule.priority < 0:
                errors.append(f"Rule '{rule.rule_id}' has negative priority: {rule.priority}")
            if not callable(rule.condition):
                errors.append(f"Rule '{rule.rule_id}' has non-callable condition")
            if not callable(rule.action):
                errors.append(f"Rule '{rule.rule_id}' has non-callable action")
        return errors
    
    @staticmethod
    def filter_rules_by_type(rules: List[TransformationRule], rule_type: RuleType) -> List[TransformationRule]:
        return [r for r in rules if r.rule_type == rule_type]
    
    @staticmethod
    def get_rule_by_id(rules: List[TransformationRule], rule_id: str) -> Optional[TransformationRule]:
        for rule in rules:
            if rule.rule_id == rule_id:
                return rule
        return None
