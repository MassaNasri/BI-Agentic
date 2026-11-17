"""Bounded live workspace and public-status regression for R4B."""

import argparse
import json

from bi_platform_shared.cdc_contract import Scope
from verify_foundation_d_cdc import Fixture


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    args = parser.parse_args()
    fixture = Fixture(args.env_file)
    prior = json.loads((fixture.env_file.parent /
        'd5-r4b-restart-20261110b.json').read_text(encoding='utf-8'))
    scope = Scope(**prior['scope'])
    active = Scope(**prior['candidate'])
    foreign = scope.workspace_id + 1000
    base = f'/database/sources/{scope.source_id}/cdc/'
    results = {}
    for action, method, body in (
            ('reseed/', 'POST', {'pipeline_id': scope.pipeline_id,
                                'intent': 'reseed', 'reason': 'operator_reseed'}),
            ('reconcile/', 'POST', {'pipeline_id': scope.pipeline_id}),
            ('status/', 'GET', None)):
        response = fixture.session.request(method, fixture.base + base + action,
            json=body, headers={'Authorization': 'Bearer ' + fixture.token(foreign),
                                'X-Cdc-Operator-Key': 'd5-r1-isolated-fixture-only'},
            timeout=15)
        assert response.status_code in {403, 404}, (action, response.status_code)
        results[action] = response.status_code
    public = fixture.api(scope.workspace_id, 'GET', base + 'status/')
    encoded = json.dumps(public, sort_keys=True)
    forbidden_values = [value for token in (scope.token, active.token)
                        for value in (token, 'b_' + token,
                                      'cdc_' + token + '_versions',
                                      'cdc_' + token + '_current')]
    forbidden_keys = ['controller_fence', 'controller_lease_owner',
                      'controller_lease_until', 'slot_name', 'publication_name',
                      'connector_name', 'capture_observed_lsn',
                      'loader_applied_through_lsn']
    assert not any(value in encoded for value in forbidden_values)
    assert not any('"' + key + '"' in encoded for key in forbidden_keys)
    query = '/query/execute/'
    technical = fixture.session.post(fixture.base + query,
        json={'dataset_id': active.dataset_id,
              'sql': f'SELECT _cdc_version FROM cdc_{active.token}_current'},
        headers={'Authorization': 'Bearer ' + fixture.token(active.workspace_id)},
        timeout=15)
    technical_data = technical.json()
    assert technical.status_code >= 400 or technical_data.get('success') is False
    assert not technical_data.get('rows')
    foreign_query = fixture.session.post(fixture.base + query,
        json={'dataset_id': active.dataset_id,
              'sql': f'SELECT id FROM cdc_{active.token}_current'},
        headers={'Authorization': 'Bearer ' + fixture.token(foreign)},
        timeout=15)
    assert foreign_query.status_code in {403, 404}
    result = {'status': 'PASS', 'foreign_workspace_http': results,
              'foreign_query_http': foreign_query.status_code,
              'technical_column_http': technical.status_code,
              'technical_column_rows': 0,
              'physical_identifiers_public': False,
              'controller_lease_internals_public': False,
              'reconciliation_lsn_public': False}
    path = fixture.env_file.parent / 'd5-r4b-security-20261110a.json'
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(path), **result}), flush=True)
