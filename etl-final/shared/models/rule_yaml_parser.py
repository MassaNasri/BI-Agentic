"""
YAML Parser for Transformation Rules
Converts declarative YAML rule definitions into TransformationRule objects.

Based on design.md section 7 and requirements US-6 (AC 6.1-6.4).

This module enables non-programmer friendly, version-controlled rule definitions
that can be loaded and executed by the transformation engine.

Example YAML format:
    transformation_rules:
      - rule_id: "trim_strings_v1"
        rule_type: "CLEAN"
        priority: 1
        description: "Trim whitespace from all string fields"
        condition:
          type: "always"
        action:
          type: "trim_strings"

**Validates: Requirements US-6 (AC 6.1-6.4)**
"""
from typing import Dict, Any, List, Callable, Optional
import yaml
import re
from pathlib import Path

from .transformation_rule import TransformationRule, RuleType
from .rule_conditions import (
    always_true, field_exists, field_not_exists, field_is_null,
    field_is_not_null, field_type, field_value_equals, field_value_in,
    field_value_matches, field_value_contains, field_value_range,
    all_fields_exist, any_field_exists, and_conditions, or_conditions,
    not_condition
)
from .rule_actions import (
    trim_strings, trim_field, uppercase_strings, uppercase_field,
    lowercase_strings, lowercase_field, normalize_whitespace,
    normalize_whitespace_field, cast_to_int, cast_to_float, cast_to_bool,
    cast_to_date, regex_replace, regex_extract, remove_field,
    remove_null_fields, rename_field, copy_field, replace_value,
    default_value, compose_actions
)


class RuleYAMLParserError(Exception):
    """Exception raised for errors in YAML rule parsing."""
    pass


class RuleYAMLParser:
    """
    Parser for YAML-based transformation rule definitions.
    
    Converts declarative YAML configurations into executable TransformationRule
    objects that can be used by the RulesEngine.
    
    Attributes:
        condition_registry: Mapping of condition type names to factory functions
        action_registry: Mapping of action type names to factory functions
    """
    
    def __init__(self):
        """Initialize the parser with condition and action registries."""
        self.condition_registry = self._build_condition_registry()
        self.action_registry = self._build_action_registry()
    
    def parse_file(self, yaml_path: str) -> List[TransformationRule]:
        """
        Parse a YAML file containing transformation rules.
        
        Args:
            yaml_path: Path to the YAML file
            
        Returns:
            List of TransformationRule objects
            
        Raises:
            RuleYAMLParserError: If file cannot be read or parsed
            
        Example:
            >>> parser = RuleYAMLParser()
            >>> rules = parser.parse_file("rules/cleaning_rules.yaml")
            >>> len(rules)
            5
        """
        try:
            path = Path(yaml_path)
            if not path.exists():
                raise RuleYAMLParserError(f"YAML file not found: {yaml_path}")
            
            with open(path, 'r', encoding='utf-8') as f:
                yaml_content = yaml.safe_load(f)
            
            return self.parse_yaml(yaml_content)
        
        except yaml.YAMLError as e:
            raise RuleYAMLParserError(f"Invalid YAML syntax: {e}")
        except Exception as e:
            raise RuleYAMLParserError(f"Error reading YAML file: {e}")
    
    def parse_yaml(self, yaml_content: Dict[str, Any]) -> List[TransformationRule]:
        """
        Parse YAML content into transformation rules.
        
        Args:
            yaml_content: Parsed YAML content as dictionary
            
        Returns:
            List of TransformationRule objects
            
        Raises:
            RuleYAMLParserError: If YAML structure is invalid
            
        Example:
            >>> parser = RuleYAMLParser()
            >>> yaml_content = {
            ...     "transformation_rules": [
            ...         {
            ...             "rule_id": "trim_v1",
            ...             "rule_type": "CLEAN",
            ...             "priority": 1,
            ...             "condition": {"type": "always"},
            ...             "action": {"type": "trim_strings"}
            ...         }
            ...     ]
            ... }
            >>> rules = parser.parse_yaml(yaml_content)
            >>> len(rules)
            1
        """
        if not isinstance(yaml_content, dict):
            raise RuleYAMLParserError("YAML content must be a dictionary")
        
        if "transformation_rules" not in yaml_content:
            raise RuleYAMLParserError("YAML must contain 'transformation_rules' key")
        
        rules_data = yaml_content["transformation_rules"]
        if not isinstance(rules_data, list):
            raise RuleYAMLParserError("'transformation_rules' must be a list")
        
        rules = []
        for idx, rule_data in enumerate(rules_data):
            try:
                rule = self._parse_rule(rule_data)
                rules.append(rule)
            except Exception as e:
                raise RuleYAMLParserError(f"Error parsing rule at index {idx}: {e}")
        
        return rules
    
    def _parse_rule(self, rule_data: Dict[str, Any]) -> TransformationRule:
        """
        Parse a single rule definition.
        
        Args:
            rule_data: Dictionary containing rule definition
            
        Returns:
            TransformationRule object
            
        Raises:
            RuleYAMLParserError: If rule definition is invalid
        """
        # Validate required fields
        required_fields = ["rule_id", "rule_type", "priority", "condition", "action"]
        for field in required_fields:
            if field not in rule_data:
                raise RuleYAMLParserError(f"Missing required field: {field}")
        
        # Parse rule_id
        rule_id = rule_data["rule_id"]
        if not isinstance(rule_id, str) or not rule_id:
            raise RuleYAMLParserError("rule_id must be a non-empty string")
        
        # Parse rule_type
        rule_type_str = rule_data["rule_type"]
        try:
            rule_type = RuleType[rule_type_str]
        except KeyError:
            valid_types = [rt.name for rt in RuleType]
            raise RuleYAMLParserError(
                f"Invalid rule_type: {rule_type_str}. Must be one of: {valid_types}"
            )
        
        # Parse priority
        priority = rule_data["priority"]
        if not isinstance(priority, int) or priority < 0:
            raise RuleYAMLParserError("priority must be a non-negative integer")
        
        # Parse condition
        condition = self._parse_condition(rule_data["condition"])
        
        # Parse action
        action = self._parse_action(rule_data["action"])
        
        # Parse metadata (optional)
        metadata = {}
        if "description" in rule_data:
            metadata["description"] = rule_data["description"]
        if "version" in rule_data:
            metadata["version"] = rule_data["version"]
        if "author" in rule_data:
            metadata["author"] = rule_data["author"]
        
        # Add any additional metadata fields
        for key, value in rule_data.items():
            if key not in required_fields and key not in ["description", "version", "author"]:
                metadata[key] = value
        
        return TransformationRule(
            rule_id=rule_id,
            rule_type=rule_type,
            priority=priority,
            condition=condition,
            action=action,
            metadata=metadata
        )
    
    def _parse_condition(self, condition_data: Dict[str, Any]) -> Callable[[Dict[str, Any]], bool]:
        """
        Parse a condition definition.
        
        Args:
            condition_data: Dictionary containing condition definition
            
        Returns:
            Condition function
            
        Raises:
            RuleYAMLParserError: If condition definition is invalid
        """
        if not isinstance(condition_data, dict):
            raise RuleYAMLParserError("condition must be a dictionary")
        
        if "type" not in condition_data:
            raise RuleYAMLParserError("condition must have a 'type' field")
        
        condition_type = condition_data["type"]
        
        if condition_type not in self.condition_registry:
            raise RuleYAMLParserError(
                f"Unknown condition type: {condition_type}. "
                f"Available types: {list(self.condition_registry.keys())}"
            )
        
        factory = self.condition_registry[condition_type]
        
        try:
            return factory(condition_data)
        except Exception as e:
            raise RuleYAMLParserError(f"Error creating condition '{condition_type}': {e}")
    
    def _parse_action(self, action_data: Dict[str, Any]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """
        Parse an action definition.
        
        Args:
            action_data: Dictionary containing action definition
            
        Returns:
            Action function
            
        Raises:
            RuleYAMLParserError: If action definition is invalid
        """
        if not isinstance(action_data, dict):
            raise RuleYAMLParserError("action must be a dictionary")
        
        if "type" not in action_data:
            raise RuleYAMLParserError("action must have a 'type' field")
        
        action_type = action_data["type"]
        
        if action_type not in self.action_registry:
            raise RuleYAMLParserError(
                f"Unknown action type: {action_type}. "
                f"Available types: {list(self.action_registry.keys())}"
            )
        
        factory = self.action_registry[action_type]
        
        try:
            return factory(action_data)
        except Exception as e:
            raise RuleYAMLParserError(f"Error creating action '{action_type}': {e}")
    
    def _build_condition_registry(self) -> Dict[str, Callable]:
        """Build registry of condition factory functions."""
        return {
            "always": self._create_always_condition,
            "field_exists": self._create_field_exists_condition,
            "field_not_exists": self._create_field_not_exists_condition,
            "field_is_null": self._create_field_is_null_condition,
            "field_is_not_null": self._create_field_is_not_null_condition,
            "field_type": self._create_field_type_condition,
            "field_value_equals": self._create_field_value_equals_condition,
            "field_value_in": self._create_field_value_in_condition,
            "field_value_matches": self._create_field_value_matches_condition,
            "field_value_contains": self._create_field_value_contains_condition,
            "field_value_range": self._create_field_value_range_condition,
            "all_fields_exist": self._create_all_fields_exist_condition,
            "any_field_exists": self._create_any_field_exists_condition,
            "and": self._create_and_condition,
            "or": self._create_or_condition,
            "not": self._create_not_condition,
        }
    
    def _build_action_registry(self) -> Dict[str, Callable]:
        """Build registry of action factory functions."""
        return {
            "trim_strings": self._create_trim_strings_action,
            "trim_field": self._create_trim_field_action,
            "uppercase_strings": self._create_uppercase_strings_action,
            "uppercase_field": self._create_uppercase_field_action,
            "lowercase_strings": self._create_lowercase_strings_action,
            "lowercase_field": self._create_lowercase_field_action,
            "normalize_whitespace": self._create_normalize_whitespace_action,
            "normalize_whitespace_field": self._create_normalize_whitespace_field_action,
            "cast_to_int": self._create_cast_to_int_action,
            "cast_to_float": self._create_cast_to_float_action,
            "cast_to_bool": self._create_cast_to_bool_action,
            "cast_to_date": self._create_cast_to_date_action,
            "regex_replace": self._create_regex_replace_action,
            "regex_extract": self._create_regex_extract_action,
            "remove_field": self._create_remove_field_action,
            "remove_null_fields": self._create_remove_null_fields_action,
            "rename_field": self._create_rename_field_action,
            "copy_field": self._create_copy_field_action,
            "replace_value": self._create_replace_value_action,
            "default_value": self._create_default_value_action,
            "compose": self._create_compose_action,
        }
    
    # ========================================================================
    # Condition Factory Functions
    # ========================================================================
    
    def _create_always_condition(self, data: Dict[str, Any]) -> Callable:
        """Create an 'always' condition."""
        return always_true
    
    def _create_field_exists_condition(self, data: Dict[str, Any]) -> Callable:
        """Create a 'field_exists' condition."""
        if "field_name" not in data:
            raise ValueError("field_exists condition requires 'field_name'")
        return field_exists(data["field_name"])
    
    def _create_field_not_exists_condition(self, data: Dict[str, Any]) -> Callable:
        """Create a 'field_not_exists' condition."""
        if "field_name" not in data:
            raise ValueError("field_not_exists condition requires 'field_name'")
        return field_not_exists(data["field_name"])
    
    def _create_field_is_null_condition(self, data: Dict[str, Any]) -> Callable:
        """Create a 'field_is_null' condition."""
        if "field_name" not in data:
            raise ValueError("field_is_null condition requires 'field_name'")
        return field_is_null(data["field_name"])
    
    def _create_field_is_not_null_condition(self, data: Dict[str, Any]) -> Callable:
        """Create a 'field_is_not_null' condition."""
        if "field_name" not in data:
            raise ValueError("field_is_not_null condition requires 'field_name'")
        return field_is_not_null(data["field_name"])
    
    def _create_field_type_condition(self, data: Dict[str, Any]) -> Callable:
        """Create a 'field_type' condition."""
        if "field_name" not in data:
            raise ValueError("field_type condition requires 'field_name'")
        if "expected_type" not in data:
            raise ValueError("field_type condition requires 'expected_type'")
        
        # Map type names to Python types
        type_map = {
            "string": str,
            "str": str,
            "integer": int,
            "int": int,
            "float": float,
            "boolean": bool,
            "bool": bool,
            "list": list,
            "dict": dict,
        }
        
        type_name = data["expected_type"]
        if type_name not in type_map:
            raise ValueError(f"Unknown type: {type_name}. Valid types: {list(type_map.keys())}")
        
        return field_type(data["field_name"], type_map[type_name])
    
    def _create_field_value_equals_condition(self, data: Dict[str, Any]) -> Callable:
        """Create a 'field_value_equals' condition."""
        if "field_name" not in data:
            raise ValueError("field_value_equals condition requires 'field_name'")
        if "expected_value" not in data:
            raise ValueError("field_value_equals condition requires 'expected_value'")
        return field_value_equals(data["field_name"], data["expected_value"])
    
    def _create_field_value_in_condition(self, data: Dict[str, Any]) -> Callable:
        """Create a 'field_value_in' condition."""
        if "field_name" not in data:
            raise ValueError("field_value_in condition requires 'field_name'")
        if "allowed_values" not in data:
            raise ValueError("field_value_in condition requires 'allowed_values'")
        
        allowed_values = data["allowed_values"]
        if not isinstance(allowed_values, list):
            raise ValueError("allowed_values must be a list")
        
        return field_value_in(data["field_name"], set(allowed_values))
    
    def _create_field_value_matches_condition(self, data: Dict[str, Any]) -> Callable:
        """Create a 'field_value_matches' condition."""
        if "field_name" not in data:
            raise ValueError("field_value_matches condition requires 'field_name'")
        if "pattern" not in data:
            raise ValueError("field_value_matches condition requires 'pattern'")
        return field_value_matches(data["field_name"], data["pattern"])
    
    def _create_field_value_contains_condition(self, data: Dict[str, Any]) -> Callable:
        """Create a 'field_value_contains' condition."""
        if "field_name" not in data:
            raise ValueError("field_value_contains condition requires 'field_name'")
        if "substring" not in data:
            raise ValueError("field_value_contains condition requires 'substring'")
        return field_value_contains(data["field_name"], data["substring"])
    
    def _create_field_value_range_condition(self, data: Dict[str, Any]) -> Callable:
        """Create a 'field_value_range' condition."""
        if "field_name" not in data:
            raise ValueError("field_value_range condition requires 'field_name'")
        
        min_value = data.get("min_value")
        max_value = data.get("max_value")
        
        if min_value is None and max_value is None:
            raise ValueError("field_value_range requires at least one of 'min_value' or 'max_value'")
        
        return field_value_range(data["field_name"], min_value, max_value)
    
    def _create_all_fields_exist_condition(self, data: Dict[str, Any]) -> Callable:
        """Create an 'all_fields_exist' condition."""
        if "field_names" not in data:
            raise ValueError("all_fields_exist condition requires 'field_names'")
        
        field_names = data["field_names"]
        if not isinstance(field_names, list):
            raise ValueError("field_names must be a list")
        
        return all_fields_exist(field_names)
    
    def _create_any_field_exists_condition(self, data: Dict[str, Any]) -> Callable:
        """Create an 'any_field_exists' condition."""
        if "field_names" not in data:
            raise ValueError("any_field_exists condition requires 'field_names'")
        
        field_names = data["field_names"]
        if not isinstance(field_names, list):
            raise ValueError("field_names must be a list")
        
        return any_field_exists(field_names)
    
    def _create_and_condition(self, data: Dict[str, Any]) -> Callable:
        """Create an 'and' condition."""
        if "conditions" not in data:
            raise ValueError("and condition requires 'conditions'")
        
        conditions_data = data["conditions"]
        if not isinstance(conditions_data, list):
            raise ValueError("conditions must be a list")
        
        conditions = [self._parse_condition(cond) for cond in conditions_data]
        return and_conditions(*conditions)
    
    def _create_or_condition(self, data: Dict[str, Any]) -> Callable:
        """Create an 'or' condition."""
        if "conditions" not in data:
            raise ValueError("or condition requires 'conditions'")
        
        conditions_data = data["conditions"]
        if not isinstance(conditions_data, list):
            raise ValueError("conditions must be a list")
        
        conditions = [self._parse_condition(cond) for cond in conditions_data]
        return or_conditions(*conditions)
    
    def _create_not_condition(self, data: Dict[str, Any]) -> Callable:
        """Create a 'not' condition."""
        if "condition" not in data:
            raise ValueError("not condition requires 'condition'")
        
        condition = self._parse_condition(data["condition"])
        return not_condition(condition)
    
    # ========================================================================
    # Action Factory Functions
    # ========================================================================
    
    def _create_trim_strings_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'trim_strings' action."""
        return trim_strings
    
    def _create_trim_field_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'trim_field' action."""
        if "field_name" not in data:
            raise ValueError("trim_field action requires 'field_name'")
        return trim_field(data["field_name"])
    
    def _create_uppercase_strings_action(self, data: Dict[str, Any]) -> Callable:
        """Create an 'uppercase_strings' action."""
        return uppercase_strings
    
    def _create_uppercase_field_action(self, data: Dict[str, Any]) -> Callable:
        """Create an 'uppercase_field' action."""
        if "field_name" not in data:
            raise ValueError("uppercase_field action requires 'field_name'")
        return uppercase_field(data["field_name"])
    
    def _create_lowercase_strings_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'lowercase_strings' action."""
        return lowercase_strings
    
    def _create_lowercase_field_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'lowercase_field' action."""
        if "field_name" not in data:
            raise ValueError("lowercase_field action requires 'field_name'")
        return lowercase_field(data["field_name"])
    
    def _create_normalize_whitespace_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'normalize_whitespace' action."""
        return normalize_whitespace
    
    def _create_normalize_whitespace_field_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'normalize_whitespace_field' action."""
        if "field_name" not in data:
            raise ValueError("normalize_whitespace_field action requires 'field_name'")
        return normalize_whitespace_field(data["field_name"])
    
    def _create_cast_to_int_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'cast_to_int' action."""
        if "field_name" not in data:
            raise ValueError("cast_to_int action requires 'field_name'")
        on_error = data.get("on_error", "raise")
        return cast_to_int(data["field_name"], on_error)
    
    def _create_cast_to_float_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'cast_to_float' action."""
        if "field_name" not in data:
            raise ValueError("cast_to_float action requires 'field_name'")
        on_error = data.get("on_error", "raise")
        return cast_to_float(data["field_name"], on_error)
    
    def _create_cast_to_bool_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'cast_to_bool' action."""
        if "field_name" not in data:
            raise ValueError("cast_to_bool action requires 'field_name'")
        on_error = data.get("on_error", "raise")
        return cast_to_bool(data["field_name"], on_error)
    
    def _create_cast_to_date_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'cast_to_date' action."""
        if "field_name" not in data:
            raise ValueError("cast_to_date action requires 'field_name'")
        date_format = data.get("date_format", "%Y-%m-%d")
        on_error = data.get("on_error", "raise")
        return cast_to_date(data["field_name"], date_format, on_error)
    
    def _create_regex_replace_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'regex_replace' action."""
        if "field_name" not in data:
            raise ValueError("regex_replace action requires 'field_name'")
        if "pattern" not in data:
            raise ValueError("regex_replace action requires 'pattern'")
        if "replacement" not in data:
            raise ValueError("regex_replace action requires 'replacement'")
        
        flags = data.get("flags", 0)
        return regex_replace(data["field_name"], data["pattern"], data["replacement"], flags)
    
    def _create_regex_extract_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'regex_extract' action."""
        if "field_name" not in data:
            raise ValueError("regex_extract action requires 'field_name'")
        if "pattern" not in data:
            raise ValueError("regex_extract action requires 'pattern'")
        
        group = data.get("group", 0)
        on_no_match = data.get("on_no_match", "skip")
        return regex_extract(data["field_name"], data["pattern"], group, on_no_match)
    
    def _create_remove_field_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'remove_field' action."""
        if "field_name" not in data:
            raise ValueError("remove_field action requires 'field_name'")
        return remove_field(data["field_name"])
    
    def _create_remove_null_fields_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'remove_null_fields' action."""
        return remove_null_fields
    
    def _create_rename_field_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'rename_field' action."""
        if "old_name" not in data:
            raise ValueError("rename_field action requires 'old_name'")
        if "new_name" not in data:
            raise ValueError("rename_field action requires 'new_name'")
        return rename_field(data["old_name"], data["new_name"])
    
    def _create_copy_field_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'copy_field' action."""
        if "source_name" not in data:
            raise ValueError("copy_field action requires 'source_name'")
        if "dest_name" not in data:
            raise ValueError("copy_field action requires 'dest_name'")
        return copy_field(data["source_name"], data["dest_name"])
    
    def _create_replace_value_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'replace_value' action."""
        if "field_name" not in data:
            raise ValueError("replace_value action requires 'field_name'")
        if "old_value" not in data:
            raise ValueError("replace_value action requires 'old_value'")
        if "new_value" not in data:
            raise ValueError("replace_value action requires 'new_value'")
        return replace_value(data["field_name"], data["old_value"], data["new_value"])
    
    def _create_default_value_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'default_value' action."""
        if "field_name" not in data:
            raise ValueError("default_value action requires 'field_name'")
        if "default" not in data:
            raise ValueError("default_value action requires 'default'")
        return default_value(data["field_name"], data["default"])
    
    def _create_compose_action(self, data: Dict[str, Any]) -> Callable:
        """Create a 'compose' action."""
        if "actions" not in data:
            raise ValueError("compose action requires 'actions'")
        
        actions_data = data["actions"]
        if not isinstance(actions_data, list):
            raise ValueError("actions must be a list")
        
        actions = [self._parse_action(action) for action in actions_data]
        return compose_actions(*actions)


def load_rules_from_yaml(yaml_path: str) -> List[TransformationRule]:
    """
    Convenience function to load transformation rules from a YAML file.
    
    Args:
        yaml_path: Path to the YAML file
        
    Returns:
        List of TransformationRule objects
        
    Raises:
        RuleYAMLParserError: If file cannot be read or parsed
        
    Example:
        >>> rules = load_rules_from_yaml("rules/cleaning_rules.yaml")
        >>> for rule in rules:
        ...     print(f"{rule.rule_id}: {rule.rule_type.name}")
    """
    parser = RuleYAMLParser()
    return parser.parse_file(yaml_path)
