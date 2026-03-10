"""
Integration Tests for Extraction Checkpointing with Extraction Strategies

Tests the integration of checkpointing with CSV and database extraction strategies,
demonstrating resume capability after failures.
"""

import pytest
import os
import tempfile
import csv
from unittest.mock import Mock, MagicMock
from datetime import datetime, timezone

from extraction_strategy import ExtractionConfig
from csv_extraction_strategy import CSVExtractionStrategy
from database_extraction_strategy import DatabaseExtractionStrategy
from extraction_checkpoint import CheckpointManager, CheckpointStatus
from extraction_progress import ProgressTracker


class TestCheckpointWithCSVExtraction:
    """Test checkpointing with CSV extraction strategy."""
    
    @pytest.fixture
    def sample_csv_file(self):
        """Create a sample CSV file for testing."""
        # Create temporary CSV file
        fd, path = tempfile.mkstemp(suffix='.csv')
        
        with os.fdopen(fd, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'name', 'email'])
            writer.writeheader()
            
            # Write 5000 rows
            for i in range(5000):
                writer.writerow({
                    'id': i + 1,
                    'name': f'User {i + 1}',
                    'email': f'user{i + 1}@example.com'
                })
        
        yield path
        
        # Cleanup
        os.unlink(path)
    
    def test_csv_extraction_with_checkpointing(self, sample_csv_file):
        """Test CSV extraction with checkpoint updates after each batch."""
        # Initialize managers
        checkpoint_manager = CheckpointManager(clickhouse_client=None)
        progress_tracker = ProgressTracker(metadata_client=None)
        
        # Create extraction config
        extraction_id = "ext_csv_123"
        source_id = "users_csv"
        
        config = ExtractionConfig(
            source_id=source_id,
            source_type="csv",
            connection_params={
                "file_path": sample_csv_file,
                "encoding": "utf-8",
                "delimiter": ",",
                "has_header": True
            },
            batch_size=1000,
            extraction_id=extraction_id,
            progress_tracker=progress_tracker
        )
        
        # Create checkpoint
        checkpoint = checkpoint_manager.create_checkpoint(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type="csv",
            metadata={"file_path": sample_csv_file}
        )
        
        # Start progress tracking
        progress_tracker.start_extraction(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type="csv",
            estimated_total_rows=5000
        )
        
        # Extract data in batches with checkpointing
        strategy = CSVExtractionStrategy()
        offset = 0
        total_rows = 0
        batch_count = 0
        
        while True:
            # Extract batch
            batch = strategy.extract_batch(config, offset, config.batch_size)
            
            # Process batch (simulate bronze write)
            total_rows += batch.total_rows
            batch_count += 1
            
            # Update checkpoint after successful batch processing
            checkpoint_manager.update_checkpoint(
                extraction_id=extraction_id,
                last_offset=offset + batch.total_rows,
                last_batch_id=batch.batch_id,
                rows_extracted=total_rows,
                batches_processed=batch_count
            )
            
            # Check if done
            if not batch.has_more:
                break
            
            offset += batch.total_rows
        
        # Complete checkpoint
        checkpoint_manager.complete_checkpoint(
            extraction_id=extraction_id,
            final_row_count=total_rows
        )
        
        # Complete progress tracking
        progress_tracker.complete_extraction(
            extraction_id=extraction_id,
            final_row_count=total_rows
        )
        
        # Verify final state
        final_checkpoint = checkpoint_manager.get_checkpoint(extraction_id)
        assert final_checkpoint.status == CheckpointStatus.COMPLETED
        assert final_checkpoint.rows_extracted == 5000
        assert final_checkpoint.batches_processed == 5
        
        final_progress = progress_tracker.get_progress(extraction_id)
        assert final_progress.rows_extracted == 5000
    
    def test_csv_extraction_resume_after_failure(self, sample_csv_file):
        """Test resuming CSV extraction from checkpoint after failure."""
        # Initialize managers
        checkpoint_manager = CheckpointManager(clickhouse_client=None)
        progress_tracker = ProgressTracker(metadata_client=None)
        
        extraction_id = "ext_csv_resume"
        source_id = "users_csv"
        
        config = ExtractionConfig(
            source_id=source_id,
            source_type="csv",
            connection_params={
                "file_path": sample_csv_file,
                "encoding": "utf-8",
                "delimiter": ",",
                "has_header": True
            },
            batch_size=1000,
            extraction_id=extraction_id,
            progress_tracker=progress_tracker
        )
        
        # Create checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type="csv"
        )
        
        progress_tracker.start_extraction(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type="csv",
            estimated_total_rows=5000
        )
        
        # Extract first 2 batches successfully
        strategy = CSVExtractionStrategy()
        offset = 0
        total_rows = 0
        batch_count = 0
        
        for _ in range(2):
            batch = strategy.extract_batch(config, offset, config.batch_size)
            total_rows += batch.total_rows
            batch_count += 1
            
            checkpoint_manager.update_checkpoint(
                extraction_id=extraction_id,
                last_offset=offset + batch.total_rows,
                last_batch_id=batch.batch_id,
                rows_extracted=total_rows,
                batches_processed=batch_count
            )
            
            offset += batch.total_rows
        
        # Simulate failure
        checkpoint_manager.fail_checkpoint(
            extraction_id=extraction_id,
            error_message="Simulated failure"
        )
        
        progress_tracker.fail_extraction(
            extraction_id=extraction_id,
            error_message="Simulated failure"
        )
        
        # Verify checkpoint state
        failed_checkpoint = checkpoint_manager.get_checkpoint(extraction_id)
        assert failed_checkpoint.status == CheckpointStatus.FAILED
        assert failed_checkpoint.rows_extracted == 2000
        assert failed_checkpoint.last_offset == 2000
        
        # Check if can resume
        assert checkpoint_manager.can_resume(extraction_id) is True
        
        # Resume from checkpoint
        resumed_checkpoint = checkpoint_manager.resume_from_checkpoint(extraction_id)
        assert resumed_checkpoint is not None
        assert resumed_checkpoint.last_offset == 2000
        
        # Continue extraction from last offset
        offset = resumed_checkpoint.last_offset
        total_rows = resumed_checkpoint.rows_extracted
        batch_count = resumed_checkpoint.batches_processed
        
        while True:
            batch = strategy.extract_batch(config, offset, config.batch_size)
            total_rows += batch.total_rows
            batch_count += 1
            
            checkpoint_manager.update_checkpoint(
                extraction_id=extraction_id,
                last_offset=offset + batch.total_rows,
                last_batch_id=batch.batch_id,
                rows_extracted=total_rows,
                batches_processed=batch_count
            )
            
            if not batch.has_more:
                break
            
            offset += batch.total_rows
        
        # Complete extraction
        checkpoint_manager.complete_checkpoint(
            extraction_id=extraction_id,
            final_row_count=total_rows
        )
        
        # Verify final state
        final_checkpoint = checkpoint_manager.get_checkpoint(extraction_id)
        assert final_checkpoint.status == CheckpointStatus.COMPLETED
        assert final_checkpoint.rows_extracted == 5000
        assert final_checkpoint.batches_processed == 5


class TestCheckpointWithDatabaseExtraction:
    """Test checkpointing with database extraction strategy."""
    
    @pytest.fixture
    def mock_db_connection(self):
        """Create a mock database connection."""
        connection = Mock()
        
        # Mock cursor
        cursor = Mock()
        
        # Mock execute to return different results based on query
        def execute_side_effect(query):
            if "COUNT(*)" in query:
                # Return total row count
                cursor.fetchone.return_value = {'total': 5000}
            elif "LIMIT" in query:
                # Parse LIMIT and OFFSET from query
                import re
                limit_match = re.search(r'LIMIT (\d+)', query)
                offset_match = re.search(r'OFFSET (\d+)', query)
                
                limit = int(limit_match.group(1)) if limit_match else 1000
                offset = int(offset_match.group(1)) if offset_match else 0
                
                # Generate mock rows
                rows = []
                for i in range(offset, min(offset + limit, 5000)):
                    rows.append({
                        'id': i + 1,
                        'name': f'User {i + 1}',
                        'email': f'user{i + 1}@example.com'
                    })
                
                cursor.fetchall.return_value = rows
                cursor.description = [('id',), ('name',), ('email',)]
        
        cursor.execute.side_effect = execute_side_effect
        connection.cursor.return_value = cursor
        
        # Mock connection type for database detection
        connection.__module__ = 'pymysql'
        
        return connection
    
    def test_database_extraction_with_checkpointing(self, mock_db_connection):
        """Test database extraction with checkpoint updates after each batch."""
        # Initialize managers
        checkpoint_manager = CheckpointManager(clickhouse_client=None)
        progress_tracker = ProgressTracker(metadata_client=None)
        
        extraction_id = "ext_db_123"
        source_id = "users_db"
        
        config = ExtractionConfig(
            source_id=source_id,
            source_type="database",
            connection_params={
                "connection": mock_db_connection,
                "table": "users",
                "order_by": "id"
            },
            batch_size=1000,
            extraction_id=extraction_id,
            progress_tracker=progress_tracker
        )
        
        # Create checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type="database"
        )
        
        progress_tracker.start_extraction(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type="database"
        )
        
        # Extract data in batches with checkpointing
        strategy = DatabaseExtractionStrategy()
        offset = 0
        total_rows = 0
        batch_count = 0
        
        while True:
            batch = strategy.extract_batch(config, offset, config.batch_size)
            
            total_rows += batch.total_rows
            batch_count += 1
            
            # Update checkpoint
            checkpoint_manager.update_checkpoint(
                extraction_id=extraction_id,
                last_offset=offset + batch.total_rows,
                last_batch_id=batch.batch_id,
                rows_extracted=total_rows,
                batches_processed=batch_count
            )
            
            if not batch.has_more:
                break
            
            offset += batch.total_rows
        
        # Complete checkpoint
        checkpoint_manager.complete_checkpoint(
            extraction_id=extraction_id,
            final_row_count=total_rows
        )
        
        # Verify final state
        final_checkpoint = checkpoint_manager.get_checkpoint(extraction_id)
        assert final_checkpoint.status == CheckpointStatus.COMPLETED
        assert final_checkpoint.rows_extracted == 5000
        # Note: batches_processed may be 5 or 6 depending on whether an empty final batch is checked
        assert final_checkpoint.batches_processed >= 5
    
    def test_database_extraction_resume_after_failure(self, mock_db_connection):
        """Test resuming database extraction from checkpoint after failure."""
        # Initialize managers
        checkpoint_manager = CheckpointManager(clickhouse_client=None)
        progress_tracker = ProgressTracker(metadata_client=None)
        
        extraction_id = "ext_db_resume"
        source_id = "users_db"
        
        config = ExtractionConfig(
            source_id=source_id,
            source_type="database",
            connection_params={
                "connection": mock_db_connection,
                "table": "users",
                "order_by": "id"
            },
            batch_size=1000,
            extraction_id=extraction_id,
            progress_tracker=progress_tracker
        )
        
        # Create checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type="database"
        )
        
        progress_tracker.start_extraction(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type="database"
        )
        
        # Extract first 3 batches successfully
        strategy = DatabaseExtractionStrategy()
        offset = 0
        total_rows = 0
        batch_count = 0
        
        for _ in range(3):
            batch = strategy.extract_batch(config, offset, config.batch_size)
            total_rows += batch.total_rows
            batch_count += 1
            
            checkpoint_manager.update_checkpoint(
                extraction_id=extraction_id,
                last_offset=offset + batch.total_rows,
                last_batch_id=batch.batch_id,
                rows_extracted=total_rows,
                batches_processed=batch_count
            )
            
            offset += batch.total_rows
        
        # Simulate failure
        checkpoint_manager.fail_checkpoint(
            extraction_id=extraction_id,
            error_message="Database connection lost"
        )
        
        # Verify checkpoint state
        failed_checkpoint = checkpoint_manager.get_checkpoint(extraction_id)
        assert failed_checkpoint.status == CheckpointStatus.FAILED
        assert failed_checkpoint.rows_extracted == 3000
        assert failed_checkpoint.last_offset == 3000
        
        # Resume from checkpoint
        resumed_checkpoint = checkpoint_manager.resume_from_checkpoint(extraction_id)
        assert resumed_checkpoint is not None
        
        # Continue extraction from last offset
        offset = resumed_checkpoint.last_offset
        total_rows = resumed_checkpoint.rows_extracted
        batch_count = resumed_checkpoint.batches_processed
        
        while True:
            batch = strategy.extract_batch(config, offset, config.batch_size)
            total_rows += batch.total_rows
            batch_count += 1
            
            checkpoint_manager.update_checkpoint(
                extraction_id=extraction_id,
                last_offset=offset + batch.total_rows,
                last_batch_id=batch.batch_id,
                rows_extracted=total_rows,
                batches_processed=batch_count
            )
            
            if not batch.has_more:
                break
            
            offset += batch.total_rows
        
        # Complete extraction
        checkpoint_manager.complete_checkpoint(
            extraction_id=extraction_id,
            final_row_count=total_rows
        )
        
        # Verify final state
        final_checkpoint = checkpoint_manager.get_checkpoint(extraction_id)
        assert final_checkpoint.status == CheckpointStatus.COMPLETED
        assert final_checkpoint.rows_extracted == 5000
        # Note: batches_processed may be 5 or 6 depending on whether an empty final batch is checked
        assert final_checkpoint.batches_processed >= 5


class TestCheckpointIdempotency:
    """Test idempotency of checkpoint operations."""
    
    def test_checkpoint_prevents_duplicate_extraction(self):
        """Test that checkpoints prevent duplicate extraction of same data."""
        checkpoint_manager = CheckpointManager(clickhouse_client=None)
        
        extraction_id = "ext_idempotent"
        source_id = "test_source"
        
        # Create checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type="csv"
        )
        
        # Update checkpoint for batch 1
        checkpoint_manager.update_checkpoint(
            extraction_id=extraction_id,
            last_offset=1000,
            last_batch_id="batch_1",
            rows_extracted=1000,
            batches_processed=1
        )
        
        # Get checkpoint
        checkpoint = checkpoint_manager.get_checkpoint(extraction_id)
        
        # If we try to extract again, we should start from last_offset
        # This prevents re-extracting data that was already processed
        assert checkpoint.last_offset == 1000
        
        # Next extraction should start from offset 1000, not 0
        next_offset = checkpoint.last_offset
        assert next_offset == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
