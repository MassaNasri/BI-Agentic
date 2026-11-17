import unittest
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import pandas as pd

from .row_extractor import RowExtractor
from . import kafka_listener as kl


class TestRowExtractorP0Fixes(unittest.TestCase):
    def test_streaming_fetch_and_tuple_mapping(self):
        connection = Mock()
        connection.__class__.__module__ = "psycopg2.extensions"
        cursor = Mock()
        cursor.description = [("id",), ("name",)]
        cursor.fetchmany.side_effect = [[(1, "alice")], []]
        cursor.fetchall.return_value = []
        connection.cursor.return_value = cursor

        extractor = RowExtractor()
        rows = list(extractor.extract_rows(connection, ["users"]))

        self.assertEqual(rows, [("users", {"id": 1, "name": "alice"})])
        cursor.fetchall.assert_not_called()


class TestExtractorListenerP0Fixes(unittest.TestCase):
    def test_delayed_sqlite_event_cannot_process_after_queue_window(self):
        listener, _, _ = self._build_listener()
        with patch.object(listener.db_connector, 'get_connector') as connector:
            self.assertFalse(listener.process_database({
                'db_type': 'sqlite',
                'snapshot_queued_at': time.time() - 301,
                'snapshot_max_queue_delay_seconds': 300,
                'configuration': {'sqlite_token': 'sqlite_23_' + 'a' * 32 + '.db'},
                'workspace_id': 23,
            }))
        connector.assert_not_called()

    def test_v2_event_without_reference_cannot_use_legacy_configuration(self):
        listener, _, _ = self._build_listener()
        message = {
            'type': 'database', 'db_type': 'postgresql', 'contract_version': 2,
            'workspace_id': 23, 'dataset_id': '42', 'ingestion_job_id': 'job',
            'configuration': {'host': 'example.org', 'password': 'legacy-secret'},
        }
        with patch.object(listener.db_connector, 'get_connector') as connector:
            self.assertFalse(listener.process_database(message))
        connector.assert_not_called()

    def test_v2_event_uses_resolved_configuration(self):
        listener, _, _ = self._build_listener()
        reference = {
            'source_id': 'source', 'workspace_id': 23, 'dataset_id': '42',
            'job_id': 'job', 'credential_id': 'credential', 'credential_version': 1,
        }
        message = {
            'type': 'database', 'db_type': 'postgresql', 'contract_version': 2,
            'workspace_id': 23, 'dataset_id': '42', 'ingestion_job_id': 'job',
            'integration_source_id': 'source', 'configuration_version': 3,
            'credential_ref': reference, 'configuration': {'host': 'ignored.example'},
        }
        resolved = {'host': 'real.example', 'database': 'db', 'password': 'resolved-secret'}
        connector = Mock()
        connector.key = 'postgresql'
        connector.validate_configuration.return_value = resolved
        connector.connect.side_effect = RuntimeError('stop after credential selection')
        with patch('shared.security.credential_client.resolve_source_execution',
                   return_value=('postgresql', resolved, 'direct_secure_internet', 3)) as resolver, \
             patch.object(listener.db_connector, 'get_connector', return_value=connector) as get_connector:
            self.assertFalse(listener.process_database(message))
        resolver.assert_called_once_with(reference, service='etl-extractor')
        self.assertEqual(get_connector.call_args.args[0]['host'], 'real.example')
        self.assertEqual(get_connector.call_args.args[0]['password'], 'resolved-secret')

    def test_v2_event_rejects_mismatched_configuration_version(self):
        listener, _, _ = self._build_listener()
        reference = {
            'source_id': 'source', 'workspace_id': 23, 'dataset_id': '42',
            'job_id': 'job', 'credential_id': 'credential', 'credential_version': 1,
        }
        message = {
            'type': 'database', 'db_type': 'postgresql', 'contract_version': 2,
            'workspace_id': 23, 'dataset_id': '42', 'ingestion_job_id': 'job',
            'integration_source_id': 'source', 'configuration_version': 3,
            'credential_ref': reference,
        }
        with patch('shared.security.credential_client.resolve_source_execution',
                   return_value=('postgresql', {'host': 'real.example'},
                                 'direct_secure_internet', 4)), \
             patch.object(listener.db_connector, 'get_connector') as connector:
            self.assertFalse(listener.process_database(message))
        connector.assert_not_called()

    def test_completed_sqlite_cleanup_requires_exact_workspace_and_generated_name(self):
        with TemporaryDirectory() as root, patch.dict(os.environ, {'ETL_SQLITE_ROOT': root}):
            own = Path(root) / ('sqlite_23_' + 'a' * 32 + '.db')
            other = Path(root) / ('sqlite_24_' + 'b' * 32 + '.db')
            unrelated = Path(root) / 'notes.db'
            for path in (own, other, unrelated):
                path.write_bytes(b'SQLite format 3\x00')
            self.assertFalse(kl.cleanup_completed_sqlite_upload({'sqlite_token': other.name}, 23))
            self.assertFalse(kl.cleanup_completed_sqlite_upload({'sqlite_token': unrelated.name}, 23))
            self.assertTrue(kl.cleanup_completed_sqlite_upload({'sqlite_token': own.name}, 23))
            self.assertFalse(own.exists())
            self.assertTrue(other.exists())
            self.assertTrue(unrelated.exists())

    def _build_listener(self):
        mock_consumer = Mock()
        mock_producer = Mock()
        mock_producer.send.return_value = True
        mock_lineage = Mock()
        mock_lineage.record_transformation.return_value = None
        with patch.object(kl, "KafkaMessageConsumer", return_value=mock_consumer), patch.object(
            kl, "KafkaMessageProducer", return_value=mock_producer
        ), patch.object(kl, "Client"), patch.object(kl, "LineageTracker", return_value=mock_lineage):
            listener = kl.ConnectionListener()
        listener.idempotency_manager = None
        return listener, mock_consumer, mock_producer

    def test_process_file_reads_csv_in_chunks(self):
        listener, _, _ = self._build_listener()
        first = pd.DataFrame([{"id": 1, "name": "a"}])
        def _read_csv_side_effect(*_args, **kwargs):
            if kwargs.get("nrows") == 1:
                return first
            raise AssertionError("streaming must use iter_batches after the schema read")

        with patch.object(kl.pd, "read_csv", side_effect=_read_csv_side_effect) as mock_read_csv, patch.object(
            listener.csv_strategy, "iter_batches", return_value=iter([[{"id": 1, "name": "a"}]])
        ) as mock_iter_batches:
            ok = listener.process_file({"filename": "a.csv", "path": "a.csv"})
        self.assertTrue(ok)
        self.assertEqual(mock_iter_batches.call_args.kwargs["batch_size"], listener.batch_size)

    def test_send_batch_retries_then_dlq(self):
        listener, _, producer = self._build_listener()
        listener.send_retries = 2
        producer.send.side_effect = [False, False, True]
        ok = listener._send_batch({"source": "s", "batch_id": "b"}, [{"data": {"id": 1}}])
        self.assertTrue(ok)
        self.assertEqual(producer.send.call_args_list[-1][0][0], listener.dlq_topic)

    def test_listener_commits_only_on_success(self):
        listener, consumer, _ = self._build_listener()
        record = Mock()
        consumer.listen_committable.return_value = iter(
            [
                ({"type": "file", "filename": "a.csv", "path": "a.csv"}, record),
                ({"type": "file", "filename": "b.csv", "path": "b.csv"}, record),
            ]
        )
        listener.process_file = Mock(side_effect=[True, False])

        listener.listen()

        self.assertEqual(consumer.commit.call_count, 1)


if __name__ == "__main__":
    unittest.main()
