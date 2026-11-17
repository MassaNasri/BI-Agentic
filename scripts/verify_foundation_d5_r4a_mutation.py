"""Live, test-scoped source mutation during an established reconciliation snapshot."""
import argparse
from datetime import datetime, timezone
import json
from decimal import Decimal
from pathlib import Path
import time

from bi_platform_shared.cdc_contract import Scope
from verify_foundation_d_cdc import Fixture, wait_for
from verify_foundation_d5_r2 import certificate
from verify_foundation_d5_r4a_remaining import attempt
from verify_foundation_d5_r1 import control_row


def request(fixture, scope):
    response=fixture.session.post(
        fixture.base+f'/database/sources/{scope.source_id}/cdc/reconcile/',
        json={'pipeline_id':scope.pipeline_id},
        headers={'Authorization':'Bearer '+fixture.token(scope.workspace_id)},timeout=20)
    if response.status_code != 202:
        raise AssertionError(f'reconcile HTTP {response.status_code}')
    return response.json()['data']['reconciliation_attempt']['id']


def gate_backend(fixture, database, role):
    with fixture.pg(database) as connection:
        with connection.cursor() as cursor:
            cursor.execute('''SELECT pid,wait_event_type,wait_event,query_start::text
                FROM pg_stat_activity WHERE datname=%s AND usename=%s
                AND query LIKE '%%pg_advisory_xact_lock%%'
                AND query NOT LIKE '%%pg_stat_activity%%'
                ORDER BY query_start DESC LIMIT 1''',(database,role))
            return cursor.fetchone()


def run(fixture, evidence_path):
    prior=json.loads(Path(evidence_path).read_text(encoding='utf-8'))
    scope=Scope(**prior['candidate'])
    database=prior['source_database']
    role='cdc_d2_'+database.split('source_d2_',1)[1]
    key=int(scope.token[:15],16)
    result={'case':'concurrent_source_mutation','scope':scope.__dict__,
            'source_database':database,'started_at':datetime.now(timezone.utc).isoformat(),
            'prior_certificate_attempt':certificate(fixture,scope).get('attempt_id')}
    path=fixture.env_file.parent/f'd5-r4a-mutation-{scope.token[:8]}.json'
    lock=fixture.pg(database)
    lock.autocommit=True
    held=False
    try:
        with lock.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_lock(%s)',(key,))
        held=True
        result['lock_held_at']=datetime.now(timezone.utc).isoformat()
        attempt_id=request(fixture,scope)
        result['first_attempt_id']=attempt_id
        def blocked():
            state=attempt(fixture,scope)
            backend=gate_backend(fixture,database,role)
            if state.get('id')==attempt_id and state.get('state')=='SOURCE_SNAPSHOT_OPEN' and backend and backend[1:3]==('Lock','advisory'):
                return backend
            return False
        backend=wait_for('reconciliation source snapshot blocked at gate',blocked,seconds=300)
        result['gate_backend']={'pid':backend[0],'wait_event_type':backend[1],
                                'wait_event':backend[2],'query_start':backend[3]}
        result['snapshot_open_gate_reached_at']=datetime.now(timezone.utc).isoformat()
        with fixture.pg(database) as writer:
            with writer.cursor() as cursor:
                cursor.execute('''UPDATE public.typed_orders SET exact_amount=exact_amount+1
                    WHERE tenant_id=1 AND order_id=9007199254740993''')
                assert cursor.rowcount==1
        result['source_update_committed_at']=datetime.now(timezone.utc).isoformat()
        with lock.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)',(key,))
        held=False
        result['gate_released_at']=datetime.now(timezone.utc).isoformat()
        state=wait_for('source movement fails first reconciliation attempt',
            lambda: (s if s.get('id')==attempt_id and s.get('state')=='FAILED' else False)
                    if (s:=attempt(fixture,scope)) else False,seconds=240)
        assert state.get('failure_code')=='CDC_RECONCILIATION_SOURCE_MOVED',state
        result['failed_attempt']=state
        assert certificate(fixture,scope).get('attempt_id')!=attempt_id
        # The later attempt uses a fresh source snapshot and marker. The gate
        # remains configured but its fixture advisory lock is no longer held.
        wait_for('candidate receives concurrent UPDATE',lambda:
            fixture.ch.query(f'SELECT exact_amount FROM etl.cdc_{scope.token}_current '
                'WHERE tenant_id=1 AND order_id=9007199254740993').result_rows
                == [(Decimal('12345678901234567891.1234567890'),)],seconds=180)
        second=request(fixture,scope)
        assert second!=attempt_id
        result['retry_attempt_id']=second
        cert=wait_for('later watermark MATCH certificate',lambda:
            (c if c.get('attempt_id')==second and c.get('status')=='MATCH' else False)
            if (c:=certificate(fixture,scope)) else False,seconds=240)
        result.update(status='PASS',retry_certificate=cert)
    except Exception as exc:
        result.update(status='FAIL',failure=f'{type(exc).__name__}: {exc}',
                      attempt=attempt(fixture,scope),certificate=certificate(fixture,scope))
        raise
    finally:
        if held:
            with lock.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)',(key,))
        lock.close()
        path.write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
        print(json.dumps({'evidence':str(path),'status':result['status']},default=str),flush=True)


def retry(fixture, path):
    path=Path(path)
    result=json.loads(path.read_text(encoding='utf-8'))
    scope=Scope(**result['scope'])
    failed=result.get('failed_attempt') or attempt(fixture,scope)
    assert failed.get('state')=='FAILED' and failed.get('failure_code')=='CDC_RECONCILIATION_SOURCE_MOVED'
    result['failed_attempt']=failed
    state=control_row(fixture,scope)
    assert state[6]=='CANDIDATE'
    if state[1]=='PAUSED':
        fixture.api(scope.workspace_id,'POST',
            f'/database/sources/{scope.source_id}/cdc/resume/',
            {'pipeline_id':scope.pipeline_id},expected=202)
    wait_for('candidate explicitly resumed after source movement',
             lambda: control_row(fixture,scope)[1]=='STREAMING',seconds=240)
    second=request(fixture,scope)
    assert second!=failed['id']
    result['retry_attempt_id']=second
    cert=wait_for('later watermark MATCH certificate',lambda:
        (c if c.get('attempt_id')==second and c.get('status')=='MATCH' else False)
        if (c:=certificate(fixture,scope)) else False,seconds=240)
    result.update(status='PASS',retry_certificate=cert,
                  retry_completed_at=datetime.now(timezone.utc).isoformat())
    path.write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'evidence':str(path),'status':'PASS','retry_attempt_id':second}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--env-file',required=True)
    parser.add_argument('--typed-evidence',required=True)
    parser.add_argument('--retry-from')
    args=parser.parse_args()
    fixture=Fixture(args.env_file)
    retry(fixture,args.retry_from) if args.retry_from else run(fixture,args.typed_evidence)
