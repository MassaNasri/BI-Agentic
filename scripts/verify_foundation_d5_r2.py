"""Isolated D5-R2 watermark certificate acceptance. Retains all evidence."""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import uuid

from verify_foundation_d_cdc import Fixture, wait_for
from bi_platform_shared.cdc_contract import Scope
from verify_foundation_d5_r1 import (control_row, django_action, engine,
                                      exact_rows, query_exact, reseed, wait_candidate)


def certificate(fixture, scope):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT validation_certificate FROM integration_cdc_generations '
                           'WHERE pipeline_id=%s AND number=%s',
                           (scope.pipeline_id, scope.generation))
            return cursor.fetchone()[0]


def request_reconciliation(fixture, scope, expected='MATCH'):
    response = fixture.session.post(
        fixture.base + f'/database/sources/{scope.source_id}/cdc/reconcile/',
        json={'pipeline_id': scope.pipeline_id},
        headers={'Authorization': 'Bearer ' + fixture.token(scope.workspace_id)},
        timeout=20)
    if response.status_code != 202:
        raise AssertionError(f'reconcile HTTP {response.status_code}')
    wait_for('watermark reconciliation certificate',
             lambda: certificate(fixture, scope).get('kind') == 'watermark_reconciliation.v1',
             seconds=180)
    result = certificate(fixture, scope)
    if result['status'] != expected:
        raise AssertionError(f'reconciliation status {result["status"]}')
    return result


def legacy(fixture):
    fixture.compose('stop', 'controller')
    try:
        old, database = fixture.d2_source(row_count=3)
        fixture.ch.command(
            f'CREATE TABLE etl.cdc_{old.token}_versions ('
            'id Int32, customer String, amount Decimal(20,4), status String, '
            '_cdc_version UInt128, _cdc_deleted UInt8, _cdc_event_id FixedString(64)) '
            'ENGINE=ReplacingMergeTree(_cdc_version) ORDER BY id')
    finally:
        fixture.compose('start', 'controller')
    wait_for('legacy storage RESEED_REQUIRED',
             lambda: control_row(fixture, old)[1:3] ==
             ('RESEED_REQUIRED', 'CDC_STORAGE_INCOMPATIBLE'), seconds=180)
    candidate = reseed(fixture, old, 'legacy_storage')
    wait_candidate(fixture, candidate, database)
    proof = request_reconciliation(fixture, candidate)
    django_action(fixture, candidate.pipeline_id, 'cutover_candidate')
    expected = exact_rows(fixture, candidate, database)[1]
    wait_for('authorized Query after watermark cutover',
             lambda: query_exact(fixture, candidate, expected), seconds=60)
    assert control_row(fixture, candidate)[6] == 'ACTIVE'
    assert engine(fixture, old) == 'ReplacingMergeTree'
    return {'source_database': database, 'old_generation': 1,
            'candidate_generation': 2, 'source_lsn': proof['source_lsn'],
            'capture_lsn': proof['capture_observed_lsn'],
            'loader_lsn': proof['loader_applied_through_lsn'],
            'source_count': proof['source_row_count'],
            'query_count': proof['query_row_count'],
            'chunk_count': proof['chunk_count'],
            'duration_ms': proof['duration_ms'],
            'query_duration_ms': proof['query_duration_ms'],
            'certificate': proof['kind'], 'query_exact': True}


def empty(fixture):
    old, database = fixture.d2_source(row_count=0)
    wait_for('old empty snapshot',
             lambda: control_row(fixture, old)[4].get('completed') is True,
             seconds=180)
    candidate = reseed(fixture, old, 'operator_reseed')
    wait_candidate(fixture, candidate, database, empty=True)
    proof = request_reconciliation(fixture, candidate)
    django_action(fixture, candidate.pipeline_id, 'cutover_candidate')
    assert fixture.rows_equal(candidate, [])
    return {'source_database': database, 'source_lsn': proof['source_lsn'],
            'source_count': proof['source_row_count'],
            'query_count': proof['query_row_count'],
            'certificate': proof['kind'], 'query_zero_rows': True}


def empty_insert(fixture):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT p.workspace_id,p.source_id,p.id,p.dataset_id,p.table_schema,'
                           'p.table_name,p.generation,'
                           "s.connection_metadata->>'database' "
                           'FROM integration_cdc_pipelines p JOIN integration_data_sources s '
                           'ON s.id=p.source_id ORDER BY p.created_at DESC LIMIT 1')
            row = cursor.fetchone()
    scope = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], row[6])
    assert certificate(fixture, scope).get('status') == 'MATCH'
    assert fixture.rows_equal(scope, [])
    with fixture.pg(row[7]) as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO public.orders VALUES (1,'after-candidate',1,'new')")
    wait_for('generation-2 post-empty INSERT through Query',
             lambda: fixture.rows_equal(scope,
                                        [[1, 'after-candidate', Decimal(1), 'new']]),
             seconds=180)
    return {'source_database': row[7], 'generation': scope.generation,
            'post_empty_insert_query_exact': True}


def boundary_overlap(fixture):
    old, database = fixture.d2_source(row_count=0)
    wait_for('old empty Query binding', lambda: fixture.rows_equal(old, []), seconds=180)
    candidate = reseed(fixture, old, 'operator_reseed')
    source_connection = fixture.pg(database)
    try:
        with source_connection.cursor() as cursor:
            cursor.execute("INSERT INTO public.orders VALUES (1,'boundary-overlap',2,'new')")
        wait_for('candidate snapshot started with source INSERT uncommitted',
                 lambda: control_row(fixture, candidate)[4].get('status') == 'STARTED',
                 seconds=120)
        source_connection.commit()
    finally:
        source_connection.close()
    wait_candidate(fixture, candidate, database)
    proof = request_reconciliation(fixture, candidate)
    django_action(fixture, candidate.pipeline_id, 'cutover_candidate')
    wait_for('overlap INSERT exactly once through authorized Query',
             lambda: fixture.rows_equal(candidate,
                                        [[1, 'boundary-overlap', Decimal(2), 'new']]),
             seconds=180)
    return {'source_database': database, 'generation': candidate.generation,
            'snapshot_started_before_commit': True,
            'source_lsn': proof['source_lsn'],
            'capture_lsn': proof['capture_observed_lsn'],
            'query_exactly_once': True}


def mismatch(fixture):
    old, database = fixture.d2_source(row_count=2)
    wait_for('old authoritative Query before mismatch',
             lambda: fixture.rows_equal(old,
                                        [[1, 'd2', Decimal(1), 'initial'],
                                         [2, 'd2', Decimal(2), 'initial']]),
             seconds=180)
    candidate = reseed(fixture, old, 'operator_reseed')
    wait_candidate(fixture, candidate, database)
    fixture.ch.command(
        f'INSERT INTO etl.cdc_{candidate.token}_versions '
        f'SELECT id, customer, amount, status, '
        f"toUInt128('340282366920938463463374607431768211455'), "
        f'toUInt8(1), toFixedString(repeat(\'0\', 64), 64) '
        f'FROM etl.cdc_{candidate.token}_current WHERE id=1')
    wait_for('candidate controlled delete corruption',
             lambda: len(fixture.ch.query(
                 f'SELECT id FROM etl.cdc_{candidate.token}_current').result_rows) == 1,
             seconds=30)
    proof = request_reconciliation(fixture, candidate, expected='MISMATCH')
    django_action(fixture, candidate.pipeline_id, 'cutover_candidate', success=False)
    assert control_row(fixture, candidate)[6] == 'CANDIDATE'
    assert fixture.rows_equal(old, [[1, 'd2', Decimal(1), 'initial'],
                                     [2, 'd2', Decimal(2), 'initial']])
    return {'source_database': database, 'status': proof['status'],
            'mismatch_chunks': proof['mismatch_chunks'],
            'old_query_retained': True, 'candidate_not_authoritative': True}


def revoke_latest(fixture):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT p.workspace_id,p.source_id,p.id,p.dataset_id,p.table_schema,'
                           'p.table_name,p.generation,'
                           "s.connection_metadata->>'database' "
                           'FROM integration_cdc_pipelines p JOIN integration_data_sources s '
                           'ON s.id=p.source_id ORDER BY p.created_at DESC LIMIT 1')
            row = cursor.fetchone()
    candidate = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], row[6])
    old = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], 1)
    assert control_row(fixture, candidate)[6] == 'CANDIDATE'
    fixture.api(candidate.workspace_id, 'POST',
                f'/database/sources/{candidate.source_id}/credential/revoke/', {},
                expected=200)
    wait_for('candidate capture stops after credential revoke',
             lambda: control_row(fixture, candidate)[1] in {'STOPPING', 'STOPPED'},
             seconds=120)
    response = fixture.session.post(fixture.base + '/internal/v1/cdc/',
        json={'pipeline_id': candidate.pipeline_id, 'scope': candidate.__dict__,
              'checkpoint': {'partition': 0, 'offset': 99, 'lsn': 999}},
        headers={'X-Cdc-Stage': 'load', 'X-Cdc-Key': fixture.env['CDC_LOAD_KEY']},
        timeout=20)
    assert response.status_code == 409
    django_action(fixture, candidate.pipeline_id, 'cutover_candidate', success=False)
    assert fixture.rows_equal(old, [[1, 'd2', Decimal(1), 'initial'],
                                     [2, 'd2', Decimal(2), 'initial']])
    return {'source_database': row[7], 'generation': candidate.generation,
            'stale_callback_http': response.status_code,
            'candidate_cutover_blocked': True, 'old_query_retained': True}


def retire_candidate(fixture):
    old, database = fixture.d2_source(row_count=0)
    wait_for('old zero-row Query before retirement',
             lambda: fixture.rows_equal(old, []), seconds=180)
    candidate = reseed(fixture, old, 'operator_reseed')
    wait_candidate(fixture, candidate, database, empty=True)
    fixture.api(candidate.workspace_id, 'DELETE',
                f'/database/sources/{candidate.source_id}/', expected=200)
    wait_for('retired candidate capture stopped',
             lambda: control_row(fixture, candidate)[1] == 'STOPPED', seconds=180)
    django_action(fixture, candidate.pipeline_id, 'cutover_candidate', success=False)
    assert fixture.rows_equal(old, [])
    return {'source_database': database, 'candidate_generation': candidate.generation,
            'candidate_cutover_blocked': True, 'historical_query_retained': True}


def retry_latest(fixture):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT p.workspace_id,p.source_id,p.id,p.dataset_id,p.table_schema,'
                           'p.table_name,p.generation,p.desired_state,'
                           "s.connection_metadata->>'database' "
                           'FROM integration_cdc_pipelines p JOIN integration_data_sources s '
                           'ON s.id=p.source_id ORDER BY p.created_at DESC LIMIT 1')
            row = cursor.fetchone()
    scope = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], row[6])
    if row[7] == 'PAUSED':
        fixture.api(scope.workspace_id, 'POST',
                    f'/database/sources/{scope.source_id}/cdc/resume/',
                    {'pipeline_id': scope.pipeline_id}, expected=202)
    wait_candidate(fixture, scope, row[8])
    proof = request_reconciliation(fixture, scope)
    django_action(fixture, scope.pipeline_id, 'cutover_candidate')
    expected = exact_rows(fixture, scope, row[8])[1]
    wait_for('authorized Query after watermark cutover',
             lambda: query_exact(fixture, scope, expected), seconds=60)
    return {'source_database': row[8], 'source_lsn': proof['source_lsn'],
            'capture_lsn': proof['capture_observed_lsn'],
            'source_count': proof['source_row_count'],
            'query_count': proof['query_row_count'],
            'certificate': proof['kind'], 'query_exact': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--case', choices=['legacy', 'empty', 'retry', 'empty_insert',
                                            'boundary_overlap', 'mismatch',
                                            'revoke_latest', 'retire_candidate'], required=True)
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--pipeline-id')
    parser.add_argument('--probe-marker', action='store_true')
    args = parser.parse_args()
    fixture = Fixture(args.env_file)
    if args.diagnose:
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT p.id,p.generation,p.desired_state,p.observed_state,p.error_code,'
                               'p.reconcile_requested,p.checkpoints,g.validation_certificate,p.snapshot_signal '
                               ',p.workspace_id,p.source_id,p.dataset_id,p.table_schema,p.table_name,'
                               "s.connection_metadata->>'database',s.connection_metadata->>'username' "
                               'FROM integration_cdc_pipelines p JOIN integration_cdc_generations g '
                               'ON g.pipeline_id=p.id AND g.number=p.generation '
                               'JOIN integration_data_sources s ON s.id=p.source_id '
                               'WHERE (%s::uuid IS NULL OR p.id=%s::uuid) '
                               'ORDER BY p.created_at DESC LIMIT 1',
                               (args.pipeline_id, args.pipeline_id))
                row = cursor.fetchone()
                cursor.execute('SELECT number,state FROM integration_cdc_generations '
                               'WHERE pipeline_id=%s ORDER BY number', (row[0],))
                lineage = cursor.fetchall()
                cursor.execute('SELECT cdc_generation FROM manager_databases WHERE id=%s', (row[11],))
                query_generation = cursor.fetchone()[0]
        scope = Scope(row[9], str(row[10]), str(row[0]), row[11], row[12], row[13], row[1])
        with fixture.pg(row[14]) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_current_wal_lsn()::text, confirmed_flush_lsn::text, '
                               'wal_status,active,restart_lsn::text,slot_type,plugin,database,temporary '
                               'FROM pg_replication_slots WHERE slot_name=%s', ('b_' + scope.token,))
                slot = cursor.fetchone()
        marker = None
        if args.probe_marker:
            try:
                with fixture.pg(row[14], user=row[15],
                                password=fixture.env['CDC_SOURCE_PASSWORD']) as source_connection:
                    with source_connection.cursor() as cursor:
                        cursor.execute("SELECT pg_logical_emit_message(false, 'biavora_reconcile', 'probe')::text")
                        marker = cursor.fetchone()[0]
            except Exception as exc:
                marker = type(exc).__name__
        print(json.dumps({'pipeline_id': str(row[0]), 'token': scope.token, 'generation': row[1],
                          'desired': row[2], 'observed': row[3], 'error': row[4],
                          'requested': row[5], 'checkpoints': row[6],
                          'certificate_status': row[7].get('status'),
                          'certificate_duration_ms': row[7].get('duration_ms'),
                          'query_duration_ms': row[7].get('query_duration_ms'),
                          'chunk_count': row[7].get('chunk_count'),
                          'source_row_count': row[7].get('source_row_count'),
                          'query_row_count': row[7].get('query_row_count'),
                          'snapshot_status': row[8].get('status'),
                          'snapshot_complete': row[8].get('completed'),
                          'lineage': lineage, 'query_generation': query_generation,
                          'source_wal_and_flush': slot, 'marker': marker}, default=str))
        return
    result = {'case': args.case,
              'result': {'legacy': legacy, 'empty': empty,
                         'retry': retry_latest,
                         'empty_insert': empty_insert,
                         'boundary_overlap': boundary_overlap,
                         'mismatch': mismatch,
                         'revoke_latest': revoke_latest,
                         'retire_candidate': retire_candidate}[args.case](fixture)}
    path = Path(args.env_file).resolve().parent / f'd5-r2-{args.case}-{uuid.uuid4().hex[:8]}.json'
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'evidence': str(path), **result}))


if __name__ == '__main__':
    main()
