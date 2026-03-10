#!/usr/bin/env python3
"""Helper script to write schema_evolution.py"""

SCHEMA_EVOLUTION_CODE = '''"""
Schema Evolution Detection - Automatic detection of schema changes.

This module provides automatic schema evolution detection capabilities:
- Infer schema from data samples
- Detect schema changes automatically
- Track schema evolution history
- Alert on breaking changes

Based on design.md section 3.2 and requirements AC 4.3.
"""
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from collections import Counter
from uuid import uuid4
import logging

from .schema_contract import (
    DataType,
    ConstraintType,
    Constraint,
    FieldDefinition,
    SchemaContract,
    SchemaEvolutionRecord,
    SchemaVersionComparator
)


logger = logging.getLogger(__name__)


@dataclass
class SchemaInferenceResult:
    """Result of schema inference from data."""
    inferred_schema: SchemaContract
    confidence_score: float
    sample_size: int
    field_statistics: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


@dataclass
class SchemaChangeAlert:
    """Alert for detected schema changes."""
    alert_id: str
    schema_id: str
    old_version: str
    new_version: Optional[str]
    evolution_record: SchemaEvolutionRecord
    severity: str  # INFO, WARNING, ERROR
    detected_at: datetime = field(default_factory=datetime.utcnow)
    acknowledged: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "alert_id": self.alert_id,
            "schema_id": self.schema_id,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "evolution_record": self.evolution_record.to_dict(),
            "severity": self.severity,
            "detected_at": self.detected_at.isoformat(),
            "acknowledged": self.acknowledged
        }


class SchemaInferenceEngine:
    """Infers schema from data samples."""
    
    def __init__(self, min_sample_size: int = 100):
        self.min_sample_size = min_sample_size
        logger.info("SchemaInferenceEngine initialized with min_sample_size=%d", min_sample_size)
    
    def infer_schema(
        self,
        rows: List[Dict[str, Any]],
        schema_id: str,
        version: str = "1.0.0"
    ) -> SchemaInferenceResult:
        """Infer schema from a sample of data rows."""
        if not rows:
            raise ValueError("Cannot infer schema from empty dataset")
        
        logger.info("Inferring schema from %d rows", len(rows))
        
        warnings = []
        if len(rows) < self.min_sample_size:
            warnings.append(
                f"Sample size ({len(rows)}) is below recommended minimum "
                f"({self.min_sample_size}). Inference may be unreliable."
            )
        
        field_stats = self._collect_field_statistics(rows)
        fields = []
        for field_name, stats in field_stats.items():
            field_def = self._infer_field_definition(field_name, stats, len(rows))
            fields.append(field_def)
        
        confidence_score = self._calculate_confidence_score(field_stats, len(rows))
        
        schema = SchemaContract(
            schema_id=schema_id,
            version=version,
            fields=fields,
            description=f"Auto-inferred schema from {len(rows)} samples",
            metadata={
                "inferred": True,
                "sample_size": len(rows),
                "confidence_score": confidence_score
            }
        )
        
        logger.info(
            "Schema inference complete: %d fields, confidence=%.2f",
            len(fields),
            confidence_score
        )
        
        return SchemaInferenceResult(
            inferred_schema=schema,
            confidence_score=confidence_score,
            sample_size=len(rows),
            field_statistics=field_stats,
            warnings=warnings
        )
    
    def _collect_field_statistics(self, rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Collect statistics about each field in the dataset."""
        field_stats: Dict[str, Dict[str, Any]] = {}
        
        all_fields: Set[str] = set()
        for row in rows:
            all_fields.update(row.keys())
        
        for field_name in all_fields:
            values = []
            null_count = 0
            
            for row in rows:
                if field_name in row:
                    value = row[field_name]
                    if value is None:
                        null_count += 1
                    else:
                        values.append(value)
            
            type_counts = Counter(type(v).__name__ for v in values)
            
            field_stats[field_name] = {
                "present_count": len(values) + null_count,
                "null_count": null_count,
                "non_null_count": len(values),
                "type_counts": dict(type_counts),
                "values": values,
                "unique_count": len(set(str(v) for v in values)) if values else 0
            }
        
        return field_stats
    
    def _infer_field_definition(
        self,
        field_name: str,
        stats: Dict[str, Any],
        total_rows: int
    ) -> FieldDefinition:
        """Infer field definition from statistics."""
        nullable = stats["null_count"] > 0
        data_type = self._infer_data_type(stats)
        constraints = self._infer_constraints(stats, data_type)
        
        return FieldDefinition(
            name=field_name,
            type=data_type,
            nullable=nullable,
            constraints=constraints,
            description=f"Auto-inferred from {stats['non_null_count']} samples",
            metadata={
                "inferred": True,
                "null_percentage": stats["null_count"] / total_rows if total_rows > 0 else 0,
                "unique_count": stats["unique_count"]
            }
        )
    
    def _infer_data_type(self, stats: Dict[str, Any]) -> DataType:
        """Infer data type from field statistics."""
        type_counts = stats["type_counts"]
        values = stats["values"]
        
        if not values:
            return DataType.STRING
        
        most_common_type = max(type_counts, key=type_counts.get) if type_counts else "str"
        
        if most_common_type == "bool":
            return DataType.BOOLEAN
        elif most_common_type == "int":
            return DataType.INTEGER
        elif most_common_type == "float":
            return DataType.FLOAT
        elif most_common_type == "list":
            return DataType.ARRAY
        elif most_common_type == "dict":
            return DataType.OBJECT
        elif most_common_type == "str":
            return self._infer_string_type(values)
        else:
            return DataType.STRING
    
    def _infer_string_type(self, values: List[Any]) -> DataType:
        """Infer specific type from string values."""
        sample_size = min(100, len(values))
        sample = values[:sample_size]
        
        date_count = 0
        timestamp_count = 0
        
        for value in sample:
            if not isinstance(value, str):
                continue
            
            if 'T' in value or ' ' in value:
                try:
                    datetime.fromisoformat(value.replace('Z', '+00:00'))
                    timestamp_count += 1
                    continue
                except (ValueError, AttributeError):
                    pass
            
            try:
                datetime.fromisoformat(value)
                date_count += 1
            except (ValueError, AttributeError):
                pass
        
        if timestamp_count > sample_size * 0.8:
            return DataType.TIMESTAMP
        elif date_count > sample_size * 0.8:
            return DataType.DATE
        
        return DataType.STRING
    
    def _infer_constraints(self, stats: Dict[str, Any], data_type: DataType) -> List[Constraint]:
        """Infer constraints from field statistics."""
        constraints = []
        values = stats["values"]
        
        if not values:
            return constraints
        
        if data_type in (DataType.INTEGER, DataType.FLOAT):
            try:
                numeric_values = [v for v in values if isinstance(v, (int, float))]
                if numeric_values:
                    min_val = min(numeric_values)
                    max_val = max(numeric_values)
                    
                    if min_val > 0:
                        constraints.append(Constraint(
                            constraint_type=ConstraintType.MIN,
                            value=min_val,
                            severity="warning"
                        ))
                    
                    if max_val < 1000000:
                        constraints.append(Constraint(
                            constraint_type=ConstraintType.MAX,
                            value=max_val,
                            severity="warning"
                        ))
            except (ValueError, TypeError):
                pass
        
        elif data_type == DataType.STRING:
            try:
                string_values = [str(v) for v in values if v is not None]
                if string_values:
                    min_len = min(len(s) for s in string_values)
                    max_len = max(len(s) for s in string_values)
                    
                    if min_len > 0:
                        constraints.append(Constraint(
                            constraint_type=ConstraintType.MIN,
                            value=min_len,
                            severity="warning"
                        ))
                    
                    if max_len < 1000:
                        constraints.append(Constraint(
                            constraint_type=ConstraintType.MAX,
                            value=max_len,
                            severity="warning"
                        ))
            except (ValueError, TypeError):
                pass
        
        unique_count = stats["unique_count"]
        non_null_count = stats["non_null_count"]
        
        if unique_count <= 10 and non_null_count > 0:
            unique_values = list(set(values))
            constraints.append(Constraint(
                constraint_type=ConstraintType.ENUM,
                value=unique_values,
                severity="warning"
            ))
        
        return constraints
    
    def _calculate_confidence_score(
        self,
        field_stats: Dict[str, Dict[str, Any]],
        total_rows: int
    ) -> float:
        """Calculate confidence score for schema inference."""
        if not field_stats or total_rows == 0:
            return 0.0
        
        scores = []
        
        for field_name, stats in field_stats.items():
            sample_factor = min(1.0, total_rows / self.min_sample_size)
            
            type_counts = stats["type_counts"]
            if type_counts:
                dominant_type_count = max(type_counts.values())
                type_consistency = dominant_type_count / stats["non_null_count"] if stats["non_null_count"] > 0 else 0
            else:
                type_consistency = 0.0
            
            completeness = stats["non_null_count"] / total_rows if total_rows > 0 else 0
            
            field_score = (sample_factor * 0.3 + type_consistency * 0.4 + completeness * 0.3)
            scores.append(field_score)
        
        return sum(scores) / len(scores) if scores else 0.0


class SchemaEvolutionDetector:
    """Detects schema evolution by comparing inferred schemas with existing schemas."""
    
    def __init__(self, inference_engine: Optional[SchemaInferenceEngine] = None):
        self.inference_engine = inference_engine or SchemaInferenceEngine()
        self._alert_history: List[SchemaChangeAlert] = []
        logger.info("SchemaEvolutionDetector initialized")
    
    def detect_evolution(
        self,
        current_schema: SchemaContract,
        new_data_sample: List[Dict[str, Any]],
        auto_version: bool = True
    ) -> Optional[SchemaChangeAlert]:
        """Detect schema evolution by comparing current schema with new data."""
        logger.info(
            "Detecting schema evolution for %s v%s with %d samples",
            current_schema.schema_id,
            current_schema.version,
            len(new_data_sample)
        )
        
        inference_result = self.inference_engine.infer_schema(
            rows=new_data_sample,
            schema_id=current_schema.schema_id,
            version="inferred"
        )
        
        inferred_schema = inference_result.inferred_schema
        
        evolution_record = SchemaVersionComparator.compare_versions(
            old_schema=current_schema,
            new_schema=inferred_schema
        )
        
        if evolution_record.change_type == "NO_CHANGE":
            logger.info("No schema changes detected")
            return None
        
        new_version = None
        if auto_version:
            new_version = self._calculate_next_version(
                current_version=current_schema.version,
                backward_compatible=evolution_record.backward_compatible,
                change_type=evolution_record.change_type
            )
            evolution_record.to_version = new_version
        
        severity = self._determine_severity(evolution_record)
        
        alert = SchemaChangeAlert(
            alert_id=str(uuid4()),
            schema_id=current_schema.schema_id,
            old_version=current_schema.version,
            new_version=new_version,
            evolution_record=evolution_record,
            severity=severity
        )
        
        self._alert_history.append(alert)
        
        logger.warning(
            "Schema evolution detected: %s v%s -> v%s (%s, %s)",
            current_schema.schema_id,
            current_schema.version,
            new_version or "unassigned",
            evolution_record.change_type,
            severity
        )
        
        return alert
    
    def _calculate_next_version(
        self,
        current_version: str,
        backward_compatible: bool,
        change_type: str
    ) -> str:
        """Calculate next semantic version based on change type."""
        try:
            major, minor, patch = SchemaVersionComparator.parse_semantic_version(current_version)
            
            if not backward_compatible or change_type == "DELETION":
                return f"{major + 1}.0.0"
            elif change_type == "ADDITION":
                return f"{major}.{minor + 1}.0"
            else:
                return f"{major}.{minor}.{patch + 1}"
        except ValueError:
            return f"{current_version}.1"
    
    def _determine_severity(self, evolution_record: SchemaEvolutionRecord) -> str:
        """Determine alert severity based on evolution record."""
        if not evolution_record.backward_compatible:
            return "ERROR"
        elif evolution_record.change_type == "MODIFICATION":
            return "WARNING"
        else:
            return "INFO"
    
    def get_alert_history(
        self,
        schema_id: Optional[str] = None,
        severity: Optional[str] = None,
        acknowledged: Optional[bool] = None
    ) -> List[SchemaChangeAlert]:
        """Get alert history with optional filtering."""
        alerts = self._alert_history
        
        if schema_id:
            alerts = [a for a in alerts if a.schema_id == schema_id]
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        if acknowledged is not None:
            alerts = [a for a in alerts if a.acknowledged == acknowledged]
        
        return alerts
    
    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        for alert in self._alert_history:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                logger.info("Alert %s acknowledged", alert_id)
                return True
        
        logger.warning("Alert %s not found", alert_id)
        return False
    
    def clear_alert_history(self) -> None:
        """Clear all alerts from history."""
        self._alert_history.clear()
        logger.info("Alert history cleared")
'''

if __name__ == "__main__":
    with open("schema_evolution.py", "w", encoding="utf-8") as f:
        f.write(SCHEMA_EVOLUTION_CODE)
    print("schema_evolution.py written successfully")
