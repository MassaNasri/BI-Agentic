"""
Extraction Checkpointing

This module provides checkpointing functionality for extraction operations to enable
resume capability after failures. Checkpoints are persisted to ClickHouse to survive
service restarts and allow failed extractions to resume from the last successful point.

Design Principles:
- Persistent: Checkpoints stored in ClickHouse
- Resumable: Failed extractions can resume from last checkpoint
- Idempotent: Safe to retry extraction operations
- Observable: Checkpoint status queryable via API

Requirements:
- US-1: Idempotent ETL operations (AC 1.3: Failed operations can be safely retried without data corruption)
- NFR-3: Reliability - Automatic retry with exponential backoff
- Section 3.2: Extractor Service (Redesigned) - Add extraction checkpointing
- Section 5.2: Loader Service Enhancement - Implement retry logic with exponential backoff
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from enum import Enum
import logging


class CheckpointStatus(Enum):
    """Status of a checkpoint."""
    ACTIVE = "active"  # Extraction is ongoing
    COMPLETED = "completed"  # Extraction completed successfully
    FAILED = "failed"  # Extraction failed
    RESUMED = "resumed"  # Extraction was resumed from checkpoint


@dataclass
class ExtractionCheckpoint:
    """
    Represents a checkpoint in an extraction operation.
    
    Checkpoints are saved after each batch is successfully extracted and written
    to the bronze layer. This allows failed extractions to resume from the last
    successful batch instead of starting over.
    
    Attributes:
        extraction_id: Unique identifier for the extraction operation
        source_id: Identifier for the data source
        source_type: Type of source (csv, database, etc.)
        last_offset: Last successfully processed offset
        last_batch_id: ID of the last successfully processed batch
        rows_extracted: Total rows extracted so far
        batches_processed: Total batches processed so far
        status: Current status of the checkpoint
        created_at: Timestamp when checkpoint was created
        updated_at: Timestamp of last checkpoint update
        completed_at: Timestamp when extraction completed (if completed)
        error_message: Error message if extraction failed
        correlation_id: Correlation ID for distributed tracing
        metadata: Additional metadata about the extraction
    """
    extraction_id: str
    source_id: str
    source_type: str
    last_offset: int
    last_batch_id: str
    rows_extracted: int = 0
    batches_processed: int = 0
    status: CheckpointStatus = CheckpointStatus.ACTIVE
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    correlation_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        # Convert enum to string
        data['status'] = self.status.value
        # Convert datetime objects to ISO format strings
        for field in ['created_at', 'updated_at', 'completed_at']:
            if data[field] is not None:
                data[field] = data[field].isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ExtractionCheckpoint':
        """Create checkpoint from dictionary."""
        # Convert status string to enum
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = CheckpointStatus(data['status'])
        
        # Convert datetime strings to datetime objects
        for field in ['created_at', 'updated_at', 'completed_at']:
            if field in data and data[field] is not None and isinstance(data[field], str):
                data[field] = datetime.fromisoformat(data[field].replace('Z', '+00:00'))
        
        return cls(**data)


class CheckpointManager:
    """
    Manages extraction checkpoints with persistence to ClickHouse.
    
    This class provides methods to create, update, and query checkpoints for
    extraction operations. Checkpoints are persisted to ClickHouse to survive
    service restarts and enable resume capability.
    
    Key Features:
    - Persistent checkpointing to ClickHouse
    - Resume capability for failed extractions
    - Automatic cleanup of old checkpoints
    - Integration with progress tracking
    - Idempotent checkpoint operations
    
    ClickHouse Schema:
        CREATE TABLE extraction_checkpoints (
            extraction_id String,
            source_id String,
            source_type String,
            last_offset UInt64,
            last_batch_id String,
            rows_extracted UInt64,
            batches_processed UInt32,
            status String,
            created_at DateTime64(3),
            updated_at DateTime64(3),
            completed_at Nullable(DateTime64(3)),
            error_message Nullable(String),
            correlation_id Nullable(String),
            metadata String  -- JSON serialized
        ) ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (extraction_id, updated_at);
    
    Example Usage:
        # Initialize manager
        manager = CheckpointManager(clickhouse_client=client)
        
        # Create initial checkpoint
        checkpoint = manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            correlation_id="corr_456"
        )
        
        # Update checkpoint after each batch
        manager.update_checkpoint(
            extraction_id="ext_123",
            last_offset=1000,
            last_batch_id="batch_123",
            rows_extracted=1000,
            batches_processed=1
        )
        
        # Resume from checkpoint
        checkpoint = manager.get_checkpoint("ext_123")
        if checkpoint:
            # Resume extraction from checkpoint.last_offset
            pass
        
        # Complete extraction
        manager.complete_checkpoint(extraction_id="ext_123")
        
        # Cleanup old checkpoints
        manager.cleanup_old_checkpoints(days=7)
    """
    
    def __init__(self, clickhouse_client=None, logger=None):
        """
        Initialize checkpoint manager.
        
        Args:
            clickhouse_client: Optional ClickHouse client for persistence
            logger: Optional logger instance (creates one if not provided)
        """
        self._clickhouse_client = clickhouse_client
        self._logger = logger or self._create_logger()
        self._in_memory_checkpoints: Dict[str, ExtractionCheckpoint] = {}
        
        # Initialize ClickHouse table if client is provided
        if self._clickhouse_client:
            self._initialize_checkpoint_table()
    
    def _create_logger(self) -> logging.Logger:
        """Create a structured logger for checkpoint management."""
        logger = logging.getLogger('extraction_checkpoint')
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
                '"logger": "%(name)s", "message": "%(message)s"}'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger
    
    def _initialize_checkpoint_table(self) -> None:
        """
        Initialize the extraction_checkpoints table in ClickHouse.
        
        Creates the table if it doesn't exist. Uses ReplacingMergeTree to handle
        updates efficiently (latest version by updated_at is kept).
        """
        try:
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS extraction_checkpoints (
                extraction_id String,
                source_id String,
                source_type String,
                last_offset UInt64,
                last_batch_id String,
                rows_extracted UInt64,
                batches_processed UInt32,
                status String,
                created_at DateTime64(3),
                updated_at DateTime64(3),
                completed_at Nullable(DateTime64(3)),
                error_message Nullable(String),
                correlation_id Nullable(String),
                metadata String
            ) ENGINE = ReplacingMergeTree(updated_at)
            PARTITION BY toYYYYMM(created_at)
            ORDER BY (extraction_id, updated_at)
            """
            
            self._clickhouse_client.execute(create_table_sql)
            self._logger.info("Initialized extraction_checkpoints table")
        except Exception as e:
            self._logger.error(f"Failed to initialize checkpoint table: {str(e)}")
            # Don't raise - fall back to in-memory only
    
    def create_checkpoint(
        self,
        extraction_id: str,
        source_id: str,
        source_type: str,
        correlation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ExtractionCheckpoint:
        """
        Create a new checkpoint for an extraction operation.
        
        Args:
            extraction_id: Unique identifier for the extraction
            source_id: Identifier for the data source
            source_type: Type of source (csv, database, etc.)
            correlation_id: Optional correlation ID for distributed tracing
            metadata: Optional additional metadata
            
        Returns:
            ExtractionCheckpoint object
        """
        now = datetime.now(timezone.utc)
        
        checkpoint = ExtractionCheckpoint(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type=source_type,
            last_offset=0,
            last_batch_id="",
            rows_extracted=0,
            batches_processed=0,
            status=CheckpointStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            correlation_id=correlation_id,
            metadata=metadata or {}
        )
        
        # Store in memory
        self._in_memory_checkpoints[extraction_id] = checkpoint
        
        # Persist to ClickHouse
        if self._clickhouse_client:
            self._persist_checkpoint(checkpoint)
        
        self._logger.info(
            f"Created checkpoint for extraction {extraction_id} (source: {source_id})",
            extra={'correlation_id': correlation_id or 'none'}
        )
        
        return checkpoint
    
    def update_checkpoint(
        self,
        extraction_id: str,
        last_offset: int,
        last_batch_id: str,
        rows_extracted: Optional[int] = None,
        batches_processed: Optional[int] = None
    ) -> Optional[ExtractionCheckpoint]:
        """
        Update checkpoint after successfully processing a batch.
        
        This method should be called after each batch is successfully extracted
        and written to the bronze layer. It updates the checkpoint with the new
        offset and batch information.
        
        Args:
            extraction_id: Unique identifier for the extraction
            last_offset: Offset of the last successfully processed batch
            last_batch_id: ID of the last successfully processed batch
            rows_extracted: Total rows extracted (cumulative)
            batches_processed: Total batches processed (cumulative)
            
        Returns:
            Updated ExtractionCheckpoint object or None if not found
        """
        checkpoint = self._in_memory_checkpoints.get(extraction_id)
        
        # If not in memory, try to load from ClickHouse
        if not checkpoint and self._clickhouse_client:
            checkpoint = self._load_checkpoint(extraction_id)
            if checkpoint:
                self._in_memory_checkpoints[extraction_id] = checkpoint
        
        if not checkpoint:
            self._logger.warning(
                f"Checkpoint update for unknown extraction_id: {extraction_id}"
            )
            return None
        
        # Update fields
        checkpoint.last_offset = last_offset
        checkpoint.last_batch_id = last_batch_id
        
        if rows_extracted is not None:
            checkpoint.rows_extracted = rows_extracted
        if batches_processed is not None:
            checkpoint.batches_processed = batches_processed
        
        checkpoint.updated_at = datetime.now(timezone.utc)
        
        # Persist to ClickHouse
        if self._clickhouse_client:
            self._persist_checkpoint(checkpoint)
        
        self._logger.info(
            f"Updated checkpoint for extraction {extraction_id}: "
            f"offset={last_offset}, batch={last_batch_id}, rows={checkpoint.rows_extracted}",
            extra={'correlation_id': checkpoint.correlation_id or 'none'}
        )
        
        return checkpoint
    
    def complete_checkpoint(
        self,
        extraction_id: str,
        final_row_count: Optional[int] = None
    ) -> Optional[ExtractionCheckpoint]:
        """
        Mark a checkpoint as completed.
        
        Args:
            extraction_id: Unique identifier for the extraction
            final_row_count: Optional final row count (if different from tracked)
            
        Returns:
            Completed ExtractionCheckpoint object or None if not found
        """
        checkpoint = self._in_memory_checkpoints.get(extraction_id)
        
        # If not in memory, try to load from ClickHouse
        if not checkpoint and self._clickhouse_client:
            checkpoint = self._load_checkpoint(extraction_id)
            if checkpoint:
                self._in_memory_checkpoints[extraction_id] = checkpoint
        
        if not checkpoint:
            return None
        
        now = datetime.now(timezone.utc)
        checkpoint.status = CheckpointStatus.COMPLETED
        checkpoint.completed_at = now
        checkpoint.updated_at = now
        
        if final_row_count is not None:
            checkpoint.rows_extracted = final_row_count
        
        # Persist to ClickHouse
        if self._clickhouse_client:
            self._persist_checkpoint(checkpoint)
        
        self._logger.info(
            f"Completed checkpoint for extraction {extraction_id}: "
            f"{checkpoint.rows_extracted} rows extracted",
            extra={'correlation_id': checkpoint.correlation_id or 'none'}
        )
        
        return checkpoint
    
    def fail_checkpoint(
        self,
        extraction_id: str,
        error_message: str
    ) -> Optional[ExtractionCheckpoint]:
        """
        Mark a checkpoint as failed.
        
        Args:
            extraction_id: Unique identifier for the extraction
            error_message: Error message describing the failure
            
        Returns:
            Failed ExtractionCheckpoint object or None if not found
        """
        checkpoint = self._in_memory_checkpoints.get(extraction_id)
        
        # If not in memory, try to load from ClickHouse
        if not checkpoint and self._clickhouse_client:
            checkpoint = self._load_checkpoint(extraction_id)
            if checkpoint:
                self._in_memory_checkpoints[extraction_id] = checkpoint
        
        if not checkpoint:
            return None
        
        now = datetime.now(timezone.utc)
        checkpoint.status = CheckpointStatus.FAILED
        checkpoint.error_message = error_message
        checkpoint.completed_at = now
        checkpoint.updated_at = now
        
        # Persist to ClickHouse
        if self._clickhouse_client:
            self._persist_checkpoint(checkpoint)
        
        self._logger.error(
            f"Failed checkpoint for extraction {extraction_id}: {error_message}",
            extra={'correlation_id': checkpoint.correlation_id or 'none'}
        )
        
        return checkpoint
    
    def get_checkpoint(self, extraction_id: str) -> Optional[ExtractionCheckpoint]:
        """
        Get checkpoint for an extraction.
        
        First checks in-memory cache, then falls back to ClickHouse if available.
        
        Args:
            extraction_id: Unique identifier for the extraction
            
        Returns:
            ExtractionCheckpoint object or None if not found
        """
        # Check in-memory first
        checkpoint = self._in_memory_checkpoints.get(extraction_id)
        if checkpoint:
            return checkpoint
        
        # Fall back to ClickHouse
        if self._clickhouse_client:
            checkpoint = self._load_checkpoint(extraction_id)
            if checkpoint:
                self._in_memory_checkpoints[extraction_id] = checkpoint
            return checkpoint
        
        return None
    
    def can_resume(self, extraction_id: str) -> bool:
        """
        Check if an extraction can be resumed from checkpoint.
        
        An extraction can be resumed if:
        - A checkpoint exists
        - Status is ACTIVE or FAILED
        - Some progress has been made (last_offset > 0)
        
        Args:
            extraction_id: Unique identifier for the extraction
            
        Returns:
            True if extraction can be resumed, False otherwise
        """
        checkpoint = self.get_checkpoint(extraction_id)
        if not checkpoint:
            return False
        
        # Can resume if status is ACTIVE or FAILED and some progress was made
        can_resume = (
            checkpoint.status in [CheckpointStatus.ACTIVE, CheckpointStatus.FAILED]
            and checkpoint.last_offset > 0
        )
        
        return can_resume
    
    def resume_from_checkpoint(self, extraction_id: str) -> Optional[ExtractionCheckpoint]:
        """
        Resume an extraction from its checkpoint.
        
        Updates the checkpoint status to RESUMED and returns the checkpoint
        so the extraction can continue from last_offset.
        
        Args:
            extraction_id: Unique identifier for the extraction
            
        Returns:
            ExtractionCheckpoint object or None if cannot resume
        """
        if not self.can_resume(extraction_id):
            self._logger.warning(
                f"Cannot resume extraction {extraction_id}: no valid checkpoint found"
            )
            return None
        
        checkpoint = self.get_checkpoint(extraction_id)
        if not checkpoint:
            return None
        
        # Update status to RESUMED
        checkpoint.status = CheckpointStatus.RESUMED
        checkpoint.updated_at = datetime.now(timezone.utc)
        
        # Persist to ClickHouse
        if self._clickhouse_client:
            self._persist_checkpoint(checkpoint)
        
        self._logger.info(
            f"Resuming extraction {extraction_id} from offset {checkpoint.last_offset}",
            extra={'correlation_id': checkpoint.correlation_id or 'none'}
        )
        
        return checkpoint
    
    def list_active_checkpoints(self) -> List[ExtractionCheckpoint]:
        """
        List all active checkpoints.
        
        Returns:
            List of ExtractionCheckpoint objects with ACTIVE or RESUMED status
        """
        # Get from in-memory cache
        active = [
            cp for cp in self._in_memory_checkpoints.values()
            if cp.status in [CheckpointStatus.ACTIVE, CheckpointStatus.RESUMED]
        ]
        
        # If ClickHouse is available, also query from there
        if self._clickhouse_client:
            try:
                query = """
                SELECT * FROM extraction_checkpoints
                WHERE status IN ('active', 'resumed')
                ORDER BY updated_at DESC
                """
                
                result = self._clickhouse_client.execute(query)
                
                # Convert to checkpoint objects
                for row in result:
                    extraction_id = row[0]  # First column is extraction_id
                    if extraction_id not in self._in_memory_checkpoints:
                        checkpoint = self._row_to_checkpoint(row)
                        active.append(checkpoint)
            except Exception as e:
                self._logger.error(f"Failed to list active checkpoints: {str(e)}")
        
        return active
    
    def cleanup_old_checkpoints(self, days: int = 7) -> int:
        """
        Cleanup completed checkpoints older than specified days.
        
        This helps prevent unbounded growth of the checkpoints table.
        Only removes COMPLETED checkpoints, keeps FAILED for debugging.
        
        Args:
            days: Number of days to keep checkpoints (default: 7)
            
        Returns:
            Number of checkpoints deleted
        """
        if not self._clickhouse_client:
            self._logger.warning("Cannot cleanup checkpoints: no ClickHouse client")
            return 0
        
        try:
            # Delete completed checkpoints older than N days
            delete_sql = f"""
            ALTER TABLE extraction_checkpoints
            DELETE WHERE status = 'completed'
            AND completed_at < now() - INTERVAL {days} DAY
            """
            
            self._clickhouse_client.execute(delete_sql)
            
            # Also cleanup in-memory cache
            to_remove = [
                extraction_id
                for extraction_id, cp in self._in_memory_checkpoints.items()
                if cp.status == CheckpointStatus.COMPLETED
                and cp.completed_at
                and (datetime.now(timezone.utc) - cp.completed_at).days > days
            ]
            
            for extraction_id in to_remove:
                del self._in_memory_checkpoints[extraction_id]
            
            count = len(to_remove)
            self._logger.info(f"Cleaned up {count} old checkpoints (older than {days} days)")
            
            return count
        except Exception as e:
            self._logger.error(f"Failed to cleanup old checkpoints: {str(e)}")
            return 0
    
    def _persist_checkpoint(self, checkpoint: ExtractionCheckpoint) -> None:
        """
        Persist checkpoint to ClickHouse.
        
        Uses INSERT to add a new version. ReplacingMergeTree will keep the
        latest version based on updated_at.
        
        Args:
            checkpoint: ExtractionCheckpoint object to persist
        """
        if not self._clickhouse_client:
            return
        
        try:
            import json
            
            # Prepare data for insertion
            insert_sql = """
            INSERT INTO extraction_checkpoints (
                extraction_id, source_id, source_type, last_offset, last_batch_id,
                rows_extracted, batches_processed, status, created_at, updated_at,
                completed_at, error_message, correlation_id, metadata
            ) VALUES
            """
            
            # Convert metadata to JSON string
            metadata_json = json.dumps(checkpoint.metadata) if checkpoint.metadata else "{}"
            payload = [{
                "extraction_id": checkpoint.extraction_id,
                "source_id": checkpoint.source_id,
                "source_type": checkpoint.source_type,
                "last_offset": checkpoint.last_offset,
                "last_batch_id": checkpoint.last_batch_id,
                "rows_extracted": checkpoint.rows_extracted,
                "batches_processed": checkpoint.batches_processed,
                "status": checkpoint.status.value,
                "created_at": checkpoint.created_at,
                "updated_at": checkpoint.updated_at,
                "completed_at": checkpoint.completed_at,
                "error_message": checkpoint.error_message,
                "correlation_id": checkpoint.correlation_id,
                "metadata": metadata_json,
            }]
            self._clickhouse_client.execute(insert_sql, payload)
        except Exception as e:
            self._logger.error(f"Failed to persist checkpoint: {str(e)}")
            # Don't raise - checkpoint is still in memory
    
    def _load_checkpoint(self, extraction_id: str) -> Optional[ExtractionCheckpoint]:
        """
        Load checkpoint from ClickHouse.
        
        Gets the latest version of the checkpoint (highest updated_at).
        
        Args:
            extraction_id: Unique identifier for the extraction
            
        Returns:
            ExtractionCheckpoint object or None if not found
        """
        if not self._clickhouse_client:
            return None
        
        try:
            query = """
            SELECT * FROM extraction_checkpoints
            WHERE extraction_id = %(extraction_id)s
            ORDER BY updated_at DESC
            LIMIT 1
            """
            
            result = self._clickhouse_client.execute(query, {"extraction_id": extraction_id})
            
            if not result:
                return None
            
            return self._row_to_checkpoint(result[0])
        except Exception as e:
            self._logger.error(f"Failed to load checkpoint: {str(e)}")
            return None
    
    def _row_to_checkpoint(self, row: tuple) -> ExtractionCheckpoint:
        """
        Convert ClickHouse row to ExtractionCheckpoint object.
        
        Args:
            row: Tuple from ClickHouse query result
            
        Returns:
            ExtractionCheckpoint object
        """
        import json
        
        # Parse row (order matches table schema)
        (
            extraction_id, source_id, source_type, last_offset, last_batch_id,
            rows_extracted, batches_processed, status, created_at, updated_at,
            completed_at, error_message, correlation_id, metadata_json
        ) = row
        
        # Parse metadata JSON
        metadata = json.loads(metadata_json) if metadata_json else {}
        
        # Convert status string to enum
        status_enum = CheckpointStatus(status)
        
        return ExtractionCheckpoint(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type=source_type,
            last_offset=last_offset,
            last_batch_id=last_batch_id,
            rows_extracted=rows_extracted,
            batches_processed=batches_processed,
            status=status_enum,
            created_at=created_at,
            updated_at=updated_at,
            completed_at=completed_at,
            error_message=error_message,
            correlation_id=correlation_id,
            metadata=metadata
        )
