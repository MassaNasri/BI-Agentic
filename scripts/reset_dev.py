"""DEV ONLY targeted reset. Default is a read-only plan; --apply executes that exact plan.

No schema drops, CASCADE, volume deletion, source edits, external endpoint writes,
Metabase reset, or secrets deletion. Any unknown table/resource or data drift refuses.
Back up offline with reset-dev.ps1 -Backup and inventory before each reset cycle.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import psycopg2
from psycopg2 import sql
import requests
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs'/'audit'
PG_KEEP={'auth_group','auth_group_permissions','auth_permission','django_content_type','django_migrations','subscription_plans'}
PG_CLEAR={'dashboard_pages','django_admin_log','django_session','invitations','manager_databases','notification_dispatch_logs','password_reset_codes','report_page_assignments','sql_edit_history','subscription_free_tier_usage','subscription_payments','token_blacklist_blacklistedtoken','token_blacklist_outstandingtoken','users','users_groups','users_user_permissions','voice_pipeline_jobs','voice_reports','workspace_members','workspace_subscriptions','workspaces'}
CH_CLEAR={'deduplication_log','quality_anomalies','quality_metrics','quarantine','sales_3months_realistic_csv'}
CH_KEEP={'schema_contract_registry'}
REDIS_KEYS={'_kombu.binding.reply.celery.pidbox','_kombu.binding.celery.pidbox','_kombu.binding.celeryev','_kombu.binding.voice_pipeline'}
FILE_VOLUMES={'bi-voice-agent_uploaded-files','bi-voice-agent_voice_service_media','etl-final_uploaded-files'}
INFRA={'clickhouse','redis','kafka','zookeeper','surrealdb','clamav','kafka-ui'}

def docker(*args,input=None):
    p=subprocess.run(['docker',*args],capture_output=True,text=True,input=input,timeout=120)
    if p.returncode:raise RuntimeError('Docker operation failed: '+args[0]+'; output withheld')
    return p.stdout.strip()

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--environment',required=True,choices=['development']);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    env=dotenv_values(ROOT/'.env')
    for k in ['APP_ENV','ENVIRONMENT','DJANGO_ENV']:
        if env.get(k) and env[k].lower() not in {'dev','development','local','test'}:raise RuntimeError('Non-development environment marker; refused')
    if env.get('DB_HOST') not in {'localhost','127.0.0.1','host.docker.internal'} or env.get('DB_NAME')!='bi_voice_agent':raise RuntimeError('Unrecognized local PostgreSQL target; refused')
    ctx=json.loads(docker('context','inspect'))[0]
    if not ctx['Endpoints']['docker']['Host'].startswith('npipe://'):raise RuntimeError('Remote Docker is forbidden')
    runtime=json.loads((OUT/'runtime_inventory.json').read_text());backup=json.loads((OUT/'backup_manifest.json').read_text());detail=json.loads((OUT/'storage_detail.json').read_text())
    if backup.get('errors') or backup['status']=='IN PROGRESS':raise RuntimeError('Incomplete backup set')
    live_names=set(docker('ps','--format','{{.Names}}').splitlines())
    if live_names-INFRA:raise RuntimeError('Application or unknown containers running; stop them before reset')
    for name in ['clickhouse','redis','kafka','surrealdb']:
        old=next(c for c in runtime['containers'] if c['name']==name)
        now=json.loads(docker('inspect',name))[0]
        if now['Id']!=old['id']:raise RuntimeError('Container identity drift: '+name)
    pg=psycopg2.connect(host='127.0.0.1',port=env.get('DB_PORT','5432'),dbname='bi_voice_agent',user=env['DB_USER'],password=env['DB_PASSWORD'],connect_timeout=5,options='-c statement_timeout=15000 -c lock_timeout=5000')
    cur=pg.cursor();cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'");tables={t[0] for t in cur.fetchall()}
    if tables!=PG_KEEP|PG_CLEAR:raise RuntimeError('PostgreSQL table drift; review ownership before reset')
    def pg_counts():
        counts={}
        for t in sorted(tables):cur.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(t)));counts[t]=cur.fetchone()[0]
        return counts
    counts=pg_counts()
    for t,n in counts.items():
        if runtime['postgres']['row_counts'].get('public.'+t)!=n:raise RuntimeError('Data changed since backup; refresh backup/inventory: '+t)
    def ch(query,json_format=True):
        r=requests.post('http://127.0.0.1:8123/',auth=(env['CLICKHOUSE_USER'],env['CLICKHOUSE_PASSWORD']),data=(query+(' FORMAT JSON' if json_format else '')).encode(),timeout=(5,30))
        if r.status_code!=200:raise RuntimeError('ClickHouse command failed; details withheld')
        return r.json()['data'] if json_format else None
    current_ch=ch("SELECT database,name,create_table_query FROM system.tables WHERE database NOT IN ('system','information_schema','INFORMATION_SCHEMA')")
    if {(t['database'],t['name']) for t in current_ch}!={('etl',t) for t in CH_CLEAR|CH_KEEP}:raise RuntimeError('Unknown ClickHouse tables/databases; refused')
    expected_ddl={(t['database'],t['name']):t['create_table_query'] for t in detail['clickhouse']['tables']}
    if any(expected_ddl[(t['database'],t['name'])]!=t['create_table_query'] for t in current_ch):raise RuntimeError('ClickHouse schema changed since backup')
    ch_counts={t:int(ch('SELECT count() AS n FROM etl.`'+t+'`')[0]['n']) for t in sorted(CH_CLEAR|CH_KEEP)}
    for t in detail['clickhouse']['tables']:
        if t['total_rows'] is not None and ch_counts[t['name']]!=int(t['total_rows']):raise RuntimeError('ClickHouse data changed since snapshot')
    keys={k for k in docker('exec','redis','redis-cli','-n','1','--scan').splitlines() if k}
    if keys-REDIS_KEYS:raise RuntimeError('Unknown Redis DB1 key; refused')
    keyspace=docker('exec','redis','redis-cli','INFO','keyspace')
    if any(l.startswith('db') and not l.startswith('db1:') for l in keyspace.splitlines()):raise RuntimeError('Other Redis database contains data; review and back up before reset')
    offsets=docker('exec','kafka','kafka-get-offsets','--bootstrap-server','localhost:9092','--time','-1')
    topics={}
    for line in offsets.splitlines():
        topic,part,offset=line.rsplit(':',2)
        if not topic.startswith('__'):
            topics[topic+':'+part]=int(offset)
    if any(topics.values()):raise RuntimeError('Kafka business messages exist: this reset deliberately requires a separate reviewed partition-offset deletion plan')
    resources={e['resource']:e for e in backup['entries']}
    required={'postgres:bi_voice_agent','metabase:H2','docker-volume:bi-voice-agent_clickhouse_data','docker-volume:bi-voice-agent_redis_data'}|{'docker-volume:'+v for v in FILE_VOLUMES}
    if required-set(resources):raise RuntimeError('Required backups missing')
    file_sets={}
    for v in sorted(FILE_VOLUMES):
        files=[]
        with tarfile.open(resources['docker-volume:'+v]['path']) as archive:
            for item in archive:
                if item.issym() or item.islnk():raise RuntimeError('Unexpected linked file in upload archive')
                if item.isfile():
                    path=Path(item.name)
                    if path.parts[0]!='data' or '..' in path.parts:raise RuntimeError('Unsafe archive path')
                    files.append({'path':'/'.join(path.parts[1:]),'sha256':hashlib.sha256(archive.extractfile(item).read()).hexdigest()})
        file_sets[v]=files
    local_files=[]
    with tarfile.open(resources['local:media']['path']) as archive:
        for item in archive:
            if item.isfile():
                p=(ROOT/'media'/Path(*Path(item.name).parts[1:])).resolve()
                if not p.is_relative_to((ROOT/'media').resolve()) or p.is_symlink():raise RuntimeError('Unsafe local media path')
                local_files.append({'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(archive.extractfile(item).read()).hexdigest()})
    plan={'environment':'LOCAL DEVELOPMENT','database':'127.0.0.1:5432/bi_voice_agent','postgres_clear':sorted(PG_CLEAR),'postgres_preserve':sorted(PG_KEEP),'postgres_before':counts,'clickhouse_clear':['etl.'+t for t in sorted(CH_CLEAR)],'clickhouse_preserve':['etl.schema_contract_registry'],'clickhouse_before':ch_counts,'redis_db':1,'redis_keys':sorted(keys),'kafka':'15 business topics have zero end offsets; preserve topics and infrastructure offsets','kafka_end_offsets':topics,'volume_files':file_sets,'local_files':local_files,'backups':str(backup['backup_directory']),'preserve':['Metabase metadata/cards/dashboards/collections/source credentials','all database schemas and migration history','subscription plans and admin bootstrap configuration','all secrets, model/signature caches','unknown/orphan Docker volumes and archived legacy ClickHouse stores','Git-tracked ClickHouse snapshot and user source changes','phase0_restore_20260913 verification database'],'external_resources':'CRITICAL — POSSIBLE PRODUCTION RESOURCE: external provider/source endpoints excluded; never contacted for reset'}
    plan_path=OUT/'DATA_WIPE_MANIFEST.json'
    if not args.apply:
        plan_path.write_text(json.dumps(plan,indent=2),encoding='utf-8')
        print('DRY RUN: wrote docs/audit/DATA_WIPE_MANIFEST.json; no data changed')
        print(json.dumps({'postgres_tables':len(PG_CLEAR),'clickhouse_tables':len(CH_CLEAR),'redis_keys':len(keys),'upload_files':sum(len(v) for v in file_sets.values()),'local_media_files':len(local_files),'kafka_messages':0},indent=2));pg.close();return
    if not plan_path.exists() or json.loads(plan_path.read_text())!=plan:raise RuntimeError('Missing/stale manifest; run dry-run and review it')
    # Hash every recorded backup, not only the database dump.
    for e in backup['entries']:
        if not Path(e['path']).is_file() or sha(e['path'])!=e['sha256']:raise RuntimeError('Backup missing or hash mismatch; refused')
    restore=json.loads((OUT/'postgres_restore_verification.json').read_text())
    if restore.get('status')!='PASS':raise RuntimeError('PostgreSQL restore drill required')
    result={'status':'IN PROGRESS','started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'actions':[]}
    def save(): (OUT/'reset_execution.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    save()
    try:
        cur.execute(sql.SQL('TRUNCATE TABLE {} RESTART IDENTITY').format(sql.SQL(', ').join(sql.Identifier('public',t) for t in sorted(PG_CLEAR))))
        after=pg_counts()
        if any(after[t] for t in PG_CLEAR) or any(after[t]!=counts[t] for t in PG_KEEP):raise RuntimeError('PostgreSQL post-reset count mismatch')
        pg.commit();result['postgres_after']=after;result['actions'].append('PostgreSQL: 21 tables truncated; six configuration tables preserved');save()
        for t in sorted(CH_CLEAR):ch('TRUNCATE TABLE etl.`'+t+'`',False)
        result['clickhouse_after']={t:int(ch('SELECT count() AS n FROM etl.`'+t+'`')[0]['n']) for t in sorted(CH_CLEAR|CH_KEEP)}
        if any(result['clickhouse_after'].values()):raise RuntimeError('ClickHouse not empty')
        result['actions'].append('ClickHouse: five tables truncated; schema registry preserved');save()
        if keys:docker('exec','redis','redis-cli','-n','1','UNLINK',*sorted(keys))
        result['redis_after']=docker('exec','redis','redis-cli','INFO','keyspace');result['actions'].append('Redis: four obsolete Kombu binding keys removed; no FLUSHALL');save()
        # Fixed local Docker volumes, no network, verified archived files only.
        helper='''import hashlib,json,pathlib,sys
root=pathlib.Path('/source').resolve();items=json.load(sys.stdin)
expected={str((root/i['path']).resolve()) for i in items}
actual={str(p.resolve()) for p in root.rglob('*') if p.is_file()}
if actual!=expected:raise RuntimeError('file-set drift')
for i in items:
 p=root/i['path']
 if p.is_symlink() or not p.resolve().is_relative_to(root):raise RuntimeError('unsafe path')
 if hashlib.sha256(p.read_bytes()).hexdigest()!=i['sha256']:raise RuntimeError('file drift')
for i in items:(root/i['path']).unlink()
print(len(items))'''
        for v,files in file_sets.items():
            n=docker('run','--rm','-i','--network','none','--read-only','--entrypoint','python','--mount',f'type=volume,source={v},target=/source','bi-voice-agent-auth-service','-c',helper,input=json.dumps(files))
            result['actions'].append('Removed '+n+' backed-up files from '+v);save()
        for item in local_files:
            p=(ROOT/item['path']).resolve()
            if not p.is_relative_to((ROOT/'media').resolve()) or p.is_symlink() or sha(p)!=item['sha256']:raise RuntimeError('Local file drift')
        for item in local_files:(ROOT/item['path']).unlink()
        result['actions'].append('Removed three backed-up local test audio files; directories preserved')
        result['kafka']='Business topics verified empty; no destructive operation needed'
        result['status']='ACTIVE DATA CLEANED; STARTUP VERIFICATION PENDING'
    except Exception as e:
        pg.rollback();result['status']='PARTIAL / FAILED';result['error_type']=type(e).__name__;save();raise
    finally:pg.close();save()
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
