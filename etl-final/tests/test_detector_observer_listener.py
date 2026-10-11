import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "detector-service" / "detector"))


def test_detector_is_an_independent_non_mutating_observer(monkeypatch):
    from core import kafka_listener as listener

    monkeypatch.setenv("DETECTOR_CONSUMER_GROUP", "detector-test-observer")
    record = Mock()
    consumer = Mock()
    consumer.listen_committable.return_value = iter(
        [
            (
                {
                    "source": "quality.csv",
                    "rows": [{"data": {"name": " Alice "}}],
                    "workspace_id": 23,
                    "dataset_id": "dataset-91",
                    "ingestion_job_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                },
                record,
            )
        ]
    )
    consumer.commit.return_value = True
    producer = Mock()
    producer.send.return_value = True

    with patch.object(listener, "KafkaMessageConsumer", return_value=consumer) as consumer_cls, patch.object(
        listener, "KafkaMessageProducer", return_value=producer
    ):
        listener.start_listener()

    consumer_cls.assert_called_once_with(
        "extracted_rows_topic",
        consumer_group="detector-test-observer",
    )
    consumer.commit.assert_called_once_with(record)
    consumer.rewind.assert_not_called()

    sent_topics = [call.args[0] for call in producer.send.call_args_list]
    assert sent_topics == ["metadata_topic"]
    payload = producer.send.call_args.args[1]
    assert payload["metadata_type"] == "detection"
    assert payload["pipeline_stage"] == "detect"
    assert payload["rows_observed"] == 1
    assert payload["workspace_id"] == 23
    assert payload["dataset_id"] == "dataset-91"
    assert payload["ingestion_job_id"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_detection_metadata_is_valid():
    from shared.utils.metadata_schema import MetadataSchema

    payload = MetadataSchema.create_detection_metadata(
        source_id="quality.csv",
        rows_observed=2,
    )

    assert MetadataSchema.validate_metadata(payload) == (True, None)
    assert datetime.fromisoformat(payload["timestamp"]).utcoffset() == timedelta(0)
