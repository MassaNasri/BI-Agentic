"""Fresh isolated D5 empty snapshot to authorized Query acceptance."""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import uuid

from verify_foundation_d_cdc import Fixture, wait_for
from bi_platform_shared.cdc_contract import Scope


def run(env_file, pipeline_id=None, nonempty=False):
    fixture = Fixture(env_file)
    if nonempty:
        scope, database = fixture.d2_source(row_count=3)
        expected = [[i, 'd2', Decimal(i), 'initial'] for i in (1, 2, 3)]
        wait_for('D4 nonempty snapshot through authorized Query',
                 lambda: fixture.rows_equal(scope, expected), seconds=180)
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE public.orders SET amount=20, status='updated' WHERE id=2")
                cursor.execute('DELETE FROM public.orders WHERE id=1')
                cursor.execute("INSERT INTO public.orders VALUES (4, 'd2', 4, 'inserted')")
        expected = [[2, 'd2', Decimal(20), 'updated'],
                    [3, 'd2', Decimal(3), 'initial'],
                    [4, 'd2', Decimal(4), 'inserted']]
        wait_for('D4 update/delete/insert through authorized Query',
                 lambda: fixture.rows_equal(scope, expected), seconds=180)
        fixture.api(22, 'POST', '/query/execute/', {
            'dataset_id': scope.dataset_id,
            'sql': f'SELECT * FROM cdc_{scope.token}_current'}, expected=403)
        output = {'scope_token': scope.token, 'generation': scope.generation,
                  'nonempty_snapshot': 'PASS', 'mutable_current_state': 'PASS',
                  'foreign_workspace_denied': 'PASS', 'source_database': database}
        path = Path(env_file).resolve().parent / f'd5-nonempty-results-{uuid.uuid4().hex[:8]}.json'
        path.write_text(json.dumps(output, indent=2), encoding='utf-8')
        print(json.dumps({'result': output, 'evidence': str(path)}))
        return
    if pipeline_id:
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute('''SELECT p.workspace_id, p.source_id, p.id, p.dataset_id,
                                  p.table_schema, p.table_name, p.generation,
                                  s.connection_metadata->>'database'
                                  FROM integration_cdc_pipelines p
                                  JOIN integration_data_sources s ON s.id=p.source_id
                                  WHERE p.id=%s''', (pipeline_id,))
                record = cursor.fetchone()
        if record is None:
            raise AssertionError('Explicit isolated pipeline was not found')
        scope = Scope(record[0], str(record[1]), str(record[2]),
                      record[3], record[4], record[5], record[6])
        database = record[7]
    else:
        scope, database = fixture.d2_source(empty=True)
    def status():
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT snapshot_signal, observed_state FROM integration_cdc_pipelines WHERE id=%s',
                    (scope.pipeline_id,))
                return cursor.fetchone()
    def query_rows():
        try:
            return fixture.query(scope)['rows']
        except (AssertionError, KeyError):
            return None
    wait_for('generation-bound durable empty snapshot completion',
             lambda: status()[0].get('completed') is True, seconds=180)
    wait_for('authorized Query publishes an empty current view',
             lambda: query_rows() == [], seconds=180)
    initial_status = status()
    assert initial_status[1] == 'STREAMING'
    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO public.orders VALUES (1, 'after-empty', 12.3400, 'new')")
    def inserted():
        rows = query_rows()
        return (rows is not None and len(rows) == 1
                and rows[0]['id'] == 1
                and rows[0]['customer'] == 'after-empty'
                and Decimal(str(rows[0]['amount'])) == Decimal('12.3400'))
    wait_for('immediate post-snapshot INSERT reaches authorized Query', inserted, seconds=180)
    output = {'scope_token': scope.token, 'generation': scope.generation,
              'empty_snapshot_completion': 'PASS', 'zero_row_query': 'PASS',
              'immediate_insert_query': 'PASS', 'source_database': database}
    path = Path(env_file).resolve().parent / f'd5-empty-results-{uuid.uuid4().hex[:8]}.json'
    path.write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps({'result': output, 'evidence': str(path)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--pipeline')
    parser.add_argument('--nonempty', action='store_true')
    args = parser.parse_args()
    run(args.env_file, args.pipeline, args.nonempty)
