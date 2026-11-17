"""Read-only first-page digest diagnosis for the disposable 2,500-row scope."""
import argparse
import json
from pathlib import Path

from bi_platform_shared.cdc_contract import Scope
from bi_platform_shared.cdc_reconciliation import chunk_digest, row_bytes
from verify_foundation_d_cdc import Fixture


parser=argparse.ArgumentParser()
parser.add_argument('--env-file',required=True)
parser.add_argument('--evidence',required=True)
args=parser.parse_args()
fixture=Fixture(args.env_file)
evidence=json.loads(Path(args.evidence).read_text(encoding='utf-8'))
scope=Scope(**evidence['candidate'])
columns=evidence['certificate']['columns']
with fixture.pg(evidence['source_database']) as connection:
    with connection.cursor() as cursor:
        cursor.execute('SELECT id,customer,amount,status FROM public.orders ORDER BY id LIMIT 500')
        source=[dict(zip(['id','customer','amount','status'],row)) for row in cursor.fetchall()]
view=f'cdc_{scope.token}_current'
query=[dict(zip(['id','customer','amount','status'],row)) for row in fixture.ch.query(
    f'SELECT toString(id) AS __cdc_value_0,toString(customer) AS __cdc_value_1,'
    f'toString(amount) AS __cdc_value_2,toString(status) AS __cdc_value_3 '
    f'FROM etl.{view} ORDER BY id LIMIT 500').result_rows]
direct=fixture.ch.query(f'SELECT id,customer,amount,status FROM etl.{view} ORDER BY id LIMIT 500').result_rows
print(json.dumps({'source_count':len(source),'query_count':len(query),'direct_count':len(direct),
  'source_first':source[0],'query_first':query[0],'direct_first':direct[0],
  'source_first_bytes':row_bytes(source[0],columns).decode(),
  'query_first_bytes':row_bytes(query[0],columns).decode(),
  'source_first_digest':chunk_digest(source[:1],columns),
  'query_first_digest':chunk_digest(query[:1],columns),
  'source_chunk_digest':chunk_digest(source,columns),
  'query_chunk_digest':chunk_digest(query,columns)},default=str),flush=True)
