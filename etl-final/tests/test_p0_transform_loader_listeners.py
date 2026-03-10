import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock, patch


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
TRANSFORMER_LISTENER_PATH = ROOT / "transformer-service" / "transformer" / "engine" / "kafka_listener.py"
LOADER_LISTENER_PATH = ROOT / "loader-service" / "loader" / "engine" / "kafka_listener.py"


def test_transformer_failed_send_goes_to_dlq():
    sys.path.insert(0, str(ROOT / "transformer-service"))
    from transformer.engine import kafka_listener as kl

    mock_consumer = Mock()
    mock_producer = Mock()
    mock_producer.send.return_value = True
    mock_lineage = Mock()
    with patch.object(kl, "KafkaMessageConsumer", return_value=mock_consumer), patch.object(
        kl, "KafkaMessageProducer", return_value=mock_producer
    ), patch.object(kl, "LineageTracker", return_value=mock_lineage), patch.object(
        kl.RawRowListener, "_init_quarantine_manager", return_value=None
    ), patch.object(
        kl.RawRowListener, "_init_quality_metrics_manager", return_value=None
    ), patch.object(
        kl.RawRowListener, "_load_rules", return_value=[]
    ), patch.object(
        kl, "TransformerService"
    ) as mock_transformer_cls:
        transformer_instance = Mock()
        mock_transformer_cls.return_value = transformer_instance
        listener = kl.RawRowListener(batch_size=1)

    listener.send_retries = 1
    listener.output_batch_size = 1
    listener.transformer_service.process_batch.return_value = (
        [
            {
                "status": "success",
                "source": "src",
                "clean_message": {
                    "source": "src",
                    "_batch_id": "b1",
                    "_transformed_dedup_key": "k1",
                    "schema_version": 1,
                    "data": {"id": 1},
                },
            }
        ],
        {"processed": 1, "failed": 0, "warnings": []},
    )

    def send_side_effect(topic, *_args, **_kwargs):
        if topic == "clean_rows_topic":
            return False
        if topic == listener.dlq_topic:
            return True
        return True

    mock_producer.send.side_effect = send_side_effect
    assert listener._process_batch([{"source": "src"}]) is True
    sent_topics = [call[0][0] for call in mock_producer.send.call_args_list]
    assert listener.dlq_topic in sent_topics


def test_loader_flush_failure_uses_dlq_and_listener_commit_on_success_only():
    sys.path.insert(0, str(ROOT / "loader-service"))
    from loader.engine import kafka_listener as kl
    mock_consumer = Mock()
    mock_producer = Mock()
    mock_producer.send.return_value = True
    mock_lineage = Mock()
    with patch.object(kl, "KafkaMessageConsumer", return_value=mock_consumer), patch.object(
        kl, "KafkaMessageProducer", return_value=mock_producer
    ), patch.object(kl, "LineageTracker", return_value=mock_lineage), patch.object(
        kl, "LoaderLogic"
    ) as mock_loader_logic, patch.object(
        kl.CleanRowListener, "_init_quarantine_manager", return_value=None
    ):
        loader_instance = Mock()
        loader_instance.client = Mock()
        mock_loader_logic.return_value = loader_instance
        listener = kl.CleanRowListener(batch_size=1)

    listener.batch_buffers["table_a"] = [{"id": 1}]
    listener.buffered_rows_total = 1
    loader_instance.load_batch_resilient.side_effect = RuntimeError("insert failed")

    def send_side_effect(topic, *_args, **_kwargs):
        if topic == listener.dlq_topic:
            return True
        return True

    mock_producer.send.side_effect = send_side_effect
    assert listener._flush_batch("table_a", "src") is True
    assert listener.batch_buffers["table_a"] == []

    record = Mock()
    mock_consumer.listen_committable.return_value = iter([({"source": "s", "data": {"id": 1}}, record)])
    listener._process_message = Mock(return_value=False)
    listener.listen()
    mock_consumer.commit.assert_not_called()


def test_transformer_listener_bounds_warning_and_source_stats_memory():
    sys.path.insert(0, str(ROOT / "transformer-service"))
    from transformer.engine import kafka_listener as kl

    mock_consumer = Mock()
    mock_producer = Mock()
    mock_producer.send.return_value = True
    mock_lineage = Mock()
    with patch.object(kl, "KafkaMessageConsumer", return_value=mock_consumer), patch.object(
        kl, "KafkaMessageProducer", return_value=mock_producer
    ), patch.object(kl, "LineageTracker", return_value=mock_lineage), patch.object(
        kl.RawRowListener, "_init_quarantine_manager", return_value=None
    ), patch.object(
        kl.RawRowListener, "_init_quality_metrics_manager", return_value=None
    ), patch.object(
        kl.RawRowListener, "_load_rules", return_value=[]
    ), patch.object(
        kl, "TransformerService"
    ) as mock_transformer_cls:
        transformer_instance = Mock()
        mock_transformer_cls.return_value = transformer_instance
        listener = kl.RawRowListener(batch_size=1)

    listener.max_warning_entries = 3
    listener.warnings = kl.deque(maxlen=listener.max_warning_entries)
    listener.max_source_stats = 2
    listener.source_stats = kl.OrderedDict()

    transformer_instance.process_batch.return_value = (
        [],
        {"processed": 0, "failed": 0, "warnings": ["w1", "w2", "w3", "w4"]},
    )
    listener._process_batch([{"source": "s1", "data": {"id": 1}}])
    assert len(listener.warnings) == 3

    listener._update_source_stats("s1", True)
    listener._update_source_stats("s2", True)
    listener._update_source_stats("s3", True)
    assert len(listener.source_stats) == 2
    assert "s1" not in listener.source_stats


def test_loader_schema_inference_not_all_string_and_dedup_skips_duplicates():
    sys.path.insert(0, str(ROOT / "loader-service"))
    from loader.engine import kafka_listener as kl

    mock_consumer = Mock()
    mock_producer = Mock()
    mock_producer.send.return_value = True
    mock_lineage = Mock()
    with patch.object(kl, "KafkaMessageConsumer", return_value=mock_consumer), patch.object(
        kl, "KafkaMessageProducer", return_value=mock_producer
    ), patch.object(kl, "LineageTracker", return_value=mock_lineage), patch.object(
        kl, "LoaderLogic"
    ) as mock_loader_logic, patch.object(
        kl.CleanRowListener, "_init_quarantine_manager", return_value=None
    ):
        loader_instance = Mock()
        loader_instance.client = Mock()
        loader_instance.client.table_exists.return_value = False
        loader_instance.load_batch_resilient.return_value = 1
        mock_loader_logic.return_value = loader_instance
        listener = kl.CleanRowListener(batch_size=10)

    listener.idempotency_manager.is_duplicate = Mock(side_effect=[False, True])
    msg = {"source": "s", "data": {"id": 1, "name": "a"}, "_batch_id": "b", "_transformed_dedup_key": "k1"}
    assert listener.process_row(msg) == "s"
    assert listener.process_row(msg) == "s"
    assert len(listener.batch_buffers["s"]) == 1
    created_columns = loader_instance.client.create_table.call_args[0][1]
    assert created_columns["id"] == "Int64"


def test_loader_failed_flush_keeps_buffer_when_dlq_fails():
    sys.path.insert(0, str(ROOT / "loader-service"))
    from loader.engine import kafka_listener as kl

    with patch.object(kl, "KafkaMessageConsumer", return_value=Mock()), patch.object(
        kl, "KafkaMessageProducer", return_value=Mock()
    ) as prod_ctor, patch.object(kl, "LineageTracker", return_value=Mock()), patch.object(
        kl, "LoaderLogic"
    ) as mock_loader_logic, patch.object(
        kl.CleanRowListener, "_init_quarantine_manager", return_value=None
    ):
        loader_instance = Mock()
        loader_instance.client = Mock()
        loader_instance.load_batch_resilient.side_effect = RuntimeError("boom")
        mock_loader_logic.return_value = loader_instance
        listener = kl.CleanRowListener(batch_size=1)

    producer = prod_ctor.return_value
    producer.send.return_value = False
    listener.batch_buffers["t"] = [{"id": 1}]
    listener.pending_idempotency_keys["t"] = ["k1"]
    listener.buffered_rows_total = 1

    assert listener._flush_batch("t", "src") is False
    assert listener.batch_buffers["t"] == [{"id": 1}]
    assert listener.pending_idempotency_keys["t"] == ["k1"]
