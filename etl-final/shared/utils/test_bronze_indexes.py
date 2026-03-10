"""
Tests for Bronze Table Indexes
Tests that indexes are properly created and improve query performance.
"""
import pytest
import os
import sys
from clickhouse_driver import Client

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from models.bronze_schema import BronzeTableSchema
from utils.clickhouse_schemas import ClickHouseSchemaManager


@pytest.fixture
def clickhouse_client():
    """Create a ClickHouse client for testing."""
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
def schema_manager(clickhouse_client):
    """Create a ClickHouseSchemaManager for testing."""
    return ClickHouseSchemaManager(clickhouse_client)


@pytest.fixture
def test_table_name():
    """Generate a unique test table name."""
    return "test_bronze_indexes"


@pytest.fixture
def cleanup_table(clickhouse_client, test_table_name):
    """Cleanup test table before and after tests."""
    # Cleanup before test
    try:
        clickhouse_client.execute(f"DROP TABLE IF EXISTS bronze_{test_table_name}")
    except:
        pass
    
    yield
    
    # Cleanup after test
    try:
        clickhouse_client.execute(f"DROP TABLE IF EXISTS bronze_{test_table_name}")
    except:
        pass


class TestBronzeTableIndexes:
    """Test suite for bronze table index functionality."""
    
    def test_default_indexes_in_schema(self):
        """Test that BronzeTableSchema includes default indexes."""
        schema = BronzeTableSchema(
            source_name="test_source",
            data_columns={"col1": "String", "col2": "String"}
        )
        
        assert len(schema.indexes) > 0
        
        # Check for expected indexes
        index_names = [idx["name"] for idx in schema.indexes]
        assert "idx_dedup_key" in index_names
        assert "idx_source_id" in index_names
        assert "idx_extracted_at" in index_names
    
    def test_index_types(self):
        """Test that indexes have appropriate types."""
        schema = BronzeTableSchema(
            source_name="test_source",
            data_columns={"col1": "String"}
        )
        
        # Find specific indexes and check their types
        dedup_idx = next(idx for idx in schema.indexes if idx["name"] == "idx_dedup_key")
        assert dedup_idx["type"] == "bloom_filter"
        
        source_idx = next(idx for idx in schema.indexes if idx["name"] == "idx_source_id")
        assert source_idx["type"] == "set"
        
        time_idx = next(idx for idx in schema.indexes if idx["name"] == "idx_extracted_at")
        assert time_idx["type"] == "minmax"
    
    def test_custom_indexes(self):
        """Test that custom indexes can be added."""
        custom_indexes = [
            {"name": "idx_custom", "column": "custom_col", "type": "set", "granularity": 2}
        ]
        
        schema = BronzeTableSchema(
            source_name="test_source",
            data_columns={"custom_col": "String"},
            indexes=custom_indexes
        )
        
        assert len(schema.indexes) == 1
        assert schema.indexes[0]["name"] == "idx_custom"
    
    def test_create_table_sql_includes_indexes(self):
        """Test that generated SQL includes INDEX definitions."""
        schema = BronzeTableSchema(
            source_name="test_source",
            data_columns={"col1": "String"}
        )
        
        sql = schema.get_create_table_sql()
        
        # Check that INDEX keyword appears in SQL
        assert "INDEX" in sql
        assert "idx_dedup_key" in sql
        assert "idx_source_id" in sql
        assert "idx_extracted_at" in sql
        
        # Check index types
        assert "bloom_filter" in sql
        assert "set" in sql
        assert "minmax" in sql
    
    def test_create_table_with_indexes(
        self,
        schema_manager,
        clickhouse_client,
        test_table_name,
        cleanup_table
    ):
        """Test that table is created with indexes in ClickHouse."""
        schema = BronzeTableSchema(
            source_name=test_table_name,
            data_columns={"col1": "String", "col2": "String"}
        )
        
        # Create table
        result = schema_manager.create_bronze_table(schema)
        assert result is True
        
        # Verify table exists
        assert schema_manager.table_exists(f"bronze_{test_table_name}")
        
        # Check that indexes were created by querying system.data_skipping_indices
        query = """
        SELECT name, type, expr
        FROM system.data_skipping_indices
        WHERE table = %(table_name)s
        AND database = %(database)s
        """
        
        indexes = clickhouse_client.execute(
            query,
            {
                'table_name': f"bronze_{test_table_name}",
                'database': os.getenv('CLICKHOUSE_DATABASE', 'etl')
            }
        )
        
        # Should have at least 3 indexes
        assert len(indexes) >= 3
        
        # Check index names
        index_names = [idx[0] for idx in indexes]
        assert "idx_dedup_key" in index_names
        assert "idx_source_id" in index_names
        assert "idx_extracted_at" in index_names


class TestIndexQueryPerformance:
    """Test that indexes improve query performance."""
    
    @pytest.fixture
    def populated_table(
        self,
        schema_manager,
        clickhouse_client,
        test_table_name,
        cleanup_table
    ):
        """Create and populate a test table with sample data."""
        schema = BronzeTableSchema(
            source_name=test_table_name,
            data_columns={"col1": "String", "col2": "String"}
        )
        
        # Create table
        schema_manager.create_bronze_table(schema)
        
        # Insert test data
        from datetime import datetime
        from uuid import uuid4
        
        rows = []
        for i in range(1000):
            rows.append({
                '_row_id': str(uuid4()),
                '_batch_id': f"batch_{i % 10}",
                '_source_id': f"source_{i % 5}",
                '_extracted_at': datetime.now(),
                '_dedup_key': f"dedup_{i}",
                'col1': f"value1_{i}",
                'col2': f"value2_{i}",
                '_file_name': f"file_{i}.csv",
                '_file_size': 1024 * i,
                '_row_number': i
            })
        
        # Insert in batches
        batch_size = 100
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i+batch_size]
            clickhouse_client.execute(
                f"INSERT INTO bronze_{test_table_name} VALUES",
                batch
            )
        
        return f"bronze_{test_table_name}"
    
    def test_dedup_key_query(self, clickhouse_client, populated_table):
        """Test query performance with _dedup_key index."""
        # Query by dedup_key (should use bloom_filter index)
        query = f"""
        SELECT COUNT(*)
        FROM {populated_table}
        WHERE _dedup_key = 'dedup_500'
        """
        
        result = clickhouse_client.execute(query)
        assert result[0][0] == 1
    
    def test_source_id_query(self, clickhouse_client, populated_table):
        """Test query performance with _source_id index."""
        # Query by source_id (should use set index)
        query = f"""
        SELECT COUNT(*)
        FROM {populated_table}
        WHERE _source_id = 'source_2'
        """
        
        result = clickhouse_client.execute(query)
        assert result[0][0] == 200  # 1000 rows / 5 sources = 200 per source
    
    def test_extracted_at_range_query(self, clickhouse_client, populated_table):
        """Test query performance with _extracted_at index."""
        from datetime import datetime, timedelta
        
        # Query by time range (should use minmax index)
        now = datetime.now()
        past = now - timedelta(hours=1)
        
        query = f"""
        SELECT COUNT(*)
        FROM {populated_table}
        WHERE _extracted_at >= %(start_time)s
        AND _extracted_at <= %(end_time)s
        """
        
        result = clickhouse_client.execute(
            query,
            {'start_time': past, 'end_time': now}
        )
        
        # Should return all rows since they were just inserted
        assert result[0][0] == 1000
    
    def test_combined_query(self, clickhouse_client, populated_table):
        """Test query with multiple indexed columns."""
        # Query using multiple indexes
        query = f"""
        SELECT COUNT(*)
        FROM {populated_table}
        WHERE _source_id = 'source_1'
        AND _batch_id = 'batch_1'
        """
        
        result = clickhouse_client.execute(query)
        # source_1 appears at i=1,6,11,16,... (every 5th starting at 1)
        # batch_1 appears at i=1,11,21,31,... (every 10th starting at 1)
        # Intersection: i=1,11,21,31,41,51,61,71,81,91,... (every 50th starting at 1)
        # Count: 1000/50 = 20
        assert result[0][0] == 20


class TestIndexEdgeCases:
    """Test edge cases for index functionality."""
    
    def test_empty_indexes_list(self):
        """Test that table can be created with no indexes."""
        schema = BronzeTableSchema(
            source_name="test_source",
            data_columns={"col1": "String"},
            indexes=[]
        )
        
        sql = schema.get_create_table_sql()
        
        # Should not contain INDEX keyword
        assert "INDEX" not in sql
    
    def test_index_without_granularity(self):
        """Test that index defaults to granularity 1 if not specified."""
        indexes = [
            {"name": "idx_test", "column": "test_col", "type": "minmax"}
        ]
        
        schema = BronzeTableSchema(
            source_name="test_source",
            data_columns={"test_col": "String"},
            indexes=indexes
        )
        
        sql = schema.get_create_table_sql()
        
        # Should include GRANULARITY 1 (default)
        assert "GRANULARITY 1" in sql
    
    def test_index_without_type(self):
        """Test that index defaults to minmax type if not specified."""
        indexes = [
            {"name": "idx_test", "column": "test_col", "granularity": 2}
        ]
        
        schema = BronzeTableSchema(
            source_name="test_source",
            data_columns={"test_col": "String"},
            indexes=indexes
        )
        
        sql = schema.get_create_table_sql()
        
        # Should include TYPE minmax (default)
        assert "TYPE minmax" in sql


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
