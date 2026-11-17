"""Controlled R4B orphan states in fresh, retained local fixture scopes."""

import argparse
from decimal import Decimal
import json
from pathlib import Path

from bi_platform_shared.cdc_contract import Scope
from shared.cdc.connect import ConnectClient
from verify_foundation_d_cdc import Fixture, wait_for
from verify_foundation_d5_r1 import control_row, engine, reseed, wait_candidate
from verify_foundation_d5_r2 import request_reconciliation
from verify_foundation_d5_r3 import sample


def save(path, value):
    path.write_text(json.dumps(value, indent=2, default=str), encoding='utf-8')


def status(fixture, scope):
    return fixture.api(scope.workspace_id, 'GET',
                       f'/database/sources/{scope.source_id}/cdc/status/')['data'][0]


def finding(value, code):
    return next((item for item in value['repair'] if item['code'] == code), None)


def physical_sample(fixture, scope, connector):
    result = sample(fixture, scope, connector)
    # The older sampler groups status, offsets, and config under one broad
    # exception handler. A failed connector can reject offsets while still
    # returning an authoritative FAILED status.
    status_value = connector.request(scope, '/status') or {}
    result['connect_state'] = status_value.get('connector', {}).get('state')
    result['task_states'] = [task.get('state') for task in
                             status_value.get('tasks', [])]
    return result


def setup(fixture, path, case):
    old, database = fixture.d2_source(row_count=1)
    wait_for(f'{case} old Query authority', lambda: fixture.rows_equal(old,
             [[1, 'd2', Decimal(1), 'initial']]), seconds=240)
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT columns,primary_key FROM integration_cdc_pipelines '
                           'WHERE id=%s', (old.pipeline_id,))
            columns, primary_key = cursor.fetchone()
    state = {'case': case, 'status': 'PREPARING', 'old': old.__dict__,
             'source_database': database, 'old_columns': columns,
             'old_primary_key': primary_key, 'old_query_exact': True}
    save(path, state)
    print(json.dumps({'path': str(path), 'phase': 'setup',
                      'old': old.__dict__}), flush=True)


def run(fixture, case, phase, run_id):
    path = fixture.env_file.parent / f'd5-r4b-orphan-{case}-{run_id}.json'
    if phase == 'setup':
        setup(fixture, path, case)
        return
    state = json.loads(path.read_text(encoding='utf-8'))
    old = Scope(**state['old'])
    database = state['source_database']
    expected_old = [[1, 'd2', Decimal(1), 'initial']]
    connector = ConnectClient()
    if case == 'missing':
        if phase == 'boundary':
            # Caller stopped Controller. Materialized metadata exists but the
            # generation-specific candidate storage does not yet exist.
            candidate = reseed(fixture, old, 'operator_reseed')
            assert engine(fixture, candidate) is None
            with fixture.pg('biavora') as connection:
                with connection.cursor() as cursor:
                    cursor.execute('''UPDATE integration_cdc_pipelines
                        SET columns=%s::jsonb,primary_key=%s::jsonb WHERE id=%s''',
                        (json.dumps(state['old_columns']),
                         json.dumps(state['old_primary_key']), old.pipeline_id))
            public = status(fixture, candidate)
            advice = finding(public, 'CDC_CANDIDATE_STORAGE_MISSING')
            assert advice and advice['repair'] == 'recoverable_retry'
            assert fixture.rows_equal(old, expected_old)
            state.update(candidate=candidate.__dict__, boundary=sample(
                fixture, candidate, connector), classification=advice,
                status='RECOVERABLE_RETRY')
            save(path, state)
            print(json.dumps({'path': str(path), 'phase': phase,
                              'classification': advice}), flush=True)
            return
        candidate = Scope(**state['candidate'])
        wait_candidate(fixture, candidate, database)
        after = sample(fixture, candidate, connector)
        assert engine(fixture, candidate) == 'MergeTree'
        assert control_row(fixture, candidate)[0] == 2
        assert fixture.rows_equal(old, expected_old)
        state.update(status='PASS', repaired=after,
                     same_generation=True, old_query_exact=True)
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'result': 'PASS'}), flush=True)
        return

    if case == 'failed':
        if phase == 'candidate':
            candidate = reseed(fixture, old, 'operator_reseed')
            wait_candidate(fixture, candidate, database)
            state.update(candidate=candidate.__dict__, ready=sample(
                fixture, candidate, connector))
            save(path, state)
            print(json.dumps({'path': str(path), 'phase': phase,
                              'candidate': candidate.__dict__}), flush=True)
            return
        candidate = Scope(**state['candidate'])
        if phase == 'abort':
            response = fixture.session.post(fixture.base +
                f'/database/sources/{old.source_id}/cdc/abort/',
                json={'pipeline_id': old.pipeline_id, 'intent': 'abort_candidate'},
                headers={'Authorization': 'Bearer ' + fixture.token(old.workspace_id),
                         'X-Cdc-Operator-Key': 'd5-r1-isolated-fixture-only'},
                timeout=20)
            assert response.status_code == 202
            state['aborted'] = sample(fixture, candidate, connector)
            save(path, state)
            print(json.dumps({'path': str(path), 'phase': phase}), flush=True)
            return
        wait_for('failed candidate physical capture non-running',
            lambda: (observation if observation['connect_state'] in {'STOPPED', 'FAILED'}
                    and observation['task_states'] == [] else None)
            if (observation := physical_sample(fixture, candidate, connector)) else None,
            seconds=180)
        observation = physical_sample(fixture, candidate, connector)
        public = status(fixture, candidate)
        advice = finding(public, 'CDC_FAILED_GENERATION_RETAINED')
        assert advice and advice['repair'] == 'manual_operator_review'
        assert observation['generation_state'] == 'FAILED'
        assert observation['connect_state'] in {'STOPPED', 'FAILED'}
        assert engine(fixture, candidate) == 'MergeTree'
        assert observation['slot'] is not None
        assert fixture.rows_equal(old, expected_old)
        state.update(status='PASS', failed=observation, classification=advice,
                     retained_storage=True, retained_slot=True,
                     old_query_exact=True)
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'result': 'PASS', 'classification': advice}), flush=True)
        return

    if case == 'binding':
        if phase == 'corrupt':
            candidate = reseed(fixture, old, 'operator_reseed')
            with fixture.pg('biavora') as connection:
                with connection.cursor() as cursor:
                    cursor.execute('UPDATE integration_cdc_pipelines SET dataset_id=%s '
                                   'WHERE id=%s', (99999999, old.pipeline_id))
            state['candidate'] = candidate.__dict__
            state['original_dataset_id'] = old.dataset_id
            save(path, state)
            print(json.dumps({'path': str(path), 'phase': phase}), flush=True)
            return
        public = status(fixture, old)
        advice = finding(public, 'CDC_DATASET_MISSING')
        assert advice and advice['repair'] == 'manual_operator_review'
        assert fixture.rows_equal(old, expected_old)
        state.update(status='PASS', classification=advice,
                     old_query_exact=True, manual_review_retained=True)
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'result': 'PASS', 'classification': advice}), flush=True)
        return

    if case == 'pending':
        if phase == 'candidate':
            candidate = reseed(fixture, old, 'operator_reseed')
            wait_candidate(fixture, candidate, database)
            proof = request_reconciliation(fixture, candidate)
            state.update(candidate=candidate.__dict__, certificate=proof,
                         status='CERTIFIED')
            save(path, state)
            print(json.dumps({'path': str(path), 'phase': phase,
                              'attempt_id': proof['attempt_id']}), flush=True)
            return
        candidate = Scope(**state['candidate'])
        public = status(fixture, candidate)
        if phase == 'bound':
            advice = finding(public, 'CDC_QUERY_BOUND_PENDING')
            assert advice and advice['repair'] == 'recoverable_retry'
            assert public['query_generation'] == 2
            assert fixture.rows_equal(candidate, expected_old)
            state.update(bound=sample(fixture, candidate, connector),
                         classification=advice, status='RECOVERABLE_RETRY')
            save(path, state)
            print(json.dumps({'path': str(path), 'phase': phase,
                              'classification': advice}), flush=True)
            return
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT number,state,cutover_phase FROM '
                    'integration_cdc_generations WHERE pipeline_id=%s ORDER BY number',
                    (candidate.pipeline_id,))
                lineage = cursor.fetchall()
        assert lineage == [(1, 'SUPERSEDED', 'NONE'), (2, 'ACTIVE', 'COMPLETE')]
        assert public['query_generation'] == 2
        assert fixture.rows_equal(candidate, expected_old)
        state.update(status='PASS', recovered=sample(fixture, candidate, connector),
                     lineage=lineage, query_exact=True)
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'result': 'PASS'}), flush=True)
        return
    raise AssertionError('unknown case')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--case', choices=['missing', 'failed', 'binding', 'pending'], required=True)
    parser.add_argument('--phase', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    run(Fixture(args.env_file), args.case, args.phase, args.run_id)
