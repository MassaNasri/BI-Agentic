"""
Additional Unit Tests for Extraction Strategies

This test file provides additional coverage for extraction strategies,
focusing on:
1. Lineage enrichment functionality
2. Progress tracking integration
3. Bronze batch conversion
4. Edge cases and error scenarios
5. Configuration validation edge cases

Requirements:
- Task 2.4.1: Unit tests for extraction strategies
- US-2: Immutable raw data storage (AC 2.2: Raw layer with timestamp and source tracking)
- US-5: Comprehensive data lineage (AC 5.1: Every row tracks source and extraction timestamp)
- FR-1: Immutable Raw Layer - Raw tables include _extracted_at, _source_id, _batch_id
"""

import pytest
import pandas as pd
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch

from extraction_strategy import (
    ExtractionStrategy,
    ExtractionConfig,
    Batch,
    ExtractionError,
    ValidationError
)
from csv_extraction_strategy import CSVExtractionStrategy
from database_extraction_strategy import DatabaseExtractionStrategy


class TestLineageEnrichment:
    """Tests for lineage enrichment functionality across all strategies."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.csv_strategy = CSVExtractionStrategy()
        self.db_strategy = DatabaseExtractionStrategy()
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def _create_csv_file(self, filename, data):
        """Helper to create a CSV file for testing."""
        file_path = os.path.join(self.temp_dir, filename)
        df = pd.DataFrame(data)
        df.to_csv(file_path, index=False)
        return file_path
    
    def test_csv_rows_include_lineage_fields(self):
        """Test that CSV extracted rows include all lineage fields."""
        data = {"id": [1, 2, 3], "name": ["Alice", "Bob", "Charlie"]}
        file_path = self._create_csv_file("test.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path}
        )
        
        batch = self.csv_strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify all rows have lineage fields
        for row in batch.rows:
            assert "_batch_id" in row, "Row missing _batch_id"
            assert "_source_id" in row, "Row missing _source_id"
            assert "_extracted_at" in row, "Row missing _extracted_at"
            
            # Verify values are correct
            assert row["_batch_id"] == batch.batch_id
            assert row["_source_id"] == "test_source"
            assert isinstance(row["_extracted_at"], str)
    
    def test_database_rows_include_lineage_fields(self):
        """Test that database extracted rows include all lineage fields."""
        test_data = [
            {'id': 1, 'name': 'Alice'},
            {'id': 2, 'name': 'Bob'}
        ]
        
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'pymysql.connections'
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = test_data
        mock_cursor.description = [('id', None, None, None, None, None, None),
                                   ('name', None, None, None, None, None, None)]
        mock_connection.cursor.return_value = mock_cursor
        
        config = ExtractionConfig(
            source_id="test_db",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            }
        )
        
        batch = self.db_strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify all rows have lineage fields
        for row in batch.rows:
            assert "_batch_id" in row
            assert "_source_id" in row
            assert "_extracted_at" in row
            assert row["_source_id"] == "test_db"
    
    def test_lineage_fields_do_not_overwrite_original_data(self):
        """Test that lineage fields don't overwrite original data fields."""
        # Create data with fields that might conflict
        data = {
            "id": [1],
            "name": ["Test"],
            "batch_id": ["original_batch"],  # This should NOT be overwritten
            "source_id": ["original_source"]  # This should NOT be overwritten
        }
        file_path = self._create_csv_file("test.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path}
        )
        
        batch = self.csv_strategy.extract_batch(config, offset=0, limit=10)
        
        row = batch.rows[0]
        
        # Original fields should be preserved
        assert row["batch_id"] == "original_batch"
        assert row["source_id"] == "original_source"
        
        # Lineage fields should be added with underscore prefix
        assert row["_batch_id"] == batch.batch_id
        assert row["_source_id"] == "test_source"
    
    def test_extracted_at_timestamp_format(self):
        """Test that _extracted_at is in ISO format."""
        data = {"id": [1]}
        file_path = self._create_csv_file("test.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path}
        )
        
        batch = self.csv_strategy.extract_batch(config, offset=0, limit=10)
        
        extracted_at = batch.rows[0]["_extracted_at"]
        
        # Verify it's a valid ISO format timestamp
        try:
            datetime.fromisoformat(extracted_at.replace('Z', '+00:00'))
        except ValueError:
            pytest.fail(f"_extracted_at is not in valid ISO format: {extracted_at}")


class TestProgressTracking:
    """Tests for progress tracking integration."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.csv_strategy = CSVExtractionStrategy()
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def _create_csv_file(self, filename, data):
        """Helper to create a CSV file for testing."""
        file_path = os.path.join(self.temp_dir, filename)
        df = pd.DataFrame(data)
        df.to_csv(file_path, index=False)
        return file_path
    
    def test_progress_tracker_called_when_provided(self):
        """Test that progress tracker is called when provided in config."""
        data = {"id": list(range(1, 101)), "value": [f"val_{i}" for i in range(1, 101)]}
        file_path = self._create_csv_file("test.csv", data)
        
        # Create mock progress tracker
        mock_tracker = Mock()
        mock_tracker.update_progress = Mock()
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path},
            batch_size=50,
            progress_tracker=mock_tracker,
            extraction_id="test_extraction_123"
        )
        
        # Extract first batch
        batch = self.csv_strategy.extract_batch(config, offset=0, limit=50)
        
        # Verify progress tracker was called
        mock_tracker.update_progress.assert_called_once()
        
        # Verify call arguments
        call_args = mock_tracker.update_progress.call_args
        assert call_args[1]["extraction_id"] == "test_extraction_123"
        assert call_args[1]["rows_extracted"] == 50
        assert call_args[1]["batches_processed"] == 1
        assert call_args[1]["current_offset"] == 50
    
    def test_progress_tracker_not_called_when_not_provided(self):
        """Test that extraction works without progress tracker."""
        data = {"id": [1, 2, 3]}
        file_path = self._create_csv_file("test.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path},
            progress_tracker=None  # No tracker
        )
        
        # Should not raise any exception
        batch = self.csv_strategy.extract_batch(config, offset=0, limit=10)
        assert len(batch.rows) == 3
    
    def test_extraction_id_auto_generated(self):
        """Test that extraction_id is auto-generated if not provided."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": "/some/path.csv"}
        )
        
        # Verify extraction_id was auto-generated
        assert config.extraction_id is not None
        assert config.extraction_id.startswith("ext_")
        assert len(config.extraction_id) > 4
    
    def test_correlation_id_auto_generated(self):
        """Test that correlation_id is auto-generated if not provided."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": "/some/path.csv"}
        )
        
        # Verify correlation_id was auto-generated
        assert config.correlation_id is not None
        assert config.correlation_id.startswith("corr_")
        assert len(config.correlation_id) > 5


class TestConfigurationEdgeCases:
    """Tests for configuration validation edge cases."""
    
    def test_config_with_none_connection_params(self):
        """Test that None connection_params raises error."""
        csv_strategy = CSVExtractionStrategy()
        
        # Create config with None connection_params (bypassing dataclass validation)
        config = ExtractionConfig.__new__(ExtractionConfig)
        config.source_id = "test"
        config.source_type = "csv"
        config.connection_params = None
        config.batch_size = 1000
        config.schema_contract = None
        config.extraction_metadata = None
        config.extraction_id = "test_123"
        config.correlation_id = "corr_123"
        config.progress_tracker = None
        
        with pytest.raises(ValueError, match="connection_params is required"):
            csv_strategy.validate_config(config)
    
    def test_csv_config_with_non_string_file_path(self):
        """Test that non-string file_path raises error."""
        csv_strategy = CSVExtractionStrategy()
        
        config = ExtractionConfig(
            source_id="test",
            source_type="csv",
            connection_params={"file_path": 123}  # Integer instead of string
        )
        
        with pytest.raises(ValueError, match="file_path must be a non-empty string"):
            csv_strategy.extract_batch(config, offset=0, limit=10)
    
    def test_csv_config_with_non_string_encoding(self):
        """Test that non-string encoding raises error."""
        csv_strategy = CSVExtractionStrategy()
        
        config = ExtractionConfig(
            source_id="test",
            source_type="csv",
            connection_params={
                "file_path": "/some/path.csv",
                "encoding": 123  # Integer instead of string
            }
        )
        
        with pytest.raises(ValueError, match="encoding must be a string"):
            csv_strategy.extract_batch(config, offset=0, limit=10)
    
    def test_database_config_with_none_connection(self):
        """Test that None database connection raises error."""
        db_strategy = DatabaseExtractionStrategy()
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": None,
                "table": "users"
            }
        )
        
        with pytest.raises(ExtractionError, match="connection cannot be None"):
            db_strategy.extract_batch(config, offset=0, limit=10)
    
    def test_database_config_with_non_string_table(self):
        """Test that non-string table name raises error."""
        db_strategy = DatabaseExtractionStrategy()
        mock_connection = Mock()
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": 123  # Integer instead of string
            }
        )
        
        with pytest.raises(ExtractionError, match="table must be a non-empty string"):
            db_strategy.extract_batch(config, offset=0, limit=10)


class TestBatchMetadata:
    """Tests for batch metadata completeness."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.csv_strategy = CSVExtractionStrategy()
        self.db_strategy = DatabaseExtractionStrategy()
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def _create_csv_file(self, filename, data):
        """Helper to create a CSV file for testing."""
        file_path = os.path.join(self.temp_dir, filename)
        df = pd.DataFrame(data)
        df.to_csv(file_path, index=False)
        return file_path
    
    def test_csv_metadata_completeness(self):
        """Test that CSV batch metadata includes all required fields."""
        data = {"id": [1, 2, 3]}
        file_path = self._create_csv_file("test.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path}
        )
        
        batch = self.csv_strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify all required metadata fields are present
        required_fields = [
            "file_name",
            "file_size",
            "encoding",
            "delimiter",
            "has_header",
            "extraction_timestamp",
            "rows_extracted"
        ]
        
        for field in required_fields:
            assert field in batch.metadata, f"Missing metadata field: {field}"
        
        # Verify metadata values are reasonable
        assert batch.metadata["file_name"] == "test.csv"
        assert batch.metadata["file_size"] > 0
        assert batch.metadata["rows_extracted"] == 3
    
    def test_database_metadata_completeness(self):
        """Test that database batch metadata includes all required fields."""
        test_data = [{'id': 1, 'name': 'Alice'}]
        
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'pymysql.connections'
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = test_data
        mock_cursor.description = [('id', None, None, None, None, None, None),
                                   ('name', None, None, None, None, None, None)]
        mock_connection.cursor.return_value = mock_cursor
        
        config = ExtractionConfig(
            source_id="test_db",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            }
        )
        
        batch = self.db_strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify all required metadata fields are present
        required_fields = [
            "table",
            "database_type",
            "extraction_timestamp",
            "rows_extracted",
            "query",
            "offset",
            "limit"
        ]
        
        for field in required_fields:
            assert field in batch.metadata, f"Missing metadata field: {field}"
        
        # Verify metadata values
        assert batch.metadata["table"] == "users"
        assert batch.metadata["database_type"] == "mysql"
        assert batch.metadata["rows_extracted"] == 1
        assert "SELECT * FROM" in batch.metadata["query"]


class TestErrorScenarios:
    """Tests for various error scenarios."""
    
    def test_csv_with_corrupted_file(self):
        """Test handling of corrupted CSV file."""
        csv_strategy = CSVExtractionStrategy()
        temp_dir = tempfile.mkdtemp()
        
        try:
            # Create a corrupted CSV file with inconsistent columns
            file_path = os.path.join(temp_dir, "corrupted.csv")
            with open(file_path, 'w') as f:
                f.write("id,name\n")
                f.write("1,Alice\n")
                f.write("2,Bob,ExtraColumn\n")  # Inconsistent columns
                f.write("3\n")  # Missing column
            
            config = ExtractionConfig(
                source_id="test",
                source_type="csv",
                connection_params={"file_path": file_path}
            )
            
            # Pandas python engine will raise ParserError for malformed CSV
            # This should be wrapped in ExtractionError
            with pytest.raises(ExtractionError, match="Failed to extract CSV data"):
                batch = csv_strategy.extract_batch(config, offset=0, limit=10)
        
        finally:
            import shutil
            shutil.rmtree(temp_dir)
    
    def test_database_connection_failure(self):
        """Test handling of database connection failure."""
        db_strategy = DatabaseExtractionStrategy()
        
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'pymysql.connections'
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("Connection lost")
        mock_connection.cursor.return_value = mock_cursor
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            }
        )
        
        with pytest.raises(ExtractionError, match="Failed to extract database data"):
            db_strategy.extract_batch(config, offset=0, limit=10)


class TestMemoryEfficiency:
    """Tests to verify memory-efficient extraction."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.csv_strategy = CSVExtractionStrategy()
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def _create_csv_file(self, filename, data):
        """Helper to create a CSV file for testing."""
        file_path = os.path.join(self.temp_dir, filename)
        df = pd.DataFrame(data)
        df.to_csv(file_path, index=False)
        return file_path
    
    def test_small_batch_from_large_file(self):
        """Test that small batch extraction doesn't load entire large file."""
        # Create a large dataset
        data = {
            "id": list(range(1, 50001)),  # 50,000 rows
            "value": [f"value_{i}" for i in range(1, 50001)]
        }
        file_path = self._create_csv_file("large.csv", data)
        
        config = ExtractionConfig(
            source_id="test",
            source_type="csv",
            connection_params={"file_path": file_path},
            batch_size=100
        )
        
        # Extract small batch from middle
        batch = self.csv_strategy.extract_batch(config, offset=25000, limit=100)
        
        # Should only get 100 rows
        assert len(batch.rows) == 100
        assert batch.rows[0]["id"] == 25001
        assert batch.rows[99]["id"] == 25100
        
        # Verify has_more is True (more data available)
        assert batch.has_more is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
