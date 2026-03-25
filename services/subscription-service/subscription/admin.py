from django.contrib import admin

from .models import FreeTierUsage, Payment, Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'price_monthly', 'price_yearly', 'max_voice_requests', 'is_active')
    list_filter = ('is_active', 'has_mcp_access')
    search_fields = ('name',)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'workspace_id', 'plan', 'is_active', 'voice_requests_used', 'start_date', 'end_date')
    list_filter = ('is_active', 'plan')
    search_fields = ('workspace_id',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'workspace_id', 'user_id', 'amount', 'payment_method', 'status', 'created_at')
    list_filter = ('status', 'payment_method')
    search_fields = ('workspace_id', 'user_id')


@admin.register(FreeTierUsage)
class FreeTierUsageAdmin(admin.ModelAdmin):
    list_display = ('workspace_id', 'requests_used', 'updated_at')
    search_fields = ('workspace_id',)
