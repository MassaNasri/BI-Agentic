"""Observe the first snapshot row without joining or changing a worker group."""
import argparse
import json
import os
import time

from kafka import KafkaConsumer, TopicPartition

from bi_platform_shared.cdc_contract import Scope


def main(scope_data, seconds):
    scope = Scope(**json.loads(scope_data))
    consumer = KafkaConsumer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],
                             enable_auto_commit=False, group_id=None,
                             auto_offset_reset='none', request_timeout_ms=15000)
    partition = TopicPartition(scope.raw_topic, 0)
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            if partition not in consumer.assignment():
                consumer.assign([partition])
                consumer.seek_to_beginning(partition)
            for records in consumer.poll(timeout_ms=500, max_records=1).values():
                for record in records:
                    if record.value:
                        value = json.loads(record.value)
                        if value.get('op') == 'r':
                            print(json.dumps({'first_snapshot_offset': record.offset,
                                              'source_snapshot': value.get('source', {}).get('snapshot')}),
                                  flush=True)
                            return
            time.sleep(0.1)
        raise TimeoutError('first snapshot row not observed')
    finally:
        consumer.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', required=True)
    parser.add_argument('--seconds', type=int, default=180)
    args = parser.parse_args()
    main(args.scope, args.seconds)
