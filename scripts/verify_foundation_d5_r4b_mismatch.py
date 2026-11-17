"""Resume and verify a retained R4B mismatch candidate in two phases."""

import argparse
from decimal import Decimal
import json

from bi_platform_shared.cdc_contract import Scope
from verify_foundation_d_cdc import Fixture, wait_for
from verify_foundation_d5_r1 import control_row, wait_candidate
from verify_foundation_d5_r2 import request_reconciliation


def run(fixture, pipeline_id, phase, run_id):
    path = fixture.env_file.parent / f'd5-r4b-mismatch-{run_id}.json'
    if phase == 'prepare':
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute('''SELECT p.workspace_id,p.source_id,p.id,p.dataset_id,
                    p.table_schema,p.table_name,p.generation,
                    s.connection_metadata->>'database'
                    FROM integration_cdc_pipelines p JOIN integration_data_sources s
                    ON s.id=p.source_id WHERE p.id=%s''', (pipeline_id,))
                row = cursor.fetchone()
        assert row and row[6] == 2
        candidate = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], 2)
        old = Scope(row[0], str(row[1]), str(row[2]), row[3], row[4], row[5], 1)
        expected = [[1, 'd2', Decimal(1), 'initial'],
                    [2, 'd2', Decimal(2), 'initial']]
        assert fixture.rows_equal(old, expected)
        wait_candidate(fixture, candidate, row[7])
        fixture.ch.command(
            f'INSERT INTO etl.cdc_{candidate.token}_versions '
            f'SELECT id, customer, amount, status, '
            f"toUInt128('340282366920938463463374607431768211455'), "
            f'toUInt8(1), toFixedString(repeat(\'0\', 64), 64) '
            f'FROM etl.cdc_{candidate.token}_current WHERE id=1')
        wait_for('candidate controlled delete corruption',
                 lambda: len(fixture.ch.query(
                     f'SELECT id FROM etl.cdc_{candidate.token}_current').result_rows) == 1,
                 seconds=30)
        proof = request_reconciliation(fixture, candidate, expected='MISMATCH')
        result = {'status': 'MISMATCH_CERTIFIED', 'pipeline_id': pipeline_id,
                  'old': old.__dict__, 'candidate': candidate.__dict__,
                  'mismatch_chunks': proof['mismatch_chunks'],
                  'old_query_exact': fixture.rows_equal(old, expected)}
        path.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({'path': str(path), 'phase': phase,
                          'status': result['status']}), flush=True)
        return
    result = json.loads(path.read_text(encoding='utf-8'))
    candidate = Scope(**result['candidate'])
    old = Scope(**result['old'])
    assert control_row(fixture, candidate)[6] == 'CANDIDATE'
    assert fixture.rows_equal(old, [[1, 'd2', Decimal(1), 'initial'],
                                    [2, 'd2', Decimal(2), 'initial']])
    result.update(status='PASS', cutover_denied=True, candidate_not_authoritative=True,
                  old_query_exact=True, automatic_repair_observed=False)
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(path), 'phase': phase, 'status': 'PASS'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--pipeline-id', required=True)
    parser.add_argument('--phase', choices=['prepare', 'verify'], required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    run(Fixture(args.env_file), args.pipeline_id, args.phase, args.run_id)
