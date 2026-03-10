"""
Enhanced Transformer Service Kafka Listener
Processes extracted rows, applies cleaning/transformation, and emits metadata
"""
import logging
import os
import threading
import time
from collections import deque, OrderedDict
from datetime import datetime
from typing import Dict, Any, List
from uuid import UUID
from shared.utils.kafka_consumer import KafkaMessageConsumer
from shared.utils.kafka_producer import KafkaMessageProducer
from shared.utils.metadata_schema import MetadataSchema
from shared.utils.idempotency_manager import IdempotencyManager
from shared.utils.quarantine_manager import QuarantineManager
from clickhouse_driver import Client
from shared.utils.logging_utils import configure_logging
from shared.utils.metrics import ROWS_PROCESSED, ERRORS_TOTAL, PROCESS_LATENCY, start_metrics_server
from shared.utils.health_server import start_health_server
from shared.utils.lineage_tracker import LineageTracker
from shared.models.lineage import LineageRecord
from shared.utils.quality_metrics import QualityMetricsManager
from shared.utils.tracing import configure_tracing
from shared.utils.schema_contract_store import build_schema_contract_store_from_env
from .transformer_service import TransformerService

logger = logging.getLogger(__name__)

configure_logging()
configure_tracing("transformer-service")
start_metrics_server(int(os.getenv("TRANSFORMER_METRICS_PORT", "9102")))
start_health_server(int(os.getenv("TRANSFORMER_HEALTH_PORT", "8084")))


class RawRowListener:
    """
    Enhanced listener for extracted_rows_topic.
    
    Features:
    - Comprehensive cleaning and transformation
    - Metadata emission
    - Error handling and recovery
    - Batch processing statistics
    """

    def __init__(self, batch_size: int | None = None):
        self.consumer = KafkaMessageConsumer("extracted_rows_topic")
        self.producer = KafkaMessageProducer()
        
        # Initialize IdempotencyManager for hash generation
        self.idempotency_manager = IdempotencyManager(None)  # Stateless hash generation only

        self.rules = self._load_rules()
        self.quarantine_manager = self._init_quarantine_manager()
        self.schema_contract_store = self._init_schema_contract_store()
        try:
            self.lineage_tracker = LineageTracker()
        except Exception as exc:
            logger.warning("[TRANSFORMER] Lineage tracker unavailable, continuing without lineage side-effects: %s", exc)
            self.lineage_tracker = None
        self.quality_metrics_manager = self._init_quality_metrics_manager()
        self.transformer_service = TransformerService(
            idempotency_manager=self.idempotency_manager,
            quarantine_manager=self.quarantine_manager,
            default_rules=self.rules,
            schema_contract_store=self.schema_contract_store,
        )

        self.batch_size = batch_size or int(os.getenv("TRANSFORMER_BATCH_SIZE", "500"))
        self.output_batch_size = int(os.getenv("TRANSFORMER_OUTPUT_BATCH_SIZE", "500"))
        self._pending_messages: List[Dict[str, Any]] = []
        
        # Statistics tracking
        self.processed_count = 0
        self.success_count = 0
        self.failed_count = 0
        self.max_warning_entries = int(os.getenv("TRANSFORMER_MAX_WARNING_ENTRIES", "1000"))
        self.max_source_stats = int(os.getenv("TRANSFORMER_MAX_SOURCE_STATS", "1000"))
        self.warnings = deque(maxlen=self.max_warning_entries)
        self.source_stats: "OrderedDict[str, Dict[str, int]]" = OrderedDict()
        
        # Metadata emission interval
        self.metadata_interval = 1000  # Emit metadata every 1000 rows
        self._next_metadata_emit = self.metadata_interval
        self.send_retries = int(os.getenv("TRANSFORMER_SEND_RETRIES", "3"))
        self.send_backoff_base = float(os.getenv("TRANSFORMER_SEND_BACKOFF_BASE", "0.5"))
        self.send_backoff_max = float(os.getenv("TRANSFORMER_SEND_BACKOFF_MAX", "5.0"))
        self.dlq_topic = os.getenv("TRANSFORMER_DLQ_TOPIC", "clean_rows_dlq")

    def _send_with_retry(self, topic: str, message: Dict[str, Any], context: str) -> bool:
        for attempt in range(1, self.send_retries + 1):
            if self.producer.send(topic, message):
                return True
            if attempt < self.send_retries:
                backoff = min(self.send_backoff_max, self.send_backoff_base * (2 ** (attempt - 1)))
                logger.warning(
                    "[TRANSFORMER] Send failed for %s (attempt %s/%s), retrying in %.2fs",
                    context,
                    attempt,
                    self.send_retries,
                    backoff,
                )
                time.sleep(backoff)
        return False

    def _send_to_dlq(self, reason: str, payload: Dict[str, Any]) -> bool:
        dlq_message = {
            "stage": "transform",
            "reason": reason,
            "failed_at": datetime.utcnow().isoformat(),
            "payload": payload,
        }
        return self.producer.send(self.dlq_topic, dlq_message, validate=False)

    def _update_source_stats(self, source: str, success: bool, count: int = 1):
        """Update statistics for a source."""
        if source not in self.source_stats:
            if len(self.source_stats) >= self.max_source_stats:
                self.source_stats.popitem(last=False)
            self.source_stats[source] = {"processed": 0, "success": 0, "failed": 0}
        else:
            # Track recency to keep most active sources.
            self.source_stats.move_to_end(source)
        self.source_stats[source]["processed"] += count
        if success:
            self.source_stats[source]["success"] += count
        else:
            self.source_stats[source]["failed"] += count

    def _emit_cleaning_metadata(self, source: str):
        """Emit cleaning metadata to metadata_topic."""
        if source not in self.source_stats:
            return
        
        stats = self.source_stats[source]
        applied_rules = (
            [rule.rule_id for rule in self.rules]
            if self.rules
            else [
                "remove_null_fields",
                "trim_strings",
                "normalize_whitespace",
                "handle_empty_strings",
                "coerce_types",
                "validate_row"
            ]
        )
        metadata = MetadataSchema.create_cleaning_metadata(
            source_id=source,
            rows_processed=stats["processed"],
            rows_cleaned=stats["success"],
            rows_failed=stats["failed"],
            cleaning_rules_applied=applied_rules,
            validation_warnings=list(self.warnings)[-10:] if self.warnings else []  # Last 10 warnings
        )
        try:
            self.producer.send("metadata_topic", metadata)
            logger.info(f"[TRANSFORMER] Emitted cleaning metadata for {source}")
        except Exception as exc:
            logger.warning("[TRANSFORMER] Cleaning metadata side-effect failed and was skipped: %s", exc)

    def _load_rules(self) -> List[Any]:
        rules_path = os.getenv("TRANSFORMER_RULES_PATH")
        if not rules_path:
            return []
        try:
            from shared.models.rule_yaml_parser import load_rules_from_yaml
            from shared.models.rules_engine import RulesEngine

            rules = load_rules_from_yaml(rules_path)
            errors = RulesEngine.validate_rules(rules)
            if errors:
                logger.warning("[TRANSFORMER] Rule validation errors: %s", errors)
            return rules
        except Exception as e:
            logger.warning("[TRANSFORMER] Failed to load rules from %s: %s", rules_path, e)
            return []

    def _init_quarantine_manager(self) -> QuarantineManager | None:
        try:
            client = Client(
                host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
                port=int(os.getenv("CLICKHOUSE_PORT", "9000")),
                user=os.getenv("CLICKHOUSE_USER", "default"),
                password=os.getenv("CLICKHOUSE_PASSWORD", ""),
                database=os.getenv("CLICKHOUSE_DATABASE", "etl"),
            )
            return QuarantineManager(client)
        except Exception as e:
            logger.warning("[TRANSFORMER] Failed to initialize QuarantineManager: %s", e)
            return None

    def _init_quality_metrics_manager(self) -> QualityMetricsManager | None:
        try:
            client = Client(
                host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
                port=int(os.getenv("CLICKHOUSE_PORT", "9000")),
                user=os.getenv("CLICKHOUSE_USER", "default"),
                password=os.getenv("CLICKHOUSE_PASSWORD", ""),
                database=os.getenv("CLICKHOUSE_DATABASE", "etl"),
            )
            return QualityMetricsManager(client)
        except Exception as e:
            logger.warning("[TRANSFORMER] Failed to initialize QualityMetricsManager: %s", e)
            return None

    def _init_schema_contract_store(self):
        clickhouse_client = None
        if self.quarantine_manager and getattr(self.quarantine_manager, "client", None) is not None:
            clickhouse_client = self.quarantine_manager.client
        else:
            try:
                clickhouse_client = Client(
                    host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
                    port=int(os.getenv("CLICKHOUSE_PORT", "9000")),
                    user=os.getenv("CLICKHOUSE_USER", "default"),
                    password=os.getenv("CLICKHOUSE_PASSWORD", ""),
                    database=os.getenv("CLICKHOUSE_DATABASE", "etl"),
                )
            except Exception as exc:
                logger.warning("[TRANSFORMER] ClickHouse client unavailable for schema store: %s", exc)
        return build_schema_contract_store_from_env(clickhouse_client)

    def _process_batch(self, messages: List[Dict[str, Any]]) -> bool:
        """
        Clean and transform a batch of rows with comprehensive error handling.
        
        Args:
            messages: Messages from extracted_rows_topic
        """
        if not messages:
            return True

        try:
            start_time = datetime.utcnow()
            row_results, stats = self.transformer_service.process_batch(messages)
            self.processed_count += stats["processed"]
            self.failed_count += stats["failed"]
            self.warnings.extend(stats["warnings"])

            batch_sources = set()
            quality_groups: Dict[tuple, Dict[str, Any]] = {}
            output_batches: Dict[tuple, List[Dict[str, Any]]] = {}

            for result in row_results:
                source = result.get("source", "unknown")
                batch_sources.add(source)
                if result["status"] != "success":
                    self._update_source_stats(source, False)
                    if ERRORS_TOTAL:
                        ERRORS_TOTAL.labels(service="transformer", stage="transform").inc()
                    continue

                clean_message = result["clean_message"]
                # Lineage tracking
                parent_lineage_id = None
                if clean_message.get("_parent_lineage_row_id"):
                    parent_lineage_id = UUID(clean_message["_parent_lineage_row_id"])

                lineage_row_id = LineageTracker.deterministic_row_id(
                    source_id=clean_message.get("source", "unknown"),
                    batch_id=clean_message.get("_batch_id", "") or clean_message.get("batch_id", ""),
                    dedup_key=clean_message.get("_transformed_dedup_key", ""),
                    stage="transform",
                )
                clean_message["_lineage_row_id"] = str(lineage_row_id)
                clean_message["_parent_lineage_row_id"] = clean_message.get("_parent_lineage_row_id")
                if self.lineage_tracker:
                    try:
                        self.lineage_tracker.record_transformation(
                            LineageRecord(
                                row_id=lineage_row_id,
                                source_id=clean_message.get("source", "unknown"),
                                batch_id=clean_message.get("_batch_id", "") or clean_message.get("batch_id", ""),
                                stage="transform",
                                applied_rules=clean_message.get("_applied_rules", []),
                                parent_row_ids=[parent_lineage_id] if parent_lineage_id else [],
                            )
                        )
                    except Exception as exc:
                        logger.warning("[TRANSFORMER] Lineage side-effect failed and was skipped: %s", exc)

                batch_key = (
                    clean_message.get("source") or clean_message.get("source_id"),
                    clean_message.get("_batch_id") or clean_message.get("batch_id"),
                    clean_message.get("schema_version") or "derived_unknown",
                )
                output_batches.setdefault(batch_key, []).append(clean_message)
                if len(output_batches[batch_key]) >= self.output_batch_size:
                    payload = {
                        "source": batch_key[0],
                        "source_id": batch_key[0],
                        "batch_id": batch_key[1],
                        "schema_version": batch_key[2],
                        "rows": output_batches[batch_key],
                        "row_count": len(output_batches[batch_key]),
                    }
                    sent = self._send_with_retry("clean_rows_topic", payload, "clean_rows_topic batch")
                    if sent:
                        self.success_count += len(output_batches[batch_key])
                        self._update_source_stats(source, True, len(output_batches[batch_key]))
                        if ROWS_PROCESSED:
                            ROWS_PROCESSED.labels(service="transformer", stage="transform").inc(len(output_batches[batch_key]))
                    else:
                        if self._send_to_dlq("clean_rows_send_failed", payload):
                            logger.warning("[TRANSFORMER] Sent failed batch to DLQ")
                        else:
                            logger.error("[TRANSFORMER] Failed to send cleaned batch and DLQ handoff failed")
                        self.failed_count += len(output_batches[batch_key])
                        self._update_source_stats(source, False, len(output_batches[batch_key]))
                        logger.error("[TRANSFORMER] Failed to send cleaned batch to Kafka")
                        if ERRORS_TOTAL:
                            ERRORS_TOTAL.labels(service="transformer", stage="transform").inc(len(output_batches[batch_key]))
                    output_batches[batch_key] = []

                key = (clean_message.get("source"), clean_message.get("_batch_id") or clean_message.get("batch_id"))
                quality_groups.setdefault(key, {"rows": [], "validity": []})
                quality_groups[key]["rows"].append(clean_message["data"])
                if clean_message.get("validation_score") is not None:
                    quality_groups[key]["validity"].append(float(clean_message.get("validation_score")))
                elif clean_message.get("quality_score") is not None:
                    quality_groups[key]["validity"].append(float(clean_message.get("quality_score")))

            # Flush remaining output batches
            for batch_key, rows in output_batches.items():
                if not rows:
                    continue
                payload = {
                    "source": batch_key[0],
                    "source_id": batch_key[0],
                    "batch_id": batch_key[1],
                    "schema_version": batch_key[2],
                    "rows": rows,
                    "row_count": len(rows),
                }
                sent = self._send_with_retry("clean_rows_topic", payload, "clean_rows_topic final batch")
                if sent:
                    self.success_count += len(rows)
                    self._update_source_stats(batch_key[0], True, len(rows))
                    if ROWS_PROCESSED:
                        ROWS_PROCESSED.labels(service="transformer", stage="transform").inc(len(rows))
                else:
                    if self._send_to_dlq("clean_rows_send_failed", payload):
                        logger.warning("[TRANSFORMER] Sent failed final batch to DLQ")
                    else:
                        logger.error("[TRANSFORMER] Failed final batch send and DLQ handoff failed")
                    self.failed_count += len(rows)
                    self._update_source_stats(batch_key[0], False, len(rows))
                    if ERRORS_TOTAL:
                        ERRORS_TOTAL.labels(service="transformer", stage="transform").inc(len(rows))

            # Persist quality metrics per batch
            if self.quality_metrics_manager:
                for (source_id, batch_id), payload in quality_groups.items():
                    if not source_id or not batch_id:
                        continue
                    try:
                        metrics = self.quality_metrics_manager.compute_batch_metrics(
                            batch_id=batch_id,
                            source_id=source_id,
                            rows=payload["rows"],
                            validity_scores=payload["validity"],
                        )
                        self.quality_metrics_manager.persist_metrics(metrics)
                        self.quality_metrics_manager.detect_anomalies(source_id, "quality", metrics.quality_score)
                    except Exception as exc:
                        logger.warning("[TRANSFORMER] Quality metrics side-effect failed and was skipped: %s", exc)

            if PROCESS_LATENCY:
                duration = (datetime.utcnow() - start_time).total_seconds()
                PROCESS_LATENCY.labels(service="transformer", stage="transform").observe(duration)

            while self.processed_count >= self._next_metadata_emit:
                for source in batch_sources:
                    self._emit_cleaning_metadata(source)
                logger.info(
                    "[TRANSFORMER] Processed %s rows (success: %s, failed: %s)",
                    self.processed_count,
                    self.success_count,
                    self.failed_count,
                )
                self._next_metadata_emit += self.metadata_interval

            return True
        except Exception as e:
            logger.error("[TRANSFORMER ERROR] Failed to process batch: %s", e)
            import traceback
            logger.error(traceback.format_exc())
            return False

    def listen(self):
        """
        Listen to extracted_rows_topic and process messages.
        Emits final metadata on completion.
        """
        logger.info("[TRANSFORMER] Listening to extracted_rows_topic...")
        
        try:
            pending_records = []
            for message, record in self.consumer.listen_committable():
                message_has_rows = isinstance(message, dict) and "rows" in message
                if isinstance(message, dict) and "rows" in message:
                    parent = {k: v for k, v in message.items() if k != "rows"}
                    for row in message.get("rows", []):
                        expanded = {**parent, **row}
                        expanded.setdefault("source", parent.get("source"))
                        expanded.setdefault("source_id", parent.get("source") or parent.get("source_id"))
                        expanded.setdefault("batch_id", parent.get("batch_id"))
                        expanded.setdefault("schema_version", parent.get("schema_version") or "derived_unknown")
                        self._pending_messages.append(expanded)
                else:
                    self._pending_messages.append(message)
                pending_records.append(record)
                # Extractor already sends row batches, so process immediately for low-latency flow.
                should_process = len(self._pending_messages) >= self.batch_size or message_has_rows
                if should_process:
                    processed = self._process_batch(self._pending_messages)
                    if processed:
                        for pending_record in pending_records:
                            self.consumer.commit(pending_record)
                        self._pending_messages = []
                        pending_records = []
                    else:
                        logger.warning("[TRANSFORMER] Batch processing failed, offsets not committed")
        except KeyboardInterrupt:
            logger.info("[TRANSFORMER] Shutting down...")
        except Exception as e:
            logger.error(f"[TRANSFORMER] Fatal error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            if self._pending_messages:
                processed = self._process_batch(self._pending_messages)
                if processed:
                    self.consumer.commit()
                    self._pending_messages = []
            # Emit final metadata for all sources
            for source in list(self.source_stats.keys()):
                self._emit_cleaning_metadata(source)
            logger.info(f"[TRANSFORMER] Final stats - Processed: {self.processed_count}, Success: {self.success_count}, Failed: {self.failed_count}")


def start_listener():
    """Entry point for the Kafka listener."""
    logger.info("[TRANSFORMER] Starting row listener...")
    parallelism = int(os.getenv("KAFKA_CONSUMER_PARALLELISM", "1"))
    if parallelism <= 1:
        listener = RawRowListener()
        listener.listen()
        return

    threads = []
    for i in range(parallelism):
        t = threading.Thread(
            target=lambda: RawRowListener().listen(),
            name=f"transformer-consumer-{i+1}",
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()
