"""
Enhanced Kafka Producer with Message Validation and Error Handling
"""
import json
import os
import logging
from uuid import uuid4
from kafka import KafkaProducer
from kafka.errors import KafkaError
from typing import Dict, Any, Optional, Tuple

# Configure logging
logger = logging.getLogger(__name__)

from .logging_utils import get_correlation_id, set_correlation_id
from .tracing import inject_trace_headers
from .kafka_validation import validate_message as _validate_kafka_message
from shared.config.kafka_topics import resolve_topic_name
from shared.kafka.topic_initializer import ensure_topics


class KafkaMessageProducer:
    """
    Enhanced Kafka message producer with validation, retries, and proper error handling.
    
    Features:
    - Message schema validation
    - Automatic retries with exponential backoff
    - Proper error logging
    - Connection pooling
    - Message acknowledgements
    """

    def __init__(self, validate_messages: bool = True):
        """
        Initialize Kafka producer.
        
        Args:
            validate_messages: Whether to validate message schemas before sending
        """
        servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
        self.validate_messages = validate_messages
        self.servers = servers
        topics_initialized = ensure_topics(bootstrap_servers=servers, logger=logger)
        if topics_initialized:
            logger.info("[Kafka Producer] Topic initialization verified for %s", servers)
        else:
            logger.warning("[Kafka Producer] Topic initialization did not complete for %s", servers)

        try:
            self.producer = KafkaProducer(
                bootstrap_servers=servers,
                value_serializer=lambda v: json.dumps(v, default=str).encode('utf-8'),
                retries=5,
                acks='all',  # Wait for all replicas to acknowledge
                max_in_flight_requests_per_connection=1,  # Ensure ordering
                enable_idempotence=True,  # Prevent duplicate messages
                compression_type='gzip',  # Compress messages
                request_timeout_ms=30000,
                delivery_timeout_ms=120000,
            )
            logger.info(f"[Kafka Producer] Connected to {servers}")
        except Exception as e:
            logger.error(f"[Kafka Producer] Failed to connect: {e}")
            raise Exception(f"[Shared Kafka] Failed to connect: {e}")

    def _validate_message(self, topic: str, message: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate message schema based on topic using KafkaSchemaValidator.
        
        Args:
            topic: Kafka topic name
            message: Message dict to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        is_valid, error = _validate_kafka_message(topic, message, validate_messages=self.validate_messages)
        if not is_valid:
            logger.error(f"[Kafka Producer] Schema validation failed for {topic}: {error}")
        return is_valid, error

    def send(self, topic: str, message: Dict[str, Any], validate: Optional[bool] = None) -> bool:
        """
        Send message to Kafka topic with validation.
        
        Args:
            topic: Kafka topic name
            message: Message dict to send
            validate: Override validation flag (defaults to instance setting)
            
        Returns:
            True if sent successfully, False otherwise
        """
        resolved_topic = resolve_topic_name(topic)

        # Ensure correlation ID exists
        if "correlation_id" not in message:
            cid = get_correlation_id() or str(uuid4())
            message["correlation_id"] = cid
            set_correlation_id(cid)

        # Validate message if requested
        should_validate = validate if validate is not None else self.validate_messages
        if should_validate:
            is_valid, error = self._validate_message(resolved_topic, message)
            if not is_valid:
                logger.error(f"[Kafka Producer] Invalid message for {topic} (resolved={resolved_topic}): {error}")
                logger.error(f"[Kafka Producer] Message: {json.dumps(message, indent=2)}")
                return False
        
        try:
            headers = inject_trace_headers()
            future = self.producer.send(resolved_topic, message, headers=headers)
            record_metadata = future.get(timeout=10)
            logger.info(
                "[Kafka Producer] Sent topic=%s resolved_topic=%s partition=%s offset=%s",
                topic,
                resolved_topic,
                record_metadata.partition,
                record_metadata.offset,
            )
            return True
        except KafkaError as e:
            logger.error(f"[Kafka Producer ERROR] Kafka error sending to {topic} (resolved={resolved_topic}): {e}")
            return False
        except Exception as e:
            logger.error(f"[Kafka Producer ERROR] Unexpected error sending to {topic} (resolved={resolved_topic}): {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def flush(self):
        """Flush all pending messages."""
        try:
            self.producer.flush(timeout=30)
            logger.debug("[Kafka Producer] Flushed pending messages")
        except Exception as e:
            logger.error(f"[Kafka Producer] Error flushing: {e}")
    
    def close(self):
        """Close producer connection."""
        try:
            self.flush()
            self.producer.close()
            logger.info("[Kafka Producer] Closed connection")
        except Exception as e:
            logger.error(f"[Kafka Producer] Error closing: {e}")
