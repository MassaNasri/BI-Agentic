import unittest
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
        empty = pd.DataFrame([])

        def _read_csv_side_effect(*_args, **kwargs):
            if kwargs.get("nrows") == 1:
                return first
            return empty

        with patch.object(kl.pd, "read_csv", side_effect=_read_csv_side_effect) as mock_read_csv, patch.object(
            listener.csv_strategy, "extract_batch"
        ) as mock_extract_batch:
            mock_extract_batch.side_effect = [
                Mock(rows=[{"id": 1, "name": "a"}], total_rows=1, has_more=False),
            ]
            ok = listener.process_file({"filename": "a.csv", "path": "a.csv"})
        self.assertTrue(ok)
        self.assertEqual(mock_extract_batch.call_args.kwargs["limit"], listener.batch_size)

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
