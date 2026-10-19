from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.db import transaction
from django.utils import timezone
import requests
import logging
import uuid
import hashlib
from bi_platform_shared.uploads import validate_upload, UploadRejected

from .models import Database
from .serializers import (
    DatabaseSerializer,
    DatabaseUploadResponseSerializer,
    DatabasePreviewSerializer
)
from .utils import ClickHouseClient, cleanup_database, format_file_size
from .internal_authentication import IngestionServiceAuthentication
from query_api.services.workspace_db_resolver import (
    WorkspaceDatasetBindingError,
    resolve_workspace_dataset_binding,
)

logger = logging.getLogger(__name__)


def _require_manager_scope(request):
    if _principal_attr(request.user, "role").lower() != "manager":
        return None, Response(
            {"success": False, "error": {"code": "PERMISSION_DENIED", "message": "Only managers can manage data sources."}},
            status=status.HTTP_403_FORBIDDEN,
        )
    workspace_id = _principal_workspace_id(request)
    if workspace_id is None:
        return None, Response(
            {"success": False, "error": {"code": "WORKSPACE_REQUIRED", "message": "A workspace-scoped token is required."}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return workspace_id, None


def _etl_headers(workspace_id, dataset_id, job_id):
    return {
        "X-Internal-Service": "query-service",
        "X-Internal-API-Key": str(getattr(settings, "ETL_INTERNAL_API_KEY", "")),
        "X-Workspace-ID": str(workspace_id),
        "X-Dataset-ID": str(dataset_id),
        "X-Ingestion-Job-ID": str(job_id),
    }


def _etl_json_response(response):
    try:
        payload = response.json()
    except ValueError:
        payload = {
            "success": False,
            "error": {"code": "ETL_INVALID_RESPONSE", "message": "The ETL service returned an invalid response."},
        }
    return Response(payload, status=response.status_code)


def _probe_scope(workspace_id):
    job_id = uuid.uuid4()
    return f"probe-{job_id.hex}", job_id


def _loader_table_name(value):
    table_name = str(value).replace(".", "_").replace("/", "_").replace("-", "_")
    table_name = "".join(char if char.isalnum() or char == "_" else "_" for char in table_name)
    if table_name and not table_name[0].isalpha():
        table_name = f"t_{table_name}"
    return table_name or "unknown_table"


def _snapshot_source_name(workspace_id, dataset_id, configuration, table):
    database_name = configuration.get("database") or configuration.get("service_name") or "sqlite"
    parts = [f"w{workspace_id}", f"d{dataset_id}", str(database_name)]
    if table.get("schema"):
        parts.append(str(table["schema"]))
    parts.append(str(table["name"]))
    return "_".join(parts)


def _imported_table_id(schema, name):
    """Return a stable opaque selector without accepting physical table names."""
    identity = f"{schema or ''}\0{name}".encode("utf-8")
    return hashlib.sha256(identity).hexdigest()[:20]


def _build_imported_tables(workspace_id, dataset_id, configuration, tables):
    imported = []
    seen = set()
    for table in tables:
        if not isinstance(table, dict) or not str(table.get("name") or "").strip():
            raise ValueError("Every selected table must include a name.")
        schema = str(table.get("schema") or "").strip() or None
        name = str(table["name"]).strip()
        identity = (schema or "", name)
        if identity in seen:
            raise ValueError("Duplicate table selections are not allowed.")
        seen.add(identity)
        source = _snapshot_source_name(workspace_id, dataset_id, configuration, {"schema": schema, "name": name})
        imported.append({
            "id": _imported_table_id(schema, name),
            "schema": schema,
            "name": name,
            "destination_table": _loader_table_name(source),
            "status": "processing",
            "row_count": None,
            "column_count": None,
        })
    return imported


def _dataset_imported_tables(database):
    """Normalize new table-aware metadata and retain legacy single-table support."""
    result = []
    source_tables = getattr(database, "source_tables", None)
    if not isinstance(source_tables, (list, tuple)):
        source_tables = []
    for index, table in enumerate(source_tables):
        if not isinstance(table, dict) or not table.get("name"):
            continue
        schema = str(table.get("schema") or "").strip() or None
        name = str(table["name"]).strip()
        destination = str(table.get("destination_table") or "").strip()
        if not destination and index == 0:
            destination = str(getattr(database, "clickhouse_table_name", "") or "").strip()
        result.append({
            **table,
            "id": str(table.get("id") or _imported_table_id(schema, name)),
            "schema": schema,
            "name": name,
            "destination_table": destination,
        })
    if result:
        return result
    legacy_destination = str(getattr(database, "clickhouse_table_name", "") or "").strip()
    if not legacy_destination:
        return []
    return [{
        "id": "default",
        "schema": None,
        "name": str(getattr(database, "filename", "") or "dataset"),
        "destination_table": legacy_destination,
        "status": getattr(database, "etl_status", "completed"),
        "row_count": getattr(database, "row_count", 0),
        "column_count": getattr(database, "column_count", 0),
    }]


def _resolve_imported_table(database, table_id=None):
    imported = _dataset_imported_tables(database)
    if not imported:
        raise ValueError("This dataset has no imported tables.")
    requested = str(table_id or "").strip()
    if not requested:
        return imported[0]
    for table in imported:
        if table["id"] == requested:
            return table
    raise KeyError("The requested imported table is not part of this dataset.")


def _wait_for_initial_rows(database, row_count, now=None):
    """Avoid publishing completion while the loader's first atomic batch is in flight.

    File uploads already use non-zero file size as the signal. Database
    snapshots have no local file size, so they get a bounded grace period; a
    genuinely empty source table is allowed to complete after that window.
    """
    if int(row_count or 0) != 0:
        return False
    if int(database.file_size or 0) > 0:
        return True
    if str(getattr(database, "source_kind", "") or "").lower() != "database":
        return False
    grace_seconds = max(1, int(getattr(settings, "DATABASE_EMPTY_SNAPSHOT_GRACE_SECONDS", 60)))
    observed_at = now or timezone.now()
    age_seconds = max(0.0, (observed_at - database.upload_date).total_seconds())
    return age_seconds < grace_seconds


def _mark_ingestion_failed(database, message):
    """Persist a terminal upload failure without masking the original error."""
    if database is None:
        return
    try:
        database.etl_status = 'failed'
        database.etl_message = str(message)[:2000]
        database.save(update_fields=['etl_status', 'etl_message'])
    except Exception:
        logger.exception("Failed to persist terminal ingestion state for database=%s", getattr(database, 'pk', None))


def _mark_processing_timeout(database, detail, now=None):
    """Bound the processing state when no terminal ETL event is observable."""
    timeout_seconds = max(30, int(getattr(settings, 'ETL_PROCESSING_TIMEOUT_SECONDS', 240)))
    if getattr(database, 'source_engine', '') == 'sqlite':
        # A queued SQLite snapshot is only a valid processing job inside this
        # window. Its private source is retained for 24 hours from dispatch.
        timeout_seconds = min(timeout_seconds, 3600)
    observed_at = now or timezone.now()
    upload_date = getattr(database, 'upload_date', None)
    if not isinstance(upload_date, observed_at.__class__):
        return False
    age_seconds = max(0.0, (observed_at - upload_date).total_seconds())
    if age_seconds < timeout_seconds:
        return False
    database.etl_status = 'failed'
    database.etl_message = (
        f"ETL did not produce a loadable dataset within {timeout_seconds} seconds. {detail}"
    )[:2000]
    database.save(update_fields=['etl_status', 'etl_message'])
    logger.error(
        "ingestion_timed_out dataset=%s workspace=%s job=%s age_seconds=%s detail=%s",
        database.pk,
        database.workspace_id,
        database.ingestion_job_id,
        int(age_seconds),
        detail,
    )
    return True


class DatabaseSourceCapabilitiesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        workspace_id, error = _require_manager_scope(request)
        if error:
            return error
        try:
            response = requests.get(
                f"{settings.ETL_SERVICE_URL.rstrip('/')}/api/databases/capabilities/",
                headers={
                    "X-Internal-Service": "query-service",
                    "X-Internal-API-Key": str(settings.ETL_INTERNAL_API_KEY),
                },
                timeout=10,
            )
            return _etl_json_response(response)
        except requests.RequestException:
            return Response(
                {"success": False, "error": {"code": "ETL_UNAVAILABLE", "message": "The data-source service is unavailable."}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class DatabaseSourceTestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        workspace_id, error = _require_manager_scope(request)
        if error:
            return error
        dataset_id, job_id = _probe_scope(workspace_id)
        try:
            response = requests.post(
                f"{settings.ETL_SERVICE_URL.rstrip('/')}/api/databases/test/",
                json={"engine": request.data.get("engine"), "configuration": request.data.get("configuration", {})},
                headers=_etl_headers(workspace_id, dataset_id, job_id),
                timeout=130,
            )
            return _etl_json_response(response)
        except requests.Timeout:
            return Response({"success": False, "error": {"code": "CONNECTION_TIMEOUT", "message": "The connection test timed out."}}, status=504)
        except requests.RequestException:
            return Response({"success": False, "error": {"code": "ETL_UNAVAILABLE", "message": "The data-source service is unavailable."}}, status=503)


class DatabaseSourceDiscoveryView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        workspace_id, error = _require_manager_scope(request)
        if error:
            return error
        dataset_id, job_id = _probe_scope(workspace_id)
        try:
            response = requests.post(
                f"{settings.ETL_SERVICE_URL.rstrip('/')}/api/databases/discover/",
                json={
                    "engine": request.data.get("engine"),
                    "configuration": request.data.get("configuration", {}),
                    "schema": request.data.get("schema"),
                    "table": request.data.get("table"),
                },
                headers=_etl_headers(workspace_id, dataset_id, job_id),
                timeout=130,
            )
            return _etl_json_response(response)
        except requests.Timeout:
            return Response({"success": False, "error": {"code": "CONNECTION_TIMEOUT", "message": "Metadata discovery timed out."}}, status=504)
        except requests.RequestException:
            return Response({"success": False, "error": {"code": "ETL_UNAVAILABLE", "message": "The data-source service is unavailable."}}, status=503)


class SQLiteSourcePrepareView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        workspace_id, error = _require_manager_scope(request)
        if error:
            return error
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return Response({"success": False, "error": {"code": "INVALID_CONFIGURATION", "message": "A SQLite file is required."}}, status=400)
        try:
            validate_upload(uploaded, 'sqlite')
        except UploadRejected as exc:
            return Response({"success": False, "error": {"code": "INVALID_UPLOAD", "message": str(exc)}}, status=400)
        dataset_id, job_id = _probe_scope(workspace_id)
        try:
            response = requests.post(
                f"{settings.ETL_SERVICE_URL.rstrip('/')}/api/databases/sqlite/prepare/",
                files={"file": (uploaded.name, uploaded.file, uploaded.content_type or "application/octet-stream")},
                headers=_etl_headers(workspace_id, dataset_id, job_id),
                timeout=130,
            )
            return _etl_json_response(response)
        except requests.RequestException:
            return Response({"success": False, "error": {"code": "ETL_UNAVAILABLE", "message": "The SQLite upload service is unavailable."}}, status=503)


class DatabaseSnapshotStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        workspace_id, error = _require_manager_scope(request)
        if error:
            return error
        manager_id = _principal_user_id(request.user)
        if manager_id is None:
            return Response({"success": False, "error": {"code": "INVALID_PRINCIPAL", "message": "The user identifier is missing."}}, status=401)
        engine = str(request.data.get("engine") or "").strip().lower()
        configuration = request.data.get("configuration", {})
        tables = request.data.get("tables", [])
        if not isinstance(configuration, dict) or not isinstance(tables, list) or not tables:
            return Response({"success": False, "error": {"code": "INVALID_CONFIGURATION", "message": "Configuration and at least one table are required."}}, status=400)
        if len(tables) > 20:
            return Response({"success": False, "error": {"code": "INVALID_CONFIGURATION", "message": "Select no more than 20 tables."}}, status=400)
        first_table = tables[0] if isinstance(tables[0], dict) else {}
        if not first_table.get("name"):
            return Response({"success": False, "error": {"code": "INVALID_CONFIGURATION", "message": "A valid table selection is required."}}, status=400)

        job_id = uuid.uuid4()
        manager_database = Database.objects.filter(manager=manager_id).first()
        if manager_database and manager_database.workspace_id != workspace_id:
            return Response(
                {"success": False, "error": {
                    "code": "WORKSPACE_CONFLICT",
                    "message": "The existing data source belongs to a different workspace.",
                }},
                status=status.HTTP_409_CONFLICT,
            )
        existing = manager_database
        if existing:
            cleanup_database(existing)
            existing.delete()
        database = Database.objects.create(
            manager=manager_id,
            manager_email=_principal_attr(request.user, "email"),
            manager_name=_principal_attr(request.user, "name"),
            workspace_id=workspace_id,
            ingestion_job_id=job_id,
            filename=f"{engine}:{first_table.get('schema') + '.' if first_table.get('schema') else ''}{first_table['name']}",
            file_size=0,
            file_path="",
            source_kind="database",
            source_engine=engine,
            source_tables=tables,
            clickhouse_database=getattr(settings, "CLICKHOUSE_DATABASE", "etl"),
            etl_status="pending",
        )
        try:
            imported_tables = _build_imported_tables(workspace_id, database.pk, configuration, tables)
        except ValueError as exc:
            database.delete()
            return Response(
                {"success": False, "error": {"code": "INVALID_CONFIGURATION", "message": str(exc)}},
                status=400,
            )
        database.source_tables = imported_tables
        database.clickhouse_table_name = imported_tables[0]["destination_table"]
        database.save(update_fields=["source_tables", "clickhouse_table_name"])
        try:
            snapshot_request = {
                "engine": engine,
                "configuration": configuration,
                "tables": tables,
                "chunk_size": request.data.get("chunk_size", 1000),
            }
            if engine == "sqlite":
                snapshot_request["max_queue_delay_seconds"] = min(
                    max(30, int(getattr(settings, "ETL_PROCESSING_TIMEOUT_SECONDS", 240))),
                    3600,
                )
            response = requests.post(
                f"{settings.ETL_SERVICE_URL.rstrip('/')}/api/databases/snapshot/",
                json=snapshot_request,
                headers=_etl_headers(workspace_id, database.pk, job_id),
                timeout=130,
            )
            if response.status_code not in (200, 202):
                database.etl_status = "failed"
                try:
                    database.etl_message = response.json().get("error", {}).get("message", "Snapshot could not be started.")
                except ValueError:
                    database.etl_message = "Snapshot could not be started."
                database.save(update_fields=["etl_status", "etl_message"])
                return _etl_json_response(response)
            database.etl_status = "processing"
            database.etl_message = "Database snapshot extraction started."
            database.save(update_fields=["etl_status", "etl_message"])
            return Response({
                "success": True,
                "message": "Database snapshot started.",
                "data": {**DatabaseSerializer(database).data, "file_size_formatted": format_file_size(0)},
            }, status=202)
        except requests.RequestException:
            database.etl_status = "failed"
            database.etl_message = "The ETL service is unavailable."
            database.save(update_fields=["etl_status", "etl_message"])
            return Response({"success": False, "error": {"code": "ETL_UNAVAILABLE", "message": database.etl_message}}, status=503)


def _principal_attr(user, *names: str) -> str:
    for name in names:
        value = getattr(user, name, None)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _principal_user_id(user) -> int | None:
    raw_value = _principal_attr(user, "id", "pk")
    if not raw_value:
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _principal_workspace_id(request) -> int | None:
    candidate = _principal_attr(request.user, "workspace_id")
    if candidate in (None, "", b""):
        return None
    try:
        return int(candidate)
    except (TypeError, ValueError):
        return None


class DatabaseHealthCheckView(APIView):
    """
    Health check endpoint to verify database module is loaded.
    GET: Returns system status
    """
    permission_classes = []  # Public endpoint
    
    def get(self, request):
        """Health check."""
        etl_url = getattr(settings, 'ETL_SERVICE_URL', 'http://127.0.0.1:8001')
        
        # Check ETL service
        etl_status = 'unknown'
        try:
            etl_response = requests.get(f'{etl_url}/api/upload/', timeout=2)
            etl_status = 'reachable'
        except requests.exceptions.RequestException:
            etl_status = 'unreachable'
        
        return Response({
            'success': True,
            'service': 'database',
            'status': 'healthy',
            'etl_service': etl_status,
            'etl_url': etl_url
        }, status=status.HTTP_200_OK)


class DatabaseUploadView(APIView):
    """
    Handle database file upload for managers.
    POST: Upload a new database file
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        """Upload database file with defensive error handling."""
        user_role = _principal_attr(request.user, "role").lower()
        user_email = _principal_attr(request.user, "email")
        user_name = _principal_attr(request.user, "name")
        manager_id = _principal_user_id(request.user)
        workspace_id = _principal_workspace_id(request)
        ingestion_job_id = uuid.uuid4()
        database = None

        # ============================================================
        # 1. VALIDATION: Check user role
        # ============================================================
        if user_role != 'manager':
            logger.warning("Non-manager user %s attempted database upload", user_email or "unknown")
            return Response(
                {'success': False, 'message': 'Only managers can upload databases'},
                status=status.HTTP_403_FORBIDDEN
            )
        if manager_id is None:
            return Response(
                {'success': False, 'message': 'Invalid authenticated principal: missing user id.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if workspace_id is None:
            return Response(
                {'success': False, 'message': 'workspace_id is required to bind uploaded database.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # ============================================================
        # 2. VALIDATION: Check file presence
        # ============================================================
        if 'file' not in request.FILES:
            logger.error("Upload attempt without file")
            return Response(
                {'success': False, 'message': 'No file provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        uploaded_file = request.FILES['file']
        try:
            validate_upload(uploaded_file, 'dataset')
        except UploadRejected as exc:
            return Response({'success': False, 'message': str(exc)}, status=400)
        logger.info("Upload started: %s (%s bytes) by manager=%s", uploaded_file.name, uploaded_file.size, manager_id)
        
        # ============================================================
        # 3. CHECK: Existing database (replace mode)
        # ============================================================
        manager_database = Database.objects.filter(manager=manager_id).first()
        if manager_database and manager_database.workspace_id != workspace_id:
            return Response(
                {'success': False, 'message': 'The existing data source belongs to a different workspace.'},
                status=status.HTTP_409_CONFLICT,
            )
        existing_db = manager_database
        replace_mode = existing_db is not None
        
        if replace_mode:
            logger.info(f"Replace mode: Existing database {existing_db.id} will be replaced")
        
        # ============================================================
        # 4. ETL INTEGRATION: Forward file with defensive handling
        # ============================================================
        etl_url = getattr(settings, 'ETL_SERVICE_URL', 'http://127.0.0.1:8001')
        etl_upload_endpoint = f'{etl_url}/api/upload/'
        
        try:
            configured_clickhouse_database = getattr(settings, 'CLICKHOUSE_DATABASE', 'etl')
            if replace_mode:
                logger.info("Cleaning up previous physical dataset for database %s", existing_db.id)
                cleanup_database(existing_db)
                database = existing_db
                database.ingestion_job_id = ingestion_job_id
                database.filename = uploaded_file.name
                database.file_size = uploaded_file.size
                database.file_path = ''
                database.source_kind = 'file'
                database.source_engine = ''
                database.source_tables = []
                database.row_count = 0
                database.column_count = 0
                database.columns_schema = {}
                database.clickhouse_table_name = ''
                database.clickhouse_database = configured_clickhouse_database
                database.upload_date = timezone.now()
                database.etl_status = 'pending'
                database.etl_message = 'Upload accepted; waiting for ETL dispatch.'
                database.save()
            else:
                database = Database.objects.create(
                    manager=manager_id,
                    manager_email=user_email,
                    manager_name=user_name,
                    workspace_id=workspace_id,
                    ingestion_job_id=ingestion_job_id,
                    filename=uploaded_file.name,
                    file_size=uploaded_file.size,
                    file_path='',
                    clickhouse_database=configured_clickhouse_database,
                    etl_status='pending',
                    etl_message='Upload accepted; waiting for ETL dispatch.',
                )

            # Prepare multipart form data
            files = {
                'file': (
                    uploaded_file.name,
                    uploaded_file.file,
                    uploaded_file.content_type or 'application/octet-stream'
                )
            }
            
            logger.info(f"Forwarding to ETL: {etl_upload_endpoint}")
            
            # Make request with timeout
            etl_response = requests.post(
                etl_upload_endpoint,
                files=files,
                data={
                    'workspace_id': str(workspace_id),
                    'dataset_id': str(database.pk),
                    'ingestion_job_id': str(ingestion_job_id),
                },
                headers={
                    'X-Internal-Service': 'query-service',
                    'X-Internal-API-Key': str(getattr(settings, 'ETL_INTERNAL_API_KEY', '')),
                    'X-Workspace-ID': str(workspace_id),
                    'X-Dataset-ID': str(database.pk),
                    'X-Ingestion-Job-ID': str(ingestion_job_id),
                },
                timeout=30
            )
            
            logger.info(f"ETL Response: Status={etl_response.status_code}, Content-Type={etl_response.headers.get('Content-Type')}")
            
            # ========================================================
            # 5. ETL RESPONSE HANDLING: Defensive JSON parsing
            # ========================================================
            
            # Check if ETL request was successful
            if etl_response.status_code != 200:
                error_msg = f"ETL service returned {etl_response.status_code}"
                
                # Try to extract error message from response
                try:
                    content_type = etl_response.headers.get('Content-Type', '')
                    
                    if 'application/json' in content_type:
                        error_data = etl_response.json()
                        error_msg = error_data.get('message', error_msg)
                    else:
                        # Non-JSON response, log it
                        response_text = etl_response.text[:200]  # First 200 chars
                        logger.error(f"ETL non-JSON error response: {response_text}")
                        error_msg = f"ETL service error (Status: {etl_response.status_code})"
                
                except Exception as parse_error:
                    logger.error(f"Failed to parse ETL error response: {parse_error}")

                _mark_ingestion_failed(database, error_msg)
                
                return Response(
                    {'success': False, 'message': error_msg},
                    status=status.HTTP_502_BAD_GATEWAY
                )
            
            # The record is created before dispatch so every asynchronous event
            # carries the real query-service dataset id and can update status.
            # Connector staging paths belong to ETL and are never returned or
            # persisted in Query's client-facing source metadata.
            database.file_path = ''
            database.etl_status = 'processing'
            database.etl_message = 'ETL processing started.'
            database.save(update_fields=['file_path', 'etl_status', 'etl_message'])
            logger.info("Database ingestion dispatched: ID=%s Status=%s", database.id, database.etl_status)
            
            # ========================================================
            # 7. SUCCESS RESPONSE
            # ========================================================
            
            response_data = {
                'success': True,
                'message': 'Database replaced successfully and ETL processing started' if replace_mode else 'Database uploaded successfully and ETL processing started',
                'data': {
                    'id': database.id,
                    'filename': database.filename,
                    'file_size': database.file_size,
                    'file_size_formatted': format_file_size(database.file_size),
                    'upload_date': database.upload_date.isoformat(),
                    'etl_status': database.etl_status,
                    'ingestion_job_id': str(database.ingestion_job_id),
                    'replaced': replace_mode
                }
            }
            
            logger.info(f"Upload successful: Database ID={database.id}")
            return Response(response_data, status=status.HTTP_201_CREATED)
        
        # ============================================================
        # 8. ERROR HANDLING: Network and unexpected errors
        # ============================================================
        
        except requests.exceptions.Timeout:
            logger.error(f"ETL service timeout after 30s: {etl_upload_endpoint}")
            _mark_ingestion_failed(database, 'ETL dispatch timed out before processing could be confirmed.')
            return Response(
                {
                    'success': False,
                    'message': 'ETL service timeout. The file upload took too long. Please try again or use a smaller file.'
                },
                status=status.HTTP_504_GATEWAY_TIMEOUT
            )
        
        except requests.exceptions.ConnectionError as e:
            logger.error(f"ETL service connection error: {e}")
            _mark_ingestion_failed(database, 'ETL service was unavailable during upload dispatch.')
            return Response(
                {
                    'success': False,
                    'message': 'ETL service is unavailable. Please ensure the ETL system is running and try again.'
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        except requests.exceptions.RequestException as e:
            logger.error(f"ETL service request error: {e}")
            _mark_ingestion_failed(database, 'ETL dispatch failed due to a service communication error.')
            return Response(
                {
                    'success': False,
                    'message': f'ETL service error: {str(e)}'
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        except Exception as e:
            logger.error(f"Unexpected error during upload: {e}", exc_info=True)
            _mark_ingestion_failed(database, 'Upload failed before ETL processing could complete.')
            return Response(
                {
                    'success': False,
                    'message': f'Upload failed: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DatabaseDetailView(APIView):
    """
    Handle database operations for the authenticated manager.
    GET: Retrieve manager's database information (with smart status checking)
    DELETE: Delete manager's database
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Resolve database information for the authenticated workspace.

        The JWT workspace claim is authoritative. Optional dataset_id and
        table_name parameters narrow the binding but can never cross workspaces.
        """
        user_role = _principal_attr(request.user, "role").lower()
        workspace_id = _principal_workspace_id(request)
        if user_role not in {'manager', 'analyst', 'executive'}:
            return Response(
                {'success': False, 'message': 'This role cannot access analytical datasets'},
                status=status.HTTP_403_FORBIDDEN
            )
        if workspace_id is None:
            return Response(
                {'success': False, 'message': 'Invalid authenticated principal: missing workspace id.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        requested_workspace_id = request.query_params.get("workspace_id")
        if requested_workspace_id not in (None, ""):
            try:
                requested_workspace_id = int(requested_workspace_id)
            except (TypeError, ValueError):
                return Response(
                    {
                        'success': False,
                        'code': 'workspace_id_invalid',
                        'category': 'data_source',
                        'message': 'workspace_id must be a positive integer.',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if requested_workspace_id != workspace_id:
                return Response(
                    {
                        'success': False,
                        'code': 'dataset_workspace_mismatch',
                        'category': 'data_source',
                        'message': 'Requested workspace does not match the authenticated workspace.',
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        try:
            status_database = (
                Database.objects.filter(workspace_id=workspace_id)
                .order_by("-upload_date")
                .first()
            )
            requested_dataset_id = request.query_params.get("dataset_id")
            candidate_matches_request = (
                status_database is not None
                and requested_dataset_id in (None, "", str(status_database.pk), status_database.pk)
            )

            # Status polling is metadata access, not analytical data access.
            # During processing (and after a terminal failure) the ClickHouse
            # table may legitimately not exist, so physical binding validation
            # must only run once the dataset is completed.
            if candidate_matches_request and status_database.etl_status == "processing":
                logger.info("Database %s is processing - checking ClickHouse", status_database.id)
                self._check_and_update_etl_status(status_database)
                status_database.refresh_from_db()

            if candidate_matches_request and status_database.etl_status != "completed":
                database = status_database
            else:
                binding = resolve_workspace_dataset_binding(
                    workspace_id,
                    dataset_id=requested_dataset_id,
                    table_name=request.query_params.get("table_name"),
                    verify_physical=True,
                )
                database = Database.objects.get(pk=binding.dataset_id)
            
            # ============================================================
            # Return current database information
            # ============================================================
            serializer = DatabaseSerializer(database)
            
            return Response({
                'success': True,
                'data': {
                    **serializer.data,
                    'file_size_formatted': format_file_size(database.file_size)
                }
            }, status=status.HTTP_200_OK)
            
        except WorkspaceDatasetBindingError as exc:
            return Response(
                {
                    'success': False,
                    'code': exc.code,
                    'category': 'data_source',
                    'message': str(exc),
                    'details': exc.details,
                },
                status=exc.http_status,
            )
        except Exception as e:
            logger.error(f"Error retrieving database: {str(e)}")
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _check_and_update_etl_status(self, database):
        """
        Check ClickHouse for table existence and data.
        Update database status, row count, and column count if ready.
        
        Returns:
            bool: True if status was updated, False otherwise
        """
        try:
            clickhouse = ClickHouseClient()
            configured_ch_database = getattr(settings, 'CLICKHOUSE_DATABASE', 'etl')
            ch_database = (database.clickhouse_database or configured_ch_database).strip()
            if ch_database == 'default' and configured_ch_database and configured_ch_database != 'default':
                logger.info(
                    "Database %s had ClickHouse database='default'. Switching to configured database '%s'.",
                    database.id,
                    configured_ch_database,
                )
                ch_database = configured_ch_database
                database.clickhouse_database = configured_ch_database
                database.save(update_fields=['clickhouse_database'])
            
            # ========================================================
            # Step 1: Find the table name
            # ========================================================
            table_name = database.clickhouse_table_name
            
            if not table_name:
                # Try to find table by searching for tables containing filename
                logger.info("No table name set - searching ClickHouse for matching table")
                
                # Get all tables
                tables_result = clickhouse.get_all_tables(ch_database)
                
                if tables_result['success']:
                    if not tables_result['tables']:
                        logger.info(
                            "No tables found in ClickHouse database '%s' yet for database %s.",
                            ch_database,
                            database.id,
                        )
                        database.etl_message = (
                            f"Waiting for ETL output in ClickHouse database '{ch_database}'."
                        )
                        database.save(update_fields=['etl_message'])
                        return _mark_processing_timeout(database, 'No ClickHouse output table was created.')

                    # Try to match by filename
                    import re
                    base_name = database.filename.rsplit('.', 1)[0].lower()
                    clean_base = re.sub(r'[^a-z0-9]', '', base_name)
                    
                    logger.info(f"Searching for tables matching: {clean_base}")
                    
                    # Look for tables that might match
                    for table in tables_result['tables']:
                        clean_table = re.sub(r'[^a-z0-9]', '', table.lower())
                        if clean_base in clean_table or clean_table in clean_base:
                            logger.info(f"Found matching table: {table}")
                            table_name = table
                            database.clickhouse_table_name = table
                            database.save()
                            break
                    
                    if not table_name:
                        logger.warning(f"No matching table found for {database.filename}")
                        logger.info(f"Available tables: {tables_result['tables']}")
                        database.etl_message = (
                            f"No matching ClickHouse table found yet in '{ch_database}'."
                        )
                        database.save(update_fields=['etl_message'])
                        return _mark_processing_timeout(database, 'No ClickHouse table matched the uploaded file.')
                else:
                    error_detail = tables_result.get('error', 'unknown_error')
                    logger.warning(
                        "Could not retrieve table list from ClickHouse database='%s' error=%s",
                        ch_database,
                        error_detail,
                    )
                    database.etl_message = (
                        f"Failed to retrieve ClickHouse table list: {error_detail}"
                    )
                    database.save(update_fields=['etl_message'])
                    return _mark_processing_timeout(database, 'ClickHouse metadata could not be read.')
            
            imported_tables = _dataset_imported_tables(database)
            if not imported_tables:
                imported_tables = [{
                    "id": "default", "schema": None, "name": database.filename,
                    "destination_table": table_name,
                }]

            completed_tables = []
            for imported in imported_tables:
                destination = imported.get("destination_table")
                if not destination:
                    return _mark_processing_timeout(database, 'An imported table has no destination identity.')
                logger.info(
                    "dataset_table_status workspace=%s dataset=%s source_schema=%s source_table=%s destination=%s",
                    database.workspace_id, database.pk, imported.get("schema"), imported.get("name"), destination,
                )
                exists_result = clickhouse.table_exists(ch_database, destination)
                if not exists_result['success']:
                    logger.warning("Failed to inspect destination table %s: %s", destination, exists_result.get('error'))
                    return _mark_processing_timeout(database, 'A ClickHouse table could not be inspected.')
                if not exists_result['exists']:
                    return _mark_processing_timeout(database, 'Not all expected ClickHouse tables were created.')

                count_result = clickhouse.get_table_count(ch_database, destination)
                if not count_result['success']:
                    database.etl_status = 'failed'
                    database.etl_message = "Failed to query an imported table."
                    database.save(update_fields=['etl_status', 'etl_message'])
                    return True
                row_count = int(count_result['count'])
                if _wait_for_initial_rows(database, row_count):
                    database.etl_message = (
                        "ClickHouse table exists; waiting for loaded rows."
                        if len(imported_tables) == 1
                        else "ClickHouse tables exist; waiting for loaded rows."
                    )
                    database.save(update_fields=['etl_message'])
                    return _mark_processing_timeout(database, 'An output table remained empty.')

                schema_result = clickhouse.get_table_schema(ch_database, destination)
                if not schema_result['success']:
                    database.etl_status = 'failed'
                    database.etl_message = "Failed to retrieve an imported table schema."
                    database.save(update_fields=['etl_status', 'etl_message'])
                    return True
                schema = schema_result['schema']
                completed_tables.append({
                    **imported,
                    "status": "completed",
                    "row_count": row_count,
                    "column_count": len(schema),
                    "columns_schema": {col['name']: col['type'] for col in schema},
                })

            first_completed = completed_tables[0]
            database.source_tables = completed_tables
            database.row_count = sum(item["row_count"] for item in completed_tables)
            database.column_count = first_completed["column_count"]
            database.columns_schema = first_completed["columns_schema"]
            database.etl_status = 'completed'
            database.etl_message = (
                f"Successfully loaded {database.row_count} rows across {len(completed_tables)} table(s)"
            )
            database.save()
            
            logger.info(
                "Dataset %s marked completed: tables=%s rows=%s",
                database.id, len(completed_tables), database.row_count,
            )
            return True
            
        except Exception as e:
            logger.error(f"Error checking ETL status: {str(e)}", exc_info=True)
            # Transient errors are tolerated until the bounded processing SLA.
            return _mark_processing_timeout(database, 'Status verification repeatedly failed.')
    
    def delete(self, request):
        """Delete manager's database."""
        user_role = _principal_attr(request.user, "role").lower()
        user_email = _principal_attr(request.user, "email")
        manager_id = _principal_user_id(request.user)
        workspace_id = _principal_workspace_id(request)
        if user_role != 'manager':
            return Response(
                {'success': False, 'message': 'Only managers can delete databases'},
                status=status.HTTP_403_FORBIDDEN
            )
        if manager_id is None:
            return Response(
                {'success': False, 'message': 'Invalid authenticated principal: missing user id.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if workspace_id is None:
            return Response({'success': False, 'message': 'Workspace scope is required.'}, status=400)
        
        try:
            database = Database.objects.get(manager=manager_id, workspace_id=workspace_id)
            
            # Cleanup ClickHouse and other resources
            cleanup_results = cleanup_database(database)
            
            # Delete database record
            database.delete()
            
            logger.info("Database deleted for manager %s", user_email or manager_id)
            
            return Response({
                'success': True,
                'message': 'Database deleted successfully',
                'cleanup_results': cleanup_results
            }, status=status.HTTP_200_OK)
            
        except Database.DoesNotExist:
            return Response(
                {'success': False, 'message': 'No database found to delete'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error deleting database: {str(e)}")
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DatabasePreviewView(APIView):
    """
    Get preview data from the manager's database.
    GET: Returns first 5 rows and schema information
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get database preview."""
        user_role = _principal_attr(request.user, "role").lower()
        manager_id = _principal_user_id(request.user)
        workspace_id = _principal_workspace_id(request)
        if user_role != 'manager':
            return Response(
                {'success': False, 'message': 'Only managers can preview databases'},
                status=status.HTTP_403_FORBIDDEN
            )
        if manager_id is None:
            return Response(
                {'success': False, 'message': 'Invalid authenticated principal: missing user id.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if workspace_id is None:
            return Response({'success': False, 'message': 'Workspace scope is required.'}, status=400)
        
        try:
            database = Database.objects.get(manager=manager_id, workspace_id=workspace_id)
            
            # Check if ETL processing is complete
            if database.etl_status != 'completed':
                return Response({
                    'success': False,
                    'message': f'Database is still processing. Status: {database.etl_status}',
                    'etl_status': database.etl_status
                }, status=status.HTTP_202_ACCEPTED)
            
            try:
                selected_table = _resolve_imported_table(
                    database,
                    request.query_params.get("table") or request.query_params.get("table_id"),
                )
            except (KeyError, ValueError) as exc:
                return Response(
                    {"success": False, "error": {"code": "TABLE_NOT_FOUND", "message": str(exc)}},
                    status=status.HTTP_404_NOT_FOUND,
                )

            destination_table = selected_table["destination_table"]
            clickhouse = ClickHouseClient()
            
            # Get schema
            schema_result = clickhouse.get_table_schema(
                database.clickhouse_database,
                destination_table
            )
            
            if not schema_result['success']:
                return Response({
                    'success': False,
                    'message': 'Failed to retrieve schema from ClickHouse',
                    'error': schema_result.get('error')
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Get preview rows
            preview_result = clickhouse.get_table_preview(
                database.clickhouse_database,
                destination_table,
                limit=5
            )
            
            if not preview_result['success']:
                return Response({
                    'success': False,
                    'message': 'Failed to retrieve preview data from ClickHouse',
                    'error': preview_result.get('error')
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Format response
            columns = [col['name'] for col in schema_result['schema']]
            column_types = {col['name']: col['type'] for col in schema_result['schema']}
            count_result = clickhouse.get_table_count(database.clickhouse_database, destination_table)
            total_rows = (
                int(count_result['count'])
                if count_result.get('success')
                else int(selected_table.get('row_count') or 0)
            )
            
            response_data = {
                'success': True,
                'data': {
                    'columns': columns,
                    'column_types': column_types,
                    'rows': preview_result['rows'],
                    'total_rows': total_rows,
                    'total_columns': len(columns),
                    'table': {
                        'id': selected_table['id'],
                        'schema': selected_table.get('schema'),
                        'name': selected_table['name'],
                    },
                }
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Database.DoesNotExist:
            return Response(
                {'success': False, 'message': 'No database found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error getting database preview: {str(e)}")
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DatabaseSchemaView(APIView):
    """Return schema for one allowlisted imported table in the current workspace."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if _principal_attr(request.user, "role").lower() != "manager":
            return Response(
                {'success': False, 'message': 'Only managers can inspect database schemas'},
                status=status.HTTP_403_FORBIDDEN,
            )
        manager_id = _principal_user_id(request.user)
        workspace_id = _principal_workspace_id(request)
        if manager_id is None or workspace_id is None:
            return Response(
                {'success': False, 'message': 'A valid workspace-scoped principal is required.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            database = Database.objects.get(manager=manager_id, workspace_id=workspace_id)
            if database.etl_status != 'completed':
                return Response(
                    {'success': False, 'message': 'Database processing is not complete.', 'etl_status': database.etl_status},
                    status=status.HTTP_202_ACCEPTED,
                )
            selected_table = _resolve_imported_table(
                database,
                request.query_params.get("table") or request.query_params.get("table_id"),
            )
            clickhouse = ClickHouseClient()
            schema_result = clickhouse.get_table_schema(
                database.clickhouse_database,
                selected_table["destination_table"],
            )
            if not schema_result['success']:
                return Response(
                    {'success': False, 'message': 'Failed to retrieve schema from ClickHouse'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            columns = schema_result['schema']
            return Response({
                'success': True,
                'data': {
                    'table': {
                        'id': selected_table['id'],
                        'schema': selected_table.get('schema'),
                        'name': selected_table['name'],
                    },
                    'columns': columns,
                    'total_columns': len(columns),
                },
            })
        except Database.DoesNotExist:
            return Response({'success': False, 'message': 'No database found'}, status=status.HTTP_404_NOT_FOUND)
        except (KeyError, ValueError) as exc:
            return Response(
                {"success": False, "error": {"code": "TABLE_NOT_FOUND", "message": str(exc)}},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception:
            logger.exception("Failed to retrieve table-aware database schema")
            return Response(
                {'success': False, 'message': 'Failed to retrieve database schema.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


ALLOWED_INGESTION_TRANSITIONS = {
    'pending': {'processing', 'failed'},
    'processing': {'completed', 'failed'},
    'completed': set(),
    'failed': set(),
}


def validate_ingestion_transition(current, requested):
    current = str(current or '').strip().lower()
    requested = str(requested or '').strip().lower()
    if current == requested:
        return True, True
    return requested in ALLOWED_INGESTION_TRANSITIONS.get(current, set()), False


class IngestionDatasetStatusView(APIView):
    """Versioned ingestion-only callback bound to job, dataset, and workspace."""

    authentication_classes = [IngestionServiceAuthentication]
    permission_classes = [IsAuthenticated]
    allowed_fields = {
        'dataset_id', 'workspace_id', 'expected_state', 'etl_status',
        'row_count', 'column_count', 'columns_schema', 'etl_message',
    }

    @transaction.atomic
    def post(self, request, job_id):
        unknown = set(request.data) - self.allowed_fields
        if unknown:
            return Response(
                {'success': False, 'error': 'Unknown callback fields.', 'fields': sorted(unknown)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            dataset_id = int(request.data.get('dataset_id'))
            workspace_id = int(request.data.get('workspace_id'))
        except (TypeError, ValueError):
            return Response(
                {'success': False, 'error': 'dataset_id and workspace_id must be positive integers.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        database = (
            Database.objects.select_for_update()
            .filter(pk=dataset_id, workspace_id=workspace_id, ingestion_job_id=job_id)
            .first()
        )
        if database is None:
            return Response(
                {'success': False, 'error': 'Ingestion job, dataset, and workspace binding not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        expected = str(request.data.get('expected_state') or '').strip().lower()
        requested = str(request.data.get('etl_status') or '').strip().lower()
        legal, idempotent = validate_ingestion_transition(database.etl_status, requested)
        # A durable consumer may redeliver after the first callback committed.
        # Identical terminal callbacks are successful even if expected_state
        # still names the former state.
        if not idempotent and expected != database.etl_status:
            return Response(
                {'success': False, 'error': 'Dataset state changed; callback expectation is stale.'},
                status=status.HTTP_409_CONFLICT,
            )
        if not legal:
            return Response(
                {'success': False, 'error': 'Illegal dataset state transition.'},
                status=status.HTTP_409_CONFLICT,
            )
        if not idempotent:
            database.etl_status = requested
            update_fields = ['etl_status']
            for field in ('row_count', 'column_count', 'columns_schema', 'etl_message'):
                if field in request.data:
                    setattr(database, field, request.data[field])
                    update_fields.append(field)
            database.save(update_fields=update_fields)
        logger.info(
            'ingestion_status_updated dataset=%s workspace=%s job=%s state=%s caller=%s idempotent=%s',
            database.pk, database.workspace_id, job_id, database.etl_status,
            request.user.service, idempotent,
        )
        return Response(
            {'success': True, 'state': database.etl_status, 'idempotent': idempotent},
            status=status.HTTP_200_OK,
        )
