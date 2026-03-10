"""
Silver Layer Schema Definition
Implements cleaned and validated data storage with quality metadata.

Based on design.md section 5.2 and requirements FR-2, US-6, US-7.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum


class DataType(str, Enum):
    """Supported data types for silver layer columns."""
    STRING = "String"
    INT8 = "Int8"
    INT16 = "Int16"
    INT32 = "Int32"
    INT64 = "Int64"
    UINT8 = "UInt8"
    UINT16 = "UInt16"
    UINT32 = "UInt32"
    UINT64 = "UInt64"
    FLOAT32 = "Float32"
    FLOAT64 = "Float64"
    BOOLEAN = "Bool"
    DATE = "Date"
    DATETIME = "DateTime"
    DATETIME64 = "DateTime64(3)"
    UUID_TYPE = "UUID"
    ARRAY_STRING = "Array(String)"
    ARRAY_INT64 = "Array(Int64)"
    ARRAY_FLOAT64 = "Array(Float64)"


@dataclass
class SilverColumnDefinition:
    """
    Definition of a single column in the silver layer.
    
    Attributes:
        name: Column name
        data_type: ClickHouse data type
        nullable: Whether the column can contain NULL values
        default_value: Default value if not provided
        comment: Description of the column
    """
    name: str
    data_type: DataType
    nullable: bool = False
    default_value: Optional[str] = None
    comment: str = ""
    
    def to_sql(self) -> str:
        """Generate SQL column definition."""
        sql = f"{self.name} "
        
        # Add Nullable wrapper if needed
        if self.nullable:
            sql += f"Nullable({self.data_type.value})"
        else:
            sql += self.data_type.value
        
        # Add default value if specified
        if self.default_value is not None:
            sql += f" DEFAULT {self.default_value}"
        
        # Add comment if specified
        if self.comment:
            sql += f" COMMENT '{self.comment}'"
        
        return sql


@dataclass
class SilverTableSchema:
    """
    Schema definition for silver layer tables.
    
    Silver layer stores cleaned and validated data with proper types and quality metadata.
    Includes lineage columns linking back to bronze layer and quality scoring columns.
    
    Attributes:
        source_name: Name of the data source (e.g., 'customers', 'orders')
        data_columns: List of SilverColumnDefinition for business data
        partition_by: Partitioning strategy (default: monthly by cleaned date)
        order_by: Ordering columns for MergeTree engine
        settings: Additional ClickHouse table settings
        indexes: List of secondary indexes for query performance
    """
    source_name: str
    data_columns: List[SilverColumnDefinition] = field(default_factory=list)
    partition_by: str = "toYYYYMM(_cleaned_at)"
    order_by: List[str] = field(default_factory=lambda: ["_batch_id", "_row_id"])
    settings: Dict[str, Any] = field(default_factory=lambda: {"index_granularity": 8192})
    indexes: List[Dict[str, Any]] = field(default_factory=lambda: [
        {"name": "idx_bronze_row_id", "column": "_bronze_row_id", "type": "bloom_filter", "granularity": 1},
        {"name": "idx_quality_score", "column": "_quality_score", "type": "minmax", "granularity": 1},
        {"name": "idx_cleaned_at", "column": "_cleaned_at", "type": "minmax", "granularity": 1}
    ])
    
    @property
    def table_name(self) -> str:
        """Generate silver table name."""
        return f"silver_{self.source_name}"
    
    def get_create_table_sql(self) -> str:
        """
        Generate CREATE TABLE SQL statement for silver layer.
        
        Returns:
            SQL statement to create the silver table
        """
        # Lineage columns (always present)
        lineage_columns = [
            "_row_id UUID DEFAULT generateUUIDv4() COMMENT 'Unique identifier for this silver row'",
            "_bronze_row_id UUID COMMENT 'Reference to bronze layer row'",
            "_batch_id String COMMENT 'Batch identifier from extraction'",
            "_cleaned_at DateTime64(3) COMMENT 'Timestamp when cleaning was performed'",
            "_cleaning_version String COMMENT 'Version of cleaning rules applied'"
        ]
        
        # Data columns (with proper types)
        data_column_defs = [col.to_sql() for col in self.data_columns]
        
        # Quality metadata columns
        quality_columns = [
            "_quality_score Float32 COMMENT 'Overall quality score (0.0 to 1.0)'",
            "_applied_rules Array(String) COMMENT 'List of transformation rules applied'",
            "_warnings Array(String) COMMENT 'Non-fatal warnings during transformation'",
            "_completeness_score Float32 COMMENT 'Percentage of non-null required fields'",
            "_validity_score Float32 COMMENT 'Percentage of fields passing validation'"
        ]
        
        # Combine all columns
        all_columns = lineage_columns + data_column_defs + quality_columns
        columns_sql = ",\n    ".join(all_columns)
        
        # Build indexes
        indexes_sql = ""
        if self.indexes:
            index_defs = []
            for idx in self.indexes:
                idx_name = idx.get("name", f"idx_{idx['column']}")
                idx_column = idx["column"]
                idx_type = idx.get("type", "minmax")
                idx_granularity = idx.get("granularity", 1)
                
                # ClickHouse index syntax: INDEX name column TYPE type GRANULARITY granularity
                index_defs.append(
                    f"INDEX {idx_name} {idx_column} TYPE {idx_type} GRANULARITY {idx_granularity}"
                )
            
            if index_defs:
                indexes_sql = ",\n    " + ",\n    ".join(index_defs)
        
        # Build settings string
        settings_sql = ", ".join([f"{k} = {v}" for k, v in self.settings.items()])
        
        # Generate full CREATE TABLE statement
        sql = f"""
CREATE TABLE IF NOT EXISTS {self.table_name} (
    {columns_sql}{indexes_sql}
) ENGINE = MergeTree()
PARTITION BY {self.partition_by}
ORDER BY ({', '.join(self.order_by)})
SETTINGS {settings_sql}
"""
        return sql.strip()


@dataclass
class QualityMetrics:
    """
    Quality metrics for a silver row.
    
    Attributes:
        completeness_score: Percentage of non-null required fields (0.0 to 1.0)
        validity_score: Percentage of fields passing validation (0.0 to 1.0)
        quality_score: Overall quality score (weighted average)
        applied_rules: List of rule IDs that were applied
        warnings: List of non-fatal warnings
    """
    completeness_score: float = 1.0
    validity_score: float = 1.0
    quality_score: float = 1.0
    applied_rules: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def calculate_overall_score(self, completeness_weight: float = 0.4, validity_weight: float = 0.6) -> float:
        """
        Calculate overall quality score as weighted average.
        
        Args:
            completeness_weight: Weight for completeness score (default 0.4)
            validity_weight: Weight for validity score (default 0.6)
        
        Returns:
            Overall quality score (0.0 to 1.0)
        """
        if completeness_weight + validity_weight != 1.0:
            raise ValueError("Weights must sum to 1.0")
        
        self.quality_score = (
            self.completeness_score * completeness_weight +
            self.validity_score * validity_weight
        )
        return self.quality_score
    
    def validate(self) -> tuple[bool, List[str]]:
        """
        Validate quality metrics.
        
        Returns:
            Tuple of (is_valid, list of validation errors)
        """
        errors = []
        
        # Check score ranges
        if not 0.0 <= self.completeness_score <= 1.0:
            errors.append(f"completeness_score must be between 0.0 and 1.0, got {self.completeness_score}")
        
        if not 0.0 <= self.validity_score <= 1.0:
            errors.append(f"validity_score must be between 0.0 and 1.0, got {self.validity_score}")
        
        if not 0.0 <= self.quality_score <= 1.0:
            errors.append(f"quality_score must be between 0.0 and 1.0, got {self.quality_score}")
        
        return len(errors) == 0, errors


@dataclass
class SilverRow:
    """
    Represents a single row in the silver layer.
    
    Encapsulates lineage metadata, cleaned data, and quality metrics.
    
    Attributes:
        bronze_row_id: UUID of the source bronze row
        batch_id: Batch identifier from extraction
        cleaned_at: Timestamp when cleaning was performed
        cleaning_version: Version of cleaning rules applied
        data: Dictionary of cleaned data columns (with proper types)
        quality_metrics: Quality metrics for this row
        row_id: Unique identifier for this silver row (auto-generated)
    """
    bronze_row_id: UUID
    batch_id: str
    cleaned_at: datetime
    cleaning_version: str
    data: Dict[str, Any]
    quality_metrics: QualityMetrics
    row_id: UUID = field(default_factory=uuid4)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert silver row to dictionary for ClickHouse insertion.
        
        Returns:
            Dictionary with all columns (lineage + data + quality)
        """
        row_dict = {
            # Lineage columns
            "_row_id": str(self.row_id),
            "_bronze_row_id": str(self.bronze_row_id),
            "_batch_id": self.batch_id,
            "_cleaned_at": self.cleaned_at,
            "_cleaning_version": self.cleaning_version,
            
            # Quality metadata columns
            "_quality_score": self.quality_metrics.quality_score,
            "_applied_rules": self.quality_metrics.applied_rules,
            "_warnings": self.quality_metrics.warnings,
            "_completeness_score": self.quality_metrics.completeness_score,
            "_validity_score": self.quality_metrics.validity_score
        }
        
        # Add data columns
        row_dict.update(self.data)
        
        return row_dict
    
    def validate(self, schema: SilverTableSchema) -> tuple[bool, List[str]]:
        """
        Validate silver row against schema.
        
        Args:
            schema: SilverTableSchema to validate against
        
        Returns:
            Tuple of (is_valid, list of validation errors)
        """
        errors = []
        
        # Check required fields
        if not self.bronze_row_id:
            errors.append("bronze_row_id is required")
        if not self.batch_id:
            errors.append("batch_id is required")
        if not self.cleaned_at:
            errors.append("cleaned_at is required")
        if not self.cleaning_version:
            errors.append("cleaning_version is required")
        if not self.data:
            errors.append("data cannot be empty")
        
        # Validate quality metrics
        is_valid_metrics, metrics_errors = self.quality_metrics.validate()
        if not is_valid_metrics:
            errors.extend(metrics_errors)
        
        # Validate data columns against schema
        schema_columns = {col.name: col for col in schema.data_columns}
        
        for col_name, col_value in self.data.items():
            if col_name not in schema_columns:
                errors.append(f"Column {col_name} not in schema")
                continue
            
            col_def = schema_columns[col_name]
            
            # Check nullable constraint
            if col_value is None and not col_def.nullable:
                errors.append(f"Column {col_name} cannot be NULL")
        
        # Check for missing required columns
        for col_name, col_def in schema_columns.items():
            if col_name not in self.data and not col_def.nullable and col_def.default_value is None:
                errors.append(f"Required column {col_name} is missing")
        
        return len(errors) == 0, errors


@dataclass
class SilverBatch:
    """
    Represents a batch of rows for silver layer insertion.
    
    Provides batch-level operations and validation.
    
    Attributes:
        batch_id: Unique identifier for this batch
        source_id: Identifier for the data source
        rows: List of SilverRow objects
        schema: SilverTableSchema for the target table
    """
    batch_id: str
    source_id: str
    rows: List[SilverRow]
    schema: SilverTableSchema
    
    def validate(self) -> tuple[bool, List[str]]:
        """
        Validate entire batch.
        
        Returns:
            Tuple of (is_valid, list of validation errors)
        """
        errors = []
        
        if not self.rows:
            errors.append("Batch cannot be empty")
            return False, errors
        
        # Validate each row
        for idx, row in enumerate(self.rows):
            is_valid, row_errors = row.validate(self.schema)
            if not is_valid:
                errors.extend([f"Row {idx}: {err}" for err in row_errors])
        
        # Check batch consistency
        batch_ids = set(row.batch_id for row in self.rows)
        if len(batch_ids) > 1:
            errors.append(f"Inconsistent batch_ids in batch: {batch_ids}")
        
        return len(errors) == 0, errors
    
    def to_dicts(self) -> List[Dict[str, Any]]:
        """
        Convert all rows to dictionaries for ClickHouse insertion.
        
        Returns:
            List of dictionaries
        """
        return [row.to_dict() for row in self.rows]
    
    def get_quality_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics for batch quality.
        
        Returns:
            Dictionary with quality statistics
        """
        if not self.rows:
            return {
                "total_rows": 0,
                "avg_quality_score": 0.0,
                "avg_completeness_score": 0.0,
                "avg_validity_score": 0.0,
                "rows_with_warnings": 0
            }
        
        total_quality = sum(row.quality_metrics.quality_score for row in self.rows)
        total_completeness = sum(row.quality_metrics.completeness_score for row in self.rows)
        total_validity = sum(row.quality_metrics.validity_score for row in self.rows)
        rows_with_warnings = sum(1 for row in self.rows if row.quality_metrics.warnings)
        
        return {
            "total_rows": len(self.rows),
            "avg_quality_score": total_quality / len(self.rows),
            "avg_completeness_score": total_completeness / len(self.rows),
            "avg_validity_score": total_validity / len(self.rows),
            "rows_with_warnings": rows_with_warnings,
            "warning_rate": rows_with_warnings / len(self.rows)
        }
