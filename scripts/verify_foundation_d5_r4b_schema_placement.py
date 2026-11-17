"""Live compatible ADD verifies Loader's exact D4 business-column order."""

import argparse
import json

from bi_platform_shared.cdc_contract import Scope
from verify_foundation_d_cdc import Fixture, wait_for
from verify_foundation_d5_r1 import wait_candidate


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    args = parser.parse_args()
    fixture = Fixture(args.env_file)
    prior = json.loads((fixture.env_file.parent /
        'd5-r4b-certificate-primary-20261110a.json').read_text(encoding='utf-8'))
    old = Scope(**prior['old'])
    scope = Scope(old.workspace_id, old.source_id, old.pipeline_id,
                  old.dataset_id, old.schema, old.table, 3)
    wait_candidate(fixture, scope, prior['source_database'])

    def metadata():
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT schema_version,columns FROM integration_cdc_pipelines '
                               'WHERE id=%s', (scope.pipeline_id,))
                return cursor.fetchone()

    before = metadata()[0]
    with fixture.pg(prior['source_database']) as connection:
        with connection.cursor() as cursor:
            cursor.execute('ALTER TABLE public.orders ADD COLUMN r4b_next text')

    def exact_order():
        version, columns = metadata()
        if version <= before or columns[-1]['name'] != 'r4b_next':
            return False
        rows = fixture.ch.query(
            'SELECT name,type FROM system.columns WHERE database={database:String} '
            'AND table={table:String} ORDER BY position', parameters={
                'database': 'etl', 'table': f'cdc_{scope.token}_versions'}).result_rows
        expected = [(column['name'], column['clickhouse_type']) for column in columns]
        expected += [('_cdc_version', 'UInt128'), ('_cdc_deleted', 'UInt8'),
                     ('_cdc_event_id', 'FixedString(64)')]
        return rows == expected

    wait_for('new business column precedes technical D4 fields',
             exact_order, seconds=180)
    result = {'status': 'PASS', 'generation': 3,
              'schema_version_before': before,
              'schema_version_after': metadata()[0],
              'business_before_technical': True,
              'old_query_generation': 1}
    path = fixture.env_file.parent / 'd5-r4b-schema-placement-20261110a.json'
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(path), **result}), flush=True)
