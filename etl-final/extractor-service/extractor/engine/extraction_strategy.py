"""
Extraction Strategy Interface

This module defines the abstract base class for extraction strategies in the ETL pipeline.
The strategy pattern allows different extraction implementations (CSV, Database, etc.)
while maintaining a consistent interface.

Design Principles:
- Stateless: No instance variables that change between calls
- Idempotent: Same input produces same output
- Batched: Extracts data in chunks to prevent memory issues
- Type-safe: Uses proper type hints

Requirements:
- FR-6: Idempotent Operations - All operations have idempotency keys
- US-1: Idempotent ETL operations (AC 1.4: Pipeline state is externalized)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from datetime import datetime
import uuid


@dataclass
class Batch:
    """
    Represents a batch of extracted data.
    
    Attributes:
        rows: List of dictionaries representing the extracted rows
        batch_id: Unique identifier for this batch
        source_id: Identifier for the data source
        offset: Starting position of this batch in the source
        total_rows: Total number of rows in this batch
        has_more: Whether there are more rows to extract
        metadata: Additional metadata about the extraction
    """
    rows: List[Dict[str, Any]]
    batch_id: str
    source_id: str
    offset: int
    total_rows: int
    has_more: bool
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ExtractionConfig:
    """
    Configuration for extraction operations.
    
    Attributes:
        source_id: Unique identifier for the data source
        source_type: Type of source (csv, database, etc.)
        connection_params: Connection parameters specific to the source type
        batch_size: Number of rows to extract per batch (default: 1000)
        schema_contract: Optional schema contract for validation
        extraction_metadata: Additional metadata for the extraction
        extraction_id: Optional unique identifier for this extraction operation
        correlation_id: Optional correlation ID for distributed tracing
        progress_tracker: Optional progress tracker instance
    """
    source_id: str
    source_type: str
    connection_params: Dict[str, Any]
    batch_size: int = 1000
    schema_contract: Optional[Dict[str, Any]] = None
    extraction_metadata: Optional[Dict[str, Any]] = None
    extraction_id: Optional[str] = None
    correlation_id: Optional[str] = None
    progress_tracker: Optional[Any] = None  # ProgressTracker instance
    
    def __post_init__(self):
        """Generate extraction_id and correlation_id if not provided."""
        if not self.extraction_id:
            self.extraction_id = f"ext_{uuid.uuid4().hex[:12]}"
        if not self.correlation_id:
            self.correlation_id = f"corr_{uuid.uuid4().hex[:12]}"


class ExtractionStrategy(ABC):
    """
    Abstract base class for extraction strategies.
    
    This interface defines the contract that all extraction strategies must implement.
    Extraction strategies are responsible for extracting data from various sources
    (CSV files, databases, APIs, etc.) in a batched, idempotent manner.
    
    Key Design Principles:
    1. Stateless: No mutable instance state between method calls
    2. Batched: Extracts data in configurable chunks to prevent memory overflow
    3. Idempotent: Same config and offset always produce the same batch
    4. Resumable: Supports offset-based extraction for checkpointing
    5. Direct Bronze Write: Can write directly to bronze tables (bypass Kafka)
    
    Implementation Requirements:
    - Must not load entire dataset into memory
    - Must support pagination/chunking via offset and limit
    - Must generate consistent batch_ids for idempotency
    - Must handle errors gracefully and provide meaningful error messages
    
    Example Usage:
        config = ExtractionConfig(
            source_id="customers_db",
            source_type="database",
            connection_params={"host": "localhost", "table": "customers"},
            batch_size=1000
        )
        
        strategy = DatabaseExtractionStrategy()
        offset = 0
        
        while True:
            batch = strategy.extract_batch(config, offset, config.batch_size)
            # Process batch...
            
            if not batch.has_more:
                break
            offset += batch.total_rows
    """
    
    @abstractmethod
    def extract_batch(
        self,
        config: ExtractionConfig,
        offset: int,
        limit: int
    ) -> Batch:
        """
        Extract a batch of data from the source.
        
        This method must be implemented by all concrete extraction strategies.
        It should extract data starting from the given offset and return up to
        'limit' rows.
        
        Args:
            config: Configuration object containing source details and connection params
            offset: Starting position for extraction (0-indexed)
            limit: Maximum number of rows to extract in this batch
            
        Returns:
            Batch object containing:
                - rows: List of extracted rows as dictionaries
                - batch_id: Unique identifier for this batch (for idempotency)
                - source_id: Identifier from config
                - offset: The offset used for this extraction
                - total_rows: Actual number of rows extracted (may be less than limit)
                - has_more: True if there are more rows to extract after this batch
                - metadata: Optional metadata about the extraction
                
        Raises:
            ExtractionError: If extraction fails due to connection issues, invalid config, etc.
            ValidationError: If extracted data fails schema validation
            
        Implementation Notes:
            - Must be idempotent: calling with same config/offset/limit returns same data
            - Must not modify any instance state
            - Must handle pagination/chunking efficiently
            - Should validate data against schema_contract if provided
            - Should generate deterministic batch_ids (e.g., hash of source_id + offset)
            - Must close/cleanup resources properly (use context managers)
            
        Performance Considerations:
            - Should stream data rather than loading all into memory
            - Should use database cursors or file readers that support seeking
            - Should minimize network round-trips
            - Should handle large rows gracefully
        """
        pass
    
    def validate_config(self, config: ExtractionConfig) -> None:
        """
        Validate the extraction configuration.
        
        This method can be overridden by concrete strategies to perform
        strategy-specific validation. The base implementation validates
        common fields.
        
        Args:
            config: Configuration to validate
            
        Raises:
            ValueError: If configuration is invalid
        """
        if not config.source_id:
            raise ValueError("source_id is required")
        
        if not config.source_type:
            raise ValueError("source_type is required")
        
        if config.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        
        if not config.connection_params:
            raise ValueError("connection_params is required")
    
    def generate_batch_id(self, source_id: str, offset: int) -> str:
        """
        Generate a deterministic batch ID for idempotency.
        
        The batch ID is used to ensure idempotent extraction operations.
        The same source_id and offset should always produce the same batch_id.
        
        Args:
            source_id: Unique identifier for the data source
            offset: Starting position of the batch
            
        Returns:
            Deterministic batch identifier
        """
        import hashlib
        
        # Create deterministic batch ID from source_id and offset
        content = f"{source_id}:{offset}"
        hash_value = hashlib.sha256(content.encode()).hexdigest()
        
        return f"batch_{source_id}_{offset}_{hash_value[:8]}"
    
    def enrich_rows_with_lineage(
        self,
        rows: List[Dict[str, Any]],
        batch_id: str,
        source_id: str,
        extracted_at: datetime
    ) -> List[Dict[str, Any]]:
        """
        Enrich extracted rows with lineage metadata.
        
        Adds _batch_id, _source_id, and _extracted_at to each row for bronze layer tracking.
        This ensures every row can be traced back to its extraction batch and source.
        
        Requirements:
        - US-2: Immutable raw data storage (AC 2.2: Raw layer with timestamp and source tracking)
        - US-5: Comprehensive data lineage (AC 5.1: Every row tracks source and extraction timestamp)
        - FR-1: Immutable Raw Layer - Raw tables include _extracted_at, _source_id, _batch_id
        
        Args:
            rows: List of extracted rows (dictionaries)
            batch_id: Unique identifier for the extraction batch
            source_id: Identifier for the data source
            extracted_at: Timestamp when data was extracted
            
        Returns:
            List of rows with lineage metadata added
            
        Note:
            This method does NOT modify the original rows, it creates new dictionaries
            with the lineage fields added. This preserves the original data structure.
        """
        enriched_rows = []
        
        for row in rows:
            # Create a new dictionary with lineage fields
            enriched_row = {
                "_batch_id": batch_id,
                "_source_id": source_id,
                "_extracted_at": extracted_at.isoformat() if isinstance(extracted_at, datetime) else extracted_at,
                **row  # Spread original row data
            }
            enriched_rows.append(enriched_row)
        
        return enriched_rows
    
    def batch_to_bronze_batch(self, batch: Batch, source_name: str):
        """
        Convert an extraction Batch to a BronzeBatch for direct bronze table writes.
        
        This method bridges the extraction layer and bronze layer by converting
        the generic Batch object into a BronzeBatch with proper schema and BronzeRow objects.
        
        Requirements:
        - Task 2.2.5: Implement direct write to bronze tables (bypass Kafka for raw data)
        - FR-1: Immutable Raw Layer - All extracted data stored in immutable raw tables
        
        Args:
            batch: Batch object from extract_batch method
            source_name: Name of the data source for bronze table naming
            
        Returns:
            BronzeBatch object ready for writing to bronze tables
            
        Note:
            This method requires the bronze_schema module. Import it when needed:
            from models.bronze_schema import BronzeRow, BronzeBatch, BronzeTableSchema
        """
        # Import here to avoid circular dependencies
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'shared'))
        from models.bronze_schema import BronzeRow, BronzeBatch, BronzeTableSchema
        
        # Extract metadata from batch
        batch_id = batch.batch_id
        source_id = batch.source_id
        extracted_at = batch.metadata.get('extraction_timestamp')
        if isinstance(extracted_at, str):
            from datetime import datetime
            extracted_at = datetime.fromisoformat(extracted_at.replace('Z', '+00:00'))
        
        # Create BronzeRow objects from batch rows
        bronze_rows = []
        for idx, row_data in enumerate(batch.rows):
            # Remove lineage fields that were added by enrich_rows_with_lineage
            # We'll let BronzeRow handle these
            clean_data = {
                k: str(v) if v is not None else ""  # Convert all to strings for bronze layer
                for k, v in row_data.items()
                if not k.startswith('_')  # Remove lineage fields
            }
            
            bronze_row = BronzeRow(
                batch_id=batch_id,
                source_id=source_id,
                extracted_at=extracted_at,
                data=clean_data,
                file_name=batch.metadata.get('file_name', ''),
                file_size=batch.metadata.get('file_size', 0),
                row_number=batch.offset + idx
            )
            bronze_rows.append(bronze_row)
        
        # Create schema from first row
        if bronze_rows:
            data_columns = {
                col: "String"
                for bronze_row in bronze_rows
                for col in bronze_row.data.keys()
            }
        else:
            data_columns = {}
        
        schema = BronzeTableSchema(
            source_name=source_name,
            data_columns=data_columns
        )
        
        # Create and return BronzeBatch
        return BronzeBatch(
            batch_id=batch_id,
            source_id=source_id,
            rows=bronze_rows,
            schema=schema
        )
    
    def _update_progress(
        self,
        config: ExtractionConfig,
        rows_extracted: int,
        batches_processed: int,
        current_offset: int,
        estimated_total_rows: Optional[int] = None
    ) -> None:
        """
        Update extraction progress if progress tracker is available.
        
        This is a helper method that extraction strategies can call to update
        progress during extraction operations.
        
        Args:
            config: ExtractionConfig containing progress tracker
            rows_extracted: Total rows extracted so far
            batches_processed: Total batches processed so far
            current_offset: Current offset position
            estimated_total_rows: Optional estimated total rows
        """
        if config.progress_tracker and config.extraction_id:
            config.progress_tracker.update_progress(
                extraction_id=config.extraction_id,
                rows_extracted=rows_extracted,
                batches_processed=batches_processed,
                current_offset=current_offset,
                estimated_total_rows=estimated_total_rows
            )


class ExtractionError(Exception):
    """Raised when extraction fails due to connection or data issues."""
    pass


class ValidationError(Exception):
    """Raised when extracted data fails schema validation."""
    pass
