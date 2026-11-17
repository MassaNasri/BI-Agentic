"""Live local CDC authorization and warehouse read-only boundary checks."""
import argparse
import json
from pathlib import Path

from verify_foundation_d_cdc import Fixture
from bi_platform_shared.cdc_contract import Scope


def main(env_file, evidence):
    base = Path(evidence).resolve()
    state = json.loads(base.read_text(encoding='utf-8-sig'))
    reconciliation = json.loads(base.with_name(base.stem + '-reconciliation.json').read_text())
    old = Scope(**state['scope'])
    active = Scope(**{**state['scope'], 'generation': reconciliation['generation']})
    fixture = Fixture(env_file)
    output = base.with_name(base.stem + '-r1-security.json')
    results = {}

    def request(workspace, method, path, body=None, role='manager', extra=None):
        headers = {'Authorization': 'Bearer ' + fixture.token(workspace, role)}
        headers.update(extra or {})
        response = fixture.session.request(method, fixture.base + path,
                                           json=body, headers=headers, timeout=15)
        return response.status_code, response.json()

    source_path = f'/database/sources/{old.source_id}/cdc/'
    for action, method, body in (
        ('status/', 'GET', None),
        ('reseed/', 'POST', {'pipeline_id': old.pipeline_id,
                            'intent': 'reseed', 'reason': 'operator_reseed'}),
        ('reconcile/', 'POST', {'pipeline_id': old.pipeline_id}),
    ):
        status, _ = request(22, method, source_path + action, body,
                            extra={'X-Cdc-Operator-Key':
                                   'd5-r1-isolated-fixture-only'})
        if status not in (403, 404):
            raise AssertionError(f'Foreign CDC {action} HTTP {status}')
        results['foreign_' + action.rstrip('/')] = status
    status, _ = request(old.workspace_id, 'GET', source_path, role='viewer')
    if status != 403:
        raise AssertionError(f'Viewer CDC role HTTP {status}')
    results['viewer_cdc'] = status

    query_path = '/query/execute/'
    for label, workspace, sql_text in (
        ('foreign_query', 22, f'SELECT id FROM cdc_{active.token}_current'),
        ('physical_query', old.workspace_id,
         f'SELECT id FROM etl.cdc_{active.token}_versions'),
        ('technical_column', old.workspace_id,
         f'SELECT _cdc_version FROM cdc_{active.token}_current'),
        ('query_mutation', old.workspace_id,
         f'DELETE FROM cdc_{active.token}_current WHERE id=1'),
    ):
        status, payload = request(workspace, 'POST', query_path,
                                  {'dataset_id': active.dataset_id, 'sql': sql_text})
        if status < 400 and payload.get('success') is not False:
            raise AssertionError(f'{label} was accepted')
        if payload.get('rows'):
            raise AssertionError(f'{label} returned rows')
        results[label] = status

    callback = '/internal/v1/cdc/'
    body = {'pipeline_id': old.pipeline_id, 'scope': old.__dict__,
            'checkpoint': {'partition': 0, 'offset': 0, 'lsn': 1}}
    public_status, _ = request(old.workspace_id, 'POST', callback, body)
    if public_status not in (401, 403):
        raise AssertionError(f'Public token callback HTTP {public_status}')
    results['public_callback'] = public_status
    stale = fixture.session.post(fixture.base + callback, json=body, headers={
        'X-Cdc-Stage': 'load', 'X-Cdc-Key': fixture.env['CDC_LOAD_KEY']}, timeout=15)
    if stale.status_code != 409:
        raise AssertionError(f'Stale generation callback HTTP {stale.status_code}')
    results['stale_generation_callback'] = stale.status_code

    public = fixture.api(old.workspace_id, 'GET', source_path + 'status/')
    encoded = json.dumps(public, sort_keys=True)
    forbidden_values = [value for scope in (old, active)
                        for value in (scope.token, 'b_' + scope.token,
                                      'cdc_' + scope.token + '_versions')]
    forbidden_keys = ('controller_fence', 'controller_lease_owner',
                      'slot_name', 'publication_name', 'connector_name',
                      'capture_observed_lsn', 'loader_applied_through_lsn')
    if any(value in encoded for value in forbidden_values) or any(
            '"' + key + '"' in encoded for key in forbidden_keys):
        raise AssertionError('Public status disclosed physical/internal identifiers')
    results['public_status_redacted'] = True

    query_user = __import__('clickhouse_connect').get_client(
        host='127.0.0.1', port=18095, username='cdc_query',
        password=fixture.env['CDC_QUERY_CH_PASSWORD'])
    try:
        grants = query_user.query('SHOW GRANTS').result_rows
        grants_text = ' '.join(str(row) for row in grants).upper()
        if 'SELECT' not in grants_text or any(word in grants_text for word in
                                              ('INSERT', 'ALTER', 'CREATE', 'DROP')):
            raise AssertionError('Query ClickHouse grants are not SELECT-only')
    finally:
        query_user.close()
    results['clickhouse_query_select_only'] = True
    result = {'status': 'PASS', 'scope_token': active.token, 'checks': results}
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'evidence': str(output), **result}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    main(args.env_file, args.evidence)
