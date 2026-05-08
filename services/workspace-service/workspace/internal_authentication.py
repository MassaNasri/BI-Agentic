from __future__ import annotations

import os
import secrets
from typing import Any, Optional, Tuple

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class InternalServiceUser:
    is_authenticated = True
    is_active = True
    is_staff = False
    is_superuser = False
    role = "service"
    id = -1
    pk = -1
    email = "internal-service@local"
    name = "internal-service"
    is_verified = True


def _expected_internal_token() -> str:
    return str(
        os.getenv("INTERNAL_SERVICE_TOKEN", "")
        or os.getenv("INTERNAL_API_TOKEN", "")
        or os.getenv("SERVICE_INTERNAL_TOKEN", "")
        or ""
    ).strip()


class ServiceInternalTokenAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request) -> Optional[Tuple[Any, Any]]:
        expected = _expected_internal_token()
        if not expected:
            return None

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header or not isinstance(auth_header, str):
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != self.keyword.lower():
            return None

        token = parts[1].strip()
        if not token:
            raise AuthenticationFailed("Invalid internal service token.")

        if not secrets.compare_digest(token, expected):
            return None

        return InternalServiceUser(), {"auth": "internal_service_token"}
