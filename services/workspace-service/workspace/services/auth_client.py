from __future__ import annotations

import os
from typing import Any

import requests

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
    _SHARED_HTTP_AVAILABLE = True
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]
    _SHARED_HTTP_AVAILABLE = False


class AuthServiceError(Exception):
    pass


class AuthServiceClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8001").rstrip("/")
        self.internal_token = str(
            os.getenv("INTERNAL_SERVICE_TOKEN", "")
            or os.getenv("INTERNAL_API_TOKEN", "")
            or os.getenv("SERVICE_INTERNAL_TOKEN", "")
            or ""
        ).strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.internal_token:
            headers["Authorization"] = f"Bearer {self.internal_token}"
            headers["X-Internal-Service"] = "workspace-service"
        return headers

    @staticmethod
    def _json(response) -> dict[str, Any]:
        try:
            payload = response.json() if getattr(response, "content", None) else {}
        except ValueError:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None):
        url = f"{self.base_url}{path}"
        headers = self._headers()
        if _SHARED_HTTP_AVAILABLE:
            return get_default_client().request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
                timeout=(5.0, 15.0),
                attach_internal_api_key=False,
            )
        return requests.request(method, url, headers=headers, params=params, json=json, timeout=15)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        try:
            response = self._request("GET", "/internal/users/by-email/", params={"email": email})
        except (HttpClientError, requests.RequestException) as exc:  # type: ignore[misc]
            raise AuthServiceError(f"auth_service_unavailable:{exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise AuthServiceError(f"auth_service_http_{response.status_code}")
        payload = self._json(response)
        user = payload.get("user")
        return user if isinstance(user, dict) else None

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        try:
            response = self._request("GET", f"/internal/users/{int(user_id)}/")
        except (HttpClientError, requests.RequestException) as exc:  # type: ignore[misc]
            raise AuthServiceError(f"auth_service_unavailable:{exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise AuthServiceError(f"auth_service_http_{response.status_code}")
        payload = self._json(response)
        user = payload.get("user")
        return user if isinstance(user, dict) else None

    def patch_user(self, user_id: int, updates: dict[str, Any]) -> dict[str, Any] | None:
        try:
            response = self._request("PATCH", f"/internal/users/{int(user_id)}/", json=updates)
        except (HttpClientError, requests.RequestException) as exc:  # type: ignore[misc]
            raise AuthServiceError(f"auth_service_unavailable:{exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise AuthServiceError(f"auth_service_http_{response.status_code}")
        payload = self._json(response)
        user = payload.get("user")
        return user if isinstance(user, dict) else None


_client: AuthServiceClient | None = None


def get_auth_service_client() -> AuthServiceClient:
    global _client
    if _client is None:
        _client = AuthServiceClient()
    return _client
