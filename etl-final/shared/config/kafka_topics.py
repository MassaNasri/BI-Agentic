"""
Central Kafka topic naming and compatibility helpers.
"""
from __future__ import annotations

import os
from typing import Dict, List


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


RAW_DATA_TOPIC = os.getenv("KAFKA_TOPIC_RAW_DATA", "raw_data")
TRANSFORMED_DATA_TOPIC = os.getenv("KAFKA_TOPIC_TRANSFORMED_DATA", "transformed_data")
LOAD_REQUESTS_TOPIC = os.getenv("KAFKA_TOPIC_LOAD_REQUESTS", "load_requests")
METADATA_UPDATES_TOPIC = os.getenv("KAFKA_TOPIC_METADATA_UPDATES", "metadata_updates")
ERRORS_TOPIC = os.getenv("KAFKA_TOPIC_ERRORS", "errors")
QUARANTINE_TOPIC = os.getenv("KAFKA_TOPIC_QUARANTINE", "quarantine")


REQUIRED_TOPICS: List[str] = [
    RAW_DATA_TOPIC,
    TRANSFORMED_DATA_TOPIC,
    LOAD_REQUESTS_TOPIC,
    METADATA_UPDATES_TOPIC,
    ERRORS_TOPIC,
    QUARANTINE_TOPIC,
]


LEGACY_PIPELINE_TOPICS: List[str] = [
    "connection_topic",
    "schema_topic",
    "extracted_rows_topic",
    "clean_rows_topic",
    "load_rows_topic",
    "metadata_topic",
    "extracted_rows_dlq",
    "clean_rows_dlq",
    "load_rows_dlq",
]


LEGACY_TO_PRIMARY: Dict[str, str] = {
    "connection_topic": LOAD_REQUESTS_TOPIC,
    "extracted_rows_topic": RAW_DATA_TOPIC,
    "clean_rows_topic": TRANSFORMED_DATA_TOPIC,
    "metadata_topic": METADATA_UPDATES_TOPIC,
}


PRIMARY_TO_SCHEMA_TOPIC: Dict[str, str] = {
    LOAD_REQUESTS_TOPIC: "connection_topic",
    RAW_DATA_TOPIC: "extracted_rows_topic",
    TRANSFORMED_DATA_TOPIC: "clean_rows_topic",
    METADATA_UPDATES_TOPIC: "metadata_topic",
}


def _unique(values: List[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


DEFAULT_BOOTSTRAP_TOPICS: List[str] = _unique(REQUIRED_TOPICS + LEGACY_PIPELINE_TOPICS)


def topic_aliasing_enabled() -> bool:
    return _truthy(os.getenv("KAFKA_ENABLE_TOPIC_ALIASING", "true"))


def resolve_topic_name(topic: str) -> str:
    if not topic_aliasing_enabled():
        return topic
    return LEGACY_TO_PRIMARY.get(topic, topic)


def resolve_validation_topic(topic: str) -> str:
    return PRIMARY_TO_SCHEMA_TOPIC.get(topic, topic)


def bootstrap_topics_from_env() -> List[str]:
    configured = _split_csv(os.getenv("KAFKA_REQUIRED_TOPICS", ",".join(DEFAULT_BOOTSTRAP_TOPICS)))
    if not configured:
        configured = list(DEFAULT_BOOTSTRAP_TOPICS)
    return _unique(configured + REQUIRED_TOPICS)

