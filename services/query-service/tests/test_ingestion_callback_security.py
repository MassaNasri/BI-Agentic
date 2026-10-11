import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import uuid

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVICE_ROOT.parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'service_config.settings')

import django  # noqa: E402
django.setup()
from django.test import override_settings  # noqa: E402

from database.internal_authentication import IngestionServiceAuthentication, InternalIdentityUnavailable  # noqa: E402
from database.views import validate_ingestion_transition  # noqa: E402
from database.views import IngestionDatasetStatusView  # noqa: E402


@pytest.mark.parametrize(
    ('current', 'requested', 'expected'),
    [
        ('pending', 'processing', (True, False)),
        ('processing', 'completed', (True, False)),
        ('pending', 'failed', (True, False)),
        ('processing', 'failed', (True, False)),
        ('completed', 'processing', (False, False)),
        ('failed', 'completed', (False, False)),
        ('completed', 'completed', (True, True)),
    ],
)
def test_dataset_state_machine(current, requested, expected):
    assert validate_ingestion_transition(current, requested) == expected


@override_settings(INGESTION_CALLBACK_API_KEY='configured-test-key')
def test_frontend_bearer_token_cannot_authenticate_as_ingestion_service():
    request = SimpleNamespace(headers={'Authorization': 'Bearer frontend-token'})
    with pytest.raises(Exception):
        IngestionServiceAuthentication().authenticate(request)


@override_settings(INGESTION_CALLBACK_API_KEY='')
def test_missing_ingestion_key_fails_closed():
    with pytest.raises(InternalIdentityUnavailable) as exc:
        IngestionServiceAuthentication().authenticate(SimpleNamespace(headers={}))
    assert exc.value.status_code == 503


@override_settings(INGESTION_CALLBACK_API_KEY='configured-test-key')
def test_approved_ingestion_identity_is_explicit():
    request = SimpleNamespace(headers={
        'X-Internal-Service': 'etl-loader',
        'X-Internal-API-Key': 'configured-test-key',
    })
    principal, auth = IngestionServiceAuthentication().authenticate(request)
    assert principal.service == 'etl-loader'
    assert auth == {'service': 'etl-loader'}


@override_settings(INGESTION_CALLBACK_API_KEY='configured-test-key')
def test_metadata_status_consumer_is_an_approved_ingestion_identity():
    request = SimpleNamespace(headers={
        'X-Internal-Service': 'etl-metadata',
        'X-Internal-API-Key': 'configured-test-key',
    })
    principal, auth = IngestionServiceAuthentication().authenticate(request)
    assert principal.service == 'etl-metadata'
    assert auth == {'service': 'etl-metadata'}


def _callback_request(**overrides):
    data = {
        'dataset_id': 91,
        'workspace_id': 23,
        'expected_state': 'processing',
        'etl_status': 'completed',
    }
    data.update(overrides)
    return SimpleNamespace(data=data, user=SimpleNamespace(service='etl-loader'))


@patch('database.views.Database.objects')
def test_wrong_dataset_job_workspace_binding_is_rejected(objects):
    objects.select_for_update.return_value.filter.return_value.first.return_value = None
    response = IngestionDatasetStatusView.post.__wrapped__(
        IngestionDatasetStatusView(), _callback_request(), uuid.uuid4()
    )
    assert response.status_code == 404
    _, kwargs = objects.select_for_update.return_value.filter.call_args
    assert kwargs['pk'] == 91 and kwargs['workspace_id'] == 23


def test_unknown_callback_fields_are_rejected():
    response = IngestionDatasetStatusView.post.__wrapped__(
        IngestionDatasetStatusView(), _callback_request(clickhouse_table_name='attacker_table'), uuid.uuid4()
    )
    assert response.status_code == 400


@patch('database.views.Database.objects')
def test_identical_callback_is_idempotent(objects):
    database = Mock(pk=91, workspace_id=23, etl_status='completed')
    objects.select_for_update.return_value.filter.return_value.first.return_value = database
    response = IngestionDatasetStatusView.post.__wrapped__(
        IngestionDatasetStatusView(), _callback_request(expected_state='completed'), uuid.uuid4()
    )
    assert response.status_code == 200
    assert response.data['idempotent'] is True
    database.save.assert_not_called()


@patch('database.views.Database.objects')
def test_redelivered_terminal_callback_is_idempotent_with_original_expected_state(objects):
    database = Mock(pk=91, workspace_id=23, etl_status='failed')
    objects.select_for_update.return_value.filter.return_value.first.return_value = database
    response = IngestionDatasetStatusView.post.__wrapped__(
        IngestionDatasetStatusView(),
        _callback_request(expected_state='processing', etl_status='failed'),
        uuid.uuid4(),
    )
    assert response.status_code == 200
    assert response.data['idempotent'] is True
    database.save.assert_not_called()


@patch('database.views.Database.objects')
def test_illegal_terminal_state_transition_is_rejected(objects):
    database = Mock(pk=91, workspace_id=23, etl_status='completed')
    objects.select_for_update.return_value.filter.return_value.first.return_value = database
    response = IngestionDatasetStatusView.post.__wrapped__(
        IngestionDatasetStatusView(),
        _callback_request(expected_state='completed', etl_status='processing'),
        uuid.uuid4(),
    )
    assert response.status_code == 409
    database.save.assert_not_called()
