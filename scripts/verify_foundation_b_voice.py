"""Disposable Gateway Voice -> AI upload check, run inside query-service.

Requires BIA_VOICE_WORKSPACE_ID and BIA_VOICE_ACTOR_ID. A matching disposable
Workspace row must already exist. No credential or file path is printed.
"""

import io
import json
import os
import time
import wave

import django
import requests

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'service_config.settings')
django.setup()

from rest_framework_simplejwt.tokens import AccessToken  # noqa: E402


BASE = 'http://api-gateway:8000'
WORKSPACE = int(os.environ['BIA_VOICE_WORKSPACE_ID'])
ACTOR = int(os.environ['BIA_VOICE_ACTOR_ID'])


def main():
    token = AccessToken()
    token['user_id'] = ACTOR
    token['role'] = 'manager'
    token['workspace_id'] = WORKSPACE
    token['email'] = 'foundation-b@example.invalid'
    token['is_verified'] = True
    headers = {'Authorization': f'Bearer {token}'}
    dataset_id = None
    try:
        response = requests.post(
            f'{BASE}/database/upload/', headers=headers,
            files={'file': ('voice-source.csv', io.BytesIO(b'id,city\n1,Damascus\n'), 'text/csv')},
            timeout=60,
        )
        assert response.status_code == 201, f'dataset HTTP {response.status_code}'
        payload = response.json()
        dataset_id = int(payload['data']['id'])
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            response = requests.get(
                f'{BASE}/database/', headers=headers,
                params={'dataset_id': dataset_id}, timeout=20,
            )
            if response.status_code == 200:
                detail = response.json().get('data') or {}
                if detail.get('clickhouse_table_name') and detail.get('etl_status') == 'completed':
                    break
            time.sleep(3)
        else:
            print('dataset_binding_status', response.status_code, (response.json().get('data') or {}).get('etl_status'))

        bad = requests.post(
            f'{BASE}/voice-reports/upload/', headers=headers,
            data={'workspace_id': WORKSPACE, 'dataset_id': dataset_id},
            files={'audio': ('bad.wav', io.BytesIO(b'not a wave'), 'audio/wav')}, timeout=30,
        )
        print('malformed_audio_status', bad.status_code)
        assert bad.status_code == 400

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b'\x00\x00' * 16000)
        wav_buffer.seek(0)
        response = requests.post(
            f'{BASE}/voice-reports/upload/', headers=headers,
            data={'workspace_id': WORKSPACE, 'dataset_id': dataset_id},
            files={'audio': ('valid.wav', wav_buffer, 'audio/wav')}, timeout=120,
        )
        rendered = json.dumps(response.json())
        assert '/app/private_uploads' not in rendered and 'biavora-audio-' not in rendered
        print('valid_wav_status', response.status_code)
        print('valid_wav_success', bool(response.json().get('success')))
        print('voice_ai_handoff', response.status_code not in {400, 401, 403, 404, 503})
        if response.status_code != 200:
            print('valid_wav_error', str(response.json().get('code') or response.json().get('error') or '')[:180])
        assert response.status_code == 200 and response.json().get('success') is True
    finally:
        if dataset_id is not None:
            response = requests.delete(
                f'{BASE}/database/', headers=headers, timeout=30,
            )
            print('dataset_cleanup_status', response.status_code)


if __name__ == '__main__':
    main()
