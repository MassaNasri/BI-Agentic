from rest_framework import serializers
from .models import Database


class DatabaseSerializer(serializers.ModelSerializer):
    """Serializer for Database model."""
    
    class Meta:
        model = Database
        fields = [
            'id',
            'manager',
            'manager_name',
            'manager_email',
            'filename',
            'file_size',
            'file_path',
            'row_count',
            'column_count',
            'columns_schema',
            'workspace_id',
            'clickhouse_table_name',
            'clickhouse_database',
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

