"""Disposable live Gateway -> Query -> ETL CSV upload check.

Run inside query-service with ``python -`` and a unique BIA_TEST_WORKSPACE_ID.
No token or service secret is printed. The dataset is deleted in finally.
"""

import io
import json
import os
import time

import django
import requests

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'service_config.settings')
django.setup()

from rest_framework_simplejwt.tokens import AccessToken  # noqa: E402


BASE_URL = 'http://api-gateway:8000'
WORKSPACE = int(os.environ['BIA_TEST_WORKSPACE_ID'])
ACTOR = WORKSPACE


def headers(workspace):
    token = AccessToken()
    token['user_id'] = ACTOR if workspace == WORKSPACE else ACTOR + 1
    token['role'] = 'manager'
    token['workspace_id'] = workspace
    token['email'] = f'foundation-b-{workspace}@example.invalid'
    token['name'] = 'Foundation-B disposable'
    token['is_verified'] = True
    return {'Authorization': f'Bearer {token}'}


def data(response, expected):
    if response.status_code != expected:
        raise AssertionError(f'HTTP {response.status_code}: {response.text[:250]}')
    payload = response.json()
    if not payload.get('success'):
        raise AssertionError(f'Unsuccessful response: {response.status_code}')
    return payload.get('data', payload)


def main():
    own = headers(WORKSPACE)
    foreign = headers(WORKSPACE + 1)
    dataset_id = None
    cleanup_status = None
    try:
        unauthenticated = requests.post(
            f'{BASE_URL}/database/upload/',
            files={'file': ('sample.csv', io.BytesIO(b'id,note\n1,A\n'), 'text/csv')},
            timeout=30,
        )
        if unauthenticated.status_code not in (401, 403):
            raise AssertionError('Unauthenticated upload was accepted')

        malformed = requests.post(
            f'{BASE_URL}/database/upload/', headers=own,
            files={'file': ('malformed.csv', io.BytesIO(b'id,note\n1,"unfinished\n'), 'text/csv')},
            timeout=30,
        )
        if malformed.status_code != 400:
            raise AssertionError(f'Malformed CSV status was {malformed.status_code}')

        unsupported = requests.post(
            f'{BASE_URL}/database/upload/', headers=own,
            files={'file': ('unsupported.xls', io.BytesIO(b'not-a-workbook'), 'application/vnd.ms-excel')},
            timeout=30,
        )
        if unsupported.status_code != 400:
            raise AssertionError(f'Unsupported XLS status was {unsupported.status_code}')

        content = b'id,note\n1,normal\n2,"=SUM(1,1)"\n'
        started = data(requests.post(
            f'{BASE_URL}/database/upload/', headers=own,
            files={'file': ('sample.csv', io.BytesIO(content), 'text/csv')},
            timeout=60,
        ), 201)
        dataset_id = int(started['id'])
        rendered = json.dumps(started).lower()
        if any(marker in rendered for marker in ('/app/uploaded_files', 'saved_path', 'file_path')):
            raise AssertionError('Public upload response exposed internal staging metadata')

        denied = requests.get(
            f'{BASE_URL}/database/', headers=foreign,
            params={'dataset_id': dataset_id}, timeout=25,
        )
        if denied.status_code not in (403, 404):
            raise AssertionError(f'Foreign workspace read status was {denied.status_code}')

        detail = None
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            response = requests.get(
                f'{BASE_URL}/database/', headers=own,
                params={'dataset_id': dataset_id}, timeout=25,
            )
            if response.status_code == 200:
                candidate = data(response, 200)
                if candidate.get('etl_status') == 'failed':
                    raise AssertionError('Dataset extraction failed')
                if candidate.get('etl_status') == 'completed':
                    detail = candidate
                    break
            elif response.status_code not in (202, 409):
                raise AssertionError(f'Dataset poll status was {response.status_code}')
            time.sleep(2)
        if detail is None:
            raise AssertionError('Dataset did not complete within 150 seconds')
        if int(detail['row_count']) != 2:
            raise AssertionError(f"Expected 2 rows, got {detail['row_count']}")

        preview = data(requests.get(
            f'{BASE_URL}/database/preview/', headers=own, timeout=25,
        ), 200)
        if int(preview['total_rows']) != 2:
            raise AssertionError('ClickHouse preview row count differs from source')
        if '=SUM(1,1)' not in [str(row.get('note')) for row in preview['rows']]:
            raise AssertionError('Formula-prefixed source cell was changed during ingestion')

        print(json.dumps({
            'public_gateway': True,
            'workspace_id': WORKSPACE,
            'dataset_id': dataset_id,
            'row_count': 2,
            'unauthenticated_status': unauthenticated.status_code,
            'malformed_status': malformed.status_code,
            'unsupported_status': unsupported.status_code,
            'foreign_status': denied.status_code,
            'formula_preserved_as_data': True,
            'status': 'PASS',
        }, sort_keys=True))
    finally:
        if dataset_id is not None:
            try:
                cleanup_status = requests.delete(f'{BASE_URL}/database/', headers=own, timeout=45).status_code
            except requests.RequestException:
                cleanup_status = 'transport_error'
            print(f'disposable_dataset_cleanup_status={cleanup_status}')
            if cleanup_status != 200:
                raise AssertionError('Disposable dataset cleanup failed')


if __name__ == '__main__':
    main()
