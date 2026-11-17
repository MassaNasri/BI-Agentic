"""Loader current-state write safety, including equal-version conflicts."""
import json
from uuid import uuid4

import pytest

from bi_platform_shared.cdc_contract import CdcError, Scope
from shared.cdc.clickhouse import BatchConflict, CurrentStateStore


class Result:
    def __init__(self, rows):
        self.rows = rows

    def named_results(self):
        return iter(self.rows)


class Client:
    def __init__(self, rows=(), sorting_key='id, _cdc_version', engine='MergeTree'):
        self.rows = list(rows)
        self.sorting_key = sorting_key
        self.engine = engine
        self.queries = []
        self.inserts = []
        self.commands = []

    def query(self, sql, **kwargs):
        self.queries.append((sql, kwargs))
        if 'FROM system.tables' in sql:
            return Result([{'engine':self.engine,'sorting_key':self.sorting_key}])
        return Result(self.rows)

    def raw_insert(self, table, **kwargs):
        self.inserts.append((table, json.loads(kwargs['insert_block'])))

    def command(self, sql):
        self.commands.append(sql)


@pytest.fixture
def scope():
    return Scope(11, str(uuid4()), str(uuid4()), 7, 'public', 'orders')


@pytest.fixture
def columns():
    return [{'name': 'id', 'postgres_type': 'integer', 'clickhouse_type': 'Int32', 'nullable': False},
            {'name': 'amount', 'postgres_type': 'numeric(30,6)',
             'clickhouse_type': 'Decimal(30, 6)', 'nullable': False}]


@pytest.fixture
def event():
    return {'operation': 'UPDATE', 'primary_key': {'id': 1},
            'row': {'id': 1, 'amount': '123456789012345678901234.123456'},
            'version': '12345678901234567890', 'event_id': 'a' * 64}


def stored(event, **changes):
    return {'_cdc_event_id': event['event_id'], '_cdc_deleted': int(event['operation'] == 'DELETE'),
            **event['row'], **changes}


def test_prepare_retains_versions_and_ranks_before_delete_filter(scope, columns):
    client = Client()
    CurrentStateStore(client, 'etl').prepare(scope, columns, ['id'])
    assert 'ENGINE=MergeTree ORDER BY (`id`,_cdc_version)' in client.commands[0]
    assert '_cdc_version UInt128' in client.commands[0]
    assert '_cdc_deleted UInt8' in client.commands[0]
    assert '_cdc_event_id FixedString(64)' in client.commands[0]
    assert any('ADD COLUMN IF NOT EXISTS `amount` Decimal(30, 6) AFTER `id`'
               in command for command in client.commands)
    assert 'FROM `etl`.' in client.commands[-1]
    assert 'row_number() OVER (PARTITION BY `id` ORDER BY _cdc_version DESC)' in client.commands[-1]
    assert 'WHERE _cdc_rank=1 AND _cdc_deleted=0' in client.commands[-1]
    assert 'SELECT `id`,`amount`' in client.commands[-1]


def test_new_write_and_identical_replay(scope, columns, event):
    client = Client()
    store = CurrentStateStore(client, 'etl')
    assert store.apply(scope, event, columns, ['id']) is True
    assert len(client.inserts) == 1
    assert client.inserts[0][1]['amount'] == event['row']['amount']
    assert client.queries[1][1]['parameters'] == {'version': event['version'], 'key_0': '1'}
    client.rows = [stored(event)]
    assert store.apply(scope, event, columns, ['id']) is False
    assert len(client.inserts) == 1


@pytest.mark.parametrize('changes', [
    {'amount': '999.000000'}, {'_cdc_event_id': 'b' * 64}, {'_cdc_deleted': 1},
])
def test_equal_version_conflict_fails_before_insert(scope, columns, event, changes):
    client = Client([stored(event, **changes)])
    with pytest.raises(CdcError, match='CDC_VERSION_CONFLICT'):
        CurrentStateStore(client, 'etl').apply(scope, event, columns, ['id'])
    assert not client.inserts


def test_composite_key_uses_every_component(scope, event):
    columns = [{'name': 'id', 'postgres_type': 'integer', 'clickhouse_type': 'Int32', 'nullable': False},
               {'name': 'part', 'postgres_type': 'text', 'clickhouse_type': 'String', 'nullable': False}]
    event['primary_key']['part'] = 'A'
    event['row'] = {'id': 1, 'part': 'A'}
    client = Client(sorting_key='id, part, _cdc_version')
    assert CurrentStateStore(client, 'etl').apply(scope, event, columns, ['id', 'part'])
    sql, options = client.queries[1]
    assert '`id` = CAST({key_0:String} AS Int32)' in sql
    assert '`part` = CAST({key_1:String} AS String)' in sql
    assert options['parameters']['key_1'] == 'A'


def test_delete_version_keeps_physical_tombstone(scope, columns, event):
    event['operation'] = 'DELETE'
    client = Client()
    assert CurrentStateStore(client, 'etl').apply(scope, event, columns, ['id'])
    assert client.inserts[0][1]['_cdc_deleted'] == 1
    client.rows = [stored(event)]
    assert CurrentStateStore(client, 'etl').apply(scope, event, columns, ['id']) is False


def test_legacy_merge_losing_version_history_fails_closed(scope, columns, event):
    client = Client(engine='ReplacingMergeTree', sorting_key='id')
    with pytest.raises(CdcError, match='CDC_STORAGE_INCOMPATIBLE'):
        CurrentStateStore(client, 'etl').apply(scope, event, columns, ['id'])
    assert client.inserts == []


class BatchClient(Client):
    def __init__(self, rows=(), fail_partial=False):
        super().__init__(rows=rows)
        self.fail_partial = fail_partial

    def raw_insert(self, table, **kwargs):
        rows = [json.loads(line) for line in kwargs['insert_block'].decode().splitlines()]
        if self.fail_partial:
            self.rows.append(rows[0])
            self.fail_partial = False
            raise RuntimeError('uncertain ClickHouse response after a partial write')
        self.rows.extend(rows)
        self.inserts.append((table, rows))


def test_batch_identical_duplicate_and_crash_replay(scope, columns, event):
    second = {**event, 'primary_key': {'id': 2},
              'row': {**event['row'], 'id': 2}, 'event_id': 'b' * 64}
    client = BatchClient(fail_partial=True)
    store = CurrentStateStore(client, 'etl')
    with pytest.raises(RuntimeError, match='uncertain ClickHouse'):
        store.apply_batch(scope, [event, second], columns, ['id'])
    assert len(client.rows) == 1
    assert store.apply_batch(scope, [event, second], columns, ['id']) == 1
    assert store.apply_batch(scope, [event, second], columns, ['id']) == 0
    assert len(client.rows) == 2


def test_batch_conflict_rejects_all_new_rows_before_insert(scope, columns, event):
    changed = {**event, 'row': {**event['row'], 'amount': '1.000000'}}
    client = BatchClient()
    with pytest.raises(BatchConflict) as error:
        CurrentStateStore(client, 'etl').apply_batch(
            scope, [event, changed], columns, ['id'])
    assert error.value.index == 1 and error.value.code == 'CDC_VERSION_CONFLICT'
    assert client.rows == []


def test_batch_mixed_existing_new_delete_versions(scope, columns, event):
    existing = {**stored(event), '_cdc_version': int(event['version'])}
    newer = {**event, 'version': str(int(event['version']) + 1),
             'event_id': 'c' * 64, 'operation': 'DELETE'}
    other = {**event, 'primary_key': {'id': 2},
             'row': {**event['row'], 'id': 2}, 'event_id': 'd' * 64}
    client = BatchClient(rows=[existing])
    assert CurrentStateStore(client, 'etl').apply_batch(
        scope, [event, other, newer], columns, ['id']) == 2
    assert len(client.inserts) == 1
    assert [row['_cdc_deleted'] for row in client.inserts[0][1]] == [0, 1]


def test_batch_stored_same_version_conflict_rejects_new_neighbor(scope, columns, event):
    conflicting = {**stored(event), '_cdc_version': int(event['version']),
                   'amount': '999.000000'}
    neighbor = {**event, 'primary_key': {'id': 2},
                'row': {**event['row'], 'id': 2}, 'event_id': 'e' * 64}
    client = BatchClient(rows=[conflicting])
    with pytest.raises(BatchConflict) as error:
        CurrentStateStore(client, 'etl').apply_batch(
            scope, [event, neighbor], columns, ['id'])
    assert error.value.index == 0
    assert not client.inserts and len(client.rows) == 1
