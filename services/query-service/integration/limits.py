"""Database-backed admission for source network operations across workers."""

from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from .models import SourceOperationBudget


LIMITS_PER_MINUTE = {
    "test": 12,
    "discover": 12,
    "snapshot": 6,
    "rotate": 6,
    "replace": 6,
}


def admit_source_operation(workspace_id, actor_id, operation):
    limit = LIMITS_PER_MINUTE[operation]
    now = timezone.now()
    window = now.replace(second=0, microsecond=0)
    budget, _ = SourceOperationBudget.objects.get_or_create(
        workspace_id=workspace_id, actor_id=actor_id,
        operation=operation, window_start=window,
    )
    # One conditional UPDATE is atomic across Query workers/processes.
    return bool(SourceOperationBudget.objects.filter(pk=budget.pk, count__lt=limit).update(count=F("count") + 1))


def prune_source_operation_budgets():
    deleted, _ = SourceOperationBudget.objects.filter(
        window_start__lt=timezone.now() - timedelta(days=1),
    ).delete()
    return deleted
