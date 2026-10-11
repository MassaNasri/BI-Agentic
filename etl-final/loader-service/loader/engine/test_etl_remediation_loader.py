import unittest
import math
from datetime import datetime
from unittest.mock import Mock, patch
from uuid import uuid4

from . import kafka_listener as ll
from .clickhouse_client import ClickHouseClient
from shared.utils.idempotency_manager import IdempotencyClaim, IdempotencyKey


class _FakeLineageTracker:
    @staticmethod
    def deterministic_row_id(*_args, **_kwargs):
        from uuid import uuid4

        return uuid4()

    def record_transformation(self, *_args, **_kwargs):
        return None

    def record_transformations(self, records):
        return len(records)


class TestLoaderRemediation(unittest.TestCase):
    def _build_listener(self):
        mock_loader = Mock()
        mock_loader.client = Mock()
        mock_loader.client.client = Mock()

        mock_consumer = Mock()
        mock_producer = Mock()
        mock_producer.send = Mock(return_value=True)

        with patch.object(ll, "KafkaMessageConsumer", return_value=mock_consumer), patch.object(
            ll, "KafkaMessageProducer", return_value=mock_producer
        ), patch.object(ll, "LoaderLogic", return_value=mock_loader), patch.object(
            ll.CleanRowListener, "_init_quarantine_manager", return_value=None
        ), patch.object(ll, "LineageTracker", _FakeLineageTracker):
            listener = ll.CleanRowListener(batch_size=100)
        return listener, mock_loader

    def test_ensure_table_schema_evolves_new_columns(self):
        listener, mock_loader = self._build_listener()
        mock_loader.client.table_exists.return_value = True
        mock_loader.client.get_table_schema.return_value = {"id": "Int64"}
        mock_loader.client.add_columns_if_missing = Mock()

        table_name = listener._ensure_table_schema("demo.table", {"id": 1, "new_col": "x"})

        self.assertEqual(table_name, "demo_table")
        mock_loader.client.add_columns_if_missing.assert_called_once()
        added_columns = mock_loader.client.add_columns_if_missing.call_args[0][1]
        self.assertIn("new_col", added_columns)

    def test_schema_only_message_materializes_zero_row_table(self):
        listener, mock_loader = self._build_listener()
        mock_loader.client.table_exists.return_value = False
        message = {
            "source": "w7_d31_sales_public_empty_table",
            "schema_only": True,
            "rows": [],
            "columns": [
                {"column_name": "id", "data_type": "integer"},
                {"column_name": "Display Name", "data_type": "text"},
            ],
            "workspace_id": 7,
            "dataset_id": 31,
            "ingestion_job_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        }

        self.assertTrue(listener._process_message(message))
        mock_loader.client.create_table.assert_called_once()
        table_name, columns = mock_loader.client.create_table.call_args.args[:2]
        self.assertEqual(table_name, "w7_d31_sales_public_empty_table")
        self.assertEqual(columns, {"id": "Nullable(String)", "Display_Name": "Nullable(String)"})
        self.assertEqual(listener.table_schema_scopes[table_name], message["ingestion_job_id"])

    def test_cached_schema_skips_per_row_clickhouse_metadata_queries(self):
        listener, mock_loader = self._build_listener()
        listener.table_schemas["demo_table"] = {
            "id": "Nullable(Int64)",
            "name": "Nullable(String)",
        }
        listener.table_schema_scopes["demo_table"] = "job-1"

        table_name = listener._ensure_table_schema(
            "demo.table", {"id": 2, "name": "b"}, "job-1"
        )

        self.assertEqual(table_name, "demo_table")
        mock_loader.client.table_exists.assert_not_called()
        mock_loader.client.get_table_schema.assert_not_called()
        mock_loader.client.add_columns_if_missing.assert_not_called()

    def test_new_ingestion_job_recreates_a_table_deleted_by_query_service(self):
        listener, mock_loader = self._build_listener()
        listener.table_schemas["demo_table"] = {
            "id": "Nullable(Int64)",
            "name": "Nullable(String)",
        }
        listener.table_schema_scopes["demo_table"] = "job-1"
        mock_loader.client.table_exists.return_value = False

        table_name = listener._ensure_table_schema(
            "demo.table", {"id": 2, "name": "b"}, "job-2"
        )

        self.assertEqual(table_name, "demo_table")
        mock_loader.client.table_exists.assert_called_once_with("demo_table")
        mock_loader.client.create_table.assert_called_once()
        created_columns = mock_loader.client.create_table.call_args.args[1]
        self.assertEqual(created_columns["id"], "Nullable(Int64)")
        self.assertEqual(listener.table_schema_scopes["demo_table"], "job-2")

    def test_process_row_sanitizes_columns_and_uses_datetime_objects(self):
        listener, _ = self._build_listener()
        listener._ensure_table_schema = Mock(return_value="demo_table")
        listener.idempotency_manager.generate_row_hash = Mock(return_value="hash-1")

        message = {
            "source": "demo.table",
            "data": {"a); DROP TABLE x;--": "v1", "normal": "v2"},
            "_batch_id": "b1",
            "_extracted_at": "2026-03-01T12:00:00",
            "_cleaned_at": "2026-03-01T12:01:00Z",
        }

        table_name = listener.process_row(message)
        self.assertEqual(table_name, "demo_table")

        row = listener.batch_buffers["demo_table"][0]
        self.assertIn("_loaded_at", row)
        self.assertIsInstance(row["_loaded_at"], datetime)
        self.assertIsInstance(row["_extracted_at"], datetime)
        self.assertIsInstance(row["_cleaned_at"], datetime)
        self.assertEqual(row["_transformed_dedup_key"], "hash-1")
        self.assertTrue(all(ch.isalnum() or ch == "_" for key in row.keys() for ch in key))
        self.assertNotIn("a); DROP TABLE x;--", row)

    def test_infer_datetime64_for_system_and_iso_columns(self):
        listener, _ = self._build_listener()
        self.assertEqual(listener._infer_clickhouse_type("_loaded_at", "2026-03-01T12:00:00"), "DateTime64(3)")
        self.assertEqual(listener._infer_clickhouse_type("_extracted_at", "2026-03-01T12:00:00Z"), "DateTime64(3)")
        self.assertEqual(listener._infer_clickhouse_type("event_time", "2026-03-01T12:00:00+00:00"), "Nullable(DateTime64(3))")
        self.assertEqual(listener._infer_clickhouse_type("name", "alice"), "Nullable(String)")
        self.assertEqual(listener._infer_clickhouse_type("optional", None), "Nullable(String)")
        self.assertEqual(listener._infer_clickhouse_type("quantity", 7), "Nullable(Int64)")

    def test_flush_batch_claims_before_insert_and_skips_post_marking(self):
        listener, mock_loader = self._build_listener()
        table = "demo_table"
        source = "demo.table"
        listener.batch_buffers[table] = [{"a": 1, "_transformed_dedup_key": "h1"}]
        listener.pending_idempotency_keys[table] = ["h1"]
        listener.table_sources[table] = source
        listener.buffered_rows_total = 1

        claim = IdempotencyClaim(
            key=IdempotencyKey(source_id=source, batch_id=f"load:{source}:legacy", row_hash="h1"),
            claim_row_id=uuid4(),
        )
        listener.idempotency_manager.claim_new_keys = Mock(return_value=[claim])
        listener.idempotency_manager.rollback_claims = Mock(return_value=True)
        listener.idempotency_manager.mark_processed_batch = Mock(return_value=True)
        mock_loader.load_batch_resilient.return_value = 1

        ok = listener._flush_batch(table, source)

        self.assertTrue(ok)
        listener.idempotency_manager.claim_new_keys.assert_called_once()
        listener.idempotency_manager.mark_processed_batch.assert_not_called()

    def test_retry_same_batch_does_not_insert_duplicates_when_claim_is_reused(self):
        listener, mock_loader = self._build_listener()
        table = "demo_table"
        source = "demo.table"
        row = {"a": 1, "_transformed_dedup_key": "h1"}
        claim = IdempotencyClaim(
            key=IdempotencyKey(source_id=source, batch_id=f"load:{source}:legacy", row_hash="h1"),
            claim_row_id=uuid4(),
        )
        listener.idempotency_manager.rollback_claims = Mock(return_value=True)
        listener.idempotency_manager.mark_processed_batch = Mock(return_value=True)
        listener.idempotency_manager.claim_new_keys = Mock(side_effect=[[claim], []])
        mock_loader.load_batch_resilient.return_value = 1

        # First attempt: one row claimed and inserted.
        listener.batch_buffers[table] = [row]
        listener.pending_idempotency_keys[table] = ["h1"]
        listener.table_sources[table] = source
        listener.buffered_rows_total = 1
        assert listener._flush_batch(table, source) is True

        # Retry with same row/hash: claim call returns empty, so no second insert.
        listener.batch_buffers[table] = [row]
        listener.pending_idempotency_keys[table] = ["h1"]
        listener.table_sources[table] = source
        listener.buffered_rows_total = 1
        assert listener._flush_batch(table, source) is True

        self.assertEqual(mock_loader.load_batch_resilient.call_count, 1)


class TestClickHouseClientRemediation(unittest.TestCase):
    def _build_client(self):
        client = ClickHouseClient.__new__(ClickHouseClient)
        client.client = Mock()
        client.insert_retries = 1
        return client

    def test_insert_batch_uses_union_of_columns_and_none_for_missing(self):
        client = self._build_client()
        rows = [{"a": 1}, {"b": 2}]

        inserted = client.insert_batch("safe_table", rows, batch_size=100)

        self.assertEqual(inserted, 2)
        query, values = client.client.execute.call_args[0][0], client.client.execute.call_args[0][1]
        self.assertIn("`a`", query)
        self.assertIn("`b`", query)
        self.assertEqual(values, [(1, None), (None, 2)])

    def test_insert_batch_sanitizes_malicious_identifiers(self):
        client = self._build_client()
        rows = [{"a); DROP TABLE x;--": 1}]

        client.insert_batch("safe_table", rows, batch_size=100)

        query = client.client.execute.call_args[0][0]
        self.assertIn("INSERT INTO `safe_table`", query)
        self.assertNotIn("DROP TABLE", query)
        self.assertIn("`a_DROP_TABLE_x_`", query)

    def test_add_columns_if_missing_uses_safe_alter_queries(self):
        client = self._build_client()
        client.add_columns_if_missing("safe_table", {"new col": "String", "1evil": "Int64"})

        executed_queries = [call[0][0] for call in client.client.execute.call_args_list]
        self.assertEqual(len(executed_queries), 2)
        self.assertTrue(all("ALTER TABLE `safe_table` ADD COLUMN IF NOT EXISTS" in q for q in executed_queries))
        self.assertTrue(any("`new_col` String" in q for q in executed_queries))
        self.assertTrue(any("`c_1evil` Int64" in q for q in executed_queries))

    def test_dirty_values_are_coerced_or_nulled_without_dropping_rows(self):
        rows = [
            {"age": 23, "balance": "$1,200.50", "active": "Y"},
            {"age": "twenty-nine", "balance": "1.234,56", "active": "maybe"},
            {"age": math.nan, "balance": "=1+1", "active": 0},
        ]
        schema = {
            "age": "Nullable(Int64)",
            "balance": "Nullable(Float64)",
            "active": "Nullable(Bool)",
        }

        normalized, issues = ClickHouseClient.normalize_rows_for_schema(rows, schema)

        self.assertEqual(len(normalized), 3)
        self.assertEqual(normalized[0], {"age": 23, "balance": 1200.5, "active": True})
        self.assertEqual(normalized[1], {"age": None, "balance": 1234.56, "active": None})
        self.assertEqual(normalized[2], {"age": None, "balance": None, "active": False})
        self.assertEqual(issues, {"age": 1, "active": 1, "balance": 1})

    def test_non_nullable_pipeline_metadata_remains_strict(self):
        with self.assertRaises(ValueError):
            ClickHouseClient.normalize_rows_for_schema(
                [{"_loaded_at": "not-a-date"}],
                {"_loaded_at": "DateTime64(3)"},
            )

    def test_idempotency_is_scoped_to_ingestion_job(self):
        listener = ll.CleanRowListener.__new__(ll.CleanRowListener)
        first = listener._build_idempotency_key("source.csv", "same-row", "job-1")
        retry = listener._build_idempotency_key("source.csv", "same-row", "job-1")
        replacement = listener._build_idempotency_key("source.csv", "same-row", "job-2")

        self.assertEqual(first.to_dedup_key(), retry.to_dedup_key())
        self.assertNotEqual(first.to_dedup_key(), replacement.to_dedup_key())
