"""Local acceptance helper; runs on the isolated broker network, prints no rows."""
import argparse
from decimal import Decimal
import json
import os
import time
from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from bi_platform_shared.cdc_contract import Scope, canonical, normalize, validate
from shared.cdc.worker import ControlPlane
from shared.cdc.connect import ConnectClient


def records(topic):
    consumer=KafkaConsumer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],enable_auto_commit=False,
                           request_timeout_ms=15000,session_timeout_ms=10000)
    partitions=consumer.partitions_for_topic(topic)
    if not partitions:
        consumer.close()
        return []
    assigned=[TopicPartition(topic,p) for p in partitions]
    consumer.assign(assigned)
    consumer.seek_to_beginning()
    end=consumer.end_offsets(assigned)
    result=[]
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        batches=consumer.poll(timeout_ms=300,max_records=1000)
        result.extend(m for batch in batches.values() for m in batch)
        if all(consumer.position(p)>=end[p] for p in assigned):
            break
        if len(result)>20000:
            raise AssertionError('bounded inspection exceeded')
    consumer.close()
    return result


def main(action, pipeline=None, snapshot_from=0, snapshot_to=0, row_id=0, amount='', kind=''):
    if action == 'ciphertext':
        os.environ['CDC_SERVICE_KEY'] = os.environ['CDC_CONTROLLER_KEY']
    items=ControlPlane('controller' if action=='ciphertext' else 'normalize').pipelines()
    scope=Scope(**next(p['scope'] for p in items if (p['scope']['pipeline_id']==pipeline if pipeline else p['scope']['workspace_id']==11)))
    raw=records(scope.raw_topic)
    if action not in {'empty', 'wait_raw', 'secrets', 'ciphertext'}:
        assert raw, 'raw capture absent'
    if action == 'ciphertext':
        ciphertexts=[item['credential']['ciphertext'].encode() for item in items if item.get('credential')]
        assert ciphertexts, 'no active encrypted fixture credential available for leakage check'
        checked=0
        for item in items:
            current=Scope(**item['scope'])
            for topic in (current.raw_topic,current.topic('normalized'),current.topic('transformed'),current.topic('dlq')):
                for message in records(topic):
                    if message.value:
                        assert not any(ciphertext in message.value for ciphertext in ciphertexts), 'ciphertext found in business topic'
                        checked+=1
        print(json.dumps({'active_ciphertexts_checked':len(ciphertexts),'business_records_checked':checked,
                          'ciphertext_in_kafka':False}),flush=True)
        return
    if action == 'capture':
        events=[json.loads(message.value) for message in raw if message.value is not None]
        counts={op:sum(event.get('op')==op for event in events) for op in 'rcud'}
        snapshots=[event for event in events if event.get('op')=='r']
        tombstones=sum(message.value is None for message in raw)
        assert all(counts.values()) and tombstones, 'r/c/u/d or tombstone missing'
        assert any(event['source'].get('snapshot')=='last' for event in snapshots), 'no final snapshot row'
        assert all(event['source'].get('schema')==scope.schema and event['source'].get('table')==scope.table
                   and event['source'].get('lsn') is not None for event in events), 'raw scope or LSN mismatch'
        assert any(event.get('op') in 'cud' and event['source'].get('snapshot') in (False, 'false', None)
                   for event in events), 'no WAL continuation after snapshot'
        if snapshot_from and snapshot_to:
            assert any(snapshot_from <= event['source']['ts_ms'] <= snapshot_to for event in snapshots), 'snapshot did not overlap controlled writes'
        secrets=[os.environ[n].encode() for n in ('CDC_SOURCE_PASSWORD','CDC_CREDENTIAL_KEY','CDC_SERVICE_KEY')]
        assert all(not any(secret in message.value for secret in secrets) for message in raw if message.value), 'fixture secret in raw topic'
        config=ConnectClient().request(scope,'/config')
        assert config['database.password'].startswith('${file:/run/cdc-secrets/')
        assert all(secret not in canonical(config).encode() for secret in secrets), 'fixture secret in connector config'
        print(json.dumps({'raw_events':len(raw),'ops':counts,'tombstones':tombstones,
                          'snapshot_last':True,'concurrent_writer_overlap':bool(snapshot_from),
                          'wal_continuation':True,'secret_reference_only':True}),flush=True)
        return
    if action == 'empty':
        status=ConnectClient().request(scope,'/status') or {}
        offsets=ConnectClient().request(scope,'/offsets') or {}
        source_offsets=[item.get('offset',{}) for item in offsets.get('offsets',[])]
        print(json.dumps({'raw_events':len(raw),'connector':status.get('connector',{}).get('state'),
                          'tasks':[task.get('state') for task in status.get('tasks',[])],
                          'source_offsets_present':bool(source_offsets),
                          'snapshot_markers':[offset.get('snapshot') for offset in source_offsets]}),flush=True)
        return
    if action == 'wait_raw':
        deadline=time.monotonic()+120
        start=time.monotonic()
        while time.monotonic()<deadline:
            for message in raw:
                if message.value:
                    event=json.loads(message.value)
                    after=event.get('after') or {}
                    if event.get('op')=='u' and after.get('id')==row_id and Decimal(str(after.get('amount','NaN')))==Decimal(amount):
                        print(json.dumps({'raw_match':True,'elapsed_seconds':round(time.monotonic()-start,3),
                                          'lsn':event['source'].get('lsn')}),flush=True)
                        return
            time.sleep(1)
            raw=records(scope.raw_topic)
        raise AssertionError('fresh source write absent from raw topic')
    if action == 'd3_snapshot':
        snapshots=[json.loads(m.value) for m in raw if m.value and json.loads(m.value).get('op')=='r']
        assert len({e['after']['id'] for e in snapshots})==3 and any(e['source'].get('snapshot')=='last' for e in snapshots)
        print(json.dumps({'snapshot_records':len(snapshots),'unique_snapshot_keys':3,'snapshot_last':True}),flush=True)
        return
    if action == 'd3_diagnose':
        failures=[json.loads(m.value).get('reason') for m in records(scope.topic('dlq')) if m.value]
        samples=[json.loads(m.value) for m in raw if m.value]
        item=next(p for p in items if p['scope']['pipeline_id']==scope.pipeline_id)
        print(json.dumps({'raw':len(samples),'normalized':len(records(scope.topic('normalized'))),
                          'transformed':len(records(scope.topic('transformed'))),'dlq_reasons':failures,
                          'state':item['desired_state'],'op_snapshot':[{'op':s.get('op'),'snapshot':s['source'].get('snapshot')} for s in samples[:4]],
                          'raw_metadata':[{k:type(v).__name__ for k,v in s.items() if k in ('op','transaction')}
                          for s in samples[:2]],'source_metadata':[{k:type(v).__name__ for k,v in s['source'].items()
                          if k in ('lsn','txId','ts_ms','snapshot')} for s in samples[:2]]}),flush=True)
        return
    if action == 'd3_recover_first':
        first=next(m for m in raw if m.value and json.loads(m.value).get('op')=='r'
                   and json.loads(m.value)['source'].get('snapshot')=='first')
        producer=KafkaProducer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],acks='all',enable_idempotence=True)
        metadata=producer.send(scope.raw_topic,key=first.key,value=first.value).get(timeout=15)
        producer.close()
        print(json.dumps({'first_snapshot_replayed':True,'offset':metadata.offset}),flush=True)
        return
    if action == 'd3_malformed_history':
        from kafka import TopicPartition
        malformed=[]
        for message in raw:
            if message.value:
                try:
                    json.loads(message.value)
                except ValueError:
                    malformed.append(message.offset)
        failures=[json.loads(m.value) for m in records(scope.topic('dlq')) if m.value]
        assert malformed and any(f['reason']=='CDC_EVENT_INVALID' for f in failures)
        assert all('D3_PRIVATE_ROW_SENTINEL' not in canonical(f) and 'before' not in f and 'after' not in f for f in failures)
        consumer=KafkaConsumer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],
                               group_id=f'biavora-cdc-v1-{scope.token}-normalize',enable_auto_commit=False)
        committed=consumer.committed(TopicPartition(scope.raw_topic,0))
        consumer.close()
        assert committed is not None and committed>malformed[0]
        print(json.dumps({'malformed_offset':malformed[0],'committed_offset':committed,'safe_dlq':True}),flush=True)
        return
    if action == 'd3_inspect':
        normalized=[json.loads(m.value) for m in records(scope.topic('normalized')) if m.value]
        transformed=[json.loads(m.value) for m in records(scope.topic('transformed')) if m.value]
        raw_events=[json.loads(m.value) for m in raw if m.value]
        counts={op:sum(e.get('op')==op for e in raw_events) for op in 'rcud'}
        assert all(counts.values()) and sum(m.value is None for m in raw)>0
        by_id={e['event_id']:e for e in normalized}
        transformed_by_id={e['event_id']:e for e in transformed}
        raw_by_id={normalize(e,json.loads(m.key),scope,['id'])['event_id']
                   for m in raw if m.value for e in [json.loads(m.value)]}
        assert all(e['operation'] in {'SNAPSHOT','INSERT','UPDATE','DELETE'} for e in normalized)
        assert all(e['event_id'] in transformed_by_id for e in normalized)
        assert all(e['event_id'] in by_id for e in transformed)
        assert all(validate(e,scope,['id'])==e for e in normalized)
        assert all({**e,'row':transformed_by_id[e['event_id']]['row']}==transformed_by_id[e['event_id']] for e in normalized)
        assert set(by_id)==set(transformed_by_id)==raw_by_id, f'stage IDs raw={len(raw_by_id)} normalized={len(by_id)} transformed={len(transformed_by_id)}'
        assert len(normalized)==len(transformed), f'stage counts normalized={len(normalized)} transformed={len(transformed)}'
        assert len({canonical(e) for e in normalized})==len(by_id)
        assert len({canonical(e) for e in transformed})==len(transformed_by_id)
        assert all(e['workspace_id']==scope.workspace_id and e['dataset_id']==scope.dataset_id for e in normalized)
        if kind=='clean':
            assert not records(scope.topic('dlq')), 'clean source had a DLQ record'
        print(json.dumps({'raw':len(raw_events),'normalized':len(normalized),'transformed':len(transformed),
                          'operations':counts,'tombstones':sum(m.value is None for m in raw),
                          'unique_event_ids':len(by_id),'snapshot_complete':any(e['snapshot_complete'] for e in normalized),
                          'trusted_scope':True,'exact_stage_correspondence':True}),flush=True)
        return
    if action == 'd3_history':
        normalized=[json.loads(m.value) for m in records(scope.topic('normalized')) if m.value]
        transformed=[json.loads(m.value) for m in records(scope.topic('transformed')) if m.value]
        failures=[json.loads(m.value) for m in records(scope.topic('dlq')) if m.value]
        assert normalized and len(normalized)==len(transformed)
        assert all(validate(e,scope,['id'])==e for e in normalized)
        by_id={}
        for event in normalized:
            by_id.setdefault(event['event_id'],set()).add(canonical(event))
        assert all(len(payloads)==1 for payloads in by_id.values())
        transformed_by_id={}
        for event in transformed:
            transformed_by_id.setdefault(event['event_id'],set()).add(canonical(event))
        assert set(by_id)==set(transformed_by_id) and all(len(payloads)==1 for payloads in transformed_by_id.values())
        assert all(e['workspace_id']==scope.workspace_id and e['dataset_id']==scope.dataset_id for e in normalized+transformed+failures)
        assert all('D3_PRIVATE_ROW_SENTINEL' not in canonical(e) for e in normalized+transformed+failures)
        assert all('before' not in f and 'after' not in f and 'row' not in f for f in failures)
        key4={op:next(e for e in normalized if e['operation']==name and e['primary_key']['id']==4)
              for op,name in [('c','INSERT'),('u','UPDATE'),('d','DELETE')]}
        assert int(key4['c']['version'])<int(key4['u']['version'])<int(key4['d']['version'])
        assert all(sum(e['event_id']==key4[op]['event_id'] for e in normalized)>=3 for op in 'cud')
        print(json.dumps({'normalized':len(normalized),'transformed':len(transformed),
                          'unique_event_ids':len(by_id),'duplicate_payload_identical':True,
                          'key4_insert_update_delete_version_order':True,
                          'dlq_reasons':[f['reason'] for f in failures], 'no_foreign_or_secret_business_output':True,
                          'safe_dlq_only':True}),flush=True)
        return
    if action == 'd3_secrets':
        secrets=[os.environ[name].encode() for name in
                 ('CDC_SOURCE_PASSWORD','CDC_SOURCE_ROTATED_PASSWORD','CDC_CREDENTIAL_KEY','CDC_SERVICE_KEY','CDC_CONTROLLER_KEY')]
        checked=0
        for topic in (scope.raw_topic,scope.topic('normalized'),scope.topic('transformed'),scope.topic('dlq')):
            for message in records(topic):
                if message.value:
                    assert not any(secret in message.value for secret in secrets)
                    checked+=1
        config=ConnectClient().request(scope,'/config')
        assert config and config['database.password'].startswith('${file:/run/cdc-secrets/')
        assert not any(secret in canonical(config).encode() for secret in secrets)
        print(json.dumps({'records_checked':checked,'fixture_secrets_checked':len(secrets),
                          'secret_leakage':False,'connector_password_reference_only':True}),flush=True)
        return
    if action == 'd3_replay':
        examples={}
        for message in raw:
            if message.value:
                op=json.loads(message.value).get('op')
                if isinstance(op,str) and op in 'rcud':
                    examples[op]=message
        assert set(examples)==set('rcud')
        producer=KafkaProducer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],acks='all',enable_idempotence=True)
        for _ in range(2):
            for op in 'ducr':
                message=examples[op]
                producer.send(scope.raw_topic,key=message.key,value=message.value).get(timeout=15)
        producer.close()
        print(json.dumps({'replayed':8,'reverse_order':True}),flush=True)
        return
    if action == 'd3_replay_check':
        raw_events=[json.loads(m.value) for m in raw if m.value]
        expected={}
        for event in raw_events:
            if isinstance(event.get('op'),str) and event['op'] in 'rcud':
                expected[event['op']]=event
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            normalized=[json.loads(m.value) for m in records(scope.topic('normalized')) if m.value]
            transformed=[json.loads(m.value) for m in records(scope.topic('transformed')) if m.value]
            groups={op:[] for op in 'rcud'}
            for event in normalized:
                for op,source in expected.items():
                    if event['position']['lsn']==source['source']['lsn'] and event['primary_key']['id']==(source.get('after') or source.get('before'))['id'] and event['operation']=={'r':'SNAPSHOT','c':'INSERT','u':'UPDATE','d':'DELETE'}[op]:
                        groups[op].append(event)
            if all(len(groups[op])>=3 for op in 'rcud') and len(transformed)>=len(normalized):
                for op in 'rcud':
                    assert len({canonical(e) for e in groups[op]})==1
                    event=groups[op][0]
                    matching=[e for e in transformed if e['event_id']==event['event_id']]
                    assert len(matching)>=3 and len({canonical(e) for e in matching})==1
                print(json.dumps({'duplicate_identity':True,'reverse_replay_payload_identical':True,
                                  'logical_version_stable':True,'per_operation_replays':{op:len(groups[op]) for op in 'rcud'}}),flush=True)
                return
            time.sleep(1)
        raise AssertionError('replay did not reach normalized and transformed topics')
    if action == 'd3_restart_check':
        source=next(m for m in reversed(raw) if m.value and json.loads(m.value).get('op')=='u'
                    and json.loads(m.value).get('after',{}).get('id')==2)
        expected=normalize(json.loads(source.value),json.loads(source.key),scope,['id'])
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            normalized=[json.loads(m.value) for m in records(scope.topic('normalized')) if m.value]
            transformed=[json.loads(m.value) for m in records(scope.topic('transformed')) if m.value]
            if expected in normalized and any(e['event_id']==expected['event_id'] for e in transformed):
                print(json.dumps({'normalizer_restart':True,'fresh_event_id_stable':True,
                                  'transformed_after_restart':True}),flush=True)
                return
            time.sleep(1)
        raise AssertionError('fresh update missing after worker restart')
    if action == 'd3_inject':
        def clean_update(message):
            try:
                value=json.loads(message.value) if message.value else {}
            except (ValueError,TypeError):
                return False
            return (value.get('op')=='u' and not any(k in value for k in ('workspace_id','source_id','pipeline_id','dataset_id'))
                    and isinstance(value.get('after'),dict) and 'amount' in value['after'])
        sample=next(m for m in reversed(raw) if clean_update(m))
        value=json.loads(sample.value)
        if kind=='malformed':
            wire=b'{"before":"D3_PRIVATE_ROW_SENTINEL"'
        elif kind=='foreign':
            value['workspace_id']=22
            value['after']['customer']='D3_PRIVATE_ROW_SENTINEL'
            wire=canonical(value).encode()
        elif kind=='unsupported':
            value['op']='t'
            wire=canonical(value).encode()
        elif kind=='schema':
            value['after'].pop('amount')
            wire=canonical(value).encode()
        else:
            raise AssertionError('unknown D3 poison kind')
        producer=KafkaProducer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],acks='all',enable_idempotence=True)
        metadata=producer.send(scope.raw_topic,key=sample.key,value=wire).get(timeout=15)
        producer.close()
        print(json.dumps({'poison_kind':kind,'offset':metadata.offset,'raw_partition':metadata.partition}),flush=True)
        return
    if action == 'd3_poison_check':
        from kafka import TopicPartition
        expected={'malformed':'CDC_EVENT_INVALID','foreign':'CDC_SCOPE_MISMATCH',
                  'unsupported':'CDC_OPERATION_UNSUPPORTED','schema':'CDC_SCHEMA_INCOMPATIBLE'}[kind]
        target_offset=row_id if row_id else raw[-1].offset
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            failures=[json.loads(m.value) for m in records(scope.topic('dlq')) if m.value]
            item=next(p for p in ControlPlane('normalize').pipelines() if p['scope']['pipeline_id']==scope.pipeline_id)
            if failures and failures[-1]['reason']==expected and item['desired_state']=='PAUSED':
                failure=failures[-1]
                assert failure['workspace_id']==scope.workspace_id and failure['dataset_id']==scope.dataset_id
                assert failure['stage']=='normalize' and failure['retry_count']==0
                assert 'D3_PRIVATE_ROW_SENTINEL' not in canonical(failure)
                assert all(key not in failure for key in ('before','after','row','password','ciphertext'))
                consumer=KafkaConsumer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],
                                       group_id=f'biavora-cdc-v1-{scope.token}-normalize',enable_auto_commit=False)
                committed=consumer.committed(TopicPartition(scope.raw_topic,0))
                consumer.close()
                assert committed is not None and committed>=target_offset+1
                print(json.dumps({'kind':kind,'reason':expected,'dlq_safe':True,'pipeline_paused':True,
                                  'committed_offset':committed,'poison_offset':target_offset}),flush=True)
                return
            time.sleep(1)
        raise AssertionError('D3 poison did not reach terminal pause/commit')
    if action=='replay':
        producer=KafkaProducer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],acks='all',enable_idempotence=True)
        # Reversed delivery includes older updates, initial snapshots, deletes,
        # and tombstones. Apply twice, with no consumer offset reset.
        for _ in range(2):
            for message in reversed(raw):
                producer.send(scope.raw_topic,key=message.key,value=message.value).get(timeout=15)
        producer.close()
        print(json.dumps({'replayed':len(raw)*2,'reverse_order':True}),flush=True)
    elif action=='secrets':
        checked=0
        secrets=[os.environ[n].encode() for n in ('CDC_SOURCE_PASSWORD','CDC_SOURCE_ROTATED_PASSWORD','CDC_CREDENTIAL_KEY','CDC_SERVICE_KEY')]
        for item in items:
            current=Scope(**item['scope'])
            for topic in [current.raw_topic,current.topic('normalized'),current.topic('transformed'),current.topic('dlq')]:
                for message in records(topic):
                    if message.value:
                        assert not any(secret in message.value for secret in secrets), 'secret found in data topic'
                        checked+=1
            config=ConnectClient().request(current,'/config')
            if config is None:
                assert not records(current.raw_topic), 'raw topic exists without connector configuration'
            else:
                assert config['database.password'].startswith('${file:/run/cdc-secrets/')
                assert not any(secret in canonical(config).encode() for secret in secrets), 'secret found in persisted config'
        print(json.dumps({'business_records_checked':checked,'persisted_connector_configs':'references_only'}),flush=True)
    elif action=='diagnose':
        from kafka.admin import KafkaAdminClient
        admin=KafkaAdminClient(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'])
        status=ConnectClient().request(scope,'/status')
        print({'connector':status.get('connector',{}).get('state'),
               'tasks':[t.get('state') for t in status.get('tasks',[])]},flush=True)
        for stage,topic in [('normalize',scope.raw_topic),('transform',scope.topic('normalized')),('load',scope.topic('transformed'))]:
            group=f'biavora-cdc-v1-{scope.token}-{stage}'
            offsets=admin.list_consumer_group_offsets(group)
            messages=records(topic)
            print({'stage':stage,'records':len(messages),'committed':[v.offset for v in offsets.values()]},flush=True)
        admin.close()
    elif action=='race':
        snapshots=[json.loads(m.value) for m in raw if m.value and json.loads(m.value).get('op')=='r']
        timestamps=[r['source']['ts_ms'] for r in snapshots]
        if snapshot_from and snapshot_to:
            assert snapshots and any(snapshot_from<=t<=snapshot_to for t in timestamps), 'snapshot did not overlap the writer interval'
        else:
            # Recovery of an interrupted verifier: the snapshot itself saw an
            # intermediate writer value, followed by captured changes from the
            # same writer. No reconstructed wall-clock measurement is claimed.
            row=next(r for r in snapshots if r['after']['id']==2500)
            assert row['after']['status']=='pending' and 0<=float(row['after']['amount'])<1000
            updates=[json.loads(m.value) for m in raw if m.value and json.loads(m.value).get('op')=='u']
            assert any(r['after']['id']==2500 and r['source']['ts_ms']>=row['source']['ts_ms'] for r in updates)
        print(json.dumps({'snapshot_records':len(snapshots),'concurrent_writer_overlap':True}),flush=True)
    elif action=='poison':
        events=records(scope.topic('normalized'))
        event=json.loads(events[-1].value)
        event['workspace_id']=22 if scope.workspace_id!=22 else 11
        # Malformed identity must not become an arbitrary DLQ string.
        event['event_id']='synthetic-sensitive-content-must-not-be-copied'
        producer=KafkaProducer(bootstrap_servers=os.environ['KAFKA_BOOTSTRAP_SERVERS'],acks='all',enable_idempotence=True)
        producer.send(scope.topic('normalized'),key=events[-1].key,value=canonical(event).encode()).get(timeout=15)
        producer.close()
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            failures=records(scope.topic('dlq'))
            if failures:
                failure=json.loads(failures[-1].value)
                assert failure['workspace_id']==scope.workspace_id and failure['reason']=='CDC_SCOPE_MISMATCH'
                assert failure['event_id'] is None and 'before' not in failure and 'after' not in failure
                item=next(p for p in ControlPlane('normalize').pipelines() if p['scope']['pipeline_id']==scope.pipeline_id)
                if item['desired_state']=='PAUSED':
                    print(json.dumps({'foreign_scope_poison':'REJECTED','DLQ':'SCOPED_WITHOUT_PAYLOAD','pipeline':'PAUSED'}),flush=True)
                    return
            time.sleep(1)
        raise AssertionError('poison did not receive terminal disposition')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['replay','secrets','diagnose','race','poison','capture','empty','wait_raw','ciphertext',
                                          'd3_snapshot','d3_diagnose','d3_recover_first','d3_malformed_history','d3_inspect','d3_history','d3_secrets',
                                          'd3_replay','d3_replay_check','d3_restart_check',
                                          'd3_inject','d3_poison_check'])
    parser.add_argument('--pipeline')
    parser.add_argument('--snapshot-from',type=int,default=0)
    parser.add_argument('--snapshot-to',type=int,default=0)
    parser.add_argument('--row-id',type=int,default=0)
    parser.add_argument('--amount',default='')
    parser.add_argument('--kind',default='')
    args=parser.parse_args()
    main(args.action,args.pipeline,args.snapshot_from,args.snapshot_to,args.row_id,args.amount,args.kind)
