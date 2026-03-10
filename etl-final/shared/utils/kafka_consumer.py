import json
import os
import time
import logging
from kafka import KafkaConsumer, TopicPartition
from kafka.errors import KafkaError
from kafka.structs import OffsetAndMetadata
from typing import Generator, Dict, Any, Optional, Tuple
from uuid import uuid4

from .logging_utils import set_correlation_id
from .tracing import extract_trace_headers, set_trace_id_from_span, get_tracer
from .kafka_validation import validate_message as _validate_kafka_message
from shared.config.kafka_topics import resolve_topic_name
from shared.kafka.topic_initializer import ensure_topics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KafkaMessageConsumer:
    def __init__(
        self,
        topic: str,
        consumer_group: Optional[str] = None,
        validate_messages: bool = True,
        enable_auto_commit: Optional[bool] = None,
    ):
        self.requested_topic = topic
        self.topic = resolve_topic_name(topic)
        self.validate_messages = validate_messages
        self.consumer_group = consumer_group or f"{topic}_consumer_group"
        self.servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
        auto_commit_default = os.getenv("KAFKA_ENABLE_AUTO_COMMIT", "false").lower() in ("1", "true", "yes")
        self.enable_auto_commit = auto_commit_default if enable_auto_commit is None else enable_auto_commit
        self.consumer = None

    def connect(self):
        """Connect to Kafka with infinite retry."""
        while True:
            try:
                ensure_topics(bootstrap_servers=self.servers, logger=logger)
                logger.info(
                    "[Kafka Consumer] Connecting to %s, topic=%s (requested=%s), group=%s",
                    self.servers,
                    self.topic,
                    self.requested_topic,
                    self.consumer_group,
                )
                consumer_kwargs = {
                    "bootstrap_servers": self.servers,
                    "value_deserializer": lambda m: json.loads(m.decode("utf-8")),
                    "auto_offset_reset": "earliest",
                    "enable_auto_commit": self.enable_auto_commit,
                    "group_id": self.consumer_group,
                    "session_timeout_ms": 30000,
                    "heartbeat_interval_ms": 10000,
                    "max_poll_interval_ms": int(os.getenv("KAFKA_MAX_POLL_INTERVAL_MS", "300000")),
                    "max_poll_records": int(os.getenv("KAFKA_MAX_POLL_RECORDS", "500")),
                    "fetch_max_bytes": int(os.getenv("KAFKA_FETCH_MAX_BYTES", str(50 * 1024 * 1024))),
                    "max_partition_fetch_bytes": int(os.getenv("KAFKA_MAX_PARTITION_FETCH_BYTES", str(10 * 1024 * 1024))),
                }
                client_id = os.getenv("KAFKA_CLIENT_ID")
                if client_id:
                    consumer_kwargs["client_id"] = client_id
                group_instance_id = os.getenv("KAFKA_GROUP_INSTANCE_ID")
                if group_instance_id:
                    consumer_kwargs["group_instance_id"] = group_instance_id
                rebalance_strategy = os.getenv("KAFKA_REBALANCE_STRATEGY", "cooperative").lower()
                if rebalance_strategy == "cooperative":
                    try:
                        from kafka.coordinator.assignors.cooperative_sticky import CooperativeStickyAssignor
                        consumer_kwargs["partition_assignment_strategy"] = [CooperativeStickyAssignor]
                    except Exception:
                        pass

                self.consumer = KafkaConsumer(self.topic, **consumer_kwargs)
                logger.info("[Kafka Consumer] Connected successfully")
                break
            except Exception as e:
                logger.warning(f"[Kafka Consumer] Kafka not ready, retrying in 5s: {e}")
                time.sleep(5)

    def _validate_message(self, message: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate message schema using KafkaSchemaValidator.
        
        Args:
            message: Message dict to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        is_valid, error = _validate_kafka_message(self.topic, message, validate_messages=self.validate_messages)
        if not is_valid:
            logger.error(f"[Kafka Consumer] Schema validation failed for {self.topic}: {error}")
        return is_valid, error

    def _iter_messages(self):
        if self.consumer is None:
            self.connect()

        logger.info(
            "[Kafka Consumer] Listening on topic=%s (requested=%s), group=%s",
            self.topic,
            self.requested_topic,
            self.consumer_group,
        )

        while True:
            try:
                for msg in self.consumer:
                    message = msg.value
                    # Correlation ID + tracing context
                    correlation_id = message.get("correlation_id") if isinstance(message, dict) else None
                    if not correlation_id:
                        correlation_id = str(uuid4())
                        if isinstance(message, dict):
                            message["correlation_id"] = correlation_id
                    set_correlation_id(correlation_id)

                    ctx = extract_trace_headers(msg.headers)
                    tracer = get_tracer("kafka_consumer")
                    if tracer and ctx is not None:
                        with tracer.start_as_current_span(
                            f"kafka.consume.{self.topic}",
                            context=ctx,
                        ) as span:
                            set_trace_id_from_span(span)
                            if self.validate_messages:
                                is_valid, error = self._validate_message(message)
                                if not is_valid:
                                    logger.error(f"[Kafka Consumer] Invalid message: {error}")
                                    continue
                            yield message, msg
                        continue
                    if self.validate_messages:
                        is_valid, error = self._validate_message(message)
                        if not is_valid:
                            logger.error(f"[Kafka Consumer] Invalid message: {error}")
                            continue
                    yield message, msg
            except KafkaError as e:
                logger.error(f"[Kafka Consumer] Kafka error, reconnecting: {e}")
                time.sleep(5)
                self.connect()
            except Exception as e:
                logger.error(f"[Kafka Consumer] Unexpected error, reconnecting: {e}")
                time.sleep(5)
                self.connect()

    def listen(self) -> Generator[Dict[str, Any], None, None]:
        for message, _ in self._iter_messages():
            yield message

    def listen_committable(self):
        """Yield `(message, record)` so callers can commit only on successful processing."""
        yield from self._iter_messages()

    def commit(self, record=None) -> bool:
        if self.consumer is None:
            return False
        try:
            if record is None:
                self.consumer.commit()
                return True
            partition = TopicPartition(record.topic, record.partition)
            try:
                offset_meta = OffsetAndMetadata(record.offset + 1, "", -1)
            except TypeError:
                offset_meta = OffsetAndMetadata(record.offset + 1, "")
            offsets = {partition: offset_meta}
            self.consumer.commit(offsets=offsets)
            return True
        except Exception as e:
            logger.error("[Kafka Consumer] Failed to commit offsets: %s", e)
            return False

    def close(self):
        if self.consumer:
            self.consumer.close()
