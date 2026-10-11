import os
from unittest.mock import MagicMock, Mock, patch

from kafka import TopicPartition

from shared.utils.kafka_consumer import KafkaMessageConsumer


@patch("shared.utils.kafka_consumer.ensure_topics")
@patch("shared.utils.kafka_consumer.KafkaConsumer")
def test_auto_commit_disabled_by_default(mock_kafka_consumer, _mock_ensure_topics):
    mock_kafka_consumer.return_value = MagicMock()
    consumer = KafkaMessageConsumer("test_topic", validate_messages=False)
    consumer.connect()
    kwargs = mock_kafka_consumer.call_args.kwargs
    assert kwargs["enable_auto_commit"] is False


@patch.dict(
    os.environ,
    {"KAFKA_CONNECT_MAX_ATTEMPTS": "2", "KAFKA_CONNECT_RETRY_SECONDS": "0"},
)
@patch("shared.utils.kafka_consumer.ensure_topics", side_effect=RuntimeError("unavailable"))
def test_connect_has_bounded_retries(mock_ensure_topics):
    consumer = KafkaMessageConsumer("test_topic", validate_messages=False)

    try:
        consumer.connect()
    except ConnectionError as exc:
        assert "after 2 attempts" in str(exc)
    else:
        raise AssertionError("Expected a bounded Kafka connection failure")

    assert mock_ensure_topics.call_count == 2


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


def test_rewind_seeks_to_failed_record_offset():
    consumer = KafkaMessageConsumer("test_topic", validate_messages=False)
    consumer.consumer = Mock()
    record = Mock(topic="test_topic", partition=2, offset=10)

    ok = consumer.rewind(record)

    assert ok is True
    consumer.consumer.seek.assert_called_once_with(TopicPartition("test_topic", 2), 10)
