"""D3 worker boundary tests: no silent offset advance across failure and replay."""
import json
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock

import pytest
from kafka.errors import NoOffsetForPartitionError

from bi_platform_shared.cdc_contract import CdcError, Scope, canonical, normalize
from shared.cdc.worker import (PipelineConsumer, decode_cdc_json,
                               snapshot_notification, MAX_CDC_JSON_BYTES)
from shared.cdc.clickhouse import BatchConflict


@pytest.fixture
def scope():
    return Scope(11, str(uuid4()), str(uuid4()), 7, 'public', 'orders')


@pytest.fixture
def item(scope):
    return {'scope': scope.__dict__, 'primary_key': ['id'], 'schema_version': 1,
            'columns': [{'name': 'id', 'postgres_type': 'integer', 'nullable': False},
                        {'name': 'amount', 'postgres_type': 'numeric(20,4)', 'nullable': False}]}


def raw(op='c', order=1):
    row = {'id': 1, 'amount': '123.4500'}
    return {'op': op, 'before': row if op in {'u', 'd'} else None,
            'after': None if op == 'd' else row,
            'source': {'schema': 'public', 'table': 'orders', 'lsn': 100,
                       'txId': 9, 'ts_ms': 1000, 'snapshot': 'false'},
            'transaction': {'total_order': order}}


def message(topic, value, key=b'{"id":1}', offset=4):
    return SimpleNamespace(topic=topic, value=value, key=key, partition=0, offset=offset)


class Consumer:
    def __init__(self, messages, journal):
        self.messages, self.journal = messages, journal

    def poll(self, **_):
        return {'partition': self.messages}

    def commit(self, offsets):
        self.journal.append(('commit', next(iter(offsets.values())).offset))


class Producer:
    def __init__(self, journal, fail=False):
        self.journal, self.fail = journal, fail

    def send(self, topic, value, key=None):
        self.journal.append(('send', topic, value, key))
        producer = self
        class Future:
            def get(self, **_):
                if producer.fail:
                    raise TimeoutError('broker unavailable')
                producer.journal.append(('durable', topic))
        return Future()


class Control:
    def __init__(self, journal, fail=False):
        self.journal, self.fail = journal, fail

    def update(self, _scope, **fields):
        if self.fail:
            raise RuntimeError('callback unavailable')
        self.journal.append(('callback', fields))


def worker(scope, stage, messages, journal, producer_fail=False, callback_fail=False):
    instance = object.__new__(PipelineConsumer)
    instance.scope, instance.stage = scope, stage
    instance.heartbeat_topic = '__debezium-heartbeat.' + scope.topic('raw') if stage == 'normalize' else None
    instance.notification_topic = scope.topic('notification') if stage == 'normalize' else None
    instance.consumer = Consumer(messages, journal)
    instance.producer = Producer(journal, producer_fail)
    instance.control = Control(journal, callback_fail)
    instance.store = None
    return instance


def test_empty_snapshot_notification_is_connector_and_table_bound(scope, item):
    data = {'id': str(uuid4()), 'aggregate_type': 'Initial Snapshot',
            'type': 'TABLE_SCAN_COMPLETED', 'timestamp': 1000,
            'additional_data': {'connector_name': scope.topic('raw'),
                                'scanned_collection': 'public.orders',
                                'total_rows_scanned': '0', 'status': 'SUCCEEDED'}}
    expected = snapshot_notification(data, scope, 0, 4)
    assert expected['empty'] is True
    journal = []
    msg = message(scope.topic('notification'), canonical(data).encode(), key=None)
    assert worker(scope, 'normalize', [msg], journal).poll(item)
    assert journal == [('callback', {'snapshot_notification': expected}), ('commit', 5)]
    data['additional_data']['connector_name'] = 'b_foreign'
    with pytest.raises(CdcError, match='SNAPSHOT_NOTIFICATION_INVALID'):
        snapshot_notification(data, scope, 0, 5)


def test_new_notification_partition_gets_explicit_checked_seek(scope, item):
    instance = worker(scope, 'normalize', [], [])
    instance.consumer.poll = Mock(side_effect=NoOffsetForPartitionError())
    instance.consumer.assignment = Mock(return_value=['notification-partition'])
    instance.offset_resumer = Mock()
    assert instance.poll(item) is True
    instance.offset_resumer.on_partitions_assigned.assert_called_once_with(
        ['notification-partition'])


def test_tombstone_and_heartbeat_are_transport_only(scope, item):
    journal = []
    tombstone = message(scope.raw_topic, None, key=b'not-json')
    heartbeat = message('__debezium-heartbeat.' + scope.topic('raw'), b'{"ts_ms":1234}', key=None, offset=5)
    assert worker(scope, 'normalize', [tombstone, heartbeat], journal).poll(item)
    assert not any(entry[0] == 'send' for entry in journal)
    assert [entry for entry in journal if entry[0] == 'commit'] == [('commit', 5), ('commit', 6)]
    assert journal[0][0] == 'callback' and journal[2] == ('callback', {'capture_timestamp_ms': 1234})


@pytest.mark.parametrize('bad,code', [
    (b'{', 'CDC_EVENT_INVALID'),
    (canonical({**raw(), 'op': 't'}).encode(), 'CDC_OPERATION_UNSUPPORTED'),
    (canonical({**raw(), 'workspace_id': 22}).encode(), 'CDC_SCOPE_MISMATCH'),
    (canonical({**raw(), 'after': {'id': 1}}).encode(), 'CDC_SCHEMA_INCOMPATIBLE'),
])
def test_poison_is_dlq_then_pause_then_commit(scope, item, bad, code):
    journal = []
    first = message(scope.raw_topic, bad)
    second = message(scope.raw_topic, canonical(raw(order=2)).encode(), offset=5)
    assert worker(scope, 'normalize', [first, second], journal).poll(item) is False
    assert [entry[0] for entry in journal] == ['send', 'durable', 'callback', 'commit']
    failure = journal[0][2]
    assert journal[0][1] == scope.topic('dlq') and failure['reason'] == code
    assert failure['workspace_id'] == scope.workspace_id
    assert 'before' not in failure and 'after' not in failure and '123.4500' not in canonical(failure)
    assert journal[2][1] == {'error_code': code} and journal[3] == ('commit', 5)


@pytest.mark.parametrize('producer_fail,callback_fail', [(True, False), (False, True)])
def test_transient_normalize_failure_replays_same_event(scope, item, producer_fail, callback_fail):
    msg = message(scope.raw_topic, canonical(raw()).encode())
    journal = []
    with pytest.raises((TimeoutError, RuntimeError)):
        worker(scope, 'normalize', [msg], journal, producer_fail, callback_fail).poll(item)
    assert not any(entry[0] == 'commit' for entry in journal)
    replay = []
    assert worker(scope, 'normalize', [msg], replay).poll(item)
    assert journal[0][2] == replay[0][2]
    assert replay[-1] == ('commit', 5)


@pytest.mark.parametrize('producer_fail,callback_fail', [(True, False), (False, True)])
def test_poison_disposition_failure_never_commits(scope, item, producer_fail, callback_fail):
    msg = message(scope.raw_topic, b'{')
    journal = []
    with pytest.raises((TimeoutError, RuntimeError)):
        worker(scope, 'normalize', [msg], journal, producer_fail, callback_fail).poll(item)
    assert not any(entry[0] == 'commit' for entry in journal)
    assert worker(scope, 'normalize', [msg], []).poll(item) is False


def test_transform_send_callback_failure_replays_identically(scope, item):
    envelope = normalize(raw(), {'id': 1}, scope, ['id'])
    msg = message(scope.topic('normalized'), canonical(envelope).encode())
    first, replay = [], []
    with pytest.raises(RuntimeError):
        worker(scope, 'transform', [msg], first, callback_fail=True).poll(item)
    assert worker(scope, 'transform', [msg], replay).poll(item)
    assert first[0][2] == replay[0][2]
    assert first[0][2]['row'] == {'id': 1, 'amount': '123.4500'}
    assert not any(entry[0] == 'commit' for entry in first)


def test_explicit_crash_after_send_replays(scope, item, monkeypatch):
    from shared.cdc import worker as module
    class SimulatedCrash(BaseException):
        pass
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('CDC_CRASH_AFTER_APPLY', 'normalize')
    monkeypatch.setattr(module.os, '_exit', lambda _: (_ for _ in ()).throw(SimulatedCrash()))
    msg = message(scope.raw_topic, canonical(raw()).encode())
    first, replay = [], []
    with pytest.raises(SimulatedCrash):
        worker(scope, 'normalize', [msg], first).poll(item)
    assert [entry[0] for entry in first] == ['send', 'durable']
    monkeypatch.delenv('CDC_CRASH_AFTER_APPLY')
    assert worker(scope, 'normalize', [msg], replay).poll(item)
    assert first[0][2] == replay[0][2]
    assert replay[-1] == ('commit', 5)


def test_loader_retry_preserves_persisted_high_watermark_before_ack(scope, item):
    envelope = normalize(raw(), {'id': 1}, scope, ['id'])
    transformed = {**envelope, 'row': {'id': 1, 'amount': '123.4500'}}
    msg = message(scope.topic('transformed'), canonical(transformed).encode(), offset=6)
    item['checkpoints'] = {'load:0': {'offset': 5, 'partition': 0, 'lsn': 500}}
    journal = []
    instance = worker(scope, 'load', [msg], journal, callback_fail=True)
    instance.store = SimpleNamespace(apply=lambda *_: journal.append(('apply',)))
    with pytest.raises(RuntimeError):
        instance.poll(item)
    assert journal == [('apply',)]
    # Query saved the checkpoint but publication failed before Kafka ack.
    item['checkpoints']['load:0']['offset'] = 6
    replay = []
    instance = worker(scope, 'load', [msg], replay)
    instance.store = SimpleNamespace(apply=lambda *_: replay.append(('apply',)))
    assert instance.poll(item)
    assert replay[0] == ('apply',)
    assert replay[1][1]['checkpoint'] == {'partition': 0, 'offset': 6, 'lsn': 500}
    assert replay[2] == ('commit', 7)


def test_payload_limits_are_bounded():
    with pytest.raises(CdcError, match='TOO_LARGE'):
        decode_cdc_json(b' ' * (MAX_CDC_JSON_BYTES + 1))


def test_normalizer_poison_in_middle_commits_only_valid_prefix(scope, item):
    messages = [message(scope.raw_topic, canonical(raw(order=i+1)).encode(), offset=i)
                for i in range(5)]
    messages[2] = message(scope.raw_topic, b'{', offset=2)
    journal = []
    assert worker(scope, 'normalize', messages, journal).poll(item) is False
    sends = [entry for entry in journal if entry[0] == 'send']
    assert [entry[1] for entry in sends] == [scope.topic('normalized')] * 2 + [scope.topic('dlq')]
    assert [entry for entry in journal if entry[0] == 'commit'] == [('commit', 2), ('commit', 3)]
    callbacks = [entry[1] for entry in journal if entry[0] == 'callback']
    assert callbacks[0]['checkpoint'] == {'partition': 0, 'offset': 1, 'lsn': 100}
    assert callbacks[1] == {'error_code': 'CDC_EVENT_INVALID'}
    assert 'before' not in sends[-1][2] and 'after' not in sends[-1][2]


def test_transform_batch_preserves_d3_output_and_coalesces_checkpoint(scope, item):
    envelopes = [normalize(raw(order=i+1), {'id': 1}, scope, ['id']) for i in range(3)]
    messages = [message(scope.topic('normalized'), canonical(event).encode(), offset=i)
                for i, event in enumerate(envelopes)]
    journal = []
    assert worker(scope, 'transform', messages, journal).poll(item)
    sent = [entry[2] for entry in journal if entry[0] == 'send']
    assert len(sent) == 3
    assert [entry['event_id'] for entry in sent] == [entry['event_id'] for entry in envelopes]
    assert [entry['version'] for entry in sent] == [entry['version'] for entry in envelopes]
    assert [entry for entry in journal if entry[0] == 'commit'] == [('commit', 3)]
    assert [entry for entry in journal if entry[0] == 'callback'][0][1]['checkpoint']['offset'] == 2


def test_batch_callback_failure_replays_without_commit(scope, item):
    messages = [message(scope.raw_topic, canonical(raw(order=i+1)).encode(), offset=i)
                for i in range(2)]
    first, replay = [], []
    with pytest.raises(RuntimeError, match='callback unavailable'):
        worker(scope, 'normalize', messages, first, callback_fail=True).poll(item)
    assert not any(entry[0] == 'commit' for entry in first)
    assert worker(scope, 'normalize', messages, replay).poll(item)
    assert [entry[2] for entry in first if entry[0] == 'send'] == [
        entry[2] for entry in replay if entry[0] == 'send']
    assert replay[-1] == ('commit', 2)


def test_loader_batch_conflict_preserves_prefix_and_pauses(scope, item):
    envelopes = [normalize(raw(order=i+1), {'id': 1}, scope, ['id']) for i in range(5)]
    transformed = [{**event, 'row': {'id': 1, 'amount': '123.4500'}} for event in envelopes]
    messages = [message(scope.topic('transformed'), canonical(event).encode(), offset=i)
                for i, event in enumerate(transformed)]
    journal = []
    instance = worker(scope, 'load', messages, journal)

    class Store:
        def apply_batch(self, _scope, events, *_):
            journal.append(('apply_batch', len(events)))
            if len(events) == 5:
                raise BatchConflict(2)

    instance.store = Store()
    assert instance.poll(item) is False
    assert [entry for entry in journal if entry[0] == 'apply_batch'] == [
        ('apply_batch', 5), ('apply_batch', 2)]
    assert [entry for entry in journal if entry[0] == 'commit'] == [('commit', 2), ('commit', 3)]
    assert journal[-2][1] == {'error_code': 'CDC_VERSION_CONFLICT'}
    assert journal[-1] == ('commit', 3)


def test_loader_batch_crash_after_durable_write_replays_before_ack(scope, item, monkeypatch):
    from shared.cdc import worker as module

    class SimulatedCrash(BaseException):
        pass

    envelopes = [normalize(raw(order=i+1), {'id': 1}, scope, ['id']) for i in range(2)]
    messages = [message(scope.topic('transformed'), canonical({
        **event, 'row': {'id': 1, 'amount': '123.4500'}}).encode(), offset=i)
        for i, event in enumerate(envelopes)]
    journal = []
    instance = worker(scope, 'load', messages, journal)
    instance.store = SimpleNamespace(apply_batch=lambda *_: journal.append(('durable_batch', 2)))
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('CDC_CRASH_AFTER_APPLY', 'load')
    monkeypatch.setattr(module.os, '_exit', lambda _: (_ for _ in ()).throw(SimulatedCrash()))
    with pytest.raises(SimulatedCrash):
        instance.poll(item)
    assert journal == [('durable_batch', 2)]
    monkeypatch.delenv('CDC_CRASH_AFTER_APPLY')
    replay = []
    instance = worker(scope, 'load', messages, replay)
    instance.store = SimpleNamespace(apply_batch=lambda *_: replay.append(('replayed_batch', 2)))
    assert instance.poll(item)
    assert replay[0] == ('replayed_batch', 2)
    assert replay[1][0] == 'callback' and replay[2] == ('commit', 2)
    with pytest.raises(CdcError, match='TOO_COMPLEX'):
        decode_cdc_json(('[' * 66 + '0' + ']' * 66).encode())
    with pytest.raises(ValueError):
        decode_cdc_json(b'{')
    with pytest.raises(CdcError, match='TOO_COMPLEX'):
        decode_cdc_json(json.dumps([0] * 100001).encode())
