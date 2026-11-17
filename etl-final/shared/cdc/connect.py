"""Fixed Debezium config, private REST client, protected FileConfigProvider."""
import os
from pathlib import Path
import re
import tempfile
import time
import requests
from bi_platform_shared.cdc_contract import CdcError


def write_password(scope, password):
    root = Path(os.environ['CDC_SECRET_DIRECTORY'])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    target = root / f'{scope.token}.properties'
    # Java Properties escaping, including newlines, separators and surrogate
    # pairs. No arbitrary file paths or property names are accepted from users.
    encoded = password.encode('utf-16-be')
    escaped = ''.join('\\u' + encoded[i:i+2].hex() for i in range(0, len(encoded), 2))
    fd, temporary = tempfile.mkstemp(prefix=f'.{scope.token}.', suffix='.tmp', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as output:
            os.chmod(temporary, 0o600)
            output.write('password=' + escaped + '\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def remove_password(scope):
    (Path(os.environ['CDC_SECRET_DIRECTORY']) / f'{scope.token}.properties').unlink(missing_ok=True)


def password_file_exists(scope):
    target = Path(os.environ['CDC_SECRET_DIRECTORY']) / f'{scope.token}.properties'
    return (target.is_file() and not target.is_symlink()
            and (os.name == 'nt' or target.stat().st_mode & 0o077 == 0))


def configuration(scope, source):
    gate_token = os.getenv('CDC_D5_R4A_GATE_SCOPE_TOKEN', '')
    if gate_token and os.getenv('APP_ENV') != 'test':
        raise CdcError('CDC_FIXTURE_GATE_FORBIDDEN')
    if os.getenv('APP_ENV') == 'production':
        raise CdcError('CDC_TRANSPORT_UNCERTIFIED')
    config = {
        'connector.class': 'io.debezium.connector.postgresql.PostgresConnector',
        'tasks.max': '1', 'plugin.name': 'pgoutput',
        'database.hostname': source['host'], 'database.port': str(source['port']),
        'database.user': source['username'], 'database.dbname': source['database'],
        'database.password': '${file:/run/cdc-secrets/' + scope.token + '.properties:password}',
        'database.sslmode': source.get('sslmode', 'verify-full'),
        'topic.prefix': scope.topic('raw'), 'slot.name': 'b_' + scope.token,
        'publication.name': 'b_' + scope.publication_token, 'publication.autocreate.mode': 'disabled',
        'slot.drop.on.stop': 'false', 'snapshot.mode': 'initial',
        'table.include.list': re.escape(scope.schema + '.' + scope.table),
        'provide.transaction.metadata': 'true', 'heartbeat.interval.ms': '5000',
        'notification.enabled.channels': 'sink',
        'notification.sink.topic.name': scope.topic('notification'),
        'decimal.handling.mode': 'string', 'time.precision.mode': 'adaptive_time_microseconds',
        'tombstones.on.delete': 'true', 'errors.tolerance': 'none',
        # A TRUNCATE must reach normalization and fail closed, never be skipped.
        'skipped.operations': 'none', 'lsn.flush.mode': 'connector',
        'offset.mismatch.strategy': 'no_validation',
        'max.batch.size': '512', 'max.queue.size': '2048', 'poll.interval.ms': '500',
        'key.converter': 'org.apache.kafka.connect.json.JsonConverter',
        'value.converter': 'org.apache.kafka.connect.json.JsonConverter',
        'key.converter.schemas.enable': 'false', 'value.converter.schemas.enable': 'false',
    }
    if gate_token and gate_token == scope.token:
        # The only override is a fixed fixture function that returns exactly
        # public.orders. The token comes from the server-derived scope and the
        # isolated controller environment, never an HTTP request.
        if (scope.generation != 2 or scope.schema != 'public' or scope.table != 'orders'
                or source['host'] != 'postgres'
                or not source['database'].startswith('source_d2_')):
            raise CdcError('CDC_FIXTURE_GATE_FORBIDDEN')
        lock_key = int(scope.token[:15], 16)
        config['snapshot.select.statement.overrides'] = 'public.orders'
        config['snapshot.select.statement.overrides.public.orders'] = (
            f'SELECT * FROM public.biavora_d5_r4a_snapshot_orders({lock_key})')
    return config


class ConnectClient:
    def __init__(self):
        self.url = os.environ['CDC_CONNECT_URL'].rstrip('/')
        self.session = requests.Session()
        self.session.trust_env = False

    def request(self, scope, suffix='', method='GET', body=None):
        response = self.session.request(method, f'{self.url}/connectors/b_{scope.token}{suffix}',
                                        json=body, timeout=10, allow_redirects=False)
        if response.status_code == 404:
            return None
        if response.status_code not in (200, 201, 202, 204):
            raise CdcError('CDC_CONNECT_UNAVAILABLE')
        return response.json() if response.content else {}

    def configure(self, scope, source):
        self.request(scope, '/config', 'PUT', configuration(scope, source))

    def pause(self, scope):
        # Connect pause can leave Debezium's replication thread alive. STOP
        # closes task resources but retains configuration, offsets and the PG
        # slot (slot.drop.on.stop=false). RESUME uses the persisted position.
        self.request(scope, '/stop', 'PUT')

    def wait_stopped(self, scope):
        for _ in range(15):
            status=self.request(scope, '/status')
            if status is None or (status.get('connector',{}).get('state')=='STOPPED' and not status.get('tasks')):
                return
            time.sleep(1)
        raise CdcError('CDC_CONNECT_TRANSITION')

    def resume(self, scope):
        self.request(scope, '/resume', 'PUT')
