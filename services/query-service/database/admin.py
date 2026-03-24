from django.contrib import admin
from .models import Database


@admin.register(Database)
class DatabaseAdmin(admin.ModelAdmin):
    list_display = ('filename', 'manager', 'upload_date', 'file_size', 'row_count', 'column_count')
    list_filter = ('upload_date', 'manager')
    search_fields = ('filename', 'manager__email', 'manager__name')
    readonly_fields = ('upload_date',)
    ordering = ('-upload_date',)

