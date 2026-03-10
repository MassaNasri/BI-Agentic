import unittest
from unittest.mock import Mock, patch

from . import kafka_listener as tl


class _FakeLineageTracker:
    @staticmethod
    def deterministic_row_id(*_args, **_kwargs):
        from uuid import uuid4

        return uuid4()

    def record_transformation(self, *_args, **_kwargs):
        return None


class TestTransformerRemediation(unittest.TestCase):
    def _build_listener(self):
        mock_consumer = Mock()
        mock_producer = Mock()
        mock_producer.send = Mock(return_value=True)

        with patch.object(tl, "KafkaMessageConsumer", return_value=mock_consumer), patch.object(
            tl, "KafkaMessageProducer", return_value=mock_producer
        ), patch.object(tl.RawRowListener, "_init_quarantine_manager", return_value=None), patch.object(
            tl.RawRowListener, "_init_quality_metrics_manager", return_value=None
        ), patch.object(
            tl.RawRowListener, "_init_schema_contract_store", return_value=None
        ), patch.object(tl, "LineageTracker", _FakeLineageTracker):
            listener = tl.RawRowListener(batch_size=10)
        return listener

    def test_side_effect_failures_do_not_break_transform_batch(self):
        listener = self._build_listener()
        listener._send_with_retry = Mock(return_value=True)
        listener.lineage_tracker = Mock()
        listener.lineage_tracker.record_transformation.side_effect = Exception("lineage down")

        metrics = Mock()
        metrics.quality_score = 0.9
        listener.quality_metrics_manager = Mock()
        listener.quality_metrics_manager.compute_batch_metrics.return_value = metrics
        listener.quality_metrics_manager.persist_metrics.side_effect = Exception("metrics down")

        listener.transformer_service = Mock()
        listener.transformer_service.process_batch.return_value = (
            [
                {
                    "source": "demo",
                    "status": "success",
                    "warnings": [],
                    "errors": [],
                    "clean_message": {
                        "source": "demo",
                        "data": {"id": 1},
                        "_batch_id": "batch-1",
                        "batch_id": "batch-1",
                        "_transformed_dedup_key": "dedup-1",
                        "_applied_rules": [],
                    },
                }
            ],
            {"processed": 1, "success": 1, "failed": 0, "invalid": 0, "quarantined": 0, "warnings": [], "errors": []},
        )

        ok = listener._process_batch([{"source": "demo", "batch_id": "batch-1", "data": {"id": 1}}])
        self.assertTrue(ok)
