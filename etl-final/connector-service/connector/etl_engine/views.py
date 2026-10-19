from django.shortcuts import render
from django.http import HttpResponse
import logging
import os
import time
import json

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .file_storage import save_uploaded_file, save_sqlite_file
from . import file_storage
from .file_validator import validate_file_type
from shared.security.upload_policy import validate_upload, UploadRejected
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
from shared.security.internal_auth import ETLInternalAuthentication, require_etl_scope
from shared.security.destination_policy import DestinationPolicyError
from shared.connectors import ConnectorError, connector_registry, safe_connector_error


logger = logging.getLogger(__name__)
_schema_contract_store = None


def _connector_response_error(exc):
    safe = safe_connector_error(exc)
    return Response(
        {"success": False, "error": safe.as_dict(), "message": safe.message},
        status=safe.status_code,
    )


def _request_configuration(request):
    value = request.data.get("configuration", {})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ConnectorError("INVALID_CONFIGURATION", "configuration must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise ConnectorError("INVALID_CONFIGURATION", "configuration must be an object.")
    return dict(value)


class DatabaseCapabilitiesView(APIView):
    authentication_classes = [ETLInternalAuthentication]

    def get(self, request):
        return Response({"success": True, "data": connector_registry.capabilities()})


class DatabaseConnectionTestView(APIView):
    authentication_classes = [ETLInternalAuthentication]

    def post(self, request):
        scope = require_etl_scope(request)
        try:
            connector = connector_registry.get(request.data.get("engine") or request.data.get("db_type"))
            configuration = _request_configuration(request)
            configuration["workspace_id"] = scope.workspace_id
            return Response({"success": True, "data": connector.test_connection(configuration)})
        except Exception as exc:
            return _connector_response_error(exc)


class DatabaseDiscoveryView(APIView):
    authentication_classes = [ETLInternalAuthentication]

    def post(self, request):
        scope = require_etl_scope(request)
        try:
            connector = connector_registry.get(request.data.get("engine") or request.data.get("db_type"))
            configuration = _request_configuration(request)
            configuration["workspace_id"] = scope.workspace_id
            data = connector.discover(
                configuration,
                schema=request.data.get("schema"),
                table=request.data.get("table"),
            )
            return Response({"success": True, "data": data})
        except Exception as exc:
            return _connector_response_error(exc)


class SQLitePrepareView(APIView):
    authentication_classes = [ETLInternalAuthentication]

    def post(self, request):
        scope = require_etl_scope(request)
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _connector_response_error(ConnectorError("INVALID_CONFIGURATION", "A SQLite file is required."))
        token = None
        prepared = False
        try:
            validate_upload(uploaded, 'sqlite')
            token = save_sqlite_file(uploaded, scope.workspace_id)
            configuration = {"sqlite_token": token, "workspace_id": scope.workspace_id}
            connector = connector_registry.get("sqlite")
            test = connector.test_connection(configuration)
            discovery = connector.discover(configuration)
            prepared = True
            return Response({"success": True, "data": {"sqlite_token": token, "test": test, **discovery}})
        except (UploadRejected, ValueError) as exc:
            return _connector_response_error(ConnectorError("INVALID_UPLOAD", str(exc)))
        except ConnectorError as exc:
            if token and exc.code == 'CONNECTION_FAILED':
                return _connector_response_error(ConnectorError('INVALID_UPLOAD', 'SQLite database could not be read.'))
            return _connector_response_error(exc)
        except Exception as exc:
            return _connector_response_error(exc)
        finally:
            # A file that failed test/discovery must not remain available as a
            # prepared token. Successful files are retained for snapshot work.
            if token and not prepared:
                try:
                    os.unlink(os.path.join(file_storage.BASE_DIR, token))
                except FileNotFoundError:
                    pass


class DatabaseSnapshotView(APIView):
    authentication_classes = [ETLInternalAuthentication]

    def post(self, request):
        scope = require_etl_scope(request)
        try:
            connector = connector_registry.get(request.data.get("engine") or request.data.get("db_type"))
            configuration = _request_configuration(request)
            configuration["workspace_id"] = scope.workspace_id
            validated = connector.validate_configuration(configuration)
            selected_tables = request.data.get("tables")
            if not isinstance(selected_tables, list) or not selected_tables or len(selected_tables) > 20:
                raise ConnectorError("INVALID_CONFIGURATION", "Select between 1 and 20 tables.")
            normalized_tables = []
            available = {
                (str(item.get("schema") or ""), str(item.get("name"))): item
                for item in connector.discover(configuration).get("tables", [])
            }
            for item in selected_tables:
                if not isinstance(item, dict):
                    raise ConnectorError("INVALID_CONFIGURATION", "Each selected table must be an object.")
                key = (str(item.get("schema") or ""), str(item.get("name") or ""))
                if key not in available:
                    raise ConnectorError("TABLE_NOT_FOUND", "A selected table is not available.", status_code=404)
                normalized_tables.append({"schema": key[0] or None, "name": key[1]})

            if connector.key == "sqlite":
                try:
                    file_storage.refresh_queued_sqlite_file(
                        validated["sqlite_token"], scope.workspace_id,
                    )
                except ValueError as exc:
                    raise ConnectorError("TOKEN_EXPIRED", str(exc), status_code=410) from exc

            event_config = {
                key: value for key, value in validated.items()
                if key not in {"resolved_host", "sqlite_path", "workspace_id"}
            }
            if "password" in event_config:
                event_config["password"] = get_encryption_instance().encrypt(str(event_config["password"]))
                event_config["_password_encrypted"] = True
            message = {
                "type": "database",
                "db_type": connector.key,
                "configuration": event_config,
                "selected_tables": normalized_tables,
                "source_id": str(scope.dataset_id),
                "schema_version": request.data.get("schema_version"),
                "chunk_size": max(100, min(int(request.data.get("chunk_size", 1000)), 10000)),
                **scope.as_message_fields(),
            }
            if connector.key == "sqlite":
                # Query ends a SQLite processing attempt within one hour; the
                # staged source remains private for 24 hours from this dispatch.
                message["snapshot_queued_at"] = time.time()
                message["snapshot_max_queue_delay_seconds"] = min(
                    max(30, int(request.data.get("max_queue_delay_seconds", 240))),
                    3600,
                )
            _attach_schema_contract_if_available(message)
            if not _send_with_retry(KafkaMessageProducer(), "connection_topic", message, "database snapshot"):
                raise ConnectorError("EXTRACTION_FAILED", "The snapshot job could not be queued.", status_code=503)
            logger.info(
                "database_snapshot_queued connector=%s workspace=%s dataset=%s job=%s tables=%s",
                connector.key, scope.workspace_id, scope.dataset_id, scope.ingestion_job_id,
                len(normalized_tables),
            )
            return Response({"success": True, "data": {"state": "processing", "tables": normalized_tables}}, status=202)
        except Exception as exc:
            return _connector_response_error(exc)


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

    authentication_classes = [ETLInternalAuthentication]

    def post(self, request):
        scope = require_etl_scope(request)
        if "file" not in request.FILES:
            return Response(make_response(False, "No file provided"), status=400)

        uploaded_file = request.FILES["file"]
        try:
            validate_upload(uploaded_file, 'dataset')
        except UploadRejected as exc:
            return Response(make_response(False, str(exc)), status=400)
        
        # Validate the active CSV/XLSX matrix and scan before storing.
        is_valid, error_message = validate_file_type(uploaded_file)
        if not is_valid:
            return Response(make_response(False, error_message), status=400)
        
        saved_path = save_uploaded_file(uploaded_file, scope.workspace_id)

        # Log metadata to SurrealDB
        try:
            surreal = SurrealClient()
            surreal.insert("upload_logs", {
                "filename": uploaded_file.name,
                "path": saved_path,
                "size": uploaded_file.size,
                **scope.as_message_fields(),
            })
        except Exception:
            if os.path.exists(saved_path):
                os.unlink(saved_path)
            raise

        # Publish to Kafka connection_topic to trigger ETL pipeline
        producer = KafkaMessageProducer()
        connection_message = {
            "type": "file",
            "filename": uploaded_file.name,
            "source_id": uploaded_file.name,
            "path": saved_path,
            "size": uploaded_file.size,
            "schema_version": request.data.get("schema_version"),
            **scope.as_message_fields(),
        }
        _attach_schema_contract_if_available(connection_message)
        if not _send_with_retry(producer, "connection_topic", connection_message, "file trigger"):
            if os.path.exists(saved_path):
                os.unlink(saved_path)
            return Response(
                make_response(False, "Failed to publish file trigger to Kafka"),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        logger.info("[CONNECTOR] Published private file upload workspace=%s", scope.workspace_id)
        
        # Emit connection metadata
        connection_metadata = MetadataSchema.create_connection_metadata(
            source_type="file",
            source_id=uploaded_file.name,
            connection_info=connection_message
        )
        connection_metadata.update(scope.as_message_fields())
        if not _send_with_retry(producer, "metadata_topic", connection_metadata, "file metadata"):
            logger.warning("[CONNECTOR] Failed to publish connection metadata for uploaded file %s", uploaded_file.name)

        return Response(make_response(True, "File uploaded successfully", {
            "state": "processing",
        }), status=200)


class ConnectDBView(APIView):
    """
    Tests DB connection and sends DB config to Kafka for detector-service.
    """

    authentication_classes = [ETLInternalAuthentication]

    def post(self, request):
        scope = require_etl_scope(request)
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
        try:
            success, message = test_db_connection(db_type, host, user, password, database, port)
        except DestinationPolicyError as exc:
            return Response(make_response(False, str(exc)), status=400)

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
            **scope.as_message_fields(),
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
        connection_metadata.update(scope.as_message_fields())
        if not _send_with_retry(producer, "metadata_topic", connection_metadata, "database metadata"):
            logger.warning("[CONNECTOR] Failed to publish connection metadata for %s://%s/%s", db_type, host, database)

        # 4) log connection metadata (without password)
        surreal = SurrealClient()
        surreal.insert("connection_logs", {
            "db_type": db_type,
            "host": host,
            "database": database,
            **scope.as_message_fields(),
        })

        return Response(make_response(True, "DB connected successfully"), status=200)


class HealthView(APIView):
    def get(self, request):
        return Response(make_response(True, "ok", {"status": "ok"}))


class MetricsView(APIView):
    def get(self, request):
        data, content_type = render_metrics()
        return HttpResponse(data, content_type=content_type)
