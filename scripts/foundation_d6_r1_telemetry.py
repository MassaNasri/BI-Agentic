"""Read-only, bounded CDC transport telemetry for one disposable scope."""
import argparse
import json
import os
import time
import urllib.request

from kafka import KafkaConsumer, KafkaProducer, TopicPartition

from bi_platform_shared.cdc_contract import Scope, validate
from shared.cdc.connect import ConnectClient
from shared.cdc.worker import ControlPlane, ResumeOffsets, decode_cdc_json
from shared.cdc.schema import transform


def main(token, stage, diagnostic_poll, diagnostic_produce):
    item = next(row for row in ControlPlane(stage).pipelines()
                if not token or Scope(**row['scope']).token == token)
    scope = Scope(**item['scope'])
    topics = {
        'raw': scope.raw_topic,
        'normalized': scope.topic('normalized'),
        'transformed': scope.topic('transformed'),
    }
    consumer = KafkaConsumer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],
                             enable_auto_commit=False, request_timeout_ms=8000)
    try:
        parts = {name: TopicPartition(topic, 0) for name, topic in topics.items()}
        beginning = consumer.beginning_offsets(list(parts.values()))
        end = consumer.end_offsets(list(parts.values()))
        offsets = {name: {'beginning': beginning.get(partition),
                          'end': end.get(partition)}
                   for name, partition in parts.items()}
    finally:
        consumer.close()
    sample_transform = {}
    sample_reader = KafkaConsumer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],
                                  enable_auto_commit=False, request_timeout_ms=8000)
    try:
        partition = parts['normalized']
        sample_reader.assign([partition])
        sample_reader.seek(partition, beginning[partition])
        messages = sample_reader.poll(timeout_ms=1000, max_records=1).get(partition, [])
        if messages:
            try:
                event = decode_cdc_json(messages[0].value)
                event.pop('row', None)
                validate(event, scope, item['primary_key'])
                converted = transform(event, item['columns'], item['primary_key'],
                                      item['schema_version'])
                sample_transform = {'status': 'PASS', 'event_id_same':
                                    converted['event_id'] == event['event_id']}
            except Exception as exc:
                sample_transform = {'status': 'ERROR', 'type': type(exc).__name__,
                                    'code': getattr(exc, 'code', '')}
    finally:
        sample_reader.close()
    poll_result = None
    if diagnostic_poll:
        reader = KafkaConsumer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],
                               group_id=f'd6-r1-diagnostic-{scope.token}',
                               enable_auto_commit=False, auto_offset_reset='none',
                               max_poll_records=100, consumer_timeout_ms=1000,
                               request_timeout_ms=15000, session_timeout_ms=10000)
        try:
            reader.subscribe([scope.topic('normalized')],
                             listener=ResumeOffsets(reader, 'transform', {}))
            batch = {}
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline and not batch:
                batch = reader.poll(timeout_ms=1000, max_records=100)
            poll_result = {'counts': {part.topic: len(messages)
                                      for part, messages in batch.items()},
                           'positions': {part.topic: reader.position(part)
                                         for part in reader.assignment()}}
            processed = 0
            started = time.monotonic()
            try:
                for messages in batch.values():
                    for message in messages:
                        event = decode_cdc_json(message.value)
                        event.pop('row', None)
                        validate(event, scope, item['primary_key'])
                        transform(event, item['columns'], item['primary_key'],
                                  item['schema_version'])
                        processed += 1
                poll_result['transformed_in_memory'] = processed
            except Exception as exc:
                poll_result['transform_error_index'] = processed
                poll_result['transform_error_type'] = type(exc).__name__
                poll_result['transform_error_code'] = getattr(exc, 'code', '')
            poll_result['transform_elapsed_seconds'] = round(time.monotonic()-started, 3)
        finally:
            reader.close()
    produce_result = None
    if diagnostic_produce:
        started = time.monotonic()
        producer = KafkaProducer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],
                                 acks='all', enable_idempotence=True,
                                 max_in_flight_requests_per_connection=1,
                                 linger_ms=5, batch_size=131072,
                                 max_request_size=2097152, retries=5,
                                 request_timeout_ms=10000, delivery_timeout_ms=30000,
                                 value_serializer=lambda value: json.dumps(value).encode())
        try:
            metadata = producer.send(f'd6-r1-diagnostic-{scope.token}',
                                     {'probe': True}).get(timeout=30)
            produce_result = {'status': 'PASS', 'offset': metadata.offset,
                              'elapsed_seconds': round(time.monotonic()-started, 3)}
        except Exception as exc:
            produce_result = {'status': 'ERROR', 'type': type(exc).__name__,
                              'elapsed_seconds': round(time.monotonic()-started, 3)}
        finally:
            producer.close(timeout=5)
    try:
        connector = ConnectClient().request(scope, '/status') or {}
        connect_status = {
            'connector': connector.get('connector', {}).get('state'),
            'tasks': [task.get('state') for task in connector.get('tasks', [])],
        }
    except Exception as exc:
        connect_status = {'error_type': type(exc).__name__}
    try:
        metrics = urllib.request.urlopen('http://localhost:9110/metrics', timeout=2).read().decode()
        worker_metrics = [line for line in metrics.splitlines()
                          if line.startswith(('biavora_cdc_events_total',
                                              'biavora_cdc_worker_heartbeat_seconds'))]
    except Exception as exc:
        worker_metrics = [type(exc).__name__]
    print(json.dumps({
        'topics': offsets,
        'checkpoints': {stage: item.get('checkpoints', {}).get(f'{stage}:0')
                        for stage in ('normalize', 'transform', 'load')},
        'generation': scope.generation,
        'desired_state': item.get('desired_state'),
        'observed_state': item.get('observed_state'),
        'connector_status': connect_status,
        'sample_transform': sample_transform,
        'worker_metrics': worker_metrics,
        'diagnostic_poll': poll_result,
        'diagnostic_produce': produce_result,
    }), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--token', default='')
    parser.add_argument('--stage', choices=('normalize', 'transform', 'load'),
                        default='normalize')
    parser.add_argument('--diagnostic-poll', action='store_true')
    parser.add_argument('--diagnostic-produce', action='store_true')
    args = parser.parse_args()
    main(args.token, args.stage, args.diagnostic_poll, args.diagnostic_produce)
