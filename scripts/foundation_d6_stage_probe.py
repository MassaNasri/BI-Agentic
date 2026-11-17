"""Read-only stage offsets for the isolated D6 baseline; prints no row data."""
import argparse
import json
import os

from kafka import KafkaConsumer, TopicPartition

from bi_platform_shared.cdc_contract import Scope
from shared.cdc.worker import ControlPlane


def main(token):
    item = next(item for item in ControlPlane('load').pipelines()
                if Scope(**item['scope']).token == token)
    scope = Scope(**item['scope'])
    topics = {
        'raw': scope.raw_topic,
        'normalized': scope.topic('normalized'),
        'transformed': scope.topic('transformed'),
    }
    consumer = KafkaConsumer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],
                             enable_auto_commit=False, request_timeout_ms=15000)
    try:
        partitions = {name: TopicPartition(topic, 0) for name, topic in topics.items()}
        ends = consumer.end_offsets(list(partitions.values()))
        print(json.dumps({
            'ends': {name: ends.get(partition, 0)
                     for name, partition in partitions.items()},
            'checkpoints': {stage: item['checkpoints'].get(f'{stage}:0')
                            for stage in ('normalize', 'transform', 'load')},
            'observed_state': item.get('observed_state'),
            'snapshot_complete': item.get('snapshot_complete'),
        }), flush=True)
    finally:
        consumer.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--token', required=True)
    main(parser.parse_args().token)
