"""
Custom Permission Classes

<<<<<<< HEAD
Role-based permissions for the BI system.
"""

from rest_framework.permissions import BasePermission


class IsManager(BasePermission):
    """
    Permission class to allow only managers.
    """
    
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'manager'


class IsAnalyst(BasePermission):
    """
    Permission class to allow only analysts.
    """
    
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'analyst'


class IsExecutive(BasePermission):
    """
    Permission class to allow only executives.
    """
    
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'executive'


class IsManagerOrAnalyst(BasePermission):
    """
    Permission class to allow managers or analysts.
    """
    
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.role in ['manager', 'analyst']
        )


class IsAdmin(BasePermission):
    """
    Permission class to allow only system admins.
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'admin'

=======
Prefer shared permission classes when ``bi_platform_shared`` is available.
Fallbacks keep local service validation/runtime stable in lightweight
environments where that package is not mounted.
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

>>>>>>> c791036 (final update)
