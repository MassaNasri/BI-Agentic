"""
Unit tests for silver table creation script.

Tests cover:
- Table creation from schema objects
- Table creation from JSON files
- Multiple table creation
- Table existence checking
- Schema retrieval
- Error handling
"""
import pytest
import json
import tempfile
import os
from unittest.mock import Mock, MagicMock, patch
from clickhouse_driver.errors import Error as ClickHouseError

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.create_silver_tables import SilverTableCreator
from models.silver_schema import (
    SilverTableSchema,
    SilverColumnDefinition,
    DataType
)


@pytest.fixture
def mock_client():
    """Create a mock ClickHouse client."""
    client = Mock()
    client.execute = Mock()
    return client


@pytest.fixture
def silver_creator(mock_client):
    """Create a SilverTableCreator with mock client."""
    return SilverTableCreator(client=mock_client)


@pytest.fixture
def sample_schema():
    """Create a sample silver table schema."""
    return SilverTableSchema(
        source_name="customers",
        data_columns=[
            SilverColumnDefinition(
                name="customer_id",
                data_type=DataType.INT64,
                nullable=False,
                comment="Customer identifier"
            ),
            SilverColumnDefinition(
                name="email",
                data_type=DataType.STRING,
                nullable=False,
                comment="Customer email"
            ),
            SilverColumnDefinition(
                name="age",
                data_type=DataType.INT32,
                nullable=True,
                comment="Customer age"
            )
        ]
    )


class TestSilverTableCreation:
    """Test silver table creation functionality."""
    
    def test_create_table_from_schema_success(self, silver_creator, mock_client, sample_schema):
        """Test successful table creation from schema object."""
        # Arrange
        mock_client.execute.return_value = None
        
        # Act
        result = silver_creator.create_table_from_schema(sample_schema)
        
        # Assert
        assert result is True
        assert mock_client.execute.called
        
        # Verify SQL contains expected elements
        call_args = mock_client.execute.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS silver_customers" in call_args
        assert "_row_id UUID" in call_args
        assert "_bronze_row_id UUID" in call_args
        assert "_quality_score Float32" in call_args
        assert "customer_id Int64" in call_args
        assert "email String" in call_args
        assert "age Nullable(Int32)" in call_args
    
    def test_create_table_from_schema_clickhouse_error(self, silver_creator, mock_client, sample_schema):
        """Test table creation with ClickHouse error."""
        # Arrange
        mock_client.execute.side_effect = ClickHouseError("Table already exists")
        
        # Act
        result = silver_creator.create_table_from_schema(sample_schema)
        
        # Assert
        assert result is False
    
    def test_create_table_from_schema_generic_error(self, silver_creator, mock_client, sample_schema):
        """Test table creation with generic error."""
        # Arrange
        mock_client.execute.side_effect = Exception("Connection failed")
        
        # Act
        result = silver_creator.create_table_from_schema(sample_schema)
        
        # Assert
        assert result is False
    
    def test_create_table_with_all_data_types(self, silver_creator, mock_client):
        """Test table creation with all supported data types."""
        # Arrange
        schema = SilverTableSchema(
            source_name="test_types",
            data_columns=[
                SilverColumnDefinition(name="col_string", data_type=DataType.STRING),
                SilverColumnDefinition(name="col_int8", data_type=DataType.INT8),
                SilverColumnDefinition(name="col_int16", data_type=DataType.INT16),
                SilverColumnDefinition(name="col_int32", data_type=DataType.INT32),
                SilverColumnDefinition(name="col_int64", data_type=DataType.INT64),
                SilverColumnDefinition(name="col_uint8", data_type=DataType.UINT8),
                SilverColumnDefinition(name="col_uint16", data_type=DataType.UINT16),
                SilverColumnDefinition(name="col_uint32", data_type=DataType.UINT32),
                SilverColumnDefinition(name="col_uint64", data_type=DataType.UINT64),
                SilverColumnDefinition(name="col_float32", data_type=DataType.FLOAT32),
                SilverColumnDefinition(name="col_float64", data_type=DataType.FLOAT64),
                SilverColumnDefinition(name="col_bool", data_type=DataType.BOOLEAN),
                SilverColumnDefinition(name="col_date", data_type=DataType.DATE),
                SilverColumnDefinition(name="col_datetime", data_type=DataType.DATETIME),
                SilverColumnDefinition(name="col_datetime64", data_type=DataType.DATETIME64),
                SilverColumnDefinition(name="col_uuid", data_type=DataType.UUID_TYPE),
                SilverColumnDefinition(name="col_array_string", data_type=DataType.ARRAY_STRING),
                SilverColumnDefinition(name="col_array_int64", data_type=DataType.ARRAY_INT64),
                SilverColumnDefinition(name="col_array_float64", data_type=DataType.ARRAY_FLOAT64),
            ]
        )
        
        # Act
        result = silver_creator.create_table_from_schema(schema)
        
        # Assert
        assert result is True
        call_args = mock_client.execute.call_args[0][0]
        
        # Verify all types are present
        assert "col_string String" in call_args
        assert "col_int8 Int8" in call_args
        assert "col_int16 Int16" in call_args
        assert "col_int32 Int32" in call_args
        assert "col_int64 Int64" in call_args
        assert "col_uint8 UInt8" in call_args
        assert "col_uint16 UInt16" in call_args
        assert "col_uint32 UInt32" in call_args
        assert "col_uint64 UInt64" in call_args
        assert "col_float32 Float32" in call_args
        assert "col_float64 Float64" in call_args
        assert "col_bool Bool" in call_args
        assert "col_date Date" in call_args
        assert "col_datetime DateTime" in call_args
        assert "col_datetime64 DateTime64(3)" in call_args
        assert "col_uuid UUID" in call_args
        assert "col_array_string Array(String)" in call_args
        assert "col_array_int64 Array(Int64)" in call_args
        assert "col_array_float64 Array(Float64)" in call_args


class TestJSONSchemaLoading:
    """Test loading schemas from JSON files."""
    
    def test_create_table_from_json_success(self, silver_creator, mock_client):
        """Test successful table creation from JSON file."""
        # Arrange
        schema_dict = {
            "source_name": "orders",
            "data_columns": [
                {
                    "name": "order_id",
                    "data_type": "INT64",
                    "nullable": False,
                    "comment": "Order identifier"
                },
                {
                    "name": "total_amount",
                    "data_type": "FLOAT64",
                    "nullable": False,
                    "comment": "Total order amount"
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(schema_dict, f)
            temp_path = f.name
        
        try:
            # Act
            result = silver_creator.create_table_from_json(temp_path)
            
            # Assert
            assert result is True
            assert mock_client.execute.called
            
            call_args = mock_client.execute.call_args[0][0]
            assert "silver_orders" in call_args
            assert "order_id Int64" in call_args
            assert "total_amount Float64" in call_args
        finally:
            os.unlink(temp_path)
    
    def test_create_table_from_json_file_not_found(self, silver_creator):
        """Test table creation with non-existent JSON file."""
        # Act
        result = silver_creator.create_table_from_json("nonexistent.json")
        
        # Assert
        assert result is False
    
    def test_create_table_from_json_invalid_json(self, silver_creator):
        """Test table creation with invalid JSON."""
        # Arrange
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{ invalid json }")
            temp_path = f.name
        
        try:
            # Act
            result = silver_creator.create_table_from_json(temp_path)
            
            # Assert
            assert result is False
        finally:
            os.unlink(temp_path)
    
    def test_create_table_from_json_missing_source_name(self, silver_creator):
        """Test table creation with missing source_name."""
        # Arrange
        schema_dict = {
            "data_columns": [
                {"name": "col1", "data_type": "STRING"}
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(schema_dict, f)
            temp_path = f.name
        
        try:
            # Act
            result = silver_creator.create_table_from_json(temp_path)
            
            # Assert
            assert result is False
        finally:
            os.unlink(temp_path)
    
    def test_create_table_from_json_with_custom_settings(self, silver_creator, mock_client):
        """Test table creation with custom partitioning and settings."""
        # Arrange
        schema_dict = {
            "source_name": "events",
            "data_columns": [
                {"name": "event_id", "data_type": "INT64", "nullable": False}
            ],
            "partition_by": "toYYYYMMDD(_cleaned_at)",
            "order_by": ["_cleaned_at", "_row_id"],
            "settings": {"index_granularity": 4096}
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(schema_dict, f)
            temp_path = f.name
        
        try:
            # Act
            result = silver_creator.create_table_from_json(temp_path)
            
            # Assert
            assert result is True
            call_args = mock_client.execute.call_args[0][0]
            assert "PARTITION BY toYYYYMMDD(_cleaned_at)" in call_args
            assert "ORDER BY (_cleaned_at, _row_id)" in call_args
            assert "index_granularity = 4096" in call_args
        finally:
            os.unlink(temp_path)


class TestMultipleTableCreation:
    """Test creating multiple tables at once."""
    
    def test_create_multiple_tables_success(self, silver_creator, mock_client):
        """Test successful creation of multiple tables."""
        # Arrange
        schema_definitions = [
            {
                "source_name": "customers",
                "data_columns": [
                    {"name": "customer_id", "data_type": "INT64", "nullable": False}
                ]
            },
            {
                "source_name": "orders",
                "data_columns": [
                    {"name": "order_id", "data_type": "INT64", "nullable": False}
                ]
            }
        ]
        
        # Act
        results = silver_creator.create_multiple_tables(schema_definitions)
        
        # Assert
        assert len(results) == 2
        assert results["customers"] is True
        assert results["orders"] is True
        assert mock_client.execute.call_count == 2
    
    def test_create_multiple_tables_partial_failure(self, silver_creator, mock_client):
        """Test multiple table creation with some failures."""
        # Arrange
        schema_definitions = [
            {
                "source_name": "customers",
                "data_columns": [
                    {"name": "customer_id", "data_type": "INT64", "nullable": False}
                ]
            },
            {
                "source_name": "orders",
                "data_columns": [
                    {"name": "order_id", "data_type": "INT64", "nullable": False}
                ]
            }
        ]
        
        # First call succeeds, second fails
        mock_client.execute.side_effect = [None, ClickHouseError("Error")]
        
        # Act
        results = silver_creator.create_multiple_tables(schema_definitions)
        
        # Assert
        assert len(results) == 2
        assert results["customers"] is True
        assert results["orders"] is False
    
    def test_create_multiple_tables_skip_invalid(self, silver_creator, mock_client):
        """Test multiple table creation skips invalid definitions."""
        # Arrange
        schema_definitions = [
            {
                "source_name": "customers",
                "data_columns": [
                    {"name": "customer_id", "data_type": "INT64", "nullable": False}
                ]
            },
            {
                # Missing source_name
                "data_columns": [
                    {"name": "order_id", "data_type": "INT64", "nullable": False}
                ]
            }
        ]
        
        # Act
        results = silver_creator.create_multiple_tables(schema_definitions)
        
        # Assert
        assert len(results) == 1
        assert "customers" in results
        assert results["customers"] is True


class TestTableOperations:
    """Test table existence checking and schema retrieval."""
    
    def test_table_exists_true(self, silver_creator, mock_client):
        """Test checking if table exists (returns True)."""
        # Arrange
        mock_client.execute.return_value = [[1]]
        
        # Act
        result = silver_creator.table_exists("customers")
        
        # Assert
        assert result is True
        mock_client.execute.assert_called_once()
        call_args = mock_client.execute.call_args[0][0]
        assert "EXISTS TABLE `silver_customers`" in call_args
    
    def test_table_exists_false(self, silver_creator, mock_client):
        """Test checking if table exists (returns False)."""
        # Arrange
        mock_client.execute.return_value = [[0]]
        
        # Act
        result = silver_creator.table_exists("customers")
        
        # Assert
        assert result is False
    
    def test_table_exists_error(self, silver_creator, mock_client):
        """Test table existence check with error."""
        # Arrange
        mock_client.execute.side_effect = Exception("Connection error")
        
        # Act
        result = silver_creator.table_exists("customers")
        
        # Assert
        assert result is False
    
    def test_get_table_schema_success(self, silver_creator, mock_client):
        """Test retrieving table schema."""
        # Arrange
        mock_client.execute.return_value = [
            ("_row_id", "UUID"),
            ("_bronze_row_id", "UUID"),
            ("customer_id", "Int64"),
            ("email", "String")
        ]
        
        # Act
        result = silver_creator.get_table_schema("customers")
        
        # Assert
        assert result is not None
        assert len(result) == 4
        assert result[0] == ("_row_id", "UUID")
        assert result[2] == ("customer_id", "Int64")
    
    def test_get_table_schema_error(self, silver_creator, mock_client):
        """Test retrieving table schema with error."""
        # Arrange
        mock_client.execute.side_effect = Exception("Table not found")
        
        # Act
        result = silver_creator.get_table_schema("customers")
        
        # Assert
        assert result is None
    
    def test_drop_table_success(self, silver_creator, mock_client):
        """Test dropping a table."""
        # Arrange
        mock_client.execute.return_value = None
        
        # Act
        result = silver_creator.drop_table("customers")
        
        # Assert
        assert result is True
        mock_client.execute.assert_called_once()
        call_args = mock_client.execute.call_args[0][0]
        assert "DROP TABLE IF EXISTS `silver_customers`" in call_args
    
    def test_drop_table_error(self, silver_creator, mock_client):
        """Test dropping a table with error."""
        # Arrange
        mock_client.execute.side_effect = Exception("Permission denied")
        
        # Act
        result = silver_creator.drop_table("customers")
        
        # Assert
        assert result is False

    def test_table_operations_sanitize_identifiers(self, silver_creator, mock_client):
        mock_client.execute.return_value = [[1]]
        silver_creator.table_exists("bad table;DROP")
        exists_query = mock_client.execute.call_args[0][0]
        assert exists_query == "EXISTS TABLE `silver_bad_table_DROP`"

        mock_client.execute.reset_mock()
        mock_client.execute.return_value = []
        silver_creator.get_table_schema("etl.bad table")
        describe_query = mock_client.execute.call_args[0][0]
        assert describe_query == "DESCRIBE TABLE `silver_etl`.`bad_table`"

        mock_client.execute.reset_mock()
        silver_creator.drop_table("1evil")
        drop_query = mock_client.execute.call_args[0][0]
        assert drop_query == "DROP TABLE IF EXISTS `silver_1evil`"


class TestSchemaParser:
    """Test schema dictionary parsing."""
    
    def test_parse_schema_dict_minimal(self, silver_creator):
        """Test parsing minimal schema dictionary."""
        # Arrange
        schema_dict = {
            "source_name": "test",
            "data_columns": [
                {"name": "col1", "data_type": "STRING"}
            ]
        }
        
        # Act
        schema = silver_creator._parse_schema_dict(schema_dict)
        
        # Assert
        assert schema.source_name == "test"
        assert len(schema.data_columns) == 1
        assert schema.data_columns[0].name == "col1"
        assert schema.data_columns[0].data_type == DataType.STRING
        assert schema.data_columns[0].nullable is False
    
    def test_parse_schema_dict_with_nullable(self, silver_creator):
        """Test parsing schema with nullable columns."""
        # Arrange
        schema_dict = {
            "source_name": "test",
            "data_columns": [
                {"name": "col1", "data_type": "INT64", "nullable": True}
            ]
        }
        
        # Act
        schema = silver_creator._parse_schema_dict(schema_dict)
        
        # Assert
        assert schema.data_columns[0].nullable is True
    
    def test_parse_schema_dict_with_default_value(self, silver_creator):
        """Test parsing schema with default values."""
        # Arrange
        schema_dict = {
            "source_name": "test",
            "data_columns": [
                {"name": "is_active", "data_type": "BOOLEAN", "default_value": "true"}
            ]
        }
        
        # Act
        schema = silver_creator._parse_schema_dict(schema_dict)
        
        # Assert
        assert schema.data_columns[0].default_value == "true"
    
    def test_parse_schema_dict_with_comment(self, silver_creator):
        """Test parsing schema with column comments."""
        # Arrange
        schema_dict = {
            "source_name": "test",
            "data_columns": [
                {"name": "col1", "data_type": "STRING", "comment": "Test column"}
            ]
        }
        
        # Act
        schema = silver_creator._parse_schema_dict(schema_dict)
        
        # Assert
        assert schema.data_columns[0].comment == "Test column"
    
    def test_parse_schema_dict_unknown_data_type(self, silver_creator):
        """Test parsing schema with unknown data type (falls back to STRING)."""
        # Arrange
        schema_dict = {
            "source_name": "test",
            "data_columns": [
                {"name": "col1", "data_type": "UNKNOWN_TYPE"}
            ]
        }
        
        # Act
        schema = silver_creator._parse_schema_dict(schema_dict)
        
        # Assert
        assert schema.data_columns[0].data_type == DataType.STRING
    
    def test_parse_schema_dict_missing_source_name(self, silver_creator):
        """Test parsing schema without source_name raises error."""
        # Arrange
        schema_dict = {
            "data_columns": [
                {"name": "col1", "data_type": "STRING"}
            ]
        }
        
        # Act & Assert
        with pytest.raises(ValueError, match="source_name is required"):
            silver_creator._parse_schema_dict(schema_dict)
    
    def test_parse_schema_dict_missing_column_name(self, silver_creator):
        """Test parsing schema without column name raises error."""
        # Arrange
        schema_dict = {
            "source_name": "test",
            "data_columns": [
                {"data_type": "STRING"}
            ]
        }
        
        # Act & Assert
        with pytest.raises(ValueError, match="Column name is required"):
            silver_creator._parse_schema_dict(schema_dict)

    def test_parse_schema_dict_sanitizes_source_and_columns(self, silver_creator):
        schema_dict = {
            "source_name": "bad source;drop",
            "data_columns": [
                {"name": "first name", "data_type": "STRING"},
                {"name": "1evil", "data_type": "INT64"},
                {"name": "first-name", "data_type": "STRING"},
            ],
        }

        schema = silver_creator._parse_schema_dict(schema_dict)

        assert schema.source_name == "bad_source_drop"
        names = [c.name for c in schema.data_columns]
        assert names == ["first_name", "c_1evil", "first_name_2"]


class TestClientCreation:
    """Test ClickHouse client creation from environment."""
    
    @patch('utils.create_silver_tables.Client')
    def test_create_client_from_env_defaults(self, mock_client_class):
        """Test client creation with default environment variables."""
        # Arrange
        mock_instance = Mock()
        mock_client_class.return_value = mock_instance
        
        # Act
        creator = SilverTableCreator()
        
        # Assert
        assert mock_client_class.call_count >= 1
    
    @patch.dict(os.environ, {
        'CLICKHOUSE_HOST': 'test-host',
        'CLICKHOUSE_PORT': '9001',
        'CLICKHOUSE_USER': 'test-user',
        'CLICKHOUSE_PASSWORD': 'test-pass',
        'CLICKHOUSE_DATABASE': 'test-db'
    })
    @patch('utils.create_silver_tables.Client')
    def test_create_client_from_env_custom(self, mock_client_class):
        """Test client creation with custom environment variables."""
        # Arrange
        mock_instance = Mock()
        mock_client_class.return_value = mock_instance
        
        # Act
        creator = SilverTableCreator()
        
        # Assert
        # Verify client was created with custom config
        assert mock_client_class.called


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
