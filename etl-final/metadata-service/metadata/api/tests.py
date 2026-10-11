from types import SimpleNamespace
from uuid import UUID

from django.test import SimpleTestCase

from .query_builder import ALLOWED_METADATA_TABLES, build_select_query
from .views import (
    ConnectionLogsView,
    ExtractLogsView,
    LoadLogsView,
    SchemaLogsView,
    TransformLogsView,
)


class UnifiedMetadataTableTests(SimpleTestCase):
    def test_public_log_views_read_listener_tables(self):
        self.assertEqual(ConnectionLogsView.table_name, "connection_metadata")
        self.assertEqual(SchemaLogsView.table_name, "schema_metadata")
        self.assertEqual(ExtractLogsView.table_name, "extraction_metadata")
        self.assertEqual(TransformLogsView.table_name, "cleaning_metadata")
        self.assertEqual(LoadLogsView.table_name, "loading_metadata")

    def test_all_listener_tables_are_allowlisted(self):
        self.assertEqual(
            ALLOWED_METADATA_TABLES,
            {
                "connection_metadata",
                "schema_metadata",
                "extraction_metadata",
                "cleaning_metadata",
                "loading_metadata",
            },
        )

    def test_query_is_exactly_scoped(self):
        scope = SimpleNamespace(
            workspace_id=23,
            dataset_id="dataset-91",
            ingestion_job_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        )
        query = build_select_query("connection_metadata", scope)
        self.assertIn("workspace_id = 23", query)
        self.assertIn('dataset_id = "dataset-91"', query)
        self.assertIn('ingestion_job_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"', query)

    def test_legacy_or_arbitrary_tables_are_rejected(self):
        scope = SimpleNamespace(workspace_id=1, dataset_id="d", ingestion_job_id=UUID(int=0))
        with self.assertRaises(ValueError):
            build_select_query("connection_logs", scope)
        with self.assertRaises(ValueError):
            build_select_query("users", scope)
