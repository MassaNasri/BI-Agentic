"""
Unit Tests for Extraction Progress Tracking

Tests the progress tracking functionality for extraction operations.

Requirements:
- US-9: Observability (AC 9.1: Structured logging with correlation IDs)
- Task 2.2.6: Add extraction progress tracking
"""

import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch
import logging

from extraction_progress import (
    ExtractionProgress,
    ExtractionStatus,
    ProgressTracker
)


class TestExtractionProgress(unittest.TestCase):
    """Test ExtractionProgress data model."""
    
    def test_create_progress(self):
        """Test creating an ExtractionProgress object."""
        progress = ExtractionProgress(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            status=ExtractionStatus.IN_PROGRESS,
            rows_extracted=1000,
            batches_processed=1,
            current_offset=1000,
            estimated_total_rows=10000
        )
        
        self.assertEqual(progress.extraction_id, "ext_123")
        self.assertEqual(progress.source_id, "customers_csv")
        self.assertEqual(progress.source_type, "csv")
        self.assertEqual(progress.status, ExtractionStatus.IN_PROGRESS)
        self.assertEqual(progress.rows_extracted, 1000)
        self.assertEqual(progress.batches_processed, 1)
        self.assertEqual(progress.current_offset, 1000)
        self.assertEqual(progress.estimated_total_rows, 10000)
    
    def test_to_dict(self):
        """Test converting ExtractionProgress to dictionary."""
        now = datetime.now(timezone.utc)
        progress = ExtractionProgress(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            status=ExtractionStatus.IN_PROGRESS,
            rows_extracted=1000,
            started_at=now,
            updated_at=now
        )
        
        data = progress.to_dict()
        
        self.assertEqual(data['extraction_id'], "ext_123")
        self.assertEqual(data['status'], "in_progress")
        self.assertIsInstance(data['started_at'], str)
        self.assertIsInstance(data['updated_at'], str)
    
    def test_get_progress_percentage(self):
        """Test calculating progress percentage."""
        progress = ExtractionProgress(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            status=ExtractionStatus.IN_PROGRESS,
            rows_extracted=2500,
            estimated_total_rows=10000
        )
        
        percentage = progress.get_progress_percentage()
        self.assertEqual(percentage, 25.0)
    
    def test_get_progress_percentage_no_estimate(self):
        """Test progress percentage when total is unknown."""
        progress = ExtractionProgress(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            status=ExtractionStatus.IN_PROGRESS,
            rows_extracted=1000
        )
        
        percentage = progress.get_progress_percentage()
        self.assertIsNone(percentage)
    
    def test_get_progress_percentage_over_100(self):
        """Test progress percentage caps at 100%."""
        progress = ExtractionProgress(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            status=ExtractionStatus.IN_PROGRESS,
            rows_extracted=15000,
            estimated_total_rows=10000
        )
        
        percentage = progress.get_progress_percentage()
        self.assertEqual(percentage, 100.0)
    
    def test_get_throughput(self):
        """Test calculating extraction throughput."""
        started = datetime.now(timezone.utc)
        updated = started + timedelta(seconds=10)
        
        progress = ExtractionProgress(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            status=ExtractionStatus.IN_PROGRESS,
            rows_extracted=1000,
            started_at=started,
            updated_at=updated
        )
        
        throughput = progress.get_throughput()
        self.assertEqual(throughput, 100.0)  # 1000 rows / 10 seconds
    
    def test_get_throughput_no_time(self):
        """Test throughput when timestamps are missing."""
        progress = ExtractionProgress(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            status=ExtractionStatus.IN_PROGRESS,
            rows_extracted=1000
        )
        
        throughput = progress.get_throughput()
        self.assertIsNone(throughput)
    
    def test_estimate_completion_time(self):
        """Test estimating completion time."""
        started = datetime.now(timezone.utc)
        updated = started + timedelta(seconds=10)
        
        progress = ExtractionProgress(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            status=ExtractionStatus.IN_PROGRESS,
            rows_extracted=1000,
            estimated_total_rows=10000,
            started_at=started,
            updated_at=updated
        )
        
        estimated = progress.estimate_completion_time()
        
        # Should estimate 90 more seconds (9000 remaining rows at 100 rows/sec)
        expected = updated + timedelta(seconds=90)
        self.assertIsNotNone(estimated)
        # Allow 1 second tolerance for test execution time
        self.assertAlmostEqual(
            estimated.timestamp(),
            expected.timestamp(),
            delta=1.0
        )
    
    def test_estimate_completion_time_no_data(self):
        """Test completion estimate when data is insufficient."""
        progress = ExtractionProgress(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            status=ExtractionStatus.IN_PROGRESS,
            rows_extracted=1000
        )
        
        estimated = progress.estimate_completion_time()
        self.assertIsNone(estimated)


class TestProgressTracker(unittest.TestCase):
    """Test ProgressTracker functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_metadata_client = Mock()
        self.mock_logger = Mock(spec=logging.Logger)
        self.tracker = ProgressTracker(
            metadata_client=self.mock_metadata_client,
            logger=self.mock_logger
        )
    
    def test_start_extraction(self):
        """Test starting extraction tracking."""
        progress = self.tracker.start_extraction(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            correlation_id="corr_456",
            estimated_total_rows=10000
        )
        
        self.assertEqual(progress.extraction_id, "ext_123")
        self.assertEqual(progress.source_id, "customers_csv")
        self.assertEqual(progress.source_type, "csv")
        self.assertEqual(progress.correlation_id, "corr_456")
        self.assertEqual(progress.estimated_total_rows, 10000)
        self.assertEqual(progress.status, ExtractionStatus.IN_PROGRESS)
        self.assertIsNotNone(progress.started_at)
        self.assertIsNotNone(progress.updated_at)
        
        # Verify logging
        self.mock_logger.log.assert_called()
        
        # Verify persistence
        self.mock_metadata_client.store_extraction_progress.assert_called_once()
    
    def test_update_progress(self):
        """Test updating extraction progress."""
        # Start extraction
        self.tracker.start_extraction(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        # Update progress
        progress = self.tracker.update_progress(
            extraction_id="ext_123",
            rows_extracted=2000,
            batches_processed=2,
            current_offset=2000
        )
        
        self.assertEqual(progress.rows_extracted, 2000)
        self.assertEqual(progress.batches_processed, 2)
        self.assertEqual(progress.current_offset, 2000)
        
        # Verify logging (start + update)
        self.assertEqual(self.mock_logger.log.call_count, 2)
        
        # Verify persistence (start + update)
        self.assertEqual(self.mock_metadata_client.store_extraction_progress.call_count, 2)
    
    def test_update_progress_unknown_extraction(self):
        """Test updating progress for unknown extraction."""
        progress = self.tracker.update_progress(
            extraction_id="unknown",
            rows_extracted=1000
        )
        
        self.assertIsNone(progress)
        self.mock_logger.warning.assert_called_once()
    
    def test_complete_extraction(self):
        """Test completing extraction."""
        # Start extraction
        self.tracker.start_extraction(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        # Complete extraction
        progress = self.tracker.complete_extraction(
            extraction_id="ext_123",
            final_row_count=10000
        )
        
        self.assertEqual(progress.status, ExtractionStatus.COMPLETED)
        self.assertEqual(progress.rows_extracted, 10000)
        self.assertIsNotNone(progress.completed_at)
        
        # Verify logging
        self.assertEqual(self.mock_logger.log.call_count, 2)  # start + complete
    
    def test_fail_extraction(self):
        """Test failing extraction."""
        # Start extraction
        self.tracker.start_extraction(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        # Fail extraction
        error_msg = "Connection timeout"
        progress = self.tracker.fail_extraction(
            extraction_id="ext_123",
            error_message=error_msg
        )
        
        self.assertEqual(progress.status, ExtractionStatus.FAILED)
        self.assertEqual(progress.error_message, error_msg)
        self.assertIsNotNone(progress.completed_at)
        
        # Verify error logging
        self.assertEqual(self.mock_logger.log.call_count, 2)  # start + fail
    
    def test_get_progress(self):
        """Test getting progress for extraction."""
        # Start extraction
        self.tracker.start_extraction(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        # Get progress
        progress = self.tracker.get_progress("ext_123")
        
        self.assertIsNotNone(progress)
        self.assertEqual(progress.extraction_id, "ext_123")
    
    def test_get_progress_not_found(self):
        """Test getting progress for non-existent extraction."""
        progress = self.tracker.get_progress("unknown")
        self.assertIsNone(progress)
    
    def test_list_active_extractions(self):
        """Test listing active extractions."""
        # Start multiple extractions
        self.tracker.start_extraction(
            extraction_id="ext_1",
            source_id="source_1",
            source_type="csv"
        )
        self.tracker.start_extraction(
            extraction_id="ext_2",
            source_id="source_2",
            source_type="database"
        )
        self.tracker.start_extraction(
            extraction_id="ext_3",
            source_id="source_3",
            source_type="csv"
        )
        
        # Complete one extraction
        self.tracker.complete_extraction("ext_2")
        
        # List active extractions
        active = self.tracker.list_active_extractions()
        
        self.assertEqual(len(active), 2)
        extraction_ids = [p.extraction_id for p in active]
        self.assertIn("ext_1", extraction_ids)
        self.assertIn("ext_3", extraction_ids)
        self.assertNotIn("ext_2", extraction_ids)
    
    def test_structured_logging_with_correlation_id(self):
        """Test that logging includes correlation ID."""
        self.tracker.start_extraction(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            correlation_id="corr_456"
        )
        
        # Check that log was called with correlation_id in extra
        call_args = self.mock_logger.log.call_args
        self.assertIsNotNone(call_args)
        
        # Extract extra dict from call
        extra = call_args[1].get('extra', {})
        self.assertEqual(extra.get('correlation_id'), 'corr_456')
        self.assertEqual(extra.get('extraction_id'), 'ext_123')
        self.assertEqual(extra.get('source_id'), 'customers_csv')
    
    def test_persistence_failure_handling(self):
        """Test that persistence failures don't break tracking."""
        # Make metadata client raise exception
        self.mock_metadata_client.store_extraction_progress.side_effect = Exception("Connection failed")
        
        # Should not raise exception
        progress = self.tracker.start_extraction(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        self.assertIsNotNone(progress)
        self.mock_logger.error.assert_called_once()


class TestProgressTrackerIntegration(unittest.TestCase):
    """Integration tests for progress tracking with extraction strategies."""
    
    def test_progress_tracking_without_metadata_client(self):
        """Test progress tracking works without metadata client."""
        tracker = ProgressTracker()  # No metadata client
        
        progress = tracker.start_extraction(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv"
        )
        
        self.assertIsNotNone(progress)
        self.assertEqual(progress.extraction_id, "ext_123")
    
    def test_full_extraction_lifecycle(self):
        """Test complete extraction lifecycle with progress tracking."""
        tracker = ProgressTracker()
        
        # Start
        progress = tracker.start_extraction(
            extraction_id="ext_123",
            source_id="customers_csv",
            source_type="csv",
            estimated_total_rows=10000
        )
        self.assertEqual(progress.status, ExtractionStatus.IN_PROGRESS)
        
        # Update multiple times
        tracker.update_progress("ext_123", rows_extracted=1000, batches_processed=1, current_offset=1000)
        tracker.update_progress("ext_123", rows_extracted=2000, batches_processed=2, current_offset=2000)
        tracker.update_progress("ext_123", rows_extracted=3000, batches_processed=3, current_offset=3000)
        
        progress = tracker.get_progress("ext_123")
        self.assertEqual(progress.rows_extracted, 3000)
        self.assertEqual(progress.batches_processed, 3)
        
        # Complete
        progress = tracker.complete_extraction("ext_123", final_row_count=10000)
        self.assertEqual(progress.status, ExtractionStatus.COMPLETED)
        self.assertEqual(progress.rows_extracted, 10000)
        self.assertIsNotNone(progress.completed_at)


if __name__ == '__main__':
    unittest.main()
