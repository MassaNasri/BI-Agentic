"""Isolated D5-R1 legacy and cutover acceptance; no production certificate."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
import requests

from verify_foundation_d_cdc import Fixture, wait_for
from bi_platform_shared.cdc_contract import Scope


ROOT = Path(__file__).resolve().parents[1]


def control_row(fixture, scope):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('''SELECT p.generation, p.observed_state, p.error_code,
                                     p.checkpoints, p.snapshot_signal, p.health,
                                     g.state, g.cutover_phase
                              FROM integration_cdc_pipelines p
                              JOIN integration_cdc_generations g
                                ON g.pipeline_id=p.id AND g.number=p.generation
                              WHERE p.id=%s''', (scope.pipeline_id,))
            return cursor.fetchone()


def engine(fixture, scope):
    rows = fixture.ch.query('SELECT engine FROM system.tables WHERE database={database:String} '
        'AND name={name:String}', parameters={
            'database': 'etl', 'name': f'cdc_{scope.token}_versions'}).result_rows
    return rows[0][0] if rows else None


def exact_rows(fixture, scope, database):
    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id, customer, amount, status FROM public.orders ORDER BY id')
            source = cursor.fetchall()
    candidate = fixture.ch.query(
        f'SELECT id, customer, amount, status FROM etl.cdc_{scope.token}_current ORDER BY id').result_rows
    left = [(int(i), c, Decimal(str(a)), s) for i, c, a, s in source]
    right = [(int(i), c, Decimal(str(a)), s) for i, c, a, s in candidate]
    return left == right, left


def query_exact(fixture, scope, expected):
    return fixture.rows_equal(scope, [list(row) for row in expected])


def reseed(fixture, old, reason):
    session = requests.Session()
    session.trust_env = False
    response = session.post(
        fixture.base + f'/database/sources/{old.source_id}/cdc/reseed/',
        json={'pipeline_id': old.pipeline_id, 'intent': 'reseed', 'reason': reason},
        headers={'Authorization': 'Bearer ' + fixture.token(old.workspace_id),
                 'X-Cdc-Operator-Key': 'd5-r1-isolated-fixture-only'}, timeout=20)
    if response.status_code != 202:
        raise AssertionError(f'reseed HTTP {response.status_code}')
    number = response.json()['data']['generation']
    candidate = Scope(old.workspace_id, old.source_id, old.pipeline_id, old.dataset_id,
                      old.schema, old.table, number)
    if candidate.token == old.token or number != 2:
        raise AssertionError('Candidate generation identity was not isolated')
    return candidate


def abort(fixture, candidate):
    session = requests.Session()
    session.trust_env = False
    response = session.post(
        fixture.base + f'/database/sources/{candidate.source_id}/cdc/abort/',
        json={'pipeline_id': candidate.pipeline_id, 'intent': 'abort_candidate'},
        headers={'Authorization': 'Bearer ' + fixture.token(candidate.workspace_id),
                 'X-Cdc-Operator-Key': 'd5-r1-isolated-fixture-only'}, timeout=20)
    if response.status_code != 202:
        raise AssertionError(f'abort HTTP {response.status_code}')


def django_action(fixture, pipeline_id, name, fault=None, success=True):
    code = (f'from integration.cdc_reseed import {name}; '
            f'{name}("{pipeline_id}"' + (f', fault="{fault}"' if fault else '') + ')')
    command = ['docker', 'compose', '--project-name', 'biavora_foundation_d',
               '--env-file', str(fixture.env_file), '-f', str(ROOT/'docker-compose.cdc-local.yml'),
               'exec', '-T', 'query', 'python', 'manage.py', 'shell', '-c', code]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=40)
    if success and result.returncode != 0 or not success and result.returncode == 0:
        raise AssertionError(f'{name} unexpected exit {result.returncode}')


def wait_candidate(fixture, candidate, database, empty=False):
    def ready():
        row = control_row(fixture, candidate)
        if not row or row[0] != candidate.generation or row[6] != 'CANDIDATE':
            return False
        if row[1] != 'STREAMING' and not (
                empty and row[1] == 'SNAPSHOTTING' and row[4].get('completed') is True):
            return False
        if row[4].get('status') != 'COMPLETED' or not row[5].get('slot_active'):
            return False
        if not (any(k.startswith('load:') for k in row[3]) or row[4].get('completed') is True):
            return False
        return engine(fixture, candidate) == 'MergeTree' and exact_rows(fixture, candidate, database)[0]
    wait_for('candidate snapshot/WAL and exact D4 current state', ready, seconds=240)
    if empty and not control_row(fixture, candidate)[4].get('completed'):
        raise AssertionError('Empty candidate lacks generation-specific durable completion')


def legacy_case(fixture):
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
    wait_for('legacy storage detected and RESEED_REQUIRED', lambda:
        control_row(fixture, old)[1:3] == ('RESEED_REQUIRED', 'CDC_STORAGE_INCOMPATIBLE'), seconds=180)
    candidate = reseed(fixture, old, 'legacy_storage')
    assert candidate.publication_token == old.token
    wait_candidate(fixture, candidate, database)
    django_action(fixture, candidate.pipeline_id, 'issue_local_certificate')
    django_action(fixture, candidate.pipeline_id, 'cutover_candidate')
    expected = exact_rows(fixture, candidate, database)[1]
    wait_for('legacy replacement through authorized Query',
             lambda: query_exact(fixture, candidate, expected), seconds=60)
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT number,state FROM integration_cdc_generations WHERE pipeline_id=%s ORDER BY number',
                           (old.pipeline_id,))
            lineage = cursor.fetchall()
    assert lineage == [(1, 'SUPERSEDED'), (2, 'ACTIVE')]
    assert engine(fixture, old) == 'ReplacingMergeTree' and engine(fixture, candidate) == 'MergeTree'
    return {'old_token': old.token, 'candidate_token': candidate.token,
            'source_database': database, 'legacy_engine': 'ReplacingMergeTree',
            'candidate_engine': 'MergeTree', 'lineage': lineage,
            'query_exact': True}


def legacy_existing_case(fixture):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('''SELECT p.workspace_id,p.source_id,p.id,p.dataset_id,p.table_schema,
                                     p.table_name,s.connection_metadata->>'database',
                                     d.cdc_generation,d.etl_status
                              FROM integration_cdc_pipelines p
                              JOIN integration_data_sources s ON s.id=p.source_id
                              JOIN manager_databases d ON d.id=p.dataset_id
                              WHERE p.id=%s''', ('326183a1-a10a-4785-bbb5-8393a00cc09b',))
            row = cursor.fetchone()
            cursor.execute('SELECT number,state FROM integration_cdc_generations WHERE pipeline_id=%s ORDER BY number',
                           (row[2],))
            lineage = cursor.fetchall()
    old = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], 1)
    candidate = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], 2)
    assert lineage == [(1,'SUPERSEDED'),(2,'ACTIVE')]
    assert row[7:9] == (2,'completed')
    assert engine(fixture,old) == 'ReplacingMergeTree'
    assert engine(fixture,candidate) == 'MergeTree'
    matched, expected = exact_rows(fixture,candidate,row[6])
    assert matched and query_exact(fixture,candidate,expected)
    with fixture.pg(row[6]) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT slot_name FROM pg_replication_slots WHERE slot_name IN (%s,%s)',
                           ('b_'+old.token,'b_'+candidate.token))
            slots = {name for (name,) in cursor.fetchall()}
    assert slots == {'b_'+old.token,'b_'+candidate.token}
    return {'old_token':old.token,'candidate_token':candidate.token,
            'legacy_engine':'ReplacingMergeTree','candidate_engine':'MergeTree',
            'old_and_new_slots_retained':True,'lineage':lineage,'query_exact':True}


def crash_case(fixture, restart=False):
    old, database = fixture.d2_source(row_count=2)
    wait_for('old Query binding ready', lambda: fixture.rows_equal(old,
        [[1, 'd2', Decimal(1), 'initial'], [2, 'd2', Decimal(2), 'initial']]), seconds=180)
    candidate = reseed(fixture, old, 'operator_reseed')
    wait_candidate(fixture, candidate, database)
    django_action(fixture, candidate.pipeline_id, 'issue_local_certificate')
    django_action(fixture, candidate.pipeline_id, 'cutover_candidate', 'before_query', success=False)
    assert fixture.rows_equal(old, [[1, 'd2', Decimal(1), 'initial'], [2, 'd2', Decimal(2), 'initial']])
    assert reseed(fixture, old, 'operator_reseed').token == candidate.token
    django_action(fixture, candidate.pipeline_id, 'cutover_candidate', 'after_query', success=False)
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT cdc_generation FROM manager_databases WHERE id=%s', (old.dataset_id,))
            assert cursor.fetchone()[0] == 2
    if restart:
        fixture.compose('restart', 'controller')
        wait_for('controller restart finalizes Query-bound generation', lambda:
                 control_row(fixture, candidate)[6:8] == ('ACTIVE', 'COMPLETE'), seconds=150)
    else:
        django_action(fixture, candidate.pipeline_id, 'cutover_candidate')
    wait_for('post-bind recovery through authorized Query', lambda: fixture.rows_equal(candidate,
        [[1, 'd2', Decimal(1), 'initial'], [2, 'd2', Decimal(2), 'initial']]), seconds=60)
    return {'old_token': old.token, 'candidate_token': candidate.token,
            'pre_bind_old_query': True, 'post_bind_recovered': True,
            'controller_restart': restart}


def empty_case(fixture):
    old, database = fixture.d2_source(empty=True)
    wait_for('old empty Query binding', lambda: fixture.rows_equal(old, []), seconds=180)
    candidate = reseed(fixture, old, 'operator_reseed')
    wait_candidate(fixture, candidate, database, empty=True)
    django_action(fixture, candidate.pipeline_id, 'issue_local_certificate')
    django_action(fixture, candidate.pipeline_id, 'cutover_candidate')
    wait_for('empty candidate Query binding', lambda: fixture.rows_equal(candidate, []), seconds=60)
    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO public.orders VALUES (1,'after-candidate',1,'new')")
    wait_for('generation 2 post-snapshot INSERT', lambda: fixture.rows_equal(candidate,
        [[1, 'after-candidate', Decimal(1), 'new']]), seconds=180)
    return {'old_token': old.token, 'candidate_token': candidate.token,
            'zero_row_query': True, 'post_snapshot_insert': True}


def empty_resume_case(fixture):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('''SELECT p.workspace_id,p.source_id,p.id,p.dataset_id,p.table_schema,
                                     p.table_name,p.generation,s.connection_metadata->>'database'
                              FROM integration_cdc_pipelines p
                              JOIN integration_data_sources s ON s.id=p.source_id
                              WHERE p.id=%s''', ('ad288d33-c976-4f0b-a302-bf9543649968',))
            row = cursor.fetchone()
    candidate = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], row[6])
    old = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], 1)
    wait_candidate(fixture, candidate, row[7], empty=True)
    django_action(fixture, candidate.pipeline_id, 'issue_local_certificate')
    django_action(fixture, candidate.pipeline_id, 'cutover_candidate')
    wait_for('empty candidate Query binding', lambda: fixture.rows_equal(candidate, []), seconds=60)
    with fixture.pg(row[7]) as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO public.orders VALUES (1,'after-candidate',1,'new')")
    wait_for('generation 2 post-snapshot INSERT', lambda: fixture.rows_equal(candidate,
        [[1, 'after-candidate', Decimal(1), 'new']]), seconds=180)
    return {'old_token': old.token, 'candidate_token': candidate.token,
            'zero_row_query': True, 'post_snapshot_insert': True}


def concurrent_case(fixture):
    old, database = fixture.d2_source(empty=True)
    wait_for('old Query binding before concurrent reseed',
             lambda: fixture.rows_equal(old, []), seconds=180)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reseed, fixture, old, 'operator_reseed') for _ in range(2)]
        candidates = [future.result() for future in futures]
    assert candidates[0].token == candidates[1].token
    candidate = candidates[0]
    assert reseed(fixture, old, 'operator_reseed').token == candidate.token
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM integration_cdc_generations WHERE pipeline_id=%s AND state=%s',
                           (old.pipeline_id, 'CANDIDATE'))
            assert cursor.fetchone()[0] == 1
            cursor.execute('SELECT count(*) FROM manager_databases WHERE id=%s', (old.dataset_id,))
            assert cursor.fetchone()[0] == 1
    wait_candidate(fixture, candidate, database, empty=True)
    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM pg_replication_slots WHERE slot_name=%s',
                           ('b_'+candidate.token,))
            assert cursor.fetchone()[0] == 1
    abort(fixture, candidate)
    abort(fixture, candidate)
    assert control_row(fixture, candidate)[6] == 'FAILED'
    assert fixture.rows_equal(old, [])
    return {'old_token': old.token, 'candidate_token': candidate.token,
            'concurrent_idempotent': True, 'response_loss_retry': True,
            'single_dataset': True, 'single_slot': True,
            'abort_idempotent': True, 'old_query_retained': True}


def run(env_file, case='all'):
    fixture = Fixture(env_file)
    cases = {'legacy': legacy_case, 'legacy_existing': legacy_existing_case,
             'crash': crash_case, 'empty': empty_case,
             'empty_resume': empty_resume_case, 'concurrent': concurrent_case,
             'crash_restart': lambda f: crash_case(f, restart=True)}
    result = {name: cases[name](fixture) for name in (
        ['legacy', 'crash', 'empty'] if case == 'all' else [case])}
    result['certificate'] = 'local_exact_v1 only'
    path = Path(env_file).resolve().parent / f'd5-r1-results-{uuid.uuid4().hex[:8]}.json'
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'result': result, 'evidence': str(path)}), flush=True)


def diagnose(env_file):
    fixture = Fixture(env_file)
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('''SELECT p.workspace_id,p.source_id,p.id,p.dataset_id,p.table_schema,
                                     p.table_name,p.generation,s.connection_metadata->>'database',
                                     d.etl_status,d.cdc_generation,d.clickhouse_table_name
                              FROM integration_cdc_pipelines p
                              JOIN integration_data_sources s ON s.id=p.source_id
                              JOIN manager_databases d ON d.id=p.dataset_id
                              WHERE p.generation=2 ORDER BY p.created_at DESC LIMIT 1''')
            row = cursor.fetchone()
    scope = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], row[6])
    response = fixture.session.post(fixture.base+'/query/execute/',
        json={'dataset_id':scope.dataset_id,
              'sql':f'SELECT id, customer, amount, status FROM cdc_{scope.token}_current ORDER BY id'},
        headers={'Authorization':'Bearer '+fixture.token(scope.workspace_id)}, timeout=20)
    data = response.json()
    print(json.dumps({'pipeline_id':scope.pipeline_id,'database':row[7],
        'dataset_status':row[8], 'dataset_generation':row[9], 'dataset_view':row[10],
        'expected_view':f'cdc_{scope.token}_current', 'http':response.status_code,
        'response_keys':list(data), 'error':data.get('error'),
        'control':control_row(fixture, scope), 'engine':engine(fixture,scope),
        'query_rows':len(data.get('rows',[])),
        'direct_rows':len(fixture.ch.query(f'SELECT * FROM etl.cdc_{scope.token}_current').result_rows)},
        default=str))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--case', choices=['all','legacy','legacy_existing','crash','crash_restart','empty','empty_resume','concurrent'], default='all')
    args = parser.parse_args()
    diagnose(args.env_file) if args.diagnose else run(args.env_file, args.case)
