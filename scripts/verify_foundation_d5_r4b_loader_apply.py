"""Live Loader crash after ClickHouse apply and before durable checkpoint."""

import argparse
import json

from bi_platform_shared.cdc_contract import Scope
from verify_foundation_d_cdc import Fixture, wait_for
from verify_foundation_d5_r1 import control_row, exact_rows
from verify_foundation_d5_r4b import topic_end


def save(path, value):
    path.write_text(json.dumps(value, indent=2, default=str), encoding='utf-8')


def versions_count(fixture, scope, row_id):
    return fixture.ch.query(
        f'SELECT count() FROM etl.cdc_{scope.token}_versions WHERE id={{row_id:Int32}}',
        parameters={'row_id': row_id}).result_rows[0][0]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--phase', choices=['pre', 'inject', 'applied', 'post'],
                        required=True)
    args = parser.parse_args()
    fixture = Fixture(args.env_file)
    path = fixture.env_file.parent / 'd5-r4b-loader-after-apply-20261110a.json'
    prior = json.loads((fixture.env_file.parent /
        'd5-r4b-restart-20261110b.json').read_text(encoding='utf-8'))
    scope = Scope(**prior['candidate'])
    database = prior['source_database']
    if args.phase == 'pre':
        exact, source = exact_rows(fixture, scope, database)
        assert exact and fixture.rows_equal(scope, [list(row) for row in source])
        control = control_row(fixture, scope)
        assert control[0] == 2 and control[6] == 'ACTIVE'
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT max(id) FROM public.orders')
                next_id = cursor.fetchone()[0] + 1
        state = {'status': 'PREPARED', 'scope': scope.__dict__,
                 'source_database': database, 'new_id': next_id,
                 'pre_loader_checkpoint': control[3].get('load:0'),
                 'pre_snapshot_notification': control[4].get('notification_id'),
                 'pre_transformed_end': topic_end(scope.topic('transformed')),
                 'pre_query_exact': True}
        assert state['pre_loader_checkpoint']
        save(path, state)
    else:
        state = json.loads(path.read_text(encoding='utf-8'))
        row_id = state['new_id']
        if args.phase == 'inject':
            with fixture.pg(database) as connection:
                with connection.cursor() as cursor:
                    cursor.execute('INSERT INTO public.orders VALUES (%s,%s,%s,%s)',
                                   (row_id, 'r4b', row_id, 'stream'))
            end = wait_for('transformed row durable while Loader stopped',
                           lambda: (value if value > state['pre_transformed_end']
                                    else None)
                           if (value := topic_end(scope.topic('transformed')))
                           else None, seconds=180)
            state['transformed_end_while_loader_stopped'] = end
            assert control_row(fixture, scope)[3].get('load:0') == state['pre_loader_checkpoint']
        elif args.phase == 'applied':
            wait_for('ClickHouse apply before checkpoint',
                     lambda: versions_count(fixture, scope, row_id) == 1,
                     seconds=60)
            assert control_row(fixture, scope)[3].get('load:0') == state['pre_loader_checkpoint']
            state['after_crash_versions_count'] = versions_count(fixture, scope, row_id)
            state['checkpoint_unchanged_after_apply'] = True
        elif args.phase == 'post':
            prior_offset = state['pre_loader_checkpoint']['offset']
            wait_for('Loader replay advances checkpoint and Query exact',
                     lambda: control_row(fixture, scope)[3].get('load:0', {}).get(
                         'offset', -1) > prior_offset
                     and exact_rows(fixture, scope, database)[0]
                     and fixture.rows_equal(scope, [list(row) for row in
                         exact_rows(fixture, scope, database)[1]]),
                     seconds=180)
            control = control_row(fixture, scope)
            assert control[0] == 2 and control[6] == 'ACTIVE'
            assert control[4].get('notification_id') == state['pre_snapshot_notification']
            assert versions_count(fixture, scope, row_id) == 1
            state.update(status='PASS', post_loader_checkpoint=control[3]['load:0'],
                         post_versions_count=1, replay_idempotent=True,
                         query_exact=True, no_resnapshot=True)
        save(path, state)
    print(json.dumps({'path': str(path), 'phase': args.phase,
                      'status': state['status'], 'scope_token': scope.token}),
          flush=True)
