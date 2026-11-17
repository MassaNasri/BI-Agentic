"""Supplemental read-only 2,500-row page timing on the retained disposable scope."""
import argparse
import json
from pathlib import Path
import time
import tracemalloc

from bi_platform_shared.cdc_contract import Scope
from bi_platform_shared.cdc_reconciliation import chunk_digest
from verify_foundation_d_cdc import Fixture


parser=argparse.ArgumentParser()
parser.add_argument('--env-file',required=True)
parser.add_argument('--evidence',required=True)
args=parser.parse_args()
fixture=Fixture(args.env_file)
previous=json.loads(Path(args.evidence).read_text(encoding='utf-8'))
scope=Scope(**previous['candidate'])
database=json.loads(Path(previous['prior_mismatch_evidence']).read_text(encoding='utf-8'))['source_database']
columns=previous['certificate']['columns']
names=[column['name'] for column in columns]
tracemalloc.start()
source_hashes=[]
source_read_ns=source_digest_ns=0
with fixture.pg(database) as connection:
    with connection.cursor(name='r4a_benchmark') as cursor:
        cursor.itersize=500
        cursor.execute('SELECT id,customer,amount,status FROM public.orders WHERE id<=2500 ORDER BY id')
        while True:
            started=time.perf_counter_ns()
            rows=cursor.fetchmany(500)
            source_read_ns+=time.perf_counter_ns()-started
            if not rows:
                break
            started=time.perf_counter_ns()
            source_hashes.append(chunk_digest((dict(zip(names,row)) for row in rows),columns))
            source_digest_ns+=time.perf_counter_ns()-started
source_peak=tracemalloc.get_traced_memory()[1]
candidate_hashes=[]
candidate_read_ns=candidate_digest_ns=0
view=f'etl.cdc_{scope.token}_current'
for page in range(5):
    started=time.perf_counter_ns()
    rows=fixture.ch.query(
        'SELECT toString(id) AS __cdc_value_0,toString(customer) AS __cdc_value_1,'
        'toString(amount) AS __cdc_value_2,toString(status) AS __cdc_value_3 '
        f'FROM {view} WHERE id<=2500 ORDER BY id LIMIT 500 OFFSET {page*500}').result_rows
    candidate_read_ns+=time.perf_counter_ns()-started
    assert len(rows)==500
    started=time.perf_counter_ns()
    candidate_hashes.append(chunk_digest((dict(zip(names,row)) for row in rows),columns))
    candidate_digest_ns+=time.perf_counter_ns()-started
candidate_peak=tracemalloc.get_traced_memory()[1]
tracemalloc.stop()
assert source_hashes==candidate_hashes and len(source_hashes)==5
result={'status':'PASS','scope_token':scope.token,'rows':2500,'chunk_count':5,
        'source_fetch_ms':round(source_read_ns/1e6,3),
        'source_digest_ms':round(source_digest_ns/1e6,3),
        'candidate_direct_read_ms':round(candidate_read_ns/1e6,3),
        'candidate_direct_digest_ms':round(candidate_digest_ns/1e6,3),
        'source_peak_tracemalloc_bytes':source_peak,
        'candidate_peak_tracemalloc_bytes':candidate_peak,
        'authorized_Query_total_ms_from_certificate':previous['certificate']['query_duration_ms'],
        'reconciliation_total_ms_from_certificate':previous['certificate']['duration_ms'],
        'note':'Supplemental direct physical paging benchmark; the MATCH certificate used internal authorized Query.'}
path=fixture.env_file.parent/'d5-r4a-near-limit-page-benchmark.json'
path.write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({'evidence':str(path),**result}),flush=True)
