"""
Shared data models for ETL pipeline.
Implements Medallion Architecture schemas (Bronze/Silver/Gold).
"""
from .bronze_schema import BronzeTableSchema, BronzeRow, BronzeBatch
from .schema_contract import (
    DataType,
    ConstraintType,
    Constraint,
    FieldDefinition,
    SchemaContract,
    ValidationResult,
    SchemaEvolutionRecord
)
from .schema_validator import SchemaValidator, BatchValidationResult
from .lineage import LineageRecord

__all__ = [
    "BronzeTableSchema",
    "BronzeRow",
    "BronzeBatch",
    "DataType",
    "ConstraintType",
    "Constraint",
    "FieldDefinition",
    "SchemaContract",
    "ValidationResult",
    "SchemaEvolutionRecord",
    "SchemaValidator",
    "BatchValidationResult",
    "LineageRecord",
]
