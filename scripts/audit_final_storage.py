"""Read-only after-startup storage and backup-hash validation."""
from pathlib import Path
import datetime,hashlib,json,subprocess
import requests
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs'/'audit';env=dotenv_values(ROOT/'.env')
result={'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
def ch(query):
    r=requests.post('http://127.0.0.1:8123/',auth=(env['CLICKHOUSE_USER'],env['CLICKHOUSE_PASSWORD']),data=(query+' FORMAT JSON').encode(),timeout=20)
    if r.status_code!=200:raise RuntimeError('ClickHouse inspection HTTP '+str(r.status_code))
    return r.json()['data']
tables=ch("SELECT name FROM system.tables WHERE database='etl' ORDER BY name")
counts={}
for row in tables:
    t=row['name']
    if not all(x.isalnum() or x=='_' for x in t):raise RuntimeError('Unknown identifier syntax; no dynamic execution')
    counts[t]=int(ch('SELECT count() AS n FROM etl.`'+t+'`')[0]['n'])
result['clickhouse_after_startup']=counts
def docker(*args):
    p=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=45)
    if p.returncode:raise RuntimeError('Docker inspection failed: '+args[0])
    return p.stdout.strip()
result['redis_keyspace']=docker('exec','redis','redis-cli','INFO','keyspace')
result['kafka_offsets']=docker('exec','kafka','kafka-get-offsets','--bootstrap-server','127.0.0.1:9092','--topic','.*','--time','-1')
result['current_voice_media_files']=docker('exec','voice-service','python','-c',"from pathlib import Path;print(sum(1 for p in Path('/app/media').rglob('*') if p.is_file()))")
result['current_upload_files']=docker('exec','etl-connector','python','-c',"from pathlib import Path;print(sum(1 for p in Path('/app/uploaded_files').rglob('*') if p.is_file()))")
m=json.loads((OUT/'backup_manifest.json').read_text());checks=[]
for e in m['entries']:
    p=Path(e['path'])
    with p.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
    checks.append({'resource':e['resource'],'sha256_matches':actual==e['sha256'],'size_matches':p.stat().st_size==e['bytes']})
result['backup_checks']=checks;result['backup_files_status']='PASS' if all(e['sha256_matches'] and e['size_matches'] for e in checks) else 'FAIL'
result['active_file_stores_empty']=result['current_voice_media_files']=='0' and result['current_upload_files']=='0'
(OUT/'final_storage_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ['backup_checks','kafka_offsets']},indent=2))
