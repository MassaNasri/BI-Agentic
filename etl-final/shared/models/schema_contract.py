"""
Schema Contract Framework - Data Models
Implements schema validation and enforcement for ETL pipeline.

Based on design.md section 3.2 and requirements FR-4, FR-5, US-4.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4
import re


class DataType(Enum):
    """Supported data types for schema fields."""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    TIMESTAMP = "timestamp"
    ARRAY = "array"
    OBJECT = "object"


class ConstraintType(Enum):
    """Types of constraints that can be applied to fields."""
    MIN = "min"  # Minimum value (numeric) or length (string/array)
    MAX = "max"  # Maximum value (numeric) or length (string/array)
    REGEX = "regex"  # Regular expression pattern (string)
    ENUM = "enum"  # Allowed values (any type)
    UNIQUE = "unique"  # Field must be unique
    REQUIRED = "required"  # Field must be present
    FORMAT = "format"  # Specific format (e.g., email, url, uuid)
    RANGE = "range"  # Value must be within range


@dataclass
class Constraint:
    """
    Represents a validation constraint on a field.
    
    Attributes:
        constraint_type: Type of constraint (MIN, MAX, REGEX, etc.)
        value: Constraint value (e.g., min value, regex pattern, enum list)
        error_message: Custom error message for constraint violation
        severity: Severity level ('error' or 'warning')
    """
    constraint_type: ConstraintType
    value: Any
    error_message: Optional[str] = None
    severity: str = "error"  # 'error' or 'warning'
    
    def validate(self, field_value: Any, field_name: str) -> tuple[bool, Optional[str]]:
        """
        Validate a field value against this constraint.
        
        Args:
            field_value: The value to validate
            field_name: Name of the field (for error messages)
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            if self.constraint_type == ConstraintType.MIN:
                if isinstance(field_value, (int, float)):
                    is_valid = field_value >= self.value
                elif isinstance(field_value, (str, list)):
                    is_valid = len(field_value) >= self.value
                else:
                    return False, f"MIN constraint not applicable to {type(field_value).__name__}"
                
                if not is_valid:
                    return False, self.error_message or f"{field_name} must be >= {self.value}"
            
            elif self.constraint_type == ConstraintType.MAX:
                if isinstance(field_value, (int, float)):
                    is_valid = field_value <= self.value
                elif isinstance(field_value, (str, list)):
                    is_valid = len(field_value) <= self.value
                else:
                    return False, f"MAX constraint not applicable to {type(field_value).__name__}"
                
                if not is_valid:
                    return False, self.error_message or f"{field_name} must be <= {self.value}"
            
            elif self.constraint_type == ConstraintType.REGEX:
                if not isinstance(field_value, str):
                    return False, f"REGEX constraint only applicable to strings"
                
                pattern = re.compile(self.value)
                if not pattern.match(field_value):
                    return False, self.error_message or f"{field_name} does not match pattern {self.value}"
            
            elif self.constraint_type == ConstraintType.ENUM:
                if field_value not in self.value:
                    return False, self.error_message or f"{field_name} must be one of {self.value}"
            
            elif self.constraint_type == ConstraintType.FORMAT:
                # Common format validations
                if self.value == "email":
                    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                    if not re.match(email_pattern, str(field_value)):
                        return False, self.error_message or f"{field_name} must be a valid email"
                elif self.value == "url":
                    url_pattern = r'^https?://[^\s/$.?#].[^\s]*$'
                    if not re.match(url_pattern, str(field_value)):
                        return False, self.error_message or f"{field_name} must be a valid URL"
                elif self.value == "uuid":
                    try:
                        UUID(str(field_value))
                    except ValueError:
                        return False, self.error_message or f"{field_name} must be a valid UUID"
            
            elif self.constraint_type == ConstraintType.RANGE:
                if not isinstance(self.value, (list, tuple)) or len(self.value) != 2:
                    return False, "RANGE constraint value must be [min, max]"
                
                min_val, max_val = self.value
                if not (min_val <= field_value <= max_val):
                    return False, self.error_message or f"{field_name} must be between {min_val} and {max_val}"
            
            return True, None
            
        except Exception as e:
            return False, f"Constraint validation error: {str(e)}"


@dataclass
class FieldDefinition:
    """
    Defines a field in the schema contract.
    
    Attributes:
        name: Field name
        type: Data type (STRING, INTEGER, etc.)
        nullable: Whether field can be null
        constraints: List of validation constraints
        description: Human-readable field description
        default_value: Default value if field is missing
        metadata: Additional metadata (e.g., source column mapping)
    """
    name: str
    type: DataType
    nullable: bool = True
    constraints: List[Constraint] = field(default_factory=list)
    description: str = ""
    default_value: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def validate_type(self, value: Any) -> tuple[bool, Optional[str]]:
        """
        Validate that a value matches the expected type.
        
        Args:
            value: Value to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if value is None:
            if not self.nullable:
                return False, f"Field {self.name} cannot be null"
            return True, None
        
        # Type validation
        if self.type == DataType.STRING:
            if not isinstance(value, str):
                return False, f"Field {self.name} must be string, got {type(value).__name__}"
        
        elif self.type == DataType.INTEGER:
            if not isinstance(value, int) or isinstance(value, bool):
                return False, f"Field {self.name} must be integer, got {type(value).__name__}"
        
        elif self.type == DataType.FLOAT:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, f"Field {self.name} must be float, got {type(value).__name__}"
        
        elif self.type == DataType.BOOLEAN:
            if not isinstance(value, bool):
                return False, f"Field {self.name} must be boolean, got {type(value).__name__}"
        
        elif self.type == DataType.DATE:
            # Accept datetime objects or ISO date strings
            if isinstance(value, str):
                try:
                    datetime.fromisoformat(value.split('T')[0])
                except ValueError:
                    return False, f"Field {self.name} must be valid date string (ISO format)"
            elif not isinstance(value, datetime):
                return False, f"Field {self.name} must be date, got {type(value).__name__}"
        
        elif self.type == DataType.TIMESTAMP:
            # Accept datetime objects or ISO timestamp strings
            if isinstance(value, str):
                try:
                    datetime.fromisoformat(value.replace('Z', '+00:00'))
                except ValueError:
                    return False, f"Field {self.name} must be valid timestamp string (ISO format)"
            elif not isinstance(value, datetime):
                return False, f"Field {self.name} must be timestamp, got {type(value).__name__}"
        
        elif self.type == DataType.ARRAY:
            if not isinstance(value, list):
                return False, f"Field {self.name} must be array, got {type(value).__name__}"
        
        elif self.type == DataType.OBJECT:
            if not isinstance(value, dict):
                return False, f"Field {self.name} must be object, got {type(value).__name__}"
        
        return True, None
    
    def validate(self, value: Any) -> tuple[bool, List[str]]:
        """
        Validate a value against this field definition.
        
        Args:
            value: Value to validate
            
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        
        # Type validation
        is_valid, error = self.validate_type(value)
        if not is_valid:
            errors.append(error)
            return False, errors
        
        # Skip constraint validation if value is None and nullable
        if value is None and self.nullable:
            return True, []
        
        # Constraint validation
        for constraint in self.constraints:
            is_valid, error = constraint.validate(value, self.name)
            if not is_valid:
                if constraint.severity == "error":
                    errors.append(error)
                # Warnings are logged but don't fail validation
        
        return len(errors) == 0, errors


@dataclass
class SchemaContract:
    """
    Defines a data contract for schema validation.
    
    A schema contract specifies the expected structure, types, and constraints
    for data at a specific pipeline stage. Contracts are versioned and tracked
    for schema evolution.
    
    Attributes:
        schema_id: Unique identifier for this schema
        version: Schema version (semantic versioning recommended)
        fields: List of field definitions
        constraints: Global constraints (e.g., unique combinations)
        description: Human-readable schema description
        created_at: When this schema version was created
        created_by: Who created this schema version
        metadata: Additional metadata (e.g., source system, table name)
    """
    schema_id: str
    version: str
    fields: List[FieldDefinition]
    constraints: List[Constraint] = field(default_factory=list)
    description: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_field(self, field_name: str) -> Optional[FieldDefinition]:
        """
        Get field definition by name.
        
        Args:
            field_name: Name of the field
            
        Returns:
            FieldDefinition or None if not found
        """
        for field_def in self.fields:
            if field_def.name == field_name:
                return field_def
        return None
    
    def get_required_fields(self) -> List[str]:
        """
        Get list of required field names.
        
        Returns:
            List of field names that are required (not nullable or have REQUIRED constraint)
        """
        required = []
        for field_def in self.fields:
            if not field_def.nullable:
                required.append(field_def.name)
            else:
                # Check for REQUIRED constraint
                for constraint in field_def.constraints:
                    if constraint.constraint_type == ConstraintType.REQUIRED:
                        required.append(field_def.name)
                        break
        return required
    
    def validate_row(self, row: Dict[str, Any]) -> 'ValidationResult':
        """
        Validate a row against this schema contract.
        
        Args:
            row: Dictionary representing a data row
            
        Returns:
            ValidationResult object
        """
        violations = []
        warnings = []
        field_scores = {}
        
        # Check required fields
        required_fields = self.get_required_fields()
        for field_name in required_fields:
            if field_name not in row:
                violations.append(f"Required field {field_name} is missing")
        
        # Validate each field in the row
        for field_name, field_value in row.items():
            field_def = self.get_field(field_name)
            
            if field_def is None:
                # Unknown field - warning but not error
                warnings.append(f"Unknown field {field_name} not in schema")
                continue
            
            # Validate field
            is_valid, errors = field_def.validate(field_value)
            
            if not is_valid:
                violations.extend(errors)
                field_scores[field_name] = 0.0
            else:
                field_scores[field_name] = 1.0
        
        # Check for missing optional fields
        for field_def in self.fields:
            if field_def.name not in row and field_def.nullable:
                field_scores[field_def.name] = 0.5  # Partial score for missing optional
        
        # Calculate quality score
        if field_scores:
            quality_score = sum(field_scores.values()) / len(self.fields)
        else:
            quality_score = 0.0
        
        is_valid = len(violations) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            violations=violations,
            warnings=warnings,
            quality_score=quality_score,
            field_scores=field_scores,
            schema_id=self.schema_id,
            schema_version=self.version
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert schema contract to dictionary for serialization.
        
        Returns:
            Dictionary representation
        """
        return {
            "schema_id": self.schema_id,
            "version": self.version,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "fields": [
                {
                    "name": f.name,
                    "type": f.type.value,
                    "nullable": f.nullable,
                    "description": f.description,
                    "default_value": f.default_value,
                    "constraints": [
                        {
                            "type": c.constraint_type.value,
                            "value": c.value,
                            "error_message": c.error_message,
                            "severity": c.severity
                        }
                        for c in f.constraints
                    ],
                    "metadata": f.metadata
                }
                for f in self.fields
            ],
            "constraints": [
                {
                    "type": c.constraint_type.value,
                    "value": c.value,
                    "error_message": c.error_message,
                    "severity": c.severity
                }
                for c in self.constraints
            ],
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SchemaContract':
        """
        Create SchemaContract from dictionary.
        
        Args:
            data: Dictionary representation
            
        Returns:
            SchemaContract instance
        """
        fields = []
        for field_data in data.get("fields", []):
            constraints = [
                Constraint(
                    constraint_type=ConstraintType(c["type"]),
                    value=c["value"],
                    error_message=c.get("error_message"),
                    severity=c.get("severity", "error")
                )
                for c in field_data.get("constraints", [])
            ]
            
            fields.append(FieldDefinition(
                name=field_data["name"],
                type=DataType(field_data["type"]),
                nullable=field_data.get("nullable", True),
                constraints=constraints,
                description=field_data.get("description", ""),
                default_value=field_data.get("default_value"),
                metadata=field_data.get("metadata", {})
            ))
        
        global_constraints = [
            Constraint(
                constraint_type=ConstraintType(c["type"]),
                value=c["value"],
                error_message=c.get("error_message"),
                severity=c.get("severity", "error")
            )
            for c in data.get("constraints", [])
        ]
        
        return cls(
            schema_id=data["schema_id"],
            version=data["version"],
            fields=fields,
            constraints=global_constraints,
            description=data.get("description", ""),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.utcnow().isoformat())),
            created_by=data.get("created_by", ""),
            metadata=data.get("metadata", {})
        )


@dataclass
class ValidationResult:
    """
    Result of schema validation.
    
    Attributes:
        is_valid: Whether validation passed
        violations: List of validation errors
        warnings: List of validation warnings
        quality_score: Overall quality score (0.0 to 1.0)
        field_scores: Per-field quality scores
        schema_id: ID of schema used for validation
        schema_version: Version of schema used for validation
        validated_at: When validation was performed
    """
    is_valid: bool
    violations: List[str]
    warnings: List[str] = field(default_factory=list)
    quality_score: float = 0.0
    field_scores: Dict[str, float] = field(default_factory=dict)
    schema_id: str = ""
    schema_version: str = ""
    validated_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "is_valid": self.is_valid,
            "violations": self.violations,
            "warnings": self.warnings,
            "quality_score": self.quality_score,
            "field_scores": self.field_scores,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "validated_at": self.validated_at.isoformat()
        }


@dataclass
class SchemaEvolutionRecord:
    """
    Tracks schema evolution over time.
    
    Attributes:
        evolution_id: Unique identifier for this evolution event
        schema_id: ID of the schema
        from_version: Previous version
        to_version: New version
        changes: List of changes made
        change_type: Type of change (ADDITION, MODIFICATION, DELETION)
        backward_compatible: Whether change is backward compatible
        created_at: When evolution occurred
        created_by: Who made the change
    """
    evolution_id: UUID = field(default_factory=uuid4)
    schema_id: str = ""
    from_version: str = ""
    to_version: str = ""
    changes: List[str] = field(default_factory=list)
    change_type: str = ""  # ADDITION, MODIFICATION, DELETION
    backward_compatible: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "evolution_id": str(self.evolution_id),
            "schema_id": self.schema_id,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "changes": self.changes,
            "change_type": self.change_type,
            "backward_compatible": self.backward_compatible,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by
        }


class SchemaVersionComparator:
    """
    Compares schema versions and detects changes.
    
    This class provides utilities for comparing two schema contracts
    and identifying differences, which is essential for schema evolution
    tracking and backward compatibility analysis.
    """
    
    @staticmethod
    def compare_versions(
        old_schema: SchemaContract,
        new_schema: SchemaContract
    ) -> SchemaEvolutionRecord:
        """
        Compare two schema versions and generate an evolution record.
        
        Args:
            old_schema: Previous schema version
            new_schema: New schema version
            
        Returns:
            SchemaEvolutionRecord documenting the changes
            
        Example:
            old_schema = SchemaContract(schema_id="user", version="1.0.0", fields=[...])
            new_schema = SchemaContract(schema_id="user", version="1.1.0", fields=[...])
            
            evolution = SchemaVersionComparator.compare_versions(old_schema, new_schema)
            print(f"Changes: {evolution.changes}")
            print(f"Backward compatible: {evolution.backward_compatible}")
        """
        if old_schema.schema_id != new_schema.schema_id:
            raise ValueError(
                f"Cannot compare schemas with different IDs: "
                f"{old_schema.schema_id} vs {new_schema.schema_id}"
            )
        
        changes = []
        change_types = set()
        backward_compatible = True
        
        # Build field maps for comparison
        old_fields = {f.name: f for f in old_schema.fields}
        new_fields = {f.name: f for f in new_schema.fields}
        
        # Check for added fields
        added_fields = set(new_fields.keys()) - set(old_fields.keys())
        for field_name in added_fields:
            field_def = new_fields[field_name]
            changes.append(f"Added field '{field_name}' ({field_def.type.value})")
            change_types.add("ADDITION")
            
            # Adding a non-nullable field breaks backward compatibility
            if not field_def.nullable and field_def.default_value is None:
                backward_compatible = False
                changes.append(
                    f"  WARNING: Field '{field_name}' is non-nullable without default "
                    "(breaks backward compatibility)"
                )
        
        # Check for removed fields
        removed_fields = set(old_fields.keys()) - set(new_fields.keys())
        for field_name in removed_fields:
            changes.append(f"Removed field '{field_name}'")
            change_types.add("DELETION")
            # Removing fields always breaks backward compatibility
            backward_compatible = False
        
        # Check for modified fields
        common_fields = set(old_fields.keys()) & set(new_fields.keys())
        for field_name in common_fields:
            old_field = old_fields[field_name]
            new_field = new_fields[field_name]
            
            field_changes = SchemaVersionComparator._compare_fields(
                field_name, old_field, new_field
            )
            
            if field_changes:
                changes.extend(field_changes["changes"])
                change_types.add("MODIFICATION")
                if not field_changes["backward_compatible"]:
                    backward_compatible = False
        
        # Determine primary change type
        if "DELETION" in change_types:
            primary_change_type = "DELETION"
        elif "MODIFICATION" in change_types:
            primary_change_type = "MODIFICATION"
        elif "ADDITION" in change_types:
            primary_change_type = "ADDITION"
        else:
            primary_change_type = "NO_CHANGE"
        
        return SchemaEvolutionRecord(
            schema_id=old_schema.schema_id,
            from_version=old_schema.version,
            to_version=new_schema.version,
            changes=changes if changes else ["No changes detected"],
            change_type=primary_change_type,
            backward_compatible=backward_compatible
        )
    
    @staticmethod
    def _compare_fields(
        field_name: str,
        old_field: FieldDefinition,
        new_field: FieldDefinition
    ) -> Optional[Dict[str, Any]]:
        """
        Compare two field definitions and identify changes.
        
        Args:
            field_name: Name of the field being compared
            old_field: Previous field definition
            new_field: New field definition
            
        Returns:
            Dictionary with 'changes' list and 'backward_compatible' flag,
            or None if no changes detected
        """
        changes = []
        backward_compatible = True
        
        # Check type changes
        if old_field.type != new_field.type:
            changes.append(
                f"Modified field '{field_name}': type changed from "
                f"{old_field.type.value} to {new_field.type.value}"
            )
            # Type changes generally break backward compatibility
            backward_compatible = False
        
        # Check nullability changes
        if old_field.nullable != new_field.nullable:
            if old_field.nullable and not new_field.nullable:
                changes.append(
                    f"Modified field '{field_name}': changed from nullable to non-nullable"
                )
                # Making field non-nullable breaks backward compatibility
                backward_compatible = False
            else:
                changes.append(
                    f"Modified field '{field_name}': changed from non-nullable to nullable"
                )
                # Making field nullable is backward compatible
        
        # Check constraint changes
        old_constraints = {c.constraint_type: c for c in old_field.constraints}
        new_constraints = {c.constraint_type: c for c in new_field.constraints}
        
        # Added constraints
        added_constraint_types = set(new_constraints.keys()) - set(old_constraints.keys())
        for constraint_type in added_constraint_types:
            constraint = new_constraints[constraint_type]
            changes.append(
                f"Modified field '{field_name}': added {constraint_type.value} constraint"
            )
            # Adding constraints can break backward compatibility
            # (existing data might not satisfy new constraints)
            backward_compatible = False
        
        # Removed constraints
        removed_constraint_types = set(old_constraints.keys()) - set(new_constraints.keys())
        for constraint_type in removed_constraint_types:
            changes.append(
                f"Modified field '{field_name}': removed {constraint_type.value} constraint"
            )
            # Removing constraints is backward compatible
        
        # Modified constraints
        common_constraint_types = set(old_constraints.keys()) & set(new_constraints.keys())
        for constraint_type in common_constraint_types:
            old_constraint = old_constraints[constraint_type]
            new_constraint = new_constraints[constraint_type]
            
            if old_constraint.value != new_constraint.value:
                changes.append(
                    f"Modified field '{field_name}': {constraint_type.value} constraint "
                    f"changed from {old_constraint.value} to {new_constraint.value}"
                )
                # Constraint value changes may break backward compatibility
                # (depends on whether constraints became more or less restrictive)
                if SchemaVersionComparator._is_constraint_more_restrictive(
                    constraint_type, old_constraint.value, new_constraint.value
                ):
                    backward_compatible = False
        
        if not changes:
            return None
        
        return {
            "changes": changes,
            "backward_compatible": backward_compatible
        }
    
    @staticmethod
    def _is_constraint_more_restrictive(
        constraint_type: ConstraintType,
        old_value: Any,
        new_value: Any
    ) -> bool:
        """
        Determine if a constraint change makes it more restrictive.
        
        Args:
            constraint_type: Type of constraint
            old_value: Previous constraint value
            new_value: New constraint value
            
        Returns:
            True if new constraint is more restrictive
        """
        if constraint_type == ConstraintType.MIN:
            # Higher minimum is more restrictive
            return new_value > old_value
        elif constraint_type == ConstraintType.MAX:
            # Lower maximum is more restrictive
            return new_value < old_value
        elif constraint_type == ConstraintType.RANGE:
            # Narrower range is more restrictive
            old_min, old_max = old_value
            new_min, new_max = new_value
            return new_min > old_min or new_max < old_max
        elif constraint_type == ConstraintType.ENUM:
            # Fewer allowed values is more restrictive
            return len(new_value) < len(old_value)
        else:
            # For other constraint types, assume more restrictive
            return True
    
    @staticmethod
    def is_compatible(
        old_schema: SchemaContract,
        new_schema: SchemaContract
    ) -> bool:
        """
        Check if new schema is backward compatible with old schema.
        
        Args:
            old_schema: Previous schema version
            new_schema: New schema version
            
        Returns:
            True if new schema is backward compatible
            
        Example:
            if SchemaVersionComparator.is_compatible(old_schema, new_schema):
                print("Safe to upgrade")
            else:
                print("Breaking changes detected")
        """
        evolution = SchemaVersionComparator.compare_versions(old_schema, new_schema)
        return evolution.backward_compatible
    
    @staticmethod
    def parse_semantic_version(version: str) -> tuple[int, int, int]:
        """
        Parse semantic version string (e.g., "1.2.3").
        
        Args:
            version: Version string in format "major.minor.patch"
            
        Returns:
            Tuple of (major, minor, patch) as integers
            
        Raises:
            ValueError: If version string is invalid
        """
        try:
            parts = version.split('.')
            if len(parts) != 3:
                raise ValueError(f"Version must have 3 parts: {version}")
            
            major, minor, patch = map(int, parts)
            return (major, minor, patch)
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Invalid semantic version: {version}") from e
    
    @staticmethod
    def compare_semantic_versions(version1: str, version2: str) -> int:
        """
        Compare two semantic versions.
        
        Args:
            version1: First version string
            version2: Second version string
            
        Returns:
            -1 if version1 < version2
             0 if version1 == version2
             1 if version1 > version2
             
        Example:
            result = SchemaVersionComparator.compare_semantic_versions("1.0.0", "1.1.0")
            if result < 0:
                print("version1 is older")
        """
        v1 = SchemaVersionComparator.parse_semantic_version(version1)
        v2 = SchemaVersionComparator.parse_semantic_version(version2)
        
        if v1 < v2:
            return -1
        elif v1 > v2:
            return 1
        else:
            return 0
