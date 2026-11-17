"""Integration-owned CDC intent transitions and safe command audit."""

from bi_platform_shared.cdc_contract import CdcError

from .models import CdcAudit


def command_transition(pipeline, action):
    """Return desired, observed, reconcile flag, and a bounded result code."""
    desired, observed = pipeline.desired_state, pipeline.observed_state
    requested = pipeline.reconcile_requested
    if action == "pause":
        if desired == "PAUSED":
            return desired, observed, requested, "CDC_IDEMPOTENT"
        if desired != "STREAMING":
            raise CdcError("CDC_INVALID_TRANSITION")
        return "PAUSED", observed if observed == "RESEED_REQUIRED" else "PAUSING", requested, "CDC_ACCEPTED"
    if action == "resume":
        if observed == "RESEED_REQUIRED":
            raise CdcError("CDC_RESEED_REQUIRED")
        if desired == "STREAMING":
            return desired, observed, requested, "CDC_IDEMPOTENT"
        if desired not in {"PAUSED", "STOPPED"} or observed not in {"PAUSED", "STOPPED"}:
            raise CdcError("CDC_INVALID_TRANSITION")
        return "STREAMING", "PROVISIONING", requested, "CDC_ACCEPTED"
    if action == "disable":
        if desired == "STOPPED":
            return desired, observed, requested, "CDC_IDEMPOTENT"
        return "STOPPED", observed if observed == "RESEED_REQUIRED" else "STOPPING", requested, "CDC_ACCEPTED"
    if action == "reconcile":
        if desired != "STREAMING" or observed != "STREAMING":
            raise CdcError("CDC_INVALID_TRANSITION")
        return desired, observed, True, "CDC_IDEMPOTENT" if requested else "CDC_ACCEPTED"
    raise CdcError("CDC_OPERATION_INVALID")


def record_command(pipeline, actor_id, action, previous_desired, previous_observed, result_code):
    return CdcAudit.objects.create(
        pipeline=pipeline, workspace_id=pipeline.workspace_id, source_id=pipeline.source_id,
        dataset_id=pipeline.dataset_id, actor_id=actor_id, action=action,
        previous_desired_state=previous_desired, previous_observed_state=previous_observed,
        new_desired_state=pipeline.desired_state, new_observed_state=pipeline.observed_state,
        result_code=result_code,
    )
