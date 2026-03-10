"""
Enhanced Loader Service Kafka Listener
Batch loads data into ClickHouse with comprehensive error handling and metadata
"""
import os
import json
import logging
import time
import threading
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from uuid import UUID
from collections import defaultdict
from shared.utils.kafka_consumer import KafkaMessageConsumer
from shared.utils.kafka_producer import KafkaMessageProducer
from shared.utils.metadata_schema import MetadataSchema
from shared.utils.idempotency_manager import (
    IdempotencyClaim,
    IdempotencyManager,
    PipelineStage,
    IdempotencyKey,
)
from shared.utils.logging_utils import configure_logging
from shared.utils.metrics import ROWS_PROCESSED, ERRORS_TOTAL, PROCESS_LATENCY, start_metrics_server
from shared.utils.health_server import start_health_server
from shared.utils.lineage_tracker import LineageTracker
from shared.models.lineage import LineageRecord
from shared.utils.tracing import configure_tracing
from shared.utils.quarantine_manager import QuarantineManager, QuarantineRecord
from .loader_logic import LoaderLogic
from .clickhouse_client import ClickHouseClient

logger = logging.getLogger(__name__)

configure_logging()
configure_tracing("loader-service")
start_metrics_server(int(os.getenv("LOADER_METRICS_PORT", "9103")))
start_health_server(int(os.getenv("LOADER_HEALTH_PORT", "8085")))

class CleanRowListener:
    """
    Enhanced listener for clean_rows_topic with batch loading.
    
    Features:
    - Batch inserts for performance
    - Table schema management
    - Error handling and retries
    - Metadata emission
    - Connection pooling
    """

    def __init__(self, batch_size: int = 1000):
        """
        Initialize loader listener.
        
        Args:
            batch_size: Number of rows to batch before inserting (default: 1000)
        """
        self.consumer = KafkaMessageConsumer("clean_rows_topic")
        self.producer = KafkaMessageProducer()
        default_batch_size = int(os.getenv("LOADER_BATCH_SIZE", str(batch_size)))
        self.batch_size = default_batch_size
        self.batch_size_overrides = self._load_batch_size_overrides()
        self.max_buffer_rows = int(os.getenv("LOADER_MAX_BUFFER_ROWS", "20000"))
        self.max_buffer_rows_per_table = int(os.getenv("LOADER_MAX_BUFFER_ROWS_PER_TABLE", "10000"))
        self.transactional_load = os.getenv("LOADER_TRANSACTIONAL_LOAD", "true").lower() in ("1", "true", "yes")
        self.backpressure_topic = os.getenv("PIPELINE_BACKPRESSURE_TOPIC", "pipeline_backpressure_topic")
        self.retry_limit = int(os.getenv("LOADER_RETRIES", "3"))
        self.backoff_base = float(os.getenv("LOADER_BACKOFF_BASE", "0.5"))
        self.max_backoff = float(os.getenv("LOADER_MAX_BACKOFF", "5.0"))
        self.stateless_mode = os.getenv("STATELESS_MODE", "false").lower() in ("1", "true", "yes")
        self.dlq_topic = os.getenv("LOADER_DLQ_TOPIC", "load_rows_dlq")
        
        # Initialize ClickHouse client using NATIVE protocol
        # IMPORTANT: ETL loader uses clickhouse_driver (native TCP on port 9000)
        # This is DIFFERENT from Django HTTP queries (port 8123)
        clickhouse_config = {
            "host": os.getenv("CLICKHOUSE_HOST", "clickhouse"),
            "port": int(os.getenv("CLICKHOUSE_PORT", "9000")),  # Native protocol port
            "user": os.getenv("CLICKHOUSE_USER", "etl_user"),
            "password": os.getenv("CLICKHOUSE_PASSWORD", "etl_pass123"),
            "database": os.getenv("CLICKHOUSE_DATABASE", "etl"),
            "connect_timeout": int(os.getenv("CLICKHOUSE_CONNECT_TIMEOUT", "10")),
            "send_receive_timeout": int(os.getenv("CLICKHOUSE_SEND_RECEIVE_TIMEOUT", "300")),
            "sync_request_timeout": int(os.getenv("CLICKHOUSE_SYNC_REQUEST_TIMEOUT", "300")),
            "insert_retries": int(os.getenv("CLICKHOUSE_INSERT_RETRIES", "3")),
            "circuit_breaker_threshold": int(os.getenv("LOADER_CIRCUIT_BREAKER_THRESHOLD", "5")),
            "circuit_breaker_recovery": int(os.getenv("LOADER_CIRCUIT_BREAKER_RECOVERY", "30")),
        }
        
        self.loader = LoaderLogic(clickhouse_config)
        self.quarantine_manager = self._init_quarantine_manager(clickhouse_config)
        
        # Initialize IdempotencyManager for hash generation
        self.idempotency_manager = IdempotencyManager(self.loader.client.client)
        try:
            self.lineage_tracker = LineageTracker()
        except Exception as exc:
            logger.warning("[LOADER] Lineage tracker unavailable, continuing without lineage side-effects: %s", exc)
            self.lineage_tracker = None
        
        # Batch buffers per table
        self.batch_buffers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.pending_idempotency_keys: Dict[str, List[str]] = defaultdict(list)
        self.table_sources: Dict[str, str] = {}
        self.table_schemas: Dict[str, Dict[str, str]] = {}  # table_name -> {col: type}
        self.column_name_mappings: Dict[str, Dict[str, str]] = defaultdict(dict)
        self.buffered_rows_total = 0
        
        # Statistics tracking
        self.loaded_count = 0
        self.error_count = 0
        self.source_stats: Dict[str, Dict[str, int]] = {}  # source -> {loaded, failed}
        
        # Metadata emission interval
        self.metadata_interval = 5000  # Emit metadata every 5000 rows

    def _init_quarantine_manager(self, clickhouse_config: Dict[str, Any]) -> Optional[QuarantineManager]:
        try:
            client = self.loader.client.client
            return QuarantineManager(client)
        except Exception as e:
            logger.warning("[LOADER] Failed to initialize QuarantineManager: %s", e)
            return None

    def _send_to_dlq(self, reason: str, source: str, table_name: str, rows: List[Dict[str, Any]], error: str) -> bool:
        dlq_message = {
            "stage": "load",
            "reason": reason,
            "source": source,
            "table": table_name,
            "failed_at": datetime.utcnow().isoformat(),
            "error": error,
            "row_count": len(rows),
            "rows": rows,
        }
        return self.producer.send(self.dlq_topic, dlq_message, validate=False)

    def _load_batch_size_overrides(self) -> Dict[str, int]:
        overrides_raw = os.getenv("LOADER_BATCH_SIZE_OVERRIDES", "")
        if not overrides_raw:
            return {}
        try:
            parsed = json.loads(overrides_raw)
            if isinstance(parsed, dict):
                return {str(k): int(v) for k, v in parsed.items()}
        except Exception as e:
            logger.warning("[LOADER] Invalid LOADER_BATCH_SIZE_OVERRIDES: %s", e)
        return {}

    def _get_batch_size_for_table(self, table_name: str) -> int:
        return int(self.batch_size_overrides.get(table_name, self.batch_size))

    def _sanitize_table_name(self, source: str) -> str:
        """Sanitize source name to valid ClickHouse table name."""
        # Replace invalid characters
        table_name = source.replace(".", "_").replace("/", "_").replace("-", "_")
        table_name = "".join(c if c.isalnum() or c == "_" else "_" for c in table_name)
        # Ensure it starts with letter or underscore
        if table_name and not table_name[0].isalpha():
            table_name = f"t_{table_name}"
        return table_name or "unknown_table"

    def _sanitize_column_name(self, name: str) -> str:
        value = str(name or "").strip()
        if not value:
            value = "column"
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", value)
        safe = re.sub(r"_+", "_", safe).strip("_") or "column"
        if safe[0].isdigit():
            safe = f"c_{safe}"
        return safe

    def _normalize_row_columns(self, table_name: str, row_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize column identifiers and keep a stable original->safe mapping.
        """
        normalized: Dict[str, Any] = {}
        mapping = self.column_name_mappings[table_name]

        for original_name, value in row_data.items():
            original_key = str(original_name)
            safe_name = mapping.get(original_key)
            if not safe_name:
                safe_name = self._sanitize_column_name(original_key)
                candidate = safe_name
                suffix = 1
                while candidate in normalized or candidate in mapping.values():
                    suffix += 1
                    candidate = f"{safe_name}_{suffix}"
                safe_name = candidate
                mapping[original_key] = safe_name
                if safe_name != original_key:
                    logger.info(
                        "[LOADER] Column normalized for table %s: '%s' -> '%s'",
                        table_name,
                        original_key,
                        safe_name,
                    )
            normalized[safe_name] = value

        return normalized

    def _parse_datetime_value(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if not isinstance(value, str):
            return value
        candidate = value.strip()
        if not candidate:
            return value
        try:
            normalized = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return value

    def _safe_record_lineage(self, record: LineageRecord) -> None:
        if not self.lineage_tracker:
            return
        try:
            self.lineage_tracker.record_transformation(record)
        except Exception as exc:
            logger.warning("[LOADER] Lineage write failed and was skipped: %s", exc)

    def _ensure_table_schema(self, source: str, row_data: Dict[str, Any]) -> Optional[str]:
        """
        Ensure table exists with correct schema.
        
        Args:
            source: Source identifier
            row_data: Sample row to infer schema
            
        Returns:
            Table name if successful, None otherwise
        """
        if not row_data:
            return None
        
        table_name = self._sanitize_table_name(source)

        incoming_columns = {
            col: self._infer_clickhouse_type(col, val) for col, val in row_data.items()
        }
        cached_columns = self.table_schemas.get(table_name, {}) if not self.stateless_mode else {}
        columns = {**cached_columns, **incoming_columns}
        
        try:
            # Create table if it doesn't exist
            if not self.loader.client.table_exists(table_name):
                engine = "MergeTree()"
                partition_by = None
                order_by = "tuple()"
                settings = "index_granularity=8192"
                if "_transformed_dedup_key" in columns:
                    engine = "ReplacingMergeTree(_loaded_at)"
                    order_by = "_transformed_dedup_key"
                    if "_loaded_at" in columns:
                        partition_by = "toYYYYMM(_loaded_at)"
                elif "_loaded_at" in columns:
                    partition_by = "toYYYYMM(_loaded_at)"
                    order_by = "(_batch_id, _loaded_at)" if "_batch_id" in columns else "_loaded_at"
                self.loader.client.create_table(
                    table_name,
                    columns,
                    engine=engine,
                    partition_by=partition_by,
                    order_by=order_by,
                    settings=settings,
                )
                logger.info(f"[LOADER] Created table {table_name} with {len(columns)} columns")
            else:
                # Evolve schema on drift: add missing columns safely.
                existing_schema = self.loader.client.get_table_schema(table_name)
                existing_columns = set(existing_schema.keys())
                to_add = {col: col_type for col, col_type in columns.items() if col not in existing_columns}
                if to_add:
                    self.loader.client.add_columns_if_missing(table_name, to_add)
                    logger.info("[LOADER] Evolved table %s with new columns: %s", table_name, sorted(to_add.keys()))
                    # Refresh schema cache after ALTER.
                    existing_schema = self.loader.client.get_table_schema(table_name)
                columns = {**existing_schema, **columns} if existing_schema else columns

            if not self.stateless_mode:
                self.table_schemas[table_name] = columns
            
            return table_name
            
        except Exception as e:
            logger.error(f"[LOADER ERROR] Failed to ensure table schema for {table_name}: {e}")
            return None

    def _infer_clickhouse_type(self, column_name: str, value: Any) -> str:
        if column_name in {"_loaded_at", "_extracted_at", "_cleaned_at"}:
            return "DateTime64(3)"
        if isinstance(value, bool):
            return "Bool"
        if isinstance(value, int) and not isinstance(value, bool):
            return "Int64"
        if isinstance(value, float):
            return "Float64"
        if isinstance(value, datetime):
            return "DateTime64(3)"
        if isinstance(value, str):
            candidate = value.strip()
            if "T" in candidate:
                normalized = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
                try:
                    datetime.fromisoformat(normalized)
                    return "DateTime64(3)"
                except ValueError:
                    pass
        return "String"

    def _emit_backpressure_signal(self, level: str, table_name: str, buffered_rows: int) -> None:
        payload = {
            "stage": "load",
            "level": level,
            "table": table_name,
            "buffered_rows": buffered_rows,
            "max_buffer_rows": self.max_buffer_rows,
            "emitted_at": datetime.utcnow().isoformat(),
        }
        try:
            self.producer.send(self.backpressure_topic, payload, validate=False)
        except Exception as exc:
            logger.warning("[LOADER] Backpressure signal failed and was skipped: %s", exc)

    def _apply_backpressure(self, table_name: str) -> None:
        if self.max_buffer_rows <= 0:
            return
        if len(self.batch_buffers[table_name]) >= self.max_buffer_rows_per_table:
            self._emit_backpressure_signal("table_high", table_name, len(self.batch_buffers[table_name]))
            self._flush_batch(table_name, table_name.replace("_", "."))
        if self.buffered_rows_total <= self.max_buffer_rows:
            return
        self._emit_backpressure_signal("global_high", table_name, self.buffered_rows_total)
        # Flush largest buffers first until under limit
        buffers = sorted(self.batch_buffers.items(), key=lambda item: len(item[1]), reverse=True)
        for tbl, rows in buffers:
            if self.buffered_rows_total <= self.max_buffer_rows:
                break
            if rows:
                source_guess = tbl.replace("_", ".")
                self._flush_batch(tbl, source_guess)

    def _flush_batch(self, table_name: str, source: str) -> bool:
        """
        Flush batch buffer for a table.
        
        Args:
            table_name: Table name
            source: Source identifier
        """
        if table_name not in self.batch_buffers or not self.batch_buffers[table_name]:
            return True
        source = self.table_sources.get(table_name, source)
        
        batch = list(self.batch_buffers[table_name])
        pending_hashes = list(self.pending_idempotency_keys.get(table_name, []))
        pending_claims: List[IdempotencyClaim] = []
        if self.idempotency_manager and pending_hashes:
            key_objects = [self._build_idempotency_key(source, dedup_hash) for dedup_hash in pending_hashes]
            claims = self.idempotency_manager.claim_new_keys(key_objects, PipelineStage.LOAD)
            claim_by_dedup = {claim.key.to_dedup_key(): claim for claim in claims}
            allowed = set(claim_by_dedup.keys())
            filtered_batch: List[Dict[str, Any]] = []
            filtered_hashes: List[str] = []
            filtered_claims: List[IdempotencyClaim] = []
            duplicates = 0
            for row, dedup_hash in zip(batch, pending_hashes):
                key = self._build_idempotency_key(source, dedup_hash)
                if key.to_dedup_key() in allowed:
                    filtered_batch.append(row)
                    filtered_hashes.append(dedup_hash)
                    filtered_claims.append(claim_by_dedup[key.to_dedup_key()])
                else:
                    duplicates += 1
            if duplicates:
                logger.info("[LOADER] Skipped %s duplicate rows for table %s", duplicates, table_name)
                self.buffered_rows_total = max(0, self.buffered_rows_total - duplicates)
            batch = filtered_batch
            pending_hashes = filtered_hashes
            pending_claims = filtered_claims

        if not batch:
            self.batch_buffers[table_name] = []
            self.pending_idempotency_keys[table_name] = []
            return True

        start_time = time.time()
        
        try:
            start_time = time.time()
            # Insert batch with retries and circuit breaker
            batch_size = self._get_batch_size_for_table(table_name)
            inserted = self.loader.load_batch_resilient(
                table_name,
                batch,
                batch_size=batch_size,
                transactional=self.transactional_load,
                retries=self.retry_limit,
                backoff_base=self.backoff_base,
                max_backoff=self.max_backoff,
            )
            
            # Update statistics
            self.loaded_count += inserted
            if source not in self.source_stats:
                self.source_stats[source] = {"loaded": 0, "failed": 0}
            self.source_stats[source]["loaded"] += inserted
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Publish success status
            status_message = {
                "source": source,
                "table": table_name,
                "status": "success",
                "row_count": inserted,
                "load_duration_ms": duration_ms
            }
            try:
                self.producer.send("load_rows_topic", status_message)
            except Exception as exc:
                logger.warning("[LOADER] Load status side-effect failed and was skipped: %s", exc)
            
            logger.info(f"[LOADER] Flushed batch: {inserted} rows to {table_name} in {duration_ms}ms")
            if PROCESS_LATENCY:
                PROCESS_LATENCY.labels(service="loader", stage="load").observe((time.time() - start_time))
            
            # Clear batch
            self.buffered_rows_total = max(0, self.buffered_rows_total - len(batch))
            self.batch_buffers[table_name] = []
            self.pending_idempotency_keys[table_name] = []
            return True
            
        except Exception as e:
            self.error_count += len(batch)
            if source not in self.source_stats:
                self.source_stats[source] = {"loaded": 0, "failed": 0}
            self.source_stats[source]["failed"] += len(batch)
            
            logger.error(f"[LOADER ERROR] Failed to flush batch for {table_name}: {e}")
            
            # Publish error status
            error_message = {
                "source": source,
                "table": table_name,
                "status": "error",
                "error": str(e),
                "row_count": len(batch)
            }
            try:
                self.producer.send("load_rows_topic", error_message)
            except Exception as exc:
                logger.warning("[LOADER] Load error status side-effect failed and was skipped: %s", exc)
            if ERRORS_TOTAL:
                ERRORS_TOTAL.labels(service="loader", stage="load").inc()

            dlq_ok = self._send_to_dlq("clickhouse_load_failed", source, table_name, batch, str(e))
            if dlq_ok:
                if self.idempotency_manager and pending_claims:
                    self.idempotency_manager.rollback_claims(pending_claims, PipelineStage.LOAD)
                self.buffered_rows_total = max(0, self.buffered_rows_total - len(batch))
                self.batch_buffers[table_name] = []
                self.pending_idempotency_keys[table_name] = []
                logger.warning("[LOADER] Batch moved to DLQ after load failure")
                return True
            if self.idempotency_manager and pending_claims:
                self.idempotency_manager.rollback_claims(pending_claims, PipelineStage.LOAD)
            logger.error("[LOADER] DLQ handoff failed, retaining batch in memory for retry")
            return False

    def _emit_loading_metadata(self, source: str):
        """Emit loading metadata to metadata_topic."""
        if source not in self.source_stats:
            return
        
        stats = self.source_stats[source]
        table_name = self._sanitize_table_name(source)
        
        metadata = MetadataSchema.create_loading_metadata(
            source_id=source,
            table_name=table_name,
            rows_loaded=stats["loaded"],
            rows_failed=stats["failed"],
            errors=[]  # Can be enhanced to track specific errors
        )

        try:
            self.producer.send("metadata_topic", metadata)
            logger.info(f"[LOADER] Emitted loading metadata for {source}")
        except Exception as exc:
            logger.warning("[LOADER] Loading metadata side-effect failed and was skipped: %s", exc)

    def process_row(self, message: Dict[str, Any]) -> Optional[str]:
        """
        Process a single row and add to batch buffer.
        
        Args:
            message: Message from clean_rows_topic
        """
        source = message.get("source") or message.get("source_id") or "unknown"
        row_data = message.get("data", {})
        
        if not row_data:
            logger.debug(f"[LOADER] Skipping empty row from {source}")
            return None
        
        try:
            # Preserve deduplication keys and metadata
            original_dedup_key = message.get("_original_dedup_key")
            transformed_dedup_key = message.get("_transformed_dedup_key")
            batch_id = message.get("_batch_id")
            now_utc = datetime.now(timezone.utc)
            extracted_at = self._parse_datetime_value(message.get("_extracted_at")) or now_utc
            cleaned_at = self._parse_datetime_value(message.get("_cleaned_at")) or extracted_at
            schema_version = message.get("schema_version") or "derived_unknown"

            table_name_hint = self._sanitize_table_name(source)
            normalized_row_data = self._normalize_row_columns(table_name_hint, row_data)
            
            dedup_basis = {
                "source_id": source,
                "_original_dedup_key": original_dedup_key,
                "data": normalized_row_data,
            }
            row_dedup_key = transformed_dedup_key or self.idempotency_manager.generate_row_hash(dedup_basis)

            # Add metadata columns to row data for storage in ClickHouse
            enriched_row = {
                **normalized_row_data,
                "_original_dedup_key": original_dedup_key or "",
                "_transformed_dedup_key": row_dedup_key,
                "_batch_id": batch_id or "",
                "_schema_version": schema_version,
                "_extracted_at": extracted_at,
                "_cleaned_at": cleaned_at,
                "_loaded_at": now_utc,
            }

            parent_lineage_id = message.get("_lineage_row_id")
            lineage_row_id = LineageTracker.deterministic_row_id(
                source_id=source,
                batch_id=batch_id or "",
                dedup_key=transformed_dedup_key or "",
                stage="load",
            )
            self._safe_record_lineage(
                LineageRecord(
                    row_id=lineage_row_id,
                    source_id=source,
                    batch_id=batch_id or "",
                    stage="load",
                    applied_rules=[],
                    parent_row_ids=[UUID(parent_lineage_id)] if parent_lineage_id else [],
                )
            )
            
            # Ensure table schema exists
            table_name = self._ensure_table_schema(source, enriched_row)
            
            if not table_name:
                self.error_count += 1
                logger.error(f"[LOADER] Failed to get table name for {source}")
                return None

            # Add to batch buffer
            self.batch_buffers[table_name].append(enriched_row)
            self.pending_idempotency_keys[table_name].append(row_dedup_key)
            self.table_sources[table_name] = source
            self.buffered_rows_total += 1
            if ROWS_PROCESSED:
                ROWS_PROCESSED.labels(service="loader", stage="load").inc()
            
            # Flush if batch is full
            self._apply_backpressure(table_name)
            if len(self.batch_buffers[table_name]) >= self._get_batch_size_for_table(table_name):
                if not self._flush_batch(table_name, source):
                    return None
            
            # Emit metadata periodically
            if self.loaded_count % self.metadata_interval == 0 and self.loaded_count > 0:
                self._emit_loading_metadata(source)
                logger.info(f"[LOADER] Processed {self.loaded_count} rows (errors: {self.error_count})")
            return table_name
                
        except Exception as e:
            self.error_count += 1
            logger.error(f"[LOADER ERROR] Failed to process row from {source}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def _build_idempotency_key(self, source: str, row_hash: str):
        batch_id = f"load:{source}"
        return IdempotencyKey(source_id=source, batch_id=batch_id, row_hash=row_hash)

    def _process_message(self, message: Dict[str, Any]) -> bool:
        impacted = set()
        if isinstance(message, dict) and "rows" in message:
            parent = {k: v for k, v in message.items() if k != "rows"}
            for row in message.get("rows", []):
                expanded = {**parent, **row}
                expanded.setdefault("source", parent.get("source"))
                expanded.setdefault("source_id", parent.get("source") or parent.get("source_id"))
                expanded.setdefault("batch_id", parent.get("batch_id"))
                expanded.setdefault("schema_version", parent.get("schema_version") or "derived_unknown")
                table_name = self.process_row(expanded)
                if table_name:
                    impacted.add((table_name, expanded.get("source", "unknown")))
                else:
                    return False
        else:
            table_name = self.process_row(message)
            if not table_name:
                return False
            impacted.add((table_name, message.get("source", "unknown")))

        for table_name, source in impacted:
            if not self._flush_batch(table_name, source):
                return False
        return True

    def listen(self):
        """
        Listen to clean_rows_topic and process messages with batch loading.
        Flushes remaining batches on completion.
        """
        logger.info("[LOADER] Listening to clean_rows_topic...")
        
        try:
            for message, record in self.consumer.listen_committable():
                if self._process_message(message):
                    self.consumer.commit(record)
                else:
                    logger.warning("[LOADER] Message processing failed, offset not committed")
        except KeyboardInterrupt:
            logger.info("[LOADER] Shutting down...")
        except Exception as e:
            logger.error(f"[LOADER] Fatal error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # Flush all remaining batches
            logger.info("[LOADER] Flushing remaining batches...")
            for table_name in list(self.batch_buffers.keys()):
                if self.batch_buffers[table_name]:
                    # Extract source from table name (approximate)
                    source = table_name.replace("_", ".")
                    self._flush_batch(table_name, source)
            
            # Emit final metadata for all sources
            for source in self.source_stats.keys():
                self._emit_loading_metadata(source)
            
            logger.info(f"[LOADER] Final stats - Loaded: {self.loaded_count}, Errors: {self.error_count}")


def start_listener():
    """Entry point for the Kafka listener"""
    print("[LOADER] Starting clean row listener...")
    parallelism = int(os.getenv("KAFKA_CONSUMER_PARALLELISM", "1"))
    if parallelism <= 1:
        listener = CleanRowListener()
        listener.listen()
        return

    threads = []
    for i in range(parallelism):
        t = threading.Thread(
            target=lambda: CleanRowListener().listen(),
            name=f"loader-consumer-{i+1}",
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()
