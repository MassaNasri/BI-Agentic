"""Restore the Phase 0 dump into a new local verification database; preserve it."""
from pathlib import Path
import hashlib,json,os,subprocess
import psycopg2
from psycopg2 import sql
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs'/'audit'

def main():
    env=dotenv_values(ROOT/'.env')
    if env.get('DB_HOST') not in {'127.0.0.1','localhost','host.docker.internal'}:raise RuntimeError('Local DB only')
    manifest=json.loads((OUT/'backup_manifest.json').read_text())
    entry=next(e for e in manifest['entries'] if e['resource']=='postgres:bi_voice_agent')
    with open(entry['path'],'rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=entry['sha256']:raise RuntimeError('Dump hash mismatch')
    name='phase0_restore_20260913'
    opts=dict(host='127.0.0.1',port=env.get('DB_PORT','5432'),dbname=env['DB_NAME'],user=env['DB_USER'],password=env['DB_PASSWORD'],connect_timeout=5)
    conn=psycopg2.connect(**opts);conn.autocommit=True;c=conn.cursor()
    c.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,))
    if c.fetchone():raise RuntimeError('Verification DB already exists; never overwrite it')
    c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)));conn.close()
    penv=os.environ.copy();penv['PGPASSWORD']=env['DB_PASSWORD']
    args=['C:/Program Files/PostgreSQL/18/bin/pg_restore.exe','-h','127.0.0.1','-p',env.get('DB_PORT','5432'),'-U',env['DB_USER'],'-d',name,'--exit-on-error',entry['path']]
    p=subprocess.run(args,env=penv,capture_output=True,timeout=120)
    if p.returncode:raise RuntimeError('Restore failed; output withheld; verification DB preserved')
    opts['dbname']=name;conn=psycopg2.connect(**opts);c=conn.cursor()
    expected=json.loads((OUT/'runtime_inventory.json').read_text())['postgres']['row_counts'];actual={}
    for table in expected:
        schema,t=table.split('.',1);c.execute(sql.SQL('SELECT count(*) FROM {}.{}').format(sql.Identifier(schema),sql.Identifier(t)));actual[table]=c.fetchone()[0]
    result={'database':name,'host':'127.0.0.1','preserved':True,'status':'PASS' if actual==expected else 'FAIL','counts':actual,'matches_before_backup':actual==expected}
    conn.close();(OUT/'postgres_restore_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='counts'}))

if __name__=='__main__':main()
