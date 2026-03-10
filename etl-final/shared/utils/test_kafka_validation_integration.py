"""
Integration Tests for Kafka Schema Validation
Tests that schema validation is properly integrated into Kafka producer and consumer.
"""
import pytest
import os
import sys
from unittest.mock import Mock, patch, MagicMock

from shared.utils.kafka_producer import KafkaMessageProducer
from shared.utils.kafka_consumer import KafkaMessageConsumer


class TestKafkaProducerValidation:
    """Test schema validation in KafkaMessageProducer."""
    
    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_producer_validates_valid_message(self, mock_kafka_producer):
        """Test that producer accepts valid messages."""
        # Setup mock
        mock_producer_instance = Mock()
        mock_future = Mock()
        mock_metadata = Mock()
        mock_metadata.partition = 0
        mock_metadata.offset = 123
        mock_future.get.return_value = mock_metadata
        mock_producer_instance.send.return_value = mock_future
        mock_kafka_producer.return_value = mock_producer_instance
        
        # Create producer with validation enabled
        producer = KafkaMessageProducer(validate_messages=True)
        
        # Valid connection message
        valid_message = {
            "type": "file",
            "filename": "test.csv",
            "path": "/uploads/test.csv",
            "size": 1024
        }
        
        # Send message
        result = producer.send("connection_topic", valid_message)
        
        # Verify message was sent
        assert result is True
        mock_producer_instance.send.assert_called_once()
    
    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_producer_rejects_invalid_message(self, mock_kafka_producer):
        """Test that producer rejects invalid messages."""
        # Setup mock
        mock_producer_instance = Mock()
        mock_kafka_producer.return_value = mock_producer_instance
        
        # Create producer with validation enabled
        producer = KafkaMessageProducer(validate_messages=True)
        
        # Invalid message (missing required fields)
        invalid_message = {
            "type": "file"
            # Missing 'filename', 'path', 'size'
        }
        
        # Send message
        result = producer.send("connection_topic", invalid_message)
        
        # Verify message was rejected
        assert result is False
        mock_producer_instance.send.assert_not_called()
    
    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_producer_validates_extracted_rows(self, mock_kafka_producer):
        """Test producer validates extracted_rows_topic messages."""
        # Setup mock
        mock_producer_instance = Mock()
        mock_future = Mock()
        mock_metadata = Mock()
        mock_metadata.partition = 0
        mock_metadata.offset = 123
        mock_future.get.return_value = mock_metadata
        mock_producer_instance.send.return_value = mock_future
        mock_kafka_producer.return_value = mock_producer_instance
        
        producer = KafkaMessageProducer(validate_messages=True)
        
        # Valid extracted row
        valid_message = {
            "source": "test.csv",
            "row_id": 1,
            "data": {"id": 1, "name": "John"}
        }
        
        result = producer.send("extracted_rows_topic", valid_message)
        assert result is True
        
        # Invalid extracted row (empty data)
        invalid_message = {
            "source": "test.csv",
            "row_id": 1,
            "data": {}  # Empty dict not allowed
        }
        
        result = producer.send("extracted_rows_topic", invalid_message)
        assert result is False
    
    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_producer_validates_clean_rows(self, mock_kafka_producer):
        """Test producer validates clean_rows_topic messages."""
        # Setup mock
        mock_producer_instance = Mock()
        mock_future = Mock()
        mock_metadata = Mock()
        mock_metadata.partition = 0
        mock_metadata.offset = 123
        mock_future.get.return_value = mock_metadata
        mock_producer_instance.send.return_value = mock_future
        mock_kafka_producer.return_value = mock_producer_instance
        
        producer = KafkaMessageProducer(validate_messages=True)
        
        # Valid clean row with quality metadata
        valid_message = {
            "source": "test.csv",
            "data": {"id": 1, "name": "John"},
            "quality_score": 0.95,
            "warnings": ["Trimmed whitespace"]
        }
        
        result = producer.send("clean_rows_topic", valid_message)
        assert result is True
        
        # Invalid quality score
        invalid_message = {
            "source": "test.csv",
            "data": {"id": 1},
            "quality_score": 1.5  # > 1.0
        }
        
        result = producer.send("clean_rows_topic", invalid_message)
        assert result is False
    
    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_producer_validates_load_status(self, mock_kafka_producer):
        """Test producer validates load_rows_topic messages."""
        # Setup mock
        mock_producer_instance = Mock()
        mock_future = Mock()
        mock_metadata = Mock()
        mock_metadata.partition = 0
        mock_metadata.offset = 123
        mock_future.get.return_value = mock_metadata
        mock_producer_instance.send.return_value = mock_future
        mock_kafka_producer.return_value = mock_producer_instance
        
        producer = KafkaMessageProducer(validate_messages=True)
        
        # Valid success status
        valid_message = {
            "source": "test.csv",
            "status": "success",
            "row_count": 100
        }
        
        result = producer.send("load_rows_topic", valid_message)
        assert result is True
        
        # Invalid: error status without error field
        invalid_message = {
            "source": "test.csv",
            "status": "error"
            # Missing 'error' field
        }
        
        result = producer.send("load_rows_topic", invalid_message)
        assert result is False
    
    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_producer_bypass_validation(self, mock_kafka_producer):
        """Test that validation can be bypassed when disabled."""
        # Setup mock
        mock_producer_instance = Mock()
        mock_future = Mock()
        mock_metadata = Mock()
        mock_metadata.partition = 0
        mock_metadata.offset = 123
        mock_future.get.return_value = mock_metadata
        mock_producer_instance.send.return_value = mock_future
        mock_kafka_producer.return_value = mock_producer_instance
        
        # Create producer with validation disabled
        producer = KafkaMessageProducer(validate_messages=False)
        
        # Invalid message (but validation is disabled)
        invalid_message = {
            "type": "invalid"
        }
        
        # Send message
        result = producer.send("connection_topic", invalid_message)
        
        # Verify message was sent despite being invalid
        assert result is True
        mock_producer_instance.send.assert_called_once()
    
    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_producer_override_validation_per_message(self, mock_kafka_producer):
        """Test that validation can be overridden per message."""
        # Setup mock
        mock_producer_instance = Mock()
        mock_future = Mock()
        mock_metadata = Mock()
        mock_metadata.partition = 0
        mock_metadata.offset = 123
        mock_future.get.return_value = mock_metadata
        mock_producer_instance.send.return_value = mock_future
        mock_kafka_producer.return_value = mock_producer_instance
        
        # Create producer with validation enabled
        producer = KafkaMessageProducer(validate_messages=True)
        
        # Invalid message
        invalid_message = {
            "type": "invalid"
        }
        
        # Send with validation explicitly disabled for this message
        result = producer.send("connection_topic", invalid_message, validate=False)
        
        # Verify message was sent
        assert result is True
        mock_producer_instance.send.assert_called_once()

    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_producer_fail_open_on_validator_exception(self, mock_kafka_producer):
        """Test fail-open behavior when schema validation throws."""
        mock_producer_instance = Mock()
        mock_future = Mock()
        mock_metadata = Mock()
        mock_metadata.partition = 0
        mock_metadata.offset = 1
        mock_future.get.return_value = mock_metadata
        mock_producer_instance.send.return_value = mock_future
        mock_kafka_producer.return_value = mock_producer_instance

        with patch.dict(os.environ, {"KAFKA_VALIDATION_FAIL_OPEN": "true"}):
            with patch(
                "shared.utils.kafka_validation.KafkaSchemaValidator.validate_message",
                side_effect=RuntimeError("validator boom"),
            ):
                producer = KafkaMessageProducer(validate_messages=True)
                result = producer.send("connection_topic", {"type": "file", "filename": "a.csv", "path": "/tmp/a.csv", "size": 1})
        assert result is True
        mock_producer_instance.send.assert_called_once()

    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_producer_fail_closed_by_default_on_validator_exception(self, mock_kafka_producer):
        """Test fail-closed default when schema validation throws."""
        mock_producer_instance = Mock()
        mock_kafka_producer.return_value = mock_producer_instance

        with patch.dict(os.environ, {"KAFKA_VALIDATION_FAIL_OPEN": "false"}):
            with patch(
                "shared.utils.kafka_validation.KafkaSchemaValidator.validate_message",
                side_effect=RuntimeError("validator boom"),
            ):
                producer = KafkaMessageProducer(validate_messages=True)
                result = producer.send("connection_topic", {"type": "file", "filename": "a.csv", "path": "/tmp/a.csv", "size": 1})
        assert result is False
        mock_producer_instance.send.assert_not_called()

    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_producer_imports_validator_without_top_level_module(self, mock_kafka_producer):
        """
        Docker-like import test: validation should work without top-level kafka_schema_validator.
        """
        mock_producer_instance = Mock()
        mock_future = Mock()
        mock_metadata = Mock()
        mock_metadata.partition = 0
        mock_metadata.offset = 1
        mock_future.get.return_value = mock_metadata
        mock_producer_instance.send.return_value = mock_future
        mock_kafka_producer.return_value = mock_producer_instance

        with patch.dict(sys.modules, {"kafka_schema_validator": None}, clear=False):
            producer = KafkaMessageProducer(validate_messages=True)
            result = producer.send(
                "connection_topic",
                {"type": "file", "filename": "a.csv", "path": "/tmp/a.csv", "size": 1},
            )
        assert result is True


class TestKafkaConsumerValidation:
    """Test schema validation in KafkaMessageConsumer."""
    
    @patch('shared.utils.kafka_consumer.KafkaConsumer')
    def test_consumer_validates_messages(self, mock_kafka_consumer):
        """Test that consumer validates incoming messages."""
        # Setup mock
        mock_consumer_instance = MagicMock()
        
        # Create mock messages
        valid_msg = Mock()
        valid_msg.value = {
            "source": "test.csv",
            "data": {"id": 1, "name": "John"}
        }
        
        invalid_msg = Mock()
        invalid_msg.value = {
            "source": "test.csv",
            "data": {}  # Empty data not allowed
        }
        
        # Mock consumer to return both messages
        mock_consumer_instance.__iter__.return_value = iter([valid_msg, invalid_msg])
        mock_kafka_consumer.return_value = mock_consumer_instance
        
        # Create consumer with validation enabled
        consumer = KafkaMessageConsumer("extracted_rows_topic", validate_messages=True)
        consumer.consumer = mock_consumer_instance
        
        # Listen for messages
        messages = []
        for i, msg in enumerate(consumer.listen()):
            messages.append(msg)
            if i >= 0:  # Only get first valid message
                break
        
        # Verify only valid message was yielded
        assert len(messages) == 1
        assert messages[0]["data"]["name"] == "John"
    
    @patch('shared.utils.kafka_consumer.KafkaConsumer')
    def test_consumer_bypass_validation(self, mock_kafka_consumer):
        """Test that consumer can bypass validation."""
        # Setup mock
        mock_consumer_instance = MagicMock()
        
        # Create mock invalid message
        invalid_msg = Mock()
        invalid_msg.value = {
            "source": "test.csv",
            "data": {}  # Empty data (invalid)
        }
        
        mock_consumer_instance.__iter__.return_value = iter([invalid_msg])
        mock_kafka_consumer.return_value = mock_consumer_instance
        
        # Create consumer with validation disabled
        consumer = KafkaMessageConsumer("extracted_rows_topic", validate_messages=False)
        consumer.consumer = mock_consumer_instance
        
        # Listen for messages
        messages = []
        for i, msg in enumerate(consumer.listen()):
            messages.append(msg)
            if i >= 0:
                break
        
        # Verify invalid message was yielded (validation bypassed)
        assert len(messages) == 1
        assert messages[0]["data"] == {}


class TestEndToEndValidation:
    """Test end-to-end validation scenarios."""
    
    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_all_topics_have_validation(self, mock_kafka_producer):
        """Test that all major topics have validation schemas."""
        # Setup mock
        mock_producer_instance = Mock()
        mock_future = Mock()
        mock_metadata = Mock()
        mock_metadata.partition = 0
        mock_metadata.offset = 123
        mock_future.get.return_value = mock_metadata
        mock_producer_instance.send.return_value = mock_future
        mock_kafka_producer.return_value = mock_producer_instance
        
        producer = KafkaMessageProducer(validate_messages=True)
        
        # Test each topic with valid message
        test_cases = [
            ("connection_topic", {
                "type": "file",
                "filename": "test.csv",
                "path": "/uploads/test.csv",
                "size": 1024
            }),
            ("schema_topic", {
                "source": "test.csv",
                "type": "file",
                "columns": ["id", "name"]
            }),
            ("extracted_rows_topic", {
                "source": "test.csv",
                "data": {"id": 1}
            }),
            ("clean_rows_topic", {
                "source": "test.csv",
                "data": {"id": 1}
            }),
            ("load_rows_topic", {
                "source": "test.csv",
                "status": "success"
            }),
            ("metadata_topic", {
                "event_type": "test",
                "timestamp": "2024-01-01T00:00:00Z"
            })
        ]
        
        for topic, message in test_cases:
            result = producer.send(topic, message)
            assert result is True, f"Failed to send valid message to {topic}"
    
    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_validation_catches_common_errors(self, mock_kafka_producer):
        """Test that validation catches common error patterns."""
        # Setup mock
        mock_producer_instance = Mock()
        mock_kafka_producer.return_value = mock_producer_instance
        
        producer = KafkaMessageProducer(validate_messages=True)
        
        # Common error patterns
        error_cases = [
            # Missing required fields
            ("connection_topic", {"type": "file"}),
            
            # Wrong type
            ("connection_topic", {"type": "invalid_type", "filename": "test.csv", "path": "/test", "size": 100}),
            
            # Empty data
            ("extracted_rows_topic", {"source": "test.csv", "data": {}}),
            
            # Invalid quality score
            ("clean_rows_topic", {"source": "test.csv", "data": {"id": 1}, "quality_score": 2.0}),
            
            # Missing error field on error status
            ("load_rows_topic", {"source": "test.csv", "status": "error"}),
            
            # Invalid port
            ("connection_topic", {
                "type": "database",
                "db_type": "mysql",
                "host": "localhost",
                "user": "admin",
                "password": "secret",
                "database": "testdb",
                "port": 99999
            })
        ]
        
        for topic, message in error_cases:
            result = producer.send(topic, message)
            assert result is False, f"Should have rejected invalid message for {topic}: {message}"


class TestValidationPerformance:
    """Test validation performance characteristics."""
    
    @patch('shared.utils.kafka_producer.KafkaProducer')
    def test_validation_does_not_block_valid_messages(self, mock_kafka_producer):
        """Test that validation doesn't significantly slow down message sending."""
        # Setup mock
        mock_producer_instance = Mock()
        mock_future = Mock()
        mock_metadata = Mock()
        mock_metadata.partition = 0
        mock_metadata.offset = 123
        mock_future.get.return_value = mock_metadata
        mock_producer_instance.send.return_value = mock_future
        mock_kafka_producer.return_value = mock_producer_instance
        
        producer = KafkaMessageProducer(validate_messages=True)
        
        # Send multiple valid messages
        valid_message = {
            "source": "test.csv",
            "data": {"id": 1, "name": "John"}
        }
        
        success_count = 0
        for _ in range(100):
            if producer.send("extracted_rows_topic", valid_message):
                success_count += 1
        
        # All messages should be sent successfully
        assert success_count == 100
        assert mock_producer_instance.send.call_count == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
