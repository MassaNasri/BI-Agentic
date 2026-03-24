"""
Voice Reports Admin

Django admin configuration for voice reports.
"""

from django.contrib import admin
from .models import VoiceReport, SQLEditHistory, DashboardPage, ReportPageAssignment


@admin.register(VoiceReport)
class VoiceReportAdmin(admin.ModelAdmin):
    """Admin interface for Voice Reports."""
    
    list_display = [
        'id',
        'workspace',
        'created_by',
        'title',
        'status',
        'chart_type',
        'created_at'
    ]
    
    list_filter = [
        'status',
        'chart_type',
        'created_at'
    ]
    
    search_fields = [
        'title',
        'transcription',
        'generated_sql',
        'created_by__email',
        'workspace__name'
    ]
    
    readonly_fields = [
        'created_at',
        'updated_at'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'workspace',
                'created_by',
                'title',
                'description',
                'status',
                'created_at',
                'updated_at'
            )
        }),
        ('Audio & Transcription', {
            'fields': (
                'audio_file',
                'audio_duration',
                'transcription',
                'transcription_language'
            )
        }),
        ('SQL', {
            'fields': (
                'intent_json',
                'generated_sql',
                'final_sql',
                'sql_validated'
            )
        }),
        ('Execution Results', {
            'fields': (
                'query_result',
                'row_count',
                'execution_time_ms',
                'error_message'
            )
        }),
        ('Visualization', {
            'fields': (
                'chart_type',
                'chart_config',
                'metabase_question_id',
                'metabase_dashboard_id',
                'embed_url'
            )
        })
    )


@admin.register(SQLEditHistory)
class SQLEditHistoryAdmin(admin.ModelAdmin):
    """Admin interface for SQL Edit History."""
    
    list_display = [
        'id',
        'report',
        'edited_by',
        'validation_passed',
        'edited_at'
    ]
    
    list_filter = [
        'validation_passed',
        'edited_at'
    ]
    
    search_fields = [
        'report__title',
        'edited_by__email',
        'previous_sql',
        'new_sql'
    ]
    
    readonly_fields = [
        'report',
        'edited_by',
        'previous_sql',
        'new_sql',
        'validation_passed',
        'validation_errors',
        'edited_at'
    ]
    
    def has_add_permission(self, request):
        return False


@admin.register(DashboardPage)
class DashboardPageAdmin(admin.ModelAdmin):
    """Admin interface for Dashboard Pages."""
    
    list_display = [
        'id',
        'workspace',
        'name',
        'order',
        'created_at'
    ]
    
    list_filter = [
        'workspace',
        'created_at'
    ]
    
    search_fields = [
        'workspace__name',
        'name',
        'description'
    ]
    
    readonly_fields = [
        'created_at'
    ]


@admin.register(ReportPageAssignment)
class ReportPageAssignmentAdmin(admin.ModelAdmin):
    """Admin interface for Report Page Assignments."""
    
    list_display = [
        'id',
        'report',
        'page',
        'order',
        'added_at'
    ]
    
    list_filter = [
        'page',
        'added_at'
    ]
    
    search_fields = [
        'report__title',
        'page__name'
    ]
    
    readonly_fields = [
        'added_at'
    ]
