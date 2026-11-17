"""Bounded read-only scan of retained CDC Kafka records for fixture secrets."""

import argparse
import json
import os
from pathlib import Path
import time

from kafka import KafkaConsumer, TopicPartition


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    env_file = Path(args.env_file)
    values = {}
    for line in env_file.read_text(encoding='utf-8').splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        if (len(value) >= 12 and any(marker in key.upper()
                for marker in ('PASSWORD', 'SECRET', 'TOKEN', 'KEY'))):
            values[key] = value.encode('utf-8')
    consumer = KafkaConsumer(bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS',
                                                       'kafka:9092'),
                             group_id=None, enable_auto_commit=False,
                             consumer_timeout_ms=1000)
    matches = []
    records = 0
    try:
        topics = sorted(topic for topic in consumer.topics()
                        if topic.startswith('biavora.cdc.v1.'))
        partitions = [TopicPartition(topic, partition)
                      for topic in topics
                      for partition in sorted(consumer.partitions_for_topic(topic) or [])]
        consumer.assign(partitions)
        beginning = consumer.beginning_offsets(partitions)
        ends = consumer.end_offsets(partitions)
        for partition in partitions:
            consumer.seek(partition, beginning[partition])
        outstanding = set(partitions)
        deadline = time.monotonic() + 90
        while outstanding and time.monotonic() < deadline:
            batches = consumer.poll(timeout_ms=1000, max_records=1000)
            for partition, messages in batches.items():
                for message in messages:
                    records += 1
                    content = (message.key or b'') + (message.value or b'')
                    matches += [{'topic': partition.topic, 'key': key}
                                for key, value in values.items() if value in content]
            outstanding = {partition for partition in partitions
                           if consumer.position(partition) < ends[partition]}
        summary = {'status': 'PASS' if not matches and not outstanding else 'FAIL',
                   'topics_scanned': len(topics), 'partitions_scanned': len(partitions),
                   'records_scanned': records, 'incomplete_partitions': len(outstanding),
                   'matches': matches}
    finally:
        consumer.close()
    path = env_file.parent / f'd5-r4b-kafka-secret-scan-{args.run_id}.json'
    path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(path), **summary}), flush=True)
    if summary['status'] != 'PASS':
        raise SystemExit(1)
