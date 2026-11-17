"""Continue read-only observation of a timed-out D6 baseline source."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import time

from verify_foundation_d_cdc import Fixture
from bi_platform_shared.cdc_contract import Scope


def main(env_file, evidence):
    path = Path(evidence).resolve()
    state = json.loads(path.read_text(encoding='utf-8-sig'))
    scope = Scope(**state['scope'])
    fixture = Fixture(env_file)
    # The original harness created this evidence file immediately at T0.
    origin_epoch = path.stat().st_ctime
    state['t0_wallclock_epoch_from_file_creation'] = origin_epoch
    marks = state['marks_seconds_from_T0']
    command = ['docker', 'exec', f"{state['project_name']}-loader-1", 'python',
               '/acceptance/foundation_d6_stage_probe.py', '--token', scope.token]
    versions = f'etl.cdc_{scope.token}_versions'
    state['status'] = 'OBSERVING_AFTER_1000_SECOND_TIMEOUT'

    def elapsed():
        return round(time.time() - origin_epoch, 3)

    def save():
        path.write_text(json.dumps(state, indent=2, default=str), encoding='utf-8')

    deadline = time.time() + 2500
    while time.time() < deadline:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            if result.returncode:
                detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ''
                raise RuntimeError(f'probe exit {result.returncode}: {detail[:100]}')
            sample = json.loads(result.stdout.strip().splitlines()[-1])
            ends, checkpoints = sample['ends'], sample['checkpoints']
            for label, condition in (
                ('T6_normalized_snapshot_complete_offset', ends['normalized'] >= 5000),
                ('T8_transformed_snapshot_complete_offset', ends['transformed'] >= 5000),
            ):
                if condition and label not in marks:
                    marks[label] = elapsed()
            physical = fixture.ch.query(f'SELECT count() FROM {versions}').result_rows[0][0]
            state['samples'].append({'at_seconds': elapsed(), 'ends': ends,
                                     'checkpoints': checkpoints, 'physical_rows': physical,
                                     'observed_state': sample.get('observed_state')})
            drained = (ends['raw'] >= 5004 and
                       all(checkpoints[stage] and checkpoints[stage]['offset'] >= ends[topic]-1
                           for stage, topic in (('normalize', 'raw'),
                                                ('transform', 'normalized'),
                                                ('load', 'transformed'))))
            save()
            if drained:
                marks['T10_loader_final_apply'] = elapsed()
                break
        except Exception as exc:
            state['errors'].append({'at_seconds': elapsed(), 'type': type(exc).__name__,
                                    'message': str(exc)[:160]})
            save()
        time.sleep(10)
    else:
        state['status'] = 'STAGES_TIMEOUT'
        save()
        raise AssertionError(f'Baseline stages did not drain: {path}')

    with fixture.pg(state['source_database']) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id,customer,amount::text,status FROM public.orders ORDER BY id')
            source = [(row[0], row[1], Decimal(row[2]), row[3]) for row in cursor.fetchall()]
    sql = (f'SELECT groupArray(tuple(id,customer,toString(amount),status)) AS records '
           f'FROM cdc_{scope.token}_current')
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            response = fixture.api(11, 'POST', '/query/execute/',
                                   {'dataset_id': scope.dataset_id, 'sql': sql})
            marks.setdefault('T11_query_publication_ready', elapsed())
            rows = response.get('rows', [{}])[0].get('records', [])
            compared = sorted((row[0], row[1], Decimal(row[2]), row[3]) for row in rows)
            if compared == source:
                marks['T12_exact_authorized_query'] = elapsed()
                state.update(status='EXACT_MATCH', source_rows=len(source),
                             query_rows=len(compared),
                             source_to_query_seconds=marks['T12_exact_authorized_query'],
                             budget_seconds=300,
                             **{'pass': marks['T12_exact_authorized_query'] < 300})
                save()
                print(json.dumps({'evidence': str(path), 'status': state['status'],
                                  'seconds': state['source_to_query_seconds'],
                                  'pass': state['pass']}), flush=True)
                return
        except Exception as exc:
            state['errors'].append({'at_seconds': elapsed(), 'type': type(exc).__name__,
                                    'message': str(exc)[:160]})
        time.sleep(2)
    state['status'] = 'EXACT_QUERY_TIMEOUT_OR_MISMATCH'
    save()
    raise AssertionError(f'Baseline exact Query failed: {path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    main(args.env_file, args.evidence)
