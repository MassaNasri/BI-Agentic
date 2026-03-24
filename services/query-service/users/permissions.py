"""
Custom Permission Classes

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

