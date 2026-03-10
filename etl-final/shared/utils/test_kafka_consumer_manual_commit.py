import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from kafka import TopicPartition

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.utils.kafka_consumer import KafkaMessageConsumer  # noqa: E402


@patch("shared.utils.kafka_consumer.KafkaConsumer")
def test_auto_commit_disabled_by_default(mock_kafka_consumer):
    mock_kafka_consumer.return_value = MagicMock()
    consumer = KafkaMessageConsumer("test_topic", validate_messages=False)
    consumer.connect()
    kwargs = mock_kafka_consumer.call_args.kwargs
    assert kwargs["enable_auto_commit"] is False


def test_commit_record_commits_next_offset():
    consumer = KafkaMessageConsumer("test_topic", validate_messages=False)
    consumer.consumer = Mock()
    record = Mock(topic="test_topic", partition=2, offset=10)

    ok = consumer.commit(record)

    assert ok is True
    kwargs = consumer.consumer.commit.call_args.kwargs
    offsets = kwargs["offsets"]
    partition = TopicPartition("test_topic", 2)
    assert partition in offsets
    assert offsets[partition].offset == 11


def test_listen_committable_returns_record():
    consumer = KafkaMessageConsumer("test_topic", validate_messages=False)
    record = Mock()
    record.value = {"source": "s"}
    record.headers = []
    record.topic = "test_topic"
    record.partition = 0
    record.offset = 0
    consumer.consumer = MagicMock()
    consumer.consumer.__iter__.return_value = iter([record])

    msg, raw = next(consumer.listen_committable())

    assert msg["source"] == "s"
    assert raw is record
