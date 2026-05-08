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


class WorkspaceServiceError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class WorkspaceServiceClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("WORKSPACE_SERVICE_URL", "http://workspace-service:8002").rstrip("/")
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
            headers["X-Internal-Service"] = "auth-service"
        return headers

    @staticmethod
    def _json(response) -> dict[str, Any]:
        try:
            payload = response.json() if getattr(response, "content", None) else {}
        except ValueError:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ):
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

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        allowed_statuses: set[int] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        allowed = allowed_statuses or {200}
        try:
            response = self._request(method, path, params=params, json=json)
        except (HttpClientError, requests.RequestException) as exc:  # type: ignore[misc]
            raise WorkspaceServiceError(f"workspace_service_unavailable:{exc}") from exc
        payload = self._json(response)
        if response.status_code not in allowed:
            message = str(payload.get("message") or f"workspace_service_http_{response.status_code}")
            raise WorkspaceServiceError(message, status_code=int(response.status_code))
        return int(response.status_code), payload

    def resolve_invitation(self, token: str) -> dict[str, Any]:
        _, payload = self._request_json(
            "POST",
            "/workspace/internal/invitations/resolve/",
            json={"token": token},
            allowed_statuses={200, 404, 409, 410},
        )
        if payload.get("success"):
            invitation = payload.get("invitation")
            return invitation if isinstance(invitation, dict) else {}
        message = str(payload.get("message") or "Invalid invitation link.")
        raise WorkspaceServiceError(message)

    def attach_user_to_invitation(
        self,
        *,
        token: str,
        user_id: int,
        user_email: str,
        user_name: str,
        user_role: str,
        is_verified: bool,
        is_active: bool,
    ) -> dict[str, Any]:
        _, payload = self._request_json(
            "POST",
            "/workspace/internal/invitations/attach-user/",
            json={
                "token": token,
                "user_id": int(user_id),
                "user_email": user_email,
                "user_name": user_name,
                "user_role": user_role,
                "is_verified": bool(is_verified),
                "is_active": bool(is_active),
            },
        )
        return payload

    def create_manager_workspace(
        self,
        *,
        user_id: int,
        user_email: str,
        user_name: str,
        workspace_name: str = "",
    ) -> dict[str, Any]:
        _, payload = self._request_json(
            "POST",
            "/workspace/internal/workspaces/create-manager/",
            json={
                "user_id": int(user_id),
                "user_email": user_email,
                "user_name": user_name,
                "workspace_name": workspace_name,
            },
        )
        workspace = payload.get("workspace")
        return workspace if isinstance(workspace, dict) else {}

    def get_user_workspaces(self, *, user_id: int, role: str) -> Any:
        _, payload = self._request_json(
            "GET",
            f"/workspace/internal/users/{int(user_id)}/workspaces/",
            params={"role": role},
        )
        return payload.get("workspace")

    def activate_user_memberships(
        self,
        *,
        user_id: int,
        user_email: str,
        user_name: str,
        user_role: str,
        is_active: bool,
        is_verified: bool,
    ) -> dict[str, Any]:
        _, payload = self._request_json(
            "POST",
            "/workspace/internal/users/activate-memberships/",
            json={
                "user_id": int(user_id),
                "user_email": user_email,
                "user_name": user_name,
                "user_role": user_role,
                "is_active": bool(is_active),
                "is_verified": bool(is_verified),
            },
        )
        return payload


_client: WorkspaceServiceClient | None = None


def get_workspace_service_client() -> WorkspaceServiceClient:
    global _client
    if _client is None:
        _client = WorkspaceServiceClient()
    return _client

