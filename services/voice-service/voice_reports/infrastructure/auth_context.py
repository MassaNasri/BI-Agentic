from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rest_framework.exceptions import APIException, NotFound, PermissionDenied

from .workspace_client import WorkspaceResolution, WorkspaceResolutionStatus


@dataclass
class IdentityContext:
    user_id: str
    role: str
    email: str
    workspace_hint: str
    authorization_header: str


def _auth_payload(request) -> dict[str, Any]:
    auth_payload = getattr(request, "auth", None)
    if isinstance(auth_payload, dict):
        return auth_payload
    return {}


def _claim(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _extract_workspace_hint(payload: dict[str, Any]) -> str:
    return _claim(payload, "workspace_id", "workspace", "ws_id", "tenant_id")


def extract_identity_context(request) -> IdentityContext:
    payload = _auth_payload(request)
    auth_header = str(request.META.get("HTTP_AUTHORIZATION") or "").strip()
    user_id = str(getattr(request.user, "id", "") or "").strip() or _claim(payload, "user_id", "sub", "id")
    role = str(getattr(request.user, "role", "") or "").strip().lower() or _claim(payload, "role", "user_role").lower()
    email = str(getattr(request.user, "email", "") or "").strip() or _claim(payload, "email", "user_email")
    workspace_hint = str(
        request.data.get("workspace_id")
        or request.query_params.get("workspace_id")
        or _extract_workspace_hint(payload)
        or ""
    ).strip()
    return IdentityContext(
        user_id=user_id,
        role=role,
        email=email,
        workspace_hint=workspace_hint,
        authorization_header=auth_header,
    )


def request_role(request) -> str:
    return extract_identity_context(request).role


def request_user_id(request) -> str:
    return extract_identity_context(request).user_id


def request_user_email(request) -> str:
    return extract_identity_context(request).email


class WorkspaceDependencyUnavailable(APIException):
    status_code = 503
    default_detail = "Workspace authorization service is unavailable."
    default_code = "workspace_authorization_unavailable"


class WorkspaceAuthorizationInvalid(APIException):
    status_code = 502
    default_detail = "Workspace authorization service returned an invalid response."
    default_code = "workspace_authorization_invalid"


def require_authorized_workspace(resolution: WorkspaceResolution):
    if resolution.status is WorkspaceResolutionStatus.AUTHORIZED and resolution.context:
        return resolution.context
    if resolution.status is WorkspaceResolutionStatus.DENIED:
        raise PermissionDenied("Workspace access denied.")
    if resolution.status is WorkspaceResolutionStatus.NOT_FOUND:
        raise NotFound("Workspace not found.")
    if resolution.status is WorkspaceResolutionStatus.DEPENDENCY_UNAVAILABLE:
        raise WorkspaceDependencyUnavailable()
    raise WorkspaceAuthorizationInvalid()
