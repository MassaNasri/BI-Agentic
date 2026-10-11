"""DEV ONLY offline preservation. Does not clear data or start application services."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs'/'audit'

def run(args, **kw):
    p=subprocess.run(args,cwd=ROOT,capture_output=True,timeout=1800,**kw)
    if p.returncode: raise RuntimeError(f'{args[0]} {args[1]} failed with exit {p.returncode}; output withheld to protect secrets')
    return p.stdout

def main():
    inventory=json.loads((OUT/'runtime_inventory.json').read_text())
    ctx=json.loads(run(['docker','context','inspect']))[0]
    if not ctx['Endpoints']['docker']['Host'].startswith('npipe://'): raise RuntimeError('Only local Windows Docker is allowed')
    if run(['docker','ps','-q']).strip(): raise RuntimeError('Offline backup requires all containers stopped; none will be stopped automatically')
    env=dotenv_values(ROOT/'.env')
    if env.get('DB_HOST') not in {'localhost','127.0.0.1','host.docker.internal'} or env.get('DB_NAME')!='bi_voice_agent': raise RuntimeError('Unrecognized database; no backup attempted')
    if shutil.disk_usage(ROOT).free < 10*1024**3: raise RuntimeError('Less than 10 GiB free; no archive attempted')
    backup=ROOT/'backups'/('phase0-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(parents=True)
    (ROOT/'backups'/'.gitignore').write_text('*\n!.gitignore\n',encoding='utf-8')
    manifest={'status':'IN PROGRESS','backup_directory':str(backup),'entries':[],'errors':[],'no_deletions':True}
    def record(p,resource,verification):
        digest=hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
        manifest['entries'].append({'resource':resource,'path':str(p),'bytes':p.stat().st_size,'sha256':digest,'verification':verification})
        (OUT/'backup_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        print(f'BACKED UP {resource}: {p.stat().st_size} bytes',flush=True)
    pg_bin=Path('C:/Program Files/PostgreSQL/18/bin')
    pg_env=os.environ.copy();pg_env['PGPASSWORD']=env['DB_PASSWORD'];pg_env['PGCONNECT_TIMEOUT']='5'
    dump=backup/'bi_voice_agent.dump'
    run([str(pg_bin/'pg_dump.exe'),'-h','127.0.0.1','-p',env.get('DB_PORT','5432'),'-U',env['DB_USER'],'-d','bi_voice_agent','-Fc','-f',str(dump)],env=pg_env)
    toc=run([str(pg_bin/'pg_restore.exe'),'--list',str(dump)])
    if b'TABLE DATA' not in toc: raise RuntimeError('Dump has no table data entries')
    record(dump,'postgres:bi_voice_agent','pg_restore --list succeeded; restore drill pending')
    # With no mounts or MB_DB_* overrides, Metabase uses its container writable layer.
    mb=backup/'metabase.db'
    try:
        run(['docker','cp','metabase:/metabase.db',str(mb)])
        paths=[mb] if mb.is_file() else list(mb.rglob('*'))
        found=False
        for p in paths:
            if p.is_file(): record(p,'metabase:H2','copied while stopped; H2 restore drill pending');found=True
        if not found: raise RuntimeError('No Metabase files found')
    except Exception as e: manifest['errors'].append(str(e))
    # Every mounted data volume of known current/legacy applications; preserve secrets/caches separately.
    volumes=set()
    for c in inventory['containers']:
        for m in c['mounts']:
            if m['Type']=='volume' and not any(x in m['Destination'] for x in ['secrets','whisper','clamav']): volumes.add(m['Name'])
    for v in inventory['volumes']:
        if v['Name'].startswith(('bi-voice-agent_','etl-final_')) and not any(x in v['Name'] for x in ['whisper','clamav']): volumes.add(v['Name'])
    helper="import tarfile; t=tarfile.open('/backup/archive.tar','w'); t.add('/source',arcname='data'); t.close()"
    for volume in sorted(volumes):
        if shutil.disk_usage(ROOT).free < 5*1024**3:
            manifest['errors'].append('Stopped volume backups: less than 5 GiB free');break
        slot=backup/volume;slot.mkdir()
        try:
            run(['docker','run','--rm','--network','none','--read-only','--entrypoint','python','--mount',f'type=volume,source={volume},target=/source,readonly','--mount',f'type=bind,source={slot},target=/backup','bi-voice-agent-auth-service','-c',helper])
            archive=slot/'archive.tar'
            with tarfile.open(archive) as t:
                count=sum(1 for _ in t)
            record(archive,'docker-volume:'+volume,f'tar directory readable; {count} members; application restore pending')
        except Exception as e: manifest['errors'].append(f'{volume}: {e}')
    # Preserve selected container writable-layer paths, without exporting multi-GB model images.
    for c in inventory['containers']:
        if c['project'] not in {'bi-voice-agent','etl-final'}: continue
        service=c['name']
        paths=['/app/media'] if service in {'voice-service','query-service','report-service'} else []
        app={'etl-connector':'connector','connector-service':'connector','etl-extractor':'extractor','extractor-service':'extractor','etl-transformer':'transformer','transformer-service':'transformer','etl-loader':'loader','loader-service':'loader','etl-detector':'detector','detector-service':'detector','etl-metadata':'metadata','metadata-service':'metadata'}.get(service)
        if app: paths += [f'/app/{app}/db.sqlite3']
        for source in paths:
            dest=backup/'container-files'/service/Path(source).name;dest.parent.mkdir(parents=True,exist_ok=True)
            p=subprocess.run(['docker','cp',service+':'+source,str(dest)],capture_output=True,timeout=120)
            if p.returncode:
                manifest.setdefault('paths_not_copied',[]).append({'container':service,'path':source,'status':'path unavailable; absence or layout mismatch requires verification'})
            else:
                for f in ([dest] if dest.is_file() else dest.rglob('*')):
                    if f.is_file():record(f,'container:'+service+source,'offline copy')
    for rel in ['media','etl-final/etl-infra/clickhouse/data']:
        source=ROOT/rel
        if source.exists():
            archive=backup/('local-'+rel.replace('/','_')+'.tar')
            with tarfile.open(archive,'w') as t: t.add(source,arcname='data')
            with tarfile.open(archive) as t: count=sum(1 for _ in t)
            record(archive,'local:'+rel,f'tar directory readable; {count} members')
    manifest['status']='PARTIAL' if manifest['errors'] else 'FILES VERIFIED; RESTORE DRILLS PENDING'
    (OUT/'backup_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'status':manifest['status'],'backup_directory':str(backup),'entries':len(manifest['entries']),'errors':manifest['errors']},indent=2))

if __name__=='__main__':main()
