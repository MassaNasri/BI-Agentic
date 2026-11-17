"""Disposable D5-R4A snapshot/WAL boundary acceptance with an explicit PG gate.

The gate is selected only by the isolated controller's environment and is
never supplied through the public CDC API or production connector config.
"""

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import time
import uuid

from kafka import KafkaConsumer, TopicPartition
from psycopg2 import sql

from bi_platform_shared.cdc_contract import CdcError, Scope
from shared.cdc.connect import ConnectClient
from verify_foundation_d_cdc import Fixture, wait_for
from verify_foundation_d5_r1 import reseed, wait_candidate
from verify_foundation_d5_r2 import request_reconciliation
from verify_foundation_d5_r2 import certificate as read_certificate
from verify_foundation_d5_r3 import notification_history, sample


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, evidence):
    path.write_text(json.dumps(evidence, indent=2, default=str), encoding='utf-8')


def create_old(fixture):
    old, database = fixture.d2_source(row_count=0)
    wait_for('generation-1 empty Query authority',
             lambda: fixture.rows_equal(old, []), seconds=180)
    path = fixture.env_file.parent / f'd5-r4a-overlap-{uuid.uuid4().hex[:8]}.json'
    evidence = {'case': 'gated_empty_snapshot_overlap', 'status': 'PREPARING',
                'old': old.__dict__, 'source_database': database,
                'timeline': {'old_query_ready': now()}}
    save(path, evidence)
    print(json.dumps({'evidence': str(path), 'old_query_ready': True}), flush=True)


def source_role(fixture, scope):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT s.connection_metadata->>'username' "
                           "FROM integration_cdc_pipelines p JOIN integration_data_sources s "
                           "ON s.id=p.source_id WHERE p.id=%s", (scope.pipeline_id,))
            return cursor.fetchone()[0]


def install_gate_function(fixture, database, role):
    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute('''CREATE OR REPLACE FUNCTION public.biavora_d5_r4a_snapshot_orders(bigint)
                RETURNS SETOF public.orders LANGUAGE plpgsql SECURITY INVOKER AS $fixture$
                BEGIN
                    PERFORM pg_advisory_xact_lock($1);
                    RETURN QUERY SELECT * FROM public.orders;
                END
                $fixture$''')
            cursor.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '
                                   'public.biavora_d5_r4a_snapshot_orders(bigint) TO {}')
                           .format(sql.Identifier(role)))


def gate_backend(fixture, database, role):
    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute('''SELECT pid,wait_event_type,wait_event,query_start::text
                FROM pg_stat_activity WHERE datname=%s AND usename=%s
                AND query LIKE '%%biavora_d5_r4a_snapshot_orders%%'
                AND query NOT LIKE '%%pg_stat_activity%%'
                ORDER BY query_start DESC LIMIT 1''', (database, role))
            return cursor.fetchone()


def row_event(scope, topic):
    consumer = KafkaConsumer(bootstrap_servers='kafka:9092', group_id=None,
                             enable_auto_commit=False, consumer_timeout_ms=1000)
    try:
        partition = TopicPartition(topic, 0)
        consumer.assign([partition])
        consumer.seek_to_beginning(partition)
        end = consumer.end_offsets([partition])[partition]
        while consumer.position(partition) < end:
            for messages in consumer.poll(timeout_ms=100, max_records=200).values():
                for record in messages:
                    if record.value is None:
                        continue
                    event = json.loads(record.value)
                    event = event.get('payload', event)
                    if (event.get('after') or {}).get('id') == 1:
                        return {'offset': record.offset,
                                'operation': event.get('operation', event.get('op')),
                                'event_id': event.get('event_id'),
                                'kafka_timestamp_ms': record.timestamp}
    finally:
        consumer.close()
    return None


def run_overlap(fixture, path):
    path = Path(path)
    evidence = json.loads(path.read_text(encoding='utf-8'))
    old = Scope(**evidence['old'])
    database = evidence['source_database']
    role = source_role(fixture, old)
    gate_connection = fixture.pg(database)
    gate_connection.autocommit = True
    transaction = None
    lock_key = None
    try:
        install_gate_function(fixture, database, role)
        candidate = Scope(old.workspace_id, old.source_id, old.pipeline_id,
                          old.dataset_id, old.schema, old.table, 2)
        lock_key = int(candidate.token[:15], 16)
        with gate_connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_lock(%s)', (lock_key,))
        evidence['timeline']['gate_lock_held'] = now()
        candidate = reseed(fixture, old, 'operator_reseed')
        evidence['candidate'] = candidate.__dict__
        evidence['gate_scope_token'] = candidate.token
        evidence['gate_lock_key'] = lock_key
        evidence['timeline']['candidate_created'] = now()
        evidence['status'] = 'WAITING_FOR_CONTROLLER_GATE_CONFIG'
        save(path, evidence)
        print(json.dumps({'stage': 'GATE_HELD_CANDIDATE_CREATED',
                          'scope_token': candidate.token, 'evidence': str(path)}), flush=True)

        connector = ConnectClient()
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                state = sample(fixture, candidate, connector)
                backend = gate_backend(fixture, database, role)
                config = connector.request(candidate, '/config') or {}
            except CdcError:
                # Connect can return 5xx while a connector is first created.
                # No snapshot boundary has been observed yet; retain the lock.
                time.sleep(0.5)
                continue
            gate_configured = config.get('snapshot.select.statement.overrides.public.orders') == (
                f'SELECT * FROM public.biavora_d5_r4a_snapshot_orders({lock_key})')
            if state['error']:
                raise AssertionError('candidate error ' + state['error'])
            slot = state['slot']
            if (gate_configured and backend and backend[1:3] == ('Lock', 'advisory')
                    and slot and slot[0:3] == ('logical', 'pgoutput', database)
                    and state['connect_state'] == 'RUNNING'
                    and state['task_states'] == ['RUNNING']):
                evidence['gate_backend'] = {'pid': backend[0],
                    'wait_event_type': backend[1], 'wait_event': backend[2],
                    'query_start': backend[3]}
                evidence['gate_slot'] = state['slot']
                evidence['gate_connect_state'] = state['connect_state']
                evidence['timeline']['snapshot_gate_reached'] = now()
                break
            time.sleep(0.5)
        else:
            raise AssertionError('snapshot SELECT did not reach explicit advisory gate')

        transaction = fixture.pg(database)
        with transaction.cursor() as cursor:
            cursor.execute('BEGIN')
            evidence['timeline']['transaction_begin'] = now()
            cursor.execute("INSERT INTO public.orders VALUES (1,'boundary-overlap',2,'new')")
            evidence['timeline']['insert_uncommitted'] = now()
        with fixture.pg(database) as observer:
            with observer.cursor() as cursor:
                cursor.execute('SELECT count(*) FROM public.orders WHERE id=1')
                evidence['uncommitted_invisible'] = cursor.fetchone()[0] == 0
        if not evidence['uncommitted_invisible']:
            raise AssertionError('uncommitted row leaked to ordinary source transaction')
        with gate_connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', (lock_key,))
        evidence['timeline']['gate_released'] = now()

        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = sample(fixture, candidate, connector)
            if state['error']:
                raise AssertionError('candidate error ' + state['error'])
            if state['snapshot'].get('status') == 'COMPLETED':
                evidence['timeline']['snapshot_completed_observed'] = now()
                break
            time.sleep(0.5)
        else:
            raise AssertionError('trusted snapshot completion not observed')
        notifications = notification_history(candidate)
        evidence['notifications'] = notifications
        kinds = {item['type']: item for item in notifications}
        if (not all(kind in kinds for kind in ('STARTED', 'TABLE_SCAN_COMPLETED', 'COMPLETED'))
                or not kinds['TABLE_SCAN_COMPLETED'].get('empty')):
            raise AssertionError('exact candidate zero-row snapshot notifications missing')
        transaction.commit()
        evidence['timeline']['transaction_commit'] = now()
        transaction.close()
        transaction = None

        wait_candidate(fixture, candidate, database)
        evidence['timeline']['candidate_loader_exact'] = now()
        for label, topic, operation in (
                ('raw_insert', candidate.raw_topic, 'c'),
                ('normalized_insert', candidate.topic('normalized'), 'INSERT'),
                ('transformed_insert', candidate.topic('transformed'), 'INSERT')):
            result = row_event(candidate, topic)
            if result is None or result['operation'] != operation:
                raise AssertionError(label + ' not captured as streaming INSERT')
            evidence[label] = result
            evidence['timeline'][label + '_observed'] = now()
        wait_for('candidate capture readiness after WAL continuation',
                 lambda: sample(fixture, candidate, connector)['capture_ready'], seconds=120)
        proof = request_reconciliation(fixture, candidate)
        evidence['certificate'] = {'kind': proof['kind'], 'status': proof['status'],
                                   'source_lsn': proof['source_lsn'],
                                   'loader_applied_through_lsn': proof['loader_applied_through_lsn'],
                                   'source_row_count': proof['source_row_count'],
                                   'query_row_count': proof['query_row_count']}
        evidence['timeline']['certificate_issued'] = now()
        evidence['status'] = 'CERTIFIED_PENDING_CUTOVER'
        save(path, evidence)
        print(json.dumps({'stage': evidence['status'], 'evidence': str(path),
                          'certificate': evidence['certificate']}), flush=True)
    except Exception as exc:
        evidence['status'] = 'FAIL'
        evidence['failure'] = type(exc).__name__ + ': ' + str(exc)[:160]
        raise
    finally:
        if transaction is not None:
            transaction.rollback()
            transaction.close()
        if lock_key is not None:
            with gate_connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', (lock_key,))
        gate_connection.close()
        save(path, evidence)


def verify_cutover(fixture, path):
    path = Path(path)
    evidence = json.loads(path.read_text(encoding='utf-8'))
    candidate = Scope(**evidence['candidate'])
    expected = [[1, 'boundary-overlap', Decimal(2), 'new']]
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT cdc_generation FROM manager_databases WHERE id=%s',
                           (candidate.dataset_id,))
            query_generation = cursor.fetchone()[0]
            cursor.execute('SELECT number,state FROM integration_cdc_generations '
                           'WHERE pipeline_id=%s ORDER BY number', (candidate.pipeline_id,))
            lineage = cursor.fetchall()
    exact = fixture.rows_equal(candidate, expected)
    evidence['authorized_query'] = {'generation': query_generation,
                                    'lineage': lineage, 'exactly_one_row': exact}
    evidence['timeline']['authorized_query_verified'] = now()
    if evidence['status'] != 'CERTIFIED_PENDING_CUTOVER' or query_generation != 2 or not exact:
        evidence['status'] = 'FAIL'
        save(path, evidence)
        raise AssertionError('certified overlap did not cut over to one authorized row')
    evidence['status'] = 'PASS'
    save(path, evidence)
    print(json.dumps({'status': 'PASS', 'evidence': str(path),
                      'authorized_query': evidence['authorized_query']}), flush=True)


def refresh_certificate(fixture, path):
    path = Path(path)
    evidence = json.loads(path.read_text(encoding='utf-8'))
    if evidence.get('status') != 'CERTIFIED_PENDING_CUTOVER':
        raise AssertionError('only a fully proven overlap may refresh its certificate')
    candidate = Scope(**evidence['candidate'])
    prior = read_certificate(fixture, candidate).get('attempt_id')
    response = fixture.session.post(
        fixture.base + f'/database/sources/{candidate.source_id}/cdc/reconcile/',
        json={'pipeline_id': candidate.pipeline_id},
        headers={'Authorization': 'Bearer ' + fixture.token(candidate.workspace_id)},
        timeout=20)
    if response.status_code != 202:
        raise AssertionError(f'fresh reconcile HTTP {response.status_code}')
    def fresh():
        proof = read_certificate(fixture, candidate)
        return proof if (proof.get('kind') == 'watermark_reconciliation.v1'
                         and proof.get('attempt_id') != prior) else None
    proof = wait_for('fresh overlap certificate', fresh, seconds=180)
    if proof['status'] != 'MATCH':
        raise AssertionError('fresh overlap certificate is not MATCH')
    evidence['certificate'] = {'kind': proof['kind'], 'status': proof['status'],
                               'attempt_id': proof['attempt_id'],
                               'source_lsn': proof['source_lsn'],
                               'loader_applied_through_lsn': proof['loader_applied_through_lsn'],
                               'source_row_count': proof['source_row_count'],
                               'query_row_count': proof['query_row_count']}
    evidence['timeline']['certificate_refreshed'] = now()
    save(path, evidence)
    print(json.dumps({'status': 'FRESH_MATCH', 'pipeline_id': candidate.pipeline_id,
                      'evidence': str(path)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--create-old', action='store_true')
    parser.add_argument('--run-overlap')
    parser.add_argument('--verify-cutover')
    parser.add_argument('--refresh-certificate')
    args = parser.parse_args()
    fixture = Fixture(args.env_file)
    if args.create_old:
        create_old(fixture)
    elif args.run_overlap:
        run_overlap(fixture, args.run_overlap)
    elif args.verify_cutover:
        verify_cutover(fixture, args.verify_cutover)
    elif args.refresh_certificate:
        refresh_certificate(fixture, args.refresh_certificate)
    else:
        parser.error('choose one operation')
