"""Integration credential lifecycle and immutable execution authorizations."""

from datetime import timedelta

from bi_platform_shared.credential_crypto import encrypt_credential
from bi_platform_shared.db_ownership import integration_atomic
from django.db.models import Max
from django.utils import timezone

from .models import DataSource, SourceCredential, SourceExecution


class CredentialUnavailable(ValueError):
    pass


def _candidate(source, plaintext):
    key_version, ciphertext = encrypt_credential(plaintext)
    next_version = (SourceCredential.objects.filter(source=source).aggregate(Max("version"))["version__max"] or 0) + 1
    return SourceCredential.objects.create(
        source=source, version=next_version, key_version=key_version,
        ciphertext=ciphertext, state=SourceCredential.CANDIDATE,
    )


@integration_atomic
def configure_credential(source_id, plaintext):
    source = DataSource.objects.select_for_update().get(pk=source_id)
    if source.state == DataSource.RETIRED:
        raise CredentialUnavailable("Source is retired.")
    if SourceCredential.objects.filter(source=source, state=SourceCredential.ACTIVE).exists():
        raise CredentialUnavailable("Use rotation for an existing credential.")
    credential = _candidate(source, plaintext)
    credential.state = SourceCredential.ACTIVE
    credential.activated_at = timezone.now()
    credential.save(update_fields=["state", "activated_at"])
    return credential


def active_credential(source):
    credential = SourceCredential.objects.filter(source=source, state=SourceCredential.ACTIVE).first()
    if credential is None:
        raise CredentialUnavailable("Source credential is not configured.")
    return credential


@integration_atomic
def create_candidate_credential(source_id, plaintext):
    source = DataSource.objects.select_for_update().get(pk=source_id)
    if source.state != DataSource.ACTIVE:
        raise CredentialUnavailable("Source is not active.")
    return _candidate(source, plaintext)


@integration_atomic
def activate_credential(source_id, credential_id, *, expected_active_id=None):
    source = DataSource.objects.select_for_update().get(pk=source_id)
    candidate = SourceCredential.objects.select_for_update().get(
        pk=credential_id, source=source, state=SourceCredential.CANDIDATE,
    )
    if source.state != DataSource.ACTIVE:
        raise CredentialUnavailable("Source is not active.")
    current = SourceCredential.objects.filter(source=source, state=SourceCredential.ACTIVE).first()
    if expected_active_id is not None and (current is None or current.pk != expected_active_id):
        raise CredentialUnavailable("Credential rotation conflicted with another change.")
    SourceCredential.objects.filter(source=source, state=SourceCredential.ACTIVE).update(
        state=SourceCredential.SUPERSEDED, deactivated_at=timezone.now(),
    )
    candidate.state = SourceCredential.ACTIVE
    candidate.activated_at = timezone.now()
    candidate.save(update_fields=["state", "activated_at"])
    return candidate


@integration_atomic
def revoke_credential(source_id):
    source = DataSource.objects.select_for_update().get(pk=source_id)
    # A rotated source can still have live grants bound to superseded versions.
    # Explicit revocation invalidates every version, including staged candidates.
    SourceCredential.objects.filter(
        source=source,
        state__in=[SourceCredential.ACTIVE, SourceCredential.SUPERSEDED, SourceCredential.CANDIDATE],
    ).update(
        state=SourceCredential.REVOKED, revoked_at=timezone.now(), ciphertext="",
    )


@integration_atomic
def authorize_execution(source, *, job_id, dataset_id, kind, credential=None,
                        engine=None, metadata=None, configuration_version=None, transport=None):
    source = DataSource.objects.select_for_update().get(pk=source.pk)
    if source.state != DataSource.ACTIVE:
        raise CredentialUnavailable("Source is not active.")
    if kind not in {"test", "discover", "snapshot", "rotate", "candidate"}:
        raise CredentialUnavailable("Invalid source operation.")
    credential = SourceCredential.objects.filter(pk=credential.pk, source=source).first() if credential is not None else active_credential(source)
    if credential is None:
        raise CredentialUnavailable("Credential is unavailable.")
    if credential.source_id != source.pk or credential.state not in {SourceCredential.ACTIVE, SourceCredential.CANDIDATE}:
        raise CredentialUnavailable("Credential is unavailable.")
    lifetime = timedelta(hours=24) if kind in {"snapshot", "candidate"} else timedelta(minutes=5)
    return SourceExecution.objects.create(
        job_id=job_id, source=source, credential=credential,
        workspace_id=source.workspace_id, dataset_id=str(dataset_id), kind=kind,
        engine=engine or source.engine,
        connection_metadata=metadata if metadata is not None else source.connection_metadata,
        configuration_version=configuration_version or source.configuration_version,
        transport=transport or source.transport, expires_at=timezone.now() + lifetime,
    )


def resolve_execution(*, workspace_id, source_id, job_id, dataset_id, credential_id, version):
    grant = SourceExecution.objects.select_related("source", "credential").filter(
        job_id=job_id, source_id=source_id, workspace_id=workspace_id,
        dataset_id=str(dataset_id), credential_id=credential_id,
        credential__version=version, expires_at__gt=timezone.now(),
    ).first()
    if grant is None or grant.credential.state == SourceCredential.REVOKED:
        raise CredentialUnavailable("Source execution authorization is unavailable.")
    return grant


def execution_reference(grant):
    return {
        "source_id": str(grant.source_id), "workspace_id": grant.workspace_id,
        "dataset_id": grant.dataset_id, "job_id": str(grant.job_id),
        "credential_id": str(grant.credential_id),
        "credential_version": grant.credential.version,
    }


def prune_old_credentials():
    """Expire decryptable superseded secrets after the 24-hour grant/rollback window.

    Run from a deployment scheduler at least daily. Active grants and rollback
    points are retained; a revoked row keeps metadata only, not ciphertext.
    """
    cutoff = timezone.now() - timedelta(hours=24)
    SourceExecution.objects.filter(expires_at__lt=cutoff).delete()
    count = 0
    for credential in SourceCredential.objects.filter(
        state=SourceCredential.SUPERSEDED, deactivated_at__lt=cutoff,
    ).iterator():
        if SourceExecution.objects.filter(credential=credential, expires_at__gt=timezone.now()).exists():
            continue
        # One-to-one candidate is the rollback point and retains the prior key.
        from .models import SourceCandidate
        rollback = SourceCandidate.objects.filter(credential=credential, state="rollback_ready").first()
        if rollback:
            if rollback.cutover_at is None or rollback.cutover_at > cutoff:
                continue
            rollback.delete()
        SourceCredential.objects.filter(pk=credential.pk, state=SourceCredential.SUPERSEDED).update(
            state=SourceCredential.REVOKED, ciphertext="", revoked_at=timezone.now(),
        )
        count += 1
    return count
