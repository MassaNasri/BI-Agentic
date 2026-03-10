import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from . import kafka_listener as kl
from .extraction_strategy import Batch
from .csv_extraction_strategy import CSVExtractionStrategy
from .extraction_strategy import ExtractionConfig


class _FakeLineageTracker:
    @staticmethod
    def deterministic_row_id(*_args, **_kwargs):
        from uuid import uuid4

        return uuid4()

    def record_transformation(self, *_args, **_kwargs):
        return None


class TestExtractorRemediation(unittest.TestCase):
    def _build_listener(self):
        mock_consumer = Mock()
        mock_producer = Mock()
        mock_producer.send = Mock(return_value=True)

        with patch.object(kl, "KafkaMessageConsumer", return_value=mock_consumer), patch.object(
            kl, "KafkaMessageProducer", return_value=mock_producer
        ), patch.object(kl, "Client"), patch.object(kl, "LineageTracker", _FakeLineageTracker):
            listener = kl.ConnectionListener()
        listener._send_with_retry = Mock(return_value=True)
        return listener

    def test_process_database_keeps_table_batches_separate(self):
        listener = self._build_listener()
        listener.idempotency_manager = None
        listener.batch_size = 10

        mock_connection = Mock()
        mock_cursor = Mock()
        state = {"last_query": ""}

        def execute(query, *_args, **_kwargs):
            state["last_query"] = query

        def fetchall():
            if state["last_query"].strip().upper().startswith("SHOW TABLES"):
                return [("table_a",), ("table_b",)]
            return []

        mock_cursor.execute.side_effect = execute
        mock_cursor.fetchall.side_effect = fetchall
        mock_cursor.description = [("id",)]
        mock_connection.cursor.return_value = mock_cursor
        listener.db_connector.connect = Mock(return_value=mock_connection)
        listener.database_strategy.detect_primary_key = Mock(return_value="id")

        def extract_batch(config, offset, limit):
            table = config.connection_params["table"]
            if offset > 0:
                return Batch(
                    rows=[],
                    batch_id="batch",
                    source_id=config.source_id,
                    offset=offset,
                    total_rows=0,
                    has_more=False,
                    metadata={"pagination_mode": "keyset"},
                )
            row_id = 1 if table == "table_a" else 2
            return Batch(
                rows=[{"id": row_id}],
                batch_id="batch",
                source_id=config.source_id,
                offset=0,
                total_rows=1,
                has_more=False,
                metadata={"pagination_mode": "keyset", "next_last_pk": row_id},
            )

        listener.database_strategy.extract_batch = Mock(side_effect=extract_batch)

        sent_batches = []

        def _capture_send(base_message, rows):
            sent_batches.append((dict(base_message), [dict(row) for row in rows]))
            return True

        listener._send_batch = _capture_send

        ok = listener.process_database(
            {
                "type": "database",
                "db_type": "mysql",
                "host": "localhost",
                "user": "root",
                "password": "pw",
                "database": "demo",
                "port": 3306,
            }
        )

        self.assertTrue(ok)
        self.assertEqual(len(sent_batches), 2)
        first_meta, first_rows = sent_batches[0]
        second_meta, second_rows = sent_batches[1]
        self.assertEqual(first_meta["table"], "table_a")
        self.assertEqual(second_meta["table"], "table_b")
        self.assertTrue(all(row["table"] == "table_a" for row in first_rows))
        self.assertTrue(all(row["table"] == "table_b" for row in second_rows))

    def test_process_file_uses_streaming_csv_iterator(self):
        listener = self._build_listener()
        listener.idempotency_manager = None
        listener.csv_strategy.extract_batch = Mock()
        listener.csv_strategy.iter_batches = Mock(return_value=iter([[{"id": 1}], [{"id": 2}]]))
        listener._send_batch = Mock(return_value=True)

        with patch.object(kl.pd, "read_csv", return_value=pd.DataFrame([{"id": 1}])):
            ok = listener.process_file({"filename": "demo.csv", "path": "demo.csv"})

        self.assertTrue(ok)
        listener.csv_strategy.iter_batches.assert_called_once()
        listener.csv_strategy.extract_batch.assert_not_called()
        self.assertGreaterEqual(listener._send_batch.call_count, 1)

    def test_csv_strategy_iter_batches_uses_chunksize_streaming(self):
        strategy = CSVExtractionStrategy()
        seen_kwargs = {}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
            tmp.write("id\n1\n2\n")
            csv_path = tmp.name

        try:
            config = ExtractionConfig(
                source_id="csv_source",
                source_type="csv",
                connection_params={"file_path": csv_path},
                batch_size=2,
            )

            def _fake_read_csv(*_args, **kwargs):
                seen_kwargs.update(kwargs)
                yield pd.DataFrame([{"id": 1}])
                yield pd.DataFrame([{"id": 2}])

            with patch("engine.csv_extraction_strategy.pd.read_csv", side_effect=_fake_read_csv):
                batches = list(strategy.iter_batches(config, batch_size=2))

            self.assertEqual(seen_kwargs.get("chunksize"), 2)
            self.assertEqual(len(batches), 2)
        finally:
            os.unlink(csv_path)

    def test_process_file_bounds_error_samples_and_tracks_error_count(self):
        listener = self._build_listener()
        listener.batch_size = 50
        listener.max_error_entries = 3

        faulty_idempotency = Mock()
        faulty_idempotency.generate_row_hash.side_effect = Exception("hash failed")
        listener.idempotency_manager = faulty_idempotency
        listener.csv_strategy.iter_batches = Mock(return_value=iter([[{"v": i} for i in range(7)]]))

        extraction_metadata = {}

        def _capture_metadata(topic, message, _context):
            if topic == "metadata_topic" and "rows_processed" in message:
                extraction_metadata.update(message)
            return True

        listener._send_with_retry = Mock(side_effect=_capture_metadata)

        with patch.object(kl.pd, "read_csv", return_value=pd.DataFrame([{"v": 1}])):
            ok = listener.process_file({"filename": "bad.csv", "path": "bad.csv"})

        self.assertFalse(ok)
        self.assertEqual(extraction_metadata.get("error_count"), 7)
        self.assertEqual(extraction_metadata.get("error_sample_count"), 3)
        self.assertEqual(len(extraction_metadata.get("errors", [])), 3)

    def test_lineage_side_effect_failure_does_not_break_file_processing(self):
        listener = self._build_listener()
        listener.idempotency_manager = None
        listener.lineage_tracker = Mock()
        listener.lineage_tracker.record_transformation.side_effect = Exception("lineage down")
        listener.csv_strategy.iter_batches = Mock(return_value=iter([[{"id": 1}]]))
        listener._send_batch = Mock(return_value=True)

        with patch.object(kl.pd, "read_csv", return_value=pd.DataFrame([{"id": 1}])):
            ok = listener.process_file({"filename": "lineage.csv", "path": "lineage.csv"})

        self.assertTrue(ok)

    def test_extraction_strategy_has_single_enrich_rows_method(self):
        strategy_path = Path(__file__).with_name("extraction_strategy.py")
        content = strategy_path.read_text(encoding="utf-8")
        self.assertEqual(content.count("def enrich_rows_with_lineage("), 1)
