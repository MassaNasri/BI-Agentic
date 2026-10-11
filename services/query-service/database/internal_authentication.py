from __future__ import annotations

import secrets
from dataclasses import dataclass

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import APIException, AuthenticationFailed


class InternalIdentityUnavailable(APIException):
    status_code = 503
    default_detail = "Internal service authentication is not configured."
    default_code = "internal_identity_unavailable"


@dataclass(frozen=True)
class InternalServicePrincipal:
    service: str

    @property
    def is_authenticated(self) -> bool:
        return True


class IngestionServiceAuthentication(BaseAuthentication):
    allowed_services = {"etl-connector", "etl-loader", "etl-metadata"}

    def authenticate(self, request):
        configured_key = str(getattr(settings, "INGESTION_CALLBACK_API_KEY", "") or "")
        if not configured_key:
            raise InternalIdentityUnavailable()
        service = str(request.headers.get("X-Internal-Service") or "").strip().lower()
        supplied_key = str(request.headers.get("X-Internal-API-Key") or "")
        if service not in self.allowed_services or not supplied_key:
            raise AuthenticationFailed("Valid ingestion service identity is required.")
        if not secrets.compare_digest(configured_key, supplied_key):
            raise AuthenticationFailed("Valid ingestion service identity is required.")
        return InternalServicePrincipal(service), {"service": service}
