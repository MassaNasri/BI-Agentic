"""
Integration Tests for Progress Tracking with Extraction Strategies

Tests the integration of progress tracking with CSV and database extraction strategies.

Requirements:
- Task 2.2.6: Add extraction progress tracking
- US-9: Observability (AC 9.1: Structured logging with correlation IDs)
"""

import unittest
import tempfile
import os
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock

from extraction_strategy import ExtractionConfig
from csv_extraction_strategy import CSVExtractionStrategy
from database_extraction_strategy import DatabaseExtractionStrategy
from extraction_progress import ProgressTracker, ExtractionStatus


class TestCSVExtractionWithProgress(unittest.TestCase):
    """Test CSV extraction with progress tracking."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary CSV file
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv')
        self.temp_file.write("id,name,email\n")
        for i in range(100):
            self.temp_file.write(f"{i},User{i},user{i}@example.com\n")
        self.temp_file.close()
        
        # Create progress tracker
        self.tracker = ProgressTracker()
        
        # Create extraction strategy
        self.strategy = CSVExtractionStrategy()
    
    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
    
    def test_csv_extraction_with_progress_tracking(self):
        """Test CSV extraction updates progress correctly."""
        # Create config with progress tracker
        config = ExtractionConfig(
            source_id="test_csv",
            source_type="csv",
            connection_params={
                "file_path": self.temp_file.name,
                "encoding": "utf-8",
                "delimiter": ",",
                "has_header": True
            },
            batch_size=25,
            extraction_id="ext_csv_123",
            correlation_id="corr_csv_456",
            progress_tracker=self.tracker
        )
        
        # Start tracking
        self.tracker.start_extraction(
            extraction_id=config.extraction_id,
            source_id=config.source_id,
            source_type=config.source_type,
            correlation_id=config.correlation_id
        )
        
        # Extract first batch
        batch1 = self.strategy.extract_batch(config, offset=0, limit=25)
        
        # Check progress after first batch
        progress = self.tracker.get_progress(config.extraction_id)
        self.assertEqual(progress.rows_extracted, 25)
        self.assertEqual(progress.batches_processed, 1)
        self.assertEqual(progress.current_offset, 25)
        self.assertIsNotNone(progress.estimated_total_rows)
        self.assertEqual(progress.estimated_total_rows, 100)
        
        # Extract second batch
        batch2 = self.strategy.extract_batch(config, offset=25, limit=25)
        
        # Check progress after second batch
        progress = self.tracker.get_progress(config.extraction_id)
        self.assertEqual(progress.rows_extracted, 50)
        self.assertEqual(progress.batches_processed, 2)
        self.assertEqual(progress.current_offset, 50)
        
        # Extract third batch
        batch3 = self.strategy.extract_batch(config, offset=50, limit=25)
        
        # Check progress after third batch
        progress = self.tracker.get_progress(config.extraction_id)
        self.assertEqual(progress.rows_extracted, 75)
        self.assertEqual(progress.batches_processed, 3)
        
        # Extract fourth batch
        batch4 = self.strategy.extract_batch(config, offset=75, limit=25)
        
        # Check progress after fourth batch
        progress = self.tracker.get_progress(config.extraction_id)
        self.assertEqual(progress.rows_extracted, 100)
        self.assertEqual(progress.batches_processed, 4)
        
        # Complete extraction
        self.tracker.complete_extraction(config.extraction_id)
        
        # Verify final state
        progress = self.tracker.get_progress(config.extraction_id)
        self.assertEqual(progress.status, ExtractionStatus.COMPLETED)
        self.assertIsNotNone(progress.completed_at)
    
    def test_csv_extraction_progress_metrics(self):
        """Test progress metrics calculation during CSV extraction."""
        config = ExtractionConfig(
            source_id="test_csv",
            source_type="csv",
            connection_params={
                "file_path": self.temp_file.name,
                "encoding": "utf-8",
                "delimiter": ",",
                "has_header": True
            },
            batch_size=50,
            extraction_id="ext_csv_metrics",
            progress_tracker=self.tracker
        )
        
        # Start tracking
        self.tracker.start_extraction(
            extraction_id=config.extraction_id,
            source_id=config.source_id,
            source_type=config.source_type,
            estimated_total_rows=100
        )
        
        # Extract first batch
        batch = self.strategy.extract_batch(config, offset=0, limit=50)
        
        # Check metrics
        progress = self.tracker.get_progress(config.extraction_id)
        
        # Progress percentage should be 50%
        percentage = progress.get_progress_percentage()
        self.assertEqual(percentage, 50.0)
        
        # Throughput should be calculated
        throughput = progress.get_throughput()
        self.assertIsNotNone(throughput)
        self.assertGreater(throughput, 0)
        
        # Estimated completion should be calculated
        estimated = progress.estimate_completion_time()
        self.assertIsNotNone(estimated)
        self.assertGreater(estimated, progress.updated_at)


class TestDatabaseExtractionWithProgress(unittest.TestCase):
    """Test database extraction with progress tracking."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create mock database connection
        self.mock_connection = Mock()
        self.mock_cursor = Mock()
        self.mock_connection.cursor.return_value = self.mock_cursor
        
        # Mock cursor description for column names
        self.mock_cursor.description = [
            ('id',), ('name',), ('email',)
        ]
        
        # Create progress tracker
        self.tracker = ProgressTracker()
        
        # Create extraction strategy
        self.strategy = DatabaseExtractionStrategy()
    
    def test_database_extraction_with_progress_tracking(self):
        """Test database extraction updates progress correctly."""
        # Mock fetchall to return data
        self.mock_cursor.fetchall.return_value = [
            {'id': i, 'name': f'User{i}', 'email': f'user{i}@example.com'}
            for i in range(25)
        ]
        
        # Mock COUNT query for total rows estimation
        def execute_side_effect(query):
            if 'COUNT(*)' in query:
                self.mock_cursor.fetchone.return_value = {'total': 100}
            else:
                self.mock_cursor.fetchone.return_value = None
        
        self.mock_cursor.execute.side_effect = execute_side_effect
        
        # Create config with progress tracker
        config = ExtractionConfig(
            source_id="test_db",
            source_type="database",
            connection_params={
                "connection": self.mock_connection,
                "table": "users",
                "order_by": "id"
            },
            batch_size=25,
            extraction_id="ext_db_123",
            correlation_id="corr_db_456",
            progress_tracker=self.tracker
        )
        
        # Start tracking
        self.tracker.start_extraction(
            extraction_id=config.extraction_id,
            source_id=config.source_id,
            source_type=config.source_type,
            correlation_id=config.correlation_id
        )
        
        # Extract first batch
        batch = self.strategy.extract_batch(config, offset=0, limit=25)
        
        # Check progress after first batch
        progress = self.tracker.get_progress(config.extraction_id)
        self.assertEqual(progress.rows_extracted, 25)
        self.assertEqual(progress.batches_processed, 1)
        self.assertEqual(progress.current_offset, 25)
        self.assertIsNotNone(progress.estimated_total_rows)
        self.assertEqual(progress.estimated_total_rows, 100)
        
        # Verify correlation ID is tracked
        self.assertEqual(progress.correlation_id, "corr_db_456")
    
    def test_database_extraction_without_total_estimate(self):
        """Test database extraction when total row count cannot be estimated."""
        # Mock fetchall to return data
        self.mock_cursor.fetchall.return_value = [
            {'id': i, 'name': f'User{i}', 'email': f'user{i}@example.com'}
            for i in range(25)
        ]
        
        # Mock COUNT query to fail
        def execute_side_effect(query):
            if 'COUNT(*)' in query:
                raise Exception("COUNT query failed")
        
        self.mock_cursor.execute.side_effect = execute_side_effect
        
        config = ExtractionConfig(
            source_id="test_db",
            source_type="database",
            connection_params={
                "connection": self.mock_connection,
                "table": "users"
            },
            batch_size=25,
            extraction_id="ext_db_no_count",
            progress_tracker=self.tracker
        )
        
        # Start tracking
        self.tracker.start_extraction(
            extraction_id=config.extraction_id,
            source_id=config.source_id,
            source_type=config.source_type
        )
        
        # Reset side effect for actual extraction query
        self.mock_cursor.execute.side_effect = None
        
        # Extract batch
        batch = self.strategy.extract_batch(config, offset=0, limit=25)
        
        # Check progress
        progress = self.tracker.get_progress(config.extraction_id)
        self.assertEqual(progress.rows_extracted, 25)
        
        # Total should be None since COUNT failed
        # Progress percentage should also be None
        percentage = progress.get_progress_percentage()
        self.assertIsNone(percentage)


class TestProgressTrackingWithMultipleExtractions(unittest.TestCase):
    """Test progress tracking with multiple concurrent extractions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.tracker = ProgressTracker()
        
        # Create multiple temp CSV files
        self.temp_files = []
        for i in range(3):
            temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv')
            temp_file.write("id,value\n")
            for j in range(50):
                temp_file.write(f"{j},{j*10}\n")
            temp_file.close()
            self.temp_files.append(temp_file.name)
        
        self.strategy = CSVExtractionStrategy()
    
    def tearDown(self):
        """Clean up test fixtures."""
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_multiple_concurrent_extractions(self):
        """Test tracking multiple extractions simultaneously."""
        configs = []
        
        # Start multiple extractions
        for i, temp_file in enumerate(self.temp_files):
            config = ExtractionConfig(
                source_id=f"csv_{i}",
                source_type="csv",
                connection_params={
                    "file_path": temp_file,
                    "encoding": "utf-8",
                    "delimiter": ",",
                    "has_header": True
                },
                batch_size=25,
                extraction_id=f"ext_{i}",
                progress_tracker=self.tracker
            )
            configs.append(config)
            
            # Start tracking
            self.tracker.start_extraction(
                extraction_id=config.extraction_id,
                source_id=config.source_id,
                source_type=config.source_type
            )
        
        # Extract first batch from each
        for config in configs:
            batch = self.strategy.extract_batch(config, offset=0, limit=25)
        
        # Check all are tracked
        active = self.tracker.list_active_extractions()
        self.assertEqual(len(active), 3)
        
        # Complete first extraction
        self.tracker.complete_extraction("ext_0")
        
        # Check active count
        active = self.tracker.list_active_extractions()
        self.assertEqual(len(active), 2)
        
        # Verify individual progress
        for i in range(3):
            progress = self.tracker.get_progress(f"ext_{i}")
            self.assertIsNotNone(progress)
            
            if i == 0:
                self.assertEqual(progress.status, ExtractionStatus.COMPLETED)
            else:
                self.assertEqual(progress.status, ExtractionStatus.IN_PROGRESS)


class TestProgressTrackingErrorHandling(unittest.TestCase):
    """Test progress tracking error handling."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.tracker = ProgressTracker()
        self.strategy = CSVExtractionStrategy()
    
    def test_extraction_failure_tracking(self):
        """Test tracking extraction failures."""
        config = ExtractionConfig(
            source_id="nonexistent_csv",
            source_type="csv",
            connection_params={
                "file_path": "/nonexistent/file.csv",
                "encoding": "utf-8",
                "delimiter": ",",
                "has_header": True
            },
            batch_size=25,
            extraction_id="ext_fail",
            progress_tracker=self.tracker
        )
        
        # Start tracking
        self.tracker.start_extraction(
            extraction_id=config.extraction_id,
            source_id=config.source_id,
            source_type=config.source_type
        )
        
        # Try to extract (should fail)
        try:
            batch = self.strategy.extract_batch(config, offset=0, limit=25)
            self.fail("Should have raised ExtractionError")
        except Exception as e:
            # Mark as failed
            self.tracker.fail_extraction(
                extraction_id=config.extraction_id,
                error_message=str(e)
            )
        
        # Check failure is tracked
        progress = self.tracker.get_progress(config.extraction_id)
        self.assertEqual(progress.status, ExtractionStatus.FAILED)
        self.assertIsNotNone(progress.error_message)
        self.assertIsNotNone(progress.completed_at)


if __name__ == '__main__':
    unittest.main()
