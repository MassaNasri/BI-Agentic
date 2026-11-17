"""Bounded CDC worker modes for Connector/Extractor/Transformer/Loader owners.

At-least-once across Kafka/ClickHouse/control-plane boundaries. A record is only
acknowledged after its durable effect and checkpoint. Replays are harmless to
the current-state projection. No row payload is ever logged or put into a DLQ.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from datetime import datetime, timezone
import json
import logging
import os
import time
import threading
import uuid
import requests
from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from kafka.structs import OffsetAndMetadata
from kafka.consumer.subscription_state import ConsumerRebalanceListener
from kafka.errors import OffsetOutOfRangeError, NoOffsetForPartitionError
from prometheus_client import Counter, Gauge, start_http_server
from bi_platform_shared.cdc_contract import Scope, CdcError, canonical, normalize, validate, safe_dlq
from bi_platform_shared.credential_crypto import decrypt_credential
from shared.connectors.core import normalize_snapshot_row
from . import postgres
from .schema import schema_additions, transform, convert, ensure_row_images
from .clickhouse import BatchConflict, store_from_env
from .connect import ConnectClient, write_password, remove_password, password_file_exists, configuration as connector_configuration

log = logging.getLogger(__name__)
EVENTS = Counter('biavora_cdc_events_total', 'CDC stage outcomes', ['stage', 'outcome'])
LAG = Gauge('biavora_cdc_event_lag_seconds', 'Last event age, bounded stage label', ['stage'])
HEARTBEAT = Gauge('biavora_cdc_worker_heartbeat_seconds', 'Successful control-plane poll', ['stage'])
CONTROLLER_OWNER = str(uuid.uuid4())


class ControlPlane:
    def __init__(self, stage):
        self.stage = stage
        self.url = os.environ['CDC_CONTROL_URL']
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({'X-Cdc-Stage': stage, 'X-Cdc-Key': os.environ['CDC_SERVICE_KEY']})
        self.owner = CONTROLLER_OWNER if stage == 'controller' else None
        self.fences = {}
        self.recover_cutovers = stage == 'controller'

    def pipelines(self):
        result, page = [], 0
        while page is not None:
            params = {'page': page}
            if self.recover_cutovers and page == 0:
                params['recover_cutovers'] = '1'
            response = self.session.get(self.url, params=params, timeout=10, allow_redirects=False)
            response.raise_for_status()
            if page == 0:
                self.recover_cutovers = False
            data=response.json()
            result.extend(data['pipelines'])
            page=data.get('next_page')
        return result

    def update(self, scope, **fields):
        if self.stage == 'controller':
            fields = {**fields, 'lease_owner': self.owner,
                      'lease_fence': self.fences[scope.pipeline_id]}
        response = self.session.post(self.url, json={'pipeline_id': scope.pipeline_id, 'scope': scope.__dict__, **fields},
                                     timeout=10, allow_redirects=False)
        response.raise_for_status()

    def claim(self, scope):
        response = self.session.post(self.url, json={
            'action': 'claim', 'pipeline_id': scope.pipeline_id,
            'scope': scope.__dict__, 'owner': self.owner,
        }, timeout=10, allow_redirects=False)
        response.raise_for_status()
        self.fences[scope.pipeline_id] = response.json()['fence']

    def verify(self, scope):
        response = self.session.post(self.url, json={
            'action': 'verify', 'pipeline_id': scope.pipeline_id, 'scope': scope.__dict__,
            'lease_owner': self.owner, 'lease_fence': self.fences[scope.pipeline_id],
        }, timeout=10, allow_redirects=False)
        response.raise_for_status()

    def candidate_digest(self, scope):
        response = self.session.post(self.url, json={
            'action': 'candidate_digest', 'pipeline_id': scope.pipeline_id,
            'scope': scope.__dict__, 'lease_owner': self.owner,
            'lease_fence': self.fences[scope.pipeline_id],
        }, timeout=60, allow_redirects=False)
        response.raise_for_status()
        return response.json()

    def reconciliation_progress(self, scope, attempt_id, state, source_lsn=0,
                                stage_ends=None, failure_code=''):
        response = self.session.post(self.url, json={
            'action': 'reconciliation_progress', 'pipeline_id': scope.pipeline_id,
            'scope': scope.__dict__, 'lease_owner': self.owner,
            'lease_fence': self.fences[scope.pipeline_id],
            'attempt_id': attempt_id, 'state': state, 'source_lsn': source_lsn,
            'stage_ends': stage_ends or {}, 'failure_code': failure_code,
        }, timeout=10, allow_redirects=False)
        response.raise_for_status()

    def issue_watermark_certificate(self, scope, proof):
        response = self.session.post(self.url, json={
            'action': 'watermark_certificate', 'pipeline_id': scope.pipeline_id,
            'scope': scope.__dict__, 'lease_owner': self.owner,
            'lease_fence': self.fences[scope.pipeline_id], 'proof': proof,
        }, timeout=30, allow_redirects=False)
        response.raise_for_status()
        return response.json()


class FencedConnect:
    """Check the database lease around each external Connect mutation."""
    def __init__(self, connector, control, authority_scope):
        self.connector, self.control, self.authority_scope = connector, control, authority_scope

    def request(self, *args, **kwargs):
        return self.connector.request(*args, **kwargs)

    def _mutate(self, method, *args):
        self.control.verify(self.authority_scope)
        result = getattr(self.connector, method)(*args)
        self.control.verify(self.authority_scope)
        return result

    def pause(self, scope):
        return self._mutate('pause', scope)

    def configure(self, scope, configuration):
        return self._mutate('configure', scope, configuration)

    def resume(self, scope):
        return self._mutate('resume', scope)


class FencedStore:
    def __init__(self, store, control, scope):
        self.store, self.control, self.scope = store, control, scope

    def prepare(self, scope, columns, primary_key):
        self.control.verify(self.scope)
        result = self.store.prepare(scope, columns, primary_key)
        self.control.verify(self.scope)
        return result

    def storage_state(self, scope):
        return self.store.storage_state(scope)

    def rows(self, *args):
        return self.store.rows(*args)


def _write_password_fenced(control, scope, password):
    control.verify(scope)
    write_password(scope, password)
    control.verify(scope)


def _remove_password_fenced(control, scope):
    control.verify(scope)
    remove_password(scope)
    control.verify(scope)


def reconcile(connection, store, scope, columns, primary_key):
    start = time.monotonic()
    source = postgres.bounded_rows(connection, scope, primary_key)
    destination = store.rows(scope, primary_key)
    def normalized(rows):
        return [canonical({c['name']: convert(normalize_snapshot_row(row)[c['name']], c) for c in columns}) for row in rows]
    left, right = normalized(source), normalized(destination)
    return {'status': 'MATCH' if left == right else 'MISMATCH', 'source_count': len(left),
            'destination_count': len(right), 'limit': 10000,
            'duration_ms': int((time.monotonic() - start)*1000), 'checked_at': datetime.now(timezone.utc).isoformat(),
            'consistency': 'bounded_observation_requires_quiescent_source'}


def _source_offset_initialized(connector, scope):
    offsets = connector.request(scope, '/offsets') or {}
    if not isinstance(offsets, dict):
        return False
    return any(isinstance(entry, dict) and isinstance(entry.get('offset'), dict)
               and type(entry['offset'].get('lsn')) is int
               for entry in offsets.get('offsets', []))


def control_pipeline(item, control, connector, store):
    scope = Scope(**item['scope'])
    previous_scope = item.get('previous_scope')
    if previous_scope and item['desired_state'] == 'STREAMING':
        old_scope = Scope(**previous_scope)
        old_status = connector.request(old_scope, '/status')
        if old_status and (old_status.get('connector', {}).get('state') != 'STOPPED' or old_status.get('tasks')):
            connector.pause(old_scope)
            return 2
    if item['desired_state'] != 'STREAMING':
        if item['desired_state'] == 'STOPPED' and item['observed_state'] == 'STOPPED':
            return
        status = connector.request(scope, '/status')
        if status and (status.get('connector', {}).get('state') != 'STOPPED' or status.get('tasks')):
            connector.pause(scope)
            log.info('CDC_CONTROL_TRANSITION scope=%s action=stop_requested', scope.token)
            return
        if item['desired_state'] == 'PAUSED' and item.get('credential'):
            credential = item['credential']
            configuration = {**item['connection_metadata'], 'password': decrypt_credential(credential['key_version'], credential['ciphertext'])}
            connection = postgres.connect(configuration)
            try:
                health, active_pid, _ = postgres.slot_health(connection, scope, existing=bool(item.get('capture_slot_seen')))
            finally:
                connection.close()
            if health['slot_active']:
                log.info('CDC_CONTROL_TRANSITION scope=%s action=waiting_for_slot active_pid=%s', scope.token, active_pid)
                return
        elif item['desired_state'] == 'PAUSED' and item['observed_state'] != 'RESEED_REQUIRED':
            # A paused active source must supply a credential for physical proof.
            raise CdcError('CDC_SOURCE_UNAVAILABLE')
        _remove_password_fenced(control, scope)
        if item.get('control_suppressed'):
            # A retired or credentialless source can require physical STOP,
            # but its historical persisted intent must not receive callbacks.
            return 300
        target_state = 'STOPPED' if item['desired_state'] == 'STOPPED' else 'PAUSED'
        if item['observed_state'] not in {'RESEED_REQUIRED', target_state}:
            control.update(scope, observed_state=target_state)
            log.info('CDC_CONTROL_TRANSITION scope=%s action=%s', scope.token, target_state.lower())
        return
    if item['observed_state'] == 'RESEED_REQUIRED':
        connector.pause(scope)
        return
    credential = item['credential']
    configuration = {**item['connection_metadata'], 'password': decrypt_credential(credential['key_version'], credential['ciphertext'])}
    connection = postgres.connect(configuration)
    try:
        slot_expected = bool(item.get('capture_slot_seen') or item.get('snapshot_signal', {}).get('status')
                             in {'STARTED', 'SCANNED', 'COMPLETED'})
        columns, primary_key, health = postgres.preflight(connection, scope, existing=slot_expected)
        if item['columns']:
            schema_additions(item['columns'], columns, item['primary_key'], primary_key)
        # This is the Loader adapter; all physical storage creation is centralized.
        needs_prepare = not item['columns'] or item['columns'] != columns
        if not needs_prepare and item.get('generation_state') == 'CANDIDATE':
            storage_state = store.storage_state(scope)
            if storage_state == 'INVALID':
                raise CdcError('CDC_STORAGE_INCOMPATIBLE')
            if storage_state == 'MISSING':
                if (item['checkpoints'] or item.get('snapshot_signal', {}).get('status')
                        in {'STARTED', 'SCANNED', 'COMPLETED'}):
                    raise CdcError('CDC_STORAGE_INCOMPATIBLE')
                needs_prepare = True
        if needs_prepare:
            store.prepare(scope, columns, primary_key)
        current = connector.request(scope, '/status')
        rotated = item['credential_version'] != item['applied_credential_version']
        expected = connector_configuration(scope, configuration)
        applied = connector.request(scope, '/config') if current else {}
        changed = any((applied or {}).get(k) != v for k,v in expected.items())
        if current is None or rotated or changed:
            if current is not None and (current.get('connector', {}).get('state') != 'STOPPED' or current.get('tasks')):
                connector.pause(scope)
                return
            _write_password_fenced(control, scope, configuration['password'])
            connector.configure(scope, configuration)
            control.update(scope, credential_version=item['credential_version'])
            if current is not None:
                connector.resume(scope)
            return
        else:
            # Rewrite on each poll so a late in-flight stale writer is repaired.
            _write_password_fenced(control, scope, configuration['password'])
            if current.get('connector', {}).get('state') in {'PAUSED', 'STOPPED'}:
                connector.resume(scope)
                log.info('CDC_CONTROL_TRANSITION scope=%s action=resume_requested', scope.token)
                return
            elif current.get('connector', {}).get('state') == 'RUNNING' and not current.get('tasks'):
                raise CdcError('CDC_CONNECT_TASK_MISSING')
        if current and any(t.get('state') == 'FAILED' for t in current.get('tasks', [])):
            # Do not repeatedly spawn a task while an old replication session
            # still owns the slot. A failed task with an active slot requires a
            # controlled Connect worker restart; offsets and slot are retained.
            if health['slot_active']:
                raise CdcError('CDC_CONNECT_TASK_ORPHANED')
            # A broker producer timeout can kill the source task after Kafka
            # returns. STOP releases the failed task without deleting its
            # connector, offsets, publication or replication slot. The next
            # controller poll resumes it from its persisted position.
            connector.pause(scope)
            log.info('CDC_CONTROL_TRANSITION scope=%s action=failed_task_stop_requested', scope.token)
            return 2
        if not current or current.get('connector', {}).get('state') != 'RUNNING' or not current.get('tasks') or any(t.get('state') != 'RUNNING' for t in current['tasks']):
            return
        health, _, slot_present = postgres.slot_health(connection, scope, existing=slot_expected)
        if not slot_present:
            return
        offset_initialized = _source_offset_initialized(connector, scope)
        snapshot_started = item.get('snapshot_signal', {}).get('status') in {
            'STARTED', 'SCANNED', 'COMPLETED'}
        capture_ready = bool(health['slot_active'] and offset_initialized and snapshot_started)
        completed = item.get('snapshot_signal', {}).get('status') == 'COMPLETED'
        state = ('STREAMING' if completed and (item['checkpoints'] or
                 item.get('snapshot_signal', {}).get('completed') is True)
                 else item['observed_state'] if item['observed_state'] in
                 {'SNAPSHOTTING', 'STREAMING'} else 'SNAPSHOTTING')
        fields = dict(columns=columns, primary_key=primary_key, credential_version=item['credential_version'],
                      observed_state=state, health=health)
        if health['slot_active'] and not item.get('capture_slot_seen'):
            fields['capture_slot_seen'] = True
        if capture_ready and not item.get('capture_ready'):
            fields['capture_ready'] = True
        control.update(scope, **fields)
        if item['reconcile_requested']:
            if item.get('generation_state') == 'CANDIDATE':
                from .reconciliation import reconcile_candidate
                reconcile_candidate(connection, control, scope, columns, primary_key,
                                    configuration, item.get('reconciliation_attempt', {}))
            else:
                control.update(scope, reconciliation=reconcile(connection, store, scope, columns, primary_key))
    finally:
        connection.close()


def control_one(item, control, connector, store):
    """A failed source or stale callback must not starve other pipelines."""
    scope = Scope(**item['scope'])
    delay = 0
    try:
        control.claim(scope)
        connector = FencedConnect(connector, control, scope)
        store = FencedStore(store, control, scope)
        delay = control_pipeline(item, control, connector, store)
    except CdcError as exc:
        if exc.code in {'CDC_CONNECT_UNAVAILABLE', 'CDC_CONNECT_TRANSITION', 'CDC_CONNECT_TASK_MISSING'}:
            log.warning('CDC_CONTROL_RETRY scope=%s code=%s', scope.token, exc.code)
            return 2
        try:
            if item['desired_state'] == 'STREAMING':
                connector.pause(scope)
            if item['desired_state'] != 'STOPPED' and not item.get('control_suppressed'):
                control.update(scope, error_code=exc.code)
        except Exception as callback_error:
            response=getattr(callback_error, 'response', None)
            log.warning('CDC_CONTROL_REPORT_RETRY scope=%s error_type=%s http_status=%s',
                        scope.token, type(callback_error).__name__, getattr(response, 'status_code', None))
            return 30 if getattr(response, 'status_code', None) == 409 else 0
    except Exception as exc:
        response=getattr(exc, 'response', None)
        code = None
        if response is not None:
            try:
                code = response.json().get('error', {}).get('code')
            except (ValueError, AttributeError, TypeError):
                pass
        log.warning('CDC_CONTROL_RETRY scope=%s error_type=%s http_status=%s code=%s',
                    scope.token, type(exc).__name__, getattr(response, 'status_code', None), code)
        return 30 if getattr(response, 'status_code', None) == 409 else 0
    return delay or 0


class ControllerScheduler:
    """At most four isolated source checks; no poll waits on a slow scope."""
    def __init__(self, workers=4):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='cdc-control')
        self.local = threading.local()
        self.inflight = {}
        self.retry_at = {}
        self.cursor = 0
        self.workers = workers

    def _control(self, item):
        if not hasattr(self.local, 'clients'):
            self.local.clients = (ControlPlane('controller'), ConnectClient(), store_from_env())
        return control_one(item, *self.local.clients)

    def step(self, items):
        now = time.monotonic()
        for key, future in list(self.inflight.items()):
            if future.done():
                del self.inflight[key]
                try:
                    delay = future.result()
                except Exception as exc:
                    log.warning('CDC_CONTROL_WORKER_RETRY scope=%s error_type=%s', key, type(exc).__name__)
                    delay = 0
                if delay:
                    self.retry_at[key] = now + delay
        if not items:
            return
        count = len(items)
        start = self.cursor % count
        self.cursor = (start + 1) % count
        for offset in range(count):
            if len(self.inflight) >= self.workers:
                break
            item = items[(start + offset) % count]
            key = item['scope']['pipeline_id']
            if (key in self.inflight or now < self.retry_at.get(key, 0)
                    or item['desired_state'] == 'STOPPED' and item['observed_state'] == 'STOPPED'):
                continue
            self.inflight[key] = self.pool.submit(self._control, item)


class ResumeOffsets(ConsumerRebalanceListener):
    def __init__(self, consumer, stage, checkpoints, heartbeat_topic=None,
                 notification_topic=None, notification_offset=None):
        self.consumer, self.stage, self.checkpoints = consumer, stage, checkpoints
        self.heartbeat_topic = heartbeat_topic
        self.notification_topic = notification_topic
        self.notification_offset = notification_offset

    def on_partitions_revoked(self, partitions):
        pass

    def on_partitions_assigned(self, partitions):
        beginnings=self.consumer.beginning_offsets(partitions)
        ends=self.consumer.end_offsets(partitions)
        for partition in partitions:
            committed=self.consumer.committed(partition)
            if partition.topic == self.heartbeat_topic:
                # Heartbeats carry no business state. Their expiry must not
                # reset a data checkpoint or falsely require a reseed.
                position = committed if committed is not None else beginnings[partition]
                self.consumer.seek(partition, min(ends[partition], max(beginnings[partition], position)))
                continue
            checkpoint = ({'offset': self.notification_offset}
                          if partition.topic == self.notification_topic
                          and self.notification_offset is not None else
                          self.checkpoints.get(f'{self.stage}:{partition.partition}'))
            position=committed if committed is not None else checkpoint['offset']+1 if checkpoint else 0
            if not beginnings[partition] <= position <= ends[partition]:
                raise CdcError('CDC_KAFKA_RETENTION_LOST')
            self.consumer.seek(partition,position)


MAX_CDC_JSON_BYTES = 2 * 1024 * 1024


def decode_cdc_json(data):
    if len(data) > MAX_CDC_JSON_BYTES:
        raise CdcError('CDC_EVENT_TOO_LARGE')
    value = json.loads(data)
    pending = [(value, 0)]
    visited = 0
    while pending:
        node, depth = pending.pop()
        visited += 1
        if visited > 100000 or depth > 64:
            raise CdcError('CDC_EVENT_TOO_COMPLEX')
        if isinstance(node, dict):
            pending.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            pending.extend((child, depth + 1) for child in node)
    return value


def snapshot_notification(value, scope, partition, offset):
    """Accept only this connector's durable initial-snapshot status record."""
    if not isinstance(value, dict):
        raise CdcError('CDC_SNAPSHOT_NOTIFICATION_INVALID')
    value = value.get('payload', value)
    if (not isinstance(value, dict)
            or value.get('aggregate_type') != 'Initial Snapshot'
            or not isinstance(value.get('additional_data'), dict)
            or value['additional_data'].get('connector_name') != scope.topic('raw')
            or partition != 0 or type(offset) is not int or offset < 0):
        raise CdcError('CDC_SNAPSHOT_NOTIFICATION_INVALID')
    kind = value.get('type')
    if kind not in {'STARTED', 'TABLE_SCAN_COMPLETED', 'COMPLETED', 'ABORTED', 'SKIPPED'}:
        return None  # Progress notifications have no publication authority.
    timestamp = value.get('timestamp')
    if (type(timestamp) is not int and not (
            isinstance(timestamp, str) and timestamp.isdecimal() and len(timestamp) <= 16)):
        raise CdcError('CDC_SNAPSHOT_NOTIFICATION_INVALID')
    if not 0 < int(timestamp) < 10**16:
        raise CdcError('CDC_SNAPSHOT_NOTIFICATION_INVALID')
    try:
        notification_id = str(uuid.UUID(value['id']))
    except (KeyError, ValueError, TypeError):
        raise CdcError('CDC_SNAPSHOT_NOTIFICATION_INVALID') from None
    signal = {'type': kind, 'offset': offset, 'partition': partition,
              'id': notification_id, 'timestamp_ms': int(timestamp)}
    if kind == 'TABLE_SCAN_COMPLETED':
        details = value['additional_data']
        rows = details.get('total_rows_scanned')
        if (details.get('scanned_collection') != f'{scope.schema}.{scope.table}'
                or details.get('status') != 'SUCCEEDED'
                or not isinstance(rows, str) or not rows.isdecimal()
                or len(rows) > 20):
            raise CdcError('CDC_SNAPSHOT_NOTIFICATION_INVALID')
        signal['empty'] = int(rows) == 0
    return signal


class PipelineConsumer:
    def __init__(self, scope, stage, control, store=None, checkpoints=None, snapshot_signal=None):
        self.scope, self.stage, self.control, self.store = scope, stage, control, store
        source_topic = {'normalize': scope.raw_topic, 'transform': scope.topic('normalized'), 'load': scope.topic('transformed')}[stage]
        self.consumer = KafkaConsumer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],
            group_id=f'biavora-cdc-v1-{scope.token}-{stage}', enable_auto_commit=False,
            auto_offset_reset='none', max_poll_records=100, max_partition_fetch_bytes=2097152,
            consumer_timeout_ms=1000, request_timeout_ms=15000, session_timeout_ms=10000)
        self.heartbeat_topic = '__debezium-heartbeat.' + scope.topic('raw') if stage == 'normalize' else None
        self.notification_topic = scope.topic('notification') if stage == 'normalize' else None
        topics = [source_topic] + ([self.heartbeat_topic, self.notification_topic]
                                   if self.heartbeat_topic else [])
        self.offset_resumer = ResumeOffsets(
            self.consumer, stage, checkpoints or {}, self.heartbeat_topic,
            self.notification_topic, (snapshot_signal or {}).get('offset'))
        self.consumer.subscribe(topics, listener=self.offset_resumer)
        self.producer = KafkaProducer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],
            acks='all', enable_idempotence=True, max_in_flight_requests_per_connection=1,
            linger_ms=5, batch_size=131072,
            max_request_size=2097152, retries=5, request_timeout_ms=10000, delivery_timeout_ms=30000,
            value_serializer=lambda value: canonical(value).encode())

    def close(self):
        self.consumer.close()
        self.producer.close(timeout=5)

    def _poison(self, partition, message, event, code):
        event_id = (event.get('event_id') if isinstance(event, dict) else
                    hashlib.sha256(f'{message.topic}:{message.partition}:{message.offset}'.encode()).hexdigest())
        self.producer.send(self.scope.topic('dlq'), safe_dlq(
            self.scope, event_id, code, self.stage,
            datetime.now(timezone.utc).isoformat())).get(timeout=30)
        self.control.update(self.scope, error_code=code)
        self.consumer.commit({partition: OffsetAndMetadata(message.offset+1, '', -1)})
        EVENTS.labels(self.stage, 'dlq').inc()

    def _flush_data_batch(self, partition, prepared, item):
        if not prepared:
            return
        if self.stage == 'load':
            events = [converted for _, _, converted in prepared]
            if len(events) == 1:
                self.store.apply(self.scope, events[0], item['columns'], item['primary_key'])
            else:
                self.store.apply_batch(self.scope, events, item['columns'], item['primary_key'])
        else:
            topic = self.scope.topic('normalized' if self.stage == 'normalize' else 'transformed')
            pending = []
            for _, event, converted in prepared:
                if event is not None:
                    pending.append(self.producer.send(
                        topic, converted, key=canonical(event['primary_key']).encode()))
            for future in pending:
                future.get(timeout=30)
        last = prepared[-1][0]
        lsn = max((event['position']['lsn'] for _, event, _ in prepared if event), default=0)
        if self.stage == 'load':
            previous = item.get('checkpoints', {}).get(f'load:{last.partition}')
            if previous:
                lsn = max(lsn, previous['lsn'])
        crash_scope = os.getenv('CDC_CRASH_AFTER_APPLY_SCOPE_TOKEN', '')
        if (os.getenv('APP_ENV') == 'test'
                and os.getenv('CDC_CRASH_AFTER_APPLY') == self.stage
                and (not crash_scope or crash_scope == self.scope.token)):
            os._exit(86)
        fields = {'checkpoint': {'partition': last.partition, 'offset': last.offset, 'lsn': lsn}}
        if self.stage == 'load':
            fields['snapshot_complete'] = any(event['snapshot_complete']
                                              for _, event, _ in prepared)
        self.control.update(self.scope, **fields)
        self.consumer.commit({partition: OffsetAndMetadata(last.offset+1, '', -1)})
        for _, event, _ in prepared:
            EVENTS.labels(self.stage, event['operation'].lower() if event else 'tombstone').inc()
        latest = next((event for _, event, _ in reversed(prepared) if event), None)
        if latest and latest.get('source_timestamp_ms'):
            LAG.labels(self.stage).set(max(0, time.time()-latest['source_timestamp_ms']/1000))

    def _poll_data_batch(self, partition, messages, item):
        # A PipelineConsumer owns exactly one persisted scope/generation. The
        # input partition supplies a contiguous, bounded range (<= 100 rows).
        prepared = []
        permanent = (CdcError, ValueError, TypeError, KeyError, UnicodeError,
                     RecursionError, OverflowError)
        for message in messages:
            event = None
            try:
                value = decode_cdc_json(message.value) if message.value is not None else None
                if self.stage == 'normalize':
                    key = decode_cdc_json(message.key) if value is not None and message.key else None
                    event = normalize(value, key, self.scope, item['primary_key'], item['schema_version'])
                    if event:
                        ensure_row_images(event, item['columns'])
                    converted = event
                else:
                    if not isinstance(value, dict):
                        raise CdcError('CDC_EVENT_INVALID')
                    event = dict(value)
                    row = event.pop('row', None)
                    validate(event, self.scope, item['primary_key'])
                    converted = transform(event, item['columns'], item['primary_key'], item['schema_version'])
                    if self.stage == 'load' and row != converted['row']:
                        raise CdcError('CDC_TRANSFORM_MISMATCH')
                prepared.append((message, event, converted))
            except permanent as exc:
                # Only the valid prefix may advance. Later records remain
                # unprocessed and the terminal poison is explicitly disposed.
                self._flush_data_batch(partition, prepared, item)
                self._poison(partition, message, event,
                             exc.code if isinstance(exc, CdcError) else 'CDC_EVENT_INVALID')
                return False
        try:
            self._flush_data_batch(partition, prepared, item)
        except BatchConflict as exc:
            self._flush_data_batch(partition, prepared[:exc.index], item)
            message, event, _ = prepared[exc.index]
            self._poison(partition, message, event, exc.code)
            return False
        except CdcError as exc:
            # A whole-batch deterministic storage failure has no safe row
            # prefix; no batch insert or checkpoint occurred.
            message, event, _ = prepared[0]
            self._poison(partition, message, event, exc.code)
            return False
        return True

    def poll(self, item):
        try:
            batches = self.consumer.poll(timeout_ms=200, max_records=100)
        except NoOffsetForPartitionError:
            # kafka-python can expose a newly created notification partition
            # before its rebalance listener supplies a position. The same
            # retained-beginning check applies; never use latest/earliest as
            # an implicit recovery position.
            self.offset_resumer.on_partitions_assigned(list(self.consumer.assignment()))
            return True
        for partition, messages in batches.items():
            data_topic = {'normalize': self.scope.raw_topic,
                          'transform': self.scope.topic('normalized'),
                          'load': self.scope.topic('transformed')}[self.stage]
            if len(messages) > 1 and all(message.topic == data_topic for message in messages):
                if not self._poll_data_batch(partition, messages, item):
                    return False
                continue
            for message in messages:
                event = None
                try:
                    value = decode_cdc_json(message.value) if message.value is not None else None
                    if message.topic == getattr(self, 'notification_topic', None):
                        signal = snapshot_notification(value, self.scope, message.partition, message.offset)
                        if signal is not None:
                            self.control.update(self.scope, snapshot_notification=signal)
                        self.consumer.commit({partition: OffsetAndMetadata(message.offset+1, '', -1)})
                        EVENTS.labels(self.stage, 'notification').inc()
                        continue
                    if message.topic == self.heartbeat_topic:
                        captured = value['ts_ms']
                        if type(captured) is not int or captured <= 0:
                            raise CdcError('CDC_HEARTBEAT_INVALID')
                        self.control.update(self.scope, capture_timestamp_ms=captured)
                        self.consumer.commit({partition: OffsetAndMetadata(message.offset+1, '', -1)})
                        EVENTS.labels(self.stage, 'heartbeat').inc()
                        continue
                    if self.stage == 'normalize':
                        key = decode_cdc_json(message.key) if message.value is not None and message.key else None
                        event = normalize(value, key, self.scope, item['primary_key'], item['schema_version'])
                        if event:
                            ensure_row_images(event, item['columns'])
                            self.producer.send(self.scope.topic('normalized'), event, key=canonical(event['primary_key']).encode()).get(timeout=30)
                    else:
                        if not isinstance(value, dict):
                            raise CdcError('CDC_EVENT_INVALID')
                        event = dict(value)
                        row = event.pop('row', None)
                        validate(event, self.scope, item['primary_key'])
                        converted = transform(event, item['columns'], item['primary_key'], item['schema_version'])
                        if self.stage == 'transform':
                            self.producer.send(self.scope.topic('transformed'), converted, key=canonical(event['primary_key']).encode()).get(timeout=30)
                        else:
                            if row != converted['row']:
                                raise CdcError('CDC_TRANSFORM_MISMATCH')
                            self.store.apply(self.scope, converted, item['columns'], item['primary_key'])
                    lsn = event['position']['lsn'] if event else 0
                    if self.stage == 'load':
                        previous = item['checkpoints'].get(f'load:{message.partition}')
                        if previous:
                            lsn = max(lsn, previous['lsn'])
                    # Fault injection is local-only, explicit, and occurs after
                    # durable side effects but before either checkpoint or ack.
                    crash_scope = os.getenv('CDC_CRASH_AFTER_APPLY_SCOPE_TOKEN', '')
                    if (os.getenv('APP_ENV') == 'test'
                            and os.getenv('CDC_CRASH_AFTER_APPLY') == self.stage
                            and (not crash_scope or crash_scope == self.scope.token)):
                        os._exit(86)
                    fields = {'checkpoint': {'partition': message.partition, 'offset': message.offset, 'lsn': lsn}}
                    if self.stage == 'load':
                        fields['snapshot_complete'] = event['snapshot_complete']
                    self.control.update(self.scope, **fields)
                    self.consumer.commit({partition: OffsetAndMetadata(message.offset+1, '', -1)})
                    EVENTS.labels(self.stage, event['operation'].lower() if event else 'tombstone').inc()
                    if event and event.get('source_timestamp_ms'):
                        LAG.labels(self.stage).set(max(0, time.time()-event['source_timestamp_ms']/1000))
                except (CdcError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError) as exc:
                    code = exc.code if isinstance(exc, CdcError) else 'CDC_EVENT_INVALID'
                    self.producer.send(self.scope.topic('dlq'), safe_dlq(self.scope,
                        event.get('event_id') if isinstance(event, dict) else hashlib.sha256(f'{message.topic}:{message.partition}:{message.offset}'.encode()).hexdigest(), code, self.stage,
                        datetime.now(timezone.utc).isoformat())).get(timeout=30)
                    self.control.update(self.scope, error_code=code)
                    # Terminal poison is durable in the scoped DLQ. Pause after
                    # acknowledgement; never process the rest of this poll.
                    self.consumer.commit({partition: OffsetAndMetadata(message.offset+1, '', -1)})
                    EVENTS.labels(self.stage, 'dlq').inc()
                    return False
        return True


def run(stage):
    if os.getenv('APP_ENV') not in {'test', 'development'}:
        raise CdcError('CDC_TRANSPORT_UNCERTIFIED')
    control, consumers = ControlPlane(stage), {}
    store = store_from_env() if stage == 'load' else None
    scheduler = ControllerScheduler() if stage == 'controller' else None
    start_http_server(int(os.getenv('CDC_METRICS_PORT', '9110')))
    while True:
        try:
            items = control.pipelines()
            HEARTBEAT.labels(stage).set(time.time())
            if stage == 'controller':
                scheduler.step(items)
                time.sleep(2)
                continue
            active = set()
            for item in items:
                scope = Scope(**item['scope'])
                if item['desired_state'] != 'STREAMING' or not item['columns'] or item['observed_state'] in {'PROVISIONING', 'RESEED_REQUIRED', 'FAILED'}:
                    continue
                key = (scope.pipeline_id, scope.generation,
                       scope.configuration_epoch, scope.credential_epoch)
                active.add(key)
                if key not in consumers:
                    consumers[key] = PipelineConsumer(scope, stage, control, store,
                                                      item['checkpoints'], item.get('snapshot_signal'))
                try:
                    continuing = consumers[key].poll(item)
                except (CdcError, OffsetOutOfRangeError):
                    control.update(scope, error_code='CDC_KAFKA_RETENTION_LOST')
                    continuing = False
                if not continuing:
                    consumers.pop(key).close()
            for key in set(consumers) - active:
                consumers.pop(key).close()
        except Exception as exc:
            # Operational exceptions can contain DSNs or Kafka row bytes. Only
            # bounded reason codes are emitted. Close resets uncommitted polls.
            EVENTS.labels(stage, 'retry').inc()
            log.warning('CDC_RETRY stage=%s error_type=%s', stage, type(exc).__name__)
            for consumer in consumers.values():
                consumer.close()
            consumers.clear()
        time.sleep(2 if stage == 'controller' else 0.2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['controller', 'normalize', 'transform', 'load'], required=True)
    run(parser.parse_args().stage)
