"""
Tests for Bronze Table Creation Script
Tests the BronzeTableCreator class and its methods.
"""
import pytest
import os
import sys
from unittest.mock import Mock, patch, MagicMock
from clickhouse_driver import Client

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))
from create_bronze_tables import BronzeTableCreator

# Add parent directory to path for model imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from models.bronze_schema import BronzeTableSchema


@pytest.fixture
def mock_client():
    """Create a mock ClickHouse client."""
    client = Mock(spec=Client)
    client.execute = Mock(return_value=None)
    return client


@pytest.fixture
def creator(mock_client):
    """Create a BronzeTableCreator with mock client."""
    return BronzeTableCreator(client=mock_client)


class TestBronzeTableCreator:
    """Test suite for BronzeTableCreator class."""
    
    def test_initialization_with_client(self, mock_client):
        """Test creator initialization with provided client."""
        creator = BronzeTableCreator(client=mock_client)
        assert creator.client == mock_client
        assert creator.schema_manager is not None
    
    @patch('create_bronze_tables.Client')
    def test_initialization_from_env(self, mock_client_class):
        """Test creator initialization from environment variables."""
        mock_instance = Mock(spec=Client)
        mock_client_class.return_value = mock_instance
        
        with patch.dict(os.environ, {
            'CLICKHOUSE_HOST': 'test-host',
            'CLICKHOUSE_PORT': '9001',
            'CLICKHOUSE_USER': 'test-user',
            'CLICKHOUSE_DATABASE': 'test-db'
        }):
            creator = BronzeTableCreator()
            assert creator.client is not None
    
    def test_create_table_success(self, creator, mock_client):
        """Test successful table creation."""
        result = creator.create_table(
            source_name="customers",
            columns=["id", "name", "email"]
        )
        
        assert result is True
        # Verify execute was called (table creation)
        assert mock_client.execute.called
    
    def test_create_table_empty_source_name(self, creator):
        """Test table creation fails with empty source name."""
        result = creator.create_table(
            source_name="",
            columns=["id", "name"]
        )
        
        assert result is False
    
    def test_create_table_empty_columns(self, creator):
        """Test table creation fails with empty columns list."""
        result = creator.create_table(
            source_name="customers",
            columns=[]
        )
        
        assert result is False
    
    def test_create_table_with_custom_partition(self, creator, mock_client):
        """Test table creation with custom partitioning."""
        result = creator.create_table(
            source_name="events",
            columns=["event_id", "event_type"],
            partition_by="toYYYYMMDD(_extracted_at)"
        )
        
        assert result is True
        assert mock_client.execute.called
    
    def test_create_table_with_custom_order(self, creator, mock_client):
        """Test table creation with custom ordering."""
        result = creator.create_table(
            source_name="logs",
            columns=["log_id", "message"],
            order_by=["_extracted_at", "_row_id"]
        )
        
        assert result is True
        assert mock_client.execute.called
    
    def test_create_table_with_custom_settings(self, creator, mock_client):
        """Test table creation with custom settings."""
        result = creator.create_table(
            source_name="metrics",
            columns=["metric_id", "value"],
            settings={"index_granularity": 4096}
        )
        
        assert result is True
        assert mock_client.execute.called
    
    def test_create_table_from_schema(self, creator, mock_client):
        """Test table creation from BronzeTableSchema object."""
        schema = BronzeTableSchema(
            source_name="orders",
            data_columns={"order_id": "String", "amount": "String"}
        )
        
        result = creator.create_table_from_schema(schema)
        
        assert result is True
        assert mock_client.execute.called
    
    def test_create_multiple_tables(self, creator, mock_client):
        """Test creating multiple tables at once."""
        table_definitions = [
            {
                "source_name": "customers",
                "columns": ["id", "name"]
            },
            {
                "source_name": "orders",
                "columns": ["order_id", "customer_id"]
            },
            {
                "source_name": "products",
                "columns": ["product_id", "name", "price"]
            }
        ]
        
        results = creator.create_multiple_tables(table_definitions)
        
        assert len(results) == 3
        assert all(results.values())
        assert "customers" in results
        assert "orders" in results
        assert "products" in results
    
    def test_create_multiple_tables_with_invalid_definition(self, creator):
        """Test creating multiple tables skips invalid definitions."""
        table_definitions = [
            {
                "source_name": "customers",
                "columns": ["id", "name"]
            },
            {
                # Missing source_name
                "columns": ["order_id"]
            },
            {
                "source_name": "products",
                "columns": ["product_id"]
            }
        ]
        
        results = creator.create_multiple_tables(table_definitions)
        
        # Should only create 2 tables (skip the invalid one)
        assert len(results) == 2
        assert "customers" in results
        assert "products" in results
    
    def test_table_exists(self, creator):
        """Test checking if table exists."""
        creator.schema_manager.table_exists = Mock(return_value=True)
        
        exists = creator.table_exists("customers")
        
        assert exists is True
        creator.schema_manager.table_exists.assert_called_once_with("bronze_customers")
    
    def test_get_table_schema(self, creator):
        """Test getting table schema."""
        expected_schema = [
            ("_row_id", "UUID"),
            ("_batch_id", "String"),
            ("id", "String"),
            ("name", "String")
        ]
        creator.schema_manager.get_table_schema = Mock(return_value=expected_schema)
        
        schema = creator.get_table_schema("customers")
        
        assert schema == expected_schema
        creator.schema_manager.get_table_schema.assert_called_once_with("bronze_customers")
    
    def test_create_table_handles_exception(self, creator, mock_client):
        """Test that exceptions during table creation are handled gracefully."""
        mock_client.execute.side_effect = Exception("Database error")
        
        result = creator.create_table(
            source_name="customers",
            columns=["id", "name"]
        )
        
        assert result is False


class TestBronzeTableCreatorIntegration:
    """Integration tests that require actual ClickHouse connection."""
    
    @pytest.fixture
    def clickhouse_client(self):
        """Create a real ClickHouse client for integration tests."""
        try:
            client = Client(
                host=os.getenv('CLICKHOUSE_HOST', 'localhost'),
                port=int(os.getenv('CLICKHOUSE_PORT', 9000)),
                user=os.getenv('CLICKHOUSE_USER', 'default'),
                password=os.getenv('CLICKHOUSE_PASSWORD', ''),
                database=os.getenv('CLICKHOUSE_DATABASE', 'etl')
            )
            # Test connection
            client.execute("SELECT 1")
            return client
        except Exception as e:
            pytest.skip(f"ClickHouse not available: {e}")
    
    @pytest.fixture
    def integration_creator(self, clickhouse_client):
        """Create a BronzeTableCreator with real ClickHouse client."""
        creator = BronzeTableCreator(client=clickhouse_client)
        
        # Cleanup before tests
        try:
            clickhouse_client.execute("DROP TABLE IF EXISTS bronze_test_integration_customers")
            clickhouse_client.execute("DROP TABLE IF EXISTS bronze_test_integration_orders")
            clickhouse_client.execute("DROP TABLE IF EXISTS bronze_test_integration_events")
        except:
            pass
        
        yield creator
        
        # Cleanup after tests
        try:
            clickhouse_client.execute("DROP TABLE IF EXISTS bronze_test_integration_customers")
            clickhouse_client.execute("DROP TABLE IF EXISTS bronze_test_integration_orders")
            clickhouse_client.execute("DROP TABLE IF EXISTS bronze_test_integration_events")
        except:
            pass
    
    def test_create_table_integration(self, integration_creator):
        """Test actual table creation in ClickHouse."""
        result = integration_creator.create_table(
            source_name="test_integration_customers",
            columns=["customer_id", "name", "email"]
        )
        
        assert result is True
        assert integration_creator.table_exists("test_integration_customers")
    
    def test_table_schema_integration(self, integration_creator):
        """Test retrieving actual table schema from ClickHouse."""
        integration_creator.create_table(
            source_name="test_integration_orders",
            columns=["order_id", "customer_id", "amount"]
        )
        
        schema = integration_creator.get_table_schema("test_integration_orders")
        
        assert schema is not None
        assert len(schema) > 0
        
        # Check for required lineage columns
        column_names = [col[0] for col in schema]
        assert "_row_id" in column_names
        assert "_batch_id" in column_names
        assert "_source_id" in column_names
        assert "_extracted_at" in column_names
        assert "_dedup_key" in column_names
        
        # Check for data columns
        assert "order_id" in column_names
        assert "customer_id" in column_names
        assert "amount" in column_names
    
    def test_create_multiple_tables_integration(self, integration_creator):
        """Test creating multiple tables in ClickHouse."""
        table_definitions = [
            {
                "source_name": "test_integration_customers",
                "columns": ["id", "name"]
            },
            {
                "source_name": "test_integration_orders",
                "columns": ["order_id", "customer_id"]
            }
        ]
        
        results = integration_creator.create_multiple_tables(table_definitions)
        
        assert len(results) == 2
        assert all(results.values())
        assert integration_creator.table_exists("test_integration_customers")
        assert integration_creator.table_exists("test_integration_orders")
    
    def test_idempotent_table_creation_integration(self, integration_creator):
        """Test that creating the same table multiple times is idempotent."""
        # Create table first time
        result1 = integration_creator.create_table(
            source_name="test_integration_events",
            columns=["event_id", "event_type"]
        )
        
        # Create same table again
        result2 = integration_creator.create_table(
            source_name="test_integration_events",
            columns=["event_id", "event_type"]
        )
        
        # Create same table third time
        result3 = integration_creator.create_table(
            source_name="test_integration_events",
            columns=["event_id", "event_type"]
        )
        
        assert result1 is True
        assert result2 is True
        assert result3 is True
        assert integration_creator.table_exists("test_integration_events")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
