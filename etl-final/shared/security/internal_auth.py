"""Fail-closed authentication and tenant scope for ETL control-plane APIs."""

from dataclasses import dataclass
import hmac
import re
import uuid

from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication


_DATASET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True)
class InternalServicePrincipal:
    service_name: str

    @property
    def is_authenticated(self) -> bool:
        return True


class InternalIdentityUnavailable(exceptions.APIException):
    status_code = 503
    default_detail = "ETL internal authentication is not configured."
    default_code = "etl_internal_identity_unavailable"


@dataclass(frozen=True)
class ETLRequestScope:
    workspace_id: int
    dataset_id: str
    ingestion_job_id: uuid.UUID

    def as_message_fields(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "dataset_id": self.dataset_id,
            "ingestion_job_id": str(self.ingestion_job_id),
        }


class ETLInternalAuthentication(BaseAuthentication):
    """Authenticate callers with a separately rotated ETL service credential."""

    allowed_services = frozenset({"query-service", "gateway-service", "etl-admin"})

    def authenticate(self, request):
        expected = str(getattr(settings, "ETL_INTERNAL_API_KEY", "") or "").strip()
        if not expected:
            raise InternalIdentityUnavailable()

        service = str(request.headers.get("X-Internal-Service", "")).strip().lower()
        provided = str(request.headers.get("X-Internal-API-Key", ""))
        if service not in self.allowed_services or not hmac.compare_digest(provided, expected):
            raise exceptions.AuthenticationFailed("Invalid internal service credentials.")
        return InternalServicePrincipal(service), None


def require_etl_scope(request) -> ETLRequestScope:
    """Parse an immutable scope from headers or request data; all fields are required."""

    data = getattr(request, "data", {})
    raw_workspace = request.headers.get("X-Workspace-ID") or data.get("workspace_id")
    raw_dataset = request.headers.get("X-Dataset-ID") or data.get("dataset_id")
    raw_job = request.headers.get("X-Ingestion-Job-ID") or data.get("ingestion_job_id")

    try:
        workspace_id = int(raw_workspace)
        if workspace_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise exceptions.ValidationError({"workspace_id": "A positive workspace scope is required."})

    dataset_id = str(raw_dataset or "").strip()
    if not _DATASET_RE.fullmatch(dataset_id):
        raise exceptions.ValidationError({"dataset_id": "A valid dataset scope is required."})

    try:
        ingestion_job_id = uuid.UUID(str(raw_job))
    except (TypeError, ValueError, AttributeError):
        raise exceptions.ValidationError({"ingestion_job_id": "A valid ingestion job UUID is required."})

    scope = ETLRequestScope(workspace_id, dataset_id, ingestion_job_id)
    request.etl_scope = scope
    return scope


def record_matches_scope(record: dict, scope: ETLRequestScope) -> bool:
    """Require exact tenant, dataset, and job equality for stored ETL metadata."""

    if not isinstance(record, dict):
        return False
    return all(
        str(record.get(key)) == str(value)
        for key, value in scope.as_message_fields().items()
    )
