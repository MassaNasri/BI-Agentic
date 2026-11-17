"""Real watermark reconciliation and cutover of an optimized 5,000-row scope."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import time

from verify_foundation_d_cdc import Fixture, ROOT, wait_for
from bi_platform_shared.cdc_contract import Scope
from verify_foundation_d5_r1 import control_row, reseed, wait_candidate
from verify_foundation_d5_r2 import request_reconciliation


def main(env_file, evidence):
    path = Path(evidence).resolve()
    state = json.loads(path.read_text(encoding='utf-8-sig'))
    fixture = Fixture(env_file)
    old = Scope(**state['scope'])
    database = state['source_database']
    result = {'status': 'RUNNING', 'source_rows_expected': 5000,
              'old_scope_token': old.token}
    output = path.with_name(path.stem + '-reconciliation.json')

    def save():
        output.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')

    save()
    candidate = reseed(fixture, old, 'operator_reseed')
    result['candidate_scope_token'] = candidate.token
    result['generation'] = candidate.generation
    save()
    wait_candidate(fixture, candidate, database)
    result['candidate_exact_direct_before_certificate'] = True
    save()
    proof = request_reconciliation(fixture, candidate)
    result['certificate'] = {key: proof.get(key) for key in (
        'kind', 'status', 'source_row_count', 'query_row_count', 'chunk_count',
        'source_lsn', 'capture_observed_lsn', 'loader_applied_through_lsn',
        'duration_ms', 'query_duration_ms')}
    save()
    if proof['status'] != 'MATCH' or proof['kind'] != 'watermark_reconciliation.v1':
        raise AssertionError('No real MATCH certificate')
    code = (f'from integration.cdc_reseed import cutover_candidate; '
            f'cutover_candidate("{candidate.pipeline_id}")')
    command = ['docker', 'compose', '--project-name', state['project_name'],
               '--env-file', str(fixture.env_file), '-f', str(ROOT/'docker-compose.cdc-local.yml'),
               'exec', '-T', 'query', 'python', 'manage.py', 'shell', '-c', code]
    cutover = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=45)
    if cutover.returncode:
        result['status'] = 'CUTOVER_FAILED'
        save()
        raise AssertionError(f'Cutover exit {cutover.returncode}')

    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id,customer,amount::text,status FROM public.orders ORDER BY id')
            source = sorted((row[0], row[1], Decimal(row[2]), row[3])
                            for row in cursor.fetchall())
    sql = (f'SELECT groupArray(tuple(id,customer,toString(amount),status)) AS records '
           f'FROM cdc_{candidate.token}_current')

    def exact():
        try:
            response = fixture.api(candidate.workspace_id, 'POST', '/query/execute/',
                                   {'dataset_id': candidate.dataset_id, 'sql': sql})
            rows = response.get('rows', [{}])[0].get('records', [])
            compared = sorted((row[0], row[1], Decimal(row[2]), row[3]) for row in rows)
            return compared == source and len(compared) == 5000
        except (AssertionError, KeyError, IndexError, ValueError):
            return False

    wait_for('candidate cutover authorized Query exact', exact, seconds=90)
    row = control_row(fixture, candidate)
    result.update(status='MATCH_AND_CUTOVER', candidate_query_exact=True,
                  candidate_generation_state=row[6], source_rows=len(source))
    save()
    print(json.dumps({'evidence': str(output), **result}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    main(args.env_file, args.evidence)
