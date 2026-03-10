"""
Extraction Progress Tracking

This module provides progress tracking for extraction operations to enable
monitoring of ongoing extractions and identification of bottlenecks.

Design Principles:
- Observable: Provides real-time progress metrics
- Structured: Uses correlation IDs for distributed tracing
- Queryable: Progress can be queried via API
- Persistent: Progress stored in metadata service

Requirements:
- US-9: Observability (AC 9.1: Structured logging with correlation IDs)
- NFR-5: Maintainability - Automated testing and documentation
- Section 4.3: Structured Logging - Add correlation IDs to all log messages
- Section 4.4: Metrics & Monitoring - Define key metrics (throughput, latency, error rate)
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from enum import Enum
import logging
import json


class ExtractionStatus(Enum):
    """Status of an extraction operation."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExtractionProgress:
    """
    Tracks progress of an extraction operation.
    
    Attributes:
        extraction_id: Unique identifier for the extraction operation
        source_id: Identifier for the data source
        source_type: Type of source (csv, database, etc.)
        status: Current status of the extraction
        rows_extracted: Total number of rows extracted so far
        batches_processed: Number of batches processed
        current_offset: Current offset position in the source
        estimated_total_rows: Estimated total rows (if known)
        started_at: Timestamp when extraction started
        updated_at: Timestamp of last progress update
        completed_at: Timestamp when extraction completed (if completed)
        error_message: Error message if extraction failed
        correlation_id: Correlation ID for distributed tracing
        metadata: Additional metadata about the extraction
    """
    extraction_id: str
    source_id: str
    source_type: str
    status: ExtractionStatus
    rows_extracted: int = 0
    batches_processed: int = 0
    current_offset: int = 0
    estimated_total_rows: Optional[int] = None
    started_at: Optional[datetime] = None
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
        for field in ['started_at', 'updated_at', 'completed_at']:
            if data[field] is not None:
                data[field] = data[field].isoformat()
        return data
    
    def get_progress_percentage(self) -> Optional[float]:
        """
        Calculate progress percentage if estimated total is known.
        
        Returns:
            Progress percentage (0-100) or None if total is unknown
        """
        if self.estimated_total_rows and self.estimated_total_rows > 0:
            return min(100.0, (self.rows_extracted / self.estimated_total_rows) * 100)
        return None
    
    def get_throughput(self) -> Optional[float]:
        """
        Calculate extraction throughput in rows per second.
        
        Returns:
            Rows per second or None if not enough data
        """
        if not self.started_at or not self.updated_at:
            return None
        
        elapsed = (self.updated_at - self.started_at).total_seconds()
        if elapsed > 0:
            return self.rows_extracted / elapsed
        return None
    
    def estimate_completion_time(self) -> Optional[datetime]:
        """
        Estimate completion time based on current throughput.
        
        Returns:
            Estimated completion datetime or None if cannot estimate
        """
        if not self.estimated_total_rows or not self.started_at or not self.updated_at:
            return None
        
        throughput = self.get_throughput()
        if not throughput or throughput <= 0:
            return None
        
        remaining_rows = self.estimated_total_rows - self.rows_extracted
        if remaining_rows <= 0:
            return self.updated_at
        
        estimated_seconds = remaining_rows / throughput
        from datetime import timedelta
        return self.updated_at + timedelta(seconds=estimated_seconds)


class ProgressTracker:
    """
    Manages extraction progress tracking with structured logging and persistence.
    
    This class provides methods to track extraction progress, log progress updates
    with correlation IDs, and persist progress to the metadata service.
    
    Key Features:
    - Structured logging with correlation IDs
    - In-memory progress tracking with periodic updates
    - Progress persistence to metadata service
    - Progress querying via API
    - Metrics calculation (throughput, ETA, percentage)
    
    Example Usage:
        tracker = ProgressTracker(metadata_client=metadata_client)
        
        # Start tracking
        progress = tracker.start_extraction(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            correlation_id="corr_456"
        )
        
        # Update progress
        tracker.update_progress(
            extraction_id="ext_123",
            rows_extracted=1000,
            batches_processed=1,
            current_offset=1000
        )
        
        # Complete extraction
        tracker.complete_extraction(extraction_id="ext_123")
    """
    
    def __init__(self, metadata_client=None, logger=None):
        """
        Initialize progress tracker.
        
        Args:
            metadata_client: Optional client for persisting progress to metadata service
            logger: Optional logger instance (creates one if not provided)
        """
        self._progress_map: Dict[str, ExtractionProgress] = {}
        self._metadata_client = metadata_client
        self._logger = logger or self._create_logger()
    
    def _create_logger(self) -> logging.Logger:
        """Create a structured logger for progress tracking."""
        logger = logging.getLogger('extraction_progress')
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
                '"logger": "%(name)s", "message": "%(message)s", '
                '"correlation_id": "%(correlation_id)s"}'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger
    
    def start_extraction(
        self,
        extraction_id: str,
        source_id: str,
        source_type: str,
        correlation_id: Optional[str] = None,
        estimated_total_rows: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ExtractionProgress:
        """
        Start tracking a new extraction operation.
        
        Args:
            extraction_id: Unique identifier for the extraction
            source_id: Identifier for the data source
            source_type: Type of source (csv, database, etc.)
            correlation_id: Optional correlation ID for distributed tracing
            estimated_total_rows: Optional estimated total rows
            metadata: Optional additional metadata
            
        Returns:
            ExtractionProgress object
        """
        now = datetime.now(timezone.utc)
        
        progress = ExtractionProgress(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type=source_type,
            status=ExtractionStatus.IN_PROGRESS,
            started_at=now,
            updated_at=now,
            correlation_id=correlation_id,
            estimated_total_rows=estimated_total_rows,
            metadata=metadata or {}
        )
        
        self._progress_map[extraction_id] = progress
        
        # Log start with correlation ID
        self._log_progress(
            progress,
            f"Started extraction for source {source_id} (type: {source_type})"
        )
        
        # Persist to metadata service if available
        if self._metadata_client:
            self._persist_progress(progress)
        
        return progress
    
    def update_progress(
        self,
        extraction_id: str,
        rows_extracted: Optional[int] = None,
        batches_processed: Optional[int] = None,
        current_offset: Optional[int] = None,
        estimated_total_rows: Optional[int] = None
    ) -> Optional[ExtractionProgress]:
        """
        Update progress for an ongoing extraction.
        
        Args:
            extraction_id: Unique identifier for the extraction
            rows_extracted: Total rows extracted (cumulative)
            batches_processed: Total batches processed (cumulative)
            current_offset: Current offset position
            estimated_total_rows: Updated estimate of total rows
            
        Returns:
            Updated ExtractionProgress object or None if not found
        """
        progress = self._progress_map.get(extraction_id)
        if not progress:
            self._logger.warning(
                f"Progress update for unknown extraction_id: {extraction_id}",
                extra={'correlation_id': 'unknown'}
            )
            return None
        
        # Update fields
        if rows_extracted is not None:
            progress.rows_extracted = rows_extracted
        if batches_processed is not None:
            progress.batches_processed = batches_processed
        if current_offset is not None:
            progress.current_offset = current_offset
        if estimated_total_rows is not None:
            progress.estimated_total_rows = estimated_total_rows
        
        progress.updated_at = datetime.now(timezone.utc)
        
        # Log progress update with metrics
        throughput = progress.get_throughput()
        percentage = progress.get_progress_percentage()
        
        log_message = (
            f"Extraction progress: {progress.rows_extracted} rows, "
            f"{progress.batches_processed} batches, offset {progress.current_offset}"
        )
        
        if throughput:
            log_message += f", throughput: {throughput:.2f} rows/sec"
        if percentage is not None:
            log_message += f", progress: {percentage:.1f}%"
        
        self._log_progress(progress, log_message)
        
        # Persist to metadata service if available
        if self._metadata_client:
            self._persist_progress(progress)
        
        return progress
    
    def complete_extraction(
        self,
        extraction_id: str,
        final_row_count: Optional[int] = None
    ) -> Optional[ExtractionProgress]:
        """
        Mark an extraction as completed.
        
        Args:
            extraction_id: Unique identifier for the extraction
            final_row_count: Optional final row count (if different from tracked)
            
        Returns:
            Completed ExtractionProgress object or None if not found
        """
        progress = self._progress_map.get(extraction_id)
        if not progress:
            return None
        
        now = datetime.now(timezone.utc)
        progress.status = ExtractionStatus.COMPLETED
        progress.completed_at = now
        progress.updated_at = now
        
        if final_row_count is not None:
            progress.rows_extracted = final_row_count
        
        # Calculate final metrics
        throughput = progress.get_throughput()
        elapsed = (now - progress.started_at).total_seconds() if progress.started_at else 0
        
        log_message = (
            f"Extraction completed: {progress.rows_extracted} rows in {elapsed:.2f}s"
        )
        if throughput:
            log_message += f", average throughput: {throughput:.2f} rows/sec"
        
        self._log_progress(progress, log_message)
        
        # Persist final state to metadata service
        if self._metadata_client:
            self._persist_progress(progress)
        
        return progress
    
    def fail_extraction(
        self,
        extraction_id: str,
        error_message: str
    ) -> Optional[ExtractionProgress]:
        """
        Mark an extraction as failed.
        
        Args:
            extraction_id: Unique identifier for the extraction
            error_message: Error message describing the failure
            
        Returns:
            Failed ExtractionProgress object or None if not found
        """
        progress = self._progress_map.get(extraction_id)
        if not progress:
            return None
        
        now = datetime.now(timezone.utc)
        progress.status = ExtractionStatus.FAILED
        progress.error_message = error_message
        progress.completed_at = now
        progress.updated_at = now
        
        self._log_progress(
            progress,
            f"Extraction failed: {error_message}",
            level=logging.ERROR
        )
        
        # Persist failure state to metadata service
        if self._metadata_client:
            self._persist_progress(progress)
        
        return progress
    
    def get_progress(self, extraction_id: str) -> Optional[ExtractionProgress]:
        """
        Get current progress for an extraction.
        
        Args:
            extraction_id: Unique identifier for the extraction
            
        Returns:
            ExtractionProgress object or None if not found
        """
        return self._progress_map.get(extraction_id)
    
    def list_active_extractions(self) -> list[ExtractionProgress]:
        """
        List all active (in-progress) extractions.
        
        Returns:
            List of ExtractionProgress objects with IN_PROGRESS status
        """
        return [
            progress for progress in self._progress_map.values()
            if progress.status == ExtractionStatus.IN_PROGRESS
        ]
    
    def _log_progress(
        self,
        progress: ExtractionProgress,
        message: str,
        level: int = logging.INFO
    ) -> None:
        """
        Log progress with structured logging and correlation ID.
        
        Args:
            progress: ExtractionProgress object
            message: Log message
            level: Log level (default: INFO)
        """
        extra = {
            'correlation_id': progress.correlation_id or 'none',
            'extraction_id': progress.extraction_id,
            'source_id': progress.source_id,
            'source_type': progress.source_type,
            'status': progress.status.value,
            'rows_extracted': progress.rows_extracted,
            'batches_processed': progress.batches_processed
        }
        
        self._logger.log(level, message, extra=extra)
    
    def _persist_progress(self, progress: ExtractionProgress) -> None:
        """
        Persist progress to metadata service.
        
        Args:
            progress: ExtractionProgress object to persist
        """
        if not self._metadata_client:
            return
        
        try:
            # Convert to dict for serialization
            progress_data = progress.to_dict()
            
            # Send to metadata service (implementation depends on metadata client API)
            self._metadata_client.store_extraction_progress(progress_data)
        except Exception as e:
            self._logger.error(
                f"Failed to persist progress to metadata service: {str(e)}",
                extra={'correlation_id': progress.correlation_id or 'none'}
            )
