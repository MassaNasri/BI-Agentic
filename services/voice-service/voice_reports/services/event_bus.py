"""
Kafka event publishing helpers for voice workflow events.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


class KafkaEventPublisher:
    def __init__(self) -> None:
        self.bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
        self.enabled = os.getenv("KAFKA_EVENTS_ENABLED", "true").lower() == "true"
        configured_topics = os.getenv(
            "KAFKA_REQUIRED_TOPICS",
            "report.voice.received,report.intent.generated,report.sql.generated,"
            "report.query.executed,report.visualization.ready",
        )
        self.required_topics = [
            topic.strip()
            for topic in configured_topics.split(",")
            if topic and topic.strip()
        ]
        self._producer = None
        self._init_error: Optional[str] = None
        self._initialize()

    def _ensure_topics(self, admin_client_cls, new_topic_cls) -> None:
        if not self.required_topics:
            return

        admin = None
        try:
            admin = admin_client_cls(
                bootstrap_servers=self.bootstrap_servers,
                client_id="voice-service-topic-initializer",
            )
            existing_topics = set(admin.list_topics())
            missing_topics = [t for t in self.required_topics if t not in existing_topics]

            if not missing_topics:
                logger.info("Kafka topics already present: %s", self.required_topics)
                return

            logger.info("Creating missing Kafka topics: %s", missing_topics)
            for topic in missing_topics:
                try:
                    admin.create_topics(
                        new_topics=[
                            new_topic_cls(
                                name=topic,
                                num_partitions=1,
                                replication_factor=1,
                            )
                        ],
                        validate_only=False,
                    )
                except Exception as topic_exc:
                    logger.warning("Failed creating Kafka topic '%s': %s", topic, topic_exc)
        except Exception as exc:
            # In local/docker environments topic creation can race at startup.
            # We log and continue because producer send() remains the source of truth.
            logger.warning("Failed ensuring Kafka topics %s: %s", self.required_topics, exc)
        finally:
            if admin is not None:
                try:
                    admin.close()
                except Exception:
                    pass

    def _initialize(self) -> None:
        if not self.enabled:
            logger.info("Kafka events are disabled by configuration.")
            return

        try:
            from kafka import KafkaProducer  # type: ignore
            from kafka.admin import KafkaAdminClient, NewTopic  # type: ignore

            self._ensure_topics(KafkaAdminClient, NewTopic)

            self._producer = KafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda value: json.dumps(value).encode("utf-8"),
                key_serializer=lambda key: str(key).encode("utf-8") if key is not None else None,
                linger_ms=20,
                retries=3,
            )
            logger.info("Kafka producer initialized for %s", self.bootstrap_servers)
        except Exception as exc:
            self._init_error = str(exc)
            logger.warning("Kafka producer not available: %s", exc)

    def publish(self, topic: str, payload: Dict[str, Any], key: Optional[str] = None) -> bool:
        event_payload = {
            **payload,
            "event_timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if not self._producer:
            logger.info("Kafka event skipped topic=%s payload=%s", topic, event_payload)
            return False

        try:
            future = self._producer.send(topic, value=event_payload, key=key)
            future.get(timeout=10)
            logger.info("Kafka event published topic=%s key=%s", topic, key)
            return True
        except Exception as exc:
            logger.error("Kafka publish failed topic=%s error=%s", topic, exc)
            return False


_publisher: Optional[KafkaEventPublisher] = None


def get_event_publisher() -> KafkaEventPublisher:
    global _publisher
    if _publisher is None:
        _publisher = KafkaEventPublisher()
    return _publisher
