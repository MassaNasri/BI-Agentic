"""
Enhanced Metadata Service Kafka Listener
Consumes metadata from multiple topics and stores in SurrealDB
"""
import logging
import time
import os
import requests
from typing import Dict, Any
from shared.utils.kafka_consumer import KafkaMessageConsumer
from shared.utils.surreal_client import SurrealClient
from shared.utils.metadata_schema import MetadataSchema
from shared.utils.logging_utils import configure_logging
from shared.utils.metrics import ROWS_PROCESSED, ERRORS_TOTAL, PROCESS_LATENCY, start_metrics_server
from shared.utils.health_server import start_health_server
from shared.utils.tracing import configure_tracing

logger = logging.getLogger(__name__)

configure_logging()
configure_tracing("metadata-service")
start_metrics_server(int(os.getenv("METADATA_METRICS_PORT", "9104")))
start_health_server(int(os.getenv("METADATA_HEALTH_PORT", "8086")))

class MetadataListener:
    """
    Enhanced listener for metadata_topic and load_rows_topic.
    
    Features:
    - Unified metadata storage
    - Validation and error handling
    - Comprehensive logging
    - Metadata aggregation
    """

    def __init__(self):
        # Listen to both metadata_topic (unified metadata) and load_rows_topic (legacy)
        self.metadata_consumer = KafkaMessageConsumer("metadata_topic")
        self.load_status_consumer = KafkaMessageConsumer("load_rows_topic")
        self.surreal = SurrealClient()
        
        # Statistics
        self.metadata_count = 0
        self.load_status_count = 0
        self.error_count = 0

    def _notify_query_service_failure(self, message: Dict[str, Any]) -> bool:
        """Deliver a terminal loader failure through the durable status consumer."""
        workspace_id = message.get("workspace_id")
        dataset_id = message.get("dataset_id")
        job_id = message.get("ingestion_job_id")
        if workspace_id in (None, "") or dataset_id in (None, "") or not job_id:
            logger.warning("[METADATA] Legacy load failure has no complete ingestion scope; callback skipped")
            return True
        try:
            workspace_id = int(workspace_id)
            dataset_id = int(dataset_id)
        except (TypeError, ValueError):
            logger.error("[METADATA] Invalid ingestion scope on load failure; callback skipped as non-retriable")
            return True

        base_url = str(os.getenv("QUERY_SERVICE_URL", "http://query-service:8006")).rstrip("/")
        api_key = str(os.getenv("INGESTION_CALLBACK_API_KEY", ""))
        if not api_key:
            logger.error("[METADATA] INGESTION_CALLBACK_API_KEY is not configured")
            return False
        payload = {
            "dataset_id": dataset_id,
            "workspace_id": workspace_id,
            "expected_state": "processing",
            "etl_status": "failed",
            "etl_message": (
                "ETL loading failed after extraction and cleaning. "
                f"{str(message.get('error') or 'The loader rejected the batch.')[:1000]}"
            ),
        }
        try:
            response = requests.post(
                f"{base_url}/internal/v1/ingestion/jobs/{job_id}/dataset-status",
                json=payload,
                headers={
                    "X-Internal-Service": "etl-metadata",
                    "X-Internal-API-Key": api_key,
                },
                timeout=5,
            )
        except requests.RequestException as exc:
            logger.warning("[METADATA] Ingestion failure callback unavailable: %s", exc)
            return False
        if response.status_code != 200:
            logger.warning(
                "[METADATA] Ingestion failure callback rejected status=%s body=%s",
                response.status_code,
                response.text[:500],
            )
            if 400 <= response.status_code < 500:
                # A malformed or stale scope will never become valid by
                # replaying the same Kafka record. The query-side timeout is
                # the fallback for these non-retriable events.
                return True
            return False
        return True

    def process_metadata(self, message: Dict[str, Any]) -> bool:
        """
        Process unified metadata from metadata_topic.
        
        Args:
            message: Metadata message from metadata_topic
        """
        try:
            # Validate metadata
            is_valid, error = MetadataSchema.validate_metadata(message)
            if not is_valid:
                logger.error(f"[METADATA] Invalid metadata: {error}")
                self.error_count += 1
                return False
            
            metadata_type = message.get("metadata_type")
            source_id = message.get("source_id", "unknown")
            
            # Store in SurrealDB with type-specific table
            table_name = f"{metadata_type}_metadata"
            result = self.surreal.insert(table_name, message)
            
            if result:
                self.metadata_count += 1
                if ROWS_PROCESSED:
                    ROWS_PROCESSED.labels(service="metadata", stage="metadata").inc()
                if self.metadata_count % 100 == 0:
                    logger.info(f"[METADATA] Logged {self.metadata_count} metadata records")
                return True
            else:
                logger.error(f"[METADATA ERROR] Failed to log metadata for {source_id}")
                if ERRORS_TOTAL:
                    ERRORS_TOTAL.labels(service="metadata", stage="metadata").inc()
                self.error_count += 1
                return False
                
        except Exception as e:
            logger.error(f"[METADATA ERROR] Failed to process metadata: {e}")
            import traceback
            logger.error(traceback.format_exc())
            if ERRORS_TOTAL:
                ERRORS_TOTAL.labels(service="metadata", stage="metadata").inc()
            self.error_count += 1
            return False

    def process_load_status(self, message: Dict[str, Any]) -> bool:
        """
        Process load status from load_rows_topic (legacy support).
        
        Args:
            message: Load status message from load_rows_topic
        """
        try:
            source = message.get("source", "unknown")
            status = message.get("status", "unknown")
            table = message.get("table", "")
            
            # Prepare metadata record
            metadata_record = {
                "source": source,
                "table": table,
                "status": status,
                "timestamp": None
            }
            
            # Add error info if present
            if status == "error":
                metadata_record["error"] = message.get("error", "Unknown error")
            
            # Add row count if present
            if "row_count" in message:
                metadata_record["row_count"] = message["row_count"]

            if status == "error" and not self._notify_query_service_failure(message):
                return False
            
            # Insert into SurrealDB load_status table
            result = self.surreal.insert("load_status", metadata_record)
            
            if result:
                self.load_status_count += 1
                if ROWS_PROCESSED:
                    ROWS_PROCESSED.labels(service="metadata", stage="load_status").inc()
                if self.load_status_count % 100 == 0:
                    logger.info(f"[METADATA] Logged {self.load_status_count} load statuses")
                return True
            else:
                logger.error(f"[METADATA ERROR] Failed to log status for {source}")
                if ERRORS_TOTAL:
                    ERRORS_TOTAL.labels(service="metadata", stage="load_status").inc()
                self.error_count += 1
                return False
                
        except Exception as e:
            logger.error(f"[METADATA ERROR] Failed to process load status: {e}")
            import traceback
            logger.error(traceback.format_exc())
            if ERRORS_TOTAL:
                ERRORS_TOTAL.labels(service="metadata", stage="load_status").inc()
            self.error_count += 1
            return False

    def listen_metadata(self):
        """Listen to metadata_topic and process messages"""
        logger.info("[METADATA] Listening to metadata_topic...")
        try:
            for message, record in self.metadata_consumer.listen_committable():
                logger.info("[METADATA] Received metadata message: metadata_type=%s", message.get("metadata_type"))
                if self.process_metadata(message):
                    self.metadata_consumer.commit(record)
                else:
                    logger.warning("[METADATA] Metadata processing failed, offset not committed")
                    self.metadata_consumer.rewind(record)
                    time.sleep(max(0.0, float(os.getenv("KAFKA_PROCESSING_RETRY_SECONDS", "2"))))
        except Exception as e:
            logger.error(f"[METADATA] Error in metadata listener: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def listen_load_status(self):
        """Listen to load_rows_topic and process messages"""
        logger.info("[METADATA] Listening to load_rows_topic...")
        try:
            for message, record in self.load_status_consumer.listen_committable():
                logger.info("[METADATA] Received load status message: status=%s", message.get("status"))
                if self.process_load_status(message):
                    self.load_status_consumer.commit(record)
                else:
                    logger.warning("[METADATA] Load status processing failed, offset not committed")
                    self.load_status_consumer.rewind(record)
                    time.sleep(max(0.0, float(os.getenv("KAFKA_PROCESSING_RETRY_SECONDS", "2"))))
        except Exception as e:
            logger.error(f"[METADATA] Error in load status listener: {e}")
            import traceback
            logger.error(traceback.format_exc())


def start_listener():
    """
    Entry point for the Kafka listener.
    Starts listeners for both metadata_topic and load_rows_topic.
    """
    import threading
    
    logger.info("[METADATA] Starting metadata listeners...")
    listener = MetadataListener()
    
    # Start both listeners in separate threads
    metadata_thread = threading.Thread(target=listener.listen_metadata, daemon=True)
    load_status_thread = threading.Thread(target=listener.listen_load_status, daemon=True)
    
    metadata_thread.start()
    load_status_thread.start()
    
    logger.info("[METADATA] Both listeners started")
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
            # Check if threads are still alive
            if not metadata_thread.is_alive() and not load_status_thread.is_alive():
                logger.warning("[METADATA] Both threads stopped, restarting...")
                metadata_thread = threading.Thread(target=listener.listen_metadata, daemon=True)
                load_status_thread = threading.Thread(target=listener.listen_load_status, daemon=True)
                metadata_thread.start()
                load_status_thread.start()
    except KeyboardInterrupt:
        logger.info("[METADATA] Shutting down...")

