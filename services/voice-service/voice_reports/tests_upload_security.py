from types import SimpleNamespace
from unittest.mock import patch
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ.setdefault('APP_ENV', 'test')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'service_config.settings')
import django
django.setup()
import pytest

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from voice_reports.views import normalize_pipeline_trace


def test_ai_trace_private_audio_paths_are_redacted_recursively():
    trace = normalize_pipeline_trace({
        'transcription': {
            'attempts': [{'input': {'audio_path': '/tmp/biavora-audio-test.wav'}}],
        },
        'request_metadata': {
            'final_output': {'audio_path': '/app/private_uploads/7/test.wav'},
        },
        'overall_status': {'status': 'success'},
    })
    assert trace['transcription']['attempts'][0]['input']['audio_path'] == '[redacted]'
    assert trace['request_metadata']['final_output']['audio_path'] == '[redacted]'
    assert trace['overall_status']['status'] == 'success'


@pytest.fixture(autouse=True)
def allow_test_host():
    with override_settings(ALLOWED_HOSTS=['testserver']):
        yield


def _client():
    client = APIClient()
    client.force_authenticate(user=SimpleNamespace(is_authenticated=True, id=41, role='manager', email='manager@example.test'))
    return client


def _wav():
    return SimpleUploadedFile('voice.wav', b'RIFF\x00\x00\x00\x00WAVEfmt ', content_type='audio/wav')


def test_real_upload_endpoint_rejects_malformed_audio_before_storage(tmp_path):
    with override_settings(PRIVATE_UPLOAD_ROOT=tmp_path):
        response = _client().post('/voice-reports/upload/', {
            'audio': SimpleUploadedFile('voice.wav', b'not a wav', content_type='audio/wav'),
        }, format='multipart')
    assert response.status_code == 400
    assert list(tmp_path.rglob('*')) == []


@patch('voice_reports.views.extract_identity_context')
@patch('voice_reports.views.get_user_workspace_id')
def test_upload_denied_without_authorized_workspace(workspace, identity, tmp_path):
    workspace.return_value = None
    identity.return_value = SimpleNamespace(user_id='41', email='manager@example.test')
    with override_settings(PRIVATE_UPLOAD_ROOT=tmp_path):
        response = _client().post('/voice-reports/upload/', {'audio': _wav()}, format='multipart')
    assert response.status_code == 400
    assert list(tmp_path.rglob('*')) == []


@patch('voice_reports.views.get_small_whisper_client')
@patch('voice_reports.views.get_subscription_client')
@patch('voice_reports.views._resolve_dataset_binding_context')
@patch('voice_reports.views.extract_identity_context')
@patch('voice_reports.views.get_user_workspace_id')
def test_failed_transcription_removes_private_temp_file(workspace, identity, binding, subscription, whisper, tmp_path):
    workspace.return_value = '23'
    identity.return_value = SimpleNamespace(user_id='41', email='manager@example.test')
    binding.return_value = {'dataset_id': 91, 'workspace_id': '23', 'manager_id': '41'}
    subscription.return_value.check_access.return_value = {'success': True, 'allowed': True}
    whisper.return_value.process_audio.side_effect = RuntimeError('private test detail')
    with override_settings(PRIVATE_UPLOAD_ROOT=tmp_path):
        response = _client().post('/voice-reports/upload/', {'audio': _wav()}, format='multipart')
    assert response.status_code == 500
    assert 'private test detail' not in str(response.data)
    assert not list(tmp_path.rglob('*.wav'))
