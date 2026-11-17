"""Bounded raw and stage audit for one disposable D6 scope; prints no payload."""
import argparse
from collections import Counter
import json

from bi_platform_shared.cdc_contract import Scope
from foundation_d_kafka_probe import records


def main(scope_data, writer_from_ms, writer_to_ms):
    scope = Scope(**json.loads(scope_data))
    raw = records(scope.raw_topic)
    events = [(message, json.loads(message.value)) for message in raw if message.value]
    snapshots = [message for message, value in events if value.get('op') == 'r']
    notifications = [(message, json.loads(message.value))
                     for message in records(scope.topic('notification')) if message.value]
    ops = Counter(value.get('op') for _, value in events)
    last_offsets = [message.offset for message, value in events
                    if value.get('op') == 'r' and value.get('source', {}).get('snapshot') == 'last']
    result = {
        'raw_records': len(raw),
        'snapshot_rows': len(snapshots),
        'operations': {name: ops[name] for name in ('r', 'c', 'u', 'd')},
        'tombstones': sum(message.value is None for message in raw),
        'snapshot_last_offsets': last_offsets,
        'snapshot_kafka_first_ms': min((message.timestamp for message in snapshots), default=None),
        'snapshot_kafka_last_ms': max((message.timestamp for message in snapshots), default=None),
        'streaming_kafka_last_ms': max(
            (message.timestamp for message, value in events
             if value.get('op') in ('c', 'u', 'd')), default=None),
        'snapshot_output_overlapped_writer': any(
            writer_from_ms <= message.timestamp <= writer_to_ms for message in snapshots),
        'wal_after_snapshot': bool(last_offsets) and any(
            message.offset > max(last_offsets) and value.get('op') in ('c', 'u', 'd')
            for message, value in events),
        'normalized_records': len(records(scope.topic('normalized'))),
        'transformed_records': len(records(scope.topic('transformed'))),
        'dlq_records': len(records(scope.topic('dlq'))),
        'snapshot_started_notification_ms': next(
            (message.timestamp for message, value in notifications
             if value.get('type') == 'STARTED'), None),
        'snapshot_completed_notification_ms': next(
            (message.timestamp for message, value in notifications
             if value.get('type') == 'TABLE_SCAN_COMPLETED'), None),
    }
    print(json.dumps(result), flush=True)
    assert result['snapshot_rows'] == 5000
    assert result['snapshot_output_overlapped_writer']
    assert result['wal_after_snapshot']
    assert all(result['operations'][op] > 0 for op in ('c', 'u', 'd'))
    assert result['dlq_records'] == 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', required=True)
    parser.add_argument('--writer-from-ms', type=int, required=True)
    parser.add_argument('--writer-to-ms', type=int, required=True)
    args = parser.parse_args()
    main(args.scope, args.writer_from_ms, args.writer_to_ms)
