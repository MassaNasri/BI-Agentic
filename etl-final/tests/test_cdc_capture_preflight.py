"""Fail-closed checks at the PostgreSQL capture boundary."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bi_platform_shared.cdc_contract import CdcError, Scope
from shared.cdc import postgres
from shared.cdc import worker
from shared.cdc.connect import configuration


def test_controller_threads_share_one_process_lease_owner(monkeypatch):
    monkeypatch.setenv('CDC_CONTROL_URL', 'http://query.invalid/internal/v1/cdc/')
    monkeypatch.setenv('CDC_SERVICE_KEY', 'unit-controller-key')
    first = worker.ControlPlane('controller')
    second = worker.ControlPlane('controller')
    assert first.owner == second.owner
    assert first.owner is not None
    first.session.close()
    second.session.close()


def test_connect_mutation_requires_live_database_fence(scope):
    connector = Mock()
    authority = Mock()
    fenced = worker.FencedConnect(connector, authority, scope)
    authority.verify.side_effect = RuntimeError('lease expired')
    with pytest.raises(RuntimeError, match='lease expired'):
        fenced.resume(scope)
    connector.resume.assert_not_called()
    authority.verify.side_effect = None
    fenced.resume(scope)
    connector.resume.assert_called_once_with(scope)
    assert authority.verify.call_count == 3


def test_candidate_controller_stops_old_connector_before_provisioning(scope):
    candidate = Scope(scope.workspace_id, scope.source_id, scope.pipeline_id,
                      scope.dataset_id, scope.schema, scope.table, generation=2)
    old = scope
    item = {'scope': candidate.__dict__, 'previous_scope': old.__dict__,
            'desired_state': 'STREAMING', 'observed_state': 'PROVISIONING'}
    connector = Mock()
    connector.request.return_value = {'connector': {'state': 'RUNNING'}, 'tasks': [{'state': 'RUNNING'}]}
    delay = worker.control_pipeline(item, Mock(), connector, Mock())
    assert delay == 2
    connector.pause.assert_called_once_with(old)


class SourceCursor:
    def __init__(self, values):
        self.values = values
        self.query = ''

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, _params=None):
        self.query = query

    def fetchone(self):
        query = self.query
        if 'server_version_num' in query:
            return self.values.get('server', (180003, 'logical', True, False))
        if 'has_table_privilege' in query:
            return self.values.get('table', (True, 'f', 'r', False))
        if 'pubinsert' in query:
            return self.values.get('publication', (True,))
        if 'slot_name, active' in query:
            slot = self.values.get('slot')
            return slot + (None,) if slot is not None and len(slot) == 10 else slot
        if 'max_replication_slots' in query:
            return (8, 8)
        if 'attnames, rowfilter' in query:
            return (['id'], None)
        raise AssertionError('unexpected preflight query')

    def fetchall(self):
        if 'pg_publication_tables' in self.query:
            return self.values.get('publication_tables', [('public', 'orders')])
        raise AssertionError('unexpected preflight query')


class SourceConnection:
    def __init__(self, values):
        self.values = values
        self.info = SimpleNamespace(dbname='source_a')

    def cursor(self):
        return SourceCursor(self.values)


@pytest.fixture
def scope():
    return Scope(11, '00000000-0000-0000-0000-000000000001',
                 '00000000-0000-0000-0000-000000000002', 3, 'public', 'orders')


@pytest.fixture(autouse=True)
def schema(monkeypatch):
    monkeypatch.setattr(postgres, 'inspect_schema', lambda *_: ([{'name': 'id'}], ['id']))


def test_exact_publication_and_initial_slot_capacity(scope):
    columns, key, health = postgres.preflight(SourceConnection({'slot': None}), scope)
    assert columns == [{'name': 'id'}] and key == ['id']
    assert health == {'slot_active': False, 'retained_wal_bytes': 0, 'wal_warning': False}


def test_new_slot_is_not_continuity_until_positions_initialize(scope):
    creating = (None, True, None, 0, 'reserved', 'logical', 'pgoutput',
                'source_a', False, None)
    _, _, health = postgres.preflight(SourceConnection({'slot': creating}), scope,
                                      existing=False)
    assert health['slot_active'] is False
    with pytest.raises(CdcError, match='CDC_SLOT_INVALID'):
        postgres.preflight(SourceConnection({'slot': creating}), scope, existing=True)


def test_snapshot_gate_is_fixed_to_exact_test_candidate(scope, monkeypatch):
    candidate = Scope(scope.workspace_id, scope.source_id, scope.pipeline_id,
                      scope.dataset_id, scope.schema, scope.table, generation=2)
    source = {'host': 'postgres', 'port': 5432, 'username': 'cdc_d2_fixture',
              'database': 'source_d2_fixture'}
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.delenv('CDC_D5_R4A_GATE_SCOPE_TOKEN', raising=False)
    ordinary = configuration(candidate, source)
    assert not any(key.startswith('snapshot.select.statement.overrides')
                   for key in ordinary)
    monkeypatch.setenv('CDC_D5_R4A_GATE_SCOPE_TOKEN', candidate.token)
    gated = configuration(candidate, source)
    assert gated['snapshot.select.statement.overrides'] == 'public.orders'
    assert gated['snapshot.select.statement.overrides.public.orders'] == (
        'SELECT * FROM public.biavora_d5_r4a_snapshot_orders('
        f'{int(candidate.token[:15], 16)})')
    assert {key: value for key, value in gated.items()
            if not key.startswith('snapshot.select.statement.overrides')} == ordinary
    assert not any(key.startswith('snapshot.select.statement.overrides')
                   for key in configuration(scope, source))
    with pytest.raises(CdcError, match='CDC_FIXTURE_GATE_FORBIDDEN'):
        configuration(candidate, {**source, 'host': 'customer.example'})
    monkeypatch.setenv('APP_ENV', 'production')
    with pytest.raises(CdcError, match='CDC_FIXTURE_GATE_FORBIDDEN'):
        configuration(candidate, source)


@pytest.mark.parametrize('slot,code', [
    (None, 'CDC_SLOT_LOST'),
    ((None, False, '0/1', 0, 'reserved', 'physical', None, None, False, None), 'CDC_SLOT_INVALID'),
    ((None, False, '0/1', 0, 'reserved', 'logical', 'pgoutput', 'other', False, '0/1'), 'CDC_SLOT_INVALID'),
    ((None, False, '0/1', 0, 'unreserved', 'logical', 'pgoutput', 'source_a', False, '0/1'), 'CDC_SLOT_LOST'),
    ((None, False, '0/1', 0, 'lost', 'logical', 'pgoutput', 'source_a', False, '0/1'), 'CDC_SLOT_LOST'),
])
def test_existing_slot_must_retain_exact_source_history(scope, slot, code):
    with pytest.raises(CdcError, match=code):
        postgres.preflight(SourceConnection({'slot': slot}), scope, existing=True)


@pytest.mark.parametrize('values,code', [
    ({'server': (180003, 'replica', True, False)}, 'CDC_WAL_UNAVAILABLE'),
    ({'server': (180003, 'logical', True, True)}, 'CDC_REPLICATION_ROLE_REQUIRED'),
    ({'table': (True, 'd', 'r', False)}, 'CDC_REPLICA_IDENTITY_FULL_REQUIRED'),
    ({'table': (True, 'f', 'r', True)}, 'CDC_TABLE_UNSUPPORTED'),
    ({'publication_tables': [('public', 'orders'), ('public', 'other')]}, 'CDC_PUBLICATION_REQUIRED'),
])
def test_source_and_publication_drift_fails_closed(scope, values, code):
    with pytest.raises(CdcError, match=code):
        postgres.preflight(SourceConnection(values), scope)


def test_reseed_required_pipeline_does_not_block_other_controller_work(scope, monkeypatch):
    remove=Mock()
    monkeypatch.setattr(worker, 'remove_password', remove)
    connector, control=Mock(), Mock()
    connector.request.return_value={'connector': {'state': 'RUNNING'}, 'tasks': [{'state': 'RUNNING'}]}
    worker.control_pipeline({'scope': scope.__dict__, 'desired_state': 'PAUSED',
                             'observed_state': 'RESEED_REQUIRED'}, control, connector, None)
    connector.pause.assert_called_once_with(scope)
    remove.assert_not_called()
    control.update.assert_not_called()


def test_stopped_pipeline_does_not_issue_repeated_stop_or_callback(scope, monkeypatch):
    remove=Mock()
    monkeypatch.setattr(worker, 'remove_password', remove)
    connector, control=Mock(), Mock()
    connector.request.return_value={'connector': {'state': 'STOPPED'}, 'tasks': []}
    connection=Mock()
    monkeypatch.setattr(worker, 'decrypt_credential', lambda *_: 'unit-secret')
    monkeypatch.setattr(postgres, 'connect', lambda *_: connection)
    monkeypatch.setattr(postgres, 'slot_health', lambda *_args, **_kwargs: (
        {'slot_active': False, 'retained_wal_bytes': 1, 'wal_warning': False}, None, True))
    worker.control_pipeline({'scope': scope.__dict__, 'desired_state': 'PAUSED',
                             'observed_state': 'PAUSED', 'applied_credential_version': 1,
                             'credential': {'key_version': 1, 'ciphertext': 'encrypted'},
                             'connection_metadata': {}}, control, connector, None)
    connector.pause.assert_not_called()
    control.update.assert_not_called()
    remove.assert_called_once_with(scope)


def test_pause_waits_for_physical_slot_release(scope, monkeypatch):
    monkeypatch.setattr(worker, 'decrypt_credential', lambda *_: 'unit-secret')
    monkeypatch.setattr(postgres, 'connect', lambda *_: Mock())
    monkeypatch.setattr(postgres, 'slot_health', lambda *_args, **_kwargs: (
        {'slot_active': True, 'retained_wal_bytes': 8, 'wal_warning': False}, 123, True))
    remove=Mock()
    monkeypatch.setattr(worker, 'remove_password', remove)
    connector, control=Mock(), Mock()
    connector.request.return_value={'connector': {'state': 'STOPPED'}, 'tasks': []}
    worker.control_pipeline({'scope': scope.__dict__, 'desired_state': 'PAUSED',
                             'observed_state': 'PAUSING', 'applied_credential_version': 1,
                             'credential': {'key_version': 1, 'ciphertext': 'encrypted'},
                             'connection_metadata': {}}, control, connector, None)
    control.update.assert_not_called()
    remove.assert_not_called()


def test_stop_request_does_not_claim_pause(scope, monkeypatch):
    connector, control=Mock(), Mock()
    connector.request.return_value={'connector': {'state': 'RUNNING'}, 'tasks': [{'state': 'RUNNING'}]}
    worker.control_pipeline({'scope': scope.__dict__, 'desired_state': 'PAUSED',
                             'observed_state': 'PAUSING'}, control, connector, None)
    connector.pause.assert_called_once_with(scope)
    control.update.assert_not_called()


@pytest.mark.parametrize('slot_active', [False, True])
def test_failed_connect_task_recovery_preserves_active_slot_boundary(scope, monkeypatch, slot_active):
    columns = [{'name': 'id', 'type': 'integer'}]
    health = {'slot_active': slot_active, 'retained_wal_bytes': 0, 'wal_warning': False}
    monkeypatch.setattr(worker, 'decrypt_credential', lambda *_: 'unit-secret')
    monkeypatch.setattr(postgres, 'connect', lambda *_: Mock())
    monkeypatch.setattr(postgres, 'preflight', lambda *_args, **_kwargs: (columns, ['id'], health))
    monkeypatch.setattr(worker, 'connector_configuration', lambda *_: {'safe': 'config'})
    monkeypatch.setattr(worker, '_write_password_fenced', Mock())
    connector, control = Mock(), Mock()
    connector.request.side_effect = [
        {'connector': {'state': 'RUNNING'}, 'tasks': [{'state': 'FAILED'}]},
        {'safe': 'config'},
    ]
    item = {'scope': scope.__dict__, 'desired_state': 'STREAMING',
            'observed_state': 'STREAMING', 'credential': {'key_version': 1, 'ciphertext': 'encrypted'},
            'connection_metadata': {}, 'columns': columns, 'primary_key': ['id'],
            'capture_slot_seen': True, 'snapshot_signal': {}, 'credential_version': 1,
            'applied_credential_version': 1}
    if slot_active:
        with pytest.raises(CdcError, match='CDC_CONNECT_TASK_ORPHANED'):
            worker.control_pipeline(item, control, connector, Mock())
        connector.pause.assert_not_called()
    else:
        assert worker.control_pipeline(item, control, connector, Mock()) == 2
        connector.pause.assert_called_once_with(scope)
        connector.configure.assert_not_called()
        control.update.assert_not_called()


def test_controller_scheduler_isolates_blocked_scope(scope):
    from threading import Event
    blocked, healthy = Event(), Event()
    scheduler = worker.ControllerScheduler(workers=2)
    other = Scope(11, scope.source_id, '00000000-0000-0000-0000-000000000003', 3, 'public', 'orders')
    def run_one(item):
        if item['scope']['pipeline_id'] == scope.pipeline_id:
            blocked.wait(2)
        else:
            healthy.set()
        return 0
    scheduler._control = run_one
    try:
        scheduler.step([{'scope': scope.__dict__, 'desired_state': 'STREAMING', 'observed_state': 'STREAMING'},
                        {'scope': other.__dict__, 'desired_state': 'STREAMING', 'observed_state': 'STREAMING'}])
        assert healthy.wait(1)
    finally:
        blocked.set()
        scheduler.pool.shutdown(wait=True)


def test_one_rejected_controller_callback_does_not_starve_next_scope(scope, monkeypatch):
    first=Mock()
    first.side_effect=[RuntimeError('rejected callback'), None]
    monkeypatch.setattr(worker, 'control_pipeline', first)
    item={'scope': scope.__dict__}
    worker.control_one(item, Mock(), Mock(), None)
    worker.control_one(item, Mock(), Mock(), None)
    assert first.call_count == 2


def test_transient_connect_failure_retries_without_changing_intent(scope, monkeypatch):
    monkeypatch.setattr(worker, 'control_pipeline', Mock(side_effect=CdcError('CDC_CONNECT_UNAVAILABLE')))
    connector, control=Mock(), Mock()
    delay=worker.control_one({'scope': scope.__dict__, 'desired_state': 'STREAMING'}, control, connector, None)
    assert delay == 2
    connector.pause.assert_not_called()
    control.update.assert_not_called()


def test_retired_stale_scope_stops_without_rejected_callback(scope, monkeypatch):
    remove=Mock()
    monkeypatch.setattr(worker, 'remove_password', remove)
    connector, control=Mock(), Mock()
    connector.request.return_value={'connector': {'state': 'STOPPED'}, 'tasks': []}
    delay=worker.control_one({'scope': scope.__dict__, 'desired_state': 'STOPPED',
                              'observed_state': 'DEGRADED', 'control_suppressed': True},
                             control, connector, None)
    assert delay == 300
    remove.assert_called_once_with(scope)
    control.update.assert_not_called()
