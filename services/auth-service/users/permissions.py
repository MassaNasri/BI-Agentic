"""
Custom permission classes for auth-service.

Prefer shared role permissions when ``bi_platform_shared`` is available.
Fallback local implementations keep runtime stable when that package is not
mounted in lightweight environments.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

try:  # pragma: no cover
    from bi_platform_shared.permissions.roles import (  # type: ignore
        IsAdmin,
        IsAnalyst,
        IsExecutive,
        IsManager,
        IsManagerOrAnalyst,
    )
except Exception:  # pragma: no cover
    class _RolePermission(BasePermission):
        allowed_roles: set[str] = set()

        def has_permission(self, request, view):
            role = str(getattr(request.user, "role", "") or "").strip().lower()
            return bool(getattr(request.user, "is_authenticated", False)) and role in self.allowed_roles

    class IsAdmin(_RolePermission):
        allowed_roles = {"admin"}

    class IsManager(_RolePermission):
        allowed_roles = {"manager"}

    class IsAnalyst(_RolePermission):
        allowed_roles = {"analyst"}

    class IsExecutive(_RolePermission):
        allowed_roles = {"executive"}

    class IsManagerOrAnalyst(_RolePermission):
        allowed_roles = {"manager", "analyst"}


__all__ = [
    "IsAdmin",
    "IsAnalyst",
    "IsExecutive",
    "IsManager",
    "IsManagerOrAnalyst",
]
