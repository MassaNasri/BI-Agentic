from __future__ import annotations

import os
import time
from urllib.parse import urlsplit

from django.db import DatabaseError
from rest_framework import serializers

from .models import DashboardPage, ReportPageAssignment
from .services import get_jwt_service, get_metabase_service

EMBED_TOKEN_REFRESH_LEEWAY_SECONDS = int(os.getenv("METABASE_EMBED_REFRESH_LEEWAY_SECONDS", "300"))


class GridAliasMixin:
    """Support both width/height and w/h payload keys."""

    def to_internal_value(self, data):
        if isinstance(data, dict):
            payload = dict(data)
            if "w" in payload and "width" not in payload:
                payload["width"] = payload["w"]
            if "h" in payload and "height" not in payload:
                payload["height"] = payload["h"]
            data = payload
        return super().to_internal_value(data)


class DashboardPageSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardPage
        fields = [
            "id",
            "workspace_id",
            "name",
            "description",
            "order",
            "metabase_dashboard_id",
            "created_by_id",
            "created_by_email",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "workspace_id",
            "metabase_dashboard_id",
            "created_by_id",
            "created_by_email",
            "created_at",
        ]


def _safe_field(instance, field_name: str, default):
    if field_name in instance.__dict__:
        value = instance.__dict__.get(field_name, default)
        return default if value is None else value
    try:
        value = getattr(instance, field_name)
    except (AttributeError, DatabaseError):
        return default
    return default if value is None else value


def _extract_embed_token(embed_url: str) -> str:
    if not embed_url:
        return ""
    parsed = urlsplit(embed_url)
    path = str(parsed.path or "").strip().strip("/")
    parts = path.split("/")
    if len(parts) < 3:
        return ""
    if parts[-2] not in {"question", "dashboard"}:
        return ""
    return str(parts[-1] or "").strip()


def _is_cached_embed_url_fresh(embed_url: str) -> bool:
    token = _extract_embed_token(embed_url)
    if not token:
        return False
    payload = get_jwt_service().verify_token(token)
    if not isinstance(payload, dict):
        return False
    try:
        exp = int(payload.get("exp") or 0)
    except (TypeError, ValueError):
        return False
    return exp > int(time.time()) + max(0, EMBED_TOKEN_REFRESH_LEEWAY_SECONDS)


class DashboardWidgetSerializer(serializers.Serializer):
    def _metabase(self):
        cached = getattr(self, "_cached_metabase_service", None)
        if cached is None:
            cached = get_metabase_service()
            self._cached_metabase_service = cached
        return cached

    def _resolve_report_embed_url(self, report) -> str:
        cached_embed_url = str(getattr(report, "embed_url", "") or "").strip()
        question_id = getattr(report, "metabase_question_id", None)
        if not question_id:
            return cached_embed_url
        if cached_embed_url and _is_cached_embed_url_fresh(cached_embed_url):
            return cached_embed_url

        metabase = self._metabase()
        refreshed_embed_url = str(metabase.get_question_embed_url(int(question_id)) or "").strip()
        if not refreshed_embed_url:
            return cached_embed_url

        if refreshed_embed_url != cached_embed_url:
            try:
                report.embed_url = refreshed_embed_url
                report.save(update_fields=["embed_url", "updated_at"])
            except Exception:
                # Best effort only; keep response generation resilient.
                pass
        return refreshed_embed_url

    def to_representation(self, instance: ReportPageAssignment):
        report = getattr(instance, "report", None)
        report_title = ""
        report_status = ""
        report_chart_type = ""
        report_metabase_question_id = None
        report_embed_url = ""
        if report is not None:
            report_title = str(getattr(report, "title", "") or "")
            report_status = str(getattr(report, "status", "") or "")
            report_chart_type = str(getattr(report, "chart_type", "") or "")
            report_metabase_question_id = getattr(report, "metabase_question_id", None)
            report_embed_url = self._resolve_report_embed_url(report)

        return {
            "id": instance.id,
            "page_id": instance.page_id,
            "report_id": instance.report_id,
            "widget_type": str(_safe_field(instance, "widget_type", "report") or "report"),
            "order": int(_safe_field(instance, "order", 0) or 0),
            "x": int(_safe_field(instance, "x", 0) or 0),
            "y": int(_safe_field(instance, "y", 0) or 0),
            "width": int(_safe_field(instance, "width", 6) or 6),
            "height": int(_safe_field(instance, "height", 4) or 4),
            "layout_metadata": _safe_field(instance, "layout_metadata", {}) or {},
            "widget_config": _safe_field(instance, "widget_config", {}) or {},
            "added_at": instance.added_at,
            "added_by_id": str(instance.added_by_id or ""),
            "added_by_email": str(instance.added_by_email or ""),
            "report_title": report_title,
            "report_status": report_status,
            "report_chart_type": report_chart_type,
            "report_metabase_question_id": report_metabase_question_id,
            "report_embed_url": report_embed_url,
        }


class DashboardPageCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(allow_blank=True, required=False, default="")
    order = serializers.IntegerField(min_value=0, required=False)


class DashboardPageUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    order = serializers.IntegerField(min_value=0, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("At least one field is required.")
        return attrs


class DashboardPageReorderSerializer(serializers.Serializer):
    page_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )

    def validate_page_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("page_ids must not contain duplicates.")
        return value


class DashboardWidgetCreateSerializer(GridAliasMixin, serializers.Serializer):
    report_id = serializers.IntegerField(min_value=1)
    widget_type = serializers.CharField(max_length=32, required=False, default="report")
    order = serializers.IntegerField(min_value=0, required=False)
    x = serializers.IntegerField(min_value=0, required=False, default=0)
    y = serializers.IntegerField(min_value=0, required=False, default=0)
    width = serializers.IntegerField(min_value=1, max_value=48, required=False, default=6)
    height = serializers.IntegerField(min_value=1, max_value=48, required=False, default=4)
    layout_metadata = serializers.DictField(required=False, default=dict)
    widget_config = serializers.DictField(required=False, default=dict)

    def validate_widget_type(self, value):
        normalized = str(value or "").strip().lower()
        if not normalized:
            raise serializers.ValidationError("widget_type cannot be empty.")
        return normalized


class DashboardWidgetUpdateSerializer(GridAliasMixin, serializers.Serializer):
    page_id = serializers.IntegerField(min_value=1, required=False)
    widget_type = serializers.CharField(max_length=32, required=False)
    order = serializers.IntegerField(min_value=0, required=False)
    x = serializers.IntegerField(min_value=0, required=False)
    y = serializers.IntegerField(min_value=0, required=False)
    width = serializers.IntegerField(min_value=1, max_value=48, required=False)
    height = serializers.IntegerField(min_value=1, max_value=48, required=False)
    layout_metadata = serializers.DictField(required=False)
    widget_config = serializers.DictField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("At least one field is required.")
        return attrs

    def validate_widget_type(self, value):
        normalized = str(value or "").strip().lower()
        if not normalized:
            raise serializers.ValidationError("widget_type cannot be empty.")
        return normalized


class DashboardWidgetBatchItemSerializer(GridAliasMixin, serializers.Serializer):
    widget_id = serializers.IntegerField(min_value=1)
    page_id = serializers.IntegerField(min_value=1, required=False)
    widget_type = serializers.CharField(max_length=32, required=False)
    order = serializers.IntegerField(min_value=0, required=False)
    x = serializers.IntegerField(min_value=0, required=False)
    y = serializers.IntegerField(min_value=0, required=False)
    width = serializers.IntegerField(min_value=1, max_value=48, required=False)
    height = serializers.IntegerField(min_value=1, max_value=48, required=False)
    layout_metadata = serializers.DictField(required=False)
    widget_config = serializers.DictField(required=False)

    def validate(self, attrs):
        if len(attrs) <= 1:
            raise serializers.ValidationError("At least one field besides widget_id is required.")
        return attrs

    def validate_widget_type(self, value):
        normalized = str(value or "").strip().lower()
        if not normalized:
            raise serializers.ValidationError("widget_type cannot be empty.")
        return normalized


class DashboardWidgetBatchUpdateSerializer(serializers.Serializer):
    updates = DashboardWidgetBatchItemSerializer(many=True)

    def validate_updates(self, value):
        widget_ids = [entry.get("widget_id") for entry in value if isinstance(entry, dict)]
        if len(widget_ids) != len(set(widget_ids)):
            raise serializers.ValidationError("updates must not contain duplicate widget_id values.")
        return value
