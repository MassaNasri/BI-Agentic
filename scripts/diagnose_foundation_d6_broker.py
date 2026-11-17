"""Read-only bounded source, Query, and slot state after broker recovery."""
import argparse
import json
from pathlib import Path

from verify_foundation_d_cdc import Fixture
from bi_platform_shared.cdc_contract import Scope


def main(env_file, evidence):
    path = Path(evidence).resolve()
    state = json.loads(path.read_text(encoding='utf-8-sig'))
    scope = Scope(**state['scope'])
    fixture = Fixture(env_file)
    result = {}
    with fixture.pg(state['source_database']) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id,amount::text,status FROM public.orders WHERE id IN (2,3) ORDER BY id')
            result['source_rows'] = cursor.fetchall()
            cursor.execute('SELECT slot_name,active,confirmed_flush_lsn::text,restart_lsn::text,wal_status '
                           'FROM pg_replication_slots WHERE slot_name=%s', ('b_'+scope.token,))
            result['slot'] = cursor.fetchone()
    try:
        response = fixture.api(scope.workspace_id, 'POST', '/query/execute/', {
            'dataset_id': scope.dataset_id,
            'sql': f'SELECT id,amount,status FROM cdc_{scope.token}_current WHERE id IN (2,3) ORDER BY id'})
        result['query_rows'] = response.get('rows')
    except Exception as exc:
        result['query_error_type'] = type(exc).__name__
    try:
        pipeline = fixture.api(scope.workspace_id, 'GET',
            f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        result['pipeline'] = {key: pipeline.get(key) for key in
                              ('desired_state', 'observed_state', 'error_code')}
    except Exception as exc:
        result['pipeline_error_type'] = type(exc).__name__
    output = path.with_name(path.stem + '-broker-diagnosis.json')
    output.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    print(json.dumps({'evidence': str(output), **result}, default=str), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    main(args.env_file, args.evidence)
