from django.db import models
from django.utils import timezone
import uuid


class DataSource(models.Model):
    """Workspace-owned source definition. Dataset materializations live in Query."""

    ACTIVE = "active"
    DISABLED = "disabled"
    RETIRED = "retired"
    STATE_CHOICES = [(ACTIVE, "Active"), (DISABLED, "Disabled"), (RETIRED, "Retired")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    legacy_dataset_id = models.PositiveBigIntegerField(null=True, blank=True, unique=True)
    workspace_id = models.PositiveBigIntegerField(db_index=True)
    created_by = models.PositiveBigIntegerField()
    name = models.CharField(max_length=255)
    engine = models.CharField(max_length=32)
    connection_metadata = models.JSONField(default=dict, blank=True)
    selected_tables = models.JSONField(default=list, blank=True)
    transport = models.CharField(max_length=48, default="direct_secure_internet")
    configuration_version = models.PositiveIntegerField(default=1)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=ACTIVE)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "integration_data_sources"
        indexes = [models.Index(fields=["workspace_id", "state"], name="source_workspace_state_idx")]


class SourceCredential(models.Model):
    """Opaque, source-scoped encrypted credential; never serialized publicly."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name="credentials")
    version = models.PositiveIntegerField()
    key_version = models.CharField(max_length=8)
    ciphertext = models.TextField()
    state = models.CharField(max_length=16, default=CANDIDATE)
    created_at = models.DateTimeField(default=timezone.now)
    activated_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "integration_source_credentials"
        constraints = [models.UniqueConstraint(fields=["source", "version"], name="source_credential_version_uniq")]

    def __str__(self):
        return "Source credential"


class SourceExecution(models.Model):
    """Immutable authorization of one operation to one config and credential."""

    job_id = models.UUIDField(primary_key=True)
    source = models.ForeignKey(DataSource, on_delete=models.CASCADE)
    credential = models.ForeignKey(SourceCredential, on_delete=models.PROTECT)
    workspace_id = models.PositiveBigIntegerField()
    dataset_id = models.CharField(max_length=128)
    kind = models.CharField(max_length=16)
    engine = models.CharField(max_length=32)
    configuration_version = models.PositiveIntegerField()
    connection_metadata = models.JSONField(default=dict)
    transport = models.CharField(max_length=48)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "integration_source_executions"


class SourceCandidate(models.Model):
    """Replacement is inert until validation, a successful snapshot, and cutover."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.OneToOneField(DataSource, on_delete=models.CASCADE, related_name="candidate")
    engine = models.CharField(max_length=32)
    connection_metadata = models.JSONField(default=dict)
    selected_tables = models.JSONField(default=list)
    credential = models.ForeignKey(SourceCredential, on_delete=models.PROTECT)
    state = models.CharField(max_length=16, default="staged")
    validation_dataset_id = models.PositiveBigIntegerField(null=True)
    cutover_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "integration_source_candidates"


class SourceOperationBudget(models.Model):
    """Shared PostgreSQL admission counter for network-capable source actions."""

    workspace_id = models.PositiveBigIntegerField()
    actor_id = models.PositiveBigIntegerField()
    operation = models.CharField(max_length=24)
    window_start = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "integration_source_operation_budgets"
        constraints = [models.UniqueConstraint(
            fields=["workspace_id", "actor_id", "operation", "window_start"],
            name="source_operation_budget_uniq",
        )]
