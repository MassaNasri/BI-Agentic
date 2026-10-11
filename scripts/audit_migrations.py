"""Run current core migrations sequentially and save only redacted output."""
from pathlib import Path
import datetime,json,subprocess
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'docs'/'audit'
env=dotenv_values(ROOT/'.env')
secrets=[v for k,v in env.items() if v and len(v)>=4 and any(s in k.upper() for s in ('SECRET','PASSWORD','TOKEN','API_KEY'))]
def redact(s):
    for v in sorted(secrets,key=len,reverse=True): s=s.replace(v,'[REDACTED]')
    return s
rows=[]
for service in ['auth-service','workspace-service','subscription-service','notification-service','voice-service','query-service','visualization-service','report-service','ai-service']:
    args=['docker','compose','-f','docker-compose.yml','-f','docs/audit/startup.override.yml','run','--rm','--no-deps','--entrypoint','python',service,'manage.py','migrate','--noinput']
    try:
        p=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=150)
        row={'service':service,'exit_code':p.returncode,'status':'PASS' if p.returncode==0 else 'FAIL','output':redact(p.stdout+'\n'+p.stderr)}
    except subprocess.TimeoutExpired: row={'service':service,'status':'TIMEOUT','exit_code':None}
    rows.append(row)
    (OUT/'migration_verification.json').write_text(json.dumps({'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'results':rows},indent=2),encoding='utf-8')
    print(service,row['status'],flush=True)
