"""Authenticated ciphertext-only resolution for authorized ETL operations."""

import hmac
import uuid

from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from .credentials import CredentialUnavailable, resolve_execution


class CredentialResolverUnavailable(exceptions.APIException):
    status_code = 503
    default_detail = "Credential resolution is unavailable."
    default_code = "credential_resolution_unavailable"


class CredentialServiceAuthentication(BaseAuthentication):
    def authenticate(self, request):
        service = request.headers.get("X-Internal-Service", "")
        supplied = request.headers.get("X-Credential-Resolver-Key", "")
        key_names = {
            "etl-connector": ("CREDENTIAL_RESOLVER_CONNECTOR_KEY", "CREDENTIAL_RESOLVER_CONNECTOR_KEY_PREVIOUS"),
            "etl-extractor": ("CREDENTIAL_RESOLVER_EXTRACTOR_KEY", "CREDENTIAL_RESOLVER_EXTRACTOR_KEY_PREVIOUS"),
        }
        if service not in key_names:
            raise exceptions.AuthenticationFailed("Invalid credential service identity.")
        expected = [str(getattr(settings, name, "") or "") for name in key_names[service]]
        if settings.APP_ENV != "production" and not expected[0]:
            expected = [str(getattr(settings, "CREDENTIAL_RESOLVER_API_KEY", "") or "")]
        expected = [value for value in expected if value]
        if not expected:
            raise CredentialResolverUnavailable()
        if not supplied or not any(hmac.compare_digest(value, supplied) for value in expected):
            raise exceptions.AuthenticationFailed("Invalid credential service identity.")
        return type("CredentialPrincipal", (), {"is_authenticated": True, "service": service})(), None


class ResolveSourceCredentialView(APIView):
    authentication_classes = [CredentialServiceAuthentication]
    permission_classes = []

    def post(self, request):
        try:
            workspace_id = int(request.data.get("workspace_id"))
            if workspace_id <= 0:
                raise ValueError
            source_id = uuid.UUID(str(request.data.get("source_id")))
            job_id = uuid.UUID(str(request.data.get("job_id")))
            credential_id = uuid.UUID(str(request.data.get("credential_id")))
            version = int(request.data.get("credential_version"))
            dataset_id = str(request.data.get("dataset_id") or "")
            if not dataset_id or len(dataset_id) > 128 or version <= 0:
                raise ValueError
            grant = resolve_execution(
                workspace_id=workspace_id, source_id=source_id, job_id=job_id,
                dataset_id=dataset_id, credential_id=credential_id, version=version,
            )
            if request.user.service == "etl-extractor" and grant.kind not in {"snapshot", "candidate"}:
                raise CredentialUnavailable("Operation is not authorized for this service.")
        except (TypeError, ValueError, CredentialUnavailable):
            return Response({"success": False, "error": {"code": "CREDENTIAL_NOT_AVAILABLE"}}, status=403)
        return Response({"success": True, "data": {
            "source_id": str(grant.source_id), "workspace_id": grant.workspace_id,
            "dataset_id": grant.dataset_id, "job_id": str(grant.job_id),
            "credential_id": str(grant.credential_id), "credential_version": grant.credential.version,
            "key_version": grant.credential.key_version, "ciphertext": grant.credential.ciphertext,
            "engine": grant.engine, "connection_metadata": grant.connection_metadata,
            "configuration_version": grant.configuration_version, "transport": grant.transport,
        }})
