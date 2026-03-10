"""
Unit Tests for Extraction Checkpointing

Tests the checkpoint manager functionality including:
- Checkpoint creation and updates
- Resume capability
- Persistence to ClickHouse
- Cleanup of old checkpoints
- Integration with progress tracking
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch
import json

from extraction_checkpoint import (
    ExtractionCheckpoint,
    CheckpointManager,
    CheckpointStatus
)


class TestExtractionCheckpoint:
    """Test ExtractionCheckpoint data class."""
    
    def test_checkpoint_creation(self):
        """Test creating a checkpoint with required fields."""
        checkpoint = ExtractionCheckpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            last_offset=1000,
            last_batch_id="batch_123"
        )
        
        assert checkpoint.extraction_id == "ext_123"
        assert checkpoint.source_id == "customers_csv"
        assert checkpoint.source_type == "csv"
        assert checkpoint.last_offset == 1000
        assert checkpoint.last_batch_id == "batch_123"
        assert checkpoint.rows_extracted == 0
        assert checkpoint.batches_processed == 0
        assert checkpoint.status == CheckpointStatus.ACTIVE
    
    def test_checkpoint_to_dict(self):
        """Test converting checkpoint to dictionary."""
        now = datetime.now(timezone.utc)
        checkpoint = ExtractionCheckpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            last_offset=1000,
            last_batch_id="batch_123",
            rows_extracted=1000,
            batches_processed=1,
            status=CheckpointStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            correlation_id="corr_456",
            metadata={"key": "value"}
        )
        
        data = checkpoint.to_dict()
        
        assert data["extraction_id"] == "ext_123"
        assert data["source_id"] == "customers_csv"
        assert data["status"] == "active"
        assert data["created_at"] == now.isoformat()
        assert data["metadata"] == {"key": "value"}
    
    def test_checkpoint_from_dict(self):
        """Test creating checkpoint from dictionary."""
        now = datetime.now(timezone.utc)
        data = {
            "extraction_id": "ext_123",
            "source_id": "customers_csv",
            "source_type": "csv",
            "last_offset": 1000,
            "last_batch_id": "batch_123",
            "rows_extracted": 1000,
            "batches_processed": 1,
            "status": "active",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "completed_at": None,
            "error_message": None,
            "correlation_id": "corr_456",
            "metadata": {"key": "value"}
        }
        
        checkpoint = ExtractionCheckpoint.from_dict(data)
        
        assert checkpoint.extraction_id == "ext_123"
        assert checkpoint.source_id == "customers_csv"
        assert checkpoint.status == CheckpointStatus.ACTIVE
        assert checkpoint.rows_extracted == 1000
        assert checkpoint.metadata == {"key": "value"}


class TestCheckpointManager:
    """Test CheckpointManager functionality."""
    
    @pytest.fixture
    def mock_clickhouse_client(self):
        """Create a mock ClickHouse client."""
        client = Mock()
        client.execute = Mock()
        return client
    
    @pytest.fixture
    def checkpoint_manager(self, mock_clickhouse_client):
        """Create a checkpoint manager with mock ClickHouse client."""
        return CheckpointManager(clickhouse_client=mock_clickhouse_client)
    
    @pytest.fixture
    def checkpoint_manager_no_db(self):
        """Create a checkpoint manager without ClickHouse (in-memory only)."""
        return CheckpointManager(clickhouse_client=None)
    
    def test_create_checkpoint(self, checkpoint_manager):
        """Test creating a new checkpoint."""
        checkpoint = checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            correlation_id="corr_456",
            metadata={"file_path": "/data/customers.csv"}
        )
        
        assert checkpoint.extraction_id == "ext_123"
        assert checkpoint.source_id == "customers_csv"
        assert checkpoint.source_type == "csv"
        assert checkpoint.last_offset == 0
        assert checkpoint.last_batch_id == ""
        assert checkpoint.rows_extracted == 0
        assert checkpoint.batches_processed == 0
        assert checkpoint.status == CheckpointStatus.ACTIVE
        assert checkpoint.correlation_id == "corr_456"
        assert checkpoint.metadata == {"file_path": "/data/customers.csv"}
        assert checkpoint.created_at is not None
        assert checkpoint.updated_at is not None
    
    def test_create_checkpoint_persists_to_clickhouse(self, checkpoint_manager, mock_clickhouse_client):
        """Test that creating a checkpoint persists to ClickHouse."""
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        # Verify ClickHouse execute was called (once for table creation, once for insert)
        assert mock_clickhouse_client.execute.call_count >= 2
    
    def test_update_checkpoint(self, checkpoint_manager):
        """Test updating a checkpoint after processing a batch."""
        # Create initial checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        # Update checkpoint
        updated = checkpoint_manager.update_checkpoint(
            extraction_id="ext_123",
            last_offset=1000,
            last_batch_id="batch_123",
            rows_extracted=1000,
            batches_processed=1
        )
        
        assert updated is not None
        assert updated.last_offset == 1000
        assert updated.last_batch_id == "batch_123"
        assert updated.rows_extracted == 1000
        assert updated.batches_processed == 1
    
    def test_update_checkpoint_incremental(self, checkpoint_manager):
        """Test updating checkpoint multiple times (incremental progress)."""
        # Create initial checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        # First batch
        checkpoint_manager.update_checkpoint(
            extraction_id="ext_123",
            last_offset=1000,
            last_batch_id="batch_1",
            rows_extracted=1000,
            batches_processed=1
        )
        
        # Second batch
        updated = checkpoint_manager.update_checkpoint(
            extraction_id="ext_123",
            last_offset=2000,
            last_batch_id="batch_2",
            rows_extracted=2000,
            batches_processed=2
        )
        
        assert updated.last_offset == 2000
        assert updated.last_batch_id == "batch_2"
        assert updated.rows_extracted == 2000
        assert updated.batches_processed == 2
    
    def test_update_nonexistent_checkpoint(self, checkpoint_manager):
        """Test updating a checkpoint that doesn't exist."""
        updated = checkpoint_manager.update_checkpoint(
            extraction_id="nonexistent",
            last_offset=1000,
            last_batch_id="batch_123"
        )
        
        assert updated is None
    
    def test_complete_checkpoint(self, checkpoint_manager):
        """Test marking a checkpoint as completed."""
        # Create and update checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        checkpoint_manager.update_checkpoint(
            extraction_id="ext_123",
            last_offset=5000,
            last_batch_id="batch_5",
            rows_extracted=5000,
            batches_processed=5
        )
        
        # Complete checkpoint
        completed = checkpoint_manager.complete_checkpoint(
            extraction_id="ext_123",
            final_row_count=5000
        )
        
        assert completed is not None
        assert completed.status == CheckpointStatus.COMPLETED
        assert completed.completed_at is not None
        assert completed.rows_extracted == 5000
    
    def test_fail_checkpoint(self, checkpoint_manager):
        """Test marking a checkpoint as failed."""
        # Create checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        # Fail checkpoint
        failed = checkpoint_manager.fail_checkpoint(
            extraction_id="ext_123",
            error_message="Connection timeout"
        )
        
        assert failed is not None
        assert failed.status == CheckpointStatus.FAILED
        assert failed.error_message == "Connection timeout"
        assert failed.completed_at is not None
    
    def test_get_checkpoint(self, checkpoint_manager):
        """Test retrieving a checkpoint."""
        # Create checkpoint
        original = checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        # Get checkpoint
        retrieved = checkpoint_manager.get_checkpoint("ext_123")
        
        assert retrieved is not None
        assert retrieved.extraction_id == original.extraction_id
        assert retrieved.source_id == original.source_id
    
    def test_get_nonexistent_checkpoint(self, checkpoint_manager):
        """Test retrieving a checkpoint that doesn't exist."""
        retrieved = checkpoint_manager.get_checkpoint("nonexistent")
        assert retrieved is None
    
    def test_can_resume_active_checkpoint(self, checkpoint_manager):
        """Test checking if an active checkpoint can be resumed."""
        # Create and update checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        checkpoint_manager.update_checkpoint(
            extraction_id="ext_123",
            last_offset=1000,
            last_batch_id="batch_1",
            rows_extracted=1000,
            batches_processed=1
        )
        
        # Should be able to resume (ACTIVE status, offset > 0)
        assert checkpoint_manager.can_resume("ext_123") is True
    
    def test_can_resume_failed_checkpoint(self, checkpoint_manager):
        """Test checking if a failed checkpoint can be resumed."""
        # Create, update, and fail checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        checkpoint_manager.update_checkpoint(
            extraction_id="ext_123",
            last_offset=1000,
            last_batch_id="batch_1",
            rows_extracted=1000,
            batches_processed=1
        )
        
        checkpoint_manager.fail_checkpoint(
            extraction_id="ext_123",
            error_message="Connection timeout"
        )
        
        # Should be able to resume (FAILED status, offset > 0)
        assert checkpoint_manager.can_resume("ext_123") is True
    
    def test_cannot_resume_completed_checkpoint(self, checkpoint_manager):
        """Test that completed checkpoints cannot be resumed."""
        # Create, update, and complete checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        checkpoint_manager.update_checkpoint(
            extraction_id="ext_123",
            last_offset=1000,
            last_batch_id="batch_1",
            rows_extracted=1000,
            batches_processed=1
        )
        
        checkpoint_manager.complete_checkpoint(extraction_id="ext_123")
        
        # Should NOT be able to resume (COMPLETED status)
        assert checkpoint_manager.can_resume("ext_123") is False
    
    def test_cannot_resume_zero_offset(self, checkpoint_manager):
        """Test that checkpoints with zero offset cannot be resumed."""
        # Create checkpoint but don't update it (offset = 0)
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        # Should NOT be able to resume (offset = 0, no progress made)
        assert checkpoint_manager.can_resume("ext_123") is False
    
    def test_resume_from_checkpoint(self, checkpoint_manager):
        """Test resuming an extraction from checkpoint."""
        # Create and update checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        checkpoint_manager.update_checkpoint(
            extraction_id="ext_123",
            last_offset=1000,
            last_batch_id="batch_1",
            rows_extracted=1000,
            batches_processed=1
        )
        
        # Resume from checkpoint
        resumed = checkpoint_manager.resume_from_checkpoint("ext_123")
        
        assert resumed is not None
        assert resumed.status == CheckpointStatus.RESUMED
        assert resumed.last_offset == 1000
        assert resumed.last_batch_id == "batch_1"
    
    def test_resume_from_failed_checkpoint(self, checkpoint_manager):
        """Test resuming from a failed checkpoint."""
        # Create, update, and fail checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        checkpoint_manager.update_checkpoint(
            extraction_id="ext_123",
            last_offset=1000,
            last_batch_id="batch_1",
            rows_extracted=1000,
            batches_processed=1
        )
        
        checkpoint_manager.fail_checkpoint(
            extraction_id="ext_123",
            error_message="Connection timeout"
        )
        
        # Resume from failed checkpoint
        resumed = checkpoint_manager.resume_from_checkpoint("ext_123")
        
        assert resumed is not None
        assert resumed.status == CheckpointStatus.RESUMED
        assert resumed.last_offset == 1000
    
    def test_cannot_resume_nonexistent_checkpoint(self, checkpoint_manager):
        """Test that resuming nonexistent checkpoint returns None."""
        resumed = checkpoint_manager.resume_from_checkpoint("nonexistent")
        assert resumed is None
    
    def test_list_active_checkpoints(self, checkpoint_manager):
        """Test listing all active checkpoints."""
        # Create multiple checkpoints
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_1",
            source_id="source_1",
            source_type="csv"
        )
        
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_2",
            source_id="source_2",
            source_type="database"
        )
        
        # Complete one
        checkpoint_manager.update_checkpoint(
            extraction_id="ext_1",
            last_offset=1000,
            last_batch_id="batch_1"
        )
        checkpoint_manager.complete_checkpoint(extraction_id="ext_1")
        
        # List active checkpoints
        active = checkpoint_manager.list_active_checkpoints()
        
        # Should only have ext_2 (ext_1 is completed)
        assert len(active) == 1
        assert active[0].extraction_id == "ext_2"
    
    def test_in_memory_only_mode(self, checkpoint_manager_no_db):
        """Test checkpoint manager works without ClickHouse (in-memory only)."""
        # Create checkpoint
        checkpoint = checkpoint_manager_no_db.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        assert checkpoint is not None
        
        # Update checkpoint
        updated = checkpoint_manager_no_db.update_checkpoint(
            extraction_id="ext_123",
            last_offset=1000,
            last_batch_id="batch_1"
        )
        
        assert updated is not None
        assert updated.last_offset == 1000
        
        # Get checkpoint
        retrieved = checkpoint_manager_no_db.get_checkpoint("ext_123")
        assert retrieved is not None
        assert retrieved.last_offset == 1000
    
    def test_cleanup_old_checkpoints(self, checkpoint_manager, mock_clickhouse_client):
        """Test cleanup of old completed checkpoints."""
        # Create and complete checkpoint
        checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        checkpoint_manager.complete_checkpoint(extraction_id="ext_123")
        
        # Manually set completed_at to old date
        checkpoint = checkpoint_manager.get_checkpoint("ext_123")
        checkpoint.completed_at = datetime.now(timezone.utc) - timedelta(days=10)
        
        # Cleanup checkpoints older than 7 days
        count = checkpoint_manager.cleanup_old_checkpoints(days=7)
        
        # Verify DELETE was called on ClickHouse
        delete_calls = [
            call for call in mock_clickhouse_client.execute.call_args_list
            if 'DELETE' in str(call)
        ]
        assert len(delete_calls) > 0
    
    def test_checkpoint_idempotency(self, checkpoint_manager):
        """Test that checkpoint operations are idempotent."""
        # Create checkpoint twice with same ID
        checkpoint1 = checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        # Second create should update existing checkpoint (in-memory)
        checkpoint2 = checkpoint_manager.create_checkpoint(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        # Both should refer to same checkpoint
        assert checkpoint1.extraction_id == checkpoint2.extraction_id
        
        # Get checkpoint should return the latest
        retrieved = checkpoint_manager.get_checkpoint("ext_123")
        assert retrieved.extraction_id == "ext_123"


class TestCheckpointIntegration:
    """Integration tests for checkpoint manager with extraction strategies."""
    
    def test_checkpoint_with_csv_extraction(self):
        """Test checkpointing during CSV extraction."""
        # This is a conceptual test showing how checkpointing integrates
        # with extraction strategies
        
        manager = CheckpointManager(clickhouse_client=None)
        
        # Simulate extraction process
        extraction_id = "ext_csv_123"
        source_id = "customers_csv"
        
        # Create checkpoint
        checkpoint = manager.create_checkpoint(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type="csv"
        )
        
        # Simulate extracting batches
        batch_size = 1000
        for batch_num in range(5):
            offset = batch_num * batch_size
            
            # Simulate batch extraction
            # batch = strategy.extract_batch(config, offset, batch_size)
            
            # Update checkpoint after successful batch
            manager.update_checkpoint(
                extraction_id=extraction_id,
                last_offset=offset + batch_size,
                last_batch_id=f"batch_{batch_num}",
                rows_extracted=(batch_num + 1) * batch_size,
                batches_processed=batch_num + 1
            )
        
        # Complete extraction
        manager.complete_checkpoint(extraction_id=extraction_id)
        
        # Verify final state
        final_checkpoint = manager.get_checkpoint(extraction_id)
        assert final_checkpoint.status == CheckpointStatus.COMPLETED
        assert final_checkpoint.rows_extracted == 5000
        assert final_checkpoint.batches_processed == 5
    
    def test_checkpoint_resume_after_failure(self):
        """Test resuming extraction after failure using checkpoint."""
        manager = CheckpointManager(clickhouse_client=None)
        
        extraction_id = "ext_db_123"
        source_id = "customers_db"
        
        # Create checkpoint
        manager.create_checkpoint(
            extraction_id=extraction_id,
            source_id=source_id,
            source_type="database"
        )
        
        # Extract first 3 batches successfully
        batch_size = 1000
        for batch_num in range(3):
            offset = batch_num * batch_size
            manager.update_checkpoint(
                extraction_id=extraction_id,
                last_offset=offset + batch_size,
                last_batch_id=f"batch_{batch_num}",
                rows_extracted=(batch_num + 1) * batch_size,
                batches_processed=batch_num + 1
            )
        
        # Simulate failure
        manager.fail_checkpoint(
            extraction_id=extraction_id,
            error_message="Database connection lost"
        )
        
        # Check if can resume
        assert manager.can_resume(extraction_id) is True
        
        # Resume from checkpoint
        resumed_checkpoint = manager.resume_from_checkpoint(extraction_id)
        assert resumed_checkpoint is not None
        assert resumed_checkpoint.last_offset == 3000
        assert resumed_checkpoint.status == CheckpointStatus.RESUMED
        
        # Continue extraction from last offset
        for batch_num in range(3, 5):
            offset = batch_num * batch_size
            manager.update_checkpoint(
                extraction_id=extraction_id,
                last_offset=offset + batch_size,
                last_batch_id=f"batch_{batch_num}",
                rows_extracted=(batch_num + 1) * batch_size,
                batches_processed=batch_num + 1
            )
        
        # Complete extraction
        manager.complete_checkpoint(extraction_id=extraction_id)
        
        # Verify final state
        final_checkpoint = manager.get_checkpoint(extraction_id)
        assert final_checkpoint.status == CheckpointStatus.COMPLETED
        assert final_checkpoint.rows_extracted == 5000
        assert final_checkpoint.batches_processed == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
