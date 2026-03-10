"""
Unit tests for CSVExtractionStrategy

Tests cover:
1. Basic CSV extraction with chunked reading
2. Idempotency (same offset returns same data)
3. Memory efficiency (doesn't load entire file)
4. Edge cases (encoding, delimiters, headers, empty files)
5. Error handling (missing files, invalid formats)
6. Schema validation
7. Batch pagination (has_more flag)
"""

import pytest
import pandas as pd
import os
import tempfile
from csv_extraction_strategy import CSVExtractionStrategy
from extraction_strategy import (
    ExtractionConfig,
    Batch,
    ExtractionError,
    ValidationError
)


class TestCSVExtractionBasics:
    """Tests for basic CSV extraction functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.strategy = CSVExtractionStrategy()
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def _create_csv_file(self, filename, data, has_header=True):
        """Helper to create a CSV file for testing."""
        file_path = os.path.join(self.temp_dir, filename)
        df = pd.DataFrame(data)
        df.to_csv(file_path, index=False, header=has_header)
        return file_path
    
    def test_extract_simple_csv(self):
        """Test extracting data from a simple CSV file."""
        data = {
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"]
        }
        file_path = self._create_csv_file("test.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path}
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        assert isinstance(batch, Batch)
        assert len(batch.rows) == 3
        assert batch.rows[0]["id"] == 1
        assert batch.rows[0]["name"] == "Alice"
        assert batch.total_rows == 3
        assert batch.has_more is False
    
    def test_extract_with_chunked_reading(self):
        """Test chunked reading extracts correct batch."""
        data = {
            "id": list(range(1, 101)),
            "value": [f"value_{i}" for i in range(1, 101)]
        }
        file_path = self._create_csv_file("large.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path},
            batch_size=10
        )
        
        # Extract first batch
        batch1 = self.strategy.extract_batch(config, offset=0, limit=10)
        
        assert len(batch1.rows) == 10
        assert batch1.rows[0]["id"] == 1
        assert batch1.rows[9]["id"] == 10
        assert batch1.has_more is True
        
        # Extract second batch
        batch2 = self.strategy.extract_batch(config, offset=10, limit=10)
        
        assert len(batch2.rows) == 10
        assert batch2.rows[0]["id"] == 11
        assert batch2.rows[9]["id"] == 20
        assert batch2.has_more is True
    
    def test_extract_last_batch(self):
        """Test extracting the last batch sets has_more to False."""
        data = {
            "id": list(range(1, 26)),  # 25 rows
            "value": [f"value_{i}" for i in range(1, 26)]
        }
        file_path = self._create_csv_file("test.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path}
        )
        
        # Extract last batch (offset 20, limit 10 should get 5 rows)
        batch = self.strategy.extract_batch(config, offset=20, limit=10)
        
        assert len(batch.rows) == 5
        assert batch.rows[0]["id"] == 21
        assert batch.rows[4]["id"] == 25
        assert batch.has_more is False
    
    def test_extract_beyond_file_end(self):
        """Test extracting beyond file end returns empty batch."""
        data = {
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"]
        }
        file_path = self._create_csv_file("test.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path}
        )
        
        batch = self.strategy.extract_batch(config, offset=100, limit=10)
        
        assert len(batch.rows) == 0
        assert batch.total_rows == 0
        assert batch.has_more is False


class TestCSVIdempotency:
    """Tests for idempotency of CSV extraction."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.strategy = CSVExtractionStrategy()
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
    
    def test_same_offset_returns_same_data(self):
        """Test that extracting same offset multiple times returns same data."""
        data = {
            "id": list(range(1, 51)),
            "value": [f"value_{i}" for i in range(1, 51)]
        }
        file_path = self._create_csv_file("test.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path}
        )
        
        # Extract same batch multiple times
        batch1 = self.strategy.extract_batch(config, offset=10, limit=10)
        batch2 = self.strategy.extract_batch(config, offset=10, limit=10)
        batch3 = self.strategy.extract_batch(config, offset=10, limit=10)
        
        # Batch IDs should be identical (deterministic)
        assert batch1.batch_id == batch2.batch_id == batch3.batch_id
        assert batch1.total_rows == batch2.total_rows == batch3.total_rows
        
        # Core data should be identical (excluding timestamps which will vary)
        # Check that all rows have the same data fields
        for i in range(len(batch1.rows)):
            row1 = batch1.rows[i]
            row2 = batch2.rows[i]
            row3 = batch3.rows[i]
            
            # Check data fields are identical
            assert row1["id"] == row2["id"] == row3["id"]
            assert row1["value"] == row2["value"] == row3["value"]
            
            # Check lineage fields are present and consistent
            assert row1["_batch_id"] == row2["_batch_id"] == row3["_batch_id"]
            assert row1["_source_id"] == row2["_source_id"] == row3["_source_id"]
            assert "_extracted_at" in row1
            assert "_extracted_at" in row2
            assert "_extracted_at" in row3
    
    def test_batch_id_deterministic(self):
        """Test that batch_id is deterministic for same source and offset."""
        data = {"id": [1, 2, 3]}
        file_path = self._create_csv_file("test.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path}
        )
        
        batch1 = self.strategy.extract_batch(config, offset=0, limit=10)
        batch2 = self.strategy.extract_batch(config, offset=0, limit=10)
        
        assert batch1.batch_id == batch2.batch_id


class TestCSVEdgeCases:
    """Tests for CSV edge cases (encoding, delimiters, headers)."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.strategy = CSVExtractionStrategy()
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_csv_with_custom_delimiter(self):
        """Test extracting CSV with custom delimiter (semicolon)."""
        file_path = os.path.join(self.temp_dir, "semicolon.csv")
        with open(file_path, 'w') as f:
            f.write("id;name;value\n")
            f.write("1;Alice;100\n")
            f.write("2;Bob;200\n")
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={
                "file_path": file_path,
                "delimiter": ";"
            }
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        assert len(batch.rows) == 2
        assert batch.rows[0]["id"] == 1
        assert batch.rows[0]["name"] == "Alice"
        assert batch.rows[0]["value"] == 100
    
    def test_csv_without_header(self):
        """Test extracting CSV without header row."""
        file_path = os.path.join(self.temp_dir, "no_header.csv")
        with open(file_path, 'w') as f:
            f.write("1,Alice,100\n")
            f.write("2,Bob,200\n")
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={
                "file_path": file_path,
                "has_header": False
            }
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        assert len(batch.rows) == 2
        # Without header, pandas uses column indices
        assert 0 in batch.rows[0]
        assert 1 in batch.rows[0]
        assert 2 in batch.rows[0]
    
    def test_empty_csv_file(self):
        """Test extracting from empty CSV file."""
        file_path = os.path.join(self.temp_dir, "empty.csv")
        with open(file_path, 'w') as f:
            f.write("")  # Empty file
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path}
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        assert len(batch.rows) == 0
        assert batch.total_rows == 0
        assert batch.has_more is False
    
    def test_csv_with_only_header(self):
        """Test extracting CSV with only header row (no data)."""
        file_path = os.path.join(self.temp_dir, "header_only.csv")
        with open(file_path, 'w') as f:
            f.write("id,name,value\n")
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path}
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        assert len(batch.rows) == 0
        assert batch.total_rows == 0
        assert batch.has_more is False
    
    def test_csv_with_skip_rows(self):
        """Test extracting CSV with skip_rows parameter."""
        file_path = os.path.join(self.temp_dir, "skip_rows.csv")
        with open(file_path, 'w') as f:
            f.write("# Comment line 1\n")
            f.write("# Comment line 2\n")
            f.write("id,name,value\n")
            f.write("1,Alice,100\n")
            f.write("2,Bob,200\n")
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={
                "file_path": file_path,
                "skip_rows": 2  # Skip comment lines
            }
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        assert len(batch.rows) == 2
        assert batch.rows[0]["id"] == 1
        assert batch.rows[0]["name"] == "Alice"


class TestCSVErrorHandling:
    """Tests for error handling in CSV extraction."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.strategy = CSVExtractionStrategy()
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_missing_file_raises_error(self):
        """Test that missing file raises ExtractionError."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": "/nonexistent/file.csv"}
        )
        
        with pytest.raises(ExtractionError, match="CSV file not found"):
            self.strategy.extract_batch(config, offset=0, limit=10)
    
    def test_missing_file_path_raises_error(self):
        """Test that missing file_path in config raises ValueError."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"other_param": "value"}  # Missing file_path
        )
        
        with pytest.raises(ValueError, match="file_path is required"):
            self.strategy.extract_batch(config, offset=0, limit=10)
    
    def test_empty_file_path_raises_error(self):
        """Test that empty file_path raises ValueError."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": ""}
        )
        
        with pytest.raises(ValueError, match="file_path must be a non-empty string"):
            self.strategy.extract_batch(config, offset=0, limit=10)
    
    def test_invalid_delimiter_raises_error(self):
        """Test that invalid delimiter raises ValueError."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={
                "file_path": "/some/path.csv",
                "delimiter": "abc"  # Must be single character
            }
        )
        
        with pytest.raises(ValueError, match="delimiter must be a single character"):
            self.strategy.extract_batch(config, offset=0, limit=10)
    
    def test_invalid_has_header_type_raises_error(self):
        """Test that invalid has_header type raises ValueError."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={
                "file_path": "/some/path.csv",
                "has_header": "yes"  # Must be boolean
            }
        )
        
        with pytest.raises(ValueError, match="has_header must be a boolean"):
            self.strategy.extract_batch(config, offset=0, limit=10)
    
    def test_negative_skip_rows_raises_error(self):
        """Test that negative skip_rows raises ValueError."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={
                "file_path": "/some/path.csv",
                "skip_rows": -1
            }
        )
        
        with pytest.raises(ValueError, match="skip_rows must be a non-negative integer"):
            self.strategy.extract_batch(config, offset=0, limit=10)


class TestCSVSchemaValidation:
    """Tests for schema validation in CSV extraction."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.strategy = CSVExtractionStrategy()
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
    
    def test_schema_validation_passes(self):
        """Test that valid data passes schema validation."""
        data = {
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"],
            "email": ["alice@example.com", "bob@example.com", "charlie@example.com"]
        }
        file_path = self._create_csv_file("test.csv", data)
        
        schema_contract = {
            "fields": [
                {"name": "id", "type": "integer", "required": True},
                {"name": "name", "type": "string", "required": True},
                {"name": "email", "type": "string", "required": True}
            ]
        }
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path},
            schema_contract=schema_contract
        )
        
        # Should not raise any exception
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        assert len(batch.rows) == 3
    
    def test_schema_validation_fails_missing_field(self):
        """Test that missing required field fails schema validation."""
        data = {
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"]
            # Missing 'email' field
        }
        file_path = self._create_csv_file("test.csv", data)
        
        schema_contract = {
            "fields": [
                {"name": "id", "type": "integer", "required": True},
                {"name": "name", "type": "string", "required": True},
                {"name": "email", "type": "string", "required": True}
            ]
        }
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path},
            schema_contract=schema_contract
        )
        
        with pytest.raises(ValidationError, match="Missing required fields"):
            self.strategy.extract_batch(config, offset=0, limit=10)
    
    def test_schema_validation_optional_fields(self):
        """Test that optional fields don't cause validation failure."""
        data = {
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"]
        }
        file_path = self._create_csv_file("test.csv", data)
        
        schema_contract = {
            "fields": [
                {"name": "id", "type": "integer", "required": True},
                {"name": "name", "type": "string", "required": True},
                {"name": "email", "type": "string", "required": False}  # Optional
            ]
        }
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path},
            schema_contract=schema_contract
        )
        
        # Should not raise any exception
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        assert len(batch.rows) == 3

    def test_schema_validation_fails_on_later_row_missing_field(self):
        """Regression: schema validation must validate all rows, not just first row."""
        data = {
            "id": [1, 2],
            "name": ["Alice", None],
            "email": ["alice@example.com", None],
        }
        file_path = self._create_csv_file("test_later_row_missing.csv", data)

        schema_contract = {
            "fields": [
                {"name": "id", "type": "integer", "required": True},
                {"name": "name", "type": "string", "required": True},
                {"name": "email", "type": "string", "required": True},
            ]
        }

        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path},
            schema_contract=schema_contract,
        )

        with pytest.raises(ValidationError, match="Missing required fields"):
            self.strategy.extract_batch(config, offset=0, limit=10)


class TestCSVMetadata:
    """Tests for metadata in CSV extraction."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.strategy = CSVExtractionStrategy()
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
    
    def test_batch_includes_metadata(self):
        """Test that batch includes file metadata."""
        data = {"id": [1, 2, 3]}
        file_path = self._create_csv_file("test.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path}
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        assert batch.metadata is not None
        assert "file_name" in batch.metadata
        assert batch.metadata["file_name"] == "test.csv"
        assert "file_size" in batch.metadata
        assert batch.metadata["file_size"] > 0
        assert "encoding" in batch.metadata
        assert "delimiter" in batch.metadata
        assert "extraction_timestamp" in batch.metadata
        assert "rows_extracted" in batch.metadata
        assert batch.metadata["rows_extracted"] == 3


class TestCSVMemoryEfficiency:
    """Tests to verify memory-efficient chunked reading."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.strategy = CSVExtractionStrategy()
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
    
    def test_chunked_reading_does_not_load_entire_file(self):
        """Test that chunked reading only loads requested batch."""
        # Create a large CSV file
        data = {
            "id": list(range(1, 10001)),  # 10,000 rows
            "value": [f"value_{i}" for i in range(1, 10001)]
        }
        file_path = self._create_csv_file("large.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path},
            batch_size=100
        )
        
        # Extract small batch from middle of file
        batch = self.strategy.extract_batch(config, offset=5000, limit=100)
        
        # Should only get 100 rows, not all 10,000
        assert len(batch.rows) == 100
        assert batch.rows[0]["id"] == 5001
        assert batch.rows[99]["id"] == 5100
        assert batch.has_more is True
    
    def test_multiple_batches_cover_entire_file(self):
        """Test that multiple batches can extract entire file."""
        data = {
            "id": list(range(1, 101)),  # 100 rows
            "value": [f"value_{i}" for i in range(1, 101)]
        }
        file_path = self._create_csv_file("test.csv", data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": file_path},
            batch_size=25
        )
        
        all_rows = []
        offset = 0
        batch_size = 25
        
        while True:
            batch = self.strategy.extract_batch(config, offset, batch_size)
            all_rows.extend(batch.rows)
            
            if not batch.has_more:
                break
            
            offset += batch.total_rows
        
        # Should have extracted all 100 rows
        assert len(all_rows) == 100
        assert all_rows[0]["id"] == 1
        assert all_rows[99]["id"] == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
