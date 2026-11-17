"""Isolated live two-controller lease takeover and Connect mutation fence."""
import argparse
import json
from pathlib import Path
import subprocess
import uuid

from verify_foundation_d_cdc import Fixture


ROOT = Path(__file__).resolve().parents[1]


def internal(fixture, method, body=None):
    response = fixture.session.request(method, fixture.base+'/internal/v1/cdc/',
        json=body, headers={'X-Cdc-Stage':'controller',
                            'X-Cdc-Key':fixture.env['CDC_CONTROLLER_KEY']}, timeout=15)
    return response


def physical(fixture, scope, owner, fence, action, success=True):
    code = (
        'import json,sys; '
        'from bi_platform_shared.cdc_contract import Scope; '
        'from shared.cdc.worker import ControlPlane,FencedConnect; '
        'from shared.cdc.connect import ConnectClient; '
        's=Scope(**json.loads(sys.argv[1])); '
        'c=ControlPlane("controller"); c.owner=sys.argv[2]; '
        'c.fences[s.pipeline_id]=int(sys.argv[3]); '
        'client=ConnectClient(); '
        'getattr(FencedConnect(client,c,s),sys.argv[4])(s); '
        'client.wait_stopped(s) if sys.argv[4]=="pause" else None')
    command = ['docker','compose','--project-name','biavora_foundation_d',
               '--env-file',str(fixture.env_file),'-f',str(ROOT/'docker-compose.cdc-local.yml'),
               'run','--rm','--no-deps','--entrypoint','python','controller','-c',code,
               json.dumps(scope),owner,str(fence),action]
    result = subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=35)
    if (result.returncode == 0) != success:
        raise AssertionError(f'{action} unexpected physical fence result {result.returncode}')


def run(env_file):
    fixture = Fixture(env_file)
    with fixture.pg('biavora') as connection:
        with connection.cursor() as cursor:
            cursor.execute('''SELECT p.id FROM integration_cdc_pipelines p
                              JOIN integration_cdc_generations g
                                ON g.pipeline_id=p.id AND g.number=p.generation
                              WHERE g.state='ACTIVE' AND g.number=2
                              ORDER BY p.created_at DESC LIMIT 1''')
            pipeline_id = str(cursor.fetchone()[0])
    items = internal(fixture,'GET').json()['pipelines']
    item = next(i for i in items if i['scope']['pipeline_id']==pipeline_id)
    scope = item['scope']
    fixture.compose('stop','controller')
    try:
        def expire():
            with fixture.pg('biavora') as connection:
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE integration_cdc_pipelines SET controller_lease_until=now()-interval '1 second' WHERE id=%s",
                                   (pipeline_id,))
        expire()
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        def claim(owner):
            response = internal(fixture,'POST',{'action':'claim','pipeline_id':pipeline_id,
                                                 'scope':scope,'owner':owner})
            if response.status_code != 200:
                raise AssertionError(f'controller claim HTTP {response.status_code}')
            return response.json()['fence']
        first = claim(a)
        expire()
        second = claim(b)
        assert second > first
        physical(fixture,scope,a,first,'pause',success=False)
        # The new owner can perform actual private Connect lifecycle calls.
        physical(fixture,scope,b,second,'pause')
        physical(fixture,scope,b,second,'resume')
        assert internal(fixture,'POST',{'action':'verify','pipeline_id':pipeline_id,
              'scope':scope,'lease_owner':a,'lease_fence':first}).status_code == 409
        expire()
    finally:
        fixture.compose('start','controller')
    result = {'pipeline_id':pipeline_id,'old_fence':first,'new_fence':second,
              'stale_connect_mutation_rejected':True,'new_owner_connect_pause_resume':True}
    path=Path(env_file).resolve().parent/f'd5-r1-fence-results-{uuid.uuid4().hex[:8]}.json'
    path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'result':result,'evidence':str(path)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--env-file',required=True)
    args=parser.parse_args()
    run(args.env_file)
