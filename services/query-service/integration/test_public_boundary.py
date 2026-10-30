"""Foundation-C public metadata and foreign-workspace route matrix."""

from unittest.mock import patch

from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver

from bi_platform_shared.public_contract import forbidden_public_metadata_keys
from database.models import Database
from database.serializers import DatabaseSerializer
from database.views import (
    DatabaseDetailView, DatabasePreviewView, DatabaseSchemaView,
    DatabaseSnapshotStartView, DatabaseSourceDiscoveryView, DatabaseSourceTestView,
    DatasetListView,
)
from integration.metadata import public_source
from integration.models import DataSource
from integration.tests import principal, request
from integration.views import (
    SourceCredentialView, SourceDetailView, SourceReplacementActionView,
    SourceReplacementView, SourcesView,
)
from query_api.views import QueryExecuteInternalView


class PublicBoundaryTests(TestCase):
    def test_public_query_route_inventory_is_explicit(self):
        def paths(patterns, prefix=""):
            for entry in patterns:
                name = prefix + str(entry.pattern)
                if isinstance(entry, URLResolver):
                    yield from paths(entry.url_patterns, name)
                elif isinstance(entry, URLPattern) and name.startswith(("database/", "query/")):
                    yield name

        actual = set(paths(get_resolver().url_patterns))
        self.assertEqual(actual, {
            "database/health/", "database/upload/", "database/datasets/", "database/",
            "database/preview/", "database/schema/", "database/sources/capabilities/",
            "database/sources/", "database/sources/<uuid:source_id>/",
            "database/sources/<uuid:source_id>/credential/<str:action>/",
            "database/sources/<uuid:source_id>/replacement/",
            "database/sources/<uuid:source_id>/replacement/<str:action>/",
            "database/sources/test/", "database/sources/discover/", "database/sources/snapshot/",
            "database/sources/sqlite/prepare/", "query/health/", "query/validate/",
            "query/execute/", "query/cancel/", "query/definitions/",
            "query/definitions/<uuid:definition_id>/visualization/",
        })

    def setUp(self):
        self.source = DataSource.objects.create(
            workspace_id=7, created_by=11, name="Sales", engine="postgresql",
            connection_metadata={"host": "internal-source.example", "database": "internal-db"},
            selected_tables=[{"schema": "public", "name": "sales"}],
        )
        self.dataset = Database.objects.create(
            manager=11, workspace_id=7, filename="sales", file_size=0, file_path="private/path",
            source=self.source, etl_status="completed", clickhouse_database="private_ch",
            clickhouse_table_name="private_table",
            source_tables=[{"id": "logical-token", "name": "sales", "destination_table": "private_table"}],
            etl_message="synthetic-upstream-secret",
        )

    def test_public_success_contract_excludes_internal_binding(self):
        payloads = [
            public_source(self.source),
            DatabaseSerializer(self.dataset).data,
            SourcesView.as_view()(request("get", "/database/sources/", principal())).data,
            DatasetListView.as_view()(request("get", "/database/datasets/", principal())).data,
        ]
        for payload in payloads:
            self.assertFalse(forbidden_public_metadata_keys(payload), payload)
            self.assertNotIn("synthetic-upstream-secret", str(payload))
            self.assertNotIn("private_ch", str(payload))
            self.assertNotIn("private_table", str(payload))

    def test_foreign_workspace_route_matrix_fails_before_upstream(self):
        foreign = principal(8)
        source_id = self.source.pk
        dataset_id = self.dataset.pk
        cases = [
            ("source-list", SourcesView.as_view(), request("get", "/database/sources/", foreign), {}),
            ("source-get", SourceDetailView.as_view(), request("get", "/database/sources/x/", foreign), {"source_id": source_id}),
            ("source-patch", SourceDetailView.as_view(), request("patch", "/database/sources/x/", foreign, {"state": "disabled"}), {"source_id": source_id}),
            ("source-retire", SourceDetailView.as_view(), request("delete", "/database/sources/x/", foreign), {"source_id": source_id}),
            *[(f"credential-{action}", SourceCredentialView.as_view(), request("post", "/credential/", foreign, {}), {"source_id": source_id, "action": action}) for action in ("configure", "rotate", "revoke")],
            ("replacement-create", SourceReplacementView.as_view(), request("post", "/replacement/", foreign, {}), {"source_id": source_id}),
            *[(f"replacement-{action}", SourceReplacementActionView.as_view(), request("post", "/replacement/action/", foreign, {}), {"source_id": source_id, "action": action}) for action in ("test", "discover", "snapshot", "cutover", "rollback")],
            ("test", DatabaseSourceTestView.as_view(), request("post", "/database/sources/test/", foreign, {"source_id": str(source_id)}), {}),
            ("discover", DatabaseSourceDiscoveryView.as_view(), request("post", "/database/sources/discover/", foreign, {"source_id": str(source_id)}), {}),
            ("snapshot", DatabaseSnapshotStartView.as_view(), request("post", "/database/sources/snapshot/", foreign, {"source_id": str(source_id)}), {}),
            ("dataset-list", DatasetListView.as_view(), request("get", "/database/datasets/", foreign), {}),
            ("dataset-get", DatabaseDetailView.as_view(), request("get", f"/database/?dataset_id={dataset_id}", foreign), {}),
            ("dataset-preview", DatabasePreviewView.as_view(), request("get", f"/database/preview/?dataset_id={dataset_id}", foreign), {}),
            ("dataset-schema", DatabaseSchemaView.as_view(), request("get", f"/database/schema/?dataset_id={dataset_id}", foreign), {}),
            ("dataset-delete", DatabaseDetailView.as_view(), request("delete", f"/database/?dataset_id={dataset_id}", foreign), {}),
            ("query-execute", QueryExecuteInternalView.as_view(), request("post", "/query/execute/", foreign, {"dataset_id": dataset_id, "sql": "SELECT 1"}), {}),
        ]
        with patch("database.views.requests.post", side_effect=AssertionError("unexpected upstream")), patch(
            "integration.views.requests.post", side_effect=AssertionError("unexpected upstream")
        ):
            for name, view, req, kwargs in cases:
                with self.subTest(route=name):
                    response = view(req, **kwargs)
                    if name.endswith("-list"):
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.data["data"], [])
                    else:
                        self.assertIn(response.status_code, {403, 404, 422})
                        self.assertNotIn("private_table", str(response.data))
                        self.assertFalse(forbidden_public_metadata_keys(response.data))
