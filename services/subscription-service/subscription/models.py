from django.db import models
from django.utils import timezone


class Plan(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True, default='')
    badge = models.CharField(max_length=40, blank=True, default='')
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2)
    duration_days = models.PositiveIntegerField(default=30)
    max_voice_requests = models.PositiveIntegerField()
    has_mcp_access = models.BooleanField(default=False)
    features = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subscription_plans'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({'active' if self.is_active else 'inactive'})"


class Subscription(models.Model):
    workspace_id = models.PositiveBigIntegerField(db_index=True)
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name='subscriptions',
    )
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    voice_requests_used = models.PositiveIntegerField(default=0)
    created_by_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workspace_subscriptions'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['workspace_id'],
                condition=models.Q(is_active=True),
                name='unique_active_subscription_per_workspace',
            ),
        ]

    def __str__(self):
        return f"Workspace {self.workspace_id} -> {self.plan.name}"


class Payment(models.Model):
    PAYMENT_METHOD_VISA = 'visa'
    PAYMENT_METHOD_BANK = 'bank'

    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_VISA, 'Visa'),
        (PAYMENT_METHOD_BANK, 'Bank'),
    ]

    STATUS_SUCCESS = 'success'

    STATUS_CHOICES = [
        (STATUS_SUCCESS, 'Success'),
    ]

    user_id = models.PositiveBigIntegerField(db_index=True)
    workspace_id = models.PositiveBigIntegerField(db_index=True)
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.SET_NULL,
        related_name='payments',
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SUCCESS)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'subscription_payments'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.workspace_id} {self.amount} {self.payment_method}"


class FreeTierUsage(models.Model):
    workspace_id = models.PositiveBigIntegerField(unique=True)
    requests_used = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subscription_free_tier_usage'

    def __str__(self):
        return f"Workspace {self.workspace_id}: {self.requests_used}"
