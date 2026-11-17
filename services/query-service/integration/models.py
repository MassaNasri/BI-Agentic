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


class CdcPipeline(models.Model):
    """Integration-owned intent and observations; dataset binding is Query-owned.

    One pipeline selects one table. A source can have many pipelines, each with a
    separate live dataset, while existing snapshot datasets remain immutable.
    """
    DESIRED_STATES = tuple((s, s) for s in ("STREAMING", "PAUSED", "STOPPED"))
    STATES = tuple((s, s) for s in (
        "DISABLED", "PROVISIONING", "SNAPSHOTTING", "STREAMING", "PAUSING", "PAUSED",
        "DEGRADED", "FAILED", "STOPPING", "STOPPED", "RESEED_REQUIRED",
    ))
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT, related_name="cdc_pipelines")
    workspace_id = models.PositiveBigIntegerField(db_index=True)
    dataset_id = models.PositiveBigIntegerField(unique=True)
    table_schema = models.CharField(max_length=63)
    table_name = models.CharField(max_length=63)
    desired_state = models.CharField(max_length=24, choices=DESIRED_STATES, default="STREAMING")
    observed_state = models.CharField(max_length=24, choices=STATES, default="PROVISIONING")
    configuration_version = models.PositiveIntegerField(default=1)
    credential_version = models.PositiveIntegerField(default=0)
    primary_key = models.JSONField(default=list)
    columns = models.JSONField(default=list)
    schema_version = models.PositiveIntegerField(default=1)
    generation = models.PositiveIntegerField(default=1)
    controller_lease_owner = models.UUIDField(null=True)
    controller_lease_until = models.DateTimeField(null=True)
    controller_fence = models.PositiveIntegerField(default=0)
    checkpoints = models.JSONField(default=dict)
    health = models.JSONField(default=dict)
    reconciliation = models.JSONField(default=dict)
    snapshot_signal = models.JSONField(default=dict)
    # Scoped to the current generation and reset only by explicit reseed.
    capture_slot_seen = models.BooleanField(default=False)
    capture_ready = models.BooleanField(default=False)
    reconcile_requested = models.BooleanField(default=False)
    error_code = models.CharField(max_length=64, blank=True)
    heartbeat_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "integration_cdc_pipelines"
        constraints = [models.UniqueConstraint(
            fields=["source", "table_schema", "table_name"], name="cdc_source_table_uniq",
        ), models.CheckConstraint(
            check=models.Q(desired_state__in=["STREAMING", "PAUSED", "STOPPED"]),
            name="cdc_desired_state_valid",
        )]


class CdcGeneration(models.Model):
    """Retained physical lineage for one Integration-owned CDC pipeline epoch."""

    STATES = tuple((state, state) for state in (
        "ACTIVE", "CANDIDATE", "SUPERSEDED", "FAILED", "RESEED_REQUIRED"))
    pipeline = models.ForeignKey(CdcPipeline, on_delete=models.PROTECT, related_name="generations")
    number = models.PositiveIntegerField()
    state = models.CharField(max_length=24, choices=STATES)
    workspace_id = models.PositiveBigIntegerField()
    source_id = models.UUIDField()
    dataset_id = models.PositiveBigIntegerField()
    table_schema = models.CharField(max_length=63)
    table_name = models.CharField(max_length=63)
    schema_version = models.PositiveIntegerField(default=1)
    columns = models.JSONField(default=list)
    primary_key = models.JSONField(default=list)
    checkpoints = models.JSONField(default=dict)
    snapshot_signal = models.JSONField(default=dict)
    previous_number = models.PositiveIntegerField(null=True)
    reason = models.CharField(max_length=64, blank=True)
    cutover_phase = models.CharField(max_length=24, default="NONE")
    validation_certificate = models.JSONField(default=dict)
    reconciliation_attempt = models.JSONField(default=dict)
    candidate_ready_at = models.DateTimeField(null=True)
    cutover_attempted_at = models.DateTimeField(null=True)
    query_bound_at = models.DateTimeField(null=True)
    failed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(default=timezone.now)
    superseded_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "integration_cdc_generations"
        constraints = [models.UniqueConstraint(
            fields=["pipeline", "number"], name="cdc_generation_number_uniq"),
            models.UniqueConstraint(fields=["pipeline"], condition=models.Q(state="ACTIVE"),
                                    name="cdc_one_active_generation"),
            models.UniqueConstraint(fields=["pipeline"], condition=models.Q(state="CANDIDATE"),
                                    name="cdc_one_candidate_generation")]


class CdcAudit(models.Model):
    pipeline = models.ForeignKey(CdcPipeline, on_delete=models.PROTECT)
    workspace_id = models.PositiveBigIntegerField(null=True)
    source_id = models.UUIDField(null=True)
    dataset_id = models.PositiveBigIntegerField(null=True)
    actor_id = models.PositiveBigIntegerField()
    action = models.CharField(max_length=24)
    previous_desired_state = models.CharField(max_length=24, blank=True)
    previous_observed_state = models.CharField(max_length=24, blank=True)
    new_desired_state = models.CharField(max_length=24, blank=True)
    new_observed_state = models.CharField(max_length=24, blank=True)
    result_code = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "integration_cdc_audit"
