from __future__ import annotations

import os
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class AuthorizedQuery:
    definition_id: str
    workspace_id: int
    dataset_id: int
    sql: str


class QueryAuthorizationError(Exception):
    def __init__(self, message, *, http_status=502):
        super().__init__(message)
        self.http_status = int(http_status)


def resolve_authorized_query(*, definition_id, authorization_header, expected_workspace_id):
    base_url = os.getenv('QUERY_SERVICE_URL', 'http://query-service:8006').rstrip('/')
    try:
        response = requests.get(
            f'{base_url}/query/definitions/{definition_id}/visualization/',
            headers={'Authorization': authorization_header},
            timeout=(3, 10),
        )
    except requests.RequestException as exc:
        raise QueryAuthorizationError('Query authorization service is unavailable.', http_status=503) from exc
    if response.status_code in {401, 403, 404}:
        raise QueryAuthorizationError('Query definition is not authorized.', http_status=response.status_code)
    if response.status_code != 200:
        raise QueryAuthorizationError('Query authorization service failed.', http_status=502)
    try:
        payload = response.json()
        workspace_id = int(payload.get('workspace_id'))
        dataset_id = int(payload.get('dataset_id'))
        sql = str(payload.get('sql') or '').strip()
    except (TypeError, ValueError, AttributeError) as exc:
        raise QueryAuthorizationError('Query authorization response is invalid.', http_status=502) from exc
    if workspace_id != int(expected_workspace_id) or not sql:
        raise QueryAuthorizationError('Query definition tenant binding is invalid.', http_status=403)
    return AuthorizedQuery(str(definition_id), workspace_id, dataset_id, sql)
