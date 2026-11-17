import copy
import hashlib
from decimal import Decimal
from uuid import uuid4
import pytest
from bi_platform_shared.cdc_contract import Scope, normalize, validate, CdcError, safe_dlq, canonical
from shared.cdc.schema import clickhouse_type, convert, schema_additions, transform
from shared.cdc.connect import configuration, write_password, remove_password, password_file_exists


@pytest.fixture
def scope():
    return Scope(1, str(uuid4()), str(uuid4()), 7, 'public', 'orders')


def record(op='u', lsn=100, index=1, row=None):
    row = row or {'id': 1, 'amount': '100.25'}
    return {'op': op, 'before': copy.deepcopy(row) if op in {'u', 'd'} else None,
            'after': None if op == 'd' else copy.deepcopy(row),
            'source': {'schema': 'public', 'table': 'orders', 'lsn': lsn, 'txId': 9, 'ts_ms': 1,
                       'snapshot': 'true' if op == 'r' else 'false'},
            'transaction': {'total_order': index}}


@pytest.mark.parametrize('op,name', [('r','SNAPSHOT'), ('c','INSERT'), ('u','UPDATE'), ('d','DELETE')])
def test_operations_and_roundtrip(scope, op, name):
    event = normalize(record(op), {'id': 1}, scope, ['id'])
    assert event['operation'] == name
    assert validate(event, scope, ['id']) == event
    assert event == normalize(record(op), {'id': 1}, scope, ['id'])


def test_tombstone_is_not_delete(scope):
    assert normalize(None, {'id': 1}, scope, ['id']) is None


def test_generation_one_wire_identity_is_retained_and_next_generation_is_isolated(scope):
    legacy = scope.event_scope
    assert scope.token == hashlib.sha256(canonical(legacy).encode()).hexdigest()[:40]
    first = normalize(record(), {'id': 1}, scope, ['id'])
    assert first['contract'] == 'ChangeEnvelope.v1'
    assert 'generation' not in first
    later = Scope(scope.workspace_id, scope.source_id, scope.pipeline_id,
                  scope.dataset_id, scope.schema, scope.table, 2)
    second = normalize(record(), {'id': 1}, later, ['id'])
    assert later.token != scope.token
    assert later.publication_token == scope.token
    assert later.raw_topic != scope.raw_topic
    assert second['contract'] == 'ChangeEnvelope.v2'
    assert second['generation'] == 2
    assert second['event_id'] != first['event_id']
    assert validate(second, later, ['id']) == second
    with pytest.raises(CdcError, match='CONTRACT|SCOPE'):
        validate(first, later, ['id'])
    with pytest.raises(CdcError, match='CONTRACT|SCOPE'):
        validate(second, scope, ['id'])


def test_composite_key_and_key_change(scope):
    value=record(row={'id':1,'part':'A','amount':'100.25'})
    event=normalize(value, {'id':1,'part':'A'}, scope, ['id','part'])
    assert event['primary_key']=={'id':1,'part':'A'}
    changed=copy.deepcopy(value)
    changed['before']['part']='B'
    with pytest.raises(CdcError,match='KEY_MUTATION'):
        normalize(changed, {'id':1,'part':'A'}, scope, ['id','part'])
    deleted=normalize(record('d',row={'id':1,'part':'B','amount':'100.25'}),
                      {'id':1,'part':'B'},scope,['id','part'])
    inserted=normalize(record('c',row={'id':1,'part':'A','amount':'100.25'}),
                       {'id':1,'part':'A'},scope,['id','part'])
    assert deleted['operation']=='DELETE' and inserted['operation']=='INSERT'


@pytest.mark.parametrize('field,value', [('workspace_id',2),('source_id','foreign'),
    ('pipeline_id','foreign'),('dataset_id',99)])
def test_raw_scope_claim_cannot_override_subscription(scope, field, value):
    raw=record()
    raw[field]=value
    with pytest.raises(CdcError,match='SCOPE_MISMATCH'):
        normalize(raw,{'id':1},scope,['id'])
    raw=record()
    raw['source'][field]=value
    with pytest.raises(CdcError,match='SCOPE_MISMATCH'):
        normalize(raw,{'id':1},scope,['id'])


@pytest.mark.parametrize('mutate', [
    lambda r:r.update(before=None),
    lambda r:r.update(after=None),
    lambda r:r['before'].pop('id'),
])
def test_update_requires_complete_keyed_images(scope, mutate):
    raw=record()
    mutate(raw)
    with pytest.raises(CdcError,match='ROW_IMAGE|KEY_MUTATION'):
        normalize(raw,{'id':1},scope,['id'])


@pytest.mark.parametrize('field,value', [('lsn',1.5),('lsn',True),('lsn','1.0'),
    ('txId','secret'),('ts_ms',1.5)])
def test_position_and_timestamp_are_strict(scope, field, value):
    raw=record()
    raw['source'][field]=value
    with pytest.raises(CdcError,match='POSITION|TIMESTAMP'):
        normalize(raw,{'id':1},scope,['id'])


@pytest.mark.parametrize('value', [None, 1.2, -1, '1.5', 2**32])
def test_transaction_order_is_bounded(scope, value):
    raw=record()
    raw['transaction']={'total_order':value}
    with pytest.raises(CdcError,match='POSITION'):
        normalize(raw,{'id':1},scope,['id'])


def test_source_position_identity_domain_and_replay(scope):
    first=normalize(record('c',100,1),{'id':1},scope,['id'])
    same=normalize(copy.deepcopy(record('c',100,1)),{'id':1},scope,['id'])
    next_in_tx=normalize(record('u',100,2),{'id':1},scope,['id'])
    next_key=normalize(record('c',100,1,row={'id':2,'amount':'100.25'}),{'id':2},scope,['id'])
    assert first==same
    assert first['event_id']!=next_in_tx['event_id']!=next_key['event_id']
    assert int(first['version'])<int(next_in_tx['version'])
    assert first['version']==next_key['version']  # Version is per key, not a global order.


def test_snapshot_last_and_stream_same_lsn(scope):
    snapshot=record('r',100,0)
    snapshot['source']['snapshot']='last'
    earlier=normalize(snapshot,{'id':1},scope,['id'])
    later=normalize(record('u',100,1),{'id':1},scope,['id'])
    assert earlier['snapshot_complete'] is True
    assert int(earlier['version'])<int(later['version'])


def test_debezium_first_snapshot_marker(scope):
    first=record('r',100,0)
    first['source']['snapshot']='first'
    event=normalize(first,{'id':1},scope,['id'])
    assert event['operation']=='SNAPSHOT' and event['snapshot_complete'] is False
    assert validate(event,scope,['id'])==event


def test_ordering_independent_of_delivery(scope):
    versions = [int(normalize(record(op, lsn, index), {'id': 1}, scope, ['id'])['version'])
                for op,lsn,index in [('u',100,2), ('r',100,0), ('u',99,999), ('u',100,1), ('d',101,1)]]
    assert versions[2] < versions[1] < versions[3] < versions[0] < versions[4]


def test_no_tenant_or_event_forgery(scope):
    event = normalize(record(), {'id': 1}, scope, ['id'])
    other = Scope(2, scope.source_id, scope.pipeline_id, 7, 'public', 'orders')
    assert other.raw_topic != scope.raw_topic
    with pytest.raises(CdcError, match='SCOPE'):
        validate(event, other, ['id'])
    event['version'] = '999999'
    with pytest.raises(CdcError, match='CONTRACT'):
        validate(event, scope, ['id'])


@pytest.mark.parametrize('mutation', [lambda r:r.update(op='t'), lambda r:r['source'].update(lsn=-1), lambda r:r.update(transaction=None), lambda r:r['source'].update(table='other')])
def test_unsafe_events_rejected(scope, mutation):
    value = record()
    mutation(value)
    with pytest.raises(CdcError):
        normalize(value, {'id':1}, scope, ['id'])


def test_pk_required(scope):
    with pytest.raises(CdcError, match='PRIMARY_KEY'):
        normalize(record(), None, scope, [])


@pytest.mark.parametrize('pg,ch', [('integer','Int32'), ('bigint','Int64'), ('numeric(20,4)','Decimal(20, 4)'), ('boolean','Bool'), ('text','String'), ('uuid','UUID'), ('date','Date32'), ('timestamp with time zone',"DateTime64(6, 'UTC')"), ('jsonb','String')])
def test_types(pg,ch):
    assert clickhouse_type(pg, False) == ch
    assert clickhouse_type(pg, True) == f'Nullable({ch})'


def test_no_precision_loss():
    c = {'postgres_type':'numeric(30,6)', 'nullable':False}
    value = '999999999999999999999999.123456'
    assert convert(value,c) == value
    maximum='9'*70+'.123456'
    assert convert(maximum,{'postgres_type':'numeric(76,6)','nullable':False}) == maximum
    with pytest.raises(CdcError):
        convert('1.0000001',c)
    with pytest.raises(CdcError):
        convert(1.234567,c)
    assert convert('1.2',c)=='1.200000'
    with pytest.raises(CdcError):
        clickhouse_type('numeric',False)


def test_temporal_and_json():
    assert convert('2026-10-27T03:15:00.123456+03:00', {'postgres_type':'timestamp with time zone','nullable':False}) == '2026-10-27 00:15:00.123456'
    assert convert(1, {'postgres_type':'timestamp without time zone','nullable':False}) == '1970-01-01 00:00:00.000001'
    assert convert(1, {'postgres_type':'date','nullable':False}) == '1970-01-02'
    assert convert('{"b":2,"a":1}', {'postgres_type':'jsonb','nullable':False}) == '{"a":1,"b":2}'
    assert convert('{"b":1.23000000000000000001,"a":2}', {'postgres_type':'jsonb','nullable':False}) == '{"a":2,"b":1.23000000000000000001}'
    with pytest.raises(CdcError,match='VALUE_INVALID'):
        convert('2026-10-27T03:15:00', {'postgres_type':'timestamp with time zone','nullable':False})
    with pytest.raises(CdcError,match='VALUE_INVALID'):
        convert(1.2, {'postgres_type':'timestamp without time zone','nullable':False})
    with pytest.raises(CdcError,match='VALUE_INVALID'):
        convert({'rate':1.2}, {'postgres_type':'jsonb','nullable':False})


def test_catalog_shape_and_version_are_checked_before_transform(scope):
    columns=[{'name':'id','postgres_type':'integer','nullable':False},
             {'name':'amount','postgres_type':'numeric(20,4)','nullable':False}]
    event=normalize(record(),{'id':1},scope,['id'],schema_version=2)
    with pytest.raises(CdcError,match='SCHEMA_INCOMPATIBLE'):
        transform(event,columns,['id'],schema_version=1)
    assert transform(event,columns,['id'],schema_version=2)['row']=={'id':1,'amount':'100.2500'}
    old=copy.deepcopy(event)
    old['after'].pop('amount')
    with pytest.raises(CdcError,match='SCHEMA_INCOMPATIBLE'):
        transform(old,columns,['id'],schema_version=2)
    extra=copy.deepcopy(event)
    extra['after']['foreign']='payload'
    with pytest.raises(CdcError,match='SCHEMA_INCOMPATIBLE'):
        transform(extra,columns,['id'],schema_version=2)


def test_only_nullable_add_allowed():
    columns = [{'name':'id','nullable':False,'postgres_type':'integer','clickhouse_type':'Int32'}]
    added = {'name':'note','nullable':True,'postgres_type':'text','clickhouse_type':'Nullable(String)'}
    assert schema_additions(columns, columns+[added], ['id'], ['id']) == [added]
    for replacement in ([], [{**columns[0], 'postgres_type':'text'}], columns+[{**added,'nullable':False}]):
        with pytest.raises(CdcError, match='INCOMPATIBLE'):
            schema_additions(columns,replacement,['id'],['id'])
    with pytest.raises(CdcError,match='INCOMPATIBLE'):
        schema_additions(columns,columns+[{**added,'name':'new_key'}],['id'],['new_key'])


def test_secret_reference_and_safe_dlq(scope, monkeypatch, tmp_path):
    monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setenv('CDC_SECRET_DIRECTORY',str(tmp_path))
    secret='private\npassword:=\\é›ª'
    config=configuration(scope, {'host':'postgres','port':5432,'username':'replicator','database':'source','password':secret})
    assert secret not in canonical(config)
    assert config['database.password'].startswith('${file:/run/cdc-secrets/')
    assert 'transforms' not in config and 'producer.override.bootstrap.servers' not in config
    write_password(scope, secret)
    assert password_file_exists(scope)
    assert len((tmp_path/f'{scope.token}.properties').read_text().splitlines()) == 1
    write_password(scope, 'rotated')
    assert password_file_exists(scope)
    assert 'private' not in (tmp_path/f'{scope.token}.properties').read_text()
    assert not list(tmp_path.glob('*.tmp'))
    remove_password(scope)
    assert not password_file_exists(scope)
    assert set(safe_dlq(scope,'abc','CDC_EVENT_INVALID','normalize','now')) == {'contract',*scope.event_scope,'event_id','reason','stage','retry_count','timestamp'}
    assert safe_dlq(scope,'malformed-event-containing-a-secret','CDC_EVENT_INVALID','normalize','now')['event_id'] is None
    hostile=safe_dlq(scope,'x'*200,'private-password','private-stage','private-token')
    assert hostile['event_id'] is None and hostile['reason']=='CDC_EVENT_INVALID'
    assert hostile['stage']=='normalize' and hostile['timestamp']==''


def test_production_transport_gate(scope,monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    with pytest.raises(CdcError,match='UNCERTIFIED'):
        configuration(scope,{})
