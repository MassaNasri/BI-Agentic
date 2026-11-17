"""Live credential rotation, stale epoch denial, and same-slot CDC continuity."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import time

import psycopg2
from psycopg2 import sql

from verify_foundation_d_cdc import Fixture
from verify_foundation_d5_r1 import control_row, exact_rows
from bi_platform_shared.cdc_contract import Scope


def main(env_file, evidence):
    base = Path(evidence).resolve()
    state = json.loads(base.read_text(encoding='utf-8-sig'))
    reconciliation = json.loads(base.with_name(base.stem + '-reconciliation.json').read_text())
    scope = Scope(**{**state['scope'], 'generation': reconciliation['generation']})
    fixture = Fixture(env_file)
    database = state['source_database']
    role = 'cdc_d2_' + database.removeprefix('source_d2_')
    output = base.with_name(base.stem + '-r1-rotation-v2.json')
    result = {'status': 'RUNNING', 'scope_token': scope.token, 'generation': 2,
              'marks': {}, 'retry_types': []}
    origin = time.monotonic()

    def save():
        output.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')

    def mark(label):
        result['marks'][label] = {'utc': datetime.now(timezone.utc).isoformat(),
                                   'elapsed_seconds': round(time.monotonic()-origin, 3)}
        save()

    def slot():
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT slot_name,active,restart_lsn::text '
                               'FROM pg_replication_slots WHERE slot_name=%s',
                               ('b_' + scope.token,))
                return cursor.fetchone()

    def exact():
        physical, source = exact_rows(fixture, scope, database)
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

    if not exact():
        raise AssertionError('Candidate not exact before rotation')
    before_slot = slot()
    before_control = control_row(fixture, scope)
    result['before'] = {'slot': before_slot,
                        'snapshot_notification': before_control[4].get('notification_id'),
                        'generation_state': before_control[6]}
    save()
    with fixture.pg() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('ALTER ROLE {} PASSWORD %s').format(
                sql.Identifier(role)), (fixture.env['CDC_SOURCE_ROTATED_PASSWORD'],))
    mark('source_role_password_rotated')
    fixture.api(scope.workspace_id, 'POST',
                f'/database/sources/{scope.source_id}/credential/rotate/',
                {'password': fixture.env['CDC_SOURCE_ROTATED_PASSWORD']})
    mark('rotation_accepted')
    try:
        fixture.pg(database, user=role,
                   password=fixture.env['CDC_SOURCE_PASSWORD']).close()
    except psycopg2.OperationalError:
        result['old_password_rejected'] = True
    else:
        raise AssertionError('Old source password still accepted')
    with fixture.pg(database, user=role,
                    password=fixture.env['CDC_SOURCE_ROTATED_PASSWORD']) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM public.orders')
            result['rotated_password_source_rows'] = cursor.fetchone()[0]
    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE public.orders SET status='d6_r1_rotated' WHERE id=10")
    mark('post_rotation_write_committed')
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if exact():
                mark('post_rotation_exact_authorized_query')
                break
        except Exception as exc:
            result['retry_types'].append(type(exc).__name__)
        time.sleep(2)
    else:
        raise AssertionError(f'Post-rotation Query did not converge: {output}')
    # The first catch-up can precede the controller's credential reconfigure.
    # Observe the settled state, then prove another distinct write still flows.
    time.sleep(30)
    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE public.orders SET status='d6_r1_rotated_settled' WHERE id=11")
    mark('settled_rotation_write_committed')
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if exact():
                mark('settled_rotation_exact_authorized_query')
                break
        except Exception as exc:
            result['retry_types'].append(type(exc).__name__)
        time.sleep(2)
    else:
        raise AssertionError(f'Settled rotation Query did not converge: {output}')
    after_control = control_row(fixture, scope)
    after_slot = slot()
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT desired_state FROM integration_cdc_pipelines WHERE id=%s',
                           (scope.pipeline_id,))
            desired_state = cursor.fetchone()[0]
    # The old generation/credential scope must not cross the new credential fence.
    stale = fixture.session.post(fixture.base + '/internal/v1/cdc/', json={
        'pipeline_id': scope.pipeline_id, 'scope': scope.__dict__,
        'checkpoint': {'partition': 0, 'offset': 0, 'lsn': 1}},
        headers={'X-Cdc-Stage': 'load', 'X-Cdc-Key': fixture.env['CDC_LOAD_KEY']},
        timeout=15)
    result['stale_credential_epoch_callback_http'] = stale.status_code
    result['same_slot'] = before_slot[0] == after_slot[0] and after_slot[1] is True
    result['no_resnapshot'] = (before_control[4].get('notification_id') ==
                              after_control[4].get('notification_id'))
    result['generation_state'] = after_control[6]
    result['desired_state'] = desired_state
    result['observed_state'] = after_control[1]
    result['error_code'] = after_control[2]
    result['status'] = ('PASS' if result['old_password_rejected'] and
                        result['rotated_password_source_rows'] == 5000 and
                        result['same_slot'] and result['no_resnapshot'] and
                        after_control[0] == 2 and after_control[6] == 'ACTIVE' and
                        desired_state == 'STREAMING' and after_control[1] == 'STREAMING'
                        and after_control[2] == '' and
                        stale.status_code == 409 else 'FAIL')
    save()
    if result['status'] != 'PASS':
        raise AssertionError(f'Rotation invariant failed: {output}')
    print(json.dumps({'evidence': str(output), 'status': result['status'],
                      'stale_credential_epoch_callback_http': stale.status_code,
                      'same_slot': result['same_slot'],
                      'no_resnapshot': result['no_resnapshot']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    main(args.env_file, args.evidence)
