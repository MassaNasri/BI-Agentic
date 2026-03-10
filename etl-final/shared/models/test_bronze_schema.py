"""
Unit tests for Bronze Layer Schema
Tests schema generation, row validation, and deduplication key generation.
"""
import pytest
from datetime import datetime
from uuid import UUID
from .bronze_schema import BronzeTableSchema, BronzeRow, BronzeBatch


class TestBronzeTableSchema:
    """Test bronze table schema generation."""
    
    def test_table_name_generation(self):
        """Test that table names are correctly prefixed with 'bronze_'."""
        schema = BronzeTableSchema(source_name="customers")
        assert schema.table_name == "bronze_customers"
    
    def test_create_table_sql_structure(self):
        """Test that CREATE TABLE SQL has all required components."""
        schema = BronzeTableSchema(
            source_name="orders",
            data_columns={"order_id": "String", "customer_id": "String", "amount": "String"}
        )
        sql = schema.get_create_table_sql()
        
        # Check table name
        assert "bronze_orders" in sql
        
        # Check lineage columns
        assert "_row_id UUID DEFAULT generateUUIDv4()" in sql
        assert "_batch_id String" in sql
        assert "_source_id String" in sql
        assert "_extracted_at DateTime64(3)" in sql
        assert "_dedup_key String" in sql
        
        # Check data columns
        assert "order_id String" in sql
        assert "customer_id String" in sql
        assert "amount String" in sql
        
        # Check metadata columns
        assert "_file_name String" in sql
        assert "_file_size UInt64" in sql
        assert "_row_number UInt64" in sql
        
        # Check engine and partitioning
        assert "ENGINE = MergeTree()" in sql
        assert "PARTITION BY toYYYYMM(_extracted_at)" in sql
        assert "ORDER BY (_batch_id, _row_id)" in sql
        assert "index_granularity = 8192" in sql
    
    def test_custom_partitioning(self):
        """Test custom partitioning strategy."""
        schema = BronzeTableSchema(
            source_name="events",
            partition_by="toYYYYMMDD(_extracted_at)"
        )
        sql = schema.get_create_table_sql()
        assert "PARTITION BY toYYYYMMDD(_extracted_at)" in sql
    
    def test_custom_ordering(self):
        """Test custom ordering columns."""
        schema = BronzeTableSchema(
            source_name="logs",
            order_by=["_extracted_at", "_row_id"]
        )
        sql = schema.get_create_table_sql()
        assert "ORDER BY (_extracted_at, _row_id)" in sql


class TestBronzeRow:
    """Test bronze row data model."""
    
    def test_row_creation(self):
        """Test basic row creation with required fields."""
        row = BronzeRow(
            batch_id="batch_001",
            source_id="customers",
            extracted_at=datetime(2024, 1, 15, 10, 30, 0),
            data={"id": "1", "name": "John Doe", "email": "john@example.com"}
        )
        
        assert row.batch_id == "batch_001"
        assert row.source_id == "customers"
        assert isinstance(row.row_id, UUID)
        assert len(row.dedup_key) == 64  # SHA256 hash length
    
    def test_dedup_key_generation(self):
        """Test that deduplication key is deterministic."""
        row1 = BronzeRow(
            batch_id="batch_001",
            source_id="customers",
            extracted_at=datetime(2024, 1, 15, 10, 30, 0),
            data={"id": "1", "name": "John Doe"}
        )
        
        row2 = BronzeRow(
            batch_id="batch_001",
            source_id="customers",
            extracted_at=datetime(2024, 1, 15, 10, 30, 0),
            data={"id": "1", "name": "John Doe"}
        )
        
        # Same data should produce same dedup key
        assert row1.dedup_key == row2.dedup_key
    
    def test_dedup_key_uniqueness(self):
        """Test that different data produces different dedup keys."""
        row1 = BronzeRow(
            batch_id="batch_001",
            source_id="customers",
            extracted_at=datetime(2024, 1, 15, 10, 30, 0),
            data={"id": "1", "name": "John Doe"}
        )
        
        row2 = BronzeRow(
            batch_id="batch_001",
            source_id="customers",
            extracted_at=datetime(2024, 1, 15, 10, 30, 0),
            data={"id": "2", "name": "Jane Smith"}
        )
        
        # Different data should produce different dedup keys
        assert row1.dedup_key != row2.dedup_key
    
    def test_to_dict_conversion(self):
        """Test conversion to dictionary for ClickHouse insertion."""
        row = BronzeRow(
            batch_id="batch_001",
            source_id="customers",
            extracted_at=datetime(2024, 1, 15, 10, 30, 0),
            data={"id": "1", "name": "John Doe"},
            file_name="customers.csv",
            file_size=1024,
            row_number=1
        )
        
        row_dict = row.to_dict()
        
        # Check lineage columns
        assert "_row_id" in row_dict
        assert row_dict["_batch_id"] == "batch_001"
        assert row_dict["_source_id"] == "customers"
        assert row_dict["_extracted_at"] == datetime(2024, 1, 15, 10, 30, 0)
        assert "_dedup_key" in row_dict
        
        # Check data columns
        assert row_dict["id"] == "1"
        assert row_dict["name"] == "John Doe"
        
        # Check metadata columns
        assert row_dict["_file_name"] == "customers.csv"
        assert row_dict["_file_size"] == 1024
        assert row_dict["_row_number"] == 1
    
    def test_validation_success(self):
        """Test validation passes for valid row."""
        row = BronzeRow(
            batch_id="batch_001",
            source_id="customers",
            extracted_at=datetime(2024, 1, 15, 10, 30, 0),
            data={"id": "1", "name": "John Doe"}
        )
        
        is_valid, errors = row.validate()
        assert is_valid
        assert len(errors) == 0
    
    def test_validation_missing_batch_id(self):
        """Test validation fails when batch_id is missing."""
        row = BronzeRow(
            batch_id="",
            source_id="customers",
            extracted_at=datetime(2024, 1, 15, 10, 30, 0),
            data={"id": "1"}
        )
        
        is_valid, errors = row.validate()
        assert not is_valid
        assert "batch_id is required" in errors
    
    def test_validation_missing_source_id(self):
        """Test validation fails when source_id is missing."""
        row = BronzeRow(
            batch_id="batch_001",
            source_id="",
            extracted_at=datetime(2024, 1, 15, 10, 30, 0),
            data={"id": "1"}
        )
        
        is_valid, errors = row.validate()
        assert not is_valid
        assert "source_id is required" in errors
    
    def test_validation_empty_data(self):
        """Test validation fails when data is empty."""
        row = BronzeRow(
            batch_id="batch_001",
            source_id="customers",
            extracted_at=datetime(2024, 1, 15, 10, 30, 0),
            data={}
        )
        
        is_valid, errors = row.validate()
        assert not is_valid
        assert "data cannot be empty" in errors
    
    def test_validation_non_string_data(self):
        """Test validation fails when data contains non-string values."""
        row = BronzeRow(
            batch_id="batch_001",
            source_id="customers",
            extracted_at=datetime(2024, 1, 15, 10, 30, 0),
            data={"id": "1", "age": 25}  # age is int, should be string
        )
        
        is_valid, errors = row.validate()
        assert not is_valid
        assert any("must be string" in err for err in errors)


class TestBronzeBatch:
    """Test bronze batch operations."""
    
    def test_batch_creation(self):
        """Test basic batch creation."""
        schema = BronzeTableSchema(
            source_name="customers",
            data_columns={"id": "String", "name": "String"}
        )
        
        rows = [
            BronzeRow(
                batch_id="batch_001",
                source_id="customers",
                extracted_at=datetime(2024, 1, 15, 10, 30, 0),
                data={"id": "1", "name": "John Doe"}
            ),
            BronzeRow(
                batch_id="batch_001",
                source_id="customers",
                extracted_at=datetime(2024, 1, 15, 10, 30, 0),
                data={"id": "2", "name": "Jane Smith"}
            )
        ]
        
        batch = BronzeBatch(
            batch_id="batch_001",
            source_id="customers",
            rows=rows,
            schema=schema
        )
        
        assert batch.batch_id == "batch_001"
        assert len(batch.rows) == 2
    
    def test_batch_validation_success(self):
        """Test batch validation passes for valid batch."""
        schema = BronzeTableSchema(source_name="customers")
        
        rows = [
            BronzeRow(
                batch_id="batch_001",
                source_id="customers",
                extracted_at=datetime(2024, 1, 15, 10, 30, 0),
                data={"id": "1", "name": "John Doe"}
            )
        ]
        
        batch = BronzeBatch(
            batch_id="batch_001",
            source_id="customers",
            rows=rows,
            schema=schema
        )
        
        is_valid, errors = batch.validate()
        assert is_valid
        assert len(errors) == 0
    
    def test_batch_validation_empty_batch(self):
        """Test batch validation fails for empty batch."""
        schema = BronzeTableSchema(source_name="customers")
        
        batch = BronzeBatch(
            batch_id="batch_001",
            source_id="customers",
            rows=[],
            schema=schema
        )
        
        is_valid, errors = batch.validate()
        assert not is_valid
        assert "Batch cannot be empty" in errors
    
    def test_batch_validation_inconsistent_batch_ids(self):
        """Test batch validation fails when rows have different batch_ids."""
        schema = BronzeTableSchema(source_name="customers")
        
        rows = [
            BronzeRow(
                batch_id="batch_001",
                source_id="customers",
                extracted_at=datetime(2024, 1, 15, 10, 30, 0),
                data={"id": "1", "name": "John Doe"}
            ),
            BronzeRow(
                batch_id="batch_002",  # Different batch_id
                source_id="customers",
                extracted_at=datetime(2024, 1, 15, 10, 30, 0),
                data={"id": "2", "name": "Jane Smith"}
            )
        ]
        
        batch = BronzeBatch(
            batch_id="batch_001",
            source_id="customers",
            rows=rows,
            schema=schema
        )
        
        is_valid, errors = batch.validate()
        assert not is_valid
        assert any("Inconsistent batch_ids" in err for err in errors)
    
    def test_to_dicts_conversion(self):
        """Test conversion of batch to list of dictionaries."""
        schema = BronzeTableSchema(source_name="customers")
        
        rows = [
            BronzeRow(
                batch_id="batch_001",
                source_id="customers",
                extracted_at=datetime(2024, 1, 15, 10, 30, 0),
                data={"id": "1", "name": "John Doe"}
            ),
            BronzeRow(
                batch_id="batch_001",
                source_id="customers",
                extracted_at=datetime(2024, 1, 15, 10, 30, 0),
                data={"id": "2", "name": "Jane Smith"}
            )
        ]
        
        batch = BronzeBatch(
            batch_id="batch_001",
            source_id="customers",
            rows=rows,
            schema=schema
        )
        
        dicts = batch.to_dicts()
        assert len(dicts) == 2
        assert all("_row_id" in d for d in dicts)
        assert all("_batch_id" in d for d in dicts)
    
    def test_get_dedup_keys(self):
        """Test extraction of deduplication keys from batch."""
        schema = BronzeTableSchema(source_name="customers")
        
        rows = [
            BronzeRow(
                batch_id="batch_001",
                source_id="customers",
                extracted_at=datetime(2024, 1, 15, 10, 30, 0),
                data={"id": "1", "name": "John Doe"}
            ),
            BronzeRow(
                batch_id="batch_001",
                source_id="customers",
                extracted_at=datetime(2024, 1, 15, 10, 30, 0),
                data={"id": "2", "name": "Jane Smith"}
            )
        ]
        
        batch = BronzeBatch(
            batch_id="batch_001",
            source_id="customers",
            rows=rows,
            schema=schema
        )
        
        dedup_keys = batch.get_dedup_keys()
        assert len(dedup_keys) == 2
        assert all(len(key) == 64 for key in dedup_keys)  # SHA256 hash length
