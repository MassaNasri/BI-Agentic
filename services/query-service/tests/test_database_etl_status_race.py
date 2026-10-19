import os
from datetime import timedelta
from unittest.mock import Mock, patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")
os.environ.setdefault("APP_ENV", "test")

import django
django.setup()

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from types import SimpleNamespace

from database.views import DatabaseDetailView, _mark_processing_timeout


@patch("database.views.ClickHouseClient")
def test_nonempty_upload_is_not_completed_before_loader_rows_are_visible(client_type):
    client = client_type.return_value
    client.table_exists.return_value = {"success": True, "exists": True}
    client.get_table_count.return_value = {"success": True, "count": 0}
    database = Mock(
        id=7,
        file_size=128,
        clickhouse_database="etl",
        clickhouse_table_name="sales",
        etl_status="processing",
    )

    updated = DatabaseDetailView()._check_and_update_etl_status(database)

    assert updated is False
    assert database.etl_status == "processing"
    assert database.etl_message == "ClickHouse table exists; waiting for loaded rows."
    database.save.assert_called_once_with(update_fields=["etl_message"])
    client.get_table_schema.assert_not_called()


@override_settings(ETL_PROCESSING_TIMEOUT_SECONDS=30)
def test_processing_state_becomes_failed_after_bounded_timeout():
    now = timezone.now()
    database = Mock(
        pk=7,
        workspace_id=23,
        ingestion_job_id="job-1",
        upload_date=now - timedelta(seconds=31),
        etl_status="processing",
    )

    updated = _mark_processing_timeout(database, "The output table remained empty.", now=now)

    assert updated is True
    assert database.etl_status == "failed"
    assert "within 30 seconds" in database.etl_message
    database.save.assert_called_once_with(update_fields=["etl_status", "etl_message"])


@override_settings(ETL_PROCESSING_TIMEOUT_SECONDS=90000)
def test_sqlite_processing_window_is_capped_before_staging_ttl():
    now = timezone.now()
    database = Mock(
        pk=8,
        workspace_id=23,
        ingestion_job_id="job-sqlite",
        source_engine="sqlite",
        upload_date=now - timedelta(seconds=3601),
        etl_status="processing",
    )
    assert _mark_processing_timeout(database, "The output table remained empty.", now=now)
    assert "within 3600 seconds" in database.etl_message


def _principal():
    return SimpleNamespace(
        id=11,
        pk=11,
        role="manager",
        workspace_id=23,
        email="manager@example.com",
        is_authenticated=True,
    )


@patch("database.views.DatabaseSerializer")
@patch("database.views.resolve_workspace_dataset_binding")
@patch("database.views.Database.objects.filter")
def test_status_poll_returns_processing_metadata_without_physical_binding(
    filter_rows, resolve_binding, serializer_type
):
    database = Mock(pk=7, id=7, workspace_id=23, etl_status="processing", file_size=128)
    filter_rows.return_value.order_by.return_value.first.return_value = database
    serializer_type.return_value.data = {"id": 7, "etl_status": "processing"}
    request = APIRequestFactory().get("/database/")
    force_authenticate(request, user=_principal())

    with patch.object(DatabaseDetailView, "_check_and_update_etl_status", return_value=False):
        response = DatabaseDetailView.as_view()(request)

    assert response.status_code == 200
    assert response.data["data"]["etl_status"] == "processing"
    resolve_binding.assert_not_called()


@patch("database.views.DatabaseSerializer")
@patch("database.views.resolve_workspace_dataset_binding")
@patch("database.views.Database.objects.filter")
def test_status_poll_returns_terminal_failure_without_physical_binding(
    filter_rows, resolve_binding, serializer_type
):
    database = Mock(pk=7, id=7, workspace_id=23, etl_status="failed", file_size=128)
    filter_rows.return_value.order_by.return_value.first.return_value = database
    serializer_type.return_value.data = {
        "id": 7,
        "etl_status": "failed",
        "etl_message": "Loader failed",
    }
    request = APIRequestFactory().get("/database/")
    force_authenticate(request, user=_principal())

    response = DatabaseDetailView.as_view()(request)

    assert response.status_code == 200
    assert response.data["data"]["etl_status"] == "failed"
    resolve_binding.assert_not_called()
