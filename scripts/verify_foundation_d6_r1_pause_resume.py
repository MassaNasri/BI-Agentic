"""Physical optimized-candidate pause, retained/fresh resume, and exact Query."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import time

from verify_foundation_d_cdc import Fixture
from verify_foundation_d5_r1 import control_row, exact_rows
from bi_platform_shared.cdc_contract import Scope


def main(env_file, evidence):
    base = Path(evidence).resolve()
    state = json.loads(base.read_text(encoding='utf-8-sig'))
    reconciliation = json.loads(base.with_name(base.stem + '-reconciliation.json').read_text())
    scope = Scope(**{**state['scope'], 'generation': reconciliation['generation']})
    fixture = Fixture(env_file)
    output = base.with_name(base.stem + '-r1-pause-resume.json')
    result = {'status': 'RUNNING', 'scope_token': scope.token,
              'generation': scope.generation, 'marks': {}}
    origin = time.monotonic()

    def save():
        output.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')

    def mark(label):
        result['marks'][label] = {'utc': datetime.now(timezone.utc).isoformat(),
                                   'elapsed_seconds': round(time.monotonic()-origin, 3)}
        save()

    def slot():
        with fixture.pg(state['source_database']) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT slot_name,active,restart_lsn::text,'
                               'confirmed_flush_lsn::text,wal_status '
                               'FROM pg_replication_slots WHERE slot_name=%s',
                               ('b_' + scope.token,))
                return cursor.fetchone()

    def telemetry():
        done = subprocess.run(['docker', 'exec', '-e',
                               'CDC_CONNECT_URL=http://connect:8083',
                               f"{state['project_name']}-normalizer-1", 'python',
                               '/acceptance/foundation_d6_r1_telemetry.py',
                               '--token', scope.token], capture_output=True,
                              text=True, timeout=60)
        if done.returncode:
            raise RuntimeError(f'telemetry exit {done.returncode}')
        return json.loads(done.stdout.strip().splitlines()[-1])

    def pipeline():
        rows = fixture.api(scope.workspace_id, 'GET',
                           f'/database/sources/{scope.source_id}/cdc/')['data']
        return next(row for row in rows if row['id'] == scope.pipeline_id)

    def exact():
        physical, source = exact_rows(fixture, scope, state['source_database'])
        if not physical:
            return False
        response = fixture.api(scope.workspace_id, 'POST', '/query/execute/', {
            'dataset_id': scope.dataset_id,
            'sql': f'SELECT groupArray(tuple(id,customer,toString(amount),status)) '
                   f'AS records FROM cdc_{scope.token}_current'})
        rows = response.get('rows', [{}])[0].get('records', [])
        actual = sorted((int(row[0]), row[1], Decimal(row[2]), row[3])
                        for row in rows)
        return actual == sorted(source) and len(actual) == 5000

    def wait(label, predicate, seconds=120):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                value = predicate()
                if value:
                    mark(label)
                    return value
            except Exception as exc:
                result.setdefault('retry_types', []).append(type(exc).__name__)
            time.sleep(2)
        raise AssertionError(f'{label} timed out: {output}')

    if not exact():
        raise AssertionError('Candidate not exact before pause')
    before = telemetry()
    before_slot = slot()
    before_control = control_row(fixture, scope)
    if not before_slot or not before_slot[1] or before_control[6] != 'ACTIVE':
        raise AssertionError('Active candidate/slot precondition failed')
    result['before'] = {'slot': before_slot, 'topics': before['topics'],
                        'checkpoint': before['checkpoints']['load'],
                        'snapshot_notification': before_control[4].get('notification_id')}
    save()
    fixture.api(scope.workspace_id, 'POST',
                f'/database/sources/{scope.source_id}/cdc/pause/',
                {'pipeline_id': scope.pipeline_id}, expected=202)
    mark('pause_accepted')
    paused = wait('paused_slot_inactive', lambda: (row if
        (row := slot()) and row[1] is False and
        (p := pipeline())['desired_state'] == 'PAUSED' and
        p['observed_state'] == 'PAUSED' else None))
    result['pause_seconds'] = round(time.monotonic()-origin-
        result['marks']['pause_accepted']['elapsed_seconds'], 3)
    if result['pause_seconds'] >= 120:
        raise AssertionError('Pause exceeded D2 bound')
    with fixture.pg(state['source_database']) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE public.orders SET status='d6_r1_pause_retained' WHERE id=8")
    mark('retained_write_committed_while_paused')
    time.sleep(3)
    if telemetry()['topics']['raw']['end'] != before['topics']['raw']['end']:
        raise AssertionError('Raw advanced while physically paused')
    fixture.api(scope.workspace_id, 'POST',
                f'/database/sources/{scope.source_id}/cdc/resume/',
                {'pipeline_id': scope.pipeline_id}, expected=202)
    mark('resume_accepted')
    resumed = wait('retained_raw_and_slot_active', lambda: (data if
        (data := telemetry())['topics']['raw']['end'] >=
        before['topics']['raw']['end'] + 1 and
        (row := slot()) and row[1] is True and
        data['connector_status'].get('tasks') == ['RUNNING'] else None))
    result['resume_to_retained_raw_seconds'] = round(
        time.monotonic()-origin-result['marks']['resume_accepted']['elapsed_seconds'], 3)
    if result['resume_to_retained_raw_seconds'] >= 120:
        raise AssertionError('Retained resume exceeded D2 bound')
    with fixture.pg(state['source_database']) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE public.orders SET status='d6_r1_pause_fresh' WHERE id=9")
    mark('fresh_write_committed_after_resume')
    wait('fresh_raw', lambda: telemetry()['topics']['raw']['end'] >=
         before['topics']['raw']['end'] + 2)
    wait('exact_authorized_query', exact)
    after_control = control_row(fixture, scope)
    after_slot = slot()
    result['after'] = {'slot': after_slot, 'control_generation': after_control[0],
                       'generation_state': after_control[6],
                       'snapshot_notification': after_control[4].get('notification_id')}
    result['same_slot'] = (before_slot[0] == paused[0] == after_slot[0])
    result['no_resnapshot'] = (result['before']['snapshot_notification'] ==
                              result['after']['snapshot_notification'])
    result['status'] = ('PASS' if result['same_slot'] and result['no_resnapshot']
                        and after_control[0] == 2 and after_control[6] == 'ACTIVE'
                        else 'FAIL')
    save()
    if result['status'] != 'PASS':
        raise AssertionError(f'Pause/resume invariant failed: {output}')
    print(json.dumps({'evidence': str(output), 'status': result['status'],
                      'pause_seconds': result['pause_seconds'],
                      'resume_to_retained_raw_seconds':
                      result['resume_to_retained_raw_seconds']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    main(args.env_file, args.evidence)
