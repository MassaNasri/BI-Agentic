"""Disposable D5-R4A typed and bounded live reconciliation gates."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from psycopg2 import sql

from bi_platform_shared.cdc_contract import Scope
from verify_foundation_d_cdc import Fixture, wait_for
from verify_foundation_d5_r1 import control_row, reseed
from verify_foundation_d5_r2 import request_reconciliation, certificate


def save(fixture, case, result):
    path = fixture.env_file.parent / f'd5-r4a-{case}-{uuid.uuid4().hex[:8]}.json'
    path.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    print(json.dumps({'evidence': str(path), **result}, default=str), flush=True)


def candidate_ready(fixture, scope, count):
    state = control_row(fixture, scope)
    if not state or state[1] != 'STREAMING' or state[6] != 'CANDIDATE':
        return False
    if state[4].get('status') != 'COMPLETED' or not state[5].get('slot_active'):
        return False
    try:
        rows = fixture.ch.query(f'SELECT count() FROM etl.cdc_{scope.token}_current').result_rows
        return rows == [(count,)]
    except Exception:
        return False


def typed(fixture):
    suffix = uuid.uuid4().hex[:8]
    database, role = 'source_d2_' + suffix, 'cdc_d2_' + suffix
    admin = fixture.pg()
    admin.autocommit = True
    with admin.cursor() as cursor:
        cursor.execute(sql.SQL('CREATE ROLE {} LOGIN REPLICATION NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %s').format(sql.Identifier(role)), (fixture.env['CDC_SOURCE_PASSWORD'],))
        cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    admin.close()
    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute('''CREATE TABLE public.typed_orders (
                tenant_id integer NOT NULL, order_id bigint NOT NULL,
                small_value smallint NOT NULL, exact_bigint bigint NOT NULL,
                exact_amount numeric(30,10) NOT NULL, enabled boolean NOT NULL,
                label varchar(80) NOT NULL, uuid_value uuid NOT NULL,
                business_day date NOT NULL, local_time timestamp NOT NULL,
                instant timestamptz NOT NULL, optional_text text NULL,
                payload jsonb NOT NULL, PRIMARY KEY (tenant_id,order_id))''')
            cursor.execute('ALTER TABLE public.typed_orders REPLICA IDENTITY FULL')
            cursor.execute('''INSERT INTO public.typed_orders VALUES
                (1,9007199254740993,-123,9007199254740993,12345678901234567890.1234567890,
                 true,'مرحبا Zürich','550e8400-e29b-41d4-a716-446655440000',
                 '2026-11-09','2026-11-09 12:34:56.123456',
                 '2026-11-09 15:34:56.123456+03',NULL,
                 '{"nested":{"text":"مرحبا 🌍","n":0.12345678901234567890123456789}}'::jsonb),
                (2,1,32767,-9007199254740993,-12.3400000000,
                 false,'naïve','550e8400-e29b-41d4-a716-446655440001',
                 '2000-01-01','2000-01-01 00:00:00',
                 '2000-01-01 00:00:00+00','optional',
                 '{"array":[1,true,null,"é"]}'::jsonb)''')
            cursor.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
            cursor.execute(sql.SQL('GRANT SELECT ON public.typed_orders TO {}').format(sql.Identifier(role)))
    source = fixture.api(11,'POST','/database/sources/',{
        'name':'D5-R4A typed '+suffix,'engine':'postgres',
        'connection_metadata':{'host':'postgres','port':5432,'database':database,'username':role,'sslmode':'disable'},
        'selected_tables':[{'schema':'public','name':'typed_orders'}],
        'password':fixture.env['CDC_SOURCE_PASSWORD']},expected=201)['data']
    pipeline = fixture.api(11,'POST',f"/database/sources/{source['id']}/cdc/enable/",
                           {'schema':'public','table':'typed_orders'},expected=202)['data']
    old = Scope(11,source['id'],pipeline['id'],pipeline['dataset_id'],'public','typed_orders')
    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE PUBLICATION {} FOR TABLE public.typed_orders').format(sql.Identifier('b_'+old.token)))
    wait_for('typed generation 1 current view', lambda: candidate_ready_active(fixture, old, 2), seconds=240)
    candidate = reseed(fixture, old, 'operator_reseed')
    wait_for('typed candidate snapshot and Loader',lambda: candidate_ready(fixture,candidate,2),seconds=300)
    result={'case':'typed','source_database':database,'old':old.__dict__,
            'candidate':candidate.__dict__,'started_at':datetime.now(timezone.utc).isoformat()}
    start=time.monotonic()
    try:
        cert=request_reconciliation(fixture,candidate)
        result.update(status='PASS',certificate=cert,elapsed_seconds=time.monotonic()-start)
    except Exception as exc:
        result.update(status='FAIL',failure=f'{type(exc).__name__}: {exc}',
                      attempt=attempt(fixture,candidate),certificate=certificate(fixture,candidate))
        raise
    finally:
        save(fixture,'typed',result)


def candidate_ready_active(fixture, scope, count):
    state=control_row(fixture,scope)
    if not state or state[6] != 'ACTIVE' or state[1] != 'STREAMING':
        return False
    try:
        return fixture.ch.query(f'SELECT count() FROM etl.cdc_{scope.token}_current').result_rows == [(count,)]
    except Exception:
        return False


def attempt(fixture, scope):
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT reconciliation_attempt FROM integration_cdc_generations WHERE pipeline_id=%s AND number=%s',
                           (scope.pipeline_id,scope.generation))
            return cursor.fetchone()[0]


def bounded(fixture, rows):
    old,database=fixture.d2_source(row_count=rows)
    result={'case':'bounded','rows':rows,'source_database':database,'old':old.__dict__,
            'started_at':datetime.now(timezone.utc).isoformat()}
    try:
        wait_for('bounded generation 1 Loader',lambda: candidate_ready_active(fixture,old,rows),seconds=300)
        candidate=reseed(fixture,old,'operator_reseed')
        result['candidate']=candidate.__dict__
        wait_for('bounded candidate Loader',lambda: candidate_ready(fixture,candidate,rows),seconds=360)
        start=time.monotonic()
        if rows<=10000:
            cert=request_reconciliation(fixture,candidate)
            assert cert['source_row_count']==rows and cert['query_row_count']==rows
            result.update(status='PASS',certificate=cert,elapsed_seconds=time.monotonic()-start)
        else:
            fixture.api(11,'POST',f'/database/sources/{candidate.source_id}/cdc/reconcile/',
                        {'pipeline_id':candidate.pipeline_id},expected=202)
            wait_for('above-cap attempt fails',lambda: attempt(fixture,candidate).get('state')=='FAILED',seconds=180)
            state=attempt(fixture,candidate)
            assert state.get('failure_code')=='CDC_RECONCILIATION_LIMIT'
            assert certificate(fixture,candidate).get('status')!='MATCH'
            result.update(status='PASS',attempt=state,certificate=certificate(fixture,candidate),
                          elapsed_seconds=time.monotonic()-start)
    except Exception as exc:
        result.update(status='FAIL',failure=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        save(fixture,'bounded',result)


def typed_existing(fixture, path):
    prior=json.loads(Path(path).read_text(encoding='utf-8'))
    scope=Scope(**prior['candidate'])
    cert=certificate(fixture,scope)
    assert cert.get('kind')=='watermark_reconciliation.v1' and cert.get('status')=='MATCH'
    assert cert.get('source_row_count')==cert.get('query_row_count')==2
    result={'case':'typed','status':'PASS','source_database':prior['source_database'],
            'candidate':scope.__dict__,'certificate':cert,
            'initial_readiness_race_evidence':str(path)}
    save(fixture,'typed-match',result)


def bounded_existing(fixture, path):
    prior=json.loads(Path(path).read_text(encoding='utf-8'))
    old=Scope(**prior['old'])
    rows=prior['rows']
    wait_for('existing bounded generation 1 Loader',
             lambda: candidate_ready_active(fixture,old,rows),seconds=900)
    candidate=reseed(fixture,old,'operator_reseed')
    result={'case':'bounded','rows':rows,'source_database':prior['source_database'],
            'candidate':candidate.__dict__,'prior_timeout_evidence':str(path)}
    try:
        wait_for('existing bounded candidate Loader',
                 lambda: candidate_ready(fixture,candidate,rows),seconds=900)
        start=time.monotonic()
        cert=request_reconciliation(fixture,candidate)
        assert cert['source_row_count']==cert['query_row_count']==rows
        result.update(status='PASS',certificate=cert,elapsed_seconds=time.monotonic()-start)
    except Exception as exc:
        result.update(status='FAIL',failure=f'{type(exc).__name__}: {exc}',
                      attempt=attempt(fixture,candidate),certificate=certificate(fixture,candidate))
        raise
    finally:
        save(fixture,'bounded-resume',result)


def bounded_retry(fixture, path):
    prior=json.loads(Path(path).read_text(encoding='utf-8'))
    scope=Scope(**prior['candidate'])
    rows=prior['rows']
    response=fixture.api(scope.workspace_id,'POST',
        f'/database/sources/{scope.source_id}/cdc/reconcile/',
        {'pipeline_id':scope.pipeline_id},expected=202)
    attempt_id=response['data']['reconciliation_attempt']['id']
    start=time.monotonic()
    result={'case':'bounded_retry','rows':rows,'candidate':scope.__dict__,
            'prior_mismatch_evidence':str(path),'attempt_id':attempt_id}
    try:
        cert=wait_for('corrected multi-chunk MATCH certificate',lambda:
            (c if c.get('attempt_id')==attempt_id and c.get('status') in {'MATCH','MISMATCH'}
             else False) if (c:=certificate(fixture,scope)) else False,seconds=240)
        assert cert['status']=='MATCH' and cert['source_row_count']==rows
        assert cert['query_row_count']==rows and cert['chunk_count']>=5
        result.update(status='PASS',certificate=cert,elapsed_seconds=time.monotonic()-start)
    except Exception as exc:
        result.update(status='FAIL',failure=f'{type(exc).__name__}: {exc}',
                      attempt=attempt(fixture,scope),certificate=certificate(fixture,scope))
        raise
    finally:
        save(fixture,'bounded-retry',result)


def above_limit_existing(fixture,path):
    prior=json.loads(Path(path).read_text(encoding='utf-8'))
    scope=Scope(**prior['candidate'])
    database=prior.get('source_database') or json.loads(
        Path(prior['prior_mismatch_evidence']).read_text(encoding='utf-8'))['source_database']
    result={'case':'above_limit','scope':scope.__dict__,'source_database':database,
            'prior_multichunk_match_evidence':str(path)}
    try:
        with fixture.pg(database) as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO public.orders SELECT i,'cap',i,'over' "
                               "FROM generate_series(2501,10001) i")
                assert cursor.rowcount==7501
                cursor.execute('SELECT count(*) FROM public.orders')
                assert cursor.fetchone()[0]==10001
        result['source_rows']=10001
        response=fixture.api(scope.workspace_id,'POST',
            f'/database/sources/{scope.source_id}/cdc/reconcile/',
            {'pipeline_id':scope.pipeline_id},expected=202)
        attempt_id=response['data']['reconciliation_attempt']['id']
        result['attempt_id']=attempt_id
        state=wait_for('above-10k attempt fails closed',lambda:
            (s if s.get('id')==attempt_id and s.get('state')=='FAILED' else False)
            if (s:=attempt(fixture,scope)) else False,seconds=240)
        assert state.get('failure_code')=='CDC_RECONCILIATION_LIMIT'
        assert certificate(fixture,scope).get('attempt_id')!=attempt_id
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT state FROM integration_cdc_generations '
                               'WHERE pipeline_id=%s AND number=2',(scope.pipeline_id,))
                generation_state=cursor.fetchone()[0]
                cursor.execute('SELECT cdc_generation FROM manager_databases WHERE id=%s',
                               (scope.dataset_id,))
                query_generation=cursor.fetchone()[0]
        assert generation_state=='CANDIDATE' and query_generation==1
        result.update(status='PASS',failed_attempt=state,
                      certificate=certificate(fixture,scope),
                      generation_state=generation_state,query_generation=query_generation)
    except Exception as exc:
        result.update(status='FAIL',failure=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        save(fixture,'above-limit',result)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--env-file',required=True)
    parser.add_argument('--case',choices=['typed','bounded','typed_existing','bounded_existing','bounded_retry','above_limit_existing'],required=True)
    parser.add_argument('--rows',type=int,default=2500)
    parser.add_argument('--existing-evidence')
    args=parser.parse_args()
    fixture=Fixture(args.env_file)
    if args.case=='typed':
        typed(fixture)
    elif args.case=='bounded':
        bounded(fixture,args.rows)
    elif args.case=='typed_existing':
        typed_existing(fixture,args.existing_evidence)
    elif args.case=='bounded_existing':
        bounded_existing(fixture,args.existing_evidence)
    elif args.case=='bounded_retry':
        bounded_retry(fixture,args.existing_evidence)
    else:
        above_limit_existing(fixture,args.existing_evidence)
