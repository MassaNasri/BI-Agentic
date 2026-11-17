"""Read-only D4 storage introspection and exact-replay/conflict probe in Loader fixture."""
import argparse
import copy
import json
import time

from kafka import KafkaConsumer, KafkaProducer, TopicPartition

from bi_platform_shared.cdc_contract import CdcError, Scope
from shared.cdc.clickhouse import store_from_env
from shared.cdc.worker import ControlPlane
from foundation_d_kafka_probe import records


def main(token, action):
    item = next(item for item in ControlPlane('load').pipelines()
                if Scope(**item['scope']).token == token)
    scope = Scope(**item['scope'])
    store = store_from_env()
    versions, view = store.names(scope)
    metadata = list(store.client.query(
        "SELECT name, engine, sorting_key, create_table_query FROM system.tables "
        "WHERE database = {database:String} AND name IN ({versions:String}, {view:String})",
        parameters={'database': store.database, 'versions': f'cdc_{token}_versions',
                    'view': f'cdc_{token}_current'}).named_results())
    assert len(metadata) == 2
    event = next(json.loads(message.value) for message in records(scope.topic('transformed'))
                 if message.value and json.loads(message.value)['operation'] == 'SNAPSHOT')
    if action == 'physical_duplicate':
        chosen = next(json.loads(message.value) for message in reversed(records(scope.topic('transformed')))
                      if message.value and json.loads(message.value)['primary_key'] == {'id': 4}
                      and json.loads(message.value)['operation'] == 'INSERT')
        before=store.client.query(f'SELECT count() FROM {versions}').result_rows[0][0]
        row={**chosen['row'],'_cdc_version':chosen['version'],'_cdc_deleted':0,
             '_cdc_event_id':chosen['event_id']}
        store.client.command(f'SYSTEM STOP MERGES {versions}')
        try:
            store.client.raw_insert(versions,insert_block=json.dumps(row).encode(),fmt='JSONEachRow')
            after=store.client.query(f'SELECT count() FROM {versions}').result_rows[0][0]
            assert after==before+1
            assert store.apply(scope,chosen,item['columns'],item['primary_key']) is False
            logical=store.client.query(f'SELECT count() FROM {view} WHERE id=4').result_rows[0][0]
            assert logical==1
        finally:
            store.client.command(f'SYSTEM START MERGES {versions}')
        print(json.dumps({'operator_injected_exact_physical_duplicate':True,
                          'physical_before':before,'physical_after':after,
                          'logical_key_rows':logical,'loader_replay_skipped':True}),flush=True)
        return
    if action in {'replay', 'replay_typed'}:
        target_id = 4 if action == 'replay' else 7
        events = []
        seen = set()
        for message in records(scope.topic('transformed')):
            if not message.value:
                continue
            payload = json.loads(message.value)
            if payload['primary_key'].get('id') == target_id and payload['event_id'] not in seen:
                events.append(message)
                seen.add(payload['event_id'])
        operations = [json.loads(message.value)['operation'] for message in events]
        assert operations == (['INSERT','UPDATE','UPDATE','DELETE','INSERT'] if action == 'replay'
                              else ['SNAPSHOT','UPDATE','DELETE']), operations
        store.client.command(f'SYSTEM STOP MERGES {versions}')
        try:
            before = store.client.query(f'SELECT count() FROM {versions}').result_rows[0][0]
            producer = KafkaProducer(bootstrap_servers=__import__('os').environ['KAFKA_BOOTSTRAP_SERVERS'],
                                     acks='all',enable_idempotence=True)
            for _ in range(2):
                for message in reversed(events):
                    metadata = producer.send(scope.topic('transformed'), key=message.key,
                                             value=message.value).get(timeout=15)
            producer.close()
            consumer = KafkaConsumer(bootstrap_servers=__import__('os').environ['KAFKA_BOOTSTRAP_SERVERS'],
                                     group_id=f'biavora-cdc-v1-{scope.token}-load', enable_auto_commit=False)
            partition = TopicPartition(scope.topic('transformed'), metadata.partition)
            deadline = time.monotonic()+90
            committed = None
            while time.monotonic()<deadline:
                committed = consumer.committed(partition)
                if committed is not None and committed > metadata.offset:
                    break
                time.sleep(1)
            consumer.close()
            assert committed is not None and committed > metadata.offset
            after = store.client.query(f'SELECT count() FROM {versions}').result_rows[0][0]
        finally:
            store.client.command(f'SYSTEM START MERGES {versions}')
        if before != after:
            identity_counts=list(store.client.query(
                f'SELECT id,toString(_cdc_version) AS version,_cdc_event_id,count() AS n FROM {versions} '
                'GROUP BY id,version,_cdc_event_id ORDER BY id,version').named_results())
            print(json.dumps({'unexpected_before':before,'unexpected_after':after,
                              'identity_counts':identity_counts},default=str),flush=True)
        assert before == after, 'exact replays must be physically skipped'
        counts = list(store.client.query(f'SELECT _cdc_deleted, count() AS n FROM {versions} '
                                          f'WHERE id={target_id} GROUP BY _cdc_deleted').named_results())
        print(json.dumps({'reverse_duplicate_deliveries':len(events)*2,
                          'loader_committed_offset':committed,'physical_rows_before':before,
                          'physical_rows_after':after,'target_versions':counts,
                          'physical_replay_skipped':True}),flush=True)
        return
    before = store.client.query(f'SELECT count() FROM {versions}').result_rows[0][0]
    assert store.apply(scope, event, item['columns'], item['primary_key']) is False
    changed = copy.deepcopy(event)
    changed['row']['amount'] = '999.0000'
    try:
        store.apply(scope, changed, item['columns'], item['primary_key'])
    except CdcError as exc:
        assert exc.code == 'CDC_VERSION_CONFLICT'
    else:
        raise AssertionError('equal-version changed payload was accepted')
    after = store.client.query(f'SELECT count() FROM {versions}').result_rows[0][0]
    assert before == after
    print(json.dumps({'engine': next(m['engine'] for m in metadata if m['name'].endswith('_versions')),
                      'sorting_key': next(m['sorting_key'] for m in metadata if m['name'].endswith('_versions')),
                      'view_engine': next(m['engine'] for m in metadata if m['name'].endswith('_current')),
                      'view_uses_final': ' FINAL ' in next(m['create_table_query'].upper() for m in metadata
                                                       if m['name'].endswith('_current')),
                      'view_sql': next(m['create_table_query'] for m in metadata if m['name'].endswith('_current')),
                      'identical_replay_skipped': True, 'equal_version_conflict_rejected': True,
                      'physical_rows_unchanged': before == after}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--token', required=True)
    parser.add_argument('--action',choices=['inspect','replay','replay_typed','physical_duplicate'],default='inspect')
    args=parser.parse_args()
    main(args.token,args.action)
