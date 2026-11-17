"""Bounded Foundation-D D4 live acceptance against the disposable CDC stack."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys
import subprocess
import time
import uuid
import statistics

from psycopg2 import sql

from verify_foundation_d_cdc import Fixture, wait_for


def main(env_file, phase):
    fixture = Fixture(env_file)
    state_file = Path(env_file).resolve().parent / 'd4-state.json'
    if phase == 'capacity':
        with fixture.pg() as connection:
            with connection.cursor() as cur:
                cur.execute('SHOW max_replication_slots')
                maximum=int(cur.fetchone()[0])
                cur.execute('SELECT count(*) FROM pg_replication_slots')
                used=cur.fetchone()[0]
        print(json.dumps({'max_replication_slots':maximum,'slots_used':used}),flush=True)
        return
    if phase == 'binding_verify':
        from bi_platform_shared.cdc_contract import Scope
        directory=Path(env_file).resolve().parent
        saved=[json.loads((directory/name).read_text()) for name in
               ('d4-state.json','d4-typed-state.json','d4-performance-state.json')]
        scopes=[Scope(**entry['scope']) for entry in saved]
        with fixture.pg('biavora') as connection:
            with connection.cursor() as cur:
                cur.execute('SELECT id,etl_status,clickhouse_database,clickhouse_table_name,source_kind '
                            'FROM manager_databases WHERE id=ANY(%s)',([scope.dataset_id for scope in scopes],))
                rows=cur.fetchall()
        by_id={row[0]:row for row in rows}
        assert len(by_id)==3
        for scope in scopes:
            assert by_id[scope.dataset_id][1:]==(
                'completed','etl',f'cdc_{scope.token}_current','cdc')
        typed=scopes[1]
        objects=list(fixture.ch.query('SELECT name,engine,sorting_key FROM system.tables '
            'WHERE database={database:String} AND name IN ({versions:String},{view:String})',
            parameters={'database':'etl','versions':f'cdc_{typed.token}_versions',
                        'view':f'cdc_{typed.token}_current'}).named_results())
        versions=next(row for row in objects if row['name'].endswith('_versions'))
        assert versions['engine']=='MergeTree'
        assert versions['sorting_key'].replace(' ','')=='id,part,_cdc_version'
        print(json.dumps({'phase':phase,'datasets':[scope.dataset_id for scope in scopes],
                          'exact_current_view_bindings':True,'composite_sorting_key':versions['sorting_key']}),flush=True)
        return
    if phase == 'performance':
        started=time.monotonic()
        scope,database=fixture.d2_source(row_count=5000)
        (Path(env_file).resolve().parent/'d4-performance-state.json').write_text(
            json.dumps({'scope':scope.__dict__,'database':database},indent=2))
        with fixture.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('SELECT id,customer,amount::text,status FROM orders ORDER BY id')
                source=[(r[0],r[1],Decimal(r[2]),r[3]) for r in cur.fetchall()]
        assert len(source)==5000
        versions=f'etl.cdc_{scope.token}_versions'
        view=f'etl.cdc_{scope.token}_current'
        first=transformed_ready=final=None
        last_progress=0
        deadline=time.monotonic()+900
        while time.monotonic()<deadline:
            result=subprocess.run(['docker','exec','biavora_foundation_d-loader-1','python',
                                   '/acceptance/foundation_d4_kafka_probe.py','--token',scope.token,
                                   'fast_state'],capture_output=True,text=True,timeout=45)
            assert result.returncode==0, result.returncode
            broker=json.loads(result.stdout.strip().splitlines()[-1])
            try:
                physical=fixture.ch.query(f'SELECT count() FROM {versions}').result_rows[0][0]
            except Exception:
                physical=0
            now=time.monotonic()
            if physical and first is None:
                first=now
            if broker['transformed_end_offset']>=5000 and transformed_ready is None:
                transformed_ready=now
            if physical>=5000 and final is None:
                final=now
            if now-last_progress>30:
                print(json.dumps({'progress_rows':physical,
                                  'transformed_end':broker['transformed_end_offset'],
                                  'elapsed_seconds':round(now-started,1)}),flush=True)
                last_progress=now
            if final is not None and transformed_ready is not None:
                break
            time.sleep(3)
        assert first is not None and transformed_ready is not None and final is not None
        assert physical==5000
        sql_text=f'SELECT groupArray(tuple(id,customer,toString(amount),status)) AS records FROM cdc_{scope.token}_current'
        query_latency=None
        def exact():
            nonlocal query_latency
            queried_at=time.monotonic()
            try:
                response=fixture.api(11,'POST','/query/execute/',
                                     {'dataset_id':scope.dataset_id,'sql':sql_text})
            except AssertionError:
                return False
            query_latency=(time.monotonic()-queried_at)*1000
            rows=response.get('rows',[{}])[0].get('records',[])
            return sorted((r[0],r[1],Decimal(r[2]),r[3]) for r in rows)==source
        wait_for('D4 5000-row exact authorized Query result',exact,seconds=300)
        query_done=time.monotonic()
        times=[]
        for _ in range(5):
            t=time.perf_counter()
            count=fixture.ch.query(f'SELECT count() FROM {view}').result_rows[0][0]
            times.append(round((time.perf_counter()-t)*1000,2))
            assert count==5000
        output={'scope':scope.token,'rows':5000,'source_to_first_apply_seconds':round(first-started,2),
                'source_to_transformed_ready_seconds':round(transformed_ready-started,2),
                'transformed_ready_to_final_apply_seconds':round(final-transformed_ready,2),
                'final_apply_to_exact_Query_seconds':round(query_done-final,2),
                'total_source_to_exact_Query_seconds':round(query_done-started,2),
                'authorized_exact_query_latency_ms':round(query_latency,2),
                'view_count_latency_ms':times,'physical_rows':physical,'logical_rows':count,
                'per_event_warehouse_writes':True,'production_capacity_claim':False}
        (Path(env_file).resolve().parent/'d4-performance-results.json').write_text(json.dumps(output,indent=2))
        print(json.dumps({'performance':output}),flush=True)
        return
    if phase == 'final_pin':
        from bi_platform_shared.cdc_contract import Scope
        saved=json.loads((Path(env_file).resolve().parent/'d4-performance-state.json').read_text())
        live=Scope(**saved['scope'])
        with fixture.pg(saved['database']) as connection:
            with connection.cursor() as cur:
                cur.execute('UPDATE orders SET amount=7777 WHERE id=2500')
        captured=fixture.d2_probe(live,'wait_raw','--row-id',2500,'--amount',7777,seconds=150)
        assert captured['raw_match']
        def query_exact():
            try:
                response=fixture.api(11,'POST','/query/execute/',{'dataset_id':live.dataset_id,
                    'sql':f'SELECT amount FROM cdc_{live.token}_current WHERE id=2500'})
                return len(response['rows'])==1 and Decimal(str(response['rows'][0]['amount']))==Decimal(7777)
            except AssertionError:
                return False
        wait_for('D4 final-pin fresh raw event reached authorized Query',query_exact,seconds=150)
        print(json.dumps({'phase':phase,'scope':live.token,'raw_capture':True,'query_exact':True}),flush=True)
        return
    if phase == 'typed_create':
        suffix = uuid.uuid4().hex[:8]
        database, role = 'source_d4_' + suffix, 'cdc_d4_' + suffix
        admin = fixture.pg()
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(sql.SQL('CREATE ROLE {} LOGIN REPLICATION NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %s').format(sql.Identifier(role)),
                        (fixture.env['CDC_SOURCE_PASSWORD'],))
            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        admin.close()
        key = str(uuid.uuid4())
        with fixture.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('''CREATE TABLE public.typed_rows (
                    id integer NOT NULL, part uuid NOT NULL, smallv smallint NOT NULL,
                    bigv bigint NOT NULL, flag boolean NOT NULL, label varchar(40) NOT NULL,
                    day date NOT NULL, local_ts timestamp without time zone NOT NULL,
                    utc_ts timestamp with time zone NOT NULL, nullable_text text,
                    doc jsonb NOT NULL, json_text json NOT NULL,
                    money numeric(30,10) NOT NULL, PRIMARY KEY (id, part))''')
                cur.execute('ALTER TABLE public.typed_rows REPLICA IDENTITY FULL')
                cur.execute('''INSERT INTO public.typed_rows VALUES
                    (7,%s,-123,9223372036854775000,true,'Unicode Ω','2024-02-29',
                     '2024-02-29 12:34:56.123456','2024-02-29 14:34:56.654321+02',
                     NULL,%s::jsonb,%s::json,12345678901234567890.1234567890)''',
                    (key, '{"z":null,"a":{"unicode":"مرحبا","n":12345678901234567890.123456789}}',
                     '{"b":[1,true,null],"a":"Ω"}'))
                cur.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
                cur.execute(sql.SQL('GRANT SELECT ON public.typed_rows TO {}').format(sql.Identifier(role)))
        source = fixture.api(11,'POST','/database/sources/',{
            'name':'D4 typed '+suffix,'engine':'postgres',
            'connection_metadata':{'host':'postgres','port':5432,'database':database,
                                   'username':role,'sslmode':'disable'},
            'selected_tables':[{'schema':'public','name':'typed_rows'}],
            'password':fixture.env['CDC_SOURCE_PASSWORD']},expected=201)['data']
        pipeline = fixture.api(11,'POST',f"/database/sources/{source['id']}/cdc/enable/",
                               {'schema':'public','table':'typed_rows'},expected=202)['data']
        from bi_platform_shared.cdc_contract import Scope
        scope = Scope(11,source['id'],pipeline['id'],pipeline['dataset_id'],'public','typed_rows')
        with fixture.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute(sql.SQL('CREATE PUBLICATION {} FOR TABLE public.typed_rows').format(sql.Identifier('b_'+scope.token)))
        typed_state = {'scope':scope.__dict__,'database':database,'key':key}
        (Path(env_file).resolve().parent/'d4-typed-state.json').write_text(json.dumps(typed_state,indent=2))
        def ready():
            state=fixture.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
            if state['desired_state']=='PAUSED' and state['observed_state']=='PAUSED':
                fixture.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/resume/',
                            {'pipeline_id':scope.pipeline_id},expected=202)
            try:
                result=fixture.api(11,'POST','/query/execute/',{'dataset_id':scope.dataset_id,
                    'sql':f'SELECT * FROM cdc_{scope.token}_current'})
                return result if result.get('rows') else False
            except AssertionError:
                return False
        result=wait_for('D4 typed composite snapshot Query publication',ready,seconds=180)
        print(json.dumps({'phase':phase,'scope':scope.token,'dataset_id':scope.dataset_id,
                          'source_database':database,'query_row':result['rows'][0]},ensure_ascii=True),flush=True)
        return
    if phase == 'typed_diagnose':
        typed = json.loads((Path(env_file).resolve().parent/'d4-typed-state.json').read_text())
        from bi_platform_shared.cdc_contract import Scope
        scope = Scope(**typed['scope'])
        state = fixture.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        with fixture.pg(typed['database']) as connection:
            with connection.cursor() as cur:
                cur.execute("SELECT attname,format_type(atttypid,atttypmod) FROM pg_attribute WHERE attrelid='public.typed_rows'::regclass AND attnum>0 ORDER BY attnum")
                catalog = cur.fetchall()
        print(json.dumps({'state':state,'catalog':catalog},default=str),flush=True)
        return
    if phase == 'typed_repair_fixture':
        typed = json.loads((Path(env_file).resolve().parent/'d4-typed-state.json').read_text())
        from bi_platform_shared.cdc_contract import Scope
        scope = Scope(**typed['scope'])
        with fixture.pg(typed['database']) as connection:
            with connection.cursor() as cur:
                cur.execute('ALTER TABLE public.typed_rows ALTER COLUMN local_ts TYPE timestamp without time zone')
                cur.execute('ALTER TABLE public.typed_rows ALTER COLUMN utc_ts TYPE timestamp with time zone')
        fixture.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/resume/',
                    {'pipeline_id':scope.pipeline_id},expected=202)
        view = f'cdc_{scope.token}_current'
        def ready():
            try:
                result = fixture.api(11,'POST','/query/execute/',
                        {'dataset_id':scope.dataset_id,'sql':f'SELECT * FROM {view}'})
                return result if result.get('rows') else False
            except AssertionError:
                return False
        result = wait_for('D4 supported typed composite snapshot Query publication',ready,seconds=180)
        print(json.dumps({'scope':scope.token,'query_row':result['rows'][0]},ensure_ascii=True),flush=True)
        return
    if phase == 'typed_check':
        typed = json.loads((Path(env_file).resolve().parent/'d4-typed-state.json').read_text())
        from bi_platform_shared.cdc_contract import Scope
        scope = Scope(**typed['scope'])
        view = f'cdc_{scope.token}_current'
        def query():
            return fixture.api(11,'POST','/query/execute/',
                               {'dataset_id':scope.dataset_id,'sql':f'SELECT * FROM {view} ORDER BY id,part'})['rows']
        initial = query()
        assert len(initial) == 1
        row = initial[0]
        print(json.dumps({'typed_initial':row},ensure_ascii=True),flush=True)
        assert row['id'] == 7 and row['part'].lower() == typed['key']
        assert row['smallv'] == -123 and row['bigv'] == 9223372036854775000
        assert row['flag'] is True and row['label'] == 'Unicode Ω'
        assert row['day'] == '2024-02-29' and row['nullable_text'] is None
        assert Decimal(str(row['money'])) == Decimal('12345678901234567890.1234567890')
        assert row['local_ts'] == '2024-02-29T12:34:56.123456'
        assert row['utc_ts'] == '2024-02-29T12:34:56.654321'
        assert json.loads(row['doc'], parse_float=Decimal) == {
            'z':None,'a':{'unicode':'مرحبا','n':Decimal('12345678901234567890.123456789')}}
        assert json.loads(row['json_text']) == {'b':[1,True,None],'a':'Ω'}
        assert set(row) == {'id','part','smallv','bigv','flag','label','day','local_ts',
                            'utc_ts','nullable_text','doc','json_text','money'}
        with fixture.pg(typed['database']) as connection:
            with connection.cursor() as cur:
                cur.execute('UPDATE typed_rows SET money=98765432109876543210.9876543210,nullable_text=%s WHERE id=7 AND part=%s',
                            ('updated',typed['key']))
        wait_for('D4 composite UPDATE exact Query',lambda: len(query())==1 and
                 Decimal(str(query()[0]['money']))==Decimal('98765432109876543210.9876543210'),seconds=120)
        with fixture.pg(typed['database']) as connection:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM typed_rows WHERE id=7 AND part=%s',(typed['key'],))
        wait_for('D4 composite DELETE Query absent',lambda: query()==[],seconds=120)
        print(json.dumps({'phase':phase,'scope':scope.token,'composite_update_delete':'PASS',
                          'exact_decimal':'PASS','timestamps':'PASS','json':'PASS'}),flush=True)
        return
    if phase == 'typed_absent':
        typed=json.loads((Path(env_file).resolve().parent/'d4-typed-state.json').read_text())
        from bi_platform_shared.cdc_contract import Scope
        typed_scope=Scope(**typed['scope'])
        for _ in range(3):
            result=fixture.api(11,'POST','/query/execute/',{'dataset_id':typed_scope.dataset_id,
                'sql':f'SELECT * FROM cdc_{typed_scope.token}_current'})
            assert result['rows']==[]
            time.sleep(1)
        print(json.dumps({'phase':phase,'scope':typed_scope.token,'stale_composite_replay_absent':True}),flush=True)
        return
    if phase == 'typed_reinsert':
        typed=json.loads((Path(env_file).resolve().parent/'d4-typed-state.json').read_text())
        from bi_platform_shared.cdc_contract import Scope
        typed_scope=Scope(**typed['scope'])
        with fixture.pg(typed['database']) as connection:
            with connection.cursor() as cur:
                cur.execute('''INSERT INTO public.typed_rows VALUES
                    (7,%s,-123,9223372036854775000,true,'Unicode Ω','2024-02-29',
                     '2024-02-29 12:34:56.123456','2024-02-29 14:34:56.654321+02',
                     NULL,%s::jsonb,%s::json,12345678901234567890.1234567890)''',
                    (typed['key'],'{"z":null,"a":{"unicode":"مرحبا","n":12345678901234567890.123456789}}',
                     '{"b":[1,true,null],"a":"Ω"}'))
        view=f'cdc_{typed_scope.token}_current'
        def exact():
            try:
                response=fixture.api(11,'POST','/query/execute/',
                                     {'dataset_id':typed_scope.dataset_id,'sql':f'SELECT * FROM {view}'})
            except AssertionError:
                return False
            rows=response.get('rows',[])
            return len(rows)==1 and rows[0]['bigv']=='9223372036854775000' and \
                rows[0]['money']=='12345678901234567890.1234567890'
        wait_for('D4 newer composite reinsert exact Int64/Decimal Query text',exact,seconds=120)
        nested=fixture.api(11,'POST','/query/execute/',{'dataset_id':typed_scope.dataset_id,
            'sql':f'SELECT groupArray(tuple(id,bigv)) AS records FROM {view}'})
        assert nested['rows']==[{'records':[[7,'9223372036854775000']]}]
        print(json.dumps({'phase':phase,'scope':typed_scope.token,
                          'newer_reinsert_visible':True,'int64_json_exact':True,
                          'nested_int64_json_exact':True,'decimal_exact':True}),flush=True)
        return
    if phase == 'create':
        scope, database = fixture.d2_source(row_count=3)
        state_file.write_text(json.dumps({'scope': scope.__dict__, 'database': database}, indent=2))
        expected = [[i, 'd2', Decimal(i), 'initial'] for i in (1, 2, 3)]
        wait_for('D4 fresh snapshot authorized Query publication',
                 lambda: fixture.rows_equal(scope, expected), seconds=180)
        status = fixture.api(11, 'GET', f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        assert status['observed_state'] == 'STREAMING'
        print(json.dumps({'phase': phase, 'scope': scope.token, 'dataset_id': scope.dataset_id,
                          'source_database': database, 'initial_rows': 3, 'publication': 'PASS'}), flush=True)
        return
    from bi_platform_shared.cdc_contract import Scope
    state = json.loads(state_file.read_text())
    scope = Scope(**state['scope'])
    database = state['database']
    def probe(action):
        result=subprocess.run(['docker','exec','biavora_foundation_d-loader-1','python',
                               '/acceptance/foundation_d4_kafka_probe.py','--token',scope.token,action],
                              capture_output=True,text=True,timeout=45)
        assert result.returncode==0, (action,result.returncode)
        return json.loads(result.stdout.strip().splitlines()[-1])
    def probe_stopped(scope):
        result=subprocess.run(['docker','exec','biavora_foundation_d-normalizer-1','python',
                               '/acceptance/foundation_d4_kafka_probe.py','--token',scope.token,
                               '--stage','normalize','state'],capture_output=True,text=True,timeout=45)
        assert result.returncode==0, result.returncode
        return json.loads(result.stdout.strip().splitlines()[-1])
    if phase == 'diagnose':
        status = fixture.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        names = (f'cdc_{scope.token}_versions',f'cdc_{scope.token}_current')
        rows = list(fixture.ch.query('SELECT name,engine,sorting_key,create_table_query FROM system.tables '
                                     'WHERE database = {db:String} AND name IN ({a:String},{b:String})',
                                     parameters={'db':'etl','a':names[0],'b':names[1]}).named_results())
        print(json.dumps({'scope':scope.token,'status':status,'objects':rows},default=str),flush=True)
        return
    if phase == 'ready':
        expected = [[i, 'd2', Decimal(i), 'initial'] for i in (1,2,3)]
        wait_for('D4 retained callback replay published the fresh view',
                 lambda: fixture.rows_equal(scope,expected),seconds=120)
        print(json.dumps({'phase':phase,'scope':scope.token,'snapshot_rows':3}),flush=True)
        return
    if phase == 'replay_check':
        expected = [[i,'d2',Decimal(i),'initial'] for i in (1,2,3)] + [
            [4,'reborn',Decimal(400),'newer']]
        for _ in range(5):
            assert fixture.rows_equal(scope,expected), 'reverse replay changed authorized Query state'
            time.sleep(1)
        print(json.dumps({'phase':phase,'scope':scope.token,'repeated_query_stable':True}),flush=True)
        return
    if phase == 'authority':
        view=f'cdc_{scope.token}_current'
        physical=f'cdc_{scope.token}_versions'
        headers={'Authorization':'Bearer '+fixture.token(11)}
        results={}
        for label,body in (
            ('physical_table',{'dataset_id':scope.dataset_id,'sql':f'SELECT * FROM {physical}'}),
            ('technical_column',{'dataset_id':scope.dataset_id,'sql':f'SELECT _cdc_version FROM {view}'}),
            ('non_allowed_table',{'dataset_id':scope.dataset_id,'sql':'SELECT * FROM unrelated_table'}),
            ('physical_override',{'dataset_id':scope.dataset_id,'workspace_database':'etl',
                                  'sql':f'SELECT * FROM {view}'})):
            response=fixture.session.post(fixture.base+'/query/execute/',headers=headers,json=body,timeout=15)
            assert response.status_code in (400,403), (label,response.status_code)
            assert not response.json().get('rows'), label
            results[label]=response.status_code
        for endpoint in ('schema','preview'):
            response=fixture.session.get(fixture.base+f'/database/{endpoint}/',headers=headers,
                                         params={'dataset_id':scope.dataset_id},timeout=15)
            assert response.status_code == 200, (endpoint,response.status_code)
            body=response.json()
            assert body['success'] is True
            data=body['data']
            names=[column['name'] for column in data['columns']] if endpoint=='schema' else data['columns']
            assert names == ['id','customer','amount','status']
            assert 'cdc_' not in json.dumps(data), 'physical name leaked through schema or preview'
            results[endpoint]='PASS'
        print(json.dumps({'phase':phase,'denials':results}),flush=True)
        return
    if phase == 'loader_restart':
        fixture.compose('restart','loader')
        with fixture.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('UPDATE orders SET amount=250 WHERE id=2')
        expected=[[1,'d2',Decimal(1),'initial'],[2,'d2',Decimal(250),'initial'],
                  [3,'d2',Decimal(3),'initial'],[4,'reborn',Decimal(400),'newer']]
        wait_for('D4 Loader restart retained offset and fresh update',
                 lambda:fixture.rows_equal(scope,expected),seconds=120)
        print(json.dumps({'phase':phase,'scope':scope.token,'fresh_update_after_restart':True}),flush=True)
        return
    if phase == 'clickhouse_outage':
        prior=probe('state')
        fixture.compose('stop','clickhouse')
        try:
            with fixture.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute('UPDATE orders SET amount=252 WHERE id=2')
            target=wait_for('D4 transformed event retained while ClickHouse is down',
                            lambda:(current if (current:=probe('state'))['last_offset']>prior['last_offset'] else False),
                            seconds=120)
            time.sleep(3)
            during=probe('state')
            assert during['committed_offset']<=target['last_offset']
            assert during['load_checkpoint']==prior['load_checkpoint']
        finally:
            fixture.compose('start','clickhouse')
        expected=[[1,'d2',Decimal(1),'initial'],[2,'d2',Decimal(252),'initial'],
                  [3,'d2',Decimal(3),'initial'],[4,'reborn',Decimal(400),'newer']]
        wait_for('D4 ClickHouse recovery replayed to exact authorized Query',
                 lambda:fixture.rows_equal(scope,expected),seconds=150)
        after=probe('state')
        assert after['committed_offset']>target['last_offset']
        print(json.dumps({'phase':phase,'scope':scope.token,'target_offset':target['last_offset'],
                          'uncommitted_during_outage':True,'no_false_checkpoint':True,
                          'recovery_query_exact':True}),flush=True)
        return
    if phase == 'crash_after_write':
        prior=probe('state')
        versions=f'etl.cdc_{scope.token}_versions'
        before=fixture.ch.query(f'SELECT count() FROM {versions}').result_rows[0][0]
        fixture.compose('stop','loader')
        try:
            with fixture.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute('UPDATE orders SET amount=253 WHERE id=2')
            target=wait_for('D4 crash target reached transformed topic',
                            lambda:(current if (current:=probe_stopped(scope))['last_offset']>prior['last_offset'] else False),
                            seconds=120)
            fixture.compose('run','--rm','--no-deps','-e','CDC_CRASH_AFTER_APPLY=load','loader',expected=86)
            physical=fixture.ch.query(f'SELECT count() FROM {versions}').result_rows[0][0]
            assert physical==before+1
            during=probe_stopped(scope)
            assert during['committed_offset']<=target['last_offset']
            assert during['load_checkpoint']==prior['load_checkpoint']
        finally:
            fixture.compose('start','loader')
        expected=[[1,'d2',Decimal(1),'initial'],[2,'d2',Decimal(253),'initial'],
                  [3,'d2',Decimal(3),'initial'],[4,'reborn',Decimal(400),'newer']]
        wait_for('D4 crash replay exact Query',lambda:fixture.rows_equal(scope,expected),seconds=150)
        after=fixture.ch.query(f'SELECT count() FROM {versions}').result_rows[0][0]
        assert after==physical
        print(json.dumps({'phase':phase,'scope':scope.token,'crash_exit':86,
                          'physical_rows_after_crash':physical,'physical_rows_after_replay':after,
                          'one_logical_current_state':True}),flush=True)
        return
    if phase == 'mixed_keys':
        with fixture.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('UPDATE orders SET customer=%s,amount=%s WHERE id=1',('changed',101))
                cur.execute('DELETE FROM orders WHERE id=3')
                cur.execute("INSERT INTO orders VALUES (5,'fifth',500,'new')")
        expected=[[1,'changed',Decimal(101),'initial'],[2,'d2',Decimal(253),'initial'],
                  [4,'reborn',Decimal(400),'newer'],[5,'fifth',Decimal(500),'new']]
        wait_for('D4 mixed multi-key Query exact state',lambda:fixture.rows_equal(scope,expected),seconds=120)
        with fixture.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('SELECT id,customer,amount::text,status FROM orders ORDER BY id')
                source=[(r[0],r[1],Decimal(r[2]),r[3]) for r in cur.fetchall()]
        assert source==[tuple(row) for row in expected]
        print(json.dumps({'phase':phase,'scope':scope.token,'keys':len(expected),'source_query_exact':True}),flush=True)
        return
    if phase == 'merge_independence':
        versions=f'etl.cdc_{scope.token}_versions'
        expected=[[1,'changed',Decimal(101),'initial'],[2,'d2',Decimal(253),'initial'],
                  [4,'reborn',Decimal(400),'newer'],[5,'fifth',Decimal(500),'new']]
        fixture.ch.command(f'SYSTEM STOP MERGES {versions}')
        try:
            for _ in range(3):
                assert fixture.rows_equal(scope,expected)
        finally:
            fixture.ch.command(f'SYSTEM START MERGES {versions}')
        fixture.ch.command(f'OPTIMIZE TABLE {versions} FINAL')
        for _ in range(3):
            assert fixture.rows_equal(scope,expected)
        print(json.dumps({'phase':phase,'pre_post_merge_query_stable':True,
                          'physical_exact_duplicate_retained':True}),flush=True)
        return
    if phase == 'cost':
        typed=json.loads((Path(env_file).resolve().parent/'d4-typed-state.json').read_text())
        perf=json.loads((Path(env_file).resolve().parent/'d4-performance-state.json').read_text())
        from bi_platform_shared.cdc_contract import Scope
        scopes={'small_replay_heavy':scope,'typed_composite':Scope(**typed['scope']),
                'five_thousand':Scope(**perf['scope'])}
        output={}
        for label,current in scopes.items():
            versions=f'etl.cdc_{current.token}_versions'
            view=f'etl.cdc_{current.token}_current'
            physical=fixture.ch.query(f'SELECT count() FROM {versions}').result_rows[0][0]
            durations=[]
            for _ in range(5):
                started=time.perf_counter()
                logical=fixture.ch.query(f'SELECT count() FROM {view}').result_rows[0][0]
                durations.append(round((time.perf_counter()-started)*1000,2))
            output[label]={'physical_rows':physical,'logical_rows':logical,
                           'view_count_ms':durations,'median_ms':statistics.median(durations)}
        assert output['small_replay_heavy']['logical_rows']==4
        assert output['typed_composite']['logical_rows']==0
        assert output['five_thousand']['logical_rows']==5000
        print(json.dumps({'phase':phase,'final_used':False,'measurements':output}),flush=True)
        return
    if phase == 'conflict':
        versions=f'etl.cdc_{scope.token}_versions'
        before=fixture.ch.query(f'SELECT count() FROM {versions}').result_rows[0][0]
        injected=probe('conflict')
        offset=injected['injected_offset']
        def failed_closed():
            status=fixture.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
            state=probe('state')
            failures=probe('dlq')
            return (status['desired_state']=='PAUSED' and
                    status['observed_state']=='RESEED_REQUIRED' and
                    status['error_code']=='CDC_VERSION_CONFLICT' and
                    state['committed_offset']>offset and
                    'CDC_VERSION_CONFLICT' in failures['reasons'] and failures['safe_fields_only'])
        wait_for('D4 equal-version conflict rejected into sticky safe DLQ',failed_closed,seconds=120)
        after=fixture.ch.query(f'SELECT count() FROM {versions}').result_rows[0][0]
        assert after==before
        expected=[[1,'changed',Decimal(101),'initial'],[2,'d2',Decimal(253),'initial'],
                  [4,'reborn',Decimal(400),'newer'],[5,'fifth',Decimal(500),'new']]
        assert fixture.rows_equal(scope,expected)
        fixture.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/resume/',
                    {'pipeline_id':scope.pipeline_id},expected=409)
        print(json.dumps({'phase':phase,'scope':scope.token,'conflict_offset':offset,
                          'sticky_reseed_required':True,'safe_dlq':True,'physical_rows_unchanged':True,
                          'authorized_query_unchanged':True}),flush=True)
        return
    if phase == 'conflict_verify':
        versions=f'etl.cdc_{scope.token}_versions'
        physical=fixture.ch.query(f'SELECT count() FROM {versions}').result_rows[0][0]
        assert physical==15
        status=fixture.api(11,'GET',f'/database/sources/{scope.source_id}/cdc/')['data'][0]
        state=probe('state')
        failures=probe('dlq')
        assert (status['desired_state'],status['observed_state'],status['error_code']) == (
            'PAUSED','RESEED_REQUIRED','CDC_VERSION_CONFLICT')
        assert state['committed_offset']>state['last_offset']
        assert failures['reasons']==['CDC_VERSION_CONFLICT'] and failures['safe_fields_only']
        expected=[[1,'changed',Decimal(101),'initial'],[2,'d2',Decimal(253),'initial'],
                  [4,'reborn',Decimal(400),'newer'],[5,'fifth',Decimal(500),'new']]
        assert fixture.rows_equal(scope,expected)
        fixture.api(11,'POST',f'/database/sources/{scope.source_id}/cdc/resume/',
                    {'pipeline_id':scope.pipeline_id},expected=409)
        print(json.dumps({'phase':phase,'scope':scope.token,'physical_rows':physical,
                          'poison_offset_committed':True,'sticky_reseed_required':True,
                          'safe_dlq':True,'authorized_query_unchanged':True}),flush=True)
        return
    if phase == 'publication_retry':
        versions=f'etl.cdc_{scope.token}_versions'
        before=fixture.ch.query(f'SELECT count() FROM {versions}').result_rows[0][0]
        def dataset_status(value):
            with fixture.pg('biavora') as connection:
                with connection.cursor() as cur:
                    cur.execute('UPDATE manager_databases SET etl_status=%s WHERE id=%s',
                                (value,scope.dataset_id))
                    assert cur.rowcount==1
        original=fixture.api(11,'POST','/query/execute/',{'dataset_id':scope.dataset_id,
                     'sql':f'SELECT count() AS n FROM cdc_{scope.token}_current'})
        assert original['rows']==[{'n':4}]
        dataset_status('failed')
        try:
            injected=probe('publication_replay')
            offset=injected['injected_offset']
            def uncommitted():
                state=probe('state')
                return state['last_offset']>=offset and state['committed_offset']<=offset and \
                    state['load_checkpoint'] and state['load_checkpoint']['offset']>=offset
            wait_for('D4 Query publication failure left Kafka replay pending',uncommitted,seconds=45)
        finally:
            dataset_status('pending')
        expected=[[1,'d2',Decimal(1),'initial'],[2,'d2',Decimal(250),'initial'],
                  [3,'d2',Decimal(3),'initial'],[4,'reborn',Decimal(400),'newer']]
        def recovered():
            state=probe('state')
            return state['committed_offset']>offset and fixture.rows_equal(scope,expected)
        wait_for('D4 same Dataset publication retried after durable write',recovered,seconds=120)
        after=fixture.ch.query(f'SELECT count() FROM {versions}').result_rows[0][0]
        assert before==after
        print(json.dumps({'phase':phase,'scope':scope.token,'dataset_id':scope.dataset_id,
                          'failed_offset':offset,'retry_committed':True,
                          'physical_rows_unchanged':True,'authorized_query_exact':True}),flush=True)
        return
    if phase == 'basic':
        def change(statement, params=()):
            with fixture.pg(database) as connection:
                with connection.cursor() as cur:
                    cur.execute(statement, params)
        def expect(rows, label):
            wait_for(label, lambda: fixture.rows_equal(scope, rows), seconds=120)
        change("INSERT INTO orders VALUES (4,'four',100,'new')")
        expect([[1,'d2',Decimal(1),'initial'],[2,'d2',Decimal(2),'initial'],
                [3,'d2',Decimal(3),'initial'],[4,'four',Decimal(100),'new']], 'D4 INSERT')
        for amount in (200, 300):
            change('UPDATE orders SET amount=%s WHERE id=4', (amount,))
            expect([[1,'d2',Decimal(1),'initial'],[2,'d2',Decimal(2),'initial'],
                    [3,'d2',Decimal(3),'initial'],[4,'four',Decimal(amount),'new']], f'D4 UPDATE {amount}')
        change('DELETE FROM orders WHERE id=4')
        base = [[i,'d2',Decimal(i),'initial'] for i in (1,2,3)]
        expect(base, 'D4 DELETE')
        change("INSERT INTO orders VALUES (4,'reborn',400,'newer')")
        expected = base + [[4,'reborn',Decimal(400),'newer']]
        expect(expected, 'D4 newer reinsert')
        for _ in range(3):
            assert fixture.rows_equal(scope, expected)
            time.sleep(1)
        with fixture.pg(database) as connection:
            with connection.cursor() as cur:
                cur.execute('SELECT id,customer,amount::text,status FROM orders ORDER BY id')
                source = [(row[0],row[1],Decimal(row[2]),row[3]) for row in cur.fetchall()]
        assert source == [tuple(row) for row in expected]
        view = f'cdc_{scope.token}_current'
        query = fixture.api(11,'POST','/query/execute/',
                            {'dataset_id':scope.dataset_id,'sql':f'SELECT * FROM {view} ORDER BY id'})
        assert all(set(row) == {'id','customer','amount','status'} for row in query['rows'])
        fixture.api(22,'POST','/query/execute/',
                    {'dataset_id':scope.dataset_id,'sql':f'SELECT * FROM {view}'}, expected=403)
        print(json.dumps({'phase':phase,'scope':scope.token,'source_query_exact':True,
                          'foreign_workspace_denied':True,'technical_columns_hidden':True}), flush=True)
        return
    raise ValueError(phase)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('phase', choices=['capacity','binding_verify','performance','final_pin','create','diagnose','ready','basic','replay_check','authority','loader_restart','publication_retry','clickhouse_outage','crash_after_write','mixed_keys','merge_independence','cost','conflict','conflict_verify','typed_create','typed_diagnose','typed_repair_fixture','typed_check','typed_absent','typed_reinsert'])
    args = parser.parse_args()
    main(args.env_file, args.phase)
