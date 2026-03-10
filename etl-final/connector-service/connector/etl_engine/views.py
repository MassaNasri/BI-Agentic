from django.shortcuts import render
from django.http import HttpResponse
import logging
import os
import time

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .file_storage import save_uploaded_file
from .file_validator import validate_file_type
from shared.utils.kafka_producer import KafkaMessageProducer
from shared.utils.surreal_client import SurrealClient
from shared.utils.metadata_schema import MetadataSchema
from shared.utils.credential_encryption import get_encryption_instance
from shared.utils.input_validator import (
    create_db_connection_validator,
    validate_json_payload_size,
    sanitize_string,
    ValidationError
)
from .utils import  test_db_connection
from shared.utils.response import make_response
from shared.utils.metrics import render_metrics
from shared.utils.db_type_utils import normalize_db_type
from shared.utils.schema_contract_store import build_schema_contract_store_from_env


logger = logging.getLogger(__name__)
_schema_contract_store = None


def _send_with_retry(producer: KafkaMessageProducer, topic: str, message: dict, context: str) -> bool:
    retries = max(1, int(os.getenv("CONNECTOR_KAFKA_SEND_RETRIES", "3")))
    backoff_base = float(os.getenv("CONNECTOR_KAFKA_SEND_BACKOFF_BASE", "0.2"))
    backoff_max = float(os.getenv("CONNECTOR_KAFKA_SEND_BACKOFF_MAX", "2.0"))

    for attempt in range(1, retries + 1):
        try:
            if producer.send(topic, message):
                return True
        except Exception as exc:
            logger.warning("[CONNECTOR] Kafka send raised on %s attempt %s/%s: %s", context, attempt, retries, exc)
        if attempt < retries:
            sleep_for = min(backoff_max, backoff_base * (2 ** (attempt - 1)))
            time.sleep(sleep_for)
    return False


def _get_schema_contract_store():
    global _schema_contract_store
    if _schema_contract_store is not None:
        return _schema_contract_store
    try:
        from clickhouse_driver import Client

        clickhouse_client = Client(
            host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
            port=int(os.getenv("CLICKHOUSE_PORT", "9000")),
            user=os.getenv("CLICKHOUSE_USER", "default"),
            password=os.getenv("CLICKHOUSE_PASSWORD", ""),
            database=os.getenv("CLICKHOUSE_DATABASE", "etl"),
        )
    except Exception:
        clickhouse_client = None
    _schema_contract_store = build_schema_contract_store_from_env(clickhouse_client)
    return _schema_contract_store


def _attach_schema_contract_if_available(message: dict) -> None:
    source_id = message.get("source_id")
    schema_version = message.get("schema_version")
    if not source_id or not schema_version:
        return
    try:
        contract = _get_schema_contract_store().get_contract(source_id, schema_version)
        if contract is not None:
            message["schema_contract"] = contract.to_dict()
    except Exception as exc:
        logger.warning(
            "[CONNECTOR] schema contract lookup failed for source=%s version=%s: %s",
            source_id,
            schema_version,
            exc,
        )

class UploadFileView(APIView):
    """
    Handles file uploads and stores locally, logs metadata.
    """

    def post(self, request):
        if "file" not in request.FILES:
            return Response(make_response(False, "No file provided"), status=400)

        uploaded_file = request.FILES["file"]
        
        # Validate file type (whitelist: CSV, Excel, Parquet)
        is_valid, error_message = validate_file_type(uploaded_file)
        if not is_valid:
            return Response(make_response(False, error_message), status=400)
        
        saved_path = save_uploaded_file(uploaded_file)

        # Log metadata to SurrealDB
        surreal = SurrealClient()
        surreal.insert("upload_logs", {
            "filename": uploaded_file.name,
            "path": saved_path,
            "size": uploaded_file.size
        })

        # Publish to Kafka connection_topic to trigger ETL pipeline
        producer = KafkaMessageProducer()
        connection_message = {
            "type": "file",
            "filename": uploaded_file.name,
            "source_id": uploaded_file.name,
            "path": saved_path,
            "size": uploaded_file.size,
            "schema_version": request.data.get("schema_version"),
        }
        _attach_schema_contract_if_available(connection_message)
        if not _send_with_retry(producer, "connection_topic", connection_message, "file trigger"):
            return Response(
                make_response(False, "Failed to publish file trigger to Kafka"),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        print(f"[CONNECTOR] Published file upload to connection_topic: {uploaded_file.name}")
        
        # Emit connection metadata
        connection_metadata = MetadataSchema.create_connection_metadata(
            source_type="file",
            source_id=uploaded_file.name,
            connection_info=connection_message
        )
        if not _send_with_retry(producer, "metadata_topic", connection_metadata, "file metadata"):
            logger.warning("[CONNECTOR] Failed to publish connection metadata for uploaded file %s", uploaded_file.name)

        return Response(make_response(True, "File uploaded successfully", {
            "saved_path": saved_path
        }), status=200)


class ConnectDBView(APIView):
    """
    Tests DB connection and sends DB config to Kafka for detector-service.
    """

    def post(self, request):
        # Validate payload size
        is_valid_size, size_error = validate_json_payload_size(request.data)
        if not is_valid_size:
            return Response(make_response(False, size_error), status=400)
        
        # Validate required fields and formats using input validation framework
        validator = create_db_connection_validator()
        is_valid, errors = validator.validate(request.data)
        
        if not is_valid:
            error_message = "; ".join(errors)
            return Response(make_response(False, error_message), status=400)
        
        # Sanitize inputs to prevent injection attacks
        db_type_raw = sanitize_string(request.data["db_type"])
        db_type = normalize_db_type(db_type_raw)
        if db_type is None:
            return Response(make_response(False, "Unsupported db_type"), status=400)
        host = sanitize_string(request.data["host"])
        user = sanitize_string(request.data["user"])
        password = request.data["password"]  # Don't sanitize password (may contain special chars)
        database = sanitize_string(request.data["database"])
        port = request.data["port"]

        # 1) test connection
        success, message = test_db_connection(db_type, host, user, password, database, port)

        if not success:
            return Response(make_response(False, message), status=400)

        # 2) Encrypt password before sending to Kafka
        encryption = get_encryption_instance()
        encrypted_password = encryption.encrypt(password)

        # 3) send config to Kafka connection_topic with encrypted password
        producer = KafkaMessageProducer()
        connection_message = {
            "type": "database",
            "db_type": db_type,
            "host": host,
            "user": user,
            "password": encrypted_password,
            "_password_encrypted": True,
            "database": database,
            "port": port,
            "source_id": database,
            "schema_version": request.data.get("schema_version"),
        }
        _attach_schema_contract_if_available(connection_message)
        if not _send_with_retry(producer, "connection_topic", connection_message, "database trigger"):
            return Response(
                make_response(False, "Failed to publish database trigger to Kafka"),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        print(f"[CONNECTOR] Published DB connection to connection_topic: {db_type}://{host}/{database}")
        
        # Emit connection metadata (without password)
        connection_metadata = MetadataSchema.create_connection_metadata(
            source_type="database",
            source_id=database,
            connection_info={k: v for k, v in connection_message.items() if k not in ["password", "_password_encrypted"]}
        )
        if not _send_with_retry(producer, "metadata_topic", connection_metadata, "database metadata"):
            logger.warning("[CONNECTOR] Failed to publish connection metadata for %s://%s/%s", db_type, host, database)

        # 4) log connection metadata (without password)
        surreal = SurrealClient()
        surreal.insert("connection_logs", {
            "db_type": db_type,
            "host": host,
            "database": database
        })

        return Response(make_response(True, "DB connected successfully"), status=200)


class HealthView(APIView):
    def get(self, request):
        return Response(make_response(True, "ok", {"status": "ok"}))


class MetricsView(APIView):
    def get(self, request):
        data, content_type = render_metrics()
        return HttpResponse(data, content_type=content_type)
