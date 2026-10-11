from django.db import models
from django.utils import timezone


class VisualizationObjectOwnership(models.Model):
    CARD = 'card'
    DASHBOARD = 'dashboard'
    OBJECT_TYPES = [(CARD, 'Card'), (DASHBOARD, 'Dashboard')]
    MAPPED = 'mapped'
    UNMAPPED = 'unmapped'
    STATUSES = [(MAPPED, 'Mapped'), (UNMAPPED, 'Unmapped')]

    workspace_id = models.PositiveBigIntegerField(db_index=True)
    object_type = models.CharField(max_length=16, choices=OBJECT_TYPES)
    metabase_object_id = models.PositiveBigIntegerField()
    creator_id = models.CharField(max_length=128)
    query_definition_id = models.UUIDField(null=True, blank=True)
    source_context = models.JSONField(default=dict, blank=True)
    ownership_status = models.CharField(max_length=16, choices=STATUSES, default=MAPPED)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'visualization_object_ownership'
        constraints = [
            models.UniqueConstraint(
                fields=['object_type', 'metabase_object_id'],
                name='unique_metabase_object_ownership',
            )
        ]
        indexes = [
            models.Index(
                fields=['workspace_id', 'object_type', 'ownership_status'],
                name='visualizati_workspa_5b3fe8_idx',
            )
        ]
