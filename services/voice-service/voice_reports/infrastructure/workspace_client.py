from __future__ import annotations

import os
from dataclasses import dataclass
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
    ) -> tuple[str, str]:
        if not workspace_id:
            return "", fallback_manager_id
        response = self._get(
            f"{self.base_url}/workspace/{workspace_id}/",
            headers=self._headers(authorization_header),
            timeout=10,
        )
        if response.status_code != 200:
            return "", fallback_manager_id
        payload = self._json_payload(response)
        nested = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
        resolved_workspace_id = str(payload.get("id") or nested.get("id") or workspace_id or "").strip()
        manager_id = str(payload.get("manager_id") or nested.get("owner_id") or fallback_manager_id or "").strip()
        return resolved_workspace_id, manager_id

    def _resolve_from_workspace_members(
        self,
        *,
        authorization_header: str,
        fallback_manager_id: str,
    ) -> tuple[str, str]:
        response = self._get(
            f"{self.base_url}/workspace/members/",
            headers=self._headers(authorization_header),
            timeout=10,
        )
        if response.status_code != 200:
            return "", fallback_manager_id
        payload = self._json_payload(response)
        workspace_id = str(payload.get("workspace_id") or "").strip()
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

        return workspace_id, manager_id

    def _resolve_from_workspace_me(
        self,
        *,
        authorization_header: str,
        fallback_manager_id: str,
    ) -> tuple[str, str]:
        response = self._get(
            f"{self.base_url}/workspace/",
            headers=self._headers(authorization_header),
            timeout=10,
        )
        if response.status_code != 200:
            return "", fallback_manager_id
        payload = self._json_payload(response)
        nested = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
        workspace_id = str(payload.get("id") or nested.get("id") or "").strip()
        manager_id = str(payload.get("manager_id") or nested.get("owner_id") or fallback_manager_id or "").strip()
        return workspace_id, manager_id

    def resolve(self, *, request, workspace_hint: str, user_id: str) -> WorkspaceContext:
        workspace_id = str(workspace_hint or "").strip()
        manager_id = str(user_id or "").strip()
        authorization_header = str(request.META.get("HTTP_AUTHORIZATION") or "")

        if workspace_id:
            try:
                resolved_workspace_id, resolved_manager_id = self._resolve_from_workspace_id(
                    workspace_id=workspace_id,
                    authorization_header=authorization_header,
                    fallback_manager_id=manager_id,
                )
                if resolved_workspace_id:
                    workspace_id = resolved_workspace_id
                manager_id = resolved_manager_id or manager_id
            except (HttpClientError, requests.RequestException, Exception):
                pass

        if not workspace_id:
            try:
                resolved_workspace_id, resolved_manager_id = self._resolve_from_workspace_members(
                    authorization_header=authorization_header,
                    fallback_manager_id=manager_id,
                )
                if resolved_workspace_id:
                    workspace_id = resolved_workspace_id
                manager_id = resolved_manager_id or manager_id
            except (HttpClientError, requests.RequestException, Exception):
                pass

        if not workspace_id:
            try:
                resolved_workspace_id, resolved_manager_id = self._resolve_from_workspace_me(
                    authorization_header=authorization_header,
                    fallback_manager_id=manager_id,
                )
                if resolved_workspace_id:
                    workspace_id = resolved_workspace_id
                manager_id = resolved_manager_id or manager_id
            except (HttpClientError, requests.RequestException, Exception):
                pass

        # Phase 13 / GAP-08: do not call query-service ``/database/`` to guess a
        # default dataset. Callers pass ``dataset_id`` / ``table_name`` on the
        # request (stored on the pipeline job trace) or leave them empty.

        return WorkspaceContext(
            workspace_id=str(workspace_id or "").strip(),
            manager_id=str(manager_id or "").strip(),
            dataset_id="",
            source_id="",
            table_name="",
        )


def get_workspace_client() -> WorkspaceClient:
    return WorkspaceClient()
