"""Read-only Phase 0 HTTP, container and clean-business-state checks. No inference/email."""
from pathlib import Path
import concurrent.futures,datetime,json,subprocess,sys
import requests,psycopg2
from psycopg2 import sql
from dotenv import dotenv_values
from reset_dev import PG_CLEAR
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs'/'audit'
env=dotenv_values(ROOT/'.env')
def docker(*args):
    p=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=30)
    if p.returncode: raise RuntimeError('Docker inspection failed')
    return p.stdout
def check(item):
    label,port,path,expected=item
    try:
        r=requests.get(f'http://127.0.0.1:{port}{path}',timeout=12,allow_redirects=False)
        try:d=r.json()
        except ValueError:d={}
        return {'check':label,'port':port,'path':path,'http_status':r.status_code,'success_field':d.get('success') if isinstance(d,dict) else None,'status':'PASS' if r.status_code in expected and (not isinstance(d,dict) or d.get('success') is not False) else 'FAIL'}
    except requests.RequestException as e:return {'check':label,'port':port,'path':path,'status':'FAIL','error_type':type(e).__name__}
def main():
    result={'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Local runtime smoke and active business-state verification; not E2E or dependency outage/load tests'}
    ids=docker('ps','-aq').split()
    cs=json.loads(docker('inspect',*ids))
    result['containers']=[{'name':c['Name'].lstrip('/'),'service':c['Config'].get('Labels',{}).get('com.docker.compose.service'),'project':c['Config'].get('Labels',{}).get('com.docker.compose.project'),'status':c['State']['Status'],'health':c['State'].get('Health',{}).get('Status','none'),'image_id':c['Image']} for c in cs]
    probes=[('gateway',8000,'/health/',[200]),('auth rejects anonymous admin',8001,'/admin/users/',[401,403]),('workspace rejects anonymous',8002,'/workspace/',[401,403]),('report rejects anonymous',8003,'/voice-reports/reports/',[401,403]),('voice rejects anonymous',8004,'/voice-reports/reports/',[401,403]),('AI health',8005,'/health/',[200]),('query dependency health',8006,'/query/health/',[200]),('visualization rejects anonymous',8007,'/visualization/question/1/embed-url/',[401,403]),('subscription health',8009,'/subscription/health/',[200]),('notification health',8010,'/notification/health/',[200]),('ETL connector health',8101,'/api/health/',[200]),('ETL metadata health',8106,'/api/health/',[200]),('Metabase restored copy health',3000,'/api/health',[200]),('frontend development page',5173,'/',[200])]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:result['http']=list(pool.map(check,probes))
    try:
        r=requests.post('http://127.0.0.1:8000/auth/login/',json={'email':'phase0-invalid@example.invalid','password':'not-a-real-password'},timeout=15)
        result['invalid_login']={'http_status':r.status_code,'status':'PASS' if r.status_code in (400,401) else 'FAIL'}
        r=requests.post('http://127.0.0.1:8000/auth/login/',json={'email':env.get('ADMIN_EMAIL'),'password':env.get('ADMIN_PASSWORD')},timeout=15)
        d=r.json();token=d.get('access')
        result['bootstrap_admin_login']={'http_status':r.status_code,'access_token_received':bool(token),'status':'PASS' if r.status_code==200 and token else 'FAIL'}
        if token:
            r=requests.get('http://127.0.0.1:8000/admin/users/',headers={'Authorization':'Bearer '+token},timeout=15)
            result['authorized_admin_route']={'http_status':r.status_code,'status':'PASS' if r.status_code==200 else 'FAIL'}
        del d
    except (requests.RequestException,ValueError) as e:result['auth_error']={'status':'FAIL','error_type':type(e).__name__}
    try:
        conn=psycopg2.connect(host='127.0.0.1',port=env.get('DB_PORT','5432'),dbname=env['DB_NAME'],user=env['DB_USER'],password=env['DB_PASSWORD'],connect_timeout=5,options='-c default_transaction_read_only=on -c statement_timeout=15000')
        cur=conn.cursor();counts={}
        for t in sorted(PG_CLEAR):
            cur.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(t)));counts[t]=cur.fetchone()[0]
        result['postgres_business_counts']=counts;result['postgres_clean']='PASS' if not any(counts.values()) else 'FAIL'
        conn.close()
    except Exception as e:result['postgres_clean']='FAIL';result['postgres_error_type']=type(e).__name__
    for name in ['query-service','voice-service','ai-service','etl-connector','etl-detector','etl-extractor','etl-transformer','etl-loader','etl-metadata']:
        try:
            logs=docker('logs','--tail','100',name)
            # Only serialize error category counts, never raw logs or credentials.
            result.setdefault('log_categories',{})[name]={x:logs.lower().count(x.lower()) for x in ['Traceback','ModuleNotFoundError','OperationalError','Consumer started','Listening']}
        except Exception:pass
    result['limitations']=['Anonymous denials establish route availability, not tenant isolation','Positive auth uses the existing environment-defined bootstrap principal; tokens are never serialized','No paid inference, SMTP send, signup, upload, source mutation or Metabase card execution','Docker TCP health does not establish worker/dependency readiness']
    (OUT/'startup_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('containers','log_categories','postgres_business_counts')},indent=2))
    return 0 if result.get('postgres_clean')=='PASS' and all(x['status']=='PASS' for x in result['http']) and result.get('bootstrap_admin_login',{}).get('status')=='PASS' and result.get('authorized_admin_route',{}).get('status')=='PASS' else 1
if __name__=='__main__':sys.exit(main())
