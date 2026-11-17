"""Disposable same-generation nullable ADD and incompatible reseed gates."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import time
import uuid

from bi_platform_shared.cdc_contract import Scope
from verify_foundation_d_cdc import Fixture, wait_for
from verify_foundation_d5_r1 import control_row, reseed, django_action, wait_candidate
from verify_foundation_d5_r2 import request_reconciliation, certificate


def state(fixture,scope):
    return fixture.api(scope.workspace_id,'GET',
        f'/database/sources/{scope.source_id}/cdc/')['data'][0]


def authorized(fixture,scope,columns):
    query=f"SELECT {', '.join(columns)} FROM cdc_{scope.token}_current ORDER BY id"
    return fixture.api(scope.workspace_id,'POST','/query/execute/',
        {'dataset_id':scope.dataset_id,'sql':query})['rows']


def compatible(fixture, overlap_path):
    old=json.loads(Path(overlap_path).read_text(encoding='utf-8'))
    scope=Scope(**old['candidate'])
    database=old['source_database']
    result={'case':'compatible_nullable_add','scope':scope.__dict__,
            'source_database':database,'started_at':datetime.now(timezone.utc).isoformat()}
    path=fixture.env_file.parent/f'd5-r4a-schema-add-{scope.token[:8]}.json'
    try:
        assert state(fixture,scope)['active_generation']==2
        assert fixture.rows_equal(scope,[[1,'boundary-overlap',Decimal(2),'new']])
        fixture.api(scope.workspace_id,'POST',
            f'/database/sources/{scope.source_id}/cdc/pause/',
            {'pipeline_id':scope.pipeline_id},expected=202)
        wait_for('same-generation CDC paused and drained',lambda:
            state(fixture,scope)['observed_state']=='PAUSED',seconds=300)
        result['paused_at']=datetime.now(timezone.utc).isoformat()
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE public.orders ADD COLUMN note text NULL')
        result['ddl_at']=datetime.now(timezone.utc).isoformat()
        fixture.api(scope.workspace_id,'POST',
            f'/database/sources/{scope.source_id}/cdc/resume/',
            {'pipeline_id':scope.pipeline_id},expected=202)
        wait_for('trusted nullable catalog version updated',lambda:
            (s if s['schema_version']==2 and any(c['name']=='note' and c['nullable']
                for c in control_columns(fixture,scope)) and s['observed_state']=='STREAMING'
                else False) if (s:=state(fixture,scope)) else False,seconds=300)
        result['resumed_schema_version']=2
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO public.orders VALUES (2,'added',3,'new','nullable-value')")
        result['new_value_committed_at']=datetime.now(timezone.utc).isoformat()
        rows=wait_for('authorized Query includes nullable ADD',lambda:
            (r if len(r)==2 and r[0]['id']==1 and r[0]['note'] is None
                and r[1]['id']==2 and r[1]['note']=='nullable-value' else False)
            if (r:=authorized(fixture,scope,['id','note'])) else False,seconds=240)
        result['authorized_rows']=rows
        fixture.api(scope.workspace_id,'POST',
            f'/database/sources/{scope.source_id}/cdc/reconcile/',
            {'pipeline_id':scope.pipeline_id},expected=202)
        reconciliation=wait_for('same-generation reconciliation MATCH',lambda:
            (s['reconciliation'] if s['reconciliation'].get('status')=='MATCH' else False)
            if (s:=state(fixture,scope)) else False,seconds=240)
        assert state(fixture,scope)['active_generation']==2
        result.update(status='PASS',reconciliation=reconciliation,
                      final_generation=2)
    except Exception as exc:
        result.update(status='FAIL',failure=f'{type(exc).__name__}: {exc}',
                      final_state=state(fixture,scope))
        raise
    finally:
        path.write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
        print(json.dumps({'evidence':str(path),'status':result['status']},default=str),flush=True)


def compatible_resume(fixture,path):
    path=Path(path)
    result=json.loads(path.read_text(encoding='utf-8'))
    scope=Scope(**result['scope'])
    assert result['authorized_rows'][1]['note']=='nullable-value'
    response=fixture.api(scope.workspace_id,'POST',
        f'/database/sources/{scope.source_id}/cdc/reconcile/',
        {'pipeline_id':scope.pipeline_id},expected=202)
    result['request_result']=response['data']['reconciliation_attempt']
    reconciliation=wait_for('active replacement same-generation reconciliation MATCH',lambda:
        (s['reconciliation'] if s['reconciliation'].get('status')=='MATCH' and
            'checked_at' in s['reconciliation'] else False)
        if (s:=state(fixture,scope)) else False,seconds=240)
    assert state(fixture,scope)['active_generation']==2
    result.update(status='PASS',reconciliation=reconciliation,final_generation=2,
                  verified_at=datetime.now(timezone.utc).isoformat())
    path.write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'evidence':str(path),'status':'PASS'}),flush=True)


def control_columns(fixture,scope):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT columns FROM integration_cdc_pipelines WHERE id=%s',
                           (scope.pipeline_id,))
            return cursor.fetchone()[0]


def incompatible(fixture):
    old,database=fixture.d2_source(row_count=1)
    result={'case':'incompatible_type_reseed','old':old.__dict__,
            'source_database':database,'started_at':datetime.now(timezone.utc).isoformat()}
    path=fixture.env_file.parent/f'd5-r4a-schema-incompatible-{uuid.uuid4().hex[:8]}.json'
    try:
        wait_for('incompatible source generation 1 Query',lambda:
            fixture.rows_equal(old,[[1,'d2',Decimal(1),'initial']]),seconds=240)
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE public.orders ALTER COLUMN amount TYPE numeric(22,4)')
        result['incompatible_ddl_at']=datetime.now(timezone.utc).isoformat()
        failed=wait_for('incompatible schema requires explicit reseed',lambda:
            (s if s['observed_state']=='RESEED_REQUIRED' and
                s['error_code']=='CDC_SCHEMA_INCOMPATIBLE' else False)
            if (s:=state(fixture,old)) else False,seconds=300)
        result['failed_generation_state']=failed
        assert fixture.rows_equal(old,[[1,'d2',Decimal(1),'initial']])
        candidate=reseed(fixture,old,'schema_incompatible')
        result['candidate']=candidate.__dict__
        wait_candidate(fixture,candidate,database)
        cert=request_reconciliation(fixture,candidate)
        assert cert['schema_version']==1 and cert['source_row_count']==1
        assert any(c['name']=='amount' and c['postgres_type']=='numeric(22,4)'
                   for c in cert['columns'])
        result.update(status='CERTIFIED_PENDING_CUTOVER',certificate=cert,
                      certified_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        result.update(status='FAIL',failure=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        path.write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
        print(json.dumps({'evidence':str(path),'status':result['status']},default=str),flush=True)


def incompatible_verify(fixture,path):
    path=Path(path)
    result=json.loads(path.read_text(encoding='utf-8'))
    candidate=Scope(**result['candidate'])
    rows=authorized(fixture,candidate,['id','amount'])
    assert len(rows)==1 and rows[0]['id']==1 and Decimal(str(rows[0]['amount']))==Decimal(1)
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT number,state FROM integration_cdc_generations '
                           'WHERE pipeline_id=%s ORDER BY number',(candidate.pipeline_id,))
            lineage=cursor.fetchall()
    assert lineage==[(1,'SUPERSEDED'),(2,'ACTIVE')]
    result.update(status='PASS',lineage=lineage,authorized_rows=rows,
                  verified_at=datetime.now(timezone.utc).isoformat())
    path.write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'evidence':str(path),'status':'PASS'},default=str),flush=True)


def incompatible_resume(fixture,path):
    path=Path(path)
    result=json.loads(path.read_text(encoding='utf-8'))
    scope=Scope(**result['candidate'])
    result['prior_readiness_race']='reconcile HTTP 409 before capture readiness'
    try:
        wait_for('incompatible candidate capture ready',lambda:
            state(fixture,scope)['candidate_capture_ready'],seconds=240)
        response=fixture.api(scope.workspace_id,'POST',
            f'/database/sources/{scope.source_id}/cdc/reconcile/',
            {'pipeline_id':scope.pipeline_id},expected=202)
        attempt_id=response['data']['reconciliation_attempt']['id']
        cert=wait_for('fresh incompatible candidate MATCH certificate',lambda:
            (c if c.get('attempt_id')==attempt_id and c.get('status')=='MATCH' else False)
            if (c:=certificate(fixture,scope)) else False,seconds=240)
        assert cert['source_row_count']==cert['query_row_count']==1
        assert any(c['name']=='amount' and c['postgres_type']=='numeric(22,4)'
                   for c in cert['columns'])
        result.update(status='CERTIFIED_PENDING_CUTOVER',certificate=cert,
                      certified_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        result.update(status='FAIL',failure=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        path.write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
        print(json.dumps({'evidence':str(path),'status':result['status']}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--env-file',required=True)
    parser.add_argument('--case',choices=['compatible','compatible_resume','incompatible','incompatible_resume','incompatible_verify'],required=True)
    parser.add_argument('--overlap-evidence')
    parser.add_argument('--existing-evidence')
    args=parser.parse_args()
    fixture=Fixture(args.env_file)
    if args.case=='compatible':
        compatible(fixture,args.overlap_evidence)
    elif args.case=='compatible_resume':
        compatible_resume(fixture,args.existing_evidence)
    elif args.case=='incompatible':
        incompatible(fixture)
    elif args.case=='incompatible_resume':
        incompatible_resume(fixture,args.existing_evidence)
    else:
        incompatible_verify(fixture,args.existing_evidence)
