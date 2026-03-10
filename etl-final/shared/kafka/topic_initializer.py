"""
Kafka topic bootstrap for service startup.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Iterable, List

from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import NoBrokersAvailable, TopicAlreadyExistsError

from shared.config.kafka_topics import bootstrap_topics_from_env


_INIT_LOCK = threading.Lock()
_INITIALIZED = False


def _resolve_servers(bootstrap_servers: str | None = None) -> str:
    return bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")


def _normalize_topics(topics: Iterable[str] | None = None) -> List[str]:
    if topics is None:
        return bootstrap_topics_from_env()
    normalized: List[str] = []
    seen = set()
    for topic in topics:
        value = str(topic).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def ensure_topics(
    bootstrap_servers: str | None = None,
    topics: Iterable[str] | None = None,
    retries: int | None = None,
    backoff_seconds: float | None = None,
    logger: logging.Logger | None = None,
    force: bool = False,
) -> bool:
    """
    Ensure required Kafka topics exist.

    Returns:
        True if initialization succeeded, False otherwise.
    """
    global _INITIALIZED

    log = logger or logging.getLogger(__name__)
    if _INITIALIZED and not force:
        return True

    with _INIT_LOCK:
        if _INITIALIZED and not force:
            return True

        servers = _resolve_servers(bootstrap_servers)
        topic_names = _normalize_topics(topics)
        attempt_limit = max(1, int(retries or os.getenv("KAFKA_TOPIC_INIT_RETRIES", "20")))
        sleep_seconds = float(backoff_seconds or os.getenv("KAFKA_TOPIC_INIT_BACKOFF_SECONDS", "3"))
        partitions = max(1, int(os.getenv("KAFKA_TOPIC_PARTITIONS", "1")))
        replication = max(1, int(os.getenv("KAFKA_TOPIC_REPLICATION_FACTOR", "1")))

        if not topic_names:
            log.warning("[Kafka Topic Init] No topics configured for initialization")
            _INITIALIZED = True
            return True

        for attempt in range(1, attempt_limit + 1):
            admin = None
            try:
                admin = KafkaAdminClient(
                    bootstrap_servers=servers,
                    client_id=os.getenv("KAFKA_TOPIC_INIT_CLIENT_ID", "etl-topic-initializer"),
                    request_timeout_ms=int(os.getenv("KAFKA_TOPIC_INIT_REQUEST_TIMEOUT_MS", "15000")),
                )
                existing = set(admin.list_topics())
                missing = [topic for topic in topic_names if topic not in existing]

                if not missing:
                    log.info("[Kafka Topic Init] All topics already exist: %s", topic_names)
                    _INITIALIZED = True
                    return True

                new_topics = [
                    NewTopic(name=topic, num_partitions=partitions, replication_factor=replication)
                    for topic in missing
                ]
                try:
                    admin.create_topics(new_topics=new_topics, validate_only=False)
                except TopicAlreadyExistsError:
                    # Race-safe: another process created topics in parallel.
                    pass

                existing_after = set(admin.list_topics())
                still_missing = [topic for topic in topic_names if topic not in existing_after]
                if still_missing:
                    raise RuntimeError(f"Topics still missing after create: {still_missing}")

                log.info("[Kafka Topic Init] Created/verified topics: %s", topic_names)
                _INITIALIZED = True
                return True
            except (NoBrokersAvailable, TimeoutError, OSError, RuntimeError) as exc:
                log.warning(
                    "[Kafka Topic Init] Kafka unavailable (%s/%s) for bootstrap %s: %s",
                    attempt,
                    attempt_limit,
                    servers,
                    exc,
                )
                if attempt < attempt_limit:
                    time.sleep(sleep_seconds)
            except Exception as exc:
                log.warning(
                    "[Kafka Topic Init] Unexpected error (%s/%s): %s",
                    attempt,
                    attempt_limit,
                    exc,
                )
                if attempt < attempt_limit:
                    time.sleep(sleep_seconds)
            finally:
                if admin is not None:
                    try:
                        admin.close()
                    except Exception:
                        pass

        log.error("[Kafka Topic Init] Failed after %s attempts for bootstrap %s", attempt_limit, servers)
        return False

