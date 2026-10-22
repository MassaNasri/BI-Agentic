from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings
from django.db import transaction
from bi_platform_shared.db_ownership import integration_atomic_alias
from django.utils import timezone
from bi_platform_shared.credential_crypto import CredentialCryptoError
import logging
import requests
import uuid

from .metadata import public_source, safe_connection_metadata
from .models import DataSource, SourceCandidate
from .scope import principal_user_id, require_manager_scope
from .service import create_source, owned_source, retire_source, update_source, selected_tables
from .credentials import (
    CredentialUnavailable, active_credential, activate_credential, authorize_execution,
    configure_credential, create_candidate_credential, execution_reference,
    revoke_credential,
    prune_old_credentials,
)
from .models import SourceCredential
from .limits import admit_source_operation

logger = logging.getLogger(__name__)


def _credential_error(code, status_code=400):
    return Response({"success": False, "error": {"code": code}}, status=status_code)


def _test_candidate(source, credential, *, engine=None, metadata=None, version=None):
    job_id = uuid.uuid4()
    dataset_id = f"probe-{job_id.hex}"
    grant = authorize_execution(source, job_id=job_id, dataset_id=dataset_id,
                                kind="candidate" if metadata is not None else "rotate", credential=credential,
                                engine=engine, metadata=metadata, configuration_version=version)
    response = requests.post(
        f"{settings.ETL_SERVICE_URL.rstrip('/')}/api/databases/test/",
        json={"credential_ref": execution_reference(grant)},
        headers={
            "X-Internal-Service": "query-service",
            "X-Internal-API-Key": str(settings.ETL_INTERNAL_API_KEY),
            "X-Workspace-ID": str(source.workspace_id),
            "X-Dataset-ID": dataset_id,
            "X-Ingestion-Job-ID": str(job_id),
        }, timeout=130,
    )
    return response.status_code == 200 and response.json().get("success") is True


class SourcesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        workspace_id, error = require_manager_scope(request)
        if error:
            return error
        sources = DataSource.objects.filter(workspace_id=workspace_id).order_by("-created_at", "-pk")
        return Response({"success": True, "data": [public_source(source) for source in sources]})

    def post(self, request):
        workspace_id, error = require_manager_scope(request)
        if error:
            return error
        actor_id = principal_user_id(request.user)
        if actor_id is None:
            return Response({"success": False, "error": {"code": "INVALID_PRINCIPAL"}}, status=401)
        if set(request.data) - {"name", "engine", "connection_metadata", "selected_tables", "password", "transport"}:
            return Response({"success": False, "error": {"code": "INVALID_SOURCE"}}, status=400)
        if request.data.get("transport", "direct_secure_internet") != "direct_secure_internet":
            return _credential_error("TRANSPORT_UNAVAILABLE", 400)
        try:
            with transaction.atomic(using=integration_atomic_alias()):
                source = create_source(
                    workspace_id=workspace_id, actor_id=actor_id,
                    name=request.data.get("name"), engine=request.data.get("engine"),
                    configuration=request.data.get("connection_metadata", {}),
                    tables=request.data.get("selected_tables", []),
                    strict_metadata=True,
                )
                if request.data.get("password") is not None:
                    configure_credential(source.pk, request.data["password"])
        except CredentialCryptoError:
            return _credential_error("CREDENTIAL_UNAVAILABLE", 503)
        except ValueError as exc:
            return Response({"success": False, "error": {"code": "INVALID_SOURCE", "message": str(exc)}}, status=400)
        return Response({"success": True, "data": public_source(source)}, status=status.HTTP_201_CREATED)


class SourceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _source(self, request, source_id):
        workspace_id, error = require_manager_scope(request)
        if error:
            return None, error
        source = owned_source(workspace_id, source_id)
        if source is None:
            return None, Response({"success": False, "error": {"code": "SOURCE_NOT_FOUND"}}, status=404)
        return source, None

    def get(self, request, source_id):
        source, error = self._source(request, source_id)
        if error:
            return error
        return Response({"success": True, "data": public_source(source)})

    def patch(self, request, source_id):
        source, error = self._source(request, source_id)
        if error:
            return error
        try:
            update_source(source, request.data)
        except ValueError as exc:
            return Response({"success": False, "error": {"code": "INVALID_SOURCE", "message": str(exc)}}, status=400)
        return Response({"success": True, "data": public_source(source)})

    def delete(self, request, source_id):
        source, error = self._source(request, source_id)
        if error:
            return error
        retire_source(source)
        revoke_credential(source.pk)
        logger.info("source_credential_retired workspace=%s source=%s actor=%s", source.workspace_id, source.pk, principal_user_id(request.user))
        return Response({"success": True, "data": public_source(source)})


class SourceCredentialView(SourceDetailView):
    """Initial setup, staged rotation, and revocation are separate operations."""
    http_method_names = ["post", "options"]

    def post(self, request, source_id, action):
        source, error = self._source(request, source_id)
        if error:
            return error
        if action not in {"configure", "rotate", "revoke"}:
            return _credential_error("INVALID_OPERATION")
        if action == "revoke":
            revoke_credential(source.pk)
            logger.info("source_credential_revoked workspace=%s source=%s actor=%s", source.workspace_id, source.pk, principal_user_id(request.user))
            return Response({"success": True, "data": public_source(source)})
        if set(request.data) != {"password"}:
            return _credential_error("INVALID_CREDENTIAL")
        try:
            if action == "configure":
                configure_credential(source.pk, request.data["password"])
            else:
                actor_id = principal_user_id(request.user)
                if actor_id is None or not admit_source_operation(source.workspace_id, actor_id, "rotate"):
                    return _credential_error("SOURCE_RATE_LIMITED", 429)
                previous_id = active_credential(source).pk
                candidate = create_candidate_credential(source.pk, request.data["password"])
                try:
                    passed = _test_candidate(source, candidate)
                except (requests.RequestException, ValueError):
                    passed = False
                if not passed:
                    candidate.state = SourceCredential.REVOKED
                    candidate.revoked_at = timezone.now()
                    candidate.ciphertext = ""
                    candidate.save(update_fields=["state", "revoked_at", "ciphertext"])
                    logger.info("source_credential_rotation_failed workspace=%s source=%s actor=%s", source.workspace_id, source.pk, principal_user_id(request.user))
                    return _credential_error("CREDENTIAL_VALIDATION_FAILED", 400)
                try:
                    activate_credential(source.pk, candidate.pk, expected_active_id=previous_id)
                except CredentialUnavailable:
                    candidate.state = SourceCredential.REVOKED
                    candidate.revoked_at = timezone.now()
                    candidate.ciphertext = ""
                    candidate.save(update_fields=["state", "revoked_at", "ciphertext"])
                    return _credential_error("CREDENTIAL_ROTATION_CONFLICT", 409)
        except CredentialCryptoError:
            return _credential_error("CREDENTIAL_UNAVAILABLE", 503)
        except (CredentialUnavailable, ValueError):
            return _credential_error("CREDENTIAL_NOT_AVAILABLE", 400)
        logger.info("source_credential_%s workspace=%s source=%s actor=%s", action, source.workspace_id, source.pk, principal_user_id(request.user))
        return Response({"success": True, "data": public_source(source)})


class SourceReplacementView(SourceDetailView):
    http_method_names = ["post", "options"]

    def post(self, request, source_id):
        source, error = self._source(request, source_id)
        if error:
            return error
        if source.state != DataSource.ACTIVE:
            return _credential_error("SOURCE_DISABLED")
        prune_old_credentials()
        if SourceCandidate.objects.filter(source=source).exists():
            return _credential_error("REPLACEMENT_ALREADY_STAGED", 409)
        if set(request.data) != {"engine", "connection_metadata", "selected_tables", "password"}:
            return _credential_error("INVALID_REPLACEMENT")
        actor_id = principal_user_id(request.user)
        if actor_id is None or not admit_source_operation(source.workspace_id, actor_id, "replace"):
            return _credential_error("SOURCE_RATE_LIMITED", 429)
        try:
            active_credential(source)
            engine = str(request.data["engine"] or "").strip().lower()
            if not engine or len(engine) > 32:
                raise ValueError
            metadata = safe_connection_metadata(request.data["connection_metadata"], strict=True)
            tables = selected_tables(request.data["selected_tables"])
            if not tables:
                raise ValueError
            candidate_credential = create_candidate_credential(source.pk, request.data["password"])
            try:
                passed = _test_candidate(source, candidate_credential, engine=engine,
                                         metadata=metadata, version=source.configuration_version + 1)
            except (requests.RequestException, ValueError):
                passed = False
            if not passed:
                candidate_credential.state = SourceCredential.REVOKED
                candidate_credential.revoked_at = timezone.now()
                candidate_credential.ciphertext = ""
                candidate_credential.save(update_fields=["state", "revoked_at", "ciphertext"])
                return _credential_error("REPLACEMENT_VALIDATION_FAILED")
            candidate = SourceCandidate.objects.create(
                source=source, engine=engine, connection_metadata=metadata,
                selected_tables=tables, credential=candidate_credential, state="validated",
            )
        except CredentialCryptoError:
            return _credential_error("CREDENTIAL_UNAVAILABLE", 503)
        except (CredentialUnavailable, ValueError, KeyError):
            return _credential_error("INVALID_REPLACEMENT")
        logger.info("source_replacement_staged workspace=%s source=%s actor=%s", source.workspace_id, source.pk, principal_user_id(request.user))
        return Response({"success": True, "data": {"candidate_id": candidate.pk, "state": candidate.state}}, status=201)


class SourceReplacementActionView(SourceDetailView):
    http_method_names = ["post", "options"]

    def post(self, request, source_id, action):
        source, error = self._source(request, source_id)
        if error:
            return error
        if action == "discover":
            if source.state != DataSource.ACTIVE or set(request.data) - {"schema", "table"}:
                return _credential_error("INVALID_OPERATION")
            candidate = SourceCandidate.objects.filter(
                source=source, state__in=["validated", "loading"],
            ).select_related("credential").first()
            if candidate is None:
                return _credential_error("REPLACEMENT_NOT_FOUND", 404)
            actor_id = principal_user_id(request.user)
            if actor_id is None or not admit_source_operation(source.workspace_id, actor_id, "discover"):
                return _credential_error("SOURCE_RATE_LIMITED", 429)
            job_id = uuid.uuid4()
            dataset_id = f"candidate-discover-{job_id.hex}"
            try:
                grant = authorize_execution(
                    source, job_id=job_id, dataset_id=dataset_id, kind="candidate",
                    credential=candidate.credential, engine=candidate.engine,
                    metadata=candidate.connection_metadata,
                    configuration_version=source.configuration_version + 1,
                )
                response = requests.post(
                    f"{settings.ETL_SERVICE_URL.rstrip('/')}/api/databases/discover/",
                    json={
                        "credential_ref": execution_reference(grant),
                        "schema": request.data.get("schema"),
                        "table": request.data.get("table"),
                    },
                    headers={
                        "X-Internal-Service": "query-service",
                        "X-Internal-API-Key": str(settings.ETL_INTERNAL_API_KEY),
                        "X-Workspace-ID": str(source.workspace_id),
                        "X-Dataset-ID": dataset_id,
                        "X-Ingestion-Job-ID": str(job_id),
                    }, timeout=130,
                )
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("Invalid discovery response")
                if response.status_code == 200 and body.get("success") is True:
                    return Response({"success": True, "data": body.get("data", {})})
                upstream_error = body.get("error")
                code = upstream_error.get("code") if isinstance(upstream_error, dict) else None
                if not isinstance(code, str) or not code.isupper() or len(code) > 64:
                    code = "DISCOVERY_FAILED"
                return _credential_error(code, response.status_code if 400 <= response.status_code <= 599 else 502)
            except CredentialUnavailable:
                return _credential_error("CREDENTIAL_NOT_AVAILABLE", 400)
            except requests.Timeout:
                return _credential_error("CONNECTION_TIMEOUT", 504)
            except (requests.RequestException, ValueError):
                return _credential_error("ETL_UNAVAILABLE", 503)
        if action not in {"cutover", "rollback"}:
            return _credential_error("INVALID_OPERATION")
        if request.data:
            return _credential_error("INVALID_OPERATION")
        try:
            with transaction.atomic(using=integration_atomic_alias()):
                source = DataSource.objects.select_for_update().get(pk=source.pk)
                if source.state != DataSource.ACTIVE:
                    return _credential_error("SOURCE_DISABLED", 409)
                candidate = SourceCandidate.objects.select_for_update().get(source=source)
                if action == "cutover":
                    from database.models import Database
                    if candidate.state != "loading" or not Database.objects.filter(
                        pk=candidate.validation_dataset_id, source=source, etl_status="completed",
                    ).exists():
                        return _credential_error("REPLACEMENT_NOT_READY", 409)
                    previous = active_credential(source)
                    old_engine, old_metadata, old_tables = source.engine, source.connection_metadata, source.selected_tables
                    source.engine = candidate.engine
                    source.connection_metadata = candidate.connection_metadata
                    source.selected_tables = candidate.selected_tables
                    source.configuration_version += 1
                    source.save(update_fields=["engine", "connection_metadata", "selected_tables", "configuration_version", "updated_at"])
                    activate_credential(source.pk, candidate.credential_id, expected_active_id=previous.pk)
                    candidate.engine, candidate.connection_metadata, candidate.selected_tables = old_engine, old_metadata, old_tables
                    candidate.credential = previous
                    candidate.state = "rollback_ready"
                    candidate.cutover_at = timezone.now()
                    candidate.save()
                else:
                    if candidate.state != "rollback_ready" or candidate.credential.state != SourceCredential.SUPERSEDED:
                        return _credential_error("ROLLBACK_NOT_AVAILABLE", 409)
                    SourceCredential.objects.filter(source=source, state=SourceCredential.ACTIVE).update(
                        state=SourceCredential.SUPERSEDED, deactivated_at=timezone.now(),
                    )
                    SourceCredential.objects.filter(pk=candidate.credential_id).update(
                        state=SourceCredential.ACTIVE, activated_at=timezone.now(), deactivated_at=None,
                    )
                    source.engine, source.connection_metadata, source.selected_tables = (
                        candidate.engine, candidate.connection_metadata, candidate.selected_tables,
                    )
                    source.configuration_version += 1
                    source.save(update_fields=["engine", "connection_metadata", "selected_tables", "configuration_version", "updated_at"])
                    candidate.delete()
        except SourceCandidate.DoesNotExist:
            return _credential_error("REPLACEMENT_NOT_FOUND", 404)
        except CredentialUnavailable:
            return _credential_error("CREDENTIAL_NOT_AVAILABLE", 409)
        logger.info("source_replacement_%s workspace=%s source=%s actor=%s", action, source.workspace_id, source.pk, principal_user_id(request.user))
        return Response({"success": True, "data": public_source(source)})
