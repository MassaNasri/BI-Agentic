"""
Comprehensive Idempotency Integration Tests for Bronze Layer Extraction

Tests that validate:
- US-1 (AC 1.1): Running the same extraction twice produces identical results
- US-1 (AC 1.3): Failed operations can be safely retried without data corruption

This test suite verifies end-to-end idempotency by:
1. Running extraction twice on the same data
2. Verifying no duplicate rows are created in bronze layer
3. Testing retry scenarios after failures
4. Validating deduplication across different batch IDs
5. Testing concurrent extraction scenarios
"""
import unittest
import tempfile
import os
import pandas as pd
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import Mock, patch, MagicMock
from clickhouse_driver import Client

import sys
# Add paths for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
shared_dir = os.path.join(current_dir, '../../../shared')
sys.path.insert(0, shared_dir)

from utils.idempotency_manager import IdempotencyManager, IdempotencyKey, PipelineStage
from utils.bronze_writer import BronzeWriter
from models.bronze_schema import BronzeRow, BronzeBatch, BronzeTableSchema


class TestIdempotencyIntegration(unittest.TestCase):
    """
    Integration tests for idempotency in extraction and bronze layer writes.
    
    These tests use a real ClickHouse client (or mock if unavailable) to verify
    that running the same extraction multiple times does not create duplicates.
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up test ClickHouse connection."""
        try:
            cls.clickhouse_client = Client(
                host=os.getenv('CLICKHOUSE_HOST', 'localhost'),
                port=int(os.getenv('CLICKHOUSE_PORT', '9000')),
                user=os.getenv('CLICKHOUSE_USER', 'default'),
                password=os.getenv('CLICKHOUSE_PASSWORD', ''),
                database=os.getenv('CLICKHOUSE_DATABASE', 'etl_test')
            )
            cls.use_real_clickhouse = True
            print("[TEST] Using real ClickHouse connection")
        except Exception as e:
            print(f"[TEST] ClickHouse not available, using mock: {e}")
            cls.use_real_clickhouse = False
            cls.clickhouse_client = None
    
    def setUp(self):
        """Set up test fixtures."""
        if self.use_real_clickhouse:
            # Clean up test tables
            try:
                self.clickhouse_client.execute("DROP TABLE IF EXISTS bronze_test_customers")
                self.clickhouse_client.execute("DROP TABLE IF EXISTS deduplication_log")
            except Exception as e:
                print(f"[TEST] Warning: Could not clean up tables: {e}")
            
            # Create deduplication_log table
            self._create_deduplication_table()
        else:
            # Use mock client
            self.clickhouse_client = Mock()
            self._setup_mock_client()
        
        # Initialize managers
        self.idempotency_manager = IdempotencyManager(self.clickhouse_client)
        self.bronze_writer = BronzeWriter(
            self.clickhouse_client,
            self.idempotency_manager,
            enable_deduplication=True
        )
    
    def _create_deduplication_table(self):
        """Create deduplication_log table for testing."""
        create_sql = """
        CREATE TABLE IF NOT EXISTS deduplication_log (
            _dedup_key String,
            _batch_id String,
            _stage String,
            _processed_at DateTime64(3),
            _row_id String
        ) ENGINE = ReplacingMergeTree(_processed_at)
        PARTITION BY toYYYYMM(_processed_at)
        ORDER BY (_dedup_key, _stage)
        """
        self.clickhouse_client.execute(create_sql)
    
    def _setup_mock_client(self):
        """Set up mock ClickHouse client for testing without real database."""
        self.mock_dedup_store = {}  # Store dedup keys
        self.mock_bronze_store = {}  # Store bronze rows
        
        def mock_execute(query, params=None):
            # Handle different query types
            if 'SELECT COUNT' in query and 'deduplication_log' in query:
                # Check for duplicates
                dedup_key = params.get('dedup_key', '')
                stage = params.get('stage', '')
                key = f"{dedup_key}:{stage}"
                count = 1 if key in self.mock_dedup_store else 0
                return [[count]]
            
            elif 'INSERT INTO deduplication_log' in query:
                # Mark as processed
                if params and isinstance(params, list):
                    for row in params:
                        dedup_key = row.get('_dedup_key', '')
                        stage = row.get('_stage', '')
                        key = f"{dedup_key}:{stage}"
                        self.mock_dedup_store[key] = row
                return None
            
            elif 'EXISTS TABLE' in query:
                # Table exists check
                return [[0]]  # Table doesn't exist
            
            elif 'CREATE TABLE' in query:
                # Table creation
                return None
            
            elif 'INSERT INTO bronze_' in query:
                # Bronze table insert
                if params and isinstance(params, list):
                    for row in params:
                        batch_id = row.get('_batch_id', '')
                        row_id = row.get('_row_id', '')
                        key = f"{batch_id}:{row_id}"
                        self.mock_bronze_store[key] = row
                return None
            
            elif 'SELECT COUNT' in query and 'bronze_' in query:
                # Count rows in bronze table
                batch_id = params.get('batch_id', '') if params else ''
                count = sum(1 for k in self.mock_bronze_store.keys() if k.startswith(batch_id))
                return [[count]]
            
            return None
        
        self.clickhouse_client.execute = Mock(side_effect=mock_execute)
    
    def test_extract_same_data_twice_no_duplicates(self):
        """
        Test AC 1.1: Running the same extraction twice produces identical results.
        
        Scenario:
        1. Extract data from CSV file (batch 1)
        2. Extract same data again (batch 2)
        3. Verify no duplicate rows in bronze layer
        """
        # Create test data
        test_data = pd.DataFrame({
            'customer_id': [1, 2, 3],
            'name': ['Alice', 'Bob', 'Charlie'],
            'email': ['alice@example.com', 'bob@example.com', 'charlie@example.com']
        })
        
        # Create bronze rows for first extraction
        batch_id_1 = str(uuid4())
        source_id = "test_customers.csv"
        
        rows_batch_1 = []
        for idx, row in test_data.iterrows():
            bronze_row = BronzeRow(
                batch_id=batch_id_1,
                source_id=source_id,
                extracted_at=datetime.now(timezone.utc),
                data=row.to_dict(),
                row_number=idx
            )
            rows_batch_1.append(bronze_row)
        
        # Create schema
        schema = BronzeTableSchema(
            source_name="test_customers",
            data_columns={
                'customer_id': 'String',
                'name': 'String',
                'email': 'String'
            }
        )
        
        # First extraction
        batch_1 = BronzeBatch(
            batch_id=batch_id_1,
            source_id=source_id,
            rows=rows_batch_1,
            schema=schema
        )
        
        result_1 = self.bronze_writer.write_batch(batch_1)
        
        # Verify first extraction succeeded
        self.assertTrue(result_1['success'], f"First extraction failed: {result_1.get('error')}")
        self.assertEqual(result_1['rows_written'], 3, "Should write 3 rows on first extraction")
        self.assertEqual(result_1['rows_skipped'], 0, "Should skip 0 rows on first extraction")
        
        # Second extraction - same data, different batch ID
        batch_id_2 = str(uuid4())
        
        rows_batch_2 = []
        for idx, row in test_data.iterrows():
            bronze_row = BronzeRow(
                batch_id=batch_id_2,
                source_id=source_id,
                extracted_at=datetime.now(timezone.utc),
                data=row.to_dict(),
                row_number=idx
            )
            rows_batch_2.append(bronze_row)
        
        batch_2 = BronzeBatch(
            batch_id=batch_id_2,
            source_id=source_id,
            rows=rows_batch_2,
            schema=schema
        )
        
        result_2 = self.bronze_writer.write_batch(batch_2)
        
        # Verify second extraction detected duplicates
        self.assertTrue(result_2['success'], f"Second extraction failed: {result_2.get('error')}")
        self.assertEqual(result_2['rows_written'], 0, "Should write 0 rows on second extraction (all duplicates)")
        self.assertEqual(result_2['rows_skipped'], 3, "Should skip 3 duplicate rows on second extraction")
        
        print("[TEST] ✓ AC 1.1 validated: Running same extraction twice produces no duplicates")
    
    def test_retry_after_failure_no_duplicates(self):
        """
        Test AC 1.3: Failed operations can be safely retried without data corruption.
        
        Scenario:
        1. Start extraction (batch 1)
        2. Process 2 rows successfully
        3. Simulate failure on 3rd row
        4. Retry extraction (batch 2)
        5. Verify only the failed row is processed, no duplicates
        """
        # Create test data
        test_data = pd.DataFrame({
            'id': [1, 2, 3],
            'value': ['A', 'B', 'C']
        })
        
        batch_id = str(uuid4())
        source_id = "test_retry.csv"
        
        # Process first 2 rows successfully
        rows_partial = []
        for idx in range(2):
            row = test_data.iloc[idx]
            bronze_row = BronzeRow(
                batch_id=batch_id,
                source_id=source_id,
                extracted_at=datetime.now(timezone.utc),
                data=row.to_dict(),
                row_number=idx
            )
            rows_partial.append(bronze_row)
        
        schema = BronzeTableSchema(
            source_name="test_retry",
            data_columns={'id': 'String', 'value': 'String'}
        )
        
        batch_partial = BronzeBatch(
            batch_id=batch_id,
            source_id=source_id,
            rows=rows_partial,
            schema=schema
        )
        
        result_partial = self.bronze_writer.write_batch(batch_partial)
        self.assertTrue(result_partial['success'])
        self.assertEqual(result_partial['rows_written'], 2)
        
        # Retry with all 3 rows (simulating retry after failure)
        rows_full = []
        for idx, row in test_data.iterrows():
            bronze_row = BronzeRow(
                batch_id=batch_id,
                source_id=source_id,
                extracted_at=datetime.now(timezone.utc),
                data=row.to_dict(),
                row_number=idx
            )
            rows_full.append(bronze_row)
        
        batch_full = BronzeBatch(
            batch_id=batch_id,
            source_id=source_id,
            rows=rows_full,
            schema=schema
        )
        
        result_retry = self.bronze_writer.write_batch(batch_full)
        
        # Verify only the new row (3rd) is written
        self.assertTrue(result_retry['success'])
        self.assertEqual(result_retry['rows_written'], 1, "Should write only 1 new row on retry")
        self.assertEqual(result_retry['rows_skipped'], 2, "Should skip 2 already-processed rows")
        
        print("[TEST] ✓ AC 1.3 validated: Failed operations can be safely retried")
    
    def test_same_content_different_batches_detected_as_duplicate(self):
        """
        Test that identical row content is detected as duplicate even across different batches.
        
        This validates that deduplication is based on row content hash, not batch ID.
        """
        source_id = "test_source"
        
        # Create identical row in two different batches
        row_data = {'id': 1, 'name': 'Test', 'value': 100}
        
        # Batch 1
        batch_id_1 = str(uuid4())
        row_1 = BronzeRow(
            batch_id=batch_id_1,
            source_id=source_id,
            extracted_at=datetime.now(timezone.utc),
            data=row_data,
            row_number=0
        )
        
        schema = BronzeTableSchema(
            source_name="test_dedup",
            data_columns={'id': 'String', 'name': 'String', 'value': 'String'}
        )
        
        batch_1 = BronzeBatch(
            batch_id=batch_id_1,
            source_id=source_id,
            rows=[row_1],
            schema=schema
        )
        
        result_1 = self.bronze_writer.write_batch(batch_1)
        self.assertTrue(result_1['success'])
        self.assertEqual(result_1['rows_written'], 1)
        
        # Batch 2 - same content, different batch ID
        batch_id_2 = str(uuid4())
        row_2 = BronzeRow(
            batch_id=batch_id_2,
            source_id=source_id,
            extracted_at=datetime.now(timezone.utc),
            data=row_data,  # Same data
            row_number=0
        )
        
        batch_2 = BronzeBatch(
            batch_id=batch_id_2,
            source_id=source_id,
            rows=[row_2],
            schema=schema
        )
        
        result_2 = self.bronze_writer.write_batch(batch_2)
        
        # Verify duplicate detected despite different batch ID
        self.assertTrue(result_2['success'])
        self.assertEqual(result_2['rows_written'], 0, "Should not write duplicate row")
        self.assertEqual(result_2['rows_skipped'], 1, "Should skip duplicate row")
        
        print("[TEST] ✓ Deduplication works across different batch IDs")
    
    def test_different_content_not_detected_as_duplicate(self):
        """
        Test that different row content is NOT detected as duplicate.
        
        This validates that deduplication correctly distinguishes different rows.
        """
        source_id = "test_source"
        batch_id = str(uuid4())
        
        # Create two different rows
        row_1_data = {'id': 1, 'name': 'Alice', 'value': 100}
        row_2_data = {'id': 2, 'name': 'Bob', 'value': 200}
        
        row_1 = BronzeRow(
            batch_id=batch_id,
            source_id=source_id,
            extracted_at=datetime.now(timezone.utc),
            data=row_1_data,
            row_number=0
        )
        
        row_2 = BronzeRow(
            batch_id=batch_id,
            source_id=source_id,
            extracted_at=datetime.now(timezone.utc),
            data=row_2_data,
            row_number=1
        )
        
        schema = BronzeTableSchema(
            source_name="test_unique",
            data_columns={'id': 'String', 'name': 'String', 'value': 'String'}
        )
        
        batch = BronzeBatch(
            batch_id=batch_id,
            source_id=source_id,
            rows=[row_1, row_2],
            schema=schema
        )
        
        result = self.bronze_writer.write_batch(batch)
        
        # Verify both rows written (no duplicates)
        self.assertTrue(result['success'])
        self.assertEqual(result['rows_written'], 2, "Should write both unique rows")
        self.assertEqual(result['rows_skipped'], 0, "Should skip 0 rows")
        
        print("[TEST] ✓ Different content correctly identified as unique")
    
    def test_partial_batch_duplicate_detection(self):
        """
        Test that in a batch with mixed duplicate and new rows, only new rows are written.
        
        Scenario:
        1. Write batch with rows A, B, C
        2. Write batch with rows B, C, D (B and C are duplicates, D is new)
        3. Verify only D is written
        """
        source_id = "test_partial"
        
        # First batch: A, B, C
        batch_id_1 = str(uuid4())
        rows_1 = []
        for i, name in enumerate(['Alice', 'Bob', 'Charlie']):
            row = BronzeRow(
                batch_id=batch_id_1,
                source_id=source_id,
                extracted_at=datetime.now(timezone.utc),
                data={'id': i+1, 'name': name},
                row_number=i
            )
            rows_1.append(row)
        
        schema = BronzeTableSchema(
            source_name="test_partial",
            data_columns={'id': 'String', 'name': 'String'}
        )
        
        batch_1 = BronzeBatch(
            batch_id=batch_id_1,
            source_id=source_id,
            rows=rows_1,
            schema=schema
        )
        
        result_1 = self.bronze_writer.write_batch(batch_1)
        self.assertTrue(result_1['success'])
        self.assertEqual(result_1['rows_written'], 3)
        
        # Second batch: B, C, D (B and C are duplicates)
        batch_id_2 = str(uuid4())
        rows_2 = []
        for i, name in enumerate(['Bob', 'Charlie', 'David']):
            row = BronzeRow(
                batch_id=batch_id_2,
                source_id=source_id,
                extracted_at=datetime.now(timezone.utc),
                data={'id': i+2, 'name': name},  # IDs 2, 3, 4
                row_number=i
            )
            rows_2.append(row)
        
        batch_2 = BronzeBatch(
            batch_id=batch_id_2,
            source_id=source_id,
            rows=rows_2,
            schema=schema
        )
        
        result_2 = self.bronze_writer.write_batch(batch_2)
        
        # Verify only David (new row) is written
        self.assertTrue(result_2['success'])
        self.assertEqual(result_2['rows_written'], 1, "Should write only 1 new row (David)")
        self.assertEqual(result_2['rows_skipped'], 2, "Should skip 2 duplicate rows (Bob, Charlie)")
        
        print("[TEST] ✓ Partial batch duplicate detection works correctly")
    
    def test_idempotency_with_deduplication_disabled(self):
        """
        Test that when deduplication is disabled, all rows are written (including duplicates).
        
        This validates the enable_deduplication flag works correctly.
        """
        # Create writer with deduplication disabled
        writer_no_dedup = BronzeWriter(
            self.clickhouse_client,
            self.idempotency_manager,
            enable_deduplication=False
        )
        
        source_id = "test_no_dedup"
        row_data = {'id': 1, 'value': 'test'}
        
        # Write same row twice
        for i in range(2):
            batch_id = str(uuid4())
            row = BronzeRow(
                batch_id=batch_id,
                source_id=source_id,
                extracted_at=datetime.now(timezone.utc),
                data=row_data,
                row_number=0
            )
            
            schema = BronzeTableSchema(
                source_name="test_no_dedup",
                data_columns={'id': 'String', 'value': 'String'}
            )
            
            batch = BronzeBatch(
                batch_id=batch_id,
                source_id=source_id,
                rows=[row],
                schema=schema
            )
            
            result = writer_no_dedup.write_batch(batch)
            
            # Both writes should succeed (no deduplication)
            self.assertTrue(result['success'])
            self.assertEqual(result['rows_written'], 1, f"Write {i+1} should succeed")
            self.assertEqual(result['rows_skipped'], 0, f"Write {i+1} should skip 0 rows")
        
        print("[TEST] ✓ Deduplication can be disabled when needed")
    
    def test_hash_determinism(self):
        """
        Test that the same row content always produces the same hash.
        
        This is critical for idempotency - the hash must be deterministic.
        """
        row_data = {
            'id': 1,
            'name': 'Test',
            'email': 'test@example.com',
            'age': 30
        }
        
        # Generate hash multiple times
        hashes = []
        for _ in range(5):
            hash_value = self.idempotency_manager.generate_row_hash(row_data)
            hashes.append(hash_value)
        
        # Verify all hashes are identical
        self.assertEqual(len(set(hashes)), 1, "Hash should be deterministic")
        self.assertEqual(len(hashes[0]), 64, "SHA256 hash should be 64 characters")
        
        print("[TEST] ✓ Row hash generation is deterministic")
    
    def test_hash_independence_from_key_order(self):
        """
        Test that row hash is independent of dictionary key order.
        
        This ensures that {'a': 1, 'b': 2} and {'b': 2, 'a': 1} produce the same hash.
        """
        row_1 = {'id': 1, 'name': 'Test', 'value': 100}
        row_2 = {'value': 100, 'id': 1, 'name': 'Test'}
        row_3 = {'name': 'Test', 'value': 100, 'id': 1}
        
        hash_1 = self.idempotency_manager.generate_row_hash(row_1)
        hash_2 = self.idempotency_manager.generate_row_hash(row_2)
        hash_3 = self.idempotency_manager.generate_row_hash(row_3)
        
        self.assertEqual(hash_1, hash_2, "Hash should be independent of key order")
        self.assertEqual(hash_2, hash_3, "Hash should be independent of key order")
        
        print("[TEST] ✓ Row hash is independent of dictionary key order")
    
    def test_large_batch_idempotency(self):
        """
        Test idempotency with a large batch of rows (1000+ rows).
        
        This validates performance and correctness at scale.
        """
        source_id = "test_large_batch"
        batch_id = str(uuid4())
        
        # Create 1000 rows
        num_rows = 1000
        rows = []
        for i in range(num_rows):
            row = BronzeRow(
                batch_id=batch_id,
                source_id=source_id,
                extracted_at=datetime.now(timezone.utc),
                data={'id': i, 'value': f'value_{i}'},
                row_number=i
            )
            rows.append(row)
        
        schema = BronzeTableSchema(
            source_name="test_large",
            data_columns={'id': 'String', 'value': 'String'}
        )
        
        batch = BronzeBatch(
            batch_id=batch_id,
            source_id=source_id,
            rows=rows,
            schema=schema
        )
        
        # First write
        result_1 = self.bronze_writer.write_batch(batch)
        self.assertTrue(result_1['success'])
        self.assertEqual(result_1['rows_written'], num_rows)
        
        # Second write - all should be duplicates
        result_2 = self.bronze_writer.write_batch(batch)
        self.assertTrue(result_2['success'])
        self.assertEqual(result_2['rows_written'], 0, "Should write 0 rows on second attempt")
        self.assertEqual(result_2['rows_skipped'], num_rows, f"Should skip all {num_rows} duplicate rows")
        
        print(f"[TEST] ✓ Idempotency works correctly with {num_rows} rows")


class TestIdempotencyEdgeCases(unittest.TestCase):
    """Test edge cases and error scenarios for idempotency."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_client = Mock()
        self.idempotency_manager = IdempotencyManager(self.mock_client)
    
    def test_empty_row_hash(self):
        """Test hash generation for empty row."""
        empty_row = {}
        hash_value = self.idempotency_manager.generate_row_hash(empty_row)
        
        self.assertIsNotNone(hash_value)
        self.assertEqual(len(hash_value), 64)
        
        print("[TEST] ✓ Empty row hash generation works")
    
    def test_row_with_none_values(self):
        """Test hash generation for row with None values."""
        row = {'id': 1, 'name': None, 'value': 'test'}
        hash_value = self.idempotency_manager.generate_row_hash(row)
        
        self.assertIsNotNone(hash_value)
        self.assertEqual(len(hash_value), 64)
        
        # Verify None is treated differently from missing key
        row_without_name = {'id': 1, 'value': 'test'}
        hash_without = self.idempotency_manager.generate_row_hash(row_without_name)
        
        self.assertNotEqual(hash_value, hash_without, "None value should differ from missing key")
        
        print("[TEST] ✓ Row with None values handled correctly")
    
    def test_row_with_special_characters(self):
        """Test hash generation for row with special characters."""
        row = {
            'id': 1,
            'name': "O'Brien",
            'email': 'test@example.com',
            'notes': 'Special chars: \n\t\r"\'\\',
            'unicode': '你好世界'
        }
        
        hash_value = self.idempotency_manager.generate_row_hash(row)
        
        self.assertIsNotNone(hash_value)
        self.assertEqual(len(hash_value), 64)
        
        print("[TEST] ✓ Row with special characters handled correctly")
    
    def test_row_with_nested_structures(self):
        """Test hash generation for row with nested dictionaries/lists."""
        row = {
            'id': 1,
            'metadata': {'created': '2024-01-01', 'tags': ['a', 'b', 'c']},
            'values': [1, 2, 3]
        }
        
        hash_value = self.idempotency_manager.generate_row_hash(row)
        
        self.assertIsNotNone(hash_value)
        self.assertEqual(len(hash_value), 64)
        
        print("[TEST] ✓ Row with nested structures handled correctly")


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
