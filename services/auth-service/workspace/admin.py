from django.contrib import admin
from .models import Workspace, WorkspaceMember, Invitation


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    """Admin configuration for Workspace model."""
    
    list_display = ['name', 'owner', 'created_at']
    list_filter = ['created_at']
    search_fields = ['name', 'owner__email', 'owner__name']
    ordering = ['-created_at']
    readonly_fields = ['created_at']
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('owner')


@admin.register(WorkspaceMember)
class WorkspaceMemberAdmin(admin.ModelAdmin):
    """Admin configuration for WorkspaceMember model."""
    
    list_display = ['user', 'workspace', 'joined_at']
    list_filter = ['joined_at']
    search_fields = ['user__email', 'user__name', 'workspace__name']
    ordering = ['-joined_at']
    readonly_fields = ['joined_at']
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('user', 'workspace')


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
