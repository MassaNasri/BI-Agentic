"""
Unit Tests for Bronze Writer

Tests the BronzeWriter class for direct writes to bronze tables.
"""
import pytest
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import Mock, MagicMock, patch, call
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models.bronze_schema import BronzeRow, BronzeBatch, BronzeTableSchema
from utils.bronze_writer import BronzeWriter, BronzeWriteError
from utils.idempotency_manager import IdempotencyManager, IdempotencyKey, PipelineStage


class TestBronzeWriter:
    """Test suite for BronzeWriter class."""
    
    @pytest.fixture
    def mock_client(self):
        """Create a mock ClickHouse client."""
        client = Mock(spec=Client)
        # Mock EXISTS TABLE query
        client.execute.return_value = [[1]]  # Table exists
        return client
    
    @pytest.fixture
    def mock_idempotency_manager(self):
        """Create a mock IdempotencyManager."""
        manager = Mock(spec=IdempotencyManager)
        manager.is_duplicate.return_value = False
        manager.mark_processed.return_value = True
        return manager
    
    @pytest.fixture
    def sample_bronze_rows(self):
        """Create sample bronze rows for testing."""
        extracted_at = datetime.now(timezone.utc)
        return [
            BronzeRow(
                batch_id="batch_123",
                source_id="test_source",
                extracted_at=extracted_at,
                data={"id": "1", "name": "Alice", "email": "alice@example.com"},
                row_number=0
            ),
            BronzeRow(
                batch_id="batch_123",
                source_id="test_source",
                extracted_at=extracted_at,
                data={"id": "2", "name": "Bob", "email": "bob@example.com"},
                row_number=1
            )
        ]
    
    @pytest.fixture
    def sample_bronze_batch(self, sample_bronze_rows):
        """Create a sample bronze batch for testing."""
        schema = BronzeTableSchema(
            source_name="test_table",
            data_columns={"id": "String", "name": "String", "email": "String"}
        )
        return BronzeBatch(
            batch_id="batch_123",
            source_id="test_source",
            rows=sample_bronze_rows,
            schema=schema
        )
    
    def test_init(self, mock_client, mock_idempotency_manager):
        """Test BronzeWriter initialization."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager,
            max_retries=5,
            enable_deduplication=True
        )
        
        assert writer.client == mock_client
        assert writer.idempotency_manager == mock_idempotency_manager
        assert writer.max_retries == 5
        assert writer.enable_deduplication is True
    
    def test_init_creates_idempotency_manager_if_not_provided(self, mock_client):
        """Test that IdempotencyManager is created if not provided."""
        writer = BronzeWriter(client=mock_client)
        
        assert writer.idempotency_manager is not None
        assert isinstance(writer.idempotency_manager, IdempotencyManager)
    
    def test_write_batch_success(self, mock_client, mock_idempotency_manager, sample_bronze_batch):
        """Test successful batch write."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager
        )
        
        # Mock table exists
        mock_client.execute.side_effect = [
            [[1]],  # EXISTS TABLE
            None,   # INSERT
            [[2]]   # COUNT verification
        ]
        
        result = writer.write_batch(sample_bronze_batch)
        
        assert result["success"] is True
        assert result["rows_written"] == 2
        assert result["rows_skipped"] == 0
        assert result["table_name"] == "bronze_test_table"
        assert result["batch_id"] == "batch_123"
        assert "duration_seconds" in result
        assert "throughput_rows_per_sec" in result
    
    def test_write_batch_validation_failure(self, mock_client, mock_idempotency_manager):
        """Test batch write with validation failure."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager
        )
        
        # Create invalid batch (empty rows)
        schema = BronzeTableSchema(
            source_name="test_table",
            data_columns={"id": "String"}
        )
        invalid_batch = BronzeBatch(
            batch_id="batch_123",
            source_id="test_source",
            rows=[],  # Empty rows - invalid
            schema=schema
        )
        
        result = writer.write_batch(invalid_batch)
        
        assert result["success"] is False
        assert result["rows_written"] == 0
        assert "error" in result
        assert "validation failed" in result["error"].lower()
    
    def test_write_batch_with_duplicates(self, mock_client, mock_idempotency_manager, sample_bronze_batch):
        """Test batch write with duplicate rows filtered out."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager
        )
        
        # Mock first row as duplicate, second as new
        mock_idempotency_manager.is_duplicate.side_effect = [True, False]
        
        # Mock table exists and insert
        mock_client.execute.side_effect = [
            [[1]],  # EXISTS TABLE
            None,   # INSERT
            [[1]]   # COUNT verification
        ]
        
        result = writer.write_batch(sample_bronze_batch)
        
        assert result["success"] is True
        assert result["rows_written"] == 1  # Only one row written
        assert result["rows_skipped"] == 1  # One duplicate skipped
    
    def test_write_batch_all_duplicates(self, mock_client, mock_idempotency_manager, sample_bronze_batch):
        """Test batch write when all rows are duplicates."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager
        )
        
        # Mock all rows as duplicates
        mock_idempotency_manager.is_duplicate.return_value = True
        
        result = writer.write_batch(sample_bronze_batch)
        
        assert result["success"] is True
        assert result["rows_written"] == 0
        assert result["rows_skipped"] == 2
    
    def test_write_batch_deduplication_disabled(self, mock_client, mock_idempotency_manager, sample_bronze_batch):
        """Test batch write with deduplication disabled."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager,
            enable_deduplication=False
        )
        
        # Mock table exists and insert
        mock_client.execute.side_effect = [
            [[1]],  # EXISTS TABLE
            None,   # INSERT
            [[2]]   # COUNT verification
        ]
        
        result = writer.write_batch(sample_bronze_batch)
        
        assert result["success"] is True
        assert result["rows_written"] == 2
        assert result["rows_skipped"] == 0
        
        # Verify is_duplicate was never called
        mock_idempotency_manager.is_duplicate.assert_not_called()
    
    def test_write_batch_table_creation(self, mock_client, mock_idempotency_manager, sample_bronze_batch):
        """Test that table is created if it doesn't exist."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager
        )
        
        # Mock table doesn't exist, then create it
        mock_client.execute.side_effect = [
            [[0]],  # EXISTS TABLE - doesn't exist
            None,   # CREATE TABLE
            None,   # INSERT
            [[2]]   # COUNT verification
        ]
        
        result = writer.write_batch(sample_bronze_batch)
        
        assert result["success"] is True
        assert result["rows_written"] == 2
        
        # Verify CREATE TABLE was called
        calls = mock_client.execute.call_args_list
        assert any("CREATE TABLE" in str(call) for call in calls)
    
    def test_write_batch_retry_on_failure(self, mock_client, mock_idempotency_manager, sample_bronze_batch):
        """Test retry logic on transient failures."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager,
            max_retries=3
        )
        
        # Mock table exists, first insert fails, second succeeds
        mock_client.execute.side_effect = [
            [[1]],  # EXISTS TABLE
            ClickHouseError("Connection timeout"),  # INSERT fails
            None,   # INSERT succeeds on retry
            [[2]]   # COUNT verification
        ]
        
        with patch('time.sleep'):  # Mock sleep to speed up test
            result = writer.write_batch(sample_bronze_batch)
        
        assert result["success"] is True
        assert result["rows_written"] == 2
    
    def test_write_batch_max_retries_exceeded(self, mock_client, mock_idempotency_manager, sample_bronze_batch):
        """Test that write fails after max retries."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager,
            max_retries=2
        )
        
        # Mock table exists, all inserts fail
        mock_client.execute.side_effect = [
            [[1]],  # EXISTS TABLE
            ClickHouseError("Connection timeout"),  # INSERT fails
            ClickHouseError("Connection timeout"),  # INSERT fails again
        ]
        
        with patch('time.sleep'):  # Mock sleep to speed up test
            result = writer.write_batch(sample_bronze_batch)
        
        assert result["success"] is False
        assert result["rows_written"] == 0
        assert "error" in result
        assert "after 2 attempts" in result["error"]
    
    def test_write_batch_schema_error_no_retry(self, mock_client, mock_idempotency_manager, sample_bronze_batch):
        """Test that schema errors don't trigger retries."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager,
            max_retries=3
        )
        
        # Mock table exists, insert fails with schema error
        mock_client.execute.side_effect = [
            [[1]],  # EXISTS TABLE
            ClickHouseError("UNKNOWN_TABLE: Table doesn't exist"),  # INSERT fails
        ]
        
        result = writer.write_batch(sample_bronze_batch)
        
        assert result["success"] is False
        assert "Schema error" in result["error"]
        
        # Verify only 2 execute calls (EXISTS and INSERT), no retries
        assert mock_client.execute.call_count == 2
    
    def test_write_rows_direct(self, mock_client, mock_idempotency_manager):
        """Test direct write of raw dictionaries."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager
        )
        
        rows = [
            {"id": "1", "name": "Alice"},
            {"id": "2", "name": "Bob"}
        ]
        
        # Mock table exists and insert
        mock_client.execute.side_effect = [
            [[1]],  # EXISTS TABLE
            None,   # INSERT
            [[2]]   # COUNT verification
        ]
        
        result = writer.write_rows_direct(
            table_name="bronze_test",
            rows=rows,
            batch_id="batch_456",
            source_id="test_source"
        )
        
        assert result["success"] is True
        assert result["rows_written"] == 2
        assert result["table_name"] == "bronze_test"
        assert result["batch_id"] == "batch_456"
    
    def test_write_rows_direct_empty_rows(self, mock_client, mock_idempotency_manager):
        """Test direct write with empty rows list."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager
        )
        
        result = writer.write_rows_direct(
            table_name="bronze_test",
            rows=[],
            batch_id="batch_456",
            source_id="test_source"
        )
        
        assert result["success"] is False
        assert "validation failed" in result["error"].lower()
    
    def test_filter_duplicates(self, mock_client, mock_idempotency_manager, sample_bronze_rows):
        """Test duplicate filtering logic."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager
        )
        
        # Mock first row as duplicate, second as new
        mock_idempotency_manager.is_duplicate.side_effect = [True, False]
        
        filtered_rows, num_duplicates = writer._filter_duplicates(
            rows=sample_bronze_rows,
            source_id="test_source"
        )
        
        assert len(filtered_rows) == 1
        assert num_duplicates == 1
        assert filtered_rows[0].data["id"] == "2"  # Second row kept
    
    def test_mark_rows_processed(self, mock_client, mock_idempotency_manager, sample_bronze_rows):
        """Test marking rows as processed."""
        writer = BronzeWriter(
            client=mock_client,
            idempotency_manager=mock_idempotency_manager
        )
        
        writer._mark_rows_processed(sample_bronze_rows, "test_source")
        
        # Verify mark_processed was called for each row
        assert mock_idempotency_manager.mark_processed.call_count == 2
        
        # Verify correct parameters
        calls = mock_idempotency_manager.mark_processed.call_args_list
        for call in calls:
            assert call[1]["stage"] == PipelineStage.EXTRACT


class TestBronzeWriterIntegration:
    """Integration tests for BronzeWriter (require ClickHouse)."""
    
    @pytest.mark.integration
    def test_write_batch_real_clickhouse(self):
        """Test writing to real ClickHouse instance."""
        # This test requires a running ClickHouse instance
        # Skip if CLICKHOUSE_HOST is not set
        import os
        if not os.getenv('CLICKHOUSE_HOST'):
            pytest.skip("CLICKHOUSE_HOST not set, skipping integration test")
        
        # Create real client
        client = Client(
            host=os.getenv('CLICKHOUSE_HOST', 'localhost'),
            port=int(os.getenv('CLICKHOUSE_PORT', 9000)),
            database=os.getenv('CLICKHOUSE_DATABASE', 'etl')
        )
        
        writer = BronzeWriter(client=client)
        
        # Create test batch
        extracted_at = datetime.now(timezone.utc)
        rows = [
            BronzeRow(
                batch_id=f"test_batch_{uuid4()}",
                source_id="integration_test",
                extracted_at=extracted_at,
                data={"id": "1", "value": "test"},
                row_number=0
            )
        ]
        
        schema = BronzeTableSchema(
            source_name="integration_test",
            data_columns={"id": "String", "value": "String"}
        )
        
        batch = BronzeBatch(
            batch_id=rows[0].batch_id,
            source_id="integration_test",
            rows=rows,
            schema=schema
        )
        
        # Write batch
        result = writer.write_batch(batch)
        
        assert result["success"] is True
        assert result["rows_written"] == 1
        
        # Cleanup: drop test table
        try:
            client.execute("DROP TABLE IF EXISTS bronze_integration_test")
        except:
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
