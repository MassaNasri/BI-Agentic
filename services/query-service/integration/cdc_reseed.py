"""Integration generation lifecycle and recoverable Query cutover.

The Query Dataset is the authority during a cross-owner cutover. No physical
resource name or generation number is accepted from an operator request.
"""
import json
import os
from datetime import datetime, timedelta
from django.db import transaction
from django.utils import timezone
from bi_platform_shared.cdc_contract import CdcError, Scope
from bi_platform_shared.db_ownership import integration_atomic_alias
from database.cdc import (CdcDatasetBindingError, _assert_current_view_ready,
                          candidate_binding_state, cutover_candidate_binding,
                          validate_live_dataset_binding, publish_live_dataset)
from database.models import Database
from database.utils import ClickHouseClient, quote_clickhouse_string
from .credentials import active_credential
from .models import CdcAudit, CdcGeneration, CdcPipeline, DataSource


REASONS = {"legacy_storage", "schema_incompatible", "slot_lost", "operator_reseed"}


def scope_for_number(pipeline, number):
    credential_version = pipeline.source.credentials.filter(
        state="active").values_list("version", flat=True).first() or 0
    return Scope(pipeline.workspace_id, str(pipeline.source_id), str(pipeline.pk),
                 pipeline.dataset_id, pipeline.table_schema, pipeline.table_name,
                 number, pipeline.source.configuration_version, credential_version)


def audit(pipeline, actor, action, code):
    return CdcAudit.objects.create(
        pipeline=pipeline, workspace_id=pipeline.workspace_id, source_id=pipeline.source_id,
        dataset_id=pipeline.dataset_id, actor_id=actor, action=action, result_code=code,
        previous_desired_state=pipeline.desired_state,
        previous_observed_state=pipeline.observed_state,
        new_desired_state=pipeline.desired_state,
        new_observed_state=pipeline.observed_state)


def create_candidate(source, pipeline_id, actor, reason):
    if reason not in REASONS:
        raise CdcError("CDC_RESEED_REASON_INVALID")
    with transaction.atomic(using=integration_atomic_alias()):
        source = DataSource.objects.select_for_update().get(pk=source.pk)
        p = CdcPipeline.objects.select_for_update().get(
            pk=pipeline_id, source=source, workspace_id=source.workspace_id)
        dataset = Database.objects.filter(pk=p.dataset_id).first()
        if dataset is None:
            raise CdcError("CDC_DATASET_BINDING_INVALID")
        validate_live_dataset_binding(dataset, source, p.table_schema, p.table_name)
        if source.state != DataSource.ACTIVE or source.engine != "postgres":
            raise CdcError("CDC_SOURCE_UNAVAILABLE")
        active_credential(source)
        existing = CdcGeneration.objects.select_for_update().filter(
            pipeline=p, state="CANDIDATE").first()
        if existing:
            audit(p, actor, "reseed", "CDC_IDEMPOTENT")
            return p, existing, False
        old = CdcGeneration.objects.select_for_update().filter(
            pipeline=p, state__in=["ACTIVE", "RESEED_REQUIRED"]).order_by("-number").first()
        if old is None or p.generation != old.number and not CdcGeneration.objects.filter(
                pipeline=p, number=p.generation, state="FAILED").exists():
            raise CdcError("CDC_RESEED_UNAVAILABLE")
        number = max(CdcGeneration.objects.filter(pipeline=p).values_list("number", flat=True)) + 1
        candidate = CdcGeneration.objects.create(
            pipeline=p, number=number, state="CANDIDATE", previous_number=old.number,
            workspace_id=p.workspace_id, source_id=p.source_id, dataset_id=p.dataset_id,
            table_schema=p.table_schema, table_name=p.table_name, reason=reason)
        p.generation = number
        p.desired_state, p.observed_state = "STREAMING", "PROVISIONING"
        p.credential_version = 0
        p.columns, p.primary_key, p.checkpoints = [], [], {}
        p.schema_version = 1
        p.snapshot_signal, p.health, p.reconciliation = {}, {}, {}
        p.capture_slot_seen, p.capture_ready = False, False
        p.error_code, p.reconcile_requested = "", False
        p.controller_lease_owner, p.controller_lease_until = None, None
        p.controller_fence += 1
        p.save()
        audit(p, actor, "reseed", "CDC_ACCEPTED")
        return p, candidate, True


def abort_candidate(source, pipeline_id, actor):
    with transaction.atomic(using=integration_atomic_alias()):
        p = CdcPipeline.objects.select_for_update().get(
            pk=pipeline_id, source=source, workspace_id=source.workspace_id)
        candidate = CdcGeneration.objects.select_for_update().filter(
            pipeline=p, number=p.generation, state__in=["CANDIDATE", "FAILED"]).first()
        if candidate is None or candidate.cutover_phase not in {"NONE", "READY"}:
            raise CdcError("CDC_ABORT_UNAVAILABLE")
        if candidate.state == "CANDIDATE":
            candidate.state, candidate.reason, candidate.failed_at = "FAILED", "CDC_CANDIDATE_ABORTED", timezone.now()
            candidate.save(update_fields=["state", "reason", "failed_at"])
            p.desired_state, p.observed_state = "STOPPED", "STOPPING"
            p.controller_lease_owner, p.controller_lease_until = None, None
            p.controller_fence += 1
            p.save()
            audit(p, actor, "abort", "CDC_CANDIDATE_ABORTED")
        return p, candidate


def _candidate_prerequisites(p, candidate):
    if (candidate.state != "CANDIDATE" or candidate.number != p.generation
            or candidate.previous_number is None
            or candidate.workspace_id != p.workspace_id or candidate.source_id != p.source_id
            or candidate.dataset_id != p.dataset_id
            or candidate.table_schema != p.table_schema or candidate.table_name != p.table_name
            or p.source.state != DataSource.ACTIVE or p.desired_state != "STREAMING"
            or p.observed_state != "STREAMING" or p.error_code
            or not p.columns or not p.primary_key
            or not p.health.get("slot_active") or not p.capture_ready
            or p.snapshot_signal.get("status") != "COMPLETED"
            or not (any(key.startswith("load:") for key in p.checkpoints)
                    or p.snapshot_signal.get("completed") is True)):
        raise CdcError("CDC_CANDIDATE_NOT_READY")
    active_credential(p.source)
    dataset = Database.objects.filter(pk=p.dataset_id).first()
    if dataset is None:
        raise CdcError("CDC_DATASET_BINDING_INVALID")
    scope = scope_for_number(p, candidate.number)
    _assert_current_view_ready(scope, dataset.clickhouse_database, p.columns, p.primary_key)
    return scope


def issue_local_certificate(pipeline_id, actor=0):
    """Isolated acceptance only. D5-R2 must supply the real watermark issuer."""
    if os.getenv("APP_ENV") != "test" and not (
            os.getenv("APP_ENV") == "development"
            and os.getenv("CDC_D5_R1_LOCAL_CERTIFICATE") == "1"):
        raise CdcError("CDC_CERTIFICATE_UNAVAILABLE")
    with transaction.atomic(using=integration_atomic_alias()):
        p = CdcPipeline.objects.select_for_update().select_related("source").get(pk=pipeline_id)
        candidate = CdcGeneration.objects.select_for_update().get(
            pipeline=p, number=p.generation, state="CANDIDATE")
        # A zero-row candidate can have a durable completion notification but
        # no later row callback to advance the observed state. Its exact D4
        # physical proof still runs in _candidate_prerequisites below.
        if (p.observed_state == "SNAPSHOTTING"
                and p.snapshot_signal.get("status") == "COMPLETED"
                and p.snapshot_signal.get("completed") is True
                and p.health.get("slot_active") and p.columns and p.primary_key):
            p.observed_state = "STREAMING"
            p.save(update_fields=["observed_state", "updated_at"])
        scope = _candidate_prerequisites(p, candidate)
        certificate = {"kind": "local_exact_v1", "generation": candidate.number,
                       "scope_token": scope.token, "schema_version": p.schema_version,
                       "loader_checkpoint": p.checkpoints,
                       "issued_at": timezone.now().isoformat()}
        candidate.validation_certificate = certificate
        candidate.candidate_ready_at = timezone.now()
        candidate.cutover_phase = "READY"
        candidate.columns, candidate.primary_key = p.columns, p.primary_key
        candidate.save(update_fields=["validation_certificate", "candidate_ready_at",
                                      "cutover_phase", "columns", "primary_key"])
        audit(p, actor, "validate", "CDC_CANDIDATE_READY")
        return certificate


def issue_watermark_certificate(p, candidate, scope, proof, actor=0):
    """Called only from the authenticated, leased Data Platform controller."""
    if not isinstance(proof, dict) or set(proof) != {
            "attempt_id", "source_lsn", "capture_lsn", "stage_ends", "checkpoints",
            "source_count", "query_count", "chunk_count", "mismatch_chunks",
            "duration_ms", "query_duration_ms"}:
        raise CdcError("CDC_RECONCILIATION_PROOF_INVALID")
    source_lsn, capture_lsn = proof["source_lsn"], proof["capture_lsn"]
    attempt = candidate.reconciliation_attempt
    if (type(source_lsn) is not int or source_lsn <= 0
            or attempt.get("id") != proof["attempt_id"]
            or attempt.get("generation") != candidate.number
            or attempt.get("state") != "COMPARING"
            or attempt.get("source_lsn") != source_lsn
            or attempt.get("stage_ends") != proof["stage_ends"]
            or type(capture_lsn) is not int or capture_lsn < source_lsn
            or any(type(proof[k]) is not int or proof[k] < 0 for k in
                   ("source_count", "query_count", "chunk_count", "duration_ms", "query_duration_ms"))
            or max(proof["source_count"], proof["query_count"]) > 10_000
            or not isinstance(proof["mismatch_chunks"], list)
            or any(type(i) is not int or i < 0 or i > 20 for i in proof["mismatch_chunks"])):
        raise CdcError("CDC_RECONCILIATION_PROOF_INVALID")
    ends = proof["stage_ends"]
    if not isinstance(ends, dict) or set(ends) != {"normalize", "transform", "load"}:
        raise CdcError("CDC_RECONCILIATION_PROOF_INVALID")
    for stage, partitions in ends.items():
        if not isinstance(partitions, dict) or not partitions:
            raise CdcError("CDC_RECONCILIATION_PROOF_INVALID")
        for partition, end in partitions.items():
            if (not str(partition).isdigit() or type(end) is not int or end < 0
                    or p.checkpoints.get(f"{stage}:{partition}", {}).get("offset", -1) < end - 1):
                raise CdcError("CDC_RECONCILIATION_WATERMARK_BEHIND")
    # A Loader callback between candidate digest and certificate issuance can
    # change the current view. Bind the certificate only to the exact durable
    # checkpoint that was present when the digest barrier was sampled.
    if proof["checkpoints"] != p.checkpoints:
        raise CdcError("CDC_RECONCILIATION_CHECKPOINT_MOVED")
    if (p.observed_state == "SNAPSHOTTING"
            and p.snapshot_signal.get("status") == "COMPLETED"
            and p.snapshot_signal.get("completed") is True
            and p.health.get("slot_active") and p.columns and p.primary_key):
        p.observed_state = "STREAMING"
        p.save(update_fields=["observed_state", "updated_at"])
    _candidate_prerequisites(p, candidate)
    if candidate.cutover_phase not in {"NONE", "READY"}:
        raise CdcError("CDC_CANDIDATE_NOT_READY")
    mismatch = (proof["source_count"] != proof["query_count"]
                or bool(proof["mismatch_chunks"]))
    certificate = {
        "kind": "watermark_reconciliation.v1", "status": "MISMATCH" if mismatch else "MATCH",
        "attempt_id": proof["attempt_id"],
        "workspace_id": p.workspace_id, "source_id": str(p.source_id),
        "pipeline_id": str(p.pk), "dataset_id": p.dataset_id,
        "generation": candidate.number, "scope_token": scope.token,
        "schema_version": p.schema_version, "columns": p.columns,
        "primary_key": p.primary_key, "source_lsn": source_lsn,
        "capture_observed_lsn": capture_lsn,
        "loader_applied_through_lsn": source_lsn,
        "loader_watermark_method": "capture_flush_and_stage_end_offsets",
        "loader_checkpoint": p.checkpoints, "stage_ends": ends,
        "query_generation": candidate.number,
        "query_view": f"cdc_{scope.token}_current",
        "source_row_count": proof["source_count"],
        "query_row_count": proof["query_count"],
        "chunk_count": proof["chunk_count"], "digest_algorithm": "SHA-256",
        "mismatch_chunks": proof["mismatch_chunks"][:20],
        "duration_ms": proof["duration_ms"],
        "query_duration_ms": proof["query_duration_ms"],
        "issued_at": timezone.now().isoformat(),
    }
    candidate.validation_certificate = certificate
    attempt["state"] = certificate["status"]
    attempt["updated_at"] = timezone.now().isoformat()
    candidate.reconciliation_attempt = attempt
    candidate.cutover_phase = "NONE" if mismatch else "READY"
    candidate.candidate_ready_at = None if mismatch else timezone.now()
    candidate.columns, candidate.primary_key = p.columns, p.primary_key
    candidate.save(update_fields=["validation_certificate", "reconciliation_attempt",
                                  "cutover_phase", "candidate_ready_at",
                                  "columns", "primary_key"])
    p.reconciliation = {"status": certificate["status"], "generation": candidate.number,
                        "source_lsn": source_lsn, "loader_lsn": source_lsn,
                        "query_generation": candidate.number,
                        "source_count": proof["source_count"],
                        "destination_count": proof["query_count"],
                        "mismatch_count": len(proof["mismatch_chunks"]),
                        "duration_ms": proof["duration_ms"]}
    p.reconcile_requested = False
    p.save(update_fields=["reconciliation", "reconcile_requested", "updated_at"])
    audit(p, actor, "reconcile", "CDC_RECONCILIATION_MISMATCH" if mismatch else "CDC_RECONCILIATION_MATCH")
    return certificate


def _certificate_valid(p, candidate, scope, *, already_bound=False):
    cert = candidate.validation_certificate
    common = (isinstance(cert, dict) and cert.get("generation") == candidate.number
              and cert.get("scope_token") == scope.token
              and cert.get("schema_version") == p.schema_version
              and cert.get("loader_checkpoint") == p.checkpoints)
    if not common:
        return False
    if cert.get("kind") == "local_exact_v1":
        return os.getenv("APP_ENV") == "test" or (
            os.getenv("APP_ENV") == "development"
            and os.getenv("CDC_D5_R1_LOCAL_CERTIFICATE") == "1")
    if cert.get("kind") != "watermark_reconciliation.v1":
        return False
    try:
        issued = datetime.fromisoformat(cert["issued_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return (cert.get("status") == "MATCH"
            and cert.get("attempt_id") == candidate.reconciliation_attempt.get("id")
            and candidate.reconciliation_attempt.get("state") == "MATCH"
            and cert.get("workspace_id") == p.workspace_id
            and cert.get("source_id") == str(p.source_id)
            and cert.get("pipeline_id") == str(p.pk)
            and cert.get("dataset_id") == p.dataset_id
            and cert.get("columns") == p.columns
            and cert.get("primary_key") == p.primary_key
            and type(cert.get("source_lsn")) is int and cert["source_lsn"] > 0
            and type(cert.get("capture_observed_lsn")) is int
            and cert["capture_observed_lsn"] >= cert["source_lsn"]
            and cert.get("loader_applied_through_lsn") == cert["source_lsn"]
            and cert.get("loader_watermark_method") == "capture_flush_and_stage_end_offsets"
            and cert.get("query_generation") == candidate.number
            and cert.get("query_view") == f"cdc_{scope.token}_current"
            and cert.get("source_row_count") == cert.get("query_row_count")
            and cert.get("mismatch_chunks") == []
            and timezone.now() - issued <= timedelta(seconds=60))


def cutover_candidate(pipeline_id, actor=0, fault=None):
    """Three durable steps: Integration intent, Query CAS, Integration finish."""
    with transaction.atomic(using=integration_atomic_alias()):
        p = CdcPipeline.objects.select_for_update().select_related("source").get(pk=pipeline_id)
        current = CdcGeneration.objects.select_for_update().get(pipeline=p, number=p.generation)
        if current.state == "ACTIVE" and current.cutover_phase == "COMPLETE":
            scope = scope_for_number(p, current.number)
            dataset = Database.objects.filter(pk=p.dataset_id).first()
            if (dataset is None or dataset.etl_status != "completed"
                    or dataset.cdc_generation != current.number
                    or dataset.clickhouse_table_name != f"cdc_{scope.token}_current"):
                raise CdcError("CDC_DATASET_BINDING_INVALID")
            return p
        candidate = CdcGeneration.objects.select_for_update().get(
            pipeline=p, number=p.generation, state="CANDIDATE")
        old = CdcGeneration.objects.select_for_update().get(
            pipeline=p, number=candidate.previous_number, state__in=["ACTIVE", "RESEED_REQUIRED"])
        scope = scope_for_number(p, candidate.number)
        old_scope = scope_for_number(p, old.number)
        binding = candidate_binding_state(p, old_scope, scope)
        if binding != "candidate":
            _candidate_prerequisites(p, candidate)
        else:
            dataset = Database.objects.get(pk=p.dataset_id)
            _assert_current_view_ready(scope, dataset.clickhouse_database,
                                       candidate.columns, candidate.primary_key)
        if not _certificate_valid(p, candidate, scope, already_bound=binding == "candidate"):
            raise CdcError("CDC_RECONCILIATION_CERTIFICATE_REQUIRED")
        if candidate.cutover_phase not in {"READY", "PENDING", "QUERY_BOUND"}:
            raise CdcError("CDC_CANDIDATE_NOT_READY")
        if candidate.cutover_phase == "READY":
            candidate.cutover_phase = "PENDING"
            candidate.cutover_attempted_at = timezone.now()
            candidate.save(update_fields=["cutover_phase", "cutover_attempted_at"])
            audit(p, actor, "cutover", "CDC_CUTOVER_PENDING")
    if fault == "before_query":
        raise RuntimeError("CDC_TEST_CRASH_BEFORE_QUERY")
    if binding != "candidate":
        current_source = DataSource.objects.get(pk=p.source_id)
        if current_source.state != DataSource.ACTIVE:
            raise CdcError("CDC_SOURCE_UNAVAILABLE")
        active_credential(current_source)
        cutover_candidate_binding(p, old_scope, scope, p.columns, p.primary_key)
    if fault == "after_query":
        raise RuntimeError("CDC_TEST_CRASH_AFTER_QUERY")
    with transaction.atomic(using=integration_atomic_alias()):
        p = CdcPipeline.objects.select_for_update().select_related("source").get(pk=pipeline_id)
        candidate = CdcGeneration.objects.select_for_update().get(
            pipeline=p, number=scope.generation, state="CANDIDATE")
        old = CdcGeneration.objects.select_for_update().get(
            pipeline=p, number=old_scope.generation, state__in=["ACTIVE", "RESEED_REQUIRED"])
        if candidate_binding_state(p, old_scope, scope) != "candidate":
            raise CdcError("CDC_CUTOVER_INCOMPLETE")
        candidate.cutover_phase, candidate.query_bound_at = "QUERY_BOUND", timezone.now()
        candidate.save(update_fields=["cutover_phase", "query_bound_at"])
        audit(p, actor, "cutover", "CDC_QUERY_BOUND")
        old.state, old.superseded_at = "SUPERSEDED", timezone.now()
        old.save(update_fields=["state", "superseded_at"])
        candidate.state, candidate.cutover_phase = "ACTIVE", "COMPLETE"
        candidate.save(update_fields=["state", "cutover_phase"])
        audit(p, actor, "cutover", "CDC_ACTIVE_UPDATED")
    return p


def recover_pending_cutovers():
    """Called once by a starting controller; Query binding decides recovery."""
    ids = list(CdcGeneration.objects.filter(
        state="CANDIDATE", cutover_phase__in=["PENDING", "QUERY_BOUND"]
    ).values_list("pipeline_id", flat=True)[:100])
    for pipeline_id in ids:
        try:
            cutover_candidate(pipeline_id)
        except (CdcError, CdcDatasetBindingError, DataSource.DoesNotExist,
                CdcPipeline.DoesNotExist, CdcGeneration.DoesNotExist):
            # Stopped/retired candidates remain visible for operator repair.
            continue


def classify_orphans(p):
    """Read-only repair advice; physical cleanup always remains operator work."""
    findings = []
    dataset = Database.objects.filter(pk=p.dataset_id).first()
    generations = list(CdcGeneration.objects.filter(pipeline=p).order_by("number"))
    if dataset is None:
        findings.append({"code": "CDC_DATASET_MISSING", "repair": "manual_operator_review"})
    else:
        try:
            validate_live_dataset_binding(dataset, p.source, p.table_schema, p.table_name)
        except CdcDatasetBindingError:
            findings.append({"code": "CDC_DATASET_BINDING_INVALID",
                             "repair": "manual_operator_review"})
    if not generations or not any(g.number == p.generation for g in generations):
        findings.append({"code": "CDC_GENERATION_MISSING", "repair": "manual_operator_review"})
    candidates = [g for g in generations if g.state == "CANDIDATE"]
    if len(candidates) > 1 or candidates and candidates[0].number != p.generation:
        findings.append({"code": "CDC_CANDIDATE_ORPHAN", "repair": "manual_operator_review"})
    if any(g.state == "FAILED" for g in generations):
        findings.append({"code": "CDC_FAILED_GENERATION_RETAINED",
                         "repair": "manual_operator_review"})
    if (dataset and candidates and candidates[0].number == p.generation
            and p.columns and p.primary_key):
        scope = scope_for_number(p, p.generation)
        versions = f"cdc_{scope.token}_versions"
        current = f"cdc_{scope.token}_current"
        try:
            result = ClickHouseClient().execute_query(
                "SELECT name FROM system.tables WHERE database = "
                f"{quote_clickhouse_string(dataset.clickhouse_database)} AND name IN ("
                f"{quote_clickhouse_string(versions)}, {quote_clickhouse_string(current)}) "
                "FORMAT JSONEachRow")
            if not result["success"]:
                raise CdcDatasetBindingError("CDC_PUBLICATION_NOT_READY")
            names = {json.loads(line)["name"] for line in result["data"].splitlines()
                     if line}
            if not names:
                safe_retry = (not p.checkpoints and p.snapshot_signal.get("status")
                              not in {"STARTED", "SCANNED", "COMPLETED"})
                findings.append({"code": "CDC_CANDIDATE_STORAGE_MISSING",
                                 "repair": "recoverable_retry" if safe_retry
                                 else "manual_operator_review"})
            elif names != {versions, current}:
                findings.append({"code": "CDC_CANDIDATE_STORAGE_PARTIAL",
                                 "repair": "manual_operator_review"})
            else:
                _assert_current_view_ready(scope, dataset.clickhouse_database,
                                           p.columns, p.primary_key)
        except Exception:
            findings.append({"code": "CDC_CANDIDATE_STORAGE_UNVERIFIED",
                             "repair": "manual_operator_review"})
    if dataset and dataset.cdc_generation is not None:
        bound = [g for g in generations if g.number == dataset.cdc_generation]
        if not bound:
            findings.append({"code": "CDC_QUERY_GENERATION_MISSING", "repair": "manual_operator_review"})
        elif bound[0].state == "CANDIDATE" and bound[0].cutover_phase == "PENDING":
            findings.append({"code": "CDC_QUERY_BOUND_PENDING", "repair": "recoverable_retry"})
        elif bound[0].state != "ACTIVE":
            findings.append({"code": "CDC_QUERY_AUTHORITY_MISMATCH", "repair": "manual_operator_review"})
        elif dataset.etl_status != "completed":
            findings.append({"code": "CDC_QUERY_PENDING_ACTIVE", "repair": "recoverable_retry"})
    return findings


def repair_active_publication(pipeline_id):
    """Retry a verified active view publication after a partial Query write."""
    with transaction.atomic(using=integration_atomic_alias()):
        p = CdcPipeline.objects.select_for_update().select_related("source").get(pk=pipeline_id)
        if not CdcGeneration.objects.filter(
                pipeline=p, number=p.generation, state="ACTIVE").exists():
            raise CdcError("CDC_STALE_CALLBACK")
        dataset = Database.objects.filter(pk=p.dataset_id).first()
        scope = scope_for_number(p, p.generation)
        if (dataset is None or dataset.cdc_generation != p.generation
                or dataset.clickhouse_table_name != f"cdc_{scope.token}_current"):
            raise CdcError("CDC_DATASET_BINDING_INVALID")
        publish_live_dataset(p, scope)
        audit(p, 0, "repair", "CDC_QUERY_BOUND")
