from django.db import models
from django.utils import timezone
import uuid


class Database(models.Model):
    """Query-owned analytical dataset/materialization (legacy table name)."""
    
    manager = models.PositiveBigIntegerField(
        db_column='manager_id',
        db_index=True,
        help_text="Manager user identifier from auth-service.",
    )
    manager_email = models.EmailField(blank=True, default="")
    manager_name = models.CharField(max_length=255, blank=True, default="")
    workspace_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Workspace identifier from workspace-service.",
    )
    ingestion_job_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text="Immutable query-service-owned ingestion job identifier.",
    )
    
    # File metadata
    filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField(help_text="File size in bytes")
    file_path = models.CharField(max_length=500, help_text="Path to file in ETL system")
    source_kind = models.CharField(max_length=20, default='file')
    source_engine = models.CharField(max_length=32, blank=True, default='')
    source_tables = models.JSONField(default=list, blank=True)
    source = models.ForeignKey(
        'integration.DataSource', null=True, blank=True,
        on_delete=models.PROTECT, related_name='datasets',
        help_text="Integration-owned source; file uploads have no persistent source.",
    )
    
    # Data metadata
    row_count = models.IntegerField(default=0, help_text="Number of rows in the dataset")
    column_count = models.IntegerField(default=0, help_text="Number of columns in the dataset")
    columns_schema = models.JSONField(
        default=dict, 
        blank=True,
        help_text="Column names and types as JSON"
    )
    
    # ClickHouse reference
    clickhouse_table_name = models.CharField(
        max_length=255, 
        blank=True,
        help_text="Name of the table in ClickHouse"
    )
    clickhouse_database = models.CharField(
        max_length=255,
        default='default',
        help_text="ClickHouse database name"
    )
    
    # Timestamps
    upload_date = models.DateTimeField(default=timezone.now)
    etl_status = models.CharField(
        max_length=50,
        default='pending',
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed')
        ]
    )
    etl_message = models.TextField(blank=True, help_text="ETL processing message/error")
    
    class Meta:
        db_table = 'manager_databases'
        verbose_name = 'Database'
        verbose_name_plural = 'Databases'
        ordering = ['-upload_date']
    
    def __str__(self):
        manager_label = self.manager_email or f"manager:{self.manager}"
        return f"{self.filename} - {manager_label}"
    
    def get_preview_data(self):
        """
        Returns preview data from ClickHouse (first 5 rows).
        This will be implemented to query ClickHouse directly.
        """
        # TODO: Implement ClickHouse query
        return []


class AuthorizedQueryDefinition(models.Model):
    """Query-service-owned proof that SQL passed tenant/dataset authorization."""

    import uuid

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.PositiveBigIntegerField(db_index=True)
    dataset_id = models.PositiveBigIntegerField(db_index=True)
    normalized_sql = models.TextField()
    creator_id = models.CharField(max_length=128)
    validation_status = models.CharField(max_length=20, default='approved')
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = 'authorized_query_definitions'
        indexes = [
            models.Index(
                fields=['workspace_id', 'dataset_id', 'validation_status'],
                name='authorized__workspa_af5518_idx',
            )
        ]

