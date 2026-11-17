"""Fresh, disposable D5-R3 empty-snapshot boundary probe.

Persists bounded physical/control evidence even when a gate fails. No slot,
offset, connector or source row is rewritten to manufacture a pass.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import time
import uuid
import requests

from kafka import KafkaAdminClient, KafkaConsumer, TopicPartition

from verify_foundation_d_cdc import Fixture, wait_for
from verify_foundation_d5_r1 import control_row, reseed, wait_candidate
from verify_foundation_d5_r2 import request_reconciliation
from bi_platform_shared.cdc_contract import Scope
from shared.cdc.connect import ConnectClient
from shared.cdc.worker import snapshot_notification


def now():
    return datetime.now(timezone.utc).isoformat()


def observe_topic(consumer, topic, row_id=1):
    partition = TopicPartition(topic, 0)
    consumer.assign([partition])
    consumer.seek_to_beginning(partition)
    end = consumer.end_offsets([partition])[partition]
    while consumer.position(partition) < end:
        for message in consumer.poll(timeout_ms=100, max_records=200).values():
            for record in message:
                if record.value is None:
                    continue
                value = json.loads(record.value)
                after = value.get('after') or {}
                if after.get('id') == row_id:
                    return {'offset': record.offset, 'at': now(),
                            'event_id': value.get('event_id')}
    return None


def notification_history(scope):
    consumer = KafkaConsumer(bootstrap_servers='kafka:9092', group_id=None,
                             enable_auto_commit=False, consumer_timeout_ms=1000)
    result = []
    try:
        partition = TopicPartition(scope.topic('notification'), 0)
        consumer.assign([partition])
        consumer.seek_to_beginning(partition)
        end = consumer.end_offsets([partition])[partition]
        while consumer.position(partition) < end:
            for messages in consumer.poll(timeout_ms=200, max_records=100).values():
                for record in messages:
                    if record.value is None:
                        continue
                    try:
                        signal = snapshot_notification(json.loads(record.value), scope,
                                                       record.partition, record.offset)
                    except Exception:
                        continue
                    if signal:
                        result.append({'kafka_timestamp_ms': record.timestamp, **signal})
    finally:
        consumer.close()
    return result


def inject_disposable_lost_slot(fixture, evidence_path):
    evidence = json.loads(Path(evidence_path).read_text(encoding='utf-8'))
    scope = Scope(**evidence['candidate'])
    if scope.generation != 2 or evidence.get('status') != 'FAIL':
        raise AssertionError('Only the failed disposable generation-2 probe is eligible')
    connector = ConnectClient()
    connector.pause(scope)
    connector.wait_stopped(scope)
    database = fixture_source_database(fixture, scope)
    slot_name = 'b_' + scope.token
    with fixture.pg(database) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute('SELECT active FROM pg_replication_slots WHERE slot_name=%s',
                           (slot_name,))
            row = cursor.fetchone()
            if row != (False,):
                raise AssertionError('Exact candidate slot is absent or active')
            cursor.execute('SELECT pg_drop_replication_slot(%s)', (slot_name,))
    result = {'case': 'disposable_candidate_lost_slot', 'at': now(),
              'pipeline_id': scope.pipeline_id, 'generation': scope.generation,
              'source_evidence': Path(evidence_path).name,
              'connector_stopped': True, 'slot_dropped': slot_name}
    path = fixture.env_file.parent / f'd5-r3-lost-slot-{uuid.uuid4().hex[:8]}.json'
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'evidence': str(path), 'slot_dropped': slot_name}))


def verify_disposable_lost_slot(fixture, evidence_path):
    evidence_path = Path(evidence_path)
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    source_evidence = evidence.get('source_evidence', 'd5-r3-overlap-3dba1569.json')
    scope = Scope(**json.loads((fixture.env_file.parent /
        source_evidence).read_text(encoding='utf-8'))['candidate'])
    if evidence['pipeline_id'] != scope.pipeline_id or evidence['generation'] != scope.generation:
        raise AssertionError('fault evidence does not match disposable candidate')
    state = sample(fixture, scope, ConnectClient())
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT cdc_generation FROM manager_databases WHERE id=%s',
                           (scope.dataset_id,))
            query_generation = cursor.fetchone()[0]
    old = Scope(scope.workspace_id, scope.source_id, scope.pipeline_id,
                scope.dataset_id, scope.schema, scope.table, 1)
    result = {'at': now(), 'error_code': state['error'],
              'observed_state': state['observed'], 'generation_state': state['generation_state'],
              'candidate_slot_absent': state['slot'] is None,
              'query_generation': query_generation,
              'old_query_exact_empty': fixture.rows_equal(old, [])}
    evidence['observed'] = result
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    if (result['error_code'] != 'CDC_SLOT_LOST'
            or result['observed_state'] != 'RESEED_REQUIRED'
            or result['generation_state'] != 'FAILED'
            or not result['candidate_slot_absent']
            or result['query_generation'] != 1
            or not result['old_query_exact_empty']):
        raise AssertionError('lost-slot fail-closed invariant did not hold')
    print(json.dumps(result))


def recover_disposable_lost_slot(fixture, evidence_path):
    evidence_path = Path(evidence_path)
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    old_scope = Scope(**json.loads((fixture.env_file.parent /
        evidence['source_evidence']).read_text(encoding='utf-8'))['candidate'])
    if evidence.get('observed', {}).get('error_code') != 'CDC_SLOT_LOST':
        raise AssertionError('lost-slot classification must be verified before reseed')
    session = requests.Session()
    session.trust_env = False
    response = session.post(
        fixture.base + f'/database/sources/{old_scope.source_id}/cdc/reseed/',
        json={'pipeline_id': old_scope.pipeline_id, 'intent': 'reseed', 'reason': 'slot_lost'},
        headers={'Authorization': 'Bearer ' + fixture.token(old_scope.workspace_id),
                 'X-Cdc-Operator-Key': 'd5-r1-isolated-fixture-only'}, timeout=20)
    if response.status_code != 202:
        raise AssertionError(f'authorized reseed HTTP {response.status_code}')
    generation = response.json()['data']['generation']
    if generation != 3:
        raise AssertionError(f'expected fresh generation 3, got {generation}')
    candidate = Scope(old_scope.workspace_id, old_scope.source_id,
                      old_scope.pipeline_id, old_scope.dataset_id,
                      old_scope.schema, old_scope.table, generation)
    evidence['recovery_candidate'] = candidate.__dict__
    evidence['reseed_at'] = now()
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    database = fixture_source_database(fixture, candidate)
    wait_candidate(fixture, candidate, database, empty=True)
    wait_for('generation-3 candidate capture readiness',
             lambda: sample(fixture, candidate, ConnectClient())['capture_ready'],
             seconds=120)
    proof = request_reconciliation(fixture, candidate)
    evidence['recovery_certificate'] = {
        'kind': proof['kind'], 'status': proof['status'],
        'source_lsn': proof['source_lsn']}
    evidence['certificate_at'] = now()
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps({'pipeline_id': candidate.pipeline_id,
                      'generation': generation, 'certificate': evidence['recovery_certificate'],
                      'evidence': str(evidence_path)}), flush=True)


def verify_disposable_recovery(fixture, evidence_path):
    evidence_path = Path(evidence_path)
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    candidate = Scope(**evidence['recovery_candidate'])
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT cdc_generation FROM manager_databases WHERE id=%s',
                           (candidate.dataset_id,))
            query_generation = cursor.fetchone()[0]
            cursor.execute('SELECT number,state FROM integration_cdc_generations '
                           'WHERE pipeline_id=%s ORDER BY number', (candidate.pipeline_id,))
            lineage = cursor.fetchall()
    state = sample(fixture, candidate, ConnectClient())
    database = fixture_source_database(fixture, candidate)
    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT slot_name FROM pg_replication_slots WHERE slot_name=%s',
                           (evidence['slot_dropped'],))
            lost_slot_recreated = cursor.fetchone() is not None
    result = {'at': now(), 'query_generation': query_generation,
              'lineage': lineage, 'old_slot_recreated': lost_slot_recreated,
              'new_slot_active': bool(state['slot'] and state['slot'][3]),
              'authorized_query_exact_empty': fixture.rows_equal(candidate, [])}
    evidence['recovery_verified'] = result
    evidence_path.write_text(json.dumps(evidence, indent=2, default=str), encoding='utf-8')
    if (query_generation != 3 or lineage != [(1, 'SUPERSEDED'), (2, 'FAILED'), (3, 'ACTIVE')]
            or lost_slot_recreated or not result['new_slot_active']
            or not result['authorized_query_exact_empty']):
        raise AssertionError('explicit lost-slot recovery did not satisfy lineage/Query invariants')
    print(json.dumps(result, default=str))


def inject_disposable_retention_gap(fixture, recovery_evidence_path):
    recovered = json.loads(Path(recovery_evidence_path).read_text(encoding='utf-8'))
    if recovered.get('recovery_verified', {}).get('query_generation') != 3:
        raise AssertionError('only the verified disposable generation-3 source is eligible')
    scope = Scope(**recovered['recovery_candidate'])
    partition = TopicPartition(scope.raw_topic, 0)
    consumer = KafkaConsumer(bootstrap_servers='kafka:9092',
                             group_id=f'biavora-cdc-v1-{scope.token}-normalize',
                             enable_auto_commit=False, consumer_timeout_ms=1000)
    path = fixture.env_file.parent / f'd5-r3-retention-gap-{uuid.uuid4().hex[:8]}.json'
    evidence = {'case': 'disposable_candidate_kafka_retention_gap',
                'source_evidence': Path(recovery_evidence_path).name,
                'pipeline_id': scope.pipeline_id, 'generation': scope.generation,
                'raw_topic': scope.raw_topic, 'at': now()}
    try:
        consumer.assign([partition])
        beginning = consumer.beginning_offsets([partition])[partition]
        end = consumer.end_offsets([partition])[partition]
        committed = consumer.committed(partition)
        checkpoint = sample(fixture, scope, ConnectClient())['checkpoints'].get('normalize:0')
        position = committed if committed is not None else (
            checkpoint['offset'] + 1 if checkpoint else 0)
        evidence.update(beginning_before=beginning, end_before=end,
                        committed_before=committed, resume_position=position)
        if not beginning <= position <= end:
            raise AssertionError('baseline normalize offset is already outside retention')
        database = fixture_source_database(fixture, scope)
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO public.orders VALUES (77,'retention-gap',2,'new')")
        evidence['source_insert_committed_at'] = now()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            new_end = consumer.end_offsets([partition])[partition]
            if new_end > end:
                break
            time.sleep(0.5)
        else:
            raise AssertionError('source row did not reach raw topic')
        evidence['raw_end_after_insert'] = new_end
        admin = KafkaAdminClient(bootstrap_servers='kafka:9092')
        try:
            admin.delete_records({partition: new_end})
        finally:
            admin.close()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            retained_beginning = consumer.beginning_offsets([partition])[partition]
            if retained_beginning == new_end:
                break
            time.sleep(0.25)
        evidence['retained_beginning'] = retained_beginning
        evidence['gap_confirmed'] = retained_beginning > position
        if not evidence['gap_confirmed']:
            raise AssertionError('broker retained beginning did not pass durable resume position')
        print(json.dumps({'evidence': str(path), 'resume_position': position,
                          'retained_beginning': retained_beginning}), flush=True)
    finally:
        consumer.close()
        path.write_text(json.dumps(evidence, indent=2), encoding='utf-8')


def verify_disposable_retention_gap(fixture, evidence_path):
    evidence_path = Path(evidence_path)
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    recovered = json.loads((fixture.env_file.parent /
        evidence['source_evidence']).read_text(encoding='utf-8'))
    scope = Scope(**recovered['recovery_candidate'])
    state = sample(fixture, scope, ConnectClient())
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT cdc_generation FROM manager_databases WHERE id=%s',
                           (scope.dataset_id,))
            query_generation = cursor.fetchone()[0]
    result = {'at': now(), 'error_code': state['error'],
              'observed_state': state['observed'],
              'generation_state': state['generation_state'],
              'checkpoints': state['checkpoints'],
              'query_generation': query_generation,
              'old_query_exact_empty': fixture.rows_equal(scope, [])}
    evidence['observed'] = result
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    if (result['error_code'] != 'CDC_KAFKA_RETENTION_LOST'
            or result['observed_state'] != 'RESEED_REQUIRED'
            or result['generation_state'] != 'RESEED_REQUIRED'
            or result['checkpoints'] != {}
            or query_generation != 3 or not result['old_query_exact_empty']):
        raise AssertionError('retention-gap fail-closed invariants did not hold')
    print(json.dumps(result))


def recover_disposable_retention_gap(fixture, evidence_path):
    evidence_path = Path(evidence_path)
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    recovered = json.loads((fixture.env_file.parent /
        evidence['source_evidence']).read_text(encoding='utf-8'))
    old_scope = Scope(**recovered['recovery_candidate'])
    if evidence.get('observed', {}).get('error_code') != 'CDC_KAFKA_RETENTION_LOST':
        raise AssertionError('retention gap must be verified before reseed')
    session = requests.Session()
    session.trust_env = False
    response = session.post(
        fixture.base + f'/database/sources/{old_scope.source_id}/cdc/reseed/',
        json={'pipeline_id': old_scope.pipeline_id, 'intent': 'reseed',
              'reason': 'operator_reseed'},
        headers={'Authorization': 'Bearer ' + fixture.token(old_scope.workspace_id),
                 'X-Cdc-Operator-Key': 'd5-r1-isolated-fixture-only'}, timeout=20)
    if response.status_code != 202:
        raise AssertionError(f'authorized retention recovery reseed HTTP {response.status_code}')
    generation = response.json()['data']['generation']
    if generation != 4:
        raise AssertionError(f'expected fresh generation 4, got {generation}')
    candidate = Scope(old_scope.workspace_id, old_scope.source_id,
                      old_scope.pipeline_id, old_scope.dataset_id,
                      old_scope.schema, old_scope.table, generation)
    evidence['recovery_candidate'] = candidate.__dict__
    evidence['reseed_at'] = now()
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    database = fixture_source_database(fixture, candidate)
    wait_candidate(fixture, candidate, database)
    wait_for('generation-4 candidate capture readiness',
             lambda: sample(fixture, candidate, ConnectClient())['capture_ready'],
             seconds=120)
    proof = request_reconciliation(fixture, candidate)
    evidence['recovery_certificate'] = {
        'kind': proof['kind'], 'status': proof['status'],
        'source_lsn': proof['source_lsn']}
    evidence['certificate_at'] = now()
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps({'pipeline_id': candidate.pipeline_id,
                      'generation': generation, 'certificate': evidence['recovery_certificate'],
                      'evidence': str(evidence_path)}), flush=True)


def verify_disposable_retention_recovery(fixture, evidence_path):
    evidence_path = Path(evidence_path)
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    candidate = Scope(**evidence['recovery_candidate'])
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT cdc_generation FROM manager_databases WHERE id=%s',
                           (candidate.dataset_id,))
            query_generation = cursor.fetchone()[0]
            cursor.execute('SELECT number,state FROM integration_cdc_generations '
                           'WHERE pipeline_id=%s ORDER BY number', (candidate.pipeline_id,))
            lineage = cursor.fetchall()
    expected = [[77, 'retention-gap', Decimal(2), 'new']]
    result = {'at': now(), 'query_generation': query_generation,
              'lineage': lineage,
              'authorized_query_exact_one_row': fixture.rows_equal(candidate, expected)}
    evidence['recovery_verified'] = result
    evidence_path.write_text(json.dumps(evidence, indent=2, default=str), encoding='utf-8')
    if (query_generation != 4 or lineage != [(1, 'SUPERSEDED'), (2, 'FAILED'),
                                             (3, 'SUPERSEDED'), (4, 'ACTIVE')]
            or not result['authorized_query_exact_one_row']):
        raise AssertionError('retention recovery did not restore exact Query state')
    print(json.dumps(result, default=str))


def sample(fixture, scope, connector):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('''SELECT p.observed_state,p.error_code,p.snapshot_signal,
                p.capture_slot_seen,p.capture_ready,p.checkpoints,p.controller_fence,
                p.controller_lease_owner,p.controller_lease_until,p.credential_version,
                s.configuration_version,g.state,g.validation_certificate,
                g.reconciliation_attempt,g.created_at
                FROM integration_cdc_pipelines p
                JOIN integration_data_sources s ON s.id=p.source_id
                JOIN integration_cdc_generations g
                  ON g.pipeline_id=p.id AND g.number=p.generation
                WHERE p.id=%s''', (scope.pipeline_id,))
            row = cursor.fetchone()
    with fixture.pg(fixture_source_database(fixture, scope)) as connection:
        with connection.cursor() as cursor:
            cursor.execute('''SELECT slot_type,plugin,database,active,active_pid,
                restart_lsn::text,confirmed_flush_lsn::text,wal_status
                FROM pg_replication_slots WHERE slot_name=%s''', ('b_' + scope.token,))
            slot = cursor.fetchone()
            cursor.execute('''SELECT pubname FROM pg_publication
                WHERE pubname=%s''', ('b_' + scope.publication_token,))
            publication = cursor.fetchone() is not None
    try:
        status = connector.request(scope, '/status') or {}
        offsets = connector.request(scope, '/offsets') or {}
        configured = connector.request(scope, '/config') is not None
    except Exception:
        status, offsets, configured = {}, {}, False
    return {
        'at': now(), 'observed': row[0], 'error': row[1],
        'snapshot': row[2], 'slot_seen': row[3], 'capture_ready': row[4],
        'checkpoints': row[5], 'controller_fence': row[6],
        'controller_lease_owner': str(row[7]) if row[7] else None,
        'controller_lease_until': str(row[8]) if row[8] else None,
        'credential_version': row[9], 'configuration_epoch': row[10],
        'generation_state': row[11],
        'certificate': {'kind': row[12].get('kind'), 'status': row[12].get('status')},
        'reconciliation_attempt': row[13], 'candidate_created_at': str(row[14]),
        'slot': slot, 'publication_present': publication,
        'connector_configured': configured,
        'connect_state': status.get('connector', {}).get('state'),
        'task_states': [task.get('state') for task in status.get('tasks', [])],
        'source_offsets': [item.get('offset', {}) for item in offsets.get('offsets', [])],
    }


def fixture_source_database(fixture, scope):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('''SELECT s.connection_metadata->>'database'
                FROM integration_cdc_pipelines p JOIN integration_data_sources s
                  ON s.id=p.source_id WHERE p.id=%s''', (scope.pipeline_id,))
            return cursor.fetchone()[0]


def run(fixture):
    evidence = {'case': 'empty_snapshot_transaction_overlap', 'timeline': {},
                'observations': [], 'status': 'FAIL'}
    path = fixture.env_file.parent / f'd5-r3-overlap-{uuid.uuid4().hex[:8]}.json'
    connector = ConnectClient()
    source_connection = None
    try:
        old, database = fixture.d2_source(row_count=0)
        evidence['source_database'] = database
        wait_for('old empty Query authority', lambda: fixture.rows_equal(old, []), seconds=180)
        candidate = reseed(fixture, old, 'operator_reseed')
        evidence['candidate'] = candidate.__dict__
        evidence['timeline']['candidate_created'] = now()
        deadline = time.monotonic() + 120
        seen = set()
        while time.monotonic() < deadline:
            state = sample(fixture, candidate, connector)
            evidence['observations'].append(state)
            for label, condition in (
                ('connector_configured', state['connector_configured']),
                ('slot_created', state['slot'] is not None),
                ('slot_active', bool(state['slot'] and state['slot'][3])),
                ('snapshot_started', state['snapshot'].get('status') == 'STARTED'),
                ('table_scan_completed', state['snapshot'].get('status') == 'SCANNED'),
                ('snapshot_completed', state['snapshot'].get('status') == 'COMPLETED'),
                ('capture_ready', state['capture_ready']),
            ):
                if condition and label not in seen:
                    evidence['timeline'][label] = state['at']
                    seen.add(label)
            if state['error']:
                raise AssertionError('candidate error ' + state['error'])
            if state['capture_ready'] and state['snapshot'].get('status') == 'STARTED':
                break
            time.sleep(0.25)
        else:
            raise AssertionError('candidate capture/snapshot-start readiness not reached')
        source_connection = fixture.pg(database)
        with source_connection.cursor() as cursor:
            cursor.execute("INSERT INTO public.orders VALUES (1,'boundary-overlap',2,'new')")
        evidence['timeline']['transaction_begin_insert'] = now()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            state = sample(fixture, candidate, connector)
            evidence['observations'].append(state)
            if state['snapshot'].get('status') in {'SCANNED', 'COMPLETED'}:
                evidence['timeline']['table_scan_completed'] = state['at']
                break
            if state['error']:
                raise AssertionError('candidate error ' + state['error'])
            time.sleep(0.25)
        else:
            raise AssertionError('snapshot scan did not complete with insert uncommitted')
        source_connection.commit()
        evidence['timeline']['transaction_commit'] = now()
        source_connection.close()
        source_connection = None
        wait_candidate(fixture, candidate, database)
        evidence['timeline']['loader_applied'] = now()
        consumer = KafkaConsumer(bootstrap_servers='kafka:9092', group_id=None,
                                 enable_auto_commit=False, consumer_timeout_ms=1000)
        try:
            for label, topic in (
                ('raw_event_received', candidate.raw_topic),
                ('normalized_event_received', candidate.topic('normalized')),
                ('transformed_event_received', candidate.topic('transformed')),
            ):
                result = observe_topic(consumer, topic)
                if result is None:
                    raise AssertionError(label + ' missing')
                evidence['timeline'][label] = result['at']
                evidence[label] = {'offset': result['offset'], 'event_id': result['event_id']}
        finally:
            consumer.close()
        proof = request_reconciliation(fixture, candidate)
        evidence['timeline']['certificate_issued'] = now()
        evidence['certificate'] = {'kind': proof['kind'], 'status': proof['status'],
                                   'source_lsn': proof['source_lsn']}
        evidence['status'] = 'CERTIFIED_PENDING_CUTOVER'
        return path, evidence
    except Exception as exc:
        evidence['failure'] = type(exc).__name__ + ': ' + str(exc)[:120]
        raise
    finally:
        if source_connection is not None:
            source_connection.rollback()
            source_connection.close()
        path.write_text(json.dumps(evidence, indent=2, default=str), encoding='utf-8')
        print(json.dumps({'evidence': str(path), 'status': evidence['status'],
                          'failure': evidence.get('failure')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--resume-evidence')
    parser.add_argument('--inspect-notifications')
    parser.add_argument('--inject-disposable-lost-slot')
    parser.add_argument('--verify-disposable-lost-slot')
    parser.add_argument('--recover-disposable-lost-slot')
    parser.add_argument('--verify-disposable-recovery')
    parser.add_argument('--inject-disposable-retention-gap')
    parser.add_argument('--verify-disposable-retention-gap')
    parser.add_argument('--recover-disposable-retention-gap')
    parser.add_argument('--verify-disposable-retention-recovery')
    args = parser.parse_args()
    fixture = Fixture(args.env_file)
    if args.verify_disposable_retention_recovery:
        verify_disposable_retention_recovery(fixture, args.verify_disposable_retention_recovery)
    elif args.recover_disposable_retention_gap:
        recover_disposable_retention_gap(fixture, args.recover_disposable_retention_gap)
    elif args.verify_disposable_retention_gap:
        verify_disposable_retention_gap(fixture, args.verify_disposable_retention_gap)
    elif args.inject_disposable_retention_gap:
        inject_disposable_retention_gap(fixture, args.inject_disposable_retention_gap)
    elif args.verify_disposable_recovery:
        verify_disposable_recovery(fixture, args.verify_disposable_recovery)
    elif args.recover_disposable_lost_slot:
        recover_disposable_lost_slot(fixture, args.recover_disposable_lost_slot)
    elif args.verify_disposable_lost_slot:
        verify_disposable_lost_slot(fixture, args.verify_disposable_lost_slot)
    elif args.inject_disposable_lost_slot:
        inject_disposable_lost_slot(fixture, args.inject_disposable_lost_slot)
    elif args.inspect_notifications:
        evidence = json.loads(Path(args.inspect_notifications).read_text(encoding='utf-8'))
        print(json.dumps(notification_history(Scope(**evidence['candidate']))))
    elif args.resume_evidence:
        evidence_path = Path(args.resume_evidence)
        evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        scope = Scope(**evidence['candidate'])
        proof = request_reconciliation(fixture, scope)
        evidence['timeline']['certificate_issued'] = now()
        evidence['certificate'] = {'kind': proof['kind'], 'status': proof['status'],
                                   'source_lsn': proof['source_lsn']}
        # A later certificate for the retained empty candidate does not turn
        # the earlier transaction-overlap timing failure into a pass.
        evidence['post_failure_empty_certificate'] = evidence.pop('certificate')
        evidence['post_failure_certificate_at'] = evidence['timeline'].pop('certificate_issued')
        evidence['status'] = 'FAIL'
        evidence_path.write_text(json.dumps(evidence, indent=2, default=str), encoding='utf-8')
        print(json.dumps({'evidence': str(evidence_path), 'certificate': evidence['certificate']}))
    else:
        run(fixture)
