"""Isolated D4 Kafka injection and offset introspection; never prints row images."""
import argparse
import copy
import json
import os

from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from bi_platform_shared.cdc_contract import Scope, canonical
from shared.cdc.worker import ControlPlane
from foundation_d_kafka_probe import records


def main(token, action, stage):
    item = next(item for item in ControlPlane(stage).pipelines()
                if Scope(**item['scope']).token == token)
    scope = Scope(**item['scope'])
    topic = scope.topic('transformed')
    consumer = KafkaConsumer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],
                             group_id=f'biavora-cdc-v1-{token}-load',enable_auto_commit=False)
    partition = TopicPartition(topic,0)
    committed = consumer.committed(partition)
    if action == 'fast_state':
        end=consumer.end_offsets([partition]).get(partition,0)
        consumer.close()
        print(json.dumps({'transformed_end_offset':end,'committed_offset':committed,
                          'load_checkpoint':item['checkpoints'].get('load:0')}),flush=True)
        return
    consumer.close()
    if action == 'dlq':
        failures=[json.loads(message.value) for message in records(scope.topic('dlq')) if message.value]
        print(json.dumps({'reasons':[failure.get('reason') for failure in failures],
                          'field_names':[sorted(failure) for failure in failures],
                          'safe_fields_only':all(set(failure)<=set(('contract','workspace_id','source_id',
                          'pipeline_id','dataset_id','schema','table','event_id','reason',
                          'stage','retry_count','timestamp'))
                          for failure in failures)}),flush=True)
        return
    messages = records(topic)
    if action == 'state':
        print(json.dumps({'transformed_records':len(messages),'last_offset':messages[-1].offset if messages else -1,
                          'committed_offset':committed,
                          'load_checkpoint':item['checkpoints'].get('load:0')}),flush=True)
        return
    if action == 'publication_replay':
        message = next(message for message in messages if message.value and
                       json.loads(message.value).get('snapshot_complete') is True)
        value=message.value
    elif action == 'conflict':
        message = next(message for message in reversed(messages) if message.value and
                       json.loads(message.value).get('primary_key') == {'id':4} and
                       json.loads(message.value).get('operation') == 'INSERT')
        value=json.loads(message.value)
        value['after']['amount']='999.0000'
        value['row']['amount']='999.0000'
        value=canonical(value).encode()
    else:
        raise ValueError(action)
    producer=KafkaProducer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],
                           acks='all',enable_idempotence=True)
    metadata=producer.send(topic,key=message.key,value=value).get(timeout=15)
    producer.close()
    print(json.dumps({'action':action,'prior_committed_offset':committed,
                      'injected_offset':metadata.offset,'partition':metadata.partition}),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--token',required=True)
    parser.add_argument('--stage',choices=['load','normalize'],default='load')
    parser.add_argument('action',choices=['state','fast_state','dlq','publication_replay','conflict'])
    args=parser.parse_args()
    main(args.token,args.action,args.stage)
