"""Measure a one-retained/one-fresh broker outage without operator recovery."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import time

from verify_foundation_d_cdc import Fixture, ROOT
from bi_platform_shared.cdc_contract import Scope


def main(env_file, evidence, outage_hold_seconds=3, run_tag=''):
    source_path = Path(evidence).resolve()
    state = json.loads(source_path.read_text(encoding='utf-8-sig'))
    scope = Scope(**state['scope'])
    fixture = Fixture(env_file)
    project = state['project_name']
    suffix = ('-r1-long-broker' if outage_hold_seconds > 3 else '-r1-broker') + (f'-{run_tag}' if run_tag else '') + '.json'
    output = source_path.with_name(source_path.stem + suffix)
    result = {'status': 'RUNNING', 'budget_seconds': 120,
              'project': project, 'scope_token': scope.token,
              'outage_hold_seconds': outage_hold_seconds,
              'operator_connect_restart': False, 'offset_reset': False,
              'marks': {}, 'samples': [], 'errors': []}
    origin = time.monotonic()
    retained_amount = (8802 if run_tag == 'postfix2' else 8801) if outage_hold_seconds > 3 else 8800
    fresh_status = ('broker_fresh_long_2' if run_tag == 'postfix2' else 'broker_fresh_long') if outage_hold_seconds > 3 else 'broker_fresh'

    def mark(label):
        result['marks'].setdefault(label, {
            'utc': datetime.now(timezone.utc).isoformat(),
            'elapsed_seconds': round(time.monotonic() - origin, 3)})
        save()

    def save():
        output.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')

    def compose(*args):
        completed = subprocess.run(
            ['docker', 'compose', '--project-name', project, '--env-file',
             str(fixture.env_file), '-f', str(ROOT/'docker-compose.cdc-local.yml'), *args],
            cwd=ROOT, capture_output=True, text=True, timeout=180)
        if completed.returncode:
            raise AssertionError(f'compose {args[0]} failed with exit {completed.returncode}')

    def health(service):
        done = subprocess.run(['docker', 'inspect', '--format',
                               '{{.State.Health.Status}}', f'{project}-{service}-1'],
                              capture_output=True, text=True, timeout=15)
        return done.returncode == 0 and done.stdout.strip() == 'healthy'

    def telemetry():
        done = subprocess.run(['docker', 'exec', '-e',
                               'CDC_CONNECT_URL=http://connect:8083',
                               f'{project}-normalizer-1',
                               'python', '/acceptance/foundation_d6_r1_telemetry.py',
                               '--token', scope.token], capture_output=True,
                              text=True, timeout=60)
        if done.returncode:
            raise RuntimeError(f'telemetry exit {done.returncode}')
        return json.loads(done.stdout.strip().splitlines()[-1])

    def slot():
        with fixture.pg(state['source_database']) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT active,restart_lsn::text,confirmed_flush_lsn::text,'
                               'pg_wal_lsn_diff(pg_current_wal_lsn(),restart_lsn)::bigint '
                               'FROM pg_replication_slots WHERE slot_name=%s',
                               ('b_' + scope.token,))
                row = cursor.fetchone()
        return dict(zip(('active', 'restart_lsn', 'confirmed_flush_lsn',
                         'wal_retained_bytes'), row)) if row else None

    def changed_visible():
        response = fixture.api(scope.workspace_id, 'POST', '/query/execute/', {
            'dataset_id': scope.dataset_id,
            'sql': f'SELECT id,amount,status FROM cdc_{scope.token}_current '
                   'WHERE id IN (2,3) ORDER BY id'})
        rows = response.get('rows', [])
        return (len(rows) == 2 and rows[0]['id'] == 2
                and Decimal(str(rows[0]['amount'])) == Decimal(retained_amount)
                and rows[1]['id'] == 3 and rows[1]['status'] == fresh_status)

    def exact():
        with fixture.pg(state['source_database']) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT id,customer,amount::text,status '
                               'FROM public.orders ORDER BY id')
                expected = sorted((row[0], row[1], Decimal(row[2]), row[3])
                                  for row in cursor.fetchall())
        response = fixture.api(scope.workspace_id, 'POST', '/query/execute/', {
            'dataset_id': scope.dataset_id,
            'sql': f'SELECT groupArray(tuple(id,customer,toString(amount),status)) '
                   f'AS records FROM cdc_{scope.token}_current'})
        rows = response.get('rows', [{}])[0].get('records', [])
        actual = sorted((row[0], row[1], Decimal(row[2]), row[3]) for row in rows)
        result['source_rows'] = len(expected)
        result['query_rows'] = len(actual)
        return actual == expected and len(expected) == 5000

    def observe(data, first):
        topics = data['topics']
        checks = data['checkpoints']
        if first and topics['raw']['end'] >= first['topics']['raw']['end'] + 1:
            mark('T8_raw_retained')
        if first and topics['raw']['end'] >= first['topics']['raw']['end'] + 2:
            mark('T10_raw_fresh')
        for stage, topic, label_a, label_b in (
            ('normalize', 'normalized', 'T11_normalizer_retained', 'T12_normalizer_fresh'),
            ('transform', 'transformed', 'T13_transformer_retained', 'T14_transformer_fresh')):
            if first and topics[topic]['end'] >= first['topics'][topic]['end'] + 1:
                mark(label_a)
            if first and topics[topic]['end'] >= first['topics'][topic]['end'] + 2:
                mark(label_b)
        if first and checks['load']:
            if checks['load']['offset'] >= first['topics']['transformed']['end']:
                mark('T15_loader_retained')
            if checks['load']['offset'] >= first['topics']['transformed']['end'] + 1:
                mark('T16_loader_fresh')
        connect = data['connector_status']
        if connect.get('connector') == 'RUNNING':
            mark('T6_connector_running')
        if 'RUNNING' in connect.get('tasks', []):
            mark('T7_task_running')

    save()
    baseline = telemetry()
    result['baseline'] = baseline
    result['slot_before'] = slot()
    if not exact():
        raise AssertionError('Source and Query must be exact before outage')
    mark('T0_broker_stop_requested')
    compose('stop', 'kafka')
    mark('T0_broker_stopped')
    with fixture.pg(state['source_database']) as connection:
        with connection.cursor() as cursor:
            cursor.execute('UPDATE public.orders SET amount=%s WHERE id=2', (retained_amount,))
    mark('T1_retained_write_committed')
    time.sleep(outage_hold_seconds)
    mark('T2_broker_start_requested')
    compose('start', 'kafka')
    until = time.monotonic() + 180
    while time.monotonic() < until and not health('kafka'):
        time.sleep(1)
    if not health('kafka'):
        result['status'] = 'BROKER_NOT_HEALTHY'
        save()
        raise AssertionError(f'Kafka health timeout: {output}')
    mark('T3_broker_healthy')
    healthy_at = time.monotonic()
    with fixture.pg(state['source_database']) as connection:
        with connection.cursor() as cursor:
            cursor.execute('UPDATE public.orders SET status=%s WHERE id=3', (fresh_status,))
    mark('T9_fresh_write_committed')
    while time.monotonic() - healthy_at < 300:
        if health('connect'):
            mark('T5_connect_worker_healthy')
        try:
            data = telemetry()
            mark('T4_kafka_metadata_available')
            observe(data, baseline)
            sample = {'utc': datetime.now(timezone.utc).isoformat(),
                      'from_broker_health_seconds': round(time.monotonic()-healthy_at, 3),
                      **data, 'slot': slot()}
            result['samples'].append(sample)
            if changed_visible():
                mark('T17_authorized_query_both_writes')
                if exact():
                    mark('T18_exact_source_vs_query')
                    elapsed = round(time.monotonic()-healthy_at, 3)
                    result.update(status='EXACT_MATCH',
                                  broker_healthy_to_exact_seconds=elapsed,
                                  **{'pass': elapsed < 120})
                    save()
                    print(json.dumps({'evidence': str(output), 'status': result['status'],
                                      'seconds': elapsed, 'pass': result['pass']}), flush=True)
                    return
        except Exception as exc:
            result['errors'].append({'from_broker_health_seconds':
                                     round(time.monotonic()-healthy_at, 3),
                                     'type': type(exc).__name__})
        save()
        time.sleep(2)
    result.update(status='EXACT_QUERY_TIMEOUT',
                  broker_healthy_to_exact_seconds=None, **{'pass': False})
    save()
    raise AssertionError(f'Broker recovery exceeded observation window: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--outage-hold-seconds', type=int, default=3)
    parser.add_argument('--run-tag', default='')
    args = parser.parse_args()
    main(args.env_file, args.evidence, args.outage_hold_seconds, args.run_tag)
