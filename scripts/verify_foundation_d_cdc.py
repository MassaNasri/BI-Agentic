"""Disposable, real CDC acceptance. Credentials/results stay outside the repo.

Run with the query test venv (psycopg2, requests, PyJWT, clickhouse-connect).
The compose project is fixed and separate from all existing BIAVORA stacks.
"""
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading
import uuid
import jwt
import psycopg2
from psycopg2 import sql
import requests
import clickhouse_connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bi_platform_shared.cdc_contract import Scope


def wait_for(label, function, seconds=120):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        try:
            result = function()
            if result:
                print('PASS ' + label, flush=True)
                return result
        except (requests.RequestException, psycopg2.Error):
            pass
        time.sleep(1)
    raise AssertionError('Timed out: '+label)


class Fixture:
    def __init__(self, env_file):
        self.env_file = Path(env_file).resolve()
        self.env = dict(line.split('=',1) for line in self.env_file.read_text().splitlines() if '=' in line)
        self.state_path = self.env_file.parent / 'fixture-state.json'
        self.session = requests.Session()
        self.session.trust_env = False
        internal = os.getenv('CDC_FIXTURE_INTERNAL') == '1'
        self.base = 'http://query:8006' if internal else 'http://127.0.0.1:18096'
        self.pg_host, self.pg_port = ('postgres', 5432) if internal else ('127.0.0.1', 18094)
        self.ch = clickhouse_connect.get_client(host='clickhouse' if internal else '127.0.0.1',
            port=8123 if internal else 18095,
            username='cdc_loader', password=self.env['CDC_CH_PASSWORD'])

    def compose(self, *args, expected=0):
        result=subprocess.run(['docker','compose','--project-name','biavora_foundation_d','--env-file',str(self.env_file),
                        '-f',str(ROOT/'docker-compose.cdc-local.yml'),*args], cwd=ROOT)
        if result.returncode != expected:
            raise AssertionError(f'Disposable compose exit {result.returncode}, expected {expected}')

    def pg(self, database='postgres', user='postgres', password=None):
        return psycopg2.connect(host=self.pg_host,port=self.pg_port,dbname=database,user=user,
                               password=password or self.env['CDC_PG_PASSWORD'],connect_timeout=5)

    def token(self, workspace, role='manager'):
        return jwt.encode({'user_id':workspace, 'workspace_id':workspace, 'role':role,
                           'token_type':'access', 'jti':str(uuid.uuid4()), 'exp':int(time.time())+7200},
                          self.env['CDC_JWT_KEY'],algorithm='HS256')

    def api(self, workspace, method, path, body=None, expected=200, role='manager'):
        response=self.session.request(method,self.base+path,json=body,
            headers={'Authorization':'Bearer '+self.token(workspace,role)}, timeout=15)
        if response.status_code != expected:
            # Response bodies can contain infrastructure details on a server
            # misconfiguration. Report bounded status only.
            raise AssertionError(f'{method} {path}: HTTP {response.status_code}, expected {expected}')
        return response.json()

    def bootstrap(self):
        wait_for('Query health',lambda:self.session.get(self.base+'/health/',timeout=3).ok)
        if self.state_path.exists():
            raise AssertionError('Fixture already initialized; use check phase or a new disposable project after explicit cleanup.')
        self.ch.command("CREATE USER IF NOT EXISTS cdc_query IDENTIFIED WITH sha256_password BY {password:String}", parameters={'password':self.env['CDC_QUERY_CH_PASSWORD']})
        self.ch.command('GRANT SELECT ON etl.* TO cdc_query')
        # SELECT-only grants prohibit writes independently of per-query settings.
        # Query sets readonly=1 together with its bounded resource settings; a
        # readonly=1/2 profile would prohibit changing those HTTP parameters.
        self.ch.command('ALTER USER cdc_query SETTINGS readonly=0')
        state=[]
        for workspace, suffix in [(11,'a'),(22,'b')]:
            database, role = 'source_'+suffix, 'cdc_'+suffix
            with self.pg() as admin:
                admin.autocommit=True
                with admin.cursor() as cur:
                    cur.execute(sql.SQL('CREATE ROLE {} LOGIN REPLICATION NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %s').format(sql.Identifier(role)),(self.env['CDC_SOURCE_PASSWORD'],))
            admin=self.pg()
            admin.autocommit=True
            with admin.cursor() as cur:
                cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
            admin.close()
            with self.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute('CREATE TABLE public.orders (id integer PRIMARY KEY, customer text NOT NULL, amount numeric(20,4) NOT NULL, status text NOT NULL)')
                    cur.execute('ALTER TABLE public.orders REPLICA IDENTITY FULL')
                    if suffix == 'a':
                        cur.execute("INSERT INTO public.orders VALUES (1,'Alice',100,'pending'),(2,'Bob',200,'pending'),(3,'Carol',300,'paid')")
                    else:
                        cur.execute("INSERT INTO public.orders VALUES (99,'Workspace B',999,'private')")
                    cur.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
                    cur.execute(sql.SQL('GRANT SELECT ON public.orders TO {}').format(sql.Identifier(role)))
            source=self.api(workspace,'POST','/database/sources/',{
                'name':'CDC fixture '+suffix, 'engine':'postgres',
                'connection_metadata':{'host':'postgres','port':5432,'database':database,'username':role,'sslmode':'disable'},
                'selected_tables':[{'schema':'public','name':'orders'}], 'password':self.env['CDC_SOURCE_PASSWORD']},expected=201)['data']
            pipeline=self.api(workspace,'POST',f"/database/sources/{source['id']}/cdc/enable/",{'schema':'public','table':'orders'},expected=202)['data']
            scope=Scope(workspace,source['id'],pipeline['id'],pipeline['dataset_id'],'public','orders')
            with self.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute(sql.SQL('CREATE PUBLICATION {} FOR TABLE public.orders').format(sql.Identifier('b_'+scope.token)))
            state.append(scope.__dict__)
        self.state_path.write_text(json.dumps(state,indent=2))
        print('PASS bootstrap: two isolated source databases, replication roles, persisted source/pipeline/dataset scopes',flush=True)

    def state(self):
        return [Scope(**row) for row in json.loads(self.state_path.read_text())]

    def query(self, scope, workspace=None):
        return self.api(workspace or scope.workspace_id,'POST','/query/execute/',
            {'dataset_id':scope.dataset_id,'sql':f'SELECT id, customer, amount, status FROM cdc_{scope.token}_current ORDER BY id'})

    def rows_equal(self, scope, expected):
        try:
            result=self.query(scope)
            return result.get('success') is True and [[r['id'],r['customer'],Decimal(str(r['amount'])),r['status']] for r in result['rows']] == expected
        except AssertionError:
            return False

    def check(self):
        a,b=self.state()
        initial=[[1,'Alice',Decimal(100),'pending'],[2,'Bob',Decimal(200),'pending'],[3,'Carol',Decimal(300),'paid']]
        wait_for('consistent initial snapshot through authorized Query',lambda:self.rows_equal(a,initial))
        wait_for('workspace B own dataset',lambda:self.rows_equal(b,[[99,'Workspace B',Decimal(999),'private']]))
        start=time.monotonic()
        with self.pg('source_a') as connection:
            with connection.cursor() as cur:
                cur.execute("INSERT INTO orders VALUES (4,'Dave',400,'pending')")
                cur.execute("UPDATE orders SET amount=250,status='paid' WHERE id=2")
                cur.execute('DELETE FROM orders WHERE id=1')
                cur.execute("UPDATE orders SET status='cancelled' WHERE id=4")
        expected=[[2,'Bob',Decimal(250),'paid'],[3,'Carol',Decimal(300),'paid'],[4,'Dave',Decimal(400),'cancelled']]
        wait_for('insert/update/delete exact final Query result',lambda:self.rows_equal(a,expected))
        elapsed=time.monotonic()-start
        self.api(22,'POST','/query/execute/',{'dataset_id':a.dataset_id,'sql':f'SELECT * FROM cdc_{a.token}_current'},expected=403)
        self.api(22,'GET',f'/database/sources/{a.source_id}/cdc/',expected=404)
        self.api(11,'POST',f'/database/sources/{a.source_id}/cdc/pause/',{'pipeline_id':b.pipeline_id},expected=404)
        self.api(11,'GET',f'/database/sources/{a.source_id}/cdc/',expected=403,role='viewer')
        self.api(11,'POST',f'/database/sources/{a.source_id}/cdc/reconcile/',{'pipeline_id':a.pipeline_id},expected=202)
        def reconciled():
            p=self.api(11,'GET',f'/database/sources/{a.source_id}/cdc/')['data'][0]
            return p['reconciliation'].get('status') == 'MATCH'
        wait_for('bounded exact reconciliation',reconciled)
        result={'status':'LOCAL_CORE_PASS','final_rows':[[r[0],r[1],str(r[2]),r[3]] for r in expected],
                'four_changes_catchup_seconds':elapsed,'workspace_isolation':'PASS','reconciliation':'MATCH',
                'full_foundation_d_acceptance':'NOT_YET_COMPLETE'}
        (self.env_file.parent/'core-results.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)

    def recovery(self):
        a,b=self.state()
        expected=[[2,'Bob',Decimal(250),'paid'],[3,'Carol',Decimal(300),'paid'],[4,'Dave',Decimal(400),'cancelled']]
        results=[]
        def changed(value):
            with self.pg('source_a') as connection:
                with connection.cursor() as cur:
                    cur.execute('UPDATE orders SET amount=%s WHERE id=2',(value,))
        def caught(label,value):
            rows=[row[:] for row in expected]
            rows[0][2]=Decimal(value)
            wait_for(label,lambda:self.rows_equal(a,rows))
            results.append(label)
            (self.env_file.parent/'recovery-progress.json').write_text(json.dumps(results,indent=2))
        changed(245)
        caught('intermediate update',245)
        changed(250)
        caught('newer update',250)
        self.ch.command(f'SYSTEM STOP MERGES etl.cdc_{a.token}_versions')
        self.compose('run','--rm','--no-deps','acceptance','replay')
        # Wait for all three durable stage checkpoints to settle, then observe
        # multiple queries while merges are disabled.
        time.sleep(8)
        for _ in range(3):
            assert self.rows_equal(a,expected),'replay regressed current state'
            time.sleep(1)
        results.append('reverse replay and tombstones before merges')
        self.ch.command(f'SYSTEM START MERGES etl.cdc_{a.token}_versions')
        for service in ('connect','normalizer','transformer','loader','query'):
            self.compose('restart',service)
            changed(251)
            caught(service+' restart catch-up',251)
            changed(250)
            caught(service+' restored exact result',250)
        for service in ('postgres','kafka','clickhouse'):
            if service=='postgres':
                self.compose('stop',service)
                time.sleep(3)
                self.compose('start',service)
                wait_for('PostgreSQL reconnected',lambda:self.pg('source_a').close() is None)
                changed(252)
            else:
                self.compose('stop',service)
                changed(252)
                time.sleep(3)
                self.compose('start',service)
            caught(service+' outage catch-up',252)
            changed(250)
            caught(service+' restored exact result',250)
        self.compose('stop','loader')
        changed(253)
        self.compose('run','--rm','--no-deps','-e','CDC_CRASH_AFTER_APPLY=load','loader',expected=86)
        caught('crash after ClickHouse write before checkpoint and Kafka acknowledgement',253)
        self.compose('start','loader')
        time.sleep(5)
        caught('unacknowledged write replay after Loader restart',253)
        changed(250)
        caught('crash recovery restored exact result',250)
        self.compose('run','--rm','--no-deps','acceptance','secrets')
        results.append('Kafka and persisted connector secret inspection')
        self.api(11,'POST',f'/database/sources/{a.source_id}/cdc/reconcile/',{'pipeline_id':a.pipeline_id},expected=202)
        output={'recovery_checks':results,'status':'PASS'}
        (self.env_file.parent/'recovery-results.json').write_text(json.dumps(output,indent=2))
        print(json.dumps(output),flush=True)

    def lifecycle(self):
        a,b=self.state()
        def status(scope):
            return self.api(scope.workspace_id,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        def action(scope,name):
            return self.api(scope.workspace_id,'POST',f'/database/sources/{scope.source_id}/cdc/{name}/',{'pipeline_id':scope.pipeline_id},expected=202)
        def inactive(scope):
            with self.pg('source_a' if scope.workspace_id==11 else 'source_b') as connection:
                with connection.cursor() as cur:
                    cur.execute('SELECT NOT active FROM pg_replication_slots WHERE slot_name=%s',('b_'+scope.token,))
                    return cur.fetchone()==(True,)
        new_password=self.env['CDC_SOURCE_ROTATED_PASSWORD']
        with self.pg() as connection:
            with connection.cursor() as cur:
                cur.execute('ALTER ROLE cdc_a PASSWORD %s',(new_password,))
        self.api(11,'POST',f'/database/sources/{a.source_id}/credential/rotate/',{'password':new_password})
        try:
            self.pg('source_a',user='cdc_a',password=self.env['CDC_SOURCE_PASSWORD']).close()
            raise AssertionError('superseded database password still accepted')
        except psycopg2.OperationalError:
            print('PASS superseded database password rejected',flush=True)
        with self.pg('source_a',user='cdc_a',password=new_password) as connection:
            with connection.cursor() as cur:
                cur.execute('SELECT count(*) FROM orders')
                assert cur.fetchone()==(3,)
        with self.pg('source_a') as connection:
            with connection.cursor() as cur:
                cur.execute("UPDATE orders SET status='rotation_verified' WHERE id=2")
        expected=[[2,'Bob',Decimal(250),'rotation_verified'],[3,'Carol',Decimal(300),'paid'],[4,'Dave',Decimal(400),'cancelled']]
        wait_for('Foundation-C rotation and controlled connector reconnect',lambda:self.rows_equal(a,expected))
        action(a,'pause')
        wait_for('pause retained an inactive replication slot',lambda:status(a)['observed_state']=='PAUSED' and inactive(a))
        with self.pg('source_a') as connection:
            with connection.cursor() as cur:
                cur.execute('ALTER TABLE orders ADD COLUMN note text')
                cur.execute("UPDATE orders SET note='nullable addition', status='paid' WHERE id=2")
        action(a,'resume')
        def added():
            try:
                r=self.api(11,'POST','/query/execute/',{'dataset_id':a.dataset_id,
                    'sql':f'SELECT id,note FROM cdc_{a.token}_current ORDER BY id'})
                return r.get('rows')==[{'id':2,'note':'nullable addition'},{'id':3,'note':None},{'id':4,'note':None}]
            except AssertionError:
                return False
        wait_for('controlled nullable ADD and resume through Query',added)
        assert status(a)['schema_version']==2
        previous_check=status(a)['reconciliation'].get('checked_at')
        action(a,'reconcile')
        wait_for('reconciliation after schema addition',lambda:status(a)['reconciliation'].get('status')=='MATCH' and status(a)['reconciliation'].get('checked_at') != previous_check)
        with self.pg('source_a') as connection:
            with connection.cursor() as cur:
                cur.execute('ALTER TABLE orders ALTER COLUMN amount TYPE numeric(21,4)')
        wait_for('incompatible type change requires reseed',lambda:status(a)['observed_state']=='RESEED_REQUIRED')
        self.api(11,'POST',f'/database/sources/{a.source_id}/cdc/resume/',{'pipeline_id':a.pipeline_id},expected=400)
        self.api(22,'DELETE',f'/database/sources/{b.source_id}/')
        wait_for('retirement stopped capture and retained slot',lambda:status(b)['observed_state']=='STOPPED' and inactive(b))
        assert self.rows_equal(b,[[99,'Workspace B',Decimal(999),'private']])
        self.api(11,'DELETE',f'/database/?dataset_id={a.dataset_id}',expected=409)
        output={'rotation':'PASS','old_password':'REJECTED','nullable_add':'PASS','incompatible_type':'RESEED_REQUIRED',
                'retirement':'STOPPED_WITH_DATA_AND_SLOT_RETAINED','snapshot_delete_route':'LIVE_DATASET_PROTECTED'}
        (self.env_file.parent/'lifecycle-results.json').write_text(json.dumps(output,indent=2))
        print(json.dumps(output),flush=True)

    def storage_recovery(self):
        a,_=self.state()
        def change(value):
            with self.pg('source_a') as connection:
                with connection.cursor() as cur:
                    cur.execute('UPDATE orders SET amount=%s WHERE id=2',(value,))
        def caught(label,value):
            expected=[[2,'Bob',Decimal(value),'paid'],[3,'Carol',Decimal(300),'paid'],[4,'Dave',Decimal(400),'cancelled']]
            wait_for(label,lambda:self.rows_equal(a,expected))
        change(250)
        caught('controlled Connect recovery retained source position',250)
        self.compose('stop','clickhouse')
        change(252)
        time.sleep(3)
        self.compose('start','clickhouse')
        caught('ClickHouse interruption catch-up',252)
        self.compose('stop','loader')
        change(253)
        self.compose('run','--rm','--no-deps','-e','CDC_CRASH_AFTER_APPLY=load','loader',expected=86)
        caught('write durable before checkpoint and acknowledgement',253)
        self.compose('start','loader')
        time.sleep(5)
        caught('unacknowledged write replay after Loader restart',253)
        change(250)
        caught('storage recovery exact final result',250)
        self.compose('run','--rm','--no-deps','acceptance','secrets')
        output={'ClickHouse_outage':'PASS','crash_after_write_before_ack':'PASS','unacknowledged_replay':'PASS','secret_inspection':'PASS','Kafka_automatic_recovery':'FAILED_IN_SEPARATE_RUN'}
        (self.env_file.parent/'storage-recovery-results.json').write_text(json.dumps(output,indent=2))
        print(json.dumps(output),flush=True)

    def race(self):
        database,role='source_race','cdc_race'
        admin=self.pg()
        admin.autocommit=True
        with admin.cursor() as cur:
            cur.execute(sql.SQL('CREATE ROLE {} LOGIN REPLICATION NOSUPERUSER PASSWORD %s').format(sql.Identifier(role)),(self.env['CDC_SOURCE_PASSWORD'],))
            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        admin.close()
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('CREATE TABLE orders(id integer PRIMARY KEY, customer text NOT NULL, amount numeric(20,4) NOT NULL, status text NOT NULL)')
                cur.execute("INSERT INTO orders SELECT i,'race',i,'pending' FROM generate_series(1,5000) i")
                cur.execute('ALTER TABLE orders REPLICA IDENTITY FULL')
                cur.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
                cur.execute(sql.SQL('GRANT SELECT ON orders TO {}').format(sql.Identifier(role)))
        source=self.api(11,'POST','/database/sources/',{'name':'snapshot race','engine':'postgres',
            'connection_metadata':{'host':'postgres','port':5432,'database':database,'username':role,'sslmode':'disable'},
            'selected_tables':[{'schema':'public','name':'orders'}],'password':self.env['CDC_SOURCE_PASSWORD']},expected=201)['data']
        errors=[]
        writer_start=int(time.time()*1000)
        def writer():
            try:
                connection=self.pg(database)
                connection.autocommit=True
                deadline=time.monotonic()+20
                i=0
                with connection.cursor() as cur:
                    while time.monotonic()<deadline:
                        cur.execute('UPDATE orders SET amount=%s WHERE id=2500',(i,))
                        i+=1
                        time.sleep(.02)
                    cur.execute("UPDATE orders SET amount=777,status='raced' WHERE id=2500")
                    cur.execute('DELETE FROM orders WHERE id=1')
                    cur.execute("INSERT INTO orders VALUES(5001,'race',5001,'inserted')")
                connection.close()
            except Exception as exc:
                errors.append(type(exc).__name__)
        thread=threading.Thread(target=writer)
        thread.start()
        pipeline=self.api(11,'POST',f"/database/sources/{source['id']}/cdc/enable/",{'schema':'public','table':'orders'},expected=202)['data']
        scope=Scope(11,source['id'],pipeline['id'],pipeline['dataset_id'],'public','orders')
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute(sql.SQL('CREATE PUBLICATION {} FOR TABLE orders').format(sql.Identifier('b_'+scope.token)))
        self.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/resume/',{'pipeline_id':scope.pipeline_id},expected=202)
        thread.join(timeout=30)
        assert not thread.is_alive() and not errors,'concurrent writer failed'
        writer_end=int(time.time()*1000)
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('SELECT id,customer,amount::text,status FROM orders ORDER BY id')
                expected=[list(row) for row in cur.fetchall()]
        def matches():
            try:
                result=self.api(11,'POST','/query/execute/',{'dataset_id':scope.dataset_id,
                    'sql':f'SELECT groupArray(tuple(id,customer,toString(amount),status)) AS records FROM cdc_{scope.token}_current'})
                rows=result.get('rows',[{}])[0].get('records',[])
                # Decimal text scale can differ; preserve exact numeric values.
                normalized=lambda records: sorted((r[0],r[1],Decimal(r[2]),r[3]) for r in records)
                return normalized(rows)==normalized(expected)
            except AssertionError:
                return False
        wait_for('snapshot race exact 5000-row Query result',matches,seconds=300)
        self.compose('run','--rm','--no-deps','acceptance','race','--pipeline',scope.pipeline_id,
                     '--snapshot-from',str(writer_start),'--snapshot-to',str(writer_end))
        elapsed=time.time()-writer_start/1000
        self.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/reconcile/',{'pipeline_id':scope.pipeline_id},expected=202)
        def reconciled():
            return self.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]['reconciliation'].get('status')=='MATCH'
        wait_for('snapshot race bounded reconciliation',reconciled)
        output={'rows':5000,'snapshot_writer_overlap':'PASS','exact_Query_comparison':'PASS','reconciliation':'MATCH',
                'start_to_catchup_seconds':elapsed,'snapshot_rows_per_elapsed_second':5000/elapsed,'production_SLA':False}
        (self.env_file.parent/'race-results.json').write_text(json.dumps(output,indent=2))
        print(json.dumps(output),flush=True)

    def race_verify(self):
        # Verify the persisted fixture after an interrupted or timed-out race.
        items=self.session.get(self.base+'/internal/v1/cdc/',headers={
            'X-Cdc-Stage':'normalize','X-Cdc-Key':self.env['CDC_NORMALIZE_KEY']},timeout=10).json()['pipelines']
        known={s.pipeline_id for s in self.state()}
        scope=Scope(**next(p['scope'] for p in items if p['scope']['pipeline_id'] not in known))
        with self.pg('source_race') as connection:
            with connection.cursor() as cur:
                cur.execute('SELECT id,customer,amount::text,status FROM orders ORDER BY id')
                expected=cur.fetchall()
        normalize=lambda rows:sorted((r[0],r[1],Decimal(str(r[2])),r[3]) for r in rows)
        def matched():
            try:
                result=self.api(11,'POST','/query/execute/',{'dataset_id':scope.dataset_id,
                    'sql':f'SELECT groupArray(tuple(id,customer,toString(amount),status)) AS records FROM cdc_{scope.token}_current'})
                return normalize(result.get('rows',[{}])[0].get('records',[]))==normalize(expected)
            except AssertionError:
                return False
        wait_for('eventual race result equals every source value',matched,seconds=120)
        self.compose('run','--rm','--no-deps','acceptance','race','--pipeline',scope.pipeline_id)
        self.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/reconcile/',{'pipeline_id':scope.pipeline_id},expected=202)
        wait_for('race exact reconciliation',lambda:self.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]['reconciliation'].get('status')=='MATCH')
        output={'rows':len(expected),'exact_Query_comparison':'PASS','snapshot_writer_overlap':'PASS',
                'reconciliation':'MATCH','original_300_second_budget':'FAILED','eventual_duration_seconds':'NOT_RECONSTRUCTED'}
        (self.env_file.parent/'race-results.json').write_text(json.dumps(output,indent=2))
        print(json.dumps(output),flush=True)

    def broker_recovery(self):
        items=self.session.get(self.base+'/internal/v1/cdc/',headers={
            'X-Cdc-Stage':'normalize','X-Cdc-Key':self.env['CDC_NORMALIZE_KEY']},timeout=10).json()['pipelines']
        known={s.pipeline_id for s in self.state()}
        scope=Scope(**next(p['scope'] for p in items if p['scope']['pipeline_id'] not in known))
        def change(value):
            with self.pg('source_race') as connection:
                with connection.cursor() as cur:
                    cur.execute('UPDATE orders SET amount=%s WHERE id=2500',(value,))
        def matches(value):
            try:
                result=self.api(11,'POST','/query/execute/',{'dataset_id':scope.dataset_id,
                    'sql':f'SELECT amount FROM cdc_{scope.token}_current WHERE id=2500'})
                return result.get('rows')==[{'amount':value}]
            except AssertionError:
                return False
        change(778)
        wait_for('upgraded Connect retained offset and captured a new write',lambda:matches(778))
        self.compose('stop','kafka')
        change(779)
        time.sleep(3)
        self.compose('start','kafka')
        started=time.monotonic()
        wait_for('Kafka interruption automatically recovered on Debezium 3.4.3',lambda:matches(779))
        elapsed=time.monotonic()-started
        change(777)
        wait_for('post-Kafka recovery exact final value',lambda:matches(777))
        output={'version':'3.4.3.Final','Kafka_interruption':'PASS','operator_Connect_restart':False,
                'broker_start_to_Query_seconds':elapsed,'old_version_failures_retained':2}
        (self.env_file.parent/'broker-recovery-results.json').write_text(json.dumps(output,indent=2))
        print(json.dumps(output),flush=True)

    def d2_source(self, *, empty=False, row_count=5000):
        suffix=uuid.uuid4().hex[:8]
        database,role='source_d2_'+suffix,'cdc_d2_'+suffix
        admin=self.pg()
        admin.autocommit=True
        with admin.cursor() as cur:
            cur.execute(sql.SQL('CREATE ROLE {} LOGIN REPLICATION NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %s').format(sql.Identifier(role)),
                        (self.env['CDC_SOURCE_PASSWORD'],))
            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        admin.close()
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('CREATE TABLE public.orders (id integer PRIMARY KEY, customer text NOT NULL, amount numeric(20,4) NOT NULL, status text NOT NULL)')
                if not empty:
                    cur.execute("INSERT INTO public.orders SELECT i,'d2',i,'initial' FROM generate_series(1,%s) i",(row_count,))
                cur.execute('ALTER TABLE public.orders REPLICA IDENTITY FULL')
                cur.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
                cur.execute(sql.SQL('GRANT SELECT ON public.orders TO {}').format(sql.Identifier(role)))
        source=self.api(11,'POST','/database/sources/',{
            'name':'D2 raw capture '+suffix, 'engine':'postgres',
            'connection_metadata':{'host':'postgres','port':5432,'database':database,'username':role,'sslmode':'disable'},
            'selected_tables':[{'schema':'public','name':'orders'}], 'password':self.env['CDC_SOURCE_PASSWORD']},expected=201)['data']
        pipeline=self.api(11,'POST',f"/database/sources/{source['id']}/cdc/enable/",{'schema':'public','table':'orders'},expected=202)['data']
        scope=Scope(11,source['id'],pipeline['id'],pipeline['dataset_id'],'public','orders')
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute(sql.SQL('CREATE PUBLICATION {} FOR TABLE public.orders').format(sql.Identifier('b_'+scope.token)))
        def publication_ready():
            state=self.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
            if state['desired_state']=='PAUSED' and state['observed_state']=='PAUSED':
                self.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/resume/',
                         {'pipeline_id':scope.pipeline_id},expected=202)
                return True
            return state['desired_state']=='STREAMING'
        wait_for('exact publication accepted for D2 source',publication_ready,seconds=30)
        return scope,database

    def d2_probe(self, scope, action, *options, seconds=120):
        command=['docker','compose','--project-name','biavora_foundation_d','--env-file',str(self.env_file),
                 '-f',str(ROOT/'docker-compose.cdc-local.yml'),'run','--rm','--no-deps','acceptance',action,
                 '--pipeline',scope.pipeline_id,*map(str,options)]
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,
                                  timeout=150 if action in {'wait_raw','d3_replay_check','d3_restart_check','d3_poison_check'} else 45)
            if result.returncode==0:
                evidence=json.loads(result.stdout.strip().splitlines()[-1])
                print(json.dumps({action:evidence}),flush=True)
                return evidence
            time.sleep(2)
        raise AssertionError('D2 raw probe timed out: '+action)

    def d2_capture(self):
        run_id=uuid.uuid4().hex[:8]
        state_path=self.env_file.parent/f'd2-capture-state-{run_id}.json'
        scope,database=self.d2_source()
        state_path.write_text(json.dumps({'scope':scope.__dict__,'database':database},indent=2))
        errors=[]
        start=int(time.time()*1000)
        def writer():
            try:
                connection=self.pg(database)
                connection.autocommit=True
                with connection.cursor() as cur:
                    deadline=time.monotonic()+20
                    i=0
                    while time.monotonic()<deadline:
                        cur.execute('UPDATE public.orders SET amount=%s WHERE id=2500',(i,))
                        i+=1
                        time.sleep(.03)
                    cur.execute("INSERT INTO public.orders VALUES (5001,'d2',5001,'inserted')")
                    cur.execute("UPDATE public.orders SET amount=9002 WHERE id=2")
                    cur.execute('DELETE FROM public.orders WHERE id=1')
                connection.close()
            except Exception as exc:
                errors.append(type(exc).__name__)
        thread=threading.Thread(target=writer)
        thread.start()
        thread.join(timeout=30)
        assert not thread.is_alive() and not errors, 'D2 controlled writer failed'
        end=int(time.time()*1000)
        evidence=self.d2_probe(scope,'capture','--snapshot-from',start,'--snapshot-to',end,seconds=180)
        (self.env_file.parent/f'd2-capture-results-{run_id}.json').write_text(json.dumps(evidence,indent=2))

    def d2_empty(self):
        run_id=uuid.uuid4().hex[:8]
        state_path=self.env_file.parent/f'd2-empty-state-{run_id}.json'
        scope,database=self.d2_source(empty=True)
        state_path.write_text(json.dumps({'scope':scope.__dict__,'database':database},indent=2))
        time.sleep(20)
        evidence=self.d2_probe(scope,'empty',seconds=90)
        (self.env_file.parent/f'd2-empty-results-{run_id}.json').write_text(json.dumps(evidence,indent=2))

    def d2_recovery(self):
        states=sorted(self.env_file.parent.glob('d2-capture-results-*.json'),key=lambda path:path.stat().st_mtime)
        if not states:
            raise AssertionError('Run a passing D2 capture before recovery')
        run_id=states[-1].stem.removeprefix('d2-capture-results-')
        entry=json.loads((self.env_file.parent/f'd2-capture-state-{run_id}.json').read_text())
        scope,database=Scope(**entry['scope']),entry['database']
        baseline=json.loads(states[-1].read_text())
        def update(amount):
            with self.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute('UPDATE public.orders SET amount=%s WHERE id=2',(amount,))
        def slot():
            with self.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute("SELECT active, restart_lsn::text, confirmed_flush_lsn::text, wal_status, pg_wal_lsn_diff(pg_current_wal_lsn(),restart_lsn)::bigint FROM pg_replication_slots WHERE slot_name=%s",
                                ('b_'+scope.token,))
                    row=cur.fetchone()
            return {'active':row[0], 'restart_lsn':row[1], 'confirmed_flush_lsn':row[2],
                    'wal_status':row[3], 'retained_wal_bytes':row[4]} if row else None
        def connect_data(suffix):
            result=subprocess.run(['docker','exec','biavora_foundation_d-connect-1','curl','-fsS',
                f'http://localhost:8083/connectors/b_{scope.token}/{suffix}'],capture_output=True,text=True,timeout=15)
            return json.loads(result.stdout) if result.returncode==0 else None
        def task_running():
            status=connect_data('status') or {}
            return status.get('connector',{}).get('state')=='RUNNING' and [t.get('state') for t in status.get('tasks',[])]==['RUNNING']
        def captured(amount, label):
            start=time.monotonic()
            update(amount)
            result=self.d2_probe(scope,'wait_raw','--row-id',2,'--amount',amount,seconds=1)
            elapsed=round(time.monotonic()-start,3)
            print(json.dumps({label+'_seconds':elapsed}),flush=True)
            return elapsed,result['lsn']
        evidence={'initial_snapshot_rows':baseline['ops']['r'], 'slot_before':slot(),
                  'offsets_before':connect_data('offsets')}
        assert evidence['slot_before'] and evidence['slot_before']['wal_status'] not in {'lost','unreserved'}
        self.compose('restart','connect')
        wait_for('Connect task running after worker restart',task_running,seconds=120)
        evidence['connect_restart_seconds'],_=captured(9101,'connect_restart_raw')
        status_code=subprocess.run(['docker','exec','biavora_foundation_d-connect-1','curl','-sS','-o','/dev/null','-w','%{http_code}',
            '-X','POST',f'http://localhost:8083/connectors/b_{scope.token}/tasks/0/restart'],
            capture_output=True,text=True,timeout=15)
        assert status_code.returncode==0 and status_code.stdout in {'200','202','204'}, 'task restart request failed'
        wait_for('Debezium task running after task restart',task_running,seconds=120)
        evidence['task_restart_seconds'],_=captured(9102,'task_restart_raw')
        self.compose('stop','postgres')
        evidence['postgres_task_state_during_outage']=[task.get('state') for task in (connect_data('status') or {}).get('tasks',[])]
        self.compose('start','postgres')
        wait_for('PostgreSQL source reconnected',lambda:self.pg(database).close() is None,seconds=120)
        evidence['postgres_recovery_seconds'],_=captured(9103,'postgres_recovery_raw')
        self.compose('restart','controller')
        evidence['controller_restart_seconds'],_=captured(9104,'controller_restart_raw')
        self.compose('stop','kafka')
        update(9105)
        evidence['slot_during_broker_outage']=slot()
        time.sleep(3)
        self.compose('start','kafka')
        def broker_healthy():
            result=subprocess.run(['docker','inspect','--format','{{.State.Health.Status}}','biavora_foundation_d-kafka-1'],
                                  capture_output=True,text=True,timeout=10)
            return result.returncode==0 and result.stdout.strip()=='healthy'
        wait_for('broker restored healthy',broker_healthy,seconds=120)
        broker_restored=time.monotonic()
        wait_for('Connect task running after broker restore',task_running,seconds=180)
        evidence['broker_to_task_healthy_seconds']=round(time.monotonic()-broker_restored,3)
        # The outage write must arrive before the fresh post-restore write.
        self.d2_probe(scope,'wait_raw','--row-id',2,'--amount',9105,seconds=1)
        evidence['broker_to_retained_raw_seconds']=round(time.monotonic()-broker_restored,3)
        evidence['broker_to_fresh_raw_seconds'],_=captured(9106,'broker_fresh_raw')
        evidence['broker_to_fresh_raw_seconds']=round(time.monotonic()-broker_restored,3)
        evidence['slot_after']=slot()
        evidence['offsets_after']=connect_data('offsets')
        final=self.d2_probe(scope,'capture',seconds=60)
        assert final['ops']['r']==baseline['ops']['r'], 'unexpected resnapshot'
        assert evidence['slot_after'] and evidence['slot_after']['wal_status'] not in {'lost','unreserved'}
        before_offset=evidence['offsets_before']['offsets'][0]['offset']['lsn']
        after_offset=evidence['offsets_after']['offsets'][0]['offset']['lsn']
        assert after_offset > before_offset, 'Connect source offset did not advance'
        (self.env_file.parent/f'd2-recovery-results-{run_id}.json').write_text(json.dumps(evidence,indent=2))
        print(json.dumps({'d2_recovery':'PASS','broker_to_fresh_raw_seconds':evidence['broker_to_fresh_raw_seconds'],
                          'unexpected_resnapshot':False}),flush=True)

    def d2_wal_scope(self):
        results=sorted(self.env_file.parent.glob('d2-capture-results-*.json'),key=lambda path:path.stat().st_mtime)
        if not results:
            raise AssertionError('Run passing D2 capture first')
        run_id=results[-1].stem.removeprefix('d2-capture-results-')
        entry=json.loads((self.env_file.parent/f'd2-capture-state-{run_id}.json').read_text())
        scope,database=Scope(**entry['scope']),entry['database']
        def status():
            return self.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        def action(name):
            return self.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/{name}/',
                            {'pipeline_id':scope.pipeline_id},expected=202)
        def slot():
            with self.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute("SELECT active, restart_lsn::text, confirmed_flush_lsn::text, wal_status, pg_wal_lsn_diff(pg_current_wal_lsn(),restart_lsn)::bigint FROM pg_replication_slots WHERE slot_name=%s",
                                ('b_'+scope.token,))
                    row=cur.fetchone()
            return {'active':row[0],'restart_lsn':row[1],'confirmed_flush_lsn':row[2],
                    'wal_status':row[3],'retained_wal_bytes':row[4]} if row else None
        def secret_present():
            result=subprocess.run(['docker','exec','biavora_foundation_d-controller-1','stat','-c','%a',
                '/run/cdc-secrets/'+scope.token+'.properties'],capture_output=True,text=True,timeout=10)
            return result.stdout.strip() if result.returncode==0 else None
        marker=1000000000 + time.time_ns() % 500000000
        started=time.monotonic()
        action('pause')
        wait_for('D2 paused slot inactive',lambda:status()['observed_state']=='PAUSED' and slot() and not slot()['active'],seconds=120)
        pause_elapsed=time.monotonic()-started
        paused=slot()
        assert secret_present() is None, 'stale credential file remained after stop'
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                for value in range(marker,marker+100):
                    cur.execute('UPDATE public.orders SET amount=%s WHERE id=2',(value,))
        accumulated=slot()
        assert accumulated and accumulated['retained_wal_bytes'] >= paused['retained_wal_bytes']
        started=time.monotonic()
        action('resume')
        self.d2_probe(scope,'wait_raw','--row-id',2,'--amount',marker+99,seconds=1)
        retained_resume_elapsed=time.monotonic()-started
        assert retained_resume_elapsed <= 120
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('UPDATE public.orders SET amount=%s WHERE id=2',(marker+100,))
        self.d2_probe(scope,'wait_raw','--row-id',2,'--amount',marker+100,seconds=1)
        wait_for('D2 secret file restored with restrictive permissions',lambda:secret_present()=='600')
        resumed=slot()
        assert resumed and resumed['wal_status'] not in {'lost','unreserved'}
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('CREATE TABLE IF NOT EXISTS public.extra (id integer PRIMARY KEY)')
                cur.execute(sql.SQL('ALTER PUBLICATION {} ADD TABLE public.extra').format(sql.Identifier('b_'+scope.token)))
        drift_started=time.monotonic()
        try:
            wait_for('publication drift stops capture',lambda:status()['desired_state']=='PAUSED' and status()['error_code']=='CDC_PUBLICATION_REQUIRED',seconds=90)
            drift_detect_elapsed=time.monotonic()-drift_started
            wait_for('publication drift leaves slot inactive',lambda:status()['observed_state']=='PAUSED' and slot() and not slot()['active'],seconds=120)
            drift_safe_elapsed=time.monotonic()-drift_started
            assert secret_present() is None
        finally:
            with self.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute(sql.SQL('ALTER PUBLICATION {} DROP TABLE public.extra').format(sql.Identifier('b_'+scope.token)))
        action('resume')
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('UPDATE public.orders SET amount=%s WHERE id=2',(marker+101,))
        self.d2_probe(scope,'wait_raw','--row-id',2,'--amount',marker+101,seconds=1)
        self.api(22,'GET',f'/database/sources/{scope.source_id}/cdc/',expected=404)
        evidence={'paused_slot':paused,'after_paused_writes':accumulated,'resumed_slot':resumed,
                  'write_marker':marker,
                  'pause_elapsed_seconds':round(pause_elapsed,3),
                  'retained_resume_elapsed_seconds':round(retained_resume_elapsed,3),
                  'drift_detect_elapsed_seconds':round(drift_detect_elapsed,3),
                  'drift_safe_elapsed_seconds':round(drift_safe_elapsed,3),
                  'secret_file_mode':'600','stale_file_removed':True,'publication_drift':'REJECTED',
                  'exact_publication_restored':True,'foreign_workspace_status':404,
                  'local_warning_bytes':268435456,'local_slot_cap_bytes':536870912}
        (self.env_file.parent/f'd2-wal-scope-results-{run_id}.json').write_text(json.dumps(evidence,indent=2))
        print(json.dumps({'d2_wal_scope':'PASS','paused_retained_wal_bytes':paused['retained_wal_bytes'],
                          'after_paused_writes_bytes':accumulated['retained_wal_bytes'],
                          'pause_elapsed_seconds':round(pause_elapsed,3),
                          'retained_resume_elapsed_seconds':round(retained_resume_elapsed,3),
                          'drift_detect_elapsed_seconds':round(drift_detect_elapsed,3),
                          'drift_safe_elapsed_seconds':round(drift_safe_elapsed,3),
                          'publication_drift':'REJECTED','credential_mode':'600'}),flush=True)

    def d2_publication_drift(self):
        results=sorted(self.env_file.parent.glob('d2-capture-results-*.json'),key=lambda path:path.stat().st_mtime)
        run_id=results[-1].stem.removeprefix('d2-capture-results-')
        entry=json.loads((self.env_file.parent/f'd2-capture-state-{run_id}.json').read_text())
        scope,database=Scope(**entry['scope']),entry['database']
        def status():
            return self.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        assert status()['observed_state']=='PAUSED', 'capture must be paused before drift test'
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('CREATE TABLE IF NOT EXISTS public.extra (id integer PRIMARY KEY)')
                cur.execute(sql.SQL('ALTER PUBLICATION {} ADD TABLE public.extra').format(sql.Identifier('b_'+scope.token)))
        try:
            self.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/resume/',
                     {'pipeline_id':scope.pipeline_id},expected=202)
            wait_for('exact publication drift rejected',lambda:status()['error_code']=='CDC_PUBLICATION_REQUIRED',seconds=90)
            self.api(22,'GET',f'/database/sources/{scope.source_id}/cdc/',expected=404)
        finally:
            with self.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute('SELECT 1 FROM pg_publication_tables WHERE pubname=%s AND schemaname=%s AND tablename=%s',
                                ('b_'+scope.token,'public','extra'))
                    if cur.fetchone():
                        cur.execute(sql.SQL('ALTER PUBLICATION {} DROP TABLE public.extra').format(sql.Identifier('b_'+scope.token)))
        evidence={'error_code':status()['error_code'],'foreign_workspace_status':404,
                  'extra_table_removed_from_publication':True}
        (self.env_file.parent/f'd2-publication-drift-results-{run_id}.json').write_text(json.dumps(evidence,indent=2))
        print(json.dumps({'d2_publication_drift':'REJECTED','foreign_workspace_status':404}),flush=True)

    def d2_control_restart(self):
        results=sorted(self.env_file.parent.glob('d2-capture-results-*.json'),key=lambda path:path.stat().st_mtime)
        run_id=results[-1].stem.removeprefix('d2-capture-results-')
        entry=json.loads((self.env_file.parent/f'd2-capture-state-{run_id}.json').read_text())
        scope,database=Scope(**entry['scope']),entry['database']
        def status():
            return self.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        def action(name):
            return self.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/{name}/',
                            {'pipeline_id':scope.pipeline_id},expected=202)
        def slot_active():
            with self.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute('SELECT active FROM pg_replication_slots WHERE slot_name=%s',('b_'+scope.token,))
                    row=cur.fetchone()
            return row[0] if row else None
        def task_running():
            response=subprocess.run(['docker','exec','biavora_foundation_d-connect-1','curl','-fsS',
                'http://localhost:8083/connectors/b_'+scope.token+'/status'],capture_output=True,text=True,timeout=15)
            if response.returncode:
                return False
            state=json.loads(response.stdout)
            return (state['connector']['state']=='RUNNING' and len(state['tasks'])==1
                    and state['tasks'][0]['state']=='RUNNING')
        with self.pg('biavora') as connection:
            with connection.cursor() as cur:
                cur.execute("SELECT count(*) FROM integration_cdc_pipelines p JOIN integration_data_sources s ON s.id=p.source_id WHERE s.state='retired' AND p.desired_state<>'STOPPED'")
                retired_stale=cur.fetchone()[0]
        assert retired_stale >= 1, 'stale retired fairness fixture is absent'
        started=time.monotonic()
        action('pause')
        self.compose('restart','controller')
        wait_for('pause converged after controller restart',lambda:status()['observed_state']=='PAUSED' and slot_active() is False,seconds=120)
        pause_elapsed=time.monotonic()-started
        started=time.monotonic()
        action('resume')
        self.compose('restart','controller')
        wait_for('no-write resume converged after controller restart',lambda:task_running() and slot_active() is True,seconds=120)
        resume_elapsed=time.monotonic()-started
        marker=1500000000 + time.time_ns() % 500000000
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('UPDATE public.orders SET amount=%s WHERE id=2',(marker,))
        self.d2_probe(scope,'wait_raw','--row-id',2,'--amount',marker,seconds=1)
        evidence={'retired_stale_scopes':retired_stale,'pause_after_restart_seconds':round(pause_elapsed,3),
                  'no_write_resume_after_restart_seconds':round(resume_elapsed,3),
                  'task_running_slot_active':True,'fresh_write_captured':True}
        (self.env_file.parent/f'd2-control-restart-results-{run_id}.json').write_text(json.dumps(evidence,indent=2))
        print(json.dumps({'d2_control_restart':'PASS',**evidence}),flush=True)

    def d2_publication_variants(self):
        results=sorted(self.env_file.parent.glob('d2-capture-results-*.json'),key=lambda path:path.stat().st_mtime)
        run_id=results[-1].stem.removeprefix('d2-capture-results-')
        entry=json.loads((self.env_file.parent/f'd2-capture-state-{run_id}.json').read_text())
        scope,database=Scope(**entry['scope']),entry['database']
        publication=sql.Identifier('b_'+scope.token)
        def status():
            return self.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        def inactive():
            with self.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute('SELECT active FROM pg_replication_slots WHERE slot_name=%s',('b_'+scope.token,))
                    row=cur.fetchone()
            return row is not None and row[0] is False
        variants=(
            ('remove_selected','ALTER PUBLICATION {} DROP TABLE public.orders','CDC_PUBLICATION_REQUIRED'),
            ('row_filter','ALTER PUBLICATION {} SET TABLE public.orders WHERE (id > 0)','CDC_PUBLICATION_FILTER_UNSUPPORTED'),
            ('column_list','ALTER PUBLICATION {} SET TABLE public.orders (id,customer,amount)','CDC_PUBLICATION_FILTER_UNSUPPORTED'),
        )
        evidence={}
        for name,command,code in variants:
            assert status()['desired_state']=='STREAMING', 'source must be streaming before drift mutation'
            with self.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute(sql.SQL(command).format(publication))
            started=time.monotonic()
            try:
                wait_for(name+' drift detected',lambda:status()['desired_state']=='PAUSED' and status()['error_code']==code,seconds=90)
                detected=time.monotonic()-started
                wait_for(name+' slot inactive',lambda:status()['observed_state']=='PAUSED' and inactive(),seconds=120)
            finally:
                with self.pg(database) as connection:
                    with connection.cursor() as cur:
                        cur.execute(sql.SQL('ALTER PUBLICATION {} SET TABLE public.orders').format(publication))
            self.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/resume/',
                     {'pipeline_id':scope.pipeline_id},expected=202)
            marker=1200000000 + time.time_ns() % 300000000
            with self.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute('UPDATE public.orders SET amount=%s WHERE id=2',(marker,))
            self.d2_probe(scope,'wait_raw','--row-id',2,'--amount',marker,seconds=1)
            evidence[name]={'error_code':code,'detected_seconds':round(detected,3),
                            'slot_inactive':True,'recovered_raw':True}
        (self.env_file.parent/f'd2-publication-variants-results-{run_id}.json').write_text(json.dumps(evidence,indent=2))
        print(json.dumps({'d2_publication_variants':'PASS',**evidence}),flush=True)

    def d3_accept(self):
        run_id=uuid.uuid4().hex[:8]
        scope,database=self.d2_source(row_count=3)
        state={'scope':scope.__dict__,'database':database,'run_id':run_id}
        (self.env_file.parent/f'd3-state-{run_id}.json').write_text(json.dumps(state,indent=2))
        evidence={'run_id':run_id,'scope_token':scope.token}
        evidence['snapshot']=self.d2_probe(scope,'d3_snapshot',seconds=120)
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute("INSERT INTO public.orders VALUES (4,'d3',40,'new')")
                cur.execute("UPDATE public.orders SET amount=41,status='updated' WHERE id=4")
                cur.execute('DELETE FROM public.orders WHERE id=4')
        self._d3_accept_remaining(scope,database,run_id,evidence)

    def d3_continue(self):
        states=sorted(self.env_file.parent.glob('d3-state-*.json'),key=lambda path:path.stat().st_mtime)
        assert states, 'D3 source state missing'
        state=json.loads(states[-1].read_text())
        scope,database,run_id=Scope(**state['scope']),state['database'],state['run_id']
        status=self.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        if status['desired_state']=='PAUSED':
            self.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/resume/',
                     {'pipeline_id':scope.pipeline_id},expected=202)
        evidence={'run_id':run_id,'scope_token':scope.token,'snapshot':self.d2_probe(scope,'d3_snapshot',seconds=120),
                  'recovered_first_marker':True}
        self._d3_accept_remaining(scope,database,run_id,evidence)

    def _d3_accept_remaining(self,scope,database,run_id,evidence):
        evidence['stages']=self.d2_probe(scope,'d3_inspect',seconds=120)
        evidence['injection']=self.d2_probe(scope,'d3_replay',seconds=60)
        evidence['replay']=self.d2_probe(scope,'d3_replay_check',seconds=120)
        self.compose('restart','normalizer')
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('UPDATE public.orders SET amount=2026 WHERE id=2')
        evidence['restart']=self.d2_probe(scope,'d3_restart_check',seconds=120)
        self._d3_poison(scope,database,run_id,evidence,('malformed','foreign','unsupported','schema'))

    def d3_poison_continue(self):
        states=sorted(self.env_file.parent.glob('d3-state-*.json'),key=lambda path:path.stat().st_mtime)
        assert states, 'D3 source state missing'
        state=json.loads(states[-1].read_text())
        scope,database,run_id=Scope(**state['scope']),state['database'],state['run_id']
        evidence={'run_id':run_id,'scope_token':scope.token,'recovered_first_marker':True,
                  'malformed_observed':self.d2_probe(scope,'d3_malformed_history',seconds=60)}
        self._d3_poison(scope,database,run_id,evidence,('foreign','unsupported','schema'))

    def d3_status(self):
        states=sorted(self.env_file.parent.glob('d3-state-*.json'),key=lambda path:path.stat().st_mtime)
        state=json.loads(states[-1].read_text())
        scope,database=Scope(**state['scope']),state['database']
        status=self.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('SELECT active,wal_status FROM pg_replication_slots WHERE slot_name=%s',('b_'+scope.token,))
                slot=cur.fetchone()
        print(json.dumps({'desired_state':status['desired_state'],'observed_state':status['observed_state'],
                          'error_code':status.get('error_code'),'slot_active':slot[0] if slot else None,
                          'wal_status':slot[1] if slot else None}),flush=True)

    def d3_finish(self):
        states=sorted(self.env_file.parent.glob('d3-state-*.json'),key=lambda path:path.stat().st_mtime)
        state=json.loads(states[-1].read_text())
        scope,database,run_id=Scope(**state['scope']),state['database'],state['run_id']
        evidence=json.loads((self.env_file.parent/f'd3-progress-{run_id}.json').read_text())
        evidence['poison']['schema']=self.d2_probe(scope,'d3_poison_check','--kind','schema',seconds=60)
        status=self.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('SELECT active FROM pg_replication_slots WHERE slot_name=%s',('b_'+scope.token,))
                slot=cur.fetchone()
        assert status['desired_state']=='PAUSED' and status['observed_state']=='RESEED_REQUIRED'
        assert status['error_code']=='CDC_SCHEMA_INCOMPATIBLE' and slot and slot[0] is False
        evidence['schema_lifecycle']={'observed_state':'RESEED_REQUIRED','slot_active':False}
        evidence['history']=self.d2_probe(scope,'d3_history',seconds=60)
        evidence['foreign_workspace_unchanged']=self.api(22,'GET',f'/database/sources/{scope.source_id}/cdc/',expected=404) is not None
        (self.env_file.parent/f'd3-results-{run_id}.json').write_text(json.dumps(evidence,indent=2))
        print(json.dumps({'d3_finish':'PASS','run_id':run_id,'scope_token':scope.token,
                          'schema_lifecycle':'RESEED_REQUIRED','poison_cases':list(evidence['poison'])}),flush=True)

    def d3_clean(self):
        run_id=uuid.uuid4().hex[:8]
        scope,database=self.d2_source(row_count=3)
        evidence={'run_id':run_id,'scope_token':scope.token,
                  'snapshot':self.d2_probe(scope,'d3_snapshot',seconds=120)}
        with self.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute("INSERT INTO public.orders VALUES (4,'d3',40,'new')")
                cur.execute("UPDATE public.orders SET amount=41,status='updated' WHERE id=4")
                cur.execute('DELETE FROM public.orders WHERE id=4')
        evidence['stages']=self.d2_probe(scope,'d3_inspect','--kind','clean',seconds=120)
        self.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/pause/',
                 {'pipeline_id':scope.pipeline_id},expected=202)
        (self.env_file.parent/f'd3-clean-results-{run_id}.json').write_text(json.dumps(evidence,indent=2))
        print(json.dumps({'d3_clean':'PASS','run_id':run_id,'scope_token':scope.token,
                          'raw_normalized_transformed':True,'dlq_records':0}),flush=True)

    def _d3_poison(self,scope,database,run_id,evidence,kinds):
        def status():
            return self.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        def inactive():
            with self.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute('SELECT active FROM pg_replication_slots WHERE slot_name=%s',('b_'+scope.token,))
                    row=cur.fetchone()
            return row is not None and row[0] is False
        for kind in kinds:
            injected=self.d2_probe(scope,'d3_inject','--kind',kind,seconds=60)
            outcome=self.d2_probe(scope,'d3_poison_check','--kind',kind,
                                  '--row-id',injected['offset'],seconds=120)
            evidence.setdefault('poison',{})[kind]=outcome
            target='RESEED_REQUIRED' if kind=='schema' else 'PAUSED'
            wait_for(f'D3 {kind} physical pause',lambda:status()['observed_state']==target and inactive(),seconds=120)
            if kind=='schema':
                evidence['schema_lifecycle']={'observed_state':target,'slot_active':False}
            (self.env_file.parent/f'd3-progress-{run_id}.json').write_text(json.dumps(evidence,indent=2))
            if kind!=kinds[-1]:
                self.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/resume/',
                         {'pipeline_id':scope.pipeline_id},expected=202)
                wait_for(f'D3 {kind} resume',lambda:status()['desired_state']=='STREAMING',seconds=30)
        evidence['foreign_workspace_unchanged']=self.api(22,'GET',f'/database/sources/{scope.source_id}/cdc/',expected=404) is not None
        (self.env_file.parent/f'd3-results-{run_id}.json').write_text(json.dumps(evidence,indent=2))
        print(json.dumps({'d3_accept':'PASS','run_id':run_id,'scope_token':scope.token,
                          'poison_cases':list(evidence['poison']),'foreign_workspace_unchanged':True}),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--env-file',required=True)
    parser.add_argument('--phase',choices=['bootstrap','check','recovery','storage_recovery','lifecycle','race','race_verify','broker_recovery','d2_capture','d2_empty','d2_recovery','d2_wal_scope','d2_publication_drift','d2_control_restart','d2_publication_variants','d3_accept','d3_continue','d3_poison_continue','d3_status','d3_finish','d3_clean'],required=True)
    args=parser.parse_args()
    fixture=Fixture(args.env_file)
    getattr(fixture,args.phase)()
