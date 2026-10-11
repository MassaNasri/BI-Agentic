"""Verify migration drift and apply existing migrations to actual local containers."""
from pathlib import Path
import datetime,json,subprocess
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs'/'audit'
env=dotenv_values(ROOT/'.env');secrets=[v for k,v in env.items() if v and len(v)>=4 and any(x in k.upper() for x in ['SECRET','PASSWORD','TOKEN','API_KEY'])]
rows=[]
checks=[(s,'manage.py',['makemigrations','--check','--dry-run']) for s in ['voice-service','notification-service']]
checks += [('api-gateway','manage.py',['migrate','--noinput']),('ai-service','manage.py',['migrate','--noinput'])]
checks += [('etl-'+s,f'{s}-service/{s}/manage.py',['migrate','--noinput']) for s in ['connector','detector','extractor','transformer','loader','metadata']]
for service,path,args in checks:
    try:
        p=subprocess.run(['docker','exec',service,'python',path,*args],capture_output=True,text=True,timeout=120)
        output=p.stdout+'\n'+p.stderr
        for v in sorted(secrets,key=len,reverse=True):output=output.replace(v,'[REDACTED]')
        row={'service':service,'command':' '.join(args),'exit_code':p.returncode,'status':'PASS' if p.returncode==0 else 'FAIL','output':output}
    except subprocess.TimeoutExpired:row={'service':service,'command':' '.join(args),'status':'TIMEOUT'}
    rows.append(row);(OUT/'container_migration_verification.json').write_text(json.dumps({'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'results':rows},indent=2),encoding='utf-8')
    print(service,' '.join(args),row['status'],flush=True)
