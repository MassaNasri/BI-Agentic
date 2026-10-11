"""Local-only storage inspection and missing writable-layer preservation."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import sqlite3
import subprocess
import tarfile
import requests
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs'/'audit'

def main():
    env=dotenv_values(ROOT/'.env')
    manifest=json.loads((OUT/'backup_manifest.json').read_text())
    backup=Path(manifest['backup_directory'])
    detail={'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'errors':[],'sqlite':[]}
    def record(p,resource):
        with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        manifest['entries'].append({'resource':resource,'path':str(p),'bytes':p.stat().st_size,'sha256':digest,'verification':'offline file copy; SQLite integrity checked separately'})
    inventory=json.loads((OUT/'runtime_inventory.json').read_text())
    for c in inventory['containers']:
        name=c['name']
        if name.startswith('etl-'):app=name[4:]
        elif name.endswith('-service') and name.split('-')[0] in {'connector','extractor','transformer','loader','metadata','detector'}:app=name.split('-')[0]
        else:app=None
        if app:source=f'/app/{app}-service/{app}/db.sqlite3'
        elif name=='ai-service':source='/app/db.sqlite3'
        else:continue
        dest=backup/'sqlite'/name/'db.sqlite3';dest.parent.mkdir(parents=True,exist_ok=True)
        p=subprocess.run(['docker','cp',name+':'+source,str(dest)],capture_output=True,timeout=60)
        if p.returncode:
            detail['sqlite'].append({'container':name,'path':source,'status':'not present at configured path'})
            continue
        record(dest,'container:'+name+source)
        db=sqlite3.connect(dest.as_uri()+'?mode=ro',uri=True)
        tables=db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        detail['sqlite'].append({'container':name,'path':source,'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],'tables':[t[0] for t in tables],'rows':{t[0]:db.execute('SELECT count(*) FROM "'+t[0].replace('"','""')+'"').fetchone()[0] for t in tables}})
        db.close()
    for base,dirs,files in os.walk(ROOT):
        dirs[:]=[d for d in dirs if d not in {'.git','node_modules','__pycache__','backups','data','timesfm'}]
        for name in files:
            if name.endswith(('.sqlite3','.sqlite')):
                p=Path(base)/name
                db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
                tables=db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                detail['sqlite'].append({'local_path':str(p.relative_to(ROOT)),'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],'tables':[t[0] for t in tables]})
                dest=backup/'local-sqlite'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True)
                out=sqlite3.connect(dest);db.backup(out);out.close();db.close();record(dest,'local:'+str(p.relative_to(ROOT)))
    def ch(sql):
        r=requests.post('http://127.0.0.1:8123/',auth=(env['CLICKHOUSE_USER'],env['CLICKHOUSE_PASSWORD']),data=sql.encode(),timeout=(5,30));r.raise_for_status();return r.json()['data']
    try:
        detail['clickhouse']={'databases':ch('SHOW DATABASES FORMAT JSON'),'tables':ch("SELECT database,name,engine,total_rows,total_bytes,partition_key,sorting_key,create_table_query FROM system.tables WHERE database NOT IN ('system','information_schema','INFORMATION_SCHEMA') ORDER BY database,name FORMAT JSON")}
        # Never include password hashes or access-control definitions.
        detail['clickhouse']['users']=ch('SELECT name, storage FROM system.users FORMAT JSON')
        detail['clickhouse']['row_policies']=ch('SELECT name,database,table FROM system.row_policies FORMAT JSON')
    except Exception as e:detail['errors'].append({'store':'clickhouse','type':type(e).__name__})
    try:
        import redis
        r=redis.Redis(host='127.0.0.1',port=6379,socket_timeout=5)
        detail['redis']={'keyspace':r.info('keyspace'),'databases':{}}
        for database in range(16):
            client=redis.Redis(host='127.0.0.1',port=6379,db=database,socket_timeout=5)
            keys=[]
            for k in client.scan_iter(count=200):
                # No key values; keys can contain user IDs, so retain only namespaces and hashes.
                key=k.decode(errors='replace')
                keys.append({'namespace':':'.join(key.split(':')[:3]),'key_sha256':hashlib.sha256(k).hexdigest(),'type':client.type(k).decode(),'ttl':client.ttl(k)})
            if keys:detail['redis']['databases'][str(database)]=keys
    except Exception as e:detail['errors'].append({'store':'redis','type':type(e).__name__})
    try:
        p=subprocess.run(['docker','exec','kafka','kafka-topics','--bootstrap-server','localhost:9092','--describe'],capture_output=True,text=True,timeout=60)
        detail['kafka']={'exit_code':p.returncode,'topics':p.stdout,'retention':'per-topic configs in describe; broker defaults require inspection'}
    except Exception as e:detail['errors'].append({'store':'kafka','type':type(e).__name__})
    try:
        r=requests.post('http://127.0.0.1:8008/sql',auth=(env['SURREAL_USER'],env['SURREAL_PASS']),headers={'Accept':'application/json'},data='INFO FOR ROOT;',timeout=10)
        payload=r.json()
        summaries=[]
        for item in payload if isinstance(payload,list) else []:
            obj=item.get('result',{})
            if isinstance(obj,dict):summaries.append({k:list(v) if isinstance(v,dict) else type(v).__name__ for k,v in obj.items()})
        detail['surrealdb']={'http_status':r.status_code,'root_object_names_only':summaries}
    except Exception as e:detail['errors'].append({'store':'surrealdb','type':type(e).__name__})
    (OUT/'backup_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (OUT/'storage_detail.json').write_text(json.dumps(detail,indent=2),encoding='utf-8')
    print(json.dumps({'sqlite':detail['sqlite'],'clickhouse_tables':[(t['database'],t['name'],t['total_rows']) for t in detail.get('clickhouse',{}).get('tables',[])],'redis':detail.get('redis',{}).get('keyspace'),'kafka_exit':detail.get('kafka',{}).get('exit_code'),'errors':detail['errors']},indent=2))

if __name__=='__main__':main()
