"""
Unit tests for Silver Layer Schema
Tests schema definition, validation, and quality metrics.
"""
import pytest
from datetime import datetime
from uuid import uuid4, UUID
from .silver_schema import (
    DataType,
    SilverColumnDefinition,
    SilverTableSchema,
    QualityMetrics,
    SilverRow,
    SilverBatch
)


class TestDataType:
    """Test DataType enum."""
    
    def test_data_type_values(self):
        """Test that DataType enum has expected values."""
        assert DataType.STRING.value == "String"
        assert DataType.INT64.value == "Int64"
        assert DataType.FLOAT64.value == "Float64"
        assert DataType.BOOLEAN.value == "Bool"
        assert DataType.DATETIME64.value == "DateTime64(3)"
        assert DataType.ARRAY_STRING.value == "Array(String)"


class TestSilverColumnDefinition:
    """Test SilverColumnDefinition class."""
    
    def test_basic_column_definition(self):
        """Test creating a basic column definition."""
        col = SilverColumnDefinition(
            name="customer_id",
            data_type=DataType.INT64,
            comment="Customer identifier"
        )
        
        assert col.name == "customer_id"
        assert col.data_type == DataType.INT64
        assert col.nullable is False
        assert col.default_value is None
        assert col.comment == "Customer identifier"
    
    def test_nullable_column_sql(self):
        """Test SQL generation for nullable column."""
        col = SilverColumnDefinition(
            name="email",
            data_type=DataType.STRING,
            nullable=True
        )
        
        sql = col.to_sql()
        assert "email" in sql
        assert "Nullable(String)" in sql
    
    def test_column_with_default_sql(self):
        """Test SQL generation for column with default value."""
        col = SilverColumnDefinition(
            name="status",
            data_type=DataType.STRING,
            default_value="'active'"
        )
        
        sql = col.to_sql()
        assert "status" in sql
        assert "DEFAULT 'active'" in sql
    
    def test_column_with_comment_sql(self):
        """Test SQL generation for column with comment."""
        col = SilverColumnDefinition(
            name="amount",
            data_type=DataType.FLOAT64,
            comment="Transaction amount"
        )
        
        sql = col.to_sql()
        assert "amount" in sql
        assert "COMMENT 'Transaction amount'" in sql


class TestSilverTableSchema:
    """Test SilverTableSchema class."""
    
    def test_table_name_generation(self):
        """Test that table name is generated correctly."""
        schema = SilverTableSchema(source_name="customers")
        assert schema.table_name == "silver_customers"
    
    def test_create_table_sql_structure(self):
        """Test that CREATE TABLE SQL has correct structure."""
        schema = SilverTableSchema(
            source_name="orders",
            data_columns=[
                SilverColumnDefinition("order_id", DataType.INT64),
                SilverColumnDefinition("amount", DataType.FLOAT64),
                SilverColumnDefinition("status", DataType.STRING)
            ]
        )
        
        sql = schema.get_create_table_sql()
        
        # Check table name
        assert "silver_orders" in sql
        
        # Check lineage columns
        assert "_row_id UUID" in sql
        assert "_bronze_row_id UUID" in sql
        assert "_batch_id String" in sql
        assert "_cleaned_at DateTime64(3)" in sql
        assert "_cleaning_version String" in sql
        
        # Check data columns
        assert "order_id Int64" in sql
        assert "amount Float64" in sql
        assert "status String" in sql
        
        # Check quality columns
        assert "_quality_score Float32" in sql
        assert "_applied_rules Array(String)" in sql
        assert "_warnings Array(String)" in sql
        assert "_completeness_score Float32" in sql
        assert "_validity_score Float32" in sql
        
        # Check engine and partitioning
        assert "ENGINE = MergeTree()" in sql
        assert "PARTITION BY toYYYYMM(_cleaned_at)" in sql
        assert "ORDER BY (_batch_id, _row_id)" in sql
    
    def test_create_table_sql_with_indexes(self):
        """Test that indexes are included in CREATE TABLE SQL."""
        schema = SilverTableSchema(
            source_name="products",
            data_columns=[
                SilverColumnDefinition("product_id", DataType.INT64)
            ]
        )
        
        sql = schema.get_create_table_sql()
        
        # Check default indexes
        assert "INDEX idx_bronze_row_id" in sql
        assert "INDEX idx_quality_score" in sql
        assert "INDEX idx_cleaned_at" in sql
    
    def test_custom_partitioning(self):
        """Test custom partitioning strategy."""
        schema = SilverTableSchema(
            source_name="events",
            partition_by="toYYYYMMDD(_cleaned_at)"
        )
        
        sql = schema.get_create_table_sql()
        assert "PARTITION BY toYYYYMMDD(_cleaned_at)" in sql
    
    def test_custom_ordering(self):
        """Test custom ordering columns."""
        schema = SilverTableSchema(
            source_name="logs",
            order_by=["_cleaned_at", "_row_id"]
        )
        
        sql = schema.get_create_table_sql()
        assert "ORDER BY (_cleaned_at, _row_id)" in sql


class TestQualityMetrics:
    """Test QualityMetrics class."""
    
    def test_default_quality_metrics(self):
        """Test default quality metrics values."""
        metrics = QualityMetrics()
        
        assert metrics.completeness_score == 1.0
        assert metrics.validity_score == 1.0
        assert metrics.quality_score == 1.0
        assert metrics.applied_rules == []
        assert metrics.warnings == []
    
    def test_calculate_overall_score_default_weights(self):
        """Test overall score calculation with default weights."""
        metrics = QualityMetrics(
            completeness_score=0.8,
            validity_score=0.9
        )
        
        score = metrics.calculate_overall_score()
        
        # Default weights: 0.4 * completeness + 0.6 * validity
        expected = 0.4 * 0.8 + 0.6 * 0.9
        assert abs(score - expected) < 0.001
        assert abs(metrics.quality_score - expected) < 0.001
    
    def test_calculate_overall_score_custom_weights(self):
        """Test overall score calculation with custom weights."""
        metrics = QualityMetrics(
            completeness_score=0.7,
            validity_score=0.8
        )
        
        score = metrics.calculate_overall_score(
            completeness_weight=0.5,
            validity_weight=0.5
        )
        
        expected = 0.5 * 0.7 + 0.5 * 0.8
        assert abs(score - expected) < 0.001
    
    def test_calculate_overall_score_invalid_weights(self):
        """Test that invalid weights raise error."""
        metrics = QualityMetrics()
        
        with pytest.raises(ValueError, match="Weights must sum to 1.0"):
            metrics.calculate_overall_score(
                completeness_weight=0.5,
                validity_weight=0.6
            )
    
    def test_validate_valid_metrics(self):
        """Test validation of valid quality metrics."""
        metrics = QualityMetrics(
            completeness_score=0.85,
            validity_score=0.92,
            quality_score=0.89
        )
        
        is_valid, errors = metrics.validate()
        assert is_valid
        assert errors == []
    
    def test_validate_invalid_completeness_score(self):
        """Test validation catches invalid completeness score."""
        metrics = QualityMetrics(completeness_score=1.5)
        
        is_valid, errors = metrics.validate()
        assert not is_valid
        assert any("completeness_score" in err for err in errors)
    
    def test_validate_invalid_validity_score(self):
        """Test validation catches invalid validity score."""
        metrics = QualityMetrics(validity_score=-0.1)
        
        is_valid, errors = metrics.validate()
        assert not is_valid
        assert any("validity_score" in err for err in errors)
    
    def test_validate_invalid_quality_score(self):
        """Test validation catches invalid quality score."""
        metrics = QualityMetrics(quality_score=2.0)
        
        is_valid, errors = metrics.validate()
        assert not is_valid
        assert any("quality_score" in err for err in errors)


class TestSilverRow:
    """Test SilverRow class."""
    
    def test_create_silver_row(self):
        """Test creating a silver row."""
        bronze_row_id = uuid4()
        cleaned_at = datetime.now()
        
        row = SilverRow(
            bronze_row_id=bronze_row_id,
            batch_id="batch_123",
            cleaned_at=cleaned_at,
            cleaning_version="v1.0",
            data={"customer_id": 42, "name": "John Doe"},
            quality_metrics=QualityMetrics()
        )
        
        assert row.bronze_row_id == bronze_row_id
        assert row.batch_id == "batch_123"
        assert row.cleaned_at == cleaned_at
        assert row.cleaning_version == "v1.0"
        assert row.data == {"customer_id": 42, "name": "John Doe"}
        assert isinstance(row.row_id, UUID)
    
    def test_to_dict(self):
        """Test converting silver row to dictionary."""
        bronze_row_id = uuid4()
        cleaned_at = datetime.now()
        
        metrics = QualityMetrics(
            completeness_score=0.9,
            validity_score=0.95,
            quality_score=0.93,
            applied_rules=["trim_strings", "validate_email"],
            warnings=["Missing optional field"]
        )
        
        row = SilverRow(
            bronze_row_id=bronze_row_id,
            batch_id="batch_456",
            cleaned_at=cleaned_at,
            cleaning_version="v2.0",
            data={"order_id": 100, "amount": 99.99},
            quality_metrics=metrics
        )
        
        row_dict = row.to_dict()
        
        # Check lineage columns
        assert "_row_id" in row_dict
        assert row_dict["_bronze_row_id"] == str(bronze_row_id)
        assert row_dict["_batch_id"] == "batch_456"
        assert row_dict["_cleaned_at"] == cleaned_at
        assert row_dict["_cleaning_version"] == "v2.0"
        
        # Check quality columns
        assert row_dict["_quality_score"] == 0.93
        assert row_dict["_applied_rules"] == ["trim_strings", "validate_email"]
        assert row_dict["_warnings"] == ["Missing optional field"]
        assert row_dict["_completeness_score"] == 0.9
        assert row_dict["_validity_score"] == 0.95
        
        # Check data columns
        assert row_dict["order_id"] == 100
        assert row_dict["amount"] == 99.99
    
    def test_validate_valid_row(self):
        """Test validation of valid silver row."""
        schema = SilverTableSchema(
            source_name="test",
            data_columns=[
                SilverColumnDefinition("id", DataType.INT64),
                SilverColumnDefinition("name", DataType.STRING)
            ]
        )
        
        row = SilverRow(
            bronze_row_id=uuid4(),
            batch_id="batch_789",
            cleaned_at=datetime.now(),
            cleaning_version="v1.0",
            data={"id": 1, "name": "Test"},
            quality_metrics=QualityMetrics()
        )
        
        is_valid, errors = row.validate(schema)
        assert is_valid
        assert errors == []
    
    def test_validate_missing_required_field(self):
        """Test validation catches missing required fields."""
        schema = SilverTableSchema(
            source_name="test",
            data_columns=[
                SilverColumnDefinition("id", DataType.INT64, nullable=False)
            ]
        )
        
        row = SilverRow(
            bronze_row_id=uuid4(),
            batch_id="batch_999",
            cleaned_at=datetime.now(),
            cleaning_version="v1.0",
            data={},  # Missing 'id'
            quality_metrics=QualityMetrics()
        )
        
        is_valid, errors = row.validate(schema)
        assert not is_valid
        assert any("id" in err and "missing" in err.lower() for err in errors)
    
    def test_validate_null_in_non_nullable_column(self):
        """Test validation catches NULL in non-nullable column."""
        schema = SilverTableSchema(
            source_name="test",
            data_columns=[
                SilverColumnDefinition("status", DataType.STRING, nullable=False)
            ]
        )
        
        row = SilverRow(
            bronze_row_id=uuid4(),
            batch_id="batch_111",
            cleaned_at=datetime.now(),
            cleaning_version="v1.0",
            data={"status": None},
            quality_metrics=QualityMetrics()
        )
        
        is_valid, errors = row.validate(schema)
        assert not is_valid
        assert any("status" in err and "NULL" in err for err in errors)
    
    def test_validate_extra_column(self):
        """Test validation catches extra columns not in schema."""
        schema = SilverTableSchema(
            source_name="test",
            data_columns=[
                SilverColumnDefinition("id", DataType.INT64)
            ]
        )
        
        row = SilverRow(
            bronze_row_id=uuid4(),
            batch_id="batch_222",
            cleaned_at=datetime.now(),
            cleaning_version="v1.0",
            data={"id": 1, "extra_field": "unexpected"},
            quality_metrics=QualityMetrics()
        )
        
        is_valid, errors = row.validate(schema)
        assert not is_valid
        assert any("extra_field" in err and "not in schema" in err for err in errors)


class TestSilverBatch:
    """Test SilverBatch class."""
    
    def test_create_silver_batch(self):
        """Test creating a silver batch."""
        schema = SilverTableSchema(
            source_name="test",
            data_columns=[
                SilverColumnDefinition("id", DataType.INT64)
            ]
        )
        
        rows = [
            SilverRow(
                bronze_row_id=uuid4(),
                batch_id="batch_333",
                cleaned_at=datetime.now(),
                cleaning_version="v1.0",
                data={"id": i},
                quality_metrics=QualityMetrics()
            )
            for i in range(5)
        ]
        
        batch = SilverBatch(
            batch_id="batch_333",
            source_id="source_1",
            rows=rows,
            schema=schema
        )
        
        assert batch.batch_id == "batch_333"
        assert batch.source_id == "source_1"
        assert len(batch.rows) == 5
        assert batch.schema == schema
    
    def test_validate_valid_batch(self):
        """Test validation of valid batch."""
        schema = SilverTableSchema(
            source_name="test",
            data_columns=[
                SilverColumnDefinition("value", DataType.INT64)
            ]
        )
        
        rows = [
            SilverRow(
                bronze_row_id=uuid4(),
                batch_id="batch_444",
                cleaned_at=datetime.now(),
                cleaning_version="v1.0",
                data={"value": i},
                quality_metrics=QualityMetrics()
            )
            for i in range(3)
        ]
        
        batch = SilverBatch(
            batch_id="batch_444",
            source_id="source_2",
            rows=rows,
            schema=schema
        )
        
        is_valid, errors = batch.validate()
        assert is_valid
        assert errors == []
    
    def test_validate_empty_batch(self):
        """Test validation catches empty batch."""
        schema = SilverTableSchema(source_name="test")
        
        batch = SilverBatch(
            batch_id="batch_555",
            source_id="source_3",
            rows=[],
            schema=schema
        )
        
        is_valid, errors = batch.validate()
        assert not is_valid
        assert any("empty" in err.lower() for err in errors)
    
    def test_validate_inconsistent_batch_ids(self):
        """Test validation catches inconsistent batch IDs."""
        schema = SilverTableSchema(
            source_name="test",
            data_columns=[
                SilverColumnDefinition("id", DataType.INT64)
            ]
        )
        
        rows = [
            SilverRow(
                bronze_row_id=uuid4(),
                batch_id="batch_666",
                cleaned_at=datetime.now(),
                cleaning_version="v1.0",
                data={"id": 1},
                quality_metrics=QualityMetrics()
            ),
            SilverRow(
                bronze_row_id=uuid4(),
                batch_id="batch_777",  # Different batch_id!
                cleaned_at=datetime.now(),
                cleaning_version="v1.0",
                data={"id": 2},
                quality_metrics=QualityMetrics()
            )
        ]
        
        batch = SilverBatch(
            batch_id="batch_666",
            source_id="source_4",
            rows=rows,
            schema=schema
        )
        
        is_valid, errors = batch.validate()
        assert not is_valid
        assert any("batch_id" in err.lower() for err in errors)
    
    def test_to_dicts(self):
        """Test converting batch to list of dictionaries."""
        schema = SilverTableSchema(
            source_name="test",
            data_columns=[
                SilverColumnDefinition("num", DataType.INT64)
            ]
        )
        
        rows = [
            SilverRow(
                bronze_row_id=uuid4(),
                batch_id="batch_888",
                cleaned_at=datetime.now(),
                cleaning_version="v1.0",
                data={"num": i},
                quality_metrics=QualityMetrics()
            )
            for i in range(3)
        ]
        
        batch = SilverBatch(
            batch_id="batch_888",
            source_id="source_5",
            rows=rows,
            schema=schema
        )
        
        dicts = batch.to_dicts()
        
        assert len(dicts) == 3
        assert all(isinstance(d, dict) for d in dicts)
        assert all("_row_id" in d for d in dicts)
        assert all("num" in d for d in dicts)
    
    def test_get_quality_summary(self):
        """Test getting quality summary for batch."""
        schema = SilverTableSchema(
            source_name="test",
            data_columns=[
                SilverColumnDefinition("id", DataType.INT64)
            ]
        )
        
        rows = [
            SilverRow(
                bronze_row_id=uuid4(),
                batch_id="batch_999",
                cleaned_at=datetime.now(),
                cleaning_version="v1.0",
                data={"id": 1},
                quality_metrics=QualityMetrics(
                    completeness_score=0.9,
                    validity_score=0.95,
                    quality_score=0.93
                )
            ),
            SilverRow(
                bronze_row_id=uuid4(),
                batch_id="batch_999",
                cleaned_at=datetime.now(),
                cleaning_version="v1.0",
                data={"id": 2},
                quality_metrics=QualityMetrics(
                    completeness_score=0.8,
                    validity_score=0.85,
                    quality_score=0.83,
                    warnings=["Warning 1"]
                )
            )
        ]
        
        batch = SilverBatch(
            batch_id="batch_999",
            source_id="source_6",
            rows=rows,
            schema=schema
        )
        
        summary = batch.get_quality_summary()
        
        assert summary["total_rows"] == 2
        assert abs(summary["avg_quality_score"] - 0.88) < 0.01
        assert abs(summary["avg_completeness_score"] - 0.85) < 0.01
        assert abs(summary["avg_validity_score"] - 0.90) < 0.01
        assert summary["rows_with_warnings"] == 1
        assert abs(summary["warning_rate"] - 0.5) < 0.01
    
    def test_get_quality_summary_empty_batch(self):
        """Test quality summary for empty batch."""
        schema = SilverTableSchema(source_name="test")
        
        batch = SilverBatch(
            batch_id="batch_000",
            source_id="source_7",
            rows=[],
            schema=schema
        )
        
        summary = batch.get_quality_summary()
        
        assert summary["total_rows"] == 0
        assert summary["avg_quality_score"] == 0.0
        assert summary["avg_completeness_score"] == 0.0
        assert summary["avg_validity_score"] == 0.0
        assert summary["rows_with_warnings"] == 0
