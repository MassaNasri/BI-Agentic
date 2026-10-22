import os
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")
os.environ.setdefault("APP_ENV", "test")

import django
django.setup()

from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from query_api.public_sql import display_sql
from query_api.views import QueryDefinitionVisualizationView


def test_public_sql_preserves_analytical_expression_with_logical_source_name():
    physical = "w7_d31_c6_orders_8a82"
    shown = display_sql(
        f"SELECT count() AS total FROM etl.{physical}",
        [{"schema": "public", "name": "c6_orders", "destination_table": physical}],
        fallback_table=physical, dataset_id=31,
    )
    assert "count()" in shown.lower()
    assert "public.c6_orders" in shown
    assert physical not in shown
    assert "etl." not in shown


def test_public_sql_rewrites_join_qualifiers_and_fails_closed_on_invalid_sql():
    shown = display_sql(
        "SELECT physical_a.id FROM etl.physical_a JOIN etl.physical_b ON "
        "physical_a.id = physical_b.id",
        [
            {"schema": "public", "name": "orders", "destination_table": "physical_a"},
            {"schema": "sales", "name": "payments", "destination_table": "physical_b"},
        ],
    )
    assert "public.orders" in shown and "sales.payments" in shown
    assert "physical_a" not in shown and "physical_b" not in shown
    assert display_sql("SELECT FROM", [{"name": "orders", "destination_table": "physical_a"}]) == ""


def test_public_visualization_definition_returns_logical_sql():
    physical = "w7_d31_c6_orders_8a82"
    definition_id = uuid4()
    definition = SimpleNamespace(
        id=definition_id, workspace_id=7, dataset_id=31, expires_at=timezone.now(),
        normalized_sql=f"SELECT count() FROM etl.{physical}",
    )
    dataset = SimpleNamespace(
        pk=31, clickhouse_table_name=physical,
        source_tables=[{"schema": "public", "name": "c6_orders", "destination_table": physical}],
    )
    request = APIRequestFactory().get(f"/query/definitions/{definition_id}/visualization/")
    force_authenticate(request, user=SimpleNamespace(id=11, workspace_id=7, is_authenticated=True))
    with (
        patch("query_api.views.AuthorizedQueryDefinition.objects.filter") as definitions,
        patch("database.models.Database.objects.filter") as datasets,
        patch("query_api.views.validate_sql_payload", return_value=(
            {"sql": definition.normalized_sql}, 200, None,
        )),
    ):
        definitions.return_value.first.return_value = definition
        datasets.return_value.first.return_value = dataset
        response = QueryDefinitionVisualizationView.as_view()(request, definition_id=definition_id)
    assert response.status_code == 200
    assert "public.c6_orders" in response.data["sql"]
    assert physical not in response.data["sql"]
