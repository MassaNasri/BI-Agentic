"""Read-only Docker and local PostgreSQL inventory; no secret values serialized."""
import datetime
import json
import os
from pathlib import Path
import socket
import subprocess
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'audit'

def command(args):
    p = subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=60)
    if p.returncode: raise RuntimeError(f'{args[0]} {args[1]} failed (exit {p.returncode})')
    return p.stdout

def main():
    result = {'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'errors':[]}
    env = dotenv_values(ROOT/'.env')
    safe_keys = {'DB_HOST','DB_PORT','DB_NAME','DB_USER','CLICKHOUSE_HOST','CLICKHOUSE_PORT','CLICKHOUSE_DATABASE','METABASE_URL','SURREAL_NS','SURREAL_DB','REDIS_URL','DEBUG','ENVIRONMENT','APP_ENV','DJANGO_ENV'}
    result['configuration']={k:v for k,v in env.items() if k in safe_keys and not (v and '@' in v)}
    try:
        ctx=json.loads(command(['docker','context','inspect']))[0]
        endpoint=ctx['Endpoints']['docker']['Host']
        result['docker_context']={'name':ctx['Name'],'endpoint':endpoint,'local_pipe':endpoint.startswith('npipe://')}
        ids=command(['docker','ps','-aq']).split()
        containers=json.loads(command(['docker','inspect',*ids])) if ids else []
        result['containers']=[]
        for c in containers:
            cfg=c['Config']; ce=dict(v.split('=',1) for v in cfg.get('Env',[]) if '=' in v)
            row={'name':c['Name'].lstrip('/'),'id':c['Id'],'image':cfg['Image'],'state':{k:v for k,v in c['State'].items() if k in {'Status','Running','ExitCode','StartedAt','FinishedAt','OOMKilled'}},'health_status':c['State'].get('Health',{}).get('Status','not configured'),'project':cfg.get('Labels',{}).get('com.docker.compose.project'),'service':cfg.get('Labels',{}).get('com.docker.compose.service'),'mounts':c.get('Mounts',[]),'ports':c['HostConfig'].get('PortBindings'),'networks':list(c['NetworkSettings'].get('Networks',{})),'user':cfg.get('User'),'env_names':sorted(ce),'safe_env':{k:v for k,v in ce.items() if k in safe_keys | {'MB_DB_TYPE','MB_DB_HOST','MB_DB_PORT','MB_DB_DBNAME','MB_DB_FILE'} and '@' not in v}}
            result['containers'].append(row)
        vids=command(['docker','volume','ls','-q']).split()
        volumes=[]
        for i in range(0,len(vids),50):
            for v in json.loads(command(['docker','volume','inspect',*vids[i:i+50]])):
                volumes.append({k:v[k] for k in ['Name','Driver','Mountpoint','Labels','Scope'] if k in v})
        result['volumes']=volumes
        nets=command(['docker','network','ls','-q']).split()
        result['networks']=[{k:n[k] for k in ['Name','Driver','Internal','IPAM','Labels'] if k in n} for n in json.loads(command(['docker','network','inspect',*nets]))]
    except Exception as e: result['errors'].append(str(e))
    host=env.get('DB_HOST','')
    if host not in {'localhost','127.0.0.1','::1','host.docker.internal'}:
        result['postgres']={'status':'CRITICAL — POSSIBLE PRODUCTION RESOURCE; excluded','host':host}
    else:
        try:
            import psycopg2
            conn=psycopg2.connect(host='127.0.0.1',port=env.get('DB_PORT','5432'),dbname=env['DB_NAME'],user=env['DB_USER'],password=env['DB_PASSWORD'],connect_timeout=5,options='-c default_transaction_read_only=on -c statement_timeout=10000')
            cur=conn.cursor()
            cur.execute('SELECT current_database(), inet_server_addr()::text, version()')
            pg={'identity':cur.fetchone()}
            cur.execute('SELECT datname, pg_get_userbyid(datdba) FROM pg_database WHERE NOT datistemplate ORDER BY datname')
            pg['databases']=cur.fetchall()
            cur.execute('SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin FROM pg_roles ORDER BY rolname')
            pg['roles']=cur.fetchall()
            cur.execute("SELECT schemaname, tablename, tableowner FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY schemaname,tablename")
            pg['tables']=cur.fetchall()
            from psycopg2 import sql
            pg['row_counts']={}
            for schema,table,owner in pg['tables']:
                cur.execute(sql.SQL('SELECT count(*) FROM {}.{}').format(sql.Identifier(schema),sql.Identifier(table)))
                pg['row_counts'][f'{schema}.{table}']=cur.fetchone()[0]
            cur.execute("SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE contype='f' AND connamespace='public'::regnamespace")
            pg['foreign_keys']=cur.fetchall()
            conn.close()
            result['postgres']=pg
        except Exception as e:
            result['postgres']={'status':'NOT VERIFIED','error_type':type(e).__name__}
    result['local_listeners']={}
    for port in [5432,3000,8000,8001,8005,8123,6379,11434,5173]:
        s=socket.socket();s.settimeout(.3)
        result['local_listeners'][str(port)]=s.connect_ex(('127.0.0.1',port))==0;s.close()
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'runtime_inventory.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'configuration':result['configuration'],'containers':len(result.get('containers',[])),'volumes':len(result.get('volumes',[])),'metabase':[c for c in result.get('containers',[]) if c['name']=='metabase'],'postgres':result.get('postgres'),'errors':result['errors'],'listeners':result['local_listeners']},indent=2))

if __name__ == '__main__': main()
