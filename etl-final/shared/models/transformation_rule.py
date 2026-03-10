"""
Transformation Rules Engine - Data Models
Implements declarative transformation rules for the Silver layer.

Based on design.md section 3.1 and requirements US-6 (AC 6.1-6.4).

Key Design Principles:
- Pure functional design (stateless, no side effects)
- Deterministic transformations (same input  same output)
- Auditable (tracks which rules applied and why)
- Versioned (rules are versioned and changes tracked)
- Composable (rules are independent and can be combined)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4


class RuleType(Enum):
    """
    Types of transformation rules.
    
    CLEAN: Data cleaning operations (trim, remove nulls, normalize whitespace)
    VALIDATE: Data validation checks (regex, range, format)
    TRANSFORM: Data transformations (type casting, calculations, derivations)
    ENRICH: Data enrichment (lookups, augmentation with external data)
    """
    CLEAN = "CLEAN"
    VALIDATE = "VALIDATE"
    TRANSFORM = "TRANSFORM"
    ENRICH = "ENRICH"


@dataclass(frozen=True)
class TransformationRule:
    """
    Immutable transformation rule definition.
    
    Attributes:
        rule_id: Unique identifier for the rule (e.g., "trim_strings_v1")
        rule_type: Type of rule (CLEAN, VALIDATE, TRANSFORM, ENRICH)
        priority: Execution priority (lower numbers execute first)
        condition: Function that determines if rule applies to a row
        action: Function that performs the transformation
        metadata: Additional metadata (description, version, author, etc.)
    
    Example:
        rule = TransformationRule(
            rule_id="trim_strings_v1",
            rule_type=RuleType.CLEAN,
            priority=1,
            condition=lambda row: any(isinstance(v, str) for v in row.values()),
            action=lambda row: {k: v.strip() if isinstance(v, str) else v 
                               for k, v in row.items()},
            metadata={"description": "Trim whitespace from all string fields",
                     "version": "1.0.0"}
        )
    """
    rule_id: str
    rule_type: RuleType
    priority: int
    condition: Callable[[Dict[str, Any]], bool]
    action: Callable[[Dict[str, Any]], Dict[str, Any]]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate rule configuration."""
        if not self.rule_id:
            raise ValueError("rule_id cannot be empty")
        if self.priority < 0:
            raise ValueError("priority must be non-negative")
        if not callable(self.condition):
            raise ValueError("condition must be callable")
        if not callable(self.action):
            raise ValueError("action must be callable")


@dataclass
class TransformationResult:
    """
    Result of applying transformation rules to a row.
    
    Attributes:
        transformed_row: The row after transformations
        applied_rules: List of rule IDs that were applied
        warnings: List of warning messages
        errors: List of error messages
        original_row: The original row before transformations (for audit)
        quality_score: Optional quality score (0.0 to 1.0)
    """
    transformed_row: Dict[str, Any]
    applied_rules: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    original_row: Optional[Dict[str, Any]] = None
    quality_score: Optional[float] = None
    
    def __post_init__(self):
        """Validate quality score if provided."""
        if self.quality_score is not None:
            if not 0.0 <= self.quality_score <= 1.0:
                raise ValueError("quality_score must be between 0.0 and 1.0")


@dataclass
class RuleExecutionContext:
    """
    Context information for rule execution.
    
    Attributes:
        batch_id: ID of the batch being processed
        source_id: ID of the data source
        schema_version: Version of the schema
        execution_timestamp: When the rules are being executed
        additional_context: Any additional context needed by rules
    """
    batch_id: str
    source_id: str
    schema_version: str
    execution_timestamp: datetime = field(default_factory=datetime.utcnow)
    additional_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleExecutionRecord:
    """
    Audit record of a rule execution.
    
    Attributes:
        record_id: Unique identifier for this execution record
        rule_id: ID of the rule that was executed
        row_id: ID of the row that was transformed
        execution_timestamp: When the rule was executed
        success: Whether the rule executed successfully
        changes_made: Dictionary of field changes (field_name -> (old_value, new_value))
        error_message: Error message if execution failed
        execution_time_ms: Time taken to execute the rule in milliseconds
    """
    record_id: UUID = field(default_factory=uuid4)
    rule_id: str = ""
    row_id: Optional[UUID] = None
    execution_timestamp: datetime = field(default_factory=datetime.utcnow)
    success: bool = True
    changes_made: Dict[str, tuple] = field(default_factory=dict)
    error_message: Optional[str] = None
    execution_time_ms: Optional[float] = None
