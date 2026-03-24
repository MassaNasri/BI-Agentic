from django.db import models
from django.conf import settings
from django.utils import timezone


class Database(models.Model):
    """
    Model representing a manager's uploaded database.
    Each manager can have only ONE database at a time.
    """
    
    manager = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='database',
        limit_choices_to={'role': 'manager'}
    )
    
    # File metadata
    filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField(help_text="File size in bytes")
    file_path = models.CharField(max_length=500, help_text="Path to file in ETL system")
    
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
        return f"{self.filename} - {self.manager.email}"
    
    def get_preview_data(self):
        """
        Returns preview data from ClickHouse (first 5 rows).
        This will be implemented to query ClickHouse directly.
        """
        # TODO: Implement ClickHouse query
        return []

