"""
Tests for Bronze Table Partitioning by Extraction Date
Validates that bronze tables are correctly partitioned by extraction date.

This test suite validates task 2.1.3: Implement table partitioning by extraction date
"""
import pytest
import os
import sys
from datetime import datetime, timedelta
from clickhouse_driver import Client

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from models.bronze_schema import BronzeTableSchema, BronzeRow, BronzeBatch

# Import from current directory
sys.path.insert(0, os.path.dirname(__file__))
from create_bronze_tables import BronzeTableCreator


class TestBronzeTablePartitioning:
    """Test suite for bronze table partitioning functionality."""
    
    def test_default_partition_strategy(self):
        """Test that default partitioning strategy is monthly by extraction date."""
        schema = BronzeTableSchema(
            source_name="test_customers",
            data_columns={"id": "String", "name": "String"}
        )
        
        # Verify default partition strategy
        assert schema.partition_by == "toYYYYMM(_extracted_at)"
        
        # Verify it's in the SQL
        sql = schema.get_create_table_sql()
        assert "PARTITION BY toYYYYMM(_extracted_at)" in sql
    
    def test_custom_daily_partition_strategy(self):
        """Test custom daily partitioning strategy."""
        schema = BronzeTableSchema(
            source_name="test_events",
            data_columns={"event_id": "String", "event_type": "String"},
            partition_by="toYYYYMMDD(_extracted_at)"
        )
        
        assert schema.partition_by == "toYYYYMMDD(_extracted_at)"
        
        sql = schema.get_create_table_sql()
        assert "PARTITION BY toYYYYMMDD(_extracted_at)" in sql
    
    def test_custom_yearly_partition_strategy(self):
        """Test custom yearly partitioning strategy."""
        schema = BronzeTableSchema(
            source_name="test_archive",
            data_columns={"record_id": "String"},
            partition_by="toYear(_extracted_at)"
        )
        
        assert schema.partition_by == "toYear(_extracted_at)"
        
        sql = schema.get_create_table_sql()
        assert "PARTITION BY toYear(_extracted_at)" in sql
    
    def test_partition_key_column_exists(self):
        """Test that the partition key column (_extracted_at) exists in schema."""
        schema = BronzeTableSchema(
            source_name="test_data",
            data_columns={"col1": "String"}
        )
        
        sql = schema.get_create_table_sql()
        
        # Verify _extracted_at column exists
        assert "_extracted_at DateTime64(3)" in sql
        
        # Verify it's used in partitioning
        assert "PARTITION BY toYYYYMM(_extracted_at)" in sql


class TestBronzeTablePartitioningIntegration:
    """Integration tests for partitioning with actual ClickHouse."""
    
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
    def test_table_name(self):
        """Generate unique test table name."""
        return "bronze_test_partition_data"
    
    @pytest.fixture
    def setup_teardown(self, clickhouse_client, test_table_name):
        """Setup and teardown test table."""
        # Cleanup before test
        try:
            clickhouse_client.execute(f"DROP TABLE IF EXISTS {test_table_name}")
        except:
            pass
        
        yield
        
        # Cleanup after test
        try:
            clickhouse_client.execute(f"DROP TABLE IF EXISTS {test_table_name}")
        except:
            pass
    
    def test_table_created_with_partitioning(
        self, clickhouse_client, test_table_name, setup_teardown
    ):
        """Test that table is created with correct partitioning."""
        creator = BronzeTableCreator(client=clickhouse_client)
        
        # Create table
        result = creator.create_table(
            source_name="test_partition_data",
            columns=["id", "value"]
        )
        
        assert result is True
        
        # Query table metadata to verify partitioning
        query = f"""
        SELECT partition_key
        FROM system.tables
        WHERE database = currentDatabase()
        AND name = '{test_table_name}'
        """
        
        result = clickhouse_client.execute(query)
        assert len(result) > 0
        
        partition_key = result[0][0]
        assert "toYYYYMM" in partition_key
        assert "_extracted_at" in partition_key
    
    def test_data_distributed_across_partitions(
        self, clickhouse_client, test_table_name, setup_teardown
    ):
        """Test that data is correctly distributed across partitions."""
        creator = BronzeTableCreator(client=clickhouse_client)
        
        # Create table
        creator.create_table(
            source_name="test_partition_data",
            columns=["id", "value"]
        )
        
        # Insert data from different months
        batch_id = "test_batch_001"
        source_id = "test_source"
        
        # January 2024
        row1 = BronzeRow(
            batch_id=batch_id,
            source_id=source_id,
            extracted_at=datetime(2024, 1, 15, 10, 0, 0),
            data={"id": "1", "value": "jan"}
        )
        
        # February 2024
        row2 = BronzeRow(
            batch_id=batch_id,
            source_id=source_id,
            extracted_at=datetime(2024, 2, 15, 10, 0, 0),
            data={"id": "2", "value": "feb"}
        )
        
        # March 2024
        row3 = BronzeRow(
            batch_id=batch_id,
            source_id=source_id,
            extracted_at=datetime(2024, 3, 15, 10, 0, 0),
            data={"id": "3", "value": "mar"}
        )
        
        # Insert rows
        rows_data = [row1.to_dict(), row2.to_dict(), row3.to_dict()]
        clickhouse_client.execute(
            f"INSERT INTO {test_table_name} VALUES",
            rows_data
        )
        
        # Query partitions
        query = f"""
        SELECT DISTINCT partition
        FROM system.parts
        WHERE database = currentDatabase()
        AND table = '{test_table_name}'
        AND active = 1
        ORDER BY partition
        """
        
        partitions = clickhouse_client.execute(query)
        partition_ids = [p[0] for p in partitions]
        
        # Should have 3 partitions (one for each month)
        assert len(partition_ids) == 3
        
        # Verify partition format (YYYYMM)
        assert "202401" in partition_ids
        assert "202402" in partition_ids
        assert "202403" in partition_ids
    
    def test_partition_pruning_performance(
        self, clickhouse_client, test_table_name, setup_teardown
    ):
        """Test that partition pruning works for date-range queries."""
        creator = BronzeTableCreator(client=clickhouse_client)
        
        # Create table
        creator.create_table(
            source_name="test_partition_data",
            columns=["id", "value"]
        )
        
        # Insert data across multiple months
        batch_id = "test_batch_001"
        source_id = "test_source"
        
        rows_data = []
        for month in range(1, 7):  # Jan to Jun 2024
            for day in [1, 15]:
                row = BronzeRow(
                    batch_id=batch_id,
                    source_id=source_id,
                    extracted_at=datetime(2024, month, day, 10, 0, 0),
                    data={"id": f"{month}_{day}", "value": f"month_{month}"}
                )
                rows_data.append(row.to_dict())
        
        clickhouse_client.execute(
            f"INSERT INTO {test_table_name} VALUES",
            rows_data
        )
        
        # Query with date filter (should only scan February partition)
        query = f"""
        SELECT count(*) as cnt
        FROM {test_table_name}
        WHERE _extracted_at >= '2024-02-01' AND _extracted_at < '2024-03-01'
        """
        
        result = clickhouse_client.execute(query)
        count = result[0][0]
        
        # Should find 2 rows (Feb 1 and Feb 15)
        assert count == 2
        
        # Verify partition pruning by checking EXPLAIN
        explain_query = f"""
        EXPLAIN
        SELECT count(*) as cnt
        FROM {test_table_name}
        WHERE _extracted_at >= '2024-02-01' AND _extracted_at < '2024-03-01'
        """
        
        explain_result = clickhouse_client.execute(explain_query)
        explain_text = "\n".join([row[0] for row in explain_result])
        
        # Should mention partition pruning or specific partition
        # (exact format depends on ClickHouse version)
        assert "202402" in explain_text or "Prune" in explain_text or "partition" in explain_text.lower()
    
    def test_custom_daily_partitioning_integration(
        self, clickhouse_client, setup_teardown
    ):
        """Test custom daily partitioning strategy in actual ClickHouse."""
        test_table = "bronze_test_daily_partition"
        
        try:
            clickhouse_client.execute(f"DROP TABLE IF EXISTS {test_table}")
        except:
            pass
        
        creator = BronzeTableCreator(client=clickhouse_client)
        
        # Create table with daily partitioning
        result = creator.create_table(
            source_name="test_daily_partition",
            columns=["event_id", "event_type"],
            partition_by="toYYYYMMDD(_extracted_at)"
        )
        
        assert result is True
        
        # Verify partitioning strategy
        query = f"""
        SELECT partition_key
        FROM system.tables
        WHERE database = currentDatabase()
        AND name = '{test_table}'
        """
        
        result = clickhouse_client.execute(query)
        partition_key = result[0][0]
        
        assert "toYYYYMMDD" in partition_key
        assert "_extracted_at" in partition_key
        
        # Cleanup
        try:
            clickhouse_client.execute(f"DROP TABLE IF EXISTS {test_table}")
        except:
            pass
    
    def test_partition_count_with_large_dataset(
        self, clickhouse_client, test_table_name, setup_teardown
    ):
        """Test partition count with data spanning multiple months."""
        creator = BronzeTableCreator(client=clickhouse_client)
        
        # Create table
        creator.create_table(
            source_name="test_partition_data",
            columns=["id", "value"]
        )
        
        # Insert data spanning 12 months
        batch_id = "test_batch_001"
        source_id = "test_source"
        
        rows_data = []
        for month in range(1, 13):  # All 12 months of 2024
            row = BronzeRow(
                batch_id=batch_id,
                source_id=source_id,
                extracted_at=datetime(2024, month, 15, 10, 0, 0),
                data={"id": str(month), "value": f"month_{month}"}
            )
            rows_data.append(row.to_dict())
        
        clickhouse_client.execute(
            f"INSERT INTO {test_table_name} VALUES",
            rows_data
        )
        
        # Query partition count
        query = f"""
        SELECT count(DISTINCT partition) as partition_count
        FROM system.parts
        WHERE database = currentDatabase()
        AND table = '{test_table_name}'
        AND active = 1
        """
        
        result = clickhouse_client.execute(query)
        partition_count = result[0][0]
        
        # Should have 12 partitions (one per month)
        assert partition_count == 12


class TestPartitioningBestPractices:
    """Test partitioning best practices and edge cases."""
    
    def test_partition_by_uses_correct_column(self):
        """Test that partitioning uses _extracted_at, not other date columns."""
        schema = BronzeTableSchema(
            source_name="test_data",
            data_columns={"created_at": "String", "updated_at": "String"}
        )
        
        sql = schema.get_create_table_sql()
        
        # Should partition by _extracted_at (lineage column)
        assert "PARTITION BY toYYYYMM(_extracted_at)" in sql
        
        # Should NOT partition by data columns
        assert "PARTITION BY toYYYYMM(created_at)" not in sql
        assert "PARTITION BY toYYYYMM(updated_at)" not in sql
    
    def test_partition_granularity_tradeoffs(self):
        """Test different partition granularities for different use cases."""
        # High-volume data: daily partitioning
        high_volume_schema = BronzeTableSchema(
            source_name="high_volume_events",
            data_columns={"event_id": "String"},
            partition_by="toYYYYMMDD(_extracted_at)"
        )
        assert "toYYYYMMDD" in high_volume_schema.get_create_table_sql()
        
        # Medium-volume data: monthly partitioning (default)
        medium_volume_schema = BronzeTableSchema(
            source_name="medium_volume_data",
            data_columns={"record_id": "String"}
        )
        assert "toYYYYMM" in medium_volume_schema.get_create_table_sql()
        
        # Low-volume archive: yearly partitioning
        archive_schema = BronzeTableSchema(
            source_name="archive_data",
            data_columns={"archive_id": "String"},
            partition_by="toYear(_extracted_at)"
        )
        assert "toYear" in archive_schema.get_create_table_sql()
    
    def test_partition_key_in_order_by(self):
        """Test that partition key considerations for ORDER BY clause."""
        schema = BronzeTableSchema(
            source_name="test_data",
            data_columns={"id": "String"}
        )
        
        sql = schema.get_create_table_sql()
        
        # Default ORDER BY should be (_batch_id, _row_id)
        assert "ORDER BY (_batch_id, _row_id)" in sql
        
        # Can customize to include _extracted_at for time-series queries
        custom_schema = BronzeTableSchema(
            source_name="test_timeseries",
            data_columns={"metric": "String"},
            order_by=["_extracted_at", "_batch_id", "_row_id"]
        )
        
        custom_sql = custom_schema.get_create_table_sql()
        assert "ORDER BY (_extracted_at, _batch_id, _row_id)" in custom_sql


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
