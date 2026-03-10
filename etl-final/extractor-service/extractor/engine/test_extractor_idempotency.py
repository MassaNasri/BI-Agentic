"""
Tests for Extractor Service Idempotency Integration

Validates:
- AC 1.1: Running the same extraction twice produces identical results
- AC 1.3: Failed operations can be safely retried without data corruption
- Duplicate detection works correctly
- Rows are marked as processed after successful extraction
"""
import unittest
from unittest.mock import Mock, MagicMock, patch, call
from uuid import uuid4
import pandas as pd
import tempfile
import os
from datetime import datetime

from .kafka_listener import ConnectionListener
from shared.utils.idempotency_manager import IdempotencyManager, IdempotencyKey, PipelineStage


class TestExtractorIdempotency(unittest.TestCase):
    """Test idempotency integration in extractor service."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock ClickHouse client
        self.mock_clickhouse_client = Mock()
        
        # Mock Kafka components
        self.mock_consumer = Mock()
        self.mock_producer = Mock()
        self.mock_producer.send = Mock(return_value=True)
        
        # Create listener with mocked dependencies
        with patch('engine.kafka_listener.KafkaMessageConsumer', return_value=self.mock_consumer), \
             patch('engine.kafka_listener.KafkaMessageProducer', return_value=self.mock_producer), \
             patch('engine.kafka_listener.Client', return_value=self.mock_clickhouse_client):
            self.listener = ConnectionListener()
    
    def test_idempotency_manager_initialized_with_clickhouse_client(self):
        """Test that IdempotencyManager is initialized with ClickHouse client."""
        self.assertIsNotNone(self.listener.idempotency_manager)
        self.assertEqual(self.listener.idempotency_manager.client, self.mock_clickhouse_client)
    
    def test_duplicate_rows_are_skipped_in_file_extraction(self):
        """
        Test AC 1.1: Running the same extraction twice produces identical results.
        Duplicate rows should be skipped on second extraction.
        """
        # Create a temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("name,age,city\n")
            f.write("Alice,30,NYC\n")
            f.write("Bob,25,LA\n")
            temp_file = f.name
        
        try:
            message = {
                "type": "file",
                "filename": "test.csv",
                "path": temp_file
            }
            
            # Mock is_duplicate to return False for first extraction, True for second
            call_count = [0]
            def mock_is_duplicate(key, stage):
                call_count[0] += 1
                # First two calls (Alice, Bob) return False (not duplicate)
                # Next two calls return True (duplicate)
                return call_count[0] > 2
            
            self.listener.idempotency_manager.is_duplicate = Mock(side_effect=mock_is_duplicate)
            self.listener.idempotency_manager.mark_processed = Mock(return_value=True)
            
            # First extraction - should process all rows
            self.listener.process_file(message)
            
            # Verify all rows were published
            published_calls = [call for call in self.mock_producer.send.call_args_list 
                             if call[0][0] == "extracted_rows_topic"]
            self.assertEqual(len(published_calls), 2, "Should publish 2 rows on first extraction")
            
            # Reset mock
            self.mock_producer.send.reset_mock()
            
            # Second extraction - should skip duplicates
            self.listener.process_file(message)
            
            # Verify no rows were published (all duplicates)
            published_calls = [call for call in self.mock_producer.send.call_args_list 
                             if call[0][0] == "extracted_rows_topic"]
            self.assertEqual(len(published_calls), 0, "Should skip all duplicate rows on second extraction")
            
        finally:
            os.unlink(temp_file)
    
    def test_rows_marked_as_processed_after_successful_publish(self):
        """Test that rows are marked as processed after successful Kafka publish."""
        # Create a temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("name,age\n")
            f.write("Alice,30\n")
            temp_file = f.name
        
        try:
            message = {
                "type": "file",
                "filename": "test.csv",
                "path": temp_file
            }
            
            # Mock idempotency methods
            self.listener.idempotency_manager.is_duplicate = Mock(return_value=False)
            self.listener.idempotency_manager.mark_processed = Mock(return_value=True)
            
            # Process file
            self.listener.process_file(message)
            
            # Verify mark_processed was called
            self.listener.idempotency_manager.mark_processed.assert_called()
            
            # Verify it was called with EXTRACT stage
            call_args = self.listener.idempotency_manager.mark_processed.call_args
            self.assertEqual(call_args[0][1], PipelineStage.EXTRACT)
            
        finally:
            os.unlink(temp_file)
    
    def test_failed_publish_does_not_mark_as_processed(self):
        """
        Test AC 1.3: Failed operations can be safely retried.
        If Kafka publish fails, row should not be marked as processed.
        """
        # Create a temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("name,age\n")
            f.write("Alice,30\n")
            temp_file = f.name
        
        try:
            message = {
                "type": "file",
                "filename": "test.csv",
                "path": temp_file
            }
            
            # Mock Kafka publish to fail
            self.mock_producer.send = Mock(return_value=False)
            
            # Mock idempotency methods
            self.listener.idempotency_manager.is_duplicate = Mock(return_value=False)
            self.listener.idempotency_manager.mark_processed = Mock(return_value=True)
            
            # Process file
            self.listener.process_file(message)
            
            # Verify mark_processed was NOT called (because publish failed)
            self.listener.idempotency_manager.mark_processed.assert_not_called()
            
        finally:
            os.unlink(temp_file)
    
    def test_deduplication_key_generated_for_each_row(self):
        """Test that deduplication key (SHA256 hash) is generated for each row."""
        # Create a temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("name,age\n")
            f.write("Alice,30\n")
            temp_file = f.name
        
        try:
            message = {
                "type": "file",
                "filename": "test.csv",
                "path": temp_file
            }
            
            # Mock idempotency methods
            self.listener.idempotency_manager.is_duplicate = Mock(return_value=False)
            self.listener.idempotency_manager.mark_processed = Mock(return_value=True)
            
            # Process file
            self.listener.process_file(message)
            
            # Verify row data includes _dedup_key
            published_calls = [call for call in self.mock_producer.send.call_args_list 
                             if call[0][0] == "extracted_rows_topic"]
            self.assertEqual(len(published_calls), 1)
            
            row_data = published_calls[0][0][1]
            self.assertIn("_dedup_key", row_data)
            self.assertEqual(len(row_data["_dedup_key"]), 64, "SHA256 hash should be 64 hex characters")
            
        finally:
            os.unlink(temp_file)
    
    def test_idempotency_check_uses_correct_stage(self):
        """Test that idempotency check uses EXTRACT stage."""
        # Create a temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("name,age\n")
            f.write("Alice,30\n")
            temp_file = f.name
        
        try:
            message = {
                "type": "file",
                "filename": "test.csv",
                "path": temp_file
            }
            
            # Mock idempotency methods
            self.listener.idempotency_manager.is_duplicate = Mock(return_value=False)
            self.listener.idempotency_manager.mark_processed = Mock(return_value=True)
            
            # Process file
            self.listener.process_file(message)
            
            # Verify is_duplicate was called with EXTRACT stage
            call_args = self.listener.idempotency_manager.is_duplicate.call_args
            self.assertEqual(call_args[0][1], PipelineStage.EXTRACT)
            
        finally:
            os.unlink(temp_file)
    
    def test_graceful_degradation_when_clickhouse_unavailable(self):
        """
        Test fail-open strategy: extraction continues even if ClickHouse is unavailable.
        """
        # Create listener without ClickHouse client
        with patch('engine.kafka_listener.KafkaMessageConsumer', return_value=self.mock_consumer), \
             patch('engine.kafka_listener.KafkaMessageProducer', return_value=self.mock_producer), \
             patch('engine.kafka_listener.Client', side_effect=Exception("ClickHouse unavailable")):
            listener = ConnectionListener()
        
        # Verify idempotency manager is None (graceful degradation)
        self.assertIsNone(listener.idempotency_manager)
        
        # Create a temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("name,age\n")
            f.write("Alice,30\n")
            temp_file = f.name
        
        try:
            message = {
                "type": "file",
                "filename": "test.csv",
                "path": temp_file
            }
            
            # Process file - should succeed despite no idempotency manager
            listener.process_file(message)
            
            # Verify row was published (extraction continues)
            published_calls = [call for call in self.mock_producer.send.call_args_list 
                             if call[0][0] == "extracted_rows_topic"]
            self.assertEqual(len(published_calls), 1, "Should publish row even without idempotency manager")
            
        finally:
            os.unlink(temp_file)
    
    def test_same_row_content_produces_same_hash(self):
        """Test that identical row content produces identical deduplication key."""
        # Create two temporary CSV files with identical content
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f1:
            f1.write("name,age\n")
            f1.write("Alice,30\n")
            temp_file1 = f1.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f2:
            f2.write("name,age\n")
            f2.write("Alice,30\n")
            temp_file2 = f2.name
        
        try:
            # Mock idempotency methods
            self.listener.idempotency_manager.is_duplicate = Mock(return_value=False)
            self.listener.idempotency_manager.mark_processed = Mock(return_value=True)
            
            # Process first file
            message1 = {"type": "file", "filename": "test1.csv", "path": temp_file1}
            self.listener.process_file(message1)
            
            # Get hash from first file
            published_calls1 = [call for call in self.mock_producer.send.call_args_list 
                               if call[0][0] == "extracted_rows_topic"]
            hash1 = published_calls1[0][0][1]["_dedup_key"]
            
            # Reset mock
            self.mock_producer.send.reset_mock()
            
            # Process second file
            message2 = {"type": "file", "filename": "test2.csv", "path": temp_file2}
            self.listener.process_file(message2)
            
            # Get hash from second file
            published_calls2 = [call for call in self.mock_producer.send.call_args_list 
                               if call[0][0] == "extracted_rows_topic"]
            hash2 = published_calls2[0][0][1]["_dedup_key"]
            
            # Verify hashes are identical
            self.assertEqual(hash1, hash2, "Identical row content should produce identical hash")
            
        finally:
            os.unlink(temp_file1)
            os.unlink(temp_file2)
    
    def test_different_row_content_produces_different_hash(self):
        """Test that different row content produces different deduplication keys."""
        # Create a temporary CSV file with two different rows
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("name,age\n")
            f.write("Alice,30\n")
            f.write("Bob,25\n")
            temp_file = f.name
        
        try:
            message = {"type": "file", "filename": "test.csv", "path": temp_file}
            
            # Mock idempotency methods
            self.listener.idempotency_manager.is_duplicate = Mock(return_value=False)
            self.listener.idempotency_manager.mark_processed = Mock(return_value=True)
            
            # Process file
            self.listener.process_file(message)
            
            # Get hashes from both rows
            published_calls = [call for call in self.mock_producer.send.call_args_list 
                             if call[0][0] == "extracted_rows_topic"]
            hash1 = published_calls[0][0][1]["_dedup_key"]
            hash2 = published_calls[1][0][1]["_dedup_key"]
            
            # Verify hashes are different
            self.assertNotEqual(hash1, hash2, "Different row content should produce different hashes")
            
        finally:
            os.unlink(temp_file)


class TestExtractorIdempotencyIntegration(unittest.TestCase):
    """Integration tests with real IdempotencyManager (mocked ClickHouse)."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock ClickHouse client
        self.mock_clickhouse_client = Mock()
        self.mock_clickhouse_client.execute = Mock(return_value=[[0]])  # No duplicates
        
        # Mock Kafka components
        self.mock_consumer = Mock()
        self.mock_producer = Mock()
        self.mock_producer.send = Mock(return_value=True)
        
        # Create listener with real IdempotencyManager but mocked ClickHouse
        with patch('engine.kafka_listener.KafkaMessageConsumer', return_value=self.mock_consumer), \
             patch('engine.kafka_listener.KafkaMessageProducer', return_value=self.mock_producer), \
             patch('engine.kafka_listener.Client', return_value=self.mock_clickhouse_client):
            self.listener = ConnectionListener()
    
    def test_end_to_end_idempotency_flow(self):
        """
        Test complete idempotency flow:
        1. Extract row
        2. Check for duplicate (not found)
        3. Publish to Kafka
        4. Mark as processed
        5. Extract same row again
        6. Check for duplicate (found)
        7. Skip row
        """
        # Create a temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("name,age\n")
            f.write("Alice,30\n")
            temp_file = f.name
        
        try:
            message = {"type": "file", "filename": "test.csv", "path": temp_file}
            
            # First extraction - no duplicates
            self.mock_clickhouse_client.execute = Mock(return_value=[[0]])
            self.listener.process_file(message)
            
            # Verify row was published
            published_calls = [call for call in self.mock_producer.send.call_args_list 
                             if call[0][0] == "extracted_rows_topic"]
            self.assertEqual(len(published_calls), 1)
            
            # Verify is_duplicate was checked (SELECT COUNT query)
            select_calls = [call for call in self.mock_clickhouse_client.execute.call_args_list
                          if 'SELECT COUNT' in str(call)]
            self.assertGreater(len(select_calls), 0, "Should check for duplicates")
            
            # Verify mark_processed was called (INSERT query)
            insert_calls = [call for call in self.mock_clickhouse_client.execute.call_args_list
                          if 'INSERT INTO deduplication_log' in str(call)]
            self.assertGreater(len(insert_calls), 0, "Should mark as processed")
            
            # Reset mocks
            self.mock_producer.send.reset_mock()
            self.mock_clickhouse_client.execute.reset_mock()
            
            # Second extraction - duplicate found
            self.mock_clickhouse_client.execute = Mock(return_value=[[1]])  # Duplicate found
            self.listener.process_file(message)
            
            # Verify row was NOT published (duplicate skipped)
            published_calls = [call for call in self.mock_producer.send.call_args_list 
                             if call[0][0] == "extracted_rows_topic"]
            self.assertEqual(len(published_calls), 0, "Should skip duplicate row")
            
        finally:
            os.unlink(temp_file)


if __name__ == '__main__':
    unittest.main()
