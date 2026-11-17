"""Live R4B stale-certificate fault phases in disposable retained scopes."""

import argparse
from decimal import Decimal
import json
import time

from bi_platform_shared.cdc_contract import Scope
from verify_foundation_d_cdc import Fixture, wait_for
from verify_foundation_d5_r1 import control_row, exact_rows, reseed, wait_candidate
from verify_foundation_d5_r2 import request_reconciliation


def save(path, state):
    path.write_text(json.dumps(state, indent=2, default=str), encoding='utf-8')


def expected(case, state):
    # Reseed pauses the old capture. The historical Query binding remains
    # deterministic until an authorized candidate cutover.
    return [[1, 'd2', Decimal(1), 'initial']]


def capture_ready(fixture, candidate):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT capture_ready FROM integration_cdc_pipelines '
                           'WHERE id=%s', (candidate.pipeline_id,))
            return cursor.fetchone()[0]


def setup(fixture, case, path, pipeline_id=None):
    if pipeline_id:
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute('''SELECT p.workspace_id,p.source_id,p.id,p.dataset_id,
                    p.table_schema,p.table_name,p.generation,
                    s.connection_metadata->>'database'
                    FROM integration_cdc_pipelines p JOIN integration_data_sources s
                    ON s.id=p.source_id WHERE p.id=%s''', (pipeline_id,))
                row = cursor.fetchone()
        assert row and row[6] == 2
        old = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], 1)
        candidate = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], 2)
        database = row[7]
    else:
        old, database = fixture.d2_source(row_count=1)
    wait_for('old Query before certificate',
             lambda: fixture.rows_equal(old, [[1, 'd2', Decimal(1), 'initial']]),
             seconds=240)
    if not pipeline_id:
        candidate = reseed(fixture, old, 'operator_reseed')
    wait_candidate(fixture, candidate, database)
    wait_for('candidate capture_ready before reconcile',
             lambda: capture_ready(fixture, candidate), seconds=90)
    proof = request_reconciliation(fixture, candidate)
    state = {'case': case, 'status': 'CERTIFIED', 'old': old.__dict__,
             'candidate': candidate.__dict__, 'source_database': database,
             'certificate': {'kind': proof['kind'], 'status': proof['status'],
                             'issued_at': proof['issued_at'],
                             'schema_version': proof['schema_version'],
                             'loader_checkpoint': proof['loader_checkpoint']},
             'old_query_exact': True}
    save(path, state)
    print(json.dumps({'path': str(path), 'phase': 'setup',
                      'case': case, 'status': 'CERTIFIED'}), flush=True)


def run(fixture, case, phase, run_id, pipeline_id=None):
    path = fixture.env_file.parent / f'd5-r4b-certificate-{case}-{run_id}.json'
    if phase == 'setup':
        setup(fixture, case, path, pipeline_id)
        return
    state = json.loads(path.read_text(encoding='utf-8'))
    old = Scope(**state['old'])
    candidate = Scope(**state['candidate'])
    database = state['source_database']
    if phase == 'expire':
        issued = __import__('datetime').datetime.fromisoformat(
            state['certificate']['issued_at'])
        remaining = 61 - (time.time() - issued.timestamp())
        if remaining > 0:
            time.sleep(remaining)
        state['expiry_elapsed_seconds'] = time.time() - issued.timestamp()
        assert state['expiry_elapsed_seconds'] > 60
    elif phase == 'checkpoint':
        proof = request_reconciliation(fixture, candidate)
        prior = proof['loader_checkpoint'].get('load:0', {}).get('offset', -1)
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                cursor.execute('''INSERT INTO public.orders
                    (id,customer,amount,status) VALUES (2,'r4b',2,'new')''')
        wait_for('Loader checkpoint after fresh MATCH',
                 lambda: control_row(fixture, candidate)[3].get(
                     'load:0', {}).get('offset', -1) > prior
                 and exact_rows(fixture, candidate, database)[0], seconds=180)
        state['inserted'] = True
        state['checkpoint_moved'] = True
        state['certificate'] = {'kind': proof['kind'], 'status': proof['status'],
                                'issued_at': proof['issued_at'],
                                'schema_version': proof['schema_version'],
                                'loader_checkpoint': proof['loader_checkpoint']}
        state['new_loader_checkpoint'] = control_row(fixture, candidate)[3]
    elif phase == 'schema':
        proof = request_reconciliation(fixture, candidate)
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE public.orders ADD COLUMN r4b_note text')
        def moved():
            with fixture.pg('biavora') as connection:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT schema_version FROM integration_cdc_pipelines '
                                   'WHERE id=%s', (candidate.pipeline_id,))
                    return cursor.fetchone()[0] > proof['schema_version']
        wait_for('compatible ADD advances candidate schema version', moved, seconds=180)
        state['schema_moved'] = True
        state['certificate'] = {'kind': proof['kind'], 'status': proof['status'],
                                'issued_at': proof['issued_at'],
                                'schema_version': proof['schema_version'],
                                'loader_checkpoint': proof['loader_checkpoint']}
    elif phase == 'generation':
        proof = request_reconciliation(fixture, candidate)
        headers = {'Authorization': 'Bearer ' + fixture.token(old.workspace_id),
                   'X-Cdc-Operator-Key': 'd5-r1-isolated-fixture-only'}
        response = fixture.session.post(fixture.base +
            f'/database/sources/{old.source_id}/cdc/abort/',
            json={'pipeline_id': old.pipeline_id, 'intent': 'abort_candidate'},
            headers=headers, timeout=20)
        assert response.status_code == 202, response.status_code
        response = fixture.session.post(fixture.base +
            f'/database/sources/{old.source_id}/cdc/reseed/',
            json={'pipeline_id': old.pipeline_id, 'intent': 'reseed',
                  'reason': 'operator_reseed'}, headers=headers, timeout=20)
        assert response.status_code == 202, response.status_code
        assert response.json()['data']['generation'] == 3
        state['generation_moved_to'] = 3
        state['prior_certificate_generation'] = proof['generation']
    elif phase == 'revoke':
        assert fixture.api(old.workspace_id, 'POST',
            f'/database/sources/{old.source_id}/credential/revoke/', {},
            expected=200)
        state['credential_revoked'] = True
    elif phase == 'retire':
        assert fixture.api(old.workspace_id, 'DELETE',
            f'/database/sources/{old.source_id}/', expected=200)
        state['source_retired'] = True
    elif phase == 'verify':
        wait_for('old Query exact after certificate denial',
                 lambda: fixture.rows_equal(old, expected(case, state)),
                 seconds=180)
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT cdc_generation FROM manager_databases '
                               'WHERE id=%s', (old.dataset_id,))
                query_generation = cursor.fetchone()[0]
        assert query_generation == 1
        state.update(status='PASS', cutover_denied=True,
                     query_generation=query_generation, old_query_exact=True)
    else:
        raise AssertionError('unknown phase')
    save(path, state)
    print(json.dumps({'path': str(path), 'phase': phase,
                      'case': case, 'status': state['status']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--case', choices=['primary', 'revoke', 'retire'], required=True)
    parser.add_argument('--phase', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--pipeline-id')
    args = parser.parse_args()
    run(Fixture(args.env_file), args.case, args.phase, args.run_id,
        args.pipeline_id)
