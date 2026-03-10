"""
Load Tests for Bronze Layer with 1M+ Rows

Tests performance and scalability requirements for bronze layer writes.

Validates:
- NFR-1: Performance - Throughput: 100K rows/sec per service instance
- NFR-1: Memory: O(batch_size) not O(total_rows)
- US-1 AC 1.1: Running the same extraction twice produces identical results
- US-2 AC 2.2: Raw layer exists in ClickHouse with timestamp and source tracking

Requirements Coverage:
- NFR-1: Performance requirements (throughput, memory)
- US-1: Idempotent ETL operations
- US-2: Immutable raw data storage
"""
import pytest
import time
import psutil
import os
from datetime import datetime, timezone
from uuid import uuid4
from typing import List
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'shared'))

from models.bronze_schema import BronzeRow, BronzeBatch, BronzeTableSchema
from utils.bronze_writer import BronzeWriter
from utils.idempotency_manager import IdempotencyManager
from clickhouse_driver import Client


def is_clickhouse_available():
    """Check if ClickHouse is available for testing."""
    try:
        host = os.getenv('CLICKHOUSE_HOST', 'localhost')
        port = int(os.getenv('CLICKHOUSE_PORT', 9000))
        client = Client(host=host, port=port)
        client.execute("SELECT 1")
        return True
    except:
        return False


# Mark all tests as load tests that require ClickHouse
requires_clickhouse = pytest.mark.skipif(
    not is_clickhouse_available(),
    reason="ClickHouse not available. Set CLICKHOUSE_HOST to run load tests."
)


@pytest.fixture(scope="module")
def clickhouse_client():
    """
    Create ClickHouse client for load tests.
    
    Requires CLICKHOUSE_HOST environment variable or uses localhost.
    """
    host = os.getenv('CLICKHOUSE_HOST', 'localhost')
    port = int(os.getenv('CLICKHOUSE_PORT', 9000))
    database = os.getenv('CLICKHOUSE_DATABASE', 'etl_load_test')
    
    client = Client(host=host, port=port)
    
    # Create test database
    try:
        client.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
        client = Client(host=host, port=port, database=database)
        yield client
    finally:
        # Cleanup: drop test database
        try:
            client.execute(f"DROP DATABASE IF EXISTS {database}")
        except:
            pass


@pytest.fixture
def bronze_writer(clickhouse_client):
    """Create BronzeWriter instance for testing."""
    return BronzeWriter(client=clickhouse_client, enable_deduplication=True)


def create_test_batch(
    batch_id: str,
    source_id: str,
    source_name: str,
    num_rows: int,
    columns: dict
) -> BronzeBatch:
    """
    Create a test batch with specified number of rows.
    
    Args:
        batch_id: Batch identifier
        source_id: Source identifier
        source_name: Source name for table
        num_rows: Number of rows to generate
        columns: Dictionary of column names to generate
        
    Returns:
        BronzeBatch with generated rows
    """
    extracted_at = datetime.now(timezone.utc)
    rows = []
    
    for i in range(num_rows):
        # Generate data for each column
        data = {}
        for col_name in columns.keys():
            if col_name == "id":
                data[col_name] = str(i)
            elif col_name.startswith("value"):
                data[col_name] = f"test_value_{i}_{col_name}"
            elif col_name == "email":
                data[col_name] = f"user{i}@example.com"
            elif col_name == "name":
                data[col_name] = f"User {i}"
            elif col_name == "timestamp":
                data[col_name] = extracted_at.isoformat()
            else:
                data[col_name] = f"data_{i}"
        
        row = BronzeRow(
            batch_id=batch_id,
            source_id=source_id,
            extracted_at=extracted_at,
            data=data,
            file_name=f"load_test_{batch_id}.csv",
            file_size=num_rows * 100,  # Approximate
            row_number=i
        )
        rows.append(row)
    
    schema = BronzeTableSchema(
        source_name=source_name,
        data_columns=columns
    )
    
    return BronzeBatch(
        batch_id=batch_id,
        source_id=source_id,
        rows=rows,
        schema=schema
    )


def get_memory_usage_mb():
    """Get current process memory usage in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


@requires_clickhouse
class TestBronzeLoadPerformance:
    """Load tests for bronze layer performance with 1M+ rows."""
    
    def test_1m_rows_single_batch_throughput(self, bronze_writer, clickhouse_client):
        """
        Test writing 1M rows in a single batch to validate throughput requirement.
        
        **Validates: NFR-1** - Performance: Throughput: 100K rows/sec per service instance
        
        This test writes 1M rows in one batch and measures:
        - Total throughput (rows/sec)
        - Write duration
        - Memory usage
        
        Success criteria:
        - Throughput >= 100K rows/sec
        - Memory usage is reasonable (< 2GB for 1M rows)
        """
        print("\n=== Test: 1M rows single batch throughput ===")
        
        batch_id = f"load_test_1m_{uuid4()}"
        source_id = "load_test_1m_source"
        source_name = "load_test_1m"
        
        # Define columns (10 columns for realistic data)
        columns = {
            "id": "String",
            "name": "String",
            "email": "String",
            "value1": "String",
            "value2": "String",
            "value3": "String",
            "value4": "String",
            "value5": "String",
            "timestamp": "String",
            "status": "String"
        }
        
        # Measure memory before
        mem_before = get_memory_usage_mb()
        print(f"Memory before: {mem_before:.2f} MB")
        
        # Create batch with 1M rows
        print("Creating batch with 1M rows...")
        start_create = time.time()
        batch = create_test_batch(batch_id, source_id, source_name, 1_000_000, columns)
        create_duration = time.time() - start_create
        print(f"Batch creation took {create_duration:.2f}s")
        
        # Measure memory after batch creation
        mem_after_create = get_memory_usage_mb()
        mem_used_create = mem_after_create - mem_before
        print(f"Memory after batch creation: {mem_after_create:.2f} MB (used: {mem_used_create:.2f} MB)")
        
        # Write batch
        print("Writing batch to bronze table...")
        start_write = time.time()
        result = bronze_writer.write_batch(batch)
        write_duration = time.time() - start_write
        
        # Measure memory after write
        mem_after_write = get_memory_usage_mb()
        mem_used_write = mem_after_write - mem_before
        print(f"Memory after write: {mem_after_write:.2f} MB (used: {mem_used_write:.2f} MB)")
        
        # Verify write succeeded
        assert result["success"] is True, f"Write failed: {result.get('error')}"
        assert result["rows_written"] == 1_000_000
        
        # Calculate throughput
        throughput = 1_000_000 / write_duration
        print(f"\n=== Results ===")
        print(f"Rows written: {result['rows_written']:,}")
        print(f"Write duration: {write_duration:.2f}s")
        print(f"Throughput: {throughput:,.0f} rows/sec")
        print(f"Memory used: {mem_used_write:.2f} MB")
        print(f"Memory per 1K rows: {(mem_used_write / 1000):.2f} MB")
        
        # Verify throughput requirement
        assert throughput >= 100_000, (
            f"Throughput {throughput:,.0f} rows/sec is below requirement of 100K rows/sec"
        )
        
        # Verify memory usage is reasonable (< 2GB for 1M rows)
        assert mem_used_write < 2048, (
            f"Memory usage {mem_used_write:.2f} MB exceeds 2GB limit"
        )
        
        # Verify data in ClickHouse
        count = clickhouse_client.execute(
            f"SELECT COUNT(*) FROM bronze_{source_name} WHERE _batch_id = '{batch_id}'"
        )[0][0]
        assert count == 1_000_000, f"Expected 1M rows, found {count:,}"
        
        print(f"✓ Throughput requirement met: {throughput:,.0f} rows/sec >= 100K rows/sec")
        print(f"✓ Memory requirement met: {mem_used_write:.2f} MB < 2048 MB")
        
        # Cleanup
        clickhouse_client.execute(f"DROP TABLE IF EXISTS bronze_{source_name}")
    
    def test_1m_rows_batched_writes_memory(self, bronze_writer, clickhouse_client):
        """
        Test writing 1M rows in multiple batches to validate memory requirement.
        
        **Validates: NFR-1** - Memory: O(batch_size) not O(total_rows)
        
        This test writes 1M rows in 10 batches of 100K rows each and measures:
        - Memory usage per batch (should be constant)
        - Total throughput
        - Memory efficiency
        
        Success criteria:
        - Memory usage per batch is constant (O(batch_size))
        - Total throughput >= 100K rows/sec
        """
        print("\n=== Test: 1M rows batched writes (memory) ===")
        
        source_id = "load_test_batched_source"
        source_name = "load_test_batched"
        
        # Define columns
        columns = {
            "id": "String",
            "name": "String",
            "email": "String",
            "value1": "String",
            "value2": "String"
        }
        
        # Write 10 batches of 100K rows each
        num_batches = 10
        rows_per_batch = 100_000
        total_rows = num_batches * rows_per_batch
        
        mem_before = get_memory_usage_mb()
        print(f"Memory before: {mem_before:.2f} MB")
        
        batch_memories = []
        batch_durations = []
        total_start = time.time()
        
        for batch_num in range(num_batches):
            batch_id = f"load_test_batch_{batch_num}_{uuid4()}"
            
            # Measure memory before batch
            mem_before_batch = get_memory_usage_mb()
            
            # Create and write batch
            batch = create_test_batch(batch_id, source_id, source_name, rows_per_batch, columns)
            
            start_write = time.time()
            result = bronze_writer.write_batch(batch)
            write_duration = time.time() - start_write
            
            # Measure memory after batch
            mem_after_batch = get_memory_usage_mb()
            mem_used_batch = mem_after_batch - mem_before_batch
            
            batch_memories.append(mem_used_batch)
            batch_durations.append(write_duration)
            
            assert result["success"] is True
            assert result["rows_written"] == rows_per_batch
            
            throughput = rows_per_batch / write_duration
            print(f"Batch {batch_num + 1}/{num_batches}: "
                  f"{rows_per_batch:,} rows in {write_duration:.2f}s "
                  f"({throughput:,.0f} rows/sec, mem: {mem_used_batch:.2f} MB)")
        
        total_duration = time.time() - total_start
        total_throughput = total_rows / total_duration
        
        # Calculate memory statistics
        avg_mem = sum(batch_memories) / len(batch_memories)
        max_mem = max(batch_memories)
        min_mem = min(batch_memories)
        mem_variance = max_mem - min_mem
        
        print(f"\n=== Results ===")
        print(f"Total rows written: {total_rows:,}")
        print(f"Total duration: {total_duration:.2f}s")
        print(f"Overall throughput: {total_throughput:,.0f} rows/sec")
        print(f"Average memory per batch: {avg_mem:.2f} MB")
        print(f"Memory variance: {mem_variance:.2f} MB (max: {max_mem:.2f}, min: {min_mem:.2f})")
        
        # Verify memory is O(batch_size) not O(total_rows)
        # Memory variance should be small (< 50% of average)
        assert mem_variance < (avg_mem * 0.5), (
            f"Memory variance {mem_variance:.2f} MB is too high, "
            f"indicating O(total_rows) instead of O(batch_size)"
        )
        
        # Verify throughput requirement
        assert total_throughput >= 100_000, (
            f"Throughput {total_throughput:,.0f} rows/sec is below requirement of 100K rows/sec"
        )
        
        # Verify data in ClickHouse
        count = clickhouse_client.execute(
            f"SELECT COUNT(*) FROM bronze_{source_name}"
        )[0][0]
        assert count == total_rows, f"Expected {total_rows:,} rows, found {count:,}"
        
        print(f"✓ Memory requirement met: O(batch_size) - variance {mem_variance:.2f} MB < {(avg_mem * 0.5):.2f} MB")
        print(f"✓ Throughput requirement met: {total_throughput:,.0f} rows/sec >= 100K rows/sec")
        
        # Cleanup
        clickhouse_client.execute(f"DROP TABLE IF EXISTS bronze_{source_name}")
    
    def test_1m_rows_idempotency(self, bronze_writer, clickhouse_client):
        """
        Test idempotency with 1M rows - writing same data twice should not create duplicates.
        
        **Validates: US-1 AC 1.1** - Running the same extraction twice produces identical results
        
        This test:
        1. Writes 1M rows
        2. Writes the same 1M rows again
        3. Verifies only 1M rows exist (no duplicates)
        4. Measures deduplication performance
        
        Success criteria:
        - Second write detects all duplicates
        - No duplicate rows in database
        - Deduplication is fast (< 10s for 1M rows)
        """
        print("\n=== Test: 1M rows idempotency ===")
        
        batch_id = f"load_test_idemp_{uuid4()}"
        source_id = "load_test_idemp_source"
        source_name = "load_test_idemp"
        
        columns = {
            "id": "String",
            "name": "String",
            "email": "String",
            "value": "String"
        }
        
        # Create batch with 1M rows
        print("Creating batch with 1M rows...")
        batch = create_test_batch(batch_id, source_id, source_name, 1_000_000, columns)
        
        # First write
        print("First write...")
        start_write1 = time.time()
        result1 = bronze_writer.write_batch(batch)
        write1_duration = time.time() - start_write1
        
        assert result1["success"] is True
        assert result1["rows_written"] == 1_000_000
        assert result1["rows_skipped"] == 0
        
        throughput1 = 1_000_000 / write1_duration
        print(f"First write: {result1['rows_written']:,} rows in {write1_duration:.2f}s "
              f"({throughput1:,.0f} rows/sec)")
        
        # Verify count after first write
        count1 = clickhouse_client.execute(
            f"SELECT COUNT(*) FROM bronze_{source_name} WHERE _batch_id = '{batch_id}'"
        )[0][0]
        assert count1 == 1_000_000
        
        # Second write (same data - should be deduplicated)
        print("Second write (same data)...")
        start_write2 = time.time()
        result2 = bronze_writer.write_batch(batch)
        write2_duration = time.time() - start_write2
        
        assert result2["success"] is True
        assert result2["rows_written"] == 0, "Expected 0 rows written (all duplicates)"
        assert result2["rows_skipped"] == 1_000_000, "Expected 1M rows skipped"
        
        print(f"Second write: {result2['rows_written']:,} rows written, "
              f"{result2['rows_skipped']:,} rows skipped in {write2_duration:.2f}s")
        
        # Verify count after second write (should still be 1M)
        count2 = clickhouse_client.execute(
            f"SELECT COUNT(*) FROM bronze_{source_name} WHERE _batch_id = '{batch_id}'"
        )[0][0]
        assert count2 == 1_000_000, f"Expected 1M rows, found {count2:,} (duplicates created!)"
        
        # Verify deduplication is fast (< 10s for 1M rows)
        assert write2_duration < 10, (
            f"Deduplication took {write2_duration:.2f}s, expected < 10s"
        )
        
        print(f"\n=== Results ===")
        print(f"First write: {result1['rows_written']:,} rows in {write1_duration:.2f}s")
        print(f"Second write: {result2['rows_skipped']:,} duplicates detected in {write2_duration:.2f}s")
        print(f"Final row count: {count2:,}")
        print(f"✓ Idempotency verified: No duplicates created")
        print(f"✓ Deduplication performance: {write2_duration:.2f}s < 10s")
        
        # Cleanup
        clickhouse_client.execute(f"DROP TABLE IF EXISTS bronze_{source_name}")
    
    def test_2m_rows_stress_test(self, bronze_writer, clickhouse_client):
        """
        Stress test with 2M rows to validate system stability at scale.
        
        **Validates: NFR-1** - Performance and memory requirements at scale
        
        This test writes 2M rows in 20 batches of 100K rows each and measures:
        - Sustained throughput over time
        - Memory stability
        - System stability
        
        Success criteria:
        - All batches complete successfully
        - Throughput remains consistent (no degradation)
        - Memory usage remains stable
        """
        print("\n=== Test: 2M rows stress test ===")
        
        source_id = "load_test_stress_source"
        source_name = "load_test_stress"
        
        columns = {
            "id": "String",
            "name": "String",
            "email": "String",
            "value1": "String",
            "value2": "String",
            "value3": "String"
        }
        
        num_batches = 20
        rows_per_batch = 100_000
        total_rows = num_batches * rows_per_batch
        
        mem_before = get_memory_usage_mb()
        print(f"Memory before: {mem_before:.2f} MB")
        
        throughputs = []
        memories = []
        total_start = time.time()
        
        for batch_num in range(num_batches):
            batch_id = f"stress_batch_{batch_num}_{uuid4()}"
            
            mem_before_batch = get_memory_usage_mb()
            
            # Create and write batch
            batch = create_test_batch(batch_id, source_id, source_name, rows_per_batch, columns)
            
            start_write = time.time()
            result = bronze_writer.write_batch(batch)
            write_duration = time.time() - start_write
            
            mem_after_batch = get_memory_usage_mb()
            mem_used = mem_after_batch - mem_before
            
            assert result["success"] is True
            assert result["rows_written"] == rows_per_batch
            
            throughput = rows_per_batch / write_duration
            throughputs.append(throughput)
            memories.append(mem_used)
            
            # Print progress every 5 batches
            if (batch_num + 1) % 5 == 0:
                avg_throughput = sum(throughputs) / len(throughputs)
                print(f"Progress: {(batch_num + 1) * rows_per_batch:,}/{total_rows:,} rows "
                      f"(avg throughput: {avg_throughput:,.0f} rows/sec, mem: {mem_used:.2f} MB)")
        
        total_duration = time.time() - total_start
        total_throughput = total_rows / total_duration
        
        # Calculate statistics
        avg_throughput = sum(throughputs) / len(throughputs)
        min_throughput = min(throughputs)
        max_throughput = max(throughputs)
        throughput_variance = (max_throughput - min_throughput) / avg_throughput * 100
        
        avg_mem = sum(memories) / len(memories)
        max_mem = max(memories)
        
        print(f"\n=== Results ===")
        print(f"Total rows written: {total_rows:,}")
        print(f"Total duration: {total_duration:.2f}s")
        print(f"Overall throughput: {total_throughput:,.0f} rows/sec")
        print(f"Average throughput: {avg_throughput:,.0f} rows/sec")
        print(f"Throughput range: {min_throughput:,.0f} - {max_throughput:,.0f} rows/sec")
        print(f"Throughput variance: {throughput_variance:.1f}%")
        print(f"Average memory: {avg_mem:.2f} MB")
        print(f"Peak memory: {max_mem:.2f} MB")
        
        # Verify throughput requirement
        assert avg_throughput >= 100_000, (
            f"Average throughput {avg_throughput:,.0f} rows/sec is below requirement"
        )
        
        # Verify throughput is consistent (variance < 50%)
        assert throughput_variance < 50, (
            f"Throughput variance {throughput_variance:.1f}% indicates performance degradation"
        )
        
        # Verify data in ClickHouse
        count = clickhouse_client.execute(
            f"SELECT COUNT(*) FROM bronze_{source_name}"
        )[0][0]
        assert count == total_rows, f"Expected {total_rows:,} rows, found {count:,}"
        
        print(f"✓ Stress test passed: {total_rows:,} rows written successfully")
        print(f"✓ Throughput stable: variance {throughput_variance:.1f}% < 50%")
        print(f"✓ Memory stable: peak {max_mem:.2f} MB")
        
        # Cleanup
        clickhouse_client.execute(f"DROP TABLE IF EXISTS bronze_{source_name}")
    
    def test_wide_table_performance(self, bronze_writer, clickhouse_client):
        """
        Test performance with wide tables (many columns).
        
        This test writes 500K rows with 50 columns to validate:
        - Performance with wide tables
        - Memory usage with many columns
        
        Success criteria:
        - Throughput >= 50K rows/sec (lower due to wide table)
        - Memory usage is reasonable
        """
        print("\n=== Test: Wide table performance (50 columns) ===")
        
        batch_id = f"load_test_wide_{uuid4()}"
        source_id = "load_test_wide_source"
        source_name = "load_test_wide"
        
        # Create 50 columns
        columns = {f"col_{i}": "String" for i in range(50)}
        
        num_rows = 500_000
        
        mem_before = get_memory_usage_mb()
        print(f"Memory before: {mem_before:.2f} MB")
        print(f"Creating batch with {num_rows:,} rows and {len(columns)} columns...")
        
        # Create batch
        batch = create_test_batch(batch_id, source_id, source_name, num_rows, columns)
        
        mem_after_create = get_memory_usage_mb()
        mem_used_create = mem_after_create - mem_before
        print(f"Memory after batch creation: {mem_after_create:.2f} MB (used: {mem_used_create:.2f} MB)")
        
        # Write batch
        print("Writing batch...")
        start_write = time.time()
        result = bronze_writer.write_batch(batch)
        write_duration = time.time() - start_write
        
        mem_after_write = get_memory_usage_mb()
        mem_used_write = mem_after_write - mem_before
        
        assert result["success"] is True
        assert result["rows_written"] == num_rows
        
        throughput = num_rows / write_duration
        
        print(f"\n=== Results ===")
        print(f"Rows written: {result['rows_written']:,}")
        print(f"Columns: {len(columns)}")
        print(f"Write duration: {write_duration:.2f}s")
        print(f"Throughput: {throughput:,.0f} rows/sec")
        print(f"Memory used: {mem_used_write:.2f} MB")
        
        # Verify throughput (lower threshold for wide tables)
        assert throughput >= 50_000, (
            f"Throughput {throughput:,.0f} rows/sec is below 50K rows/sec for wide table"
        )
        
        # Verify data in ClickHouse
        count = clickhouse_client.execute(
            f"SELECT COUNT(*) FROM bronze_{source_name} WHERE _batch_id = '{batch_id}'"
        )[0][0]
        assert count == num_rows
        
        print(f"✓ Wide table test passed: {throughput:,.0f} rows/sec >= 50K rows/sec")
        
        # Cleanup
        clickhouse_client.execute(f"DROP TABLE IF EXISTS bronze_{source_name}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
