"""
Bronze Layer Schema Definition
Implements immutable raw data storage with comprehensive lineage tracking.

Based on design.md section 5.1 and requirements FR-1, US-2.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
from uuid import UUID, uuid4
import hashlib
import json


@dataclass
class BronzeTableSchema:
    """
    Schema definition for bronze layer tables.
    
    Bronze layer stores immutable raw data with lineage columns for full traceability.
    All data columns are initially stored as String type to preserve original format.
    
    Attributes:
        source_name: Name of the data source (e.g., 'customers', 'orders')
        data_columns: Dictionary mapping column names to their types (all String initially)
        partition_by: Partitioning strategy (default: monthly by extraction date)
        order_by: Ordering columns for MergeTree engine
        settings: Additional ClickHouse table settings
        indexes: List of secondary indexes for query performance
    """
    source_name: str
    data_columns: Dict[str, str] = field(default_factory=dict)
    partition_by: str = "toYYYYMM(_extracted_at)"
    order_by: List[str] = field(default_factory=lambda: ["_batch_id", "_row_id"])
    settings: Dict[str, Any] = field(default_factory=lambda: {"index_granularity": 8192})
    indexes: List[Dict[str, Any]] = field(default_factory=lambda: [
        {"name": "idx_dedup_key", "column": "_dedup_key", "type": "bloom_filter", "granularity": 1},
        {"name": "idx_source_id", "column": "_source_id", "type": "set", "granularity": 4},
        {"name": "idx_extracted_at", "column": "_extracted_at", "type": "minmax", "granularity": 1}
    ])
    
    @property
    def table_name(self) -> str:
        """Generate bronze table name."""
        return f"bronze_{self.source_name}"
    
    def get_create_table_sql(self) -> str:
        """
        Generate CREATE TABLE SQL statement for bronze layer.
        
        Returns:
            SQL statement to create the bronze table
        """
        # Lineage columns (always present)
        lineage_columns = [
            "_row_id UUID DEFAULT generateUUIDv4()",
            "_batch_id String",
            "_source_id String",
            "_extracted_at DateTime64(3)",
            "_dedup_key String"
        ]
        
        # Data columns (all as String initially to preserve original format)
        data_column_defs = [f"{col_name} String" for col_name in self.data_columns.keys()]
        
        # Metadata columns
        metadata_columns = [
            "_file_name String",
            "_file_size UInt64",
            "_row_number UInt64"
        ]
        
        # Combine all columns
        all_columns = lineage_columns + data_column_defs + metadata_columns
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
class BronzeRow:
    """
    Represents a single row in the bronze layer.
    
    Encapsulates both lineage metadata and raw data content.
    Provides methods for deduplication key generation and validation.
    
    Attributes:
        batch_id: Unique identifier for the extraction batch
        source_id: Identifier for the data source
        extracted_at: Timestamp when data was extracted
        data: Dictionary of raw data columns (all values as strings)
        file_name: Name of source file (if applicable)
        file_size: Size of source file in bytes (if applicable)
        row_number: Row number in source file/table
        row_id: Unique identifier for this row (auto-generated)
        dedup_key: SHA256 hash for deduplication (auto-generated)
    """
    batch_id: str
    source_id: str
    extracted_at: datetime
    data: Dict[str, str]
    file_name: str = ""
    file_size: int = 0
    row_number: int = 0
    row_id: UUID = field(default_factory=uuid4)
    dedup_key: str = field(default="")
    
    def __post_init__(self):
        """Generate deduplication key if not provided."""
        if not self.dedup_key:
            self.dedup_key = self.generate_dedup_key()
    
    def generate_dedup_key(self) -> str:
        """
        Generate SHA256 hash for deduplication.
        
        The deduplication key is based on:
        - source_id: Identifies the data source
        - batch_id: Identifies the extraction batch
        - data content: Ensures identical data is detected
        
        Returns:
            SHA256 hash string
        """
        # Create deterministic representation of the row
        key_components = {
            "source_id": self.source_id,
            "batch_id": self.batch_id,
            "data": self.data
        }
        
        # Sort keys for deterministic JSON serialization
        key_json = json.dumps(key_components, sort_keys=True)
        
        # Generate SHA256 hash
        return hashlib.sha256(key_json.encode('utf-8')).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert bronze row to dictionary for ClickHouse insertion.
        
        Returns:
            Dictionary with all columns (lineage + data + metadata)
        """
        row_dict = {
            # Lineage columns
            "_row_id": str(self.row_id),
            "_batch_id": self.batch_id,
            "_source_id": self.source_id,
            "_extracted_at": self.extracted_at,
            "_dedup_key": self.dedup_key,
            
            # Metadata columns
            "_file_name": self.file_name,
            "_file_size": self.file_size,
            "_row_number": self.row_number
        }
        
        # Add data columns
        row_dict.update(self.data)
        
        return row_dict
    
    def validate(self) -> tuple[bool, List[str]]:
        """
        Validate bronze row data.
        
        Checks:
        - Required fields are present
        - Data types are correct
        - Deduplication key is valid
        
        Returns:
            Tuple of (is_valid, list of validation errors)
        """
        errors = []
        
        # Check required fields
        if not self.batch_id:
            errors.append("batch_id is required")
        if not self.source_id:
            errors.append("source_id is required")
        if not self.extracted_at:
            errors.append("extracted_at is required")
        if not self.data:
            errors.append("data cannot be empty")
        
        # Validate deduplication key
        expected_dedup_key = self.generate_dedup_key()
        if self.dedup_key != expected_dedup_key:
            errors.append(f"dedup_key mismatch: expected {expected_dedup_key}, got {self.dedup_key}")
        
        # Validate data columns are strings
        for col_name, col_value in self.data.items():
            if not isinstance(col_value, str):
                errors.append(f"Column {col_name} must be string, got {type(col_value).__name__}")
        
        return len(errors) == 0, errors


@dataclass
class BronzeBatch:
    """
    Represents a batch of rows for bronze layer insertion.
    
    Provides batch-level operations and validation.
    
    Attributes:
        batch_id: Unique identifier for this batch
        source_id: Identifier for the data source
        rows: List of BronzeRow objects
        schema: BronzeTableSchema for the target table
    """
    batch_id: str
    source_id: str
    rows: List[BronzeRow]
    schema: BronzeTableSchema
    
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
            is_valid, row_errors = row.validate()
            if not is_valid:
                errors.extend([f"Row {idx}: {err}" for err in row_errors])
        
        # Check batch consistency
        batch_ids = set(row.batch_id for row in self.rows)
        if len(batch_ids) > 1:
            errors.append(f"Inconsistent batch_ids in batch: {batch_ids}")
        
        source_ids = set(row.source_id for row in self.rows)
        if len(source_ids) > 1:
            errors.append(f"Inconsistent source_ids in batch: {source_ids}")
        
        return len(errors) == 0, errors
    
    def to_dicts(self) -> List[Dict[str, Any]]:
        """
        Convert all rows to dictionaries for ClickHouse insertion.
        
        Returns:
            List of dictionaries
        """
        return [row.to_dict() for row in self.rows]
    
    def get_dedup_keys(self) -> List[str]:
        """
        Get all deduplication keys in the batch.
        
        Returns:
            List of dedup_key strings
        """
        return [row.dedup_key for row in self.rows]
