"""Two real controller leases with a delayed external Connect STOP and secret write."""

import argparse
import json
import os
from pathlib import Path
import stat
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from bi_platform_shared.cdc_contract import Scope
from shared.cdc.connect import ConnectClient, password_file_exists
from shared.cdc.worker import (ControlPlane, FencedConnect, _write_password_fenced)
import shared.cdc.worker as worker
from verify_foundation_d_cdc import Fixture, wait_for
from verify_foundation_d5_r3 import sample


def expire_lease(fixture, scope):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE integration_cdc_pipelines SET controller_lease_until="
                           "now()-interval '1 second' WHERE id=%s", (scope.pipeline_id,))


def current_item(fixture, pipeline_id):
    page = 0
    while page is not None:
        response = fixture.session.get(fixture.base + '/internal/v1/cdc/',
            params={'page': page},
            headers={'X-Cdc-Stage': 'controller',
                     'X-Cdc-Key': fixture.env['CDC_CONTROLLER_KEY']}, timeout=20)
        response.raise_for_status()
        data = response.json()
        for item in data['pipelines']:
            if item['scope']['pipeline_id'] == pipeline_id:
                return item
        page = data.get('next_page')
    raise AssertionError('scope not enumerated')


def controller(owner):
    control = ControlPlane('controller')
    control.owner = owner
    return control


def reject_stale(callback):
    try:
        callback()
    except requests.HTTPError as exc:
        return getattr(exc.response, 'status_code', None) == 409
    return False


def run(fixture, state_path):
    prior = json.loads(Path(state_path).read_text(encoding='utf-8'))
    scope = Scope(**current_item(fixture, prior['candidate']['pipeline_id'])['scope'])
    assert scope.generation == 2
    os.environ['CDC_CONTROL_URL'] = fixture.base + '/internal/v1/cdc/'
    os.environ['CDC_SERVICE_KEY'] = fixture.env['CDC_CONTROLLER_KEY']
    os.environ['CDC_CONNECT_URL'] = 'http://connect:8083'
    os.environ['CDC_SECRET_DIRECTORY'] = '/run/cdc-secrets'
    real = ConnectClient()
    before = sample(fixture, scope, real)
    assert before['generation_state'] == 'ACTIVE'
    assert before['connect_state'] == 'RUNNING'
    received, release = threading.Event(), threading.Event()
    proxy_error = []

    class DelayedStop(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_PUT(self):
            if self.path != f'/connectors/b_{scope.token}/stop':
                self.send_error(404)
                return
            received.set()
            if not release.wait(7):
                proxy_error.append('late effect gate timed out')
                self.send_error(504)
                return
            try:
                response = requests.put('http://connect:8083' + self.path,
                                        timeout=5)
                self.send_response(response.status_code)
                self.end_headers()
                self.wfile.write(response.content)
            except Exception as exc:
                proxy_error.append(type(exc).__name__)
                self.send_error(502)

    server = ThreadingHTTPServer(('127.0.0.1', 0), DelayedStop)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    a, b = controller(str(uuid.uuid4())), controller(str(uuid.uuid4()))
    first = second = None
    late = {'post_effect_stale_rejected': False}
    try:
        expire_lease(fixture, scope)
        a.claim(scope)
        first = a.fences[scope.pipeline_id]
        proxied = ConnectClient()
        proxied.url = f'http://127.0.0.1:{server.server_port}'

        def old_stop():
            late['post_effect_stale_rejected'] = reject_stale(
                lambda: FencedConnect(proxied, a, scope).pause(scope))

        old_thread = threading.Thread(target=old_stop)
        old_thread.start()
        assert received.wait(5), 'old controller did not send Connect STOP'
        expire_lease(fixture, scope)
        b.claim(scope)
        second = b.fences[scope.pipeline_id]
        assert second > first
        FencedConnect(real, b, scope).resume(scope)
        release.set()
        old_thread.join(12)
        assert not old_thread.is_alive() and not proxy_error
        assert late['post_effect_stale_rejected']
        assert reject_stale(lambda: a.update(scope, observed_state='STOPPED'))
        wait_for('late Connect STOP reached physical worker',
                 lambda: (status if status and status.get('connector', {}).get('state')
                          == 'STOPPED' else None)
                 if (status := real.request(scope, '/status')) else None,
                 seconds=40)
        FencedConnect(real, b, scope).resume(scope)
        wait_for('new controller restored running Connect task',
                 lambda: (status if status and status.get('connector', {}).get('state')
                          == 'RUNNING' and status.get('tasks') and
                          all(task.get('state') == 'RUNNING'
                              for task in status['tasks']) else None)
                 if (status := real.request(scope, '/status')) else None,
                 seconds=90)
        connect_after = sample(fixture, scope, real)

        # Separate delayed stale file write; no password bytes enter evidence.
        expire_lease(fixture, scope)
        c, d = controller(str(uuid.uuid4())), controller(str(uuid.uuid4()))
        c.claim(scope)
        third = c.fences[scope.pipeline_id]
        file_started, file_release = threading.Event(), threading.Event()
        original_write = worker.write_password
        stale_secret = fixture.env['CDC_SOURCE_ROTATED_PASSWORD']
        current_secret = fixture.env['CDC_SOURCE_PASSWORD']
        file_result = {'post_effect_stale_rejected': False}

        def delayed_write(target, password):
            file_started.set()
            assert file_release.wait(7)
            original_write(target, password)

        def old_file_write():
            worker.write_password = delayed_write
            try:
                file_result['post_effect_stale_rejected'] = reject_stale(
                    lambda: _write_password_fenced(c, scope, stale_secret))
            finally:
                worker.write_password = original_write

        file_thread = threading.Thread(target=old_file_write)
        file_thread.start()
        assert file_started.wait(5)
        expire_lease(fixture, scope)
        d.claim(scope)
        fourth = d.fences[scope.pipeline_id]
        assert fourth > third
        # Direct call avoids the thread-local monkeypatch until the stale write lands.
        d.verify(scope)
        original_write(scope, current_secret)
        d.verify(scope)
        file_release.set()
        file_thread.join(10)
        assert not file_thread.is_alive() and file_result['post_effect_stale_rejected']
        _write_password_fenced(d, scope, current_secret)
        secret_path = Path('/run/cdc-secrets') / f'{scope.token}.properties'
        assert password_file_exists(scope)
        encoded = current_secret.encode('utf-16-be')
        expected_file = 'password=' + ''.join(
            '\\u' + encoded[index:index+2].hex()
            for index in range(0, len(encoded), 2)) + '\n'
        final_secret_matches = secret_path.read_text(encoding='ascii') == expected_file
        mode = stat.S_IMODE(secret_path.stat().st_mode)
        assert final_secret_matches and mode == 0o600
        assert reject_stale(lambda: c.update(scope, observed_state='STOPPED'))

        after = sample(fixture, scope, real)
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT cdc_generation FROM manager_databases WHERE id=%s',
                               (scope.dataset_id,))
                query_generation = cursor.fetchone()[0]
        result = {'case': 'late_external_effect_two_controller', 'status': 'PASS',
                  'scope': scope.__dict__, 'old_fence': first, 'new_fence': second,
                  'secret_old_fence': third, 'secret_new_fence': fourth,
                  'old_connect_post_effect_rejected': late['post_effect_stale_rejected'],
                  'old_logical_callback_rejected': True,
                  'new_connect_running': after['connect_state'] == 'RUNNING',
                  'new_connect_tasks': after['task_states'],
                  'same_slot': list(before['slot'][:3]) == list(after['slot'][:3]),
                  'query_generation': query_generation,
                  'late_secret_post_effect_rejected': file_result['post_effect_stale_rejected'],
                  'final_secret_matches_current': final_secret_matches,
                  'final_secret_mode': oct(mode),
                  'before': before, 'after': after}
        assert result['new_connect_running'] and result['same_slot']
        assert query_generation == 2
        path = fixture.env_file.parent / f'd5-r4b-fence-{scope.token[:8]}.json'
        path.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
        print(json.dumps({'evidence': str(path), 'status': 'PASS',
                          'old_fence': first, 'new_fence': second,
                          'secret_mode': oct(mode)}), flush=True)
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        if first is not None:
            expire_lease(fixture, scope)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--restart-evidence', required=True)
    args = parser.parse_args()
    run(Fixture(args.env_file), args.restart_evidence)
