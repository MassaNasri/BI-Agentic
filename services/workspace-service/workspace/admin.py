from django.contrib import admin
from .models import Workspace, WorkspaceMember, Invitation


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    """Admin configuration for Workspace model."""
    
    list_display = ['name', 'owner', 'owner_email', 'created_at']
    list_filter = ['created_at']
    search_fields = ['name', 'owner_email', 'owner_name']
    ordering = ['-created_at']
    readonly_fields = ['created_at']
    
    def get_queryset(self, request):
        return super().get_queryset(request)


@admin.register(WorkspaceMember)
class WorkspaceMemberAdmin(admin.ModelAdmin):
    """Admin configuration for WorkspaceMember model."""
    
    list_display = ['user', 'user_email', 'workspace', 'status', 'joined_at']
    list_filter = ['joined_at', 'status', 'role']
    search_fields = ['user_email', 'user_name', 'invited_email', 'workspace__name']
    ordering = ['-joined_at']
    readonly_fields = ['joined_at']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('workspace')


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    """Admin configuration for Invitation model."""
    
    list_display = ['invited_email', 'workspace', 'role', 'status', 'created_at', 'expires_at']
    list_filter = ['status', 'role', 'created_at']
    search_fields = ['invited_email', 'workspace__name']
    ordering = ['-created_at']
    readonly_fields = ['token', 'created_at', 'expires_at']
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('workspace')
