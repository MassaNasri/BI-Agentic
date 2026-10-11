import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")
os.environ.setdefault("APP_ENV", "test")

import django
django.setup()

from rest_framework.test import APIRequestFactory, force_authenticate
from django.utils import timezone

from database.views import (
    DatabaseSourceCapabilitiesView,
    DatabaseSourceDiscoveryView,
    DatabasePreviewView,
    DatabaseSchemaView,
    _build_imported_tables,
    _resolve_imported_table,
    _wait_for_initial_rows,
    _loader_table_name,
    _snapshot_source_name,
)


def _principal(workspace_id="7", role="manager"):
    return SimpleNamespace(
        id="11", pk="11", role=role, email="manager@example.com", name="Manager",
        workspace_id=workspace_id, is_authenticated=True,
    )


def test_capabilities_are_proxied_without_exposing_user_credentials():
    upstream = Mock(status_code=200)
    upstream.json.return_value = {"success": True, "data": {"connectors": [{"id": "postgres"}]}}
    request = APIRequestFactory().get("/database/sources/capabilities/")
    force_authenticate(request, user=_principal())
    with patch("database.views.requests.get", return_value=upstream) as get:
        response = DatabaseSourceCapabilitiesView.as_view()(request)
    assert response.status_code == 200
    assert response.data["data"]["connectors"][0]["id"] == "postgres"
    assert "X-Internal-API-Key" in get.call_args.kwargs["headers"]


def test_discovery_scope_is_derived_from_authenticated_workspace():
    upstream = Mock(status_code=200)
    upstream.json.return_value = {"success": True, "data": {"schemas": [], "tables": []}}
    request = APIRequestFactory().post(
        "/database/sources/discover/",
        {"engine": "postgres", "configuration": {"host": "db.example", "password": "secret"}},
        format="json",
    )
    force_authenticate(request, user=_principal(workspace_id="19"))
    with patch("database.views.requests.post", return_value=upstream) as post:
        response = DatabaseSourceDiscoveryView.as_view()(request)
    assert response.status_code == 200
    assert post.call_args.kwargs["headers"]["X-Workspace-ID"] == "19"
    assert post.call_args.kwargs["json"]["configuration"]["password"] == "secret"


def test_non_manager_cannot_probe_database_sources():
    request = APIRequestFactory().post("/database/sources/discover/", {}, format="json")
    force_authenticate(request, user=_principal(role="analyst"))
    response = DatabaseSourceDiscoveryView.as_view()(request)
    assert response.status_code == 403


def test_snapshot_table_name_is_tenant_and_dataset_qualified():
    source = _snapshot_source_name(7, 31, {"database": "sales"}, {"schema": "public", "name": "order"})
    assert source == "w7_d31_sales_public_order"
    assert _loader_table_name(source) == "w7_d31_sales_public_order"


def test_preview_lookup_is_workspace_scoped():
    request = APIRequestFactory().get("/database/preview/")
    force_authenticate(request, user=_principal(workspace_id="23"))
    with patch("database.views.Database.objects.get", side_effect=__import__("database.models", fromlist=["Database"]).Database.DoesNotExist) as get:
        response = DatabasePreviewView.as_view()(request)
    assert response.status_code == 404
    get.assert_called_once_with(manager=11, workspace_id=23)


def test_database_snapshot_does_not_complete_during_first_batch_race():
    now = timezone.now()
    database = SimpleNamespace(
        file_size=0, source_kind="database", upload_date=now - timedelta(seconds=5)
    )
    assert _wait_for_initial_rows(database, 0, now=now) is True
    assert _wait_for_initial_rows(database, 3, now=now) is False


def test_genuinely_empty_database_snapshot_completes_after_grace_window():
    now = timezone.now()
    database = SimpleNamespace(
        file_size=0, source_kind="database", upload_date=now - timedelta(seconds=61)
    )
    assert _wait_for_initial_rows(database, 0, now=now) is False


def test_imported_table_metadata_is_opaque_qualified_and_collision_safe():
    tables = _build_imported_tables(
        7,
        31,
        {"database": "sales"},
        [
            {"schema": "public", "name": "order"},
            {"schema": "analytics", "name": "Sales Data"},
        ],
    )
    assert tables[0]["id"] != tables[1]["id"]
    assert tables[0]["destination_table"] == "w7_d31_sales_public_order"
    assert tables[1]["destination_table"] == "w7_d31_sales_analytics_Sales_Data"
    assert _resolve_imported_table(SimpleNamespace(source_tables=tables), tables[1]["id"])["name"] == "Sales Data"


def test_duplicate_imported_table_selection_is_rejected():
    table = {"schema": "public", "name": "orders"}
    try:
        _build_imported_tables(7, 31, {"database": "sales"}, [table, table])
    except ValueError as exc:
        assert "Duplicate" in str(exc)
    else:
        raise AssertionError("duplicate selection was accepted")


def test_preview_selects_only_an_allowlisted_imported_table():
    database = SimpleNamespace(
        etl_status="completed",
        clickhouse_database="etl",
        clickhouse_table_name="w7_d31_sales_public_orders",
        row_count=5,
        column_count=2,
        source_tables=[
            {
                "id": "orders-token",
                "schema": "public",
                "name": "orders",
                "destination_table": "w7_d31_sales_public_orders",
                "row_count": 5,
            },
            {
                "id": "sales-token",
                "schema": "analytics",
                "name": "Sales Data",
                "destination_table": "w7_d31_sales_analytics_Sales_Data",
                "row_count": 4,
            },
        ],
    )
    request = APIRequestFactory().get("/database/preview/?table=sales-token")
    force_authenticate(request, user=_principal())
    client = Mock()
    client.get_table_schema.return_value = {
        "success": True,
        "schema": [{"name": "Total Value", "type": "Nullable(Decimal(18, 2))"}],
    }
    client.get_table_preview.return_value = {
        "success": True,
        "rows": [{"Total Value": "12.34"}],
    }
    client.get_table_count.return_value = {"success": True, "count": 4}
    with patch("database.views.Database.objects.get", return_value=database), patch(
        "database.views.ClickHouseClient", return_value=client
    ):
        response = DatabasePreviewView.as_view()(request)
    assert response.status_code == 200
    assert response.data["data"]["table"]["name"] == "Sales Data"
    assert response.data["data"]["total_rows"] == 4
    client.get_table_preview.assert_called_once_with("etl", "w7_d31_sales_analytics_Sales_Data", limit=5)


def test_preview_rejects_arbitrary_physical_table_name():
    database = SimpleNamespace(
        etl_status="completed",
        clickhouse_database="etl",
        clickhouse_table_name="safe_table",
        source_tables=[{
            "id": "safe-token", "schema": "public", "name": "orders",
            "destination_table": "safe_table",
        }],
    )
    request = APIRequestFactory().get("/database/preview/?table=system.users")
    force_authenticate(request, user=_principal())
    with patch("database.views.Database.objects.get", return_value=database), patch(
        "database.views.ClickHouseClient"
    ) as clickhouse:
        response = DatabasePreviewView.as_view()(request)
    assert response.status_code == 404
    assert response.data["error"]["code"] == "TABLE_NOT_FOUND"
    clickhouse.assert_not_called()


def test_schema_endpoint_is_table_aware_and_workspace_scoped():
    database = SimpleNamespace(
        etl_status="completed",
        clickhouse_database="etl",
        source_tables=[{
            "id": "products-token", "schema": "company_data", "name": "products",
            "destination_table": "w7_d31_sales_company_data_products",
        }],
    )
    request = APIRequestFactory().get("/database/schema/?table=products-token")
    force_authenticate(request, user=_principal(workspace_id="23"))
    client = Mock()
    client.get_table_schema.return_value = {
        "success": True,
        "schema": [{"name": "id", "type": "Int64"}],
    }
    with patch("database.views.Database.objects.get", return_value=database) as get, patch(
        "database.views.ClickHouseClient", return_value=client
    ):
        response = DatabaseSchemaView.as_view()(request)
    assert response.status_code == 200
    get.assert_called_once_with(manager=11, workspace_id=23)
    client.get_table_schema.assert_called_once_with("etl", "w7_d31_sales_company_data_products")
