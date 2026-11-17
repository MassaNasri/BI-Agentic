"""Fresh 5,000-row D6 baseline against the existing isolated local fixture.

This is measurement tooling only. It does not alter offsets, connectors, or workers.
Evidence is written beside the external fixture env file, never into the repo.
"""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid

from verify_foundation_d_cdc import Fixture


def main(env_file, project_name, writer_after_first_raw):
    fixture = Fixture(env_file)
    run_id = uuid.uuid4().hex[:8]
    path = Path(env_file).resolve().parent / f'd6-baseline-{run_id}.json'
    started = time.monotonic()
    marks = {'T0_source_candidate_creation': 0.0}
    state = {'status': 'RUNNING', 'run_id': run_id, 'rows_initial': 5000,
             'project_name': project_name,
             'marks_seconds_from_T0': marks, 'samples': [], 'errors': []}

    def save():
        path.write_text(json.dumps(state, indent=2, default=str), encoding='utf-8')

    save()
    scope, database = fixture.d2_source(row_count=5000)
    state.update({'scope': scope.__dict__, 'source_database': database})
    save()
    writer_errors = []
    mutation_times = []

    def writer():
        try:
            connection = fixture.pg(database)
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute('UPDATE public.orders SET amount=9001 WHERE id=2500')
                cursor.execute("INSERT INTO public.orders VALUES (5001,'d6',5001,'inserted')")
                cursor.execute('DELETE FROM public.orders WHERE id=1')
                cursor.execute("UPDATE public.orders SET status='updated' WHERE id=3")
                mutation_times.append(round(time.monotonic() - started, 3))
                deadline = time.monotonic() + 20
                index = 0
                while time.monotonic() < deadline:
                    cursor.execute('UPDATE public.orders SET amount=%s WHERE id=2500', (index,))
                    mutation_times.append(round(time.monotonic() - started, 3))
                    index += 1
                    time.sleep(0.1)
                cursor.execute("UPDATE public.orders SET amount=9002 WHERE id=2")
                mutation_times.append(round(time.monotonic() - started, 3))
            connection.close()
        except Exception as exc:
            writer_errors.append(type(exc).__name__)

    if writer_after_first_raw:
        first = subprocess.run(
            ['docker', 'exec', f'{project_name}-loader-1', 'python',
             '/acceptance/foundation_d6_wait_raw.py', '--scope', json.dumps(scope.__dict__)],
            capture_output=True, text=True, timeout=210)
        if first.returncode:
            state['status'] = 'FIRST_RAW_BARRIER_FAILED'
            state['errors'].append({'type': 'FirstRawBarrier',
                                    'message': first.stderr.strip().splitlines()[-1][:160]
                                    if first.stderr.strip() else f'exit {first.returncode}'})
            save()
            raise AssertionError(f'First raw barrier failed: {path}')
        state['first_raw_barrier'] = json.loads(first.stdout.strip().splitlines()[-1])
        marks['T3_raw_topic_first_row'] = round(time.monotonic() - started, 3)
        save()
    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    probe_cmd = ['docker', 'exec', f'{project_name}-loader-1', 'python',
                 '/acceptance/foundation_d6_stage_probe.py', '--token', scope.token]
    versions = f'etl.cdc_{scope.token}_versions'
    deadline = started + 1000
    last_ends = None
    while time.monotonic() < deadline:
        now = time.monotonic()
        try:
            probe = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
            if probe.returncode:
                detail = probe.stderr.strip().splitlines()[-1] if probe.stderr.strip() else ''
                raise RuntimeError(f'probe exit {probe.returncode}: {detail[:100]}')
            sample = json.loads(probe.stdout.strip().splitlines()[-1])
            ends = sample['ends']
            last_ends = ends
            for label, condition in (
                ('T3_raw_topic_first_row', ends['raw'] > 0),
                ('T4_raw_snapshot_complete_offset', ends['raw'] >= 5000),
                ('T5_normalized_first_event', ends['normalized'] > 0),
                ('T6_normalized_snapshot_complete_offset', ends['normalized'] >= 5000),
                ('T7_transformed_first_event', ends['transformed'] > 0),
                ('T8_transformed_snapshot_complete_offset', ends['transformed'] >= 5000),
            ):
                if condition and label not in marks:
                    marks[label] = round(time.monotonic() - started, 3)
            try:
                physical = fixture.ch.query(f'SELECT count() FROM {versions}').result_rows[0][0]
            except Exception:
                # Loader storage may not exist until controller preparation.
                physical = 0
            if physical and 'T9_loader_first_apply' not in marks:
                marks['T9_loader_first_apply'] = round(time.monotonic() - started, 3)
            checkpoints = sample['checkpoints']
            writer_done = not thread.is_alive()
            drained = (writer_done and ends['raw'] >= 5004
                       and all(checkpoints[stage] and checkpoints[stage]['offset'] >= ends[topic] - 1
                               for stage, topic in (('normalize', 'raw'),
                                                    ('transform', 'normalized'),
                                                    ('load', 'transformed'))))
            if drained and 'T10_loader_final_apply' not in marks:
                marks['T10_loader_final_apply'] = round(time.monotonic() - started, 3)
            state['samples'].append({'at_seconds': round(now-started, 3),
                                     'ends': ends, 'checkpoints': checkpoints,
                                     'physical_rows': physical,
                                     'observed_state': sample.get('observed_state')})
            save()
            if drained:
                break
        except Exception as exc:
            state['errors'].append({'at_seconds': round(now-started, 3),
                                    'type': type(exc).__name__, 'message': str(exc)[:160]})
            save()
        time.sleep(5)

    thread.join(timeout=5)
    state['mutation_count'] = len(mutation_times)
    state['first_mutation_seconds'] = mutation_times[0] if mutation_times else None
    state['last_mutation_seconds'] = mutation_times[-1] if mutation_times else None
    state['writer_errors'] = writer_errors
    if writer_errors or thread.is_alive() or 'T10_loader_final_apply' not in marks:
        state['status'] = 'FAILED_BEFORE_EXACT_QUERY'
        state['last_ends'] = last_ends
        save()
        raise AssertionError(f'Baseline did not drain; evidence: {path}')

    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id,customer,amount::text,status FROM public.orders ORDER BY id')
            source = [(row[0], row[1], Decimal(row[2]), row[3]) for row in cursor.fetchall()]
    sql = (f'SELECT groupArray(tuple(id,customer,toString(amount),status)) AS records '
           f'FROM cdc_{scope.token}_current')
    query_deadline = time.monotonic() + 120
    while time.monotonic() < query_deadline:
        try:
            response = fixture.api(11, 'POST', '/query/execute/',
                                   {'dataset_id': scope.dataset_id, 'sql': sql})
            marks.setdefault('T11_query_publication_ready', round(time.monotonic()-started, 3))
            rows = response.get('rows', [{}])[0].get('records', [])
            compared = sorted((row[0], row[1], Decimal(row[2]), row[3]) for row in rows)
            if compared == source:
                marks['T12_exact_authorized_query'] = round(time.monotonic()-started, 3)
                state['status'] = 'EXACT_MATCH'
                state['source_rows'] = len(source)
                state['query_rows'] = len(compared)
                state['source_to_query_seconds'] = marks['T12_exact_authorized_query']
                state['budget_seconds'] = 300
                state['pass'] = state['source_to_query_seconds'] < 300
                save()
                print(json.dumps({'evidence': str(path), 'status': state['status'],
                                  'seconds': state['source_to_query_seconds'],
                                  'pass': state['pass']}), flush=True)
                return
        except Exception as exc:
            state['errors'].append({'at_seconds': round(time.monotonic()-started, 3),
                                    'type': type(exc).__name__, 'message': str(exc)[:160]})
        time.sleep(2)
    state['status'] = 'EXACT_QUERY_TIMEOUT_OR_MISMATCH'
    save()
    raise AssertionError(f'Exact Query failed; evidence: {path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--project-name', default='biavora_foundation_d')
    parser.add_argument('--writer-after-first-raw', action='store_true')
    args = parser.parse_args()
    main(args.env_file, args.project_name, args.writer_after_first_raw)
