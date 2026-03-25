from django.db import models
from django.utils import timezone


class NotificationDispatchLog(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SKIPPED, 'Skipped'),
    ]

    event_type = models.CharField(max_length=100)
    event_key = models.CharField(max_length=255)
    recipient_email = models.EmailField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'notification_dispatch_logs'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['event_type', 'event_key', 'recipient_email'],
                name='notification_dispatch_unique_event_recipient',
            ),
        ]

    def __str__(self):
        return f"{self.event_type} -> {self.recipient_email} ({self.status})"


class UserRecord(models.Model):
    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    email = models.EmailField()
    role = models.CharField(max_length=20)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'users'


class WorkspaceRecord(models.Model):
    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(
        UserRecord,
        on_delete=models.DO_NOTHING,
        db_column='owner_id',
        related_name='owned_workspace_records',
    )

    class Meta:
        managed = False
        db_table = 'workspaces'


class WorkspaceMemberRecord(models.Model):
    id = models.BigIntegerField(primary_key=True)
    workspace = models.ForeignKey(
        WorkspaceRecord,
        on_delete=models.DO_NOTHING,
        db_column='workspace_id',
        related_name='member_records',
    )
    user = models.ForeignKey(
        UserRecord,
        on_delete=models.DO_NOTHING,
        db_column='user_id',
        related_name='workspace_member_records',
        null=True,
        blank=True,
    )
    invited_email = models.EmailField(null=True, blank=True)
    role = models.CharField(max_length=20)
    status = models.CharField(max_length=30)
    joined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'workspace_members'


class PlanRecord(models.Model):
    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=120)
    duration_days = models.PositiveIntegerField(default=30)

    class Meta:
        managed = False
        db_table = 'subscription_plans'


class SubscriptionRecord(models.Model):
    id = models.BigIntegerField(primary_key=True)
    workspace_id = models.BigIntegerField()
    plan = models.ForeignKey(
        PlanRecord,
        on_delete=models.DO_NOTHING,
        db_column='plan_id',
        related_name='subscription_records',
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'workspace_subscriptions'
