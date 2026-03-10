"""
Unit tests for IdempotencyManager.
Tests deduplication, idempotent operations, and row hash generation.
"""
import pytest
import uuid
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from idempotency_manager import (
    IdempotencyManager,
    IdempotencyKey,
    PipelineStage
)


@pytest.fixture
def mock_clickhouse_client():
    """Create a mock ClickHouse client for testing."""
    client = Mock()
    client.execute = Mock()
    return client


@pytest.fixture
def idempotency_manager(mock_clickhouse_client):
    """Create an IdempotencyManager instance with mock client."""
    return IdempotencyManager(mock_clickhouse_client)


class TestIdempotencyKey:
    """Tests for IdempotencyKey class."""
    
    def test_idempotency_key_creation(self):
        """Test creating an IdempotencyKey."""
        key = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash="abc123def456"
        )
        
        assert key.source_id == "source_001"
        assert key.batch_id == "batch_001"
        assert key.row_hash == "abc123def456"
    
    def test_to_dedup_key(self):
        """Test generating composite deduplication key."""
        key = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash="abc123"
        )
        
        dedup_key = key.to_dedup_key()
        assert dedup_key == "source_001:batch_001:abc123"
    
    def test_to_dedup_key_with_special_characters(self):
        """Test dedup key generation with special characters."""
        key = IdempotencyKey(
            source_id="source:with:colons",
            batch_id="batch-with-dashes",
            row_hash="hash_with_underscores"
        )
        
        dedup_key = key.to_dedup_key()
        assert dedup_key == "source:with:colons:batch-with-dashes:hash_with_underscores"


class TestRowHashGeneration:
    """Tests for row hash generation."""
    
    def test_generate_row_hash(self, idempotency_manager):
        """Test generating SHA256 hash from row data."""
        row = {
            "id": 1,
            "name": "John Doe",
            "email": "john@example.com"
        }
        
        hash_value = idempotency_manager.generate_row_hash(row)
        
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64  # SHA256 produces 64 hex characters
    
    def test_generate_row_hash_deterministic(self, idempotency_manager):
        """Test that same row produces same hash (deterministic)."""
        row = {
            "id": 1,
            "name": "John Doe",
            "email": "john@example.com"
        }
        
        hash1 = idempotency_manager.generate_row_hash(row)
        hash2 = idempotency_manager.generate_row_hash(row)
        hash3 = idempotency_manager.generate_row_hash(row)
        
        assert hash1 == hash2 == hash3
    
    def test_generate_row_hash_different_order_same_hash(self, idempotency_manager):
        """Test that row with different key order produces same hash."""
        row1 = {"id": 1, "name": "John", "email": "john@example.com"}
        row2 = {"email": "john@example.com", "id": 1, "name": "John"}
        row3 = {"name": "John", "email": "john@example.com", "id": 1}
        
        hash1 = idempotency_manager.generate_row_hash(row1)
        hash2 = idempotency_manager.generate_row_hash(row2)
        hash3 = idempotency_manager.generate_row_hash(row3)
        
        assert hash1 == hash2 == hash3
    
    def test_generate_row_hash_different_values_different_hash(self, idempotency_manager):
        """Test that different row values produce different hashes."""
        row1 = {"id": 1, "name": "John"}
        row2 = {"id": 2, "name": "John"}
        row3 = {"id": 1, "name": "Jane"}
        
        hash1 = idempotency_manager.generate_row_hash(row1)
        hash2 = idempotency_manager.generate_row_hash(row2)
        hash3 = idempotency_manager.generate_row_hash(row3)
        
        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3
    
    def test_generate_row_hash_empty_row(self, idempotency_manager):
        """Test hash generation for empty row."""
        row = {}
        hash_value = idempotency_manager.generate_row_hash(row)
        
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64


class TestIsDuplicate:
    """Tests for is_duplicate method."""
    
    def test_is_duplicate_not_processed(self, idempotency_manager, mock_clickhouse_client):
        """Test that unprocessed row is not a duplicate."""
        # Mock: no rows found (not processed)
        mock_clickhouse_client.execute.return_value = [[0]]
        
        key = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash="abc123"
        )
        
        is_dup = idempotency_manager.is_duplicate(key, PipelineStage.EXTRACT)
        assert is_dup is False
        
        # Verify query was called
        assert mock_clickhouse_client.execute.called
    
    def test_is_duplicate_after_marking(self, idempotency_manager, mock_clickhouse_client):
        """Test that row is duplicate after marking as processed."""
        key = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash="abc123"
        )
        
        # Mock: mark_processed succeeds
        mock_clickhouse_client.execute.return_value = None
        idempotency_manager.mark_processed(key, PipelineStage.EXTRACT)
        
        # Mock: is_duplicate returns True (row found)
        mock_clickhouse_client.execute.return_value = [[1]]
        is_dup = idempotency_manager.is_duplicate(key, PipelineStage.EXTRACT)
        assert is_dup is True
    
    def test_is_duplicate_different_stages(self, idempotency_manager, mock_clickhouse_client):
        """Test that duplicate check is stage-specific."""
        key = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash="abc123"
        )
        
        # Mock: mark_processed succeeds
        mock_clickhouse_client.execute.return_value = None
        idempotency_manager.mark_processed(key, PipelineStage.EXTRACT)
        
        # Mock: EXTRACT stage has the row (duplicate)
        def mock_execute(query, params):
            if params.get('stage') == 'extract':
                return [[1]]
            else:
                return [[0]]
        
        mock_clickhouse_client.execute.side_effect = mock_execute
        
        # Should be duplicate in EXTRACT
        assert idempotency_manager.is_duplicate(key, PipelineStage.EXTRACT) is True
        
        # Should NOT be duplicate in TRANSFORM (different stage)
        assert idempotency_manager.is_duplicate(key, PipelineStage.TRANSFORM) is False
        
        # Should NOT be duplicate in LOAD (different stage)
        assert idempotency_manager.is_duplicate(key, PipelineStage.LOAD) is False
    
    def test_is_duplicate_different_batches(self, idempotency_manager, mock_clickhouse_client):
        """Test that duplicate check considers batch_id."""
        key1 = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash="abc123"
        )
        key2 = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_002",
            row_hash="abc123"
        )
        
        # Mock: mark key1 as processed
        mock_clickhouse_client.execute.return_value = None
        idempotency_manager.mark_processed(key1, PipelineStage.EXTRACT)
        
        # Mock: key1 is duplicate, key2 is not
        def mock_execute(query, params):
            dedup_key = params.get('dedup_key', '')
            if 'batch_001' in dedup_key:
                return [[1]]
            else:
                return [[0]]
        
        mock_clickhouse_client.execute.side_effect = mock_execute
        
        # key1 should be duplicate
        assert idempotency_manager.is_duplicate(key1, PipelineStage.EXTRACT) is True
        
        # key2 should NOT be duplicate (different batch)
        assert idempotency_manager.is_duplicate(key2, PipelineStage.EXTRACT) is False


class TestMarkProcessed:
    """Tests for mark_processed method."""
    
    def test_mark_processed_success(self, idempotency_manager, mock_clickhouse_client):
        """Test successfully marking a row as processed."""
        mock_clickhouse_client.execute.return_value = None
        
        key = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash="abc123"
        )
        
        result = idempotency_manager.mark_processed(key, PipelineStage.EXTRACT)
        assert result is True
        assert mock_clickhouse_client.execute.called
    
    def test_mark_processed_with_row_id(self, idempotency_manager, mock_clickhouse_client):
        """Test marking processed with explicit row_id."""
        mock_clickhouse_client.execute.return_value = None
        
        key = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash="abc123"
        )
        row_id = uuid.uuid4()
        
        result = idempotency_manager.mark_processed(
            key,
            PipelineStage.EXTRACT,
            row_id=row_id
        )
        assert result is True
    
    def test_mark_processed_multiple_stages(self, idempotency_manager, mock_clickhouse_client):
        """Test marking same row as processed in multiple stages."""
        mock_clickhouse_client.execute.return_value = None
        
        key = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash="abc123"
        )
        
        # Mark in all stages
        result1 = idempotency_manager.mark_processed(key, PipelineStage.EXTRACT)
        result2 = idempotency_manager.mark_processed(key, PipelineStage.TRANSFORM)
        result3 = idempotency_manager.mark_processed(key, PipelineStage.LOAD)
        
        assert result1 is True
        assert result2 is True
        assert result3 is True
        
        # Verify execute was called 3 times
        assert mock_clickhouse_client.execute.call_count == 3


class TestCheckAndMark:
    """Tests for check_and_mark atomic operation."""
    
    def test_check_and_mark_first_time(self, idempotency_manager, mock_clickhouse_client):
        """Test check_and_mark for first-time processing."""
        key = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash="abc123"
        )
        
        # Mock: not duplicate (first time)
        mock_clickhouse_client.execute.return_value = [[0]]
        
        result = idempotency_manager.check_and_mark(key, PipelineStage.EXTRACT)
        assert result is True
    
    def test_check_and_mark_duplicate(self, idempotency_manager, mock_clickhouse_client):
        """Test check_and_mark returns False for duplicate."""
        key = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash="abc123"
        )
        
        # First call: not duplicate
        mock_clickhouse_client.execute.return_value = [[0]]
        result1 = idempotency_manager.check_and_mark(key, PipelineStage.EXTRACT)
        assert result1 is True
        
        # Second call: is duplicate
        mock_clickhouse_client.execute.return_value = [[1]]
        result2 = idempotency_manager.check_and_mark(key, PipelineStage.EXTRACT)
        assert result2 is False
    
    def test_check_and_mark_idempotent(self, idempotency_manager, mock_clickhouse_client):
        """Test that check_and_mark is idempotent."""
        key = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash="abc123"
        )
        
        # First call succeeds (not duplicate)
        mock_clickhouse_client.execute.return_value = [[0]]
        result1 = idempotency_manager.check_and_mark(key, PipelineStage.EXTRACT)
        assert result1 is True
        
        # Subsequent calls return False (already processed)
        mock_clickhouse_client.execute.return_value = [[1]]
        result2 = idempotency_manager.check_and_mark(key, PipelineStage.EXTRACT)
        result3 = idempotency_manager.check_and_mark(key, PipelineStage.EXTRACT)
        result4 = idempotency_manager.check_and_mark(key, PipelineStage.EXTRACT)
        
        assert result2 is False
        assert result3 is False
        assert result4 is False


class TestProcessingStats:
    """Tests for get_processing_stats method."""
    
    def test_get_processing_stats_empty_batch(self, idempotency_manager, mock_clickhouse_client):
        """Test stats for batch with no processed rows."""
        mock_clickhouse_client.execute.return_value = []
        
        stats = idempotency_manager.get_processing_stats("batch_999")
        assert stats == {}
    
    def test_get_processing_stats_single_stage(self, idempotency_manager, mock_clickhouse_client):
        """Test stats for single stage."""
        # Mock: 3 rows processed
        mock_clickhouse_client.execute.return_value = [[3]]
        
        batch_id = "batch_001"
        stats = idempotency_manager.get_processing_stats(
            batch_id,
            stage=PipelineStage.EXTRACT
        )
        
        assert stats['count'] == 3
    
    def test_get_processing_stats_multiple_stages(self, idempotency_manager, mock_clickhouse_client):
        """Test stats across multiple stages."""
        # Mock: different counts per stage
        mock_clickhouse_client.execute.return_value = [
            ['extract', 2],
            ['transform', 3],
            ['load', 1]
        ]
        
        batch_id = "batch_002"
        stats = idempotency_manager.get_processing_stats(batch_id)
        
        assert stats['extract'] == 2
        assert stats['transform'] == 3
        assert stats['load'] == 1


class TestEndToEndScenarios:
    """End-to-end integration tests."""
    
    def test_complete_pipeline_flow(self, idempotency_manager, mock_clickhouse_client):
        """Test complete pipeline flow: extract → transform → load."""
        row_data = {
            "id": 1,
            "name": "John Doe",
            "email": "john@example.com"
        }
        
        # Generate hash from row data
        row_hash = idempotency_manager.generate_row_hash(row_data)
        
        key = IdempotencyKey(
            source_id="csv_file_001",
            batch_id="batch_20240101_001",
            row_hash=row_hash
        )
        
        # Mock responses for each stage
        call_count = [0]
        
        def mock_execute(query, params=None):
            if 'SELECT COUNT' in query:
                # First check: not duplicate, subsequent checks: duplicate
                call_count[0] += 1
                if call_count[0] in [1, 3, 5]:  # First check for each stage
                    return [[0]]
                else:
                    return [[1]]
            return None
        
        mock_clickhouse_client.execute.side_effect = mock_execute
        
        # EXTRACT stage
        assert idempotency_manager.is_duplicate(key, PipelineStage.EXTRACT) is False
        assert idempotency_manager.mark_processed(key, PipelineStage.EXTRACT) is True
        assert idempotency_manager.is_duplicate(key, PipelineStage.EXTRACT) is True
        
        # TRANSFORM stage
        assert idempotency_manager.is_duplicate(key, PipelineStage.TRANSFORM) is False
        assert idempotency_manager.mark_processed(key, PipelineStage.TRANSFORM) is True
        assert idempotency_manager.is_duplicate(key, PipelineStage.TRANSFORM) is True
        
        # LOAD stage
        assert idempotency_manager.is_duplicate(key, PipelineStage.LOAD) is False
        assert idempotency_manager.mark_processed(key, PipelineStage.LOAD) is True
        assert idempotency_manager.is_duplicate(key, PipelineStage.LOAD) is True
    
    def test_retry_scenario(self, idempotency_manager, mock_clickhouse_client):
        """Test retry scenario - same row processed multiple times."""
        row_data = {"id": 1, "value": "test"}
        row_hash = idempotency_manager.generate_row_hash(row_data)
        
        key = IdempotencyKey(
            source_id="source_001",
            batch_id="batch_001",
            row_hash=row_hash
        )
        
        # Mock: first check returns not duplicate, subsequent checks return duplicate
        call_count = [0]
        
        def mock_execute(query, params=None):
            if 'SELECT COUNT' in query:
                call_count[0] += 1
                if call_count[0] == 1:
                    return [[0]]  # First check: not duplicate
                else:
                    return [[1]]  # Subsequent checks: duplicate
            return None
        
        mock_clickhouse_client.execute.side_effect = mock_execute
        
        # First attempt - should succeed
        result1 = idempotency_manager.check_and_mark(key, PipelineStage.EXTRACT)
        assert result1 is True
        
        # Retry attempts - should be detected as duplicates
        result2 = idempotency_manager.check_and_mark(key, PipelineStage.EXTRACT)
        result3 = idempotency_manager.check_and_mark(key, PipelineStage.EXTRACT)
        
        assert result2 is False
        assert result3 is False
    
    def test_batch_processing(self, idempotency_manager, mock_clickhouse_client):
        """Test processing multiple rows in a batch."""
        batch_id = "batch_003"
        source_id = "source_001"
        
        rows = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Charlie"},
            {"id": 4, "name": "David"},
            {"id": 5, "name": "Eve"}
        ]
        
        # Mock: all rows are not duplicates initially
        call_count = [0]
        
        def mock_execute(query, params=None):
            if 'SELECT COUNT' in query:
                call_count[0] += 1
                if call_count[0] <= 5:  # First 5 checks: not duplicate
                    return [[0]]
                else:  # Subsequent checks: duplicate
                    return [[1]]
            return None
        
        mock_clickhouse_client.execute.side_effect = mock_execute
        
        # Process all rows
        for row in rows:
            row_hash = idempotency_manager.generate_row_hash(row)
            key = IdempotencyKey(
                source_id=source_id,
                batch_id=batch_id,
                row_hash=row_hash
            )
            result = idempotency_manager.check_and_mark(key, PipelineStage.EXTRACT)
            assert result is True
        
        # Mock stats query
        mock_clickhouse_client.execute.side_effect = None
        mock_clickhouse_client.execute.return_value = [[5]]
        
        # Verify stats
        stats = idempotency_manager.get_processing_stats(
            batch_id,
            stage=PipelineStage.EXTRACT
        )
        assert stats['count'] == 5
        
        # Try to reprocess - all should be duplicates
        mock_clickhouse_client.execute.return_value = [[1]]
        for row in rows:
            row_hash = idempotency_manager.generate_row_hash(row)
            key = IdempotencyKey(
                source_id=source_id,
                batch_id=batch_id,
                row_hash=row_hash
            )
            is_dup = idempotency_manager.is_duplicate(key, PipelineStage.EXTRACT)
            assert is_dup is True
