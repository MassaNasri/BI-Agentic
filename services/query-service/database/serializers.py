from rest_framework import serializers
from .models import Database


class DatabaseSerializer(serializers.ModelSerializer):
    """Serializer for Database model."""
    source_tables = serializers.SerializerMethodField()
    source_id = serializers.UUIDField(read_only=True)
    etl_message = serializers.SerializerMethodField()

    def get_etl_message(self, obj):
        # Internal diagnostics may contain physical destinations or driver text.
        return {
            'completed': 'Dataset is ready.',
            'processing': 'Dataset is processing.',
            'failed': 'Dataset processing failed.',
            'pending': 'Dataset is queued.',
        }.get(str(obj.etl_status or '').lower(), 'Dataset status is unavailable.')

    def get_source_tables(self, obj):
        """Expose source identity and status, never the physical storage name."""
        public_fields = (
            'id', 'schema', 'name', 'status', 'row_count', 'column_count', 'columns_schema'
        )
        tables = []
        for item in obj.source_tables or []:
            if isinstance(item, dict):
                tables.append({key: item.get(key) for key in public_fields if key in item})
        return tables
    
    class Meta:
        model = Database
        fields = [
            'id',
            'manager',
            'manager_name',
            'manager_email',
            'filename',
            'file_size',
            'source_kind',
            'source_engine',
            'source_id',
            'source_tables',
            'row_count',
            'column_count',
            'columns_schema',
            'workspace_id',
            'upload_date',
            'etl_status',
            'etl_message'
        ]
        read_only_fields = [
            'id',
            'manager',
            'manager_name',
            'manager_email',
            'upload_date',
            'etl_status',
            'etl_message'
        ]


class DatabaseUploadResponseSerializer(serializers.Serializer):
    """Serializer for database upload response."""
    
    id = serializers.IntegerField()
    filename = serializers.CharField()
    file_size = serializers.IntegerField()
    upload_date = serializers.DateTimeField()
    message = serializers.CharField()


class DatabasePreviewSerializer(serializers.Serializer):
    """Serializer for database preview data."""
    
    columns = serializers.ListField(child=serializers.CharField())
    rows = serializers.ListField(child=serializers.DictField())
    total_rows = serializers.IntegerField()
    total_columns = serializers.IntegerField()

