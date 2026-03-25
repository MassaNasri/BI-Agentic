from rest_framework import serializers


class NotificationEventSerializer(serializers.Serializer):
    event_type = serializers.CharField(max_length=100)
    event_key = serializers.CharField(max_length=255, required=False, allow_blank=True)
    payload = serializers.JSONField()
