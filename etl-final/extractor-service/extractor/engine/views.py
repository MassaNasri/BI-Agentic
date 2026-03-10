from django.shortcuts import render
from django.http import HttpResponse
import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from shared.utils.kafka_producer import KafkaMessageProducer
from shared.utils.surreal_client import SurrealClient
from shared.utils.response import make_response
from shared.utils.metrics import render_metrics
from shared.utils.db_type_utils import normalize_db_type

from .db_connector import DBConnector
from .row_extractor import RowExtractor


class RunExtractorView(APIView):
    def _publish_batch(
        self,
        producer: KafkaMessageProducer,
        source: str,
        table: str,
        batch_id: str,
        rows: List[Dict[str, Any]],
    ) -> bool:
        payload = {
            "source": source,
            "source_id": source,
            "batch_id": batch_id,
            "table": table,
            "schema_version": "derived_unknown",
            "rows": rows,
            "row_count": len(rows),
        }
        return producer.send("extracted_rows_topic", payload)

    def post(self, request):
        cfg = request.data.get("config")
        schema = request.data.get("schema")
        batch_size = int(os.getenv("EXTRACTOR_BATCH_SIZE", "500"))
        conn = None

        try:
            if not isinstance(cfg, dict):
                return Response(make_response(False, "config is required"), status=status.HTTP_400_BAD_REQUEST)

            db_type = normalize_db_type(cfg.get("db_type"))
            if db_type is None:
                return Response(make_response(False, "Unsupported db_type"), status=status.HTTP_400_BAD_REQUEST)

            cfg = {**cfg, "db_type": db_type}
            tables = []
            if isinstance(schema, dict):
                tables = list(schema.keys())
            elif isinstance(schema, list):
                tables = [str(item) for item in schema]

            if not tables:
                return Response(
                    make_response(False, "schema (dict) or table list is required"),
                    status=status.HTTP_400_BAD_REQUEST,
                )

            conn = DBConnector().connect(cfg)
            extractor = RowExtractor()
            producer = KafkaMessageProducer()
            batch_id = str(uuid4())
            database_name = cfg.get("database", "unknown")

            current_table = None
            current_source = None
            pending_rows: List[Dict[str, Any]] = []
            published_count = 0

            for table, row in extractor.extract_rows(conn, tables):
                table_source = f"{database_name}.{table}"
                dedup_key = hashlib.sha256(str(sorted(row.items())).encode("utf-8")).hexdigest()
                row_payload = {
                    "source": table_source,
                    "source_id": table_source,
                    "batch_id": batch_id,
                    "table": table,
                    "data": row,
                    "_dedup_key": dedup_key,
                    "_extracted_at": datetime.now(timezone.utc).isoformat(),
                }

                if current_table is None:
                    current_table = table
                    current_source = table_source

                if table != current_table:
                    if pending_rows and not self._publish_batch(producer, current_source, current_table, batch_id, pending_rows):
                        return Response(
                            make_response(False, "Failed to publish extracted rows"),
                            status=status.HTTP_503_SERVICE_UNAVAILABLE,
                        )
                    published_count += len(pending_rows)
                    pending_rows = []
                    current_table = table
                    current_source = table_source

                pending_rows.append(row_payload)
                if len(pending_rows) >= batch_size:
                    if not self._publish_batch(producer, current_source, current_table, batch_id, pending_rows):
                        return Response(
                            make_response(False, "Failed to publish extracted rows"),
                            status=status.HTTP_503_SERVICE_UNAVAILABLE,
                        )
                    published_count += len(pending_rows)
                    pending_rows = []

            if pending_rows and not self._publish_batch(producer, current_source, current_table, batch_id, pending_rows):
                return Response(
                    make_response(False, "Failed to publish extracted rows"),
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            published_count += len(pending_rows)

            SurrealClient().insert("extract_logs", {
                "status": "done",
                "tables": tables,
                "batch_id": batch_id,
                "rows_published": published_count,
            })

            return Response(make_response(True, "Extraction completed", {"batch_id": batch_id, "rows_published": published_count}))
        except Exception as e:
            return Response(make_response(False, str(e)))
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


class ExtractionProgressView(APIView):
    """
    API endpoint to query extraction progress.
    
    Provides real-time progress information for ongoing and completed extractions.
    
    Requirements:
    - US-9: Observability (AC 9.1: Structured logging with correlation IDs)
    - Task 2.2.6: Enable querying of extraction progress via API
    
    Endpoints:
    - GET /progress/<extraction_id>/ - Get progress for specific extraction
    - GET /progress/active/ - List all active extractions
    """
    
    # Class-level progress tracker instance (shared across requests)
    # In production, this should be replaced with a persistent store
    _progress_tracker = None

    class _SurrealProgressPersistence:
        def __init__(self):
            self.client = SurrealClient()

        def store_extraction_progress(self, progress_data):
            self.client.insert("extraction_progress_log", progress_data)
    
    @classmethod
    def get_progress_tracker(cls):
        """Get or create the shared progress tracker instance."""
        if cls._progress_tracker is None:
            from .extraction_progress import ProgressTracker
            cls._progress_tracker = ProgressTracker(metadata_client=cls._SurrealProgressPersistence())
        return cls._progress_tracker
    
    def get(self, request, extraction_id=None):
        """
        Get extraction progress.
        
        Query Parameters:
        - extraction_id: Specific extraction ID to query
        - active: If 'true', list all active extractions
        
        Returns:
            JSON response with progress information
        """
        tracker = self.get_progress_tracker()
        
        # Check if requesting active extractions list
        if request.query_params.get('active') == 'true' or extraction_id == 'active':
            active_extractions = tracker.list_active_extractions()
            return Response(make_response(
                True,
                "Active extractions retrieved",
                data={
                    "active_extractions": [p.to_dict() for p in active_extractions],
                    "count": len(active_extractions)
                }
            ))
        
        # Get specific extraction progress
        if not extraction_id:
            return Response(make_response(
                False,
                "extraction_id is required"
            ), status=400)
        
        progress = tracker.get_progress(extraction_id)
        
        if not progress:
            return Response(make_response(
                False,
                f"Extraction not found: {extraction_id}"
            ), status=404)
        
        # Calculate additional metrics
        progress_data = progress.to_dict()
        progress_data['progress_percentage'] = progress.get_progress_percentage()
        progress_data['throughput_rows_per_sec'] = progress.get_throughput()
        progress_data['estimated_completion'] = progress.estimate_completion_time()
        
        if progress_data['estimated_completion']:
            progress_data['estimated_completion'] = progress_data['estimated_completion'].isoformat()
        
        return Response(make_response(
            True,
            "Progress retrieved",
            data=progress_data
        ))


class HealthView(APIView):
    def get(self, request):
        return Response(make_response(True, "ok", {"status": "ok"}))


class MetricsView(APIView):
    def get(self, request):
        data, content_type = render_metrics()
        return HttpResponse(data, content_type=content_type)
