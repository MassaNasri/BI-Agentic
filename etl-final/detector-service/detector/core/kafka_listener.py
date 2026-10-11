import logging
import os
import time

from shared.utils.kafka_consumer import KafkaMessageConsumer
from shared.utils.kafka_producer import KafkaMessageProducer
from shared.utils.metadata_schema import MetadataSchema

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _build_detection_metadata(message):
    """Build a valid, tenant-scoped observation without changing row data."""
    source = message.get("source") or message.get("source_id") or "unknown"
    rows = message.get("rows")
    if isinstance(rows, list):
        rows_observed = len(rows)
    else:
        rows_observed = 1 if message.get("data") else 0

    metadata = MetadataSchema.create_detection_metadata(
        source_id=source,
        rows_observed=rows_observed,
        detected_issues=[],
    )
    metadata.update(MetadataSchema.scope_fields(message))
    return metadata


def start_listener():
    """Observe extracted data without competing with or bypassing Transformer.

    Detector and Transformer are independent logical consumers. They must use
    different Kafka consumer groups. Detector deliberately never publishes to
    ``clean_rows_topic``; only Transformer may produce data for Loader.
    """
    logger.info("[DETECTOR] Creating Kafka consumer...")
    consumer_group = os.getenv(
        "DETECTOR_CONSUMER_GROUP",
        "detector_extracted_rows_observer_v1",
    )
    consumer = KafkaMessageConsumer(
        "extracted_rows_topic",
        consumer_group=consumer_group,
    )
    producer = KafkaMessageProducer()

    logger.info(
        "[DETECTOR] Observing extracted_rows_topic with group=%s",
        consumer_group,
    )

    for message, record in consumer.listen_committable():
        try:
            metadata = _build_detection_metadata(message)
            if not producer.send("metadata_topic", metadata):
                raise RuntimeError("failed to publish detection metadata")
            if not consumer.commit(record):
                raise RuntimeError("failed to commit detector offset")
            logger.info(
                "[DETECTOR] Observed source=%s rows=%s",
                metadata["source_id"],
                metadata["rows_observed"],
            )
        except Exception as e:
            logger.error(f"[DETECTOR ERROR] {e}")
            consumer.rewind(record)
            time.sleep(max(0.0, float(os.getenv("KAFKA_PROCESSING_RETRY_SECONDS", "2"))))
