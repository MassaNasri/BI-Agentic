from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
