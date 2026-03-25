from django.contrib import admin

from .models import NotificationDispatchLog


@admin.register(NotificationDispatchLog)
class NotificationDispatchLogAdmin(admin.ModelAdmin):
    list_display = (
        'event_type',
        'event_key',
        'recipient_email',
        'status',
        'created_at',
        'sent_at',
    )
    list_filter = ('event_type', 'status', 'created_at')
    search_fields = ('event_type', 'event_key', 'recipient_email')
