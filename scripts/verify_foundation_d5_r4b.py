"""R4B disposable live lifecycle probes. Run phases with the fixture controller stopped.

The caller controls Compose restarts. This script persists only safe identifiers and
observations in the sibling validation directory, never source credentials.
"""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import time
import uuid
from kafka import KafkaConsumer, TopicPartition

from bi_platform_shared.cdc_contract import Scope
from shared.cdc.connect import ConnectClient
from verify_foundation_d_cdc import Fixture, wait_for
from verify_foundation_d5_r1 import control_row, reseed, wait_candidate
from verify_foundation_d5_r2 import certificate, request_reconciliation
from verify_foundation_d5_r3 import sample


def path_for(fixture, case, run_id):
    return fixture.env_file.parent / f'd5-r4b-{case}-{run_id}.json'


def save(path, state):
    path.write_text(json.dumps(state, indent=2, default=str), encoding='utf-8')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def public_status(fixture, scope):
    return fixture.api(scope.workspace_id, 'GET',
                       f'/database/sources/{scope.source_id}/cdc/')['data'][0]


def internal_item(fixture, scope):
    page = 0
    while page is not None:
        response = fixture.session.get(fixture.base + '/internal/v1/cdc/',
            params={'page': page},
            headers={'X-Cdc-Stage': 'controller',
                     'X-Cdc-Key': fixture.env['CDC_CONTROLLER_KEY']}, timeout=20)
        response.raise_for_status()
        data = response.json()
        for item in data['pipelines']:
            if item['scope']['pipeline_id'] == scope.pipeline_id:
                return item
        page = data.get('next_page')
    raise AssertionError('candidate absent from internal enumeration')


def lifecycle(fixture, case, phase, run_id):
    path = path_for(fixture, case, run_id)
    if phase == 'setup':
        old, database = fixture.d2_source(row_count=1)
        expected = [[1, 'd2', Decimal(1), 'initial']]
        wait_for('old generation authoritative before provisioning race',
                 lambda: fixture.rows_equal(old, expected), seconds=240)
        state = {'case': case, 'result': 'PREPARING', 'old': old.__dict__,
                 'source_database': database,
                 'old_control': control_row(fixture, old),
                 'old_query_exact_before': True}
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase, 'old': old.__dict__}), flush=True)
        return
    state = load(path)
    old = Scope(**state['old'])
    expected = [[1, 'd2', Decimal(1), 'initial']]
    if phase == 'candidate':
        # The external caller has stopped the controller before this phase.
        candidate = reseed(fixture, old, 'operator_reseed')
        before = control_row(fixture, candidate)
        assert before[6] == 'CANDIDATE' and before[1] == 'PROVISIONING'
        assert not before[4].get('completed')
        if case == 'revoke':
            fixture.api(old.workspace_id, 'POST',
                        f'/database/sources/{old.source_id}/credential/revoke/', {}, expected=200)
        else:
            fixture.api(old.workspace_id, 'DELETE',
                        f'/database/sources/{old.source_id}/', expected=200)
        state['candidate'] = candidate.__dict__
        state['candidate_before_lifecycle'] = before
        state['candidate_after_lifecycle'] = control_row(fixture, candidate)
        state['old_query_exact_after_lifecycle'] = fixture.rows_equal(old, expected)
        state['result'] = 'AWAITING_CONTROLLER_RECOVERY'
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'candidate': candidate.__dict__}), flush=True)
        return
    candidate = Scope(**state['candidate'])
    connector = ConnectClient()
    def converged():
        observation = sample(fixture, candidate, connector)
        return observation if (observation['observed'] == 'STOPPED'
                               and observation['connect_state'] in (None, 'STOPPED')
                               and observation['task_states'] == []) else None
    observation = wait_for('candidate capture stopped after lifecycle race',
                           converged, seconds=180)
    item = internal_item(fixture, candidate)
    response = fixture.session.post(fixture.base + '/internal/v1/cdc/',
        json={'pipeline_id': candidate.pipeline_id, 'scope': candidate.__dict__,
              'checkpoint': {'partition': 0, 'offset': 99, 'lsn': 999}},
        headers={'X-Cdc-Stage': 'load', 'X-Cdc-Key': fixture.env['CDC_LOAD_KEY']},
        timeout=20)
    state['after_controller'] = observation
    state['internal_credential_absent'] = not item.get('credential')
    state['internal_desired'] = item['desired_state']
    state['stale_loader_callback_http'] = response.status_code
    state['old_query_exact_after_recovery'] = fixture.rows_equal(old, expected)
    state['candidate_certificate_absent'] = not observation['certificate'].get('kind')
    state['result'] = ('PASS' if state['internal_credential_absent']
                       and state['internal_desired'] == 'STOPPED'
                       and response.status_code == 409
                       and state['old_query_exact_after_recovery']
                       and state['candidate_certificate_absent']
                       and observation['observed'] == 'STOPPED'
                       and observation['connect_state'] in (None, 'STOPPED')
                       else 'FAIL')
    save(path, state)
    print(json.dumps({'path': str(path), 'phase': phase, 'result': state['result'],
                      'candidate_connect': observation['connect_state'],
                      'stale_callback_http': response.status_code}), flush=True)
    if state['result'] != 'PASS':
        raise AssertionError('lifecycle race failed closed invariants')


RESTART_COMPONENTS = ('normalizer', 'transformer', 'loader', 'query', 'connect', 'controller')


def topic_end(topic):
    consumer = KafkaConsumer(bootstrap_servers='kafka:9092', group_id=None,
                             enable_auto_commit=False, consumer_timeout_ms=1000)
    try:
        partition = TopicPartition(topic, 0)
        return consumer.end_offsets([partition])[partition]
    finally:
        consumer.close()


def expected_rows(state):
    return [[i, 'd2' if i == 1 else 'r4b', Decimal(i),
             'initial' if i == 1 else 'stream'] for i in state['ids']]


def restart_matrix(fixture, phase, run_id, component):
    path = path_for(fixture, 'restart', run_id)
    connector = ConnectClient()
    if phase == 'diagnose':
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute('''SELECT p.workspace_id,p.source_id,p.id,p.dataset_id,
                    p.table_schema,p.table_name,p.generation,
                    s.connection_metadata->>'database'
                    FROM integration_cdc_pipelines p JOIN integration_data_sources s
                    ON s.id=p.source_id ORDER BY p.created_at DESC LIMIT 1''')
                row = cursor.fetchone()
        scope = Scope(*row[:7])
        observation = sample(fixture, scope, connector)
        print(json.dumps({'phase': phase, 'scope': scope.__dict__, 'token': scope.token,
                          'source_database': row[7], 'observation': observation},
                         default=str), flush=True)
        return
    if phase == 'setup':
        scope, database = fixture.d2_source(row_count=1)
        state = {'case': 'restart_matrix', 'result': 'IN_PROGRESS',
                 'scope': scope.__dict__, 'source_database': database,
                 'ids': [1], 'components': {}}
        save(path, state)
        wait_for('restart matrix old Query generation ready',
                 lambda: fixture.rows_equal(scope, expected_rows(state)), seconds=240)
        state['initial'] = sample(fixture, scope, connector)
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'scope': scope.__dict__}), flush=True)
        return
    state = load(path)
    scope = Scope(**state['scope'])
    record = state['components'].setdefault(component, {})
    topics = {'raw': scope.raw_topic, 'normalized': scope.topic('normalized'),
              'transformed': scope.topic('transformed')}
    if phase == 'pre':
        assert fixture.rows_equal(scope, expected_rows(state))
        record['pre'] = sample(fixture, scope, connector)
        record['topic_ends_pre'] = {name: topic_end(topic) for name, topic in topics.items()}
        record['expected_ids_pre'] = state['ids'][:]
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'component': component}), flush=True)
        return
    if phase == 'inject':
        if component not in ('normalizer', 'transformer', 'loader'):
            raise AssertionError('inject only while an event consumer is stopped')
        next_id = max(state['ids']) + 1
        with fixture.pg(state['source_database']) as connection:
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO public.orders VALUES (%s,%s,%s,%s)',
                               (next_id, 'r4b', next_id, 'stream'))
        upstream = {'normalizer': 'raw', 'transformer': 'normalized',
                    'loader': 'transformed'}[component]
        observed_end = wait_for(f'{component} durable upstream event',
            lambda: topic_end(topics[upstream]) if topic_end(topics[upstream]) >
            record['topic_ends_pre'][upstream] else None, seconds=180)
        record['upstream_end_while_stopped'] = observed_end
        record['boundary'] = sample(fixture, scope, connector)
        record['query_unchanged_while_stopped'] = fixture.rows_equal(
            scope, expected_rows(state))
        state['ids'].append(next_id)
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'component': component, 'upstream_end': observed_end}), flush=True)
        return
    if component in ('query', 'connect', 'controller'):
        if component != 'query':
            next_id = max(state['ids']) + 1
            with fixture.pg(state['source_database']) as connection:
                with connection.cursor() as cursor:
                    cursor.execute('INSERT INTO public.orders VALUES (%s,%s,%s,%s)',
                                   (next_id, 'r4b', next_id, 'stream'))
            state['ids'].append(next_id)
    wait_for(f'{component} restart exact Query recovery',
             lambda: fixture.rows_equal(scope, expected_rows(state)), seconds=240)
    after = sample(fixture, scope, connector)
    before = record['pre']
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT number,state FROM integration_cdc_generations '
                           'WHERE pipeline_id=%s ORDER BY number', (scope.pipeline_id,))
            lineage = cursor.fetchall()
            cursor.execute('SELECT cdc_generation FROM manager_databases WHERE id=%s',
                           (scope.dataset_id,))
            query_generation = cursor.fetchone()[0]
    checkpoint_monotonic = all(
        after['checkpoints'].get(key, {}).get('offset', -1) >= value['offset']
        for key, value in before['checkpoints'].items())
    record.update(after=after, lineage=lineage, query_generation=query_generation,
                  checkpoint_monotonic=checkpoint_monotonic,
                  snapshot_unchanged=(after['snapshot'].get('notification_id') ==
                                      before['snapshot'].get('notification_id') and
                                      after['snapshot'].get('status') == 'COMPLETED'),
                  slot_lineage_unchanged=bool(before['slot'] and after['slot']
                                             and list(before['slot'][:3]) ==
                                             list(after['slot'][:3])),
                  exact_query=True)
    record['result'] = ('PASS' if lineage == [(1, 'ACTIVE')]
                        and query_generation == 1 and checkpoint_monotonic
                        and record['snapshot_unchanged']
                        and record['slot_lineage_unchanged']
                        and (component not in ('normalizer', 'transformer', 'loader')
                             or record['query_unchanged_while_stopped']) else 'FAIL')
    save(path, state)
    print(json.dumps({'path': str(path), 'phase': phase, 'component': component,
                      'result': record['result'], 'query_generation': query_generation}), flush=True)
    if record['result'] != 'PASS':
        raise AssertionError(f'{component} restart invariant failed')


def finalize_restart(fixture, run_id):
    path = path_for(fixture, 'restart', run_id)
    state = load(path)
    checks = (all(state['components'].get(name, {}).get('result') == 'PASS'
                  for name in RESTART_COMPONENTS)
              and all(state.get(name) == 'PASS' for name in
                      ('candidate_restart_result', 'interrupted_result',
                       'fresh_match_result', 'match_restart_result'))
              and state.get('cutover', {}).get('result') == 'PASS'
              and state.get('fence_continuity', {}).get('result') == 'PASS')
    state['result'] = 'PASS' if checks else 'FAIL'
    save(path, state)
    print(json.dumps({'path': str(path), 'phase': 'finalize',
                      'result': state['result']}), flush=True)
    if not checks:
        raise AssertionError('restart/reconciliation matrix incomplete')


def recovery(fixture, phase, run_id):
    path = path_for(fixture, 'restart', run_id)
    state = load(path)
    old = Scope(**state['scope'])
    database = state['source_database']
    connector = ConnectClient()
    if phase == 'candidate':
        assert all(state['components'][name]['result'] == 'PASS'
                   for name in RESTART_COMPONENTS)
        assert fixture.rows_equal(old, expected_rows(state))
        candidate = reseed(fixture, old, 'operator_reseed')
        before = sample(fixture, candidate, connector)
        assert before['observed'] == 'PROVISIONING'
        assert not before['connector_configured']
        state['candidate'] = candidate.__dict__
        state['candidate_before_restart'] = before
        state['old_query_at_candidate_creation'] = fixture.rows_equal(
            old, expected_rows(state))
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'candidate': candidate.__dict__}), flush=True)
        return
    candidate = Scope(**state['candidate'])
    if phase == 'candidate_post':
        wait_candidate(fixture, candidate, database)
        after = wait_for('candidate capture readiness after controller restart',
                         lambda: (observed if observed['capture_ready'] else None)
                         if (observed := sample(fixture, candidate, connector)) else None,
                         seconds=120)
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT number,state FROM integration_cdc_generations '
                               'WHERE pipeline_id=%s ORDER BY number',
                               (candidate.pipeline_id,))
                lineage = cursor.fetchall()
        state['candidate_after_restart'] = after
        state['candidate_lineage'] = lineage
        state['candidate_restart_result'] = ('PASS' if
            lineage == [(1, 'ACTIVE'), (2, 'CANDIDATE')]
            and after['slot'] and after['slot_seen'] and after['capture_ready']
            and fixture.rows_equal(old, expected_rows(state)) else 'FAIL')
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'result': state['candidate_restart_result']}), flush=True)
        if state['candidate_restart_result'] != 'PASS':
            raise AssertionError('candidate provisioning controller restart failed')
        return
    if phase == 'watermark_request':
        # Loader is stopped by the caller. Make a transformed row durable first.
        before = topic_end(candidate.topic('transformed'))
        next_id = max(state['ids']) + 1
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO public.orders VALUES (%s,%s,%s,%s)',
                               (next_id, 'r4b', next_id, 'stream'))
        end = wait_for('candidate transformed record held before Loader',
            lambda: (end if end > before else None)
            if (end := topic_end(candidate.topic('transformed'))) else None,
            seconds=180)
        assert fixture.rows_equal(old, expected_rows(state))
        response = fixture.session.post(fixture.base +
            f'/database/sources/{candidate.source_id}/cdc/reconcile/',
            json={'pipeline_id': candidate.pipeline_id},
            headers={'Authorization': 'Bearer ' + fixture.token(candidate.workspace_id)},
            timeout=20)
        assert response.status_code == 202
        attempt_id = response.json()['data']['reconciliation_attempt']['id']
        def waiting():
            observation = sample(fixture, candidate, connector)
            attempt = observation['reconciliation_attempt']
            return observation if (attempt.get('id') == attempt_id
                    and attempt.get('state') == 'WAITING_LOADER'
                    and attempt.get('source_lsn', 0) > 0) else None
        observation = wait_for('persisted nonterminal Loader watermark', waiting,
                               seconds=180)
        state['watermark_boundary'] = observation
        state['watermark_attempt_id'] = attempt_id
        state['held_row_id'] = next_id
        state['transformed_end_while_loader_stopped'] = end
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'attempt': attempt_id, 'state': 'WAITING_LOADER'}), flush=True)
        return
    if phase == 'watermark_after_restart':
        first = state['watermark_attempt_id']
        def interrupted():
            observation = sample(fixture, candidate, connector)
            attempt = observation['reconciliation_attempt']
            return observation if (attempt.get('id') == first
                    and attempt.get('state') == 'FAILED') else None
        observation = wait_for('interrupted watermark attempt failed safely',
                               interrupted, seconds=180)
        attempt = observation['reconciliation_attempt']
        state['interrupted_attempt'] = attempt
        state['interrupted_certificate_absent'] = not certificate(fixture, candidate)
        state['interrupted_result'] = ('PASS' if
            attempt.get('failure_code') == 'CDC_RECONCILIATION_INTERRUPTED'
            and state['interrupted_certificate_absent']
            and fixture.rows_equal(old, expected_rows(state)) else 'FAIL')
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'result': state['interrupted_result'],
                          'failure_code': attempt.get('failure_code')}), flush=True)
        if state['interrupted_result'] != 'PASS':
            raise AssertionError('interrupted reconciliation gained authority')
        return
    if phase == 'fresh_match':
        if state['held_row_id'] not in state['ids']:
            state['ids'].append(state['held_row_id'])
        wait_candidate(fixture, candidate, database)
        proof = state.get('fresh_certificate') or request_reconciliation(fixture, candidate)
        state['fresh_attempt_id'] = proof['attempt_id']
        state['fresh_certificate'] = proof
        state['fresh_match_result'] = ('PASS' if proof['status'] == 'MATCH'
            and proof['attempt_id'] != state['watermark_attempt_id']
            and fixture.rows_equal(old, expected_rows({**state, 'ids':
                [row_id for row_id in state['ids'] if row_id != state['held_row_id']]}))
            else 'FAIL')
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'result': state['fresh_match_result'],
                          'fresh_attempt': proof['attempt_id']}), flush=True)
        if state['fresh_match_result'] != 'PASS':
            raise AssertionError('fresh reconciliation failed')
        return
    if phase == 'refresh_match':
        response = fixture.session.post(fixture.base +
            f'/database/sources/{candidate.source_id}/cdc/reconcile/',
            json={'pipeline_id': candidate.pipeline_id},
            headers={'Authorization': 'Bearer ' + fixture.token(candidate.workspace_id)},
            timeout=20)
        assert response.status_code == 202
        attempt_id = response.json()['data']['reconciliation_attempt']['id']
        proof = wait_for('fresh MATCH for post-restart cutover',
            lambda: (value if value.get('attempt_id') == attempt_id
                    and value.get('status') == 'MATCH' else None)
            if (value := certificate(fixture, candidate)) else None, seconds=180)
        state['pre_refresh_certificate'] = state.get('fresh_certificate', {})
        state['fresh_attempt_id'] = attempt_id
        state['fresh_certificate'] = proof
        state['fresh_match_result'] = 'PASS'
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'attempt': attempt_id, 'issued_at': proof['issued_at']}), flush=True)
        return
    if phase == 'match_restart':
        observed = sample(fixture, candidate, connector)
        proof = certificate(fixture, candidate)
        state['match_after_restart'] = observed
        state['match_restart_result'] = ('PASS' if
            proof.get('attempt_id') == state['fresh_attempt_id']
            and proof.get('status') == 'MATCH'
            and observed['reconciliation_attempt'].get('state') == 'MATCH'
            and fixture.rows_equal(old, expected_rows({**state, 'ids':
                [row_id for row_id in state['ids'] if row_id != state['held_row_id']]}))
            else 'FAIL')
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'result': state['match_restart_result']}), flush=True)
        if state['match_restart_result'] != 'PASS':
            raise AssertionError('MATCH certificate changed after restart')
        return
    if phase == 'cutover_verify':
        observed = sample(fixture, candidate, connector)
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT number,state FROM integration_cdc_generations '
                               'WHERE pipeline_id=%s ORDER BY number',
                               (candidate.pipeline_id,))
                lineage = cursor.fetchall()
                cursor.execute('SELECT cdc_generation FROM manager_databases WHERE id=%s',
                               (candidate.dataset_id,))
                bound = cursor.fetchone()[0]
        state['cutover'] = {'observed': observed, 'lineage': lineage,
                            'query_generation': bound,
                            'exact_query': fixture.rows_equal(candidate,
                                                             expected_rows(state))}
        state['cutover']['result'] = ('PASS' if lineage ==
            [(1, 'SUPERSEDED'), (2, 'ACTIVE')] and bound == 2
            and state['cutover']['exact_query']
            and observed['reconciliation_attempt'].get('id') ==
            state['fresh_attempt_id'] else 'FAIL')
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'result': state['cutover']['result']}), flush=True)
        if state['cutover']['result'] != 'PASS':
            raise AssertionError('certified cutover after restart failed')
        return
    if phase == 'fence_continuity':
        before = sample(fixture, candidate, connector)
        next_id = max(state['ids']) + 1
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO public.orders VALUES (%s,%s,%s,%s)',
                               (next_id, 'r4b', next_id, 'stream'))
        state['ids'].append(next_id)
        wait_for('post-fence source write reaches exact Query',
                 lambda: fixture.rows_equal(candidate, expected_rows(state)),
                 seconds=180)
        after = sample(fixture, candidate, connector)
        state['fence_continuity'] = {'before': before, 'after': after,
            'result': ('PASS' if after['generation_state'] == 'ACTIVE'
                and after['snapshot'].get('notification_id') ==
                    before['snapshot'].get('notification_id')
                and list(after['slot'][:3]) == list(before['slot'][:3])
                and after['checkpoints'].get('load:0', {}).get('offset', -1) >
                    before['checkpoints'].get('load:0', {}).get('offset', -1)
                else 'FAIL')}
        save(path, state)
        print(json.dumps({'path': str(path), 'phase': phase,
                          'result': state['fence_continuity']['result']}), flush=True)
        if state['fence_continuity']['result'] != 'PASS':
            raise AssertionError('post-fence continuity failed')
        return
    raise AssertionError('unknown recovery phase')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--case', choices=['revoke', 'retire', 'restart', 'recovery',
                                           'finalize'], required=True)
    parser.add_argument('--phase', choices=['setup', 'candidate', 'verify', 'pre', 'inject', 'post',
                                            'diagnose', 'candidate_post', 'watermark_request',
                                            'watermark_after_restart', 'fresh_match',
                                            'refresh_match', 'match_restart', 'cutover_verify',
                                            'fence_continuity'], required=True)
    parser.add_argument('--component', choices=RESTART_COMPONENTS)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    fixture = Fixture(args.env_file)
    if args.case == 'recovery':
        recovery(fixture, args.phase, args.run_id)
    elif args.case == 'finalize':
        finalize_restart(fixture, args.run_id)
    elif args.case == 'restart':
        if not args.component:
            parser.error('--component required for restart matrix')
        restart_matrix(fixture, args.phase, args.run_id, args.component)
    else:
        lifecycle(fixture, args.case, args.phase, args.run_id)


if __name__ == '__main__':
    main()
