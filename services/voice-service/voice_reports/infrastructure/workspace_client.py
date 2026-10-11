from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

import requests

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
    _SHARED_CLIENT_AVAILABLE = True
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]
    _SHARED_CLIENT_AVAILABLE = False


@dataclass
class WorkspaceContext:
    workspace_id: str
    manager_id: str
    dataset_id: str
    source_id: str
    table_name: str


class WorkspaceResolutionStatus(str, Enum):
    AUTHORIZED = "authorized"
    DENIED = "denied"
    NOT_FOUND = "not_found"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True)
class WorkspaceResolution:
    status: WorkspaceResolutionStatus
    context: WorkspaceContext | None = None
    detail: str = ""

    @property
    def authorized(self) -> bool:
        return self.status is WorkspaceResolutionStatus.AUTHORIZED and self.context is not None

    # Compatibility properties deliberately return empty values unless the
    # workspace service positively authorized the resource.
    @property
    def workspace_id(self) -> str:
        return self.context.workspace_id if self.authorized else ""

    @property
    def manager_id(self) -> str:
        return self.context.manager_id if self.authorized else ""

    @property
    def dataset_id(self) -> str:
        return self.context.dataset_id if self.authorized else ""

    @property
    def source_id(self) -> str:
        return self.context.source_id if self.authorized else ""

    @property
    def table_name(self) -> str:
        return self.context.table_name if self.authorized else ""


class WorkspaceClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("WORKSPACE_SERVICE_URL", "http://workspace-service:8002").rstrip("/")

    def _headers(self, authorization_header: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if authorization_header:
            headers["Authorization"] = authorization_header
        return headers

    def _get(self, url: str, *, headers: dict[str, str], timeout: float):
        if _SHARED_CLIENT_AVAILABLE:
            return get_default_client().get(
                url,
                headers=headers,
                timeout=(min(5.0, float(timeout)), float(timeout)),
                attach_internal_api_key=False,
            )
        return requests.get(url, headers=headers, timeout=timeout)

    @staticmethod
    def _json_payload(response) -> dict[str, Any]:
        try:
            payload = response.json() if getattr(response, "content", None) else {}
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _resolve_from_workspace_id(
        self,
        *,
        workspace_id: str,
        authorization_header: str,
        fallback_manager_id: str,
    ) -> WorkspaceResolution:
        if not workspace_id:
            return WorkspaceResolution(WorkspaceResolutionStatus.INVALID_RESPONSE, detail="workspace_id is required")
        try:
            response = self._get(
                f"{self.base_url}/workspace/{workspace_id}/",
                headers=self._headers(authorization_header),
                timeout=10,
            )
        except Exception:
            return WorkspaceResolution(WorkspaceResolutionStatus.DEPENDENCY_UNAVAILABLE)
        if response.status_code != 200:
            if response.status_code in {401, 403}:
                return WorkspaceResolution(WorkspaceResolutionStatus.DENIED)
            if response.status_code == 404:
                return WorkspaceResolution(WorkspaceResolutionStatus.NOT_FOUND)
            return WorkspaceResolution(WorkspaceResolutionStatus.DEPENDENCY_UNAVAILABLE)
        payload = self._json_payload(response)
        nested = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
        resolved_workspace_id = str(payload.get("id") or nested.get("id") or "").strip()
        if not resolved_workspace_id or resolved_workspace_id != str(workspace_id).strip():
            return WorkspaceResolution(WorkspaceResolutionStatus.INVALID_RESPONSE)
        manager_id = str(payload.get("manager_id") or nested.get("owner_id") or fallback_manager_id or "").strip()
        return WorkspaceResolution(
            WorkspaceResolutionStatus.AUTHORIZED,
            WorkspaceContext(resolved_workspace_id, manager_id, "", "", ""),
        )

    def _resolve_from_workspace_members(
        self,
        *,
        authorization_header: str,
        fallback_manager_id: str,
    ) -> WorkspaceResolution:
        try:
            response = self._get(
                f"{self.base_url}/workspace/members/",
                headers=self._headers(authorization_header),
                timeout=10,
            )
        except Exception:
            return WorkspaceResolution(WorkspaceResolutionStatus.DEPENDENCY_UNAVAILABLE)
        if response.status_code != 200:
            if response.status_code in {401, 403}:
                return WorkspaceResolution(WorkspaceResolutionStatus.DENIED)
            if response.status_code == 404:
                return WorkspaceResolution(WorkspaceResolutionStatus.NOT_FOUND)
            return WorkspaceResolution(WorkspaceResolutionStatus.DEPENDENCY_UNAVAILABLE)
        payload = self._json_payload(response)
        workspace_id = str(payload.get("workspace_id") or "").strip()
        if not workspace_id:
            return WorkspaceResolution(WorkspaceResolutionStatus.INVALID_RESPONSE)
        manager_id = str(fallback_manager_id or "").strip()

        accepted_members = payload.get("accepted_members")
        if isinstance(accepted_members, list):
            for member in accepted_members:
                if not isinstance(member, dict):
                    continue
                role = str(member.get("role") or "").strip().lower()
                candidate_id = str(member.get("id") or "").strip()
                if role == "manager" and candidate_id:
                    manager_id = candidate_id
                    break

        return WorkspaceResolution(
            WorkspaceResolutionStatus.AUTHORIZED,
            WorkspaceContext(workspace_id, manager_id, "", "", ""),
        )

    def _resolve_from_workspace_me(
        self,
        *,
        authorization_header: str,
        fallback_manager_id: str,
    ) -> WorkspaceResolution:
        try:
            response = self._get(
                f"{self.base_url}/workspace/",
                headers=self._headers(authorization_header),
                timeout=10,
            )
        except Exception:
            return WorkspaceResolution(WorkspaceResolutionStatus.DEPENDENCY_UNAVAILABLE)
        if response.status_code != 200:
            if response.status_code in {401, 403}:
                return WorkspaceResolution(WorkspaceResolutionStatus.DENIED)
            if response.status_code == 404:
                return WorkspaceResolution(WorkspaceResolutionStatus.NOT_FOUND)
            return WorkspaceResolution(WorkspaceResolutionStatus.DEPENDENCY_UNAVAILABLE)
        payload = self._json_payload(response)
        nested = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
        workspace_id = str(payload.get("id") or nested.get("id") or "").strip()
        if not workspace_id:
            return WorkspaceResolution(WorkspaceResolutionStatus.INVALID_RESPONSE)
        manager_id = str(payload.get("manager_id") or nested.get("owner_id") or fallback_manager_id or "").strip()
        return WorkspaceResolution(
            WorkspaceResolutionStatus.AUTHORIZED,
            WorkspaceContext(workspace_id, manager_id, "", "", ""),
        )

    def resolve(self, *, request, workspace_hint: str, user_id: str) -> WorkspaceResolution:
        requested_workspace_id = str(workspace_hint or "").strip()
        manager_id = str(user_id or "").strip()
        authorization_header = str(request.META.get("HTTP_AUTHORIZATION") or "")

        if requested_workspace_id:
            return self._resolve_from_workspace_id(
                workspace_id=requested_workspace_id,
                authorization_header=authorization_header,
                fallback_manager_id=manager_id,
            )

        # With no requested ID, resolve a membership-owned workspace. A denied,
        # malformed, or unavailable response is final; it must not fall through
        # to a different endpoint and accidentally broaden authorization.
        return self._resolve_from_workspace_members(
            authorization_header=authorization_header,
            fallback_manager_id=manager_id,
        )


def get_workspace_client() -> WorkspaceClient:
    return WorkspaceClient()
