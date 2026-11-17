"""Full optimized pipeline recovery after a disposable Kafka interruption."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import time

from verify_foundation_d_cdc import Fixture, ROOT
from bi_platform_shared.cdc_contract import Scope


def main(env_file, evidence):
    path = Path(evidence).resolve()
    state = json.loads(path.read_text(encoding='utf-8-sig'))
    fixture = Fixture(env_file)
    scope = Scope(**state['scope'])
    output = path.with_name(path.stem + '-broker-recovery.json')
    result = {'status': 'RUNNING', 'budget_seconds': 120,
              'scope_token': scope.token, 'operator_connect_restart': False}

    def save():
        output.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')

    def compose(*args):
        command = ['docker', 'compose', '--project-name', state['project_name'],
                   '--env-file', str(fixture.env_file), '-f',
                   str(ROOT/'docker-compose.cdc-local.yml'), *args]
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        if done.returncode:
            raise AssertionError(f'compose {args} exit {done.returncode}')

    def exact_query():
        with fixture.pg(state['source_database']) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT id,customer,amount::text,status FROM public.orders ORDER BY id')
                source = sorted((row[0], row[1], Decimal(row[2]), row[3])
                                for row in cursor.fetchall())
        sql = (f'SELECT groupArray(tuple(id,customer,toString(amount),status)) AS records '
               f'FROM cdc_{scope.token}_current')
        response = fixture.api(scope.workspace_id, 'POST', '/query/execute/',
                               {'dataset_id': scope.dataset_id, 'sql': sql})
        rows = response.get('rows', [{}])[0].get('records', [])
        query = sorted((row[0], row[1], Decimal(row[2]), row[3]) for row in rows)
        return query == source and len(source) == 5000

    def changed_rows_visible():
        response = fixture.api(scope.workspace_id, 'POST', '/query/execute/', {
            'dataset_id': scope.dataset_id,
            'sql': f'SELECT id,amount,status FROM cdc_{scope.token}_current '
                   'WHERE id IN (2,3) ORDER BY id'})
        rows = response.get('rows', [])
        return (len(rows) == 2 and rows[0]['id'] == 2
                and Decimal(str(rows[0]['amount'])) == Decimal(8800)
                and rows[1]['id'] == 3 and rows[1]['status'] == 'broker_fresh')

    save()
    compose('stop', 'kafka')
    result['broker_stopped'] = True
    save()
    with fixture.pg(state['source_database']) as connection:
        with connection.cursor() as cursor:
            cursor.execute('UPDATE public.orders SET amount=8800 WHERE id=2')
    result['retained_write_committed_during_outage'] = True
    save()
    time.sleep(3)
    compose('start', 'kafka')
    container = f"{state['project_name']}-kafka-1"
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        check = subprocess.run(['docker', 'inspect', '--format',
                                '{{.State.Health.Status}}', container],
                               capture_output=True, text=True, timeout=20)
        if check.returncode == 0 and check.stdout.strip() == 'healthy':
            break
        time.sleep(2)
    else:
        result['status'] = 'BROKER_NOT_HEALTHY'
        save()
        raise AssertionError('Kafka did not become healthy')
    healthy_at = time.monotonic()
    result['broker_healthy'] = True
    result['broker_healthy_epoch_utc'] = time.time()
    with fixture.pg(state['source_database']) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE public.orders SET status='broker_fresh' WHERE id=3")
    result['fresh_write_committed_after_broker_healthy'] = True
    save()
    while time.monotonic() - healthy_at < 120:
        try:
            if changed_rows_visible():
                result.setdefault('changed_rows_visible_seconds',
                                  round(time.monotonic() - healthy_at, 3))
            else:
                time.sleep(3)
                continue
            if exact_query():
                elapsed = round(time.monotonic() - healthy_at, 3)
                pipeline = fixture.api(scope.workspace_id, 'GET',
                    f'/database/sources/{scope.source_id}/cdc/')['data'][0]
                result.update(status='EXACT_MATCH', broker_healthy_to_query_seconds=elapsed,
                              **{'pass': elapsed < 120},
                              desired_state=pipeline.get('desired_state'),
                              observed_state=pipeline.get('observed_state'),
                              error_code=pipeline.get('error_code'))
                save()
                print(json.dumps({'evidence': str(output), **result}), flush=True)
                return
        except Exception as exc:
            result['last_retry_type'] = type(exc).__name__
        time.sleep(3)
    result.update(status='QUERY_TIMEOUT', broker_healthy_to_query_seconds=None,
                  **{'pass': False})
    save()
    raise AssertionError(f'Broker recovery did not reach exact Query within 120 s: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    main(args.env_file, args.evidence)
