"""Live optimized-stage crash/replay drills on one disposable active candidate."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import time

from verify_foundation_d_cdc import Fixture, ROOT
from verify_foundation_d5_r1 import control_row, exact_rows
from bi_platform_shared.cdc_contract import Scope


def main(env_file, evidence, stage):
    base = Path(evidence).resolve()
    state = json.loads(base.read_text(encoding='utf-8-sig'))
    reconciliation = json.loads(base.with_name(base.stem + '-reconciliation.json').read_text())
    scope = Scope(**{**state['scope'], 'generation': reconciliation['generation']})
    if scope.token != reconciliation['candidate_scope_token']:
        raise AssertionError('Active candidate scope mismatch')
    fixture = Fixture(env_file)
    project = state['project_name']
    database = state['source_database']
    output = base.with_name(base.stem + f'-r1-{stage}-crash.json')
    result = {'status': 'RUNNING', 'stage': stage, 'scope_token': scope.token,
              'generation': scope.generation, 'project': project,
              'marks': {}, 'samples': []}
    origin = time.monotonic()
    service = {'normalize': 'normalizer', 'transform': 'transformer', 'load': 'loader'}[stage]
    observer = {'normalize': 'transformer', 'transform': 'normalizer',
                'load': 'normalizer'}[stage]
    observer_stage = {'normalizer': 'normalize', 'transformer': 'transform'}[observer]
    upstream = {'normalize': 'raw', 'transform': 'normalized',
                'load': 'transformed'}[stage]
    downstream = {'normalize': 'normalized', 'transform': 'transformed'} .get(stage)
    row_ids = {'normalize': (4,), 'transform': (5,), 'load': (6, 7)}[stage]

    def save():
        output.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')

    def mark(name):
        result['marks'][name] = {'utc': datetime.now(timezone.utc).isoformat(),
                                 'elapsed_seconds': round(time.monotonic()-origin, 3)}
        save()

    def compose(*args, timeout=120, expected=0):
        done = subprocess.run(['docker', 'compose', '--project-name', project,
                               '--env-file', str(fixture.env_file), '-f',
                               str(ROOT/'docker-compose.cdc-local.yml'), *args],
                              cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        if done.returncode != expected:
            raise AssertionError(f'compose {args[0]} exit {done.returncode}, expected {expected}')
        return done

    def telemetry():
        done = subprocess.run(['docker', 'exec', '-e',
                               'CDC_CONNECT_URL=http://connect:8083',
                               f'{project}-{observer}-1', 'python',
                               '/acceptance/foundation_d6_r1_telemetry.py',
                               '--token', scope.token, '--stage', observer_stage],
                              capture_output=True, text=True, timeout=60)
        if done.returncode:
            raise RuntimeError(f'telemetry exit {done.returncode}')
        return json.loads(done.stdout.strip().splitlines()[-1])

    def versions(row_id):
        return fixture.ch.query(
            f'SELECT count() FROM etl.cdc_{scope.token}_versions '
            'WHERE id={row_id:Int32}', parameters={'row_id': row_id}).result_rows[0][0]

    def authorized_exact(expected):
        response = fixture.api(scope.workspace_id, 'POST', '/query/execute/', {
            'dataset_id': scope.dataset_id,
            'sql': f'SELECT groupArray(tuple(id,customer,toString(amount),status)) '
                   f'AS records FROM cdc_{scope.token}_current'})
        rows = response.get('rows', [{}])[0].get('records', [])
        actual = sorted((int(row[0]), row[1], Decimal(row[2]), row[3])
                        for row in rows)
        return actual == sorted(expected) and len(actual) == 5000

    def wait_until(label, predicate, seconds=120):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                value = predicate()
                if value:
                    mark(label)
                    return value
            except Exception as exc:
                result.setdefault('transient_errors', []).append(type(exc).__name__)
            time.sleep(2)
        raise AssertionError(f'{label} timed out')

    before_control = control_row(fixture, scope)
    before_exact, source = exact_rows(fixture, scope, database)
    if not before_exact or not authorized_exact(source):
        raise AssertionError('Active candidate not exact before crash drill')
    if before_control[0] != 2 or before_control[6] != 'ACTIVE':
        raise AssertionError('Candidate is not ACTIVE')
    before = telemetry()
    result['before'] = before
    result['snapshot_notification_before'] = before_control[4].get('notification_id')
    result['physical_versions_before'] = {str(row_id): versions(row_id)
                                          for row_id in row_ids}
    save()
    compose('stop', service)
    mark('worker_stopped_before_new_input')
    restarted = False
    try:
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                for row_id in row_ids:
                    cursor.execute('UPDATE public.orders SET status=%s WHERE id=%s',
                                   (f'd6_r1_{stage}_live', row_id))
        mark('source_write_committed')
        count = len(row_ids)
        wait_until('upstream_durable',
                   lambda: ((data if data['topics'][upstream]['end'] >=
                            before['topics'][upstream]['end'] + count else None)
                            if (data := telemetry()) else None), seconds=120)
        after_upstream = telemetry()
        result['upstream'] = after_upstream
        if after_upstream['checkpoints'][stage] != before['checkpoints'][stage]:
            raise AssertionError('Stopped worker checkpoint advanced')
        save()
        crash = compose('run', '--rm', '--no-deps', '-e',
                        f'CDC_CRASH_AFTER_APPLY={stage}', '-e',
                        f'CDC_CRASH_AFTER_APPLY_SCOPE_TOKEN={scope.token}',
                        service, timeout=180, expected=86)
        result['crash_exit_code'] = crash.returncode
        mark('crash_after_durable_effect_before_checkpoint')
        after_crash = telemetry()
        result['after_crash'] = after_crash
        if after_crash['checkpoints'][stage] != before['checkpoints'][stage]:
            raise AssertionError('Checkpoint advanced across crash boundary')
        if downstream and after_crash['topics'][downstream]['end'] < \
                before['topics'][downstream]['end'] + count:
            raise AssertionError('Downstream output not durable before crash')
        if stage == 'load':
            result['physical_versions_after_crash'] = {
                str(row_id): versions(row_id) for row_id in row_ids}
            if any(result['physical_versions_after_crash'][str(row_id)] !=
                   result['physical_versions_before'][str(row_id)] + 1
                   for row_id in row_ids):
                raise AssertionError('Loader batch not durable before crash')
        save()
    finally:
        compose('start', service)
        restarted = True
        mark('worker_restarted')
    if not restarted:
        raise AssertionError('Worker restart failed')

    def recovered():
        current = telemetry()
        checkpoint = current['checkpoints'][stage]
        exact, source_rows = exact_rows(fixture, scope, database)
        if checkpoint and checkpoint['offset'] > before['checkpoints'][stage]['offset'] \
                and exact and authorized_exact(source_rows):
            return current
        return None

    after = wait_until('authorized_query_exact_after_replay', recovered, seconds=180)
    result['after'] = after
    after_control = control_row(fixture, scope)
    result['snapshot_notification_after'] = after_control[4].get('notification_id')
    result['physical_versions_after_replay'] = {str(row_id): versions(row_id)
                                                for row_id in row_ids}
    result['no_resnapshot'] = (result['snapshot_notification_after'] ==
                              result['snapshot_notification_before'])
    result['no_duplicate_logical_state'] = exact_rows(fixture, scope, database)[0]
    result['loader_replay_idempotent'] = stage != 'load' or (
        result['physical_versions_after_replay'] ==
        result['physical_versions_after_crash'])
    result['status'] = ('PASS' if result['no_resnapshot'] and
                        result['no_duplicate_logical_state'] and
                        result['loader_replay_idempotent'] and
                        after_control[0] == 2 and after_control[6] == 'ACTIVE'
                        else 'FAIL')
    save()
    if result['status'] != 'PASS':
        raise AssertionError(f'Crash/replay invariant failed: {output}')
    print(json.dumps({'evidence': str(output), 'status': result['status'],
                      'stage': stage, 'crash_exit_code': result['crash_exit_code'],
                      'loader_replay_idempotent': result['loader_replay_idempotent']}),
          flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--stage', choices=('normalize', 'transform', 'load'), required=True)
    args = parser.parse_args()
    main(args.env_file, args.evidence, args.stage)
