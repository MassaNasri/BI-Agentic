"""Durable CDC control plane. Network execution remains in Data Platform."""
import os
import hmac
import uuid
import logging
from datetime import timedelta
from django.db import transaction, IntegrityError, DatabaseError
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView
from bi_platform_shared.db_ownership import integration_atomic_alias
from bi_platform_shared.secret_delivery import read_secret
from bi_platform_shared.cdc_contract import Scope, identifier, CdcError
from database.cdc import (CdcDatasetBindingError, create_live_dataset,
                          publish_live_dataset, validate_live_dataset_binding)
from database.models import Database
from .credentials import active_credential, CredentialUnavailable
from .models import CdcPipeline, CdcGeneration, DataSource
from .cdc_lifecycle import command_transition, record_command
from .views import SourceDetailView
from .scope import principal_user_id
from .limits import admit_source_operation
from .cdc_reseed import (create_candidate, abort_candidate, classify_orphans,
                         scope_for_number, recover_pending_cutovers,
                         issue_watermark_certificate)

log = logging.getLogger(__name__)


def pipeline_scope(p):
    credential_version = p.source.credentials.filter(
        state="active").values_list("version", flat=True).first() or 0
    return Scope(p.workspace_id, str(p.source_id), str(p.pk), p.dataset_id,
                 p.table_schema, p.table_name, p.generation,
                 p.source.configuration_version, credential_version)


def _bound_dataset(p, source):
    dataset = Database.objects.filter(pk=p.dataset_id).first()
    if dataset is None:
        raise CdcDatasetBindingError("CDC_DATASET_BINDING_INVALID")
    return validate_live_dataset_binding(dataset, source, p.table_schema, p.table_name)


def _compensate_new_dataset(dataset):
    # The Query and Integration roles may use separate transactions. Remove
    # only this request's still-pending orphan, never a published binding.
    if dataset is None:
        return
    try:
        if not CdcPipeline.objects.filter(dataset_id=dataset.pk).exists():
            Database.objects.filter(pk=dataset.pk, source_kind="cdc", etl_status="pending",
                                    ingestion_job_id=dataset.ingestion_job_id).delete()
    except DatabaseError:
        # An incomplete Query dataset remains pending and cannot be queried.
        log.warning("cdc_pending_dataset_compensation_unavailable dataset=%s", dataset.pk)


def public_pipeline(p):
    health = {key: p.health[key] for key in (
        "slot_active", "retained_wal_bytes", "wal_warning", "capture_timestamp_ms") if key in p.health}
    captured = health.get('capture_timestamp_ms')
    health['capture_age_seconds'] = max(0, int(timezone.now().timestamp()-captured/1000)) if captured else None
    health['capture_status'] = 'UNKNOWN' if not captured else 'RECENT' if health['capture_age_seconds'] <= 30 else 'STALE_OR_IDLE'
    stale = p.desired_state == 'STREAMING' and p.observed_state == 'STREAMING' and health['capture_status'] != 'RECENT'
    query_generation = Database.objects.filter(pk=p.dataset_id).values_list(
        "cdc_generation", flat=True).first()
    active = CdcGeneration.objects.filter(pipeline=p, state="ACTIVE").order_by("-number").first()
    candidate = CdcGeneration.objects.filter(pipeline=p, state="CANDIDATE").first()
    return {"id": str(p.pk), "source_id": str(p.source_id), "dataset_id": p.dataset_id,
            "generation": p.generation, "active_generation": active.number if active else None,
            "candidate_generation": candidate.number if candidate else None,
            "candidate_capture_ready": p.capture_ready if candidate else None,
            "query_generation": query_generation,
            "certificate_status": candidate.validation_certificate.get("status") if candidate else None,
            "reconciliation_attempt": ({key: candidate.reconciliation_attempt.get(key)
                for key in ("id", "state", "source_lsn", "failure_code")}
                if candidate and candidate.reconciliation_attempt else {}),
            "last_successful_cutover_at": active.query_bound_at if active else None,
            "table": {"schema": p.table_schema, "name": p.table_name},
            "desired_state": p.desired_state, "observed_state": 'DEGRADED' if stale else p.observed_state,
            "error_code": 'CDC_CAPTURE_STALE' if stale else p.error_code, "heartbeat_at": p.heartbeat_at,
            "schema_version": p.schema_version,
            "reconciliation": p.reconciliation if _valid_reconciliation(p.reconciliation) else {},
            "health": health}


def _controller_state_allowed(p, state):
    if state not in dict(CdcPipeline.STATES):
        return False
    if p.observed_state == "RESEED_REQUIRED":
        return True  # The sticky failure is preserved below.
    allowed = {
        "STREAMING": {"PROVISIONING", "SNAPSHOTTING", "DEGRADED", "FAILED"},
        "PAUSED": {"PAUSING", "PAUSED"},
        "STOPPED": {"STOPPING", "STOPPED"},
    }
    if state == "STREAMING":
        # A paused candidate resumes through PROVISIONING. Its original
        # generation-specific Loader checkpoint remains durable, so the
        # controller may restore STREAMING after rechecking capture and slot.
        durable = (any(key.startswith('load:') for key in p.checkpoints)
                   or p.snapshot_signal.get('completed') is True)
        return (p.desired_state == "STREAMING" and (
            p.observed_state == "STREAMING" or
            (p.observed_state in {"PROVISIONING", "SNAPSHOTTING"} and durable)))
    return state in allowed.get(p.desired_state, set())


def _valid_reconciliation(value):
    if isinstance(value, dict) and set(value) == {
            "status", "generation", "source_lsn", "loader_lsn", "query_generation",
            "source_count", "destination_count", "mismatch_count", "duration_ms"}:
        return (value["status"] in {"MATCH", "MISMATCH"}
                and all(type(value[key]) is int and value[key] >= 0 for key in
                        set(value) - {"status"}))
    if not isinstance(value, dict) or set(value) != {
            "status", "source_count", "destination_count", "limit", "duration_ms",
            "checked_at", "consistency"}:
        return False
    if value["status"] not in {"MATCH", "MISMATCH"} or value["consistency"] != "bounded_observation_requires_quiescent_source":
        return False
    if any(type(value[k]) is not int or value[k] < 0 for k in
           ("source_count", "destination_count", "limit", "duration_ms")):
        return False
    return value["limit"] <= 10000 and isinstance(value["checked_at"], str) and len(value["checked_at"]) <= 40


def _valid_stage_ends(value):
    if not isinstance(value, dict) or set(value) - {"normalize", "transform", "load"}:
        return False
    return all(isinstance(partitions, dict) and len(partitions) <= 16 and all(
        isinstance(partition, str) and partition.isdigit() and len(partition) <= 3
        and type(end) is int and end >= 0
        for partition, end in partitions.items()) for partitions in value.values())


def _next_snapshot_signal(previous, signal):
    """Fold ordered, connector-scoped notifications into durable evidence."""
    base = {"type", "offset", "partition", "id", "timestamp_ms"}
    if (not isinstance(signal, dict)
            or set(signal) not in (base, base | {"empty"})
            or signal.get("type") not in {"STARTED", "TABLE_SCAN_COMPLETED",
                                          "COMPLETED", "ABORTED", "SKIPPED"}
            or type(signal.get("offset")) is not int or signal["offset"] < 0
            or type(signal.get("partition")) is not int or signal["partition"] != 0
            or type(signal.get("timestamp_ms")) is not int
            or signal["timestamp_ms"] <= 0):
        raise CdcError("CDC_SNAPSHOT_NOTIFICATION_INVALID")
    try:
        uuid.UUID(signal["id"])
    except (KeyError, ValueError, TypeError):
        raise CdcError("CDC_SNAPSHOT_NOTIFICATION_INVALID") from None
    if signal["offset"] <= previous.get("offset", -1):
        return previous
    kind = signal["type"]
    if previous.get("status") == "COMPLETED" and kind == "SKIPPED":
        # Debezium reports SKIPPED when an already-snapshotted connector
        # restarts. It advances the notification offset, not the durable
        # completion proof for this generation.
        return {**previous, "offset": signal["offset"]}
    if kind == "STARTED" and set(signal) == base:
        return {"status": "STARTED", "offset": signal["offset"],
                "started_at_ms": signal["timestamp_ms"], "empty_scan": False,
                "completed": False, "notification_id": signal["id"]}
    if kind == "TABLE_SCAN_COMPLETED" and set(signal) == base | {"empty"}:
        if (previous.get("status") != "STARTED"
                or type(signal["empty"]) is not bool):
            raise CdcError("CDC_SNAPSHOT_NOTIFICATION_INVALID")
        return {**previous, "status": "SCANNED", "offset": signal["offset"],
                "empty_scan": signal["empty"], "notification_id": signal["id"]}
    if kind == "COMPLETED" and set(signal) == base:
        if previous.get("status") != "SCANNED":
            raise CdcError("CDC_SNAPSHOT_NOTIFICATION_INVALID")
        return {**previous, "status": "COMPLETED", "offset": signal["offset"],
                "completed": bool(previous["empty_scan"]),
                "notification_id": signal["id"]}
    if kind in {"ABORTED", "SKIPPED"} and set(signal) == base:
        return {"status": kind, "offset": signal["offset"], "completed": False,
                "notification_id": signal["id"]}
    raise CdcError("CDC_SNAPSHOT_NOTIFICATION_INVALID")


class SourceCdcView(SourceDetailView):
    http_method_names = ["get", "post", "options"]

    def get(self, request, source_id, action=None):
        source, error = self._source(request, source_id)
        if error is not None:
            return error
        if action not in {None, "status"}:
            return Response({"error": {"code": "CDC_OPERATION_INVALID"}}, status=400)
        data = []
        for p in source.cdc_pipelines.all():
            item = public_pipeline(p)
            if action == "status":
                item["generations"] = [{"number": g.number, "state": g.state,
                                        "cutover_phase": g.cutover_phase, "reason": g.reason}
                                       for g in p.generations.order_by("number")]
                item["repair"] = classify_orphans(p)
            data.append(item)
        return Response({"success": True, "data": data})

    def post(self, request, source_id, action):
        source, error = self._source(request, source_id)
        if error is not None:
            return error
        if os.getenv("CDC_ENABLED") != "1" or os.getenv("APP_ENV") == "production":
            return Response({"error": {"code": "CDC_TRANSPORT_UNCERTIFIED"}}, status=503)
        actor = principal_user_id(request.user)
        if actor is None:
            return Response({"error": {"code": "INVALID_PRINCIPAL"}}, status=401)
        if not admit_source_operation(source.workspace_id, actor, "cdc"):
            return Response({"error": {"code": "SOURCE_RATE_LIMITED"}}, status=429)
        if action in {"reseed", "abort"}:
            expected = read_secret("CDC_RESEED_OPERATOR_KEY")
            supplied = request.headers.get("X-Cdc-Operator-Key", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                return Response({"error": {"code": "CDC_OPERATOR_DENIED"}}, status=403)
            allowed = {"pipeline_id", "intent", "reason"} if action == "reseed" else {"pipeline_id", "intent"}
            intent = "reseed" if action == "reseed" else "abort_candidate"
            if set(request.data) != allowed or request.data.get("intent") != intent:
                return Response({"error": {"code": "CDC_CONFIGURATION_INVALID"}}, status=400)
            try:
                pipeline_id = uuid.UUID(str(request.data["pipeline_id"]))
                if action == "reseed":
                    p, _, _ = create_candidate(source, pipeline_id, actor, request.data["reason"])
                else:
                    p, _ = abort_candidate(source, pipeline_id, actor)
            except (CdcPipeline.DoesNotExist, ValueError, TypeError):
                return Response({"error": {"code": "CDC_NOT_FOUND"}}, status=404)
            except (CdcError, CredentialUnavailable, CdcDatasetBindingError) as exc:
                code = exc.code if isinstance(exc, CdcError) else str(exc)
                return Response({"error": {"code": code}}, status=409)
            except DatabaseError:
                return Response({"error": {"code": "CDC_PERSISTENCE_UNAVAILABLE"}}, status=503)
            return Response({"success": True, "data": public_pipeline(p)}, status=202)
        created_dataset = None
        try:
            with transaction.atomic(using=integration_atomic_alias()):
                source = DataSource.objects.select_for_update().get(pk=source.pk)
                if action == "enable":
                    if set(request.data) != {"schema", "table"}:
                        raise CdcError("CDC_CONFIGURATION_INVALID")
                    schema, table = identifier(request.data["schema"]), identifier(request.data["table"])
                    if source.engine != "postgres" or source.state != DataSource.ACTIVE:
                        raise CdcError("CDC_SOURCE_UNAVAILABLE")
                    if not any((t.get("schema") or "public", t.get("name")) == (schema, table) for t in source.selected_tables):
                        raise CdcError("CDC_TABLE_NOT_SELECTED")
                    active_credential(source)
                    p = CdcPipeline.objects.select_for_update().filter(
                        source=source, table_schema=schema, table_name=table).first()
                    if p is None:
                        dataset, created = create_live_dataset(source, actor, schema, table)
                        if created:
                            created_dataset = dataset
                        p = CdcPipeline.objects.create(source=source, workspace_id=source.workspace_id,
                            dataset_id=dataset.pk, table_schema=schema, table_name=table)
                        CdcGeneration.objects.create(
                            pipeline=p, number=p.generation, state="ACTIVE",
                            workspace_id=p.workspace_id, source_id=p.source_id,
                            dataset_id=p.dataset_id, table_schema=schema, table_name=table)
                        result_code = "CDC_ACCEPTED"
                    else:
                        result_code = "CDC_IDEMPOTENT"
                    _bound_dataset(p, source)
                    if p.workspace_id != source.workspace_id:
                        raise CdcError("CDC_SCOPE_MISMATCH")
                    record_command(p, actor, action, p.desired_state, p.observed_state, result_code)
                else:
                    if set(request.data) != {"pipeline_id"}:
                        raise CdcError("CDC_CONFIGURATION_INVALID")
                    p = CdcPipeline.objects.select_for_update().filter(
                        pk=uuid.UUID(str(request.data["pipeline_id"])), source=source, workspace_id=source.workspace_id).first()
                    if p is None:
                        return Response({"error": {"code": "CDC_NOT_FOUND"}}, status=404)
                    _bound_dataset(p, source)
                    if action == "resume":
                        if source.state != DataSource.ACTIVE:
                            raise CdcError("CDC_SOURCE_UNAVAILABLE")
                        active_credential(source)
                    previous_desired, previous_observed = p.desired_state, p.observed_state
                    desired, observed, reconcile_requested, result_code = command_transition(p, action)
                    if action == "reconcile" and p.generation > 1 and not p.capture_ready:
                        raise CdcError("CDC_CAPTURE_NOT_READY")
                    p.desired_state, p.observed_state = desired, observed
                    p.reconcile_requested = reconcile_requested
                    p.save(update_fields=["desired_state", "observed_state", "reconcile_requested", "updated_at"])
                    if (action == "reconcile" and p.generation > 1
                            and result_code == "CDC_ACCEPTED"
                            and CdcGeneration.objects.filter(
                                pipeline=p, number=p.generation,
                                state="CANDIDATE").exists()):
                        generation = CdcGeneration.objects.select_for_update().filter(
                            pipeline=p, number=p.generation, state="CANDIDATE").first()
                        if generation is None:
                            raise CdcError("CDC_INVALID_TRANSITION")
                        now = timezone.now().isoformat()
                        generation.reconciliation_attempt = {
                            "id": str(uuid.uuid4()), "generation": p.generation,
                            "state": "REQUESTED", "source_lsn": 0, "stage_ends": {},
                            "requested_at": now, "updated_at": now, "failure_code": ""}
                        generation.validation_certificate = {}
                        generation.cutover_phase = "NONE"
                        generation.candidate_ready_at = None
                        generation.save(update_fields=["reconciliation_attempt", "validation_certificate",
                                                       "cutover_phase", "candidate_ready_at"])
                    record_command(p, actor, action, previous_desired, previous_observed, result_code)
        except (CdcError, CdcDatasetBindingError, CredentialUnavailable, ValueError, TypeError) as exc:
            _compensate_new_dataset(created_dataset)
            code = exc.code if isinstance(exc, CdcError) else (
                str(exc) if isinstance(exc, CdcDatasetBindingError) else "CDC_CONFIGURATION_INVALID")
            return Response({"error": {"code": code}}, status=409 if code in {
                "CDC_INVALID_TRANSITION", "CDC_DATASET_BINDING_INVALID", "CDC_RESEED_REQUIRED",
                "CDC_CAPTURE_NOT_READY"} else 400)
        except IntegrityError:
            _compensate_new_dataset(created_dataset)
            # A concurrent enable may have won the source/table unique key.
            if action == "enable":
                p = CdcPipeline.objects.filter(source=source, table_schema=schema, table_name=table).first()
                if p is not None:
                    try:
                        _bound_dataset(p, source)
                        return Response({"success": True, "data": public_pipeline(p)}, status=202)
                    except CdcDatasetBindingError:
                        pass
            return Response({"error": {"code": "CDC_CONFLICT"}}, status=409)
        except DatabaseError:
            _compensate_new_dataset(created_dataset)
            return Response({"error": {"code": "CDC_PERSISTENCE_UNAVAILABLE"}}, status=503)
        return Response({"success": True, "data": public_pipeline(p)}, status=202)


class CdcServiceAuthentication(BaseAuthentication):
    def authenticate(self, request):
        if os.getenv("CDC_ENABLED") != "1" or os.getenv("APP_ENV") == "production":
            raise exceptions.PermissionDenied("CDC transport is not enabled for this environment.")
        stage = request.headers.get("X-Cdc-Stage", "")
        if stage not in {"controller", "normalize", "transform", "load"}:
            raise exceptions.AuthenticationFailed("Invalid CDC identity.")
        expected = read_secret(f"CDC_{stage.upper()}_KEY")
        if not expected or not hmac.compare_digest(expected, request.headers.get("X-Cdc-Key", "")):
            raise exceptions.AuthenticationFailed("Invalid CDC identity.")
        return type("CdcPrincipal", (), {"is_authenticated": True, "stage": stage})(), None


class InternalCdcView(APIView):
    authentication_classes = [CdcServiceAuthentication]
    permission_classes = []

    def get(self, request):
        result = []
        if request.user.stage == "controller" and request.query_params.get("recover_cutovers") == "1":
            recover_pending_cutovers()
        try:
            page = int(request.query_params.get("page", "0"))
            if page < 0 or page > 10000:
                raise ValueError
        except ValueError:
            return Response({"error": {"code": "CDC_PAGE_INVALID"}}, status=400)
        rows = list(CdcPipeline.objects.select_related("source").order_by("created_at", "pk")[page*100:page*100+101])
        for p in rows[:100]:
            source = p.source
            desired = p.desired_state if source.state == DataSource.ACTIVE and source.engine == "postgres" else "STOPPED"
            generation = CdcGeneration.objects.filter(pipeline=p, number=p.generation).first()
            if generation is None or generation.state == "FAILED":
                desired = "STOPPED"
            try:
                credential = active_credential(source)
            except CredentialUnavailable:
                credential, desired = None, "STOPPED"
            item = {"scope": pipeline_scope(p).__dict__, "desired_state": desired,
                    "control_suppressed": desired != p.desired_state,
                    "observed_state": p.observed_state, "error_code": p.error_code,
                    "primary_key": p.primary_key,
                    "columns": p.columns, "schema_version": p.schema_version,
                    "credential_version": credential.version if credential else 0,
                    "applied_credential_version": p.credential_version,
                    "capture_slot_seen": p.capture_slot_seen,
                    "capture_ready": p.capture_ready,
                    "checkpoints": p.checkpoints, "reconcile_requested": p.reconcile_requested,
                    "snapshot_signal": p.snapshot_signal}
            if generation:
                item["generation_state"] = generation.state
                item["reconciliation_attempt"] = generation.reconciliation_attempt
            if generation and generation.state == "CANDIDATE" and generation.previous_number:
                item["previous_scope"] = scope_for_number(p, generation.previous_number).__dict__
            if request.user.stage == "controller" and credential and source.state == DataSource.ACTIVE and desired in {"STREAMING", "PAUSED"}:
                item.update(connection_metadata=source.connection_metadata, transport=source.transport,
                            credential={"key_version": credential.key_version, "ciphertext": credential.ciphertext})
            result.append(item)
        return Response({"pipelines": result, "next_page": page+1 if len(rows)>100 else None})

    def post(self, request):
        data, stage = request.data, request.user.stage
        publish = False
        try:
            with transaction.atomic(using=integration_atomic_alias()):
                p = CdcPipeline.objects.select_for_update().select_related("source").get(
                    pk=uuid.UUID(str(data["pipeline_id"])))
                scope = pipeline_scope(p)
                if data.get("scope") != scope.__dict__:
                    submitted_scope = data.get("scope")
                    if (isinstance(submitted_scope, dict)
                            and (submitted_scope.get("generation") != p.generation
                                 or submitted_scope.get("configuration_epoch") != scope.configuration_epoch
                                 or submitted_scope.get("credential_epoch") != scope.credential_epoch)):
                        raise CdcError("CDC_STALE_CALLBACK")
                    raise CdcError("CDC_SCOPE_MISMATCH")
                generation = CdcGeneration.objects.select_for_update().filter(
                    pipeline=p, number=p.generation,
                    state__in=["ACTIVE", "CANDIDATE", "FAILED", "RESEED_REQUIRED"]).first()
                if generation is None:
                    raise CdcError("CDC_STALE_CALLBACK")
                if data.get("action") == "claim":
                    if stage != "controller" or set(data) != {
                            "action", "pipeline_id", "scope", "owner"}:
                        raise CdcError("CDC_CALLBACK_INVALID")
                    owner = uuid.UUID(str(data["owner"]))
                    now = timezone.now()
                    if (p.controller_lease_owner != owner
                            and p.controller_lease_until is not None
                            and p.controller_lease_until > now):
                        raise CdcError("CDC_CONTROLLER_LEASE_HELD")
                    if p.controller_lease_owner != owner or p.controller_lease_until is None or p.controller_lease_until <= now:
                        p.controller_fence += 1
                    p.controller_lease_owner = owner
                    p.controller_lease_until = now + timedelta(seconds=90)
                    p.save(update_fields=["controller_lease_owner", "controller_lease_until",
                                          "controller_fence", "updated_at"])
                    return Response({"fence": p.controller_fence})
                if (generation.state == "RESEED_REQUIRED"
                        and (stage != "controller" or set(data) - {
                            "pipeline_id", "scope", "observed_state", "action",
                            "lease_owner", "lease_fence"})):
                    raise CdcError("CDC_STALE_CALLBACK")
                if stage == "controller":
                    try:
                        owner = uuid.UUID(str(data["lease_owner"]))
                        fence = data["lease_fence"]
                    except (KeyError, ValueError, TypeError):
                        raise CdcError("CDC_STALE_CALLBACK") from None
                    if (p.controller_lease_owner != owner
                            or type(fence) is not int or p.controller_fence != fence
                            or p.controller_lease_until is None
                            or p.controller_lease_until <= timezone.now()):
                        raise CdcError("CDC_STALE_CALLBACK")
                if data.get("action") == "verify":
                    if stage != "controller" or set(data) != {
                            "action", "pipeline_id", "scope", "lease_owner", "lease_fence"}:
                        raise CdcError("CDC_CALLBACK_INVALID")
                    return Response({"success": True})
                if data.get("action") == "candidate_digest":
                    if (stage != "controller" or set(data) != {
                            "action", "pipeline_id", "scope", "lease_owner", "lease_fence"}
                            or generation.state != "CANDIDATE"
                            or generation.reconciliation_attempt.get("state") != "COMPARING"):
                        raise CdcError("CDC_CALLBACK_INVALID")
                    from database.cdc_reconciliation import candidate_digest
                    return Response(candidate_digest(p, generation, scope))
                if data.get("action") == "reconciliation_progress":
                    if (stage != "controller" or set(data) != {
                            "action", "pipeline_id", "scope", "lease_owner", "lease_fence",
                            "attempt_id", "state", "source_lsn", "stage_ends", "failure_code"}
                            or generation.state != "CANDIDATE"):
                        raise CdcError("CDC_CALLBACK_INVALID")
                    attempt = generation.reconciliation_attempt
                    states = ["REQUESTED", "SOURCE_SNAPSHOT_OPEN", "WATERMARK_EMITTED",
                              "WAITING_CAPTURE", "WAITING_LOADER", "COMPARING"]
                    new_state = data["state"]
                    if (attempt.get("id") != data["attempt_id"]
                            or attempt.get("generation") != p.generation
                            or attempt.get("state") not in states
                            or new_state not in states[1:] + ["FAILED"]
                            or (new_state != "FAILED" and states.index(new_state) !=
                                states.index(attempt["state"]) + 1)
                            or type(data["source_lsn"]) is not int or data["source_lsn"] < 0
                            or not _valid_stage_ends(data["stage_ends"])
                            or not isinstance(data["failure_code"], str)
                            or (new_state == "FAILED") != bool(data["failure_code"])
                            or data["failure_code"] and not __import__('re').fullmatch(
                                r"CDC_[A-Z_]{1,50}", data["failure_code"])):
                        raise CdcError("CDC_CALLBACK_INVALID")
                    attempt.update(state=new_state, source_lsn=data["source_lsn"],
                                   stage_ends=data["stage_ends"],
                                   failure_code=data["failure_code"],
                                   updated_at=timezone.now().isoformat())
                    generation.reconciliation_attempt = attempt
                    generation.save(update_fields=["reconciliation_attempt"])
                    if new_state == "FAILED":
                        p.reconcile_requested = False
                        p.save(update_fields=["reconcile_requested", "updated_at"])
                    return Response({"state": new_state})
                if data.get("action") == "watermark_certificate":
                    if (stage != "controller" or set(data) != {
                            "action", "pipeline_id", "scope", "lease_owner", "lease_fence", "proof"}
                            or generation.state != "CANDIDATE"):
                        raise CdcError("CDC_CALLBACK_INVALID")
                    certificate = issue_watermark_certificate(p, generation, scope, data["proof"])
                    return Response({"status": certificate["status"],
                                     "generation": certificate["generation"],
                                     "source_lsn": certificate["source_lsn"]})
                if generation.state == "FAILED" and not (
                        stage == "controller" and p.desired_state == "STOPPED"
                        and set(data) == {"pipeline_id", "scope", "lease_owner",
                                          "lease_fence", "observed_state"}
                        and data["observed_state"] == "STOPPED"):
                    raise CdcError("CDC_STALE_CALLBACK")
                if p.source.state != DataSource.ACTIVE or p.desired_state == "STOPPED":
                    if (stage != "controller"
                            or set(data) != {"pipeline_id", "scope", "lease_owner",
                                                 "lease_fence", "observed_state"}
                            or data["observed_state"] != "STOPPED"):
                        raise CdcError("CDC_STALE_CALLBACK")
                if stage != "controller" and (p.source.state != DataSource.ACTIVE or p.desired_state != "STREAMING"):
                    raise CdcError("CDC_STALE_CALLBACK")
                allowed = {"pipeline_id", "scope", "checkpoint", "error_code"}
                if stage == "load":
                    allowed.add("snapshot_complete")
                if stage == "normalize":
                    allowed |= {"capture_timestamp_ms", "snapshot_notification"}
                if stage == "controller":
                    allowed |= {"observed_state", "columns", "primary_key", "credential_version", "health", "reconciliation",
                                "capture_slot_seen", "capture_ready",
                                "lease_owner", "lease_fence"}
                if set(data) - allowed:
                    raise CdcError("CDC_CALLBACK_INVALID")
                code = data.get("error_code", "")
                if code and (not isinstance(code, str) or not __import__('re').fullmatch(r"CDC_[A-Z_]{1,50}", code)):
                    raise CdcError("CDC_CALLBACK_INVALID")
                if code:
                    if p.source.state != DataSource.ACTIVE or p.desired_state == "STOPPED":
                        raise CdcError("CDC_STALE_CALLBACK")
                    p.error_code = code
                    if p.observed_state != "RESEED_REQUIRED":
                        p.observed_state = "RESEED_REQUIRED" if code in {
                            "CDC_SCHEMA_INCOMPATIBLE", "CDC_SLOT_LOST", "CDC_KAFKA_RETENTION_LOST",
                            "CDC_VERSION_CONFLICT", "CDC_STORAGE_INCOMPATIBLE"} else "DEGRADED"
                    p.desired_state = "PAUSED"
                elif stage == "controller":
                    state = data.get("observed_state", p.observed_state)
                    if not _controller_state_allowed(p, state):
                        raise CdcError("CDC_CALLBACK_INVALID")
                    preserve_failure = p.observed_state == 'RESEED_REQUIRED'
                    if not preserve_failure and not (p.observed_state == "STREAMING" and state == "SNAPSHOTTING"):
                        p.observed_state = state
                        if state in {"PROVISIONING", "SNAPSHOTTING", "STREAMING"}:
                            p.error_code = ""
                    if "columns" in data and p.columns and p.columns != data["columns"]:
                        p.schema_version += 1
                    for field in ("columns", "primary_key", "credential_version"):
                        if field in data:
                            setattr(p, field, data[field])
                    if "health" in data:
                        health = data['health']
                        if set(health) != {'slot_active', 'retained_wal_bytes', 'wal_warning'} or type(health['slot_active']) is not bool or type(health['wal_warning']) is not bool or type(health['retained_wal_bytes']) is not int or health['retained_wal_bytes'] < 0:
                            raise CdcError('CDC_CALLBACK_INVALID')
                        p.health = {**p.health, **health}
                    for field in ("capture_slot_seen", "capture_ready"):
                        if field in data:
                            if data[field] is not True or (field == "capture_ready" and not (
                                    p.capture_slot_seen or data.get("capture_slot_seen") is True)):
                                raise CdcError("CDC_CALLBACK_INVALID")
                            setattr(p, field, True)
                    if "reconciliation" in data:
                        if not _valid_reconciliation(data["reconciliation"]):
                            raise CdcError("CDC_CALLBACK_INVALID")
                        p.reconciliation = data["reconciliation"]
                        p.reconcile_requested = False
                if 'capture_timestamp_ms' in data:
                    captured = data['capture_timestamp_ms']
                    if type(captured) is not int or not 0 < captured <= int(timezone.now().timestamp()*1000)+60000:
                        raise CdcError('CDC_CALLBACK_INVALID')
                    p.health = {**p.health, 'capture_timestamp_ms': max(captured, p.health.get('capture_timestamp_ms', 0))}
                if "snapshot_notification" in data:
                    next_signal = _next_snapshot_signal(
                        p.snapshot_signal, data["snapshot_notification"])
                    if (next_signal is not p.snapshot_signal
                            and data["snapshot_notification"].get("type") == "STARTED"
                            and (p.snapshot_signal.get("status") == "COMPLETED"
                                 or (generation.state == "ACTIVE" and p.checkpoints
                                     and Database.objects.filter(
                                         pk=p.dataset_id, etl_status="completed",
                                         cdc_generation=p.generation).exists()))):
                        p.error_code = "CDC_UNEXPECTED_RESNAPSHOT"
                        p.observed_state = "RESEED_REQUIRED"
                        p.desired_state = "PAUSED"
                    p.snapshot_signal = next_signal
                if "checkpoint" in data:
                    checkpoint = data["checkpoint"]
                    if set(checkpoint) != {"offset", "partition", "lsn"} or any(type(v) is not int or v < 0 for v in checkpoint.values()):
                        raise CdcError("CDC_CALLBACK_INVALID")
                    key = f"{stage}:{checkpoint['partition']}"
                    old = p.checkpoints.get(key, {"offset": -1, "lsn": 0})
                    if checkpoint["offset"] > old["offset"]:
                        checkpoint["lsn"] = max(checkpoint["lsn"], old["lsn"])
                        p.checkpoints = {**p.checkpoints, key: checkpoint}
                    if stage == "load" and data.get("snapshot_complete") is True:
                        if (code or not p.columns or not p.primary_key
                                or checkpoint["offset"] < old["offset"]
                                or checkpoint["lsn"] < old["lsn"]):
                            raise CdcError("CDC_PUBLICATION_NOT_READY")
                        _bound_dataset(p, p.source)
                        p.observed_state = "STREAMING"
                        publish = generation.state == "ACTIVE"
                elif data.get("snapshot_complete") is True:
                    raise CdcError("CDC_PUBLICATION_NOT_READY")
                if (p.snapshot_signal.get("completed") is True
                        and p.columns and p.primary_key and not code
                        and p.desired_state == "STREAMING"
                        and p.observed_state != "RESEED_REQUIRED"):
                    dataset = _bound_dataset(p, p.source)
                    if dataset.etl_status == "pending" or generation.state == "CANDIDATE":
                        p.observed_state = "STREAMING"
                        publish = generation.state == "ACTIVE"
                p.heartbeat_at = timezone.now()
                p.save()
                generation.schema_version = p.schema_version
                generation.columns = p.columns
                generation.primary_key = p.primary_key
                generation.checkpoints = p.checkpoints
                generation.snapshot_signal = p.snapshot_signal
                if p.observed_state == "RESEED_REQUIRED":
                    generation.state = "FAILED" if generation.state == "CANDIDATE" else "RESEED_REQUIRED"
                    generation.reason = p.error_code
                generation.save(update_fields=["schema_version", "columns", "primary_key",
                                               "checkpoints", "snapshot_signal", "state", "reason"])
            if publish:
                # A generation replacement must serialize with publication.
                # Keep the checkpoint durable if Query publication fails, so
                # the same Loader record can be replayed without data loss.
                with transaction.atomic(using=integration_atomic_alias()):
                    current = CdcPipeline.objects.select_for_update().select_related("source").get(pk=p.pk)
                    if (current.generation != scope.generation
                            or not CdcGeneration.objects.filter(
                                pipeline=current, number=scope.generation, state="ACTIVE").exists()):
                        raise CdcError("CDC_STALE_CALLBACK")
                    publish_live_dataset(current, scope)
        except (CdcError, CdcDatasetBindingError) as exc:
            code = exc.code if isinstance(exc, CdcError) else str(exc)
            return Response({"error": {"code": code}}, status=409 if code in {
                "CDC_STALE_CALLBACK", "CDC_CONTROLLER_LEASE_HELD", "CDC_DATASET_BINDING_INVALID", "CDC_PUBLICATION_NOT_READY"} else 400)
        except (ValueError, KeyError, TypeError, CdcPipeline.DoesNotExist):
            return Response({"error": {"code": "CDC_CALLBACK_INVALID"}}, status=400)
        except DatabaseError:
            return Response({"error": {"code": "CDC_PERSISTENCE_UNAVAILABLE"}}, status=503)
        return Response({"success": True})
