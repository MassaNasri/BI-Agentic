"""Open a disposable copy of backed-up H2 with the original Metabase image, offline."""
from pathlib import Path
import json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs'/'audit'
m=json.loads((OUT/'backup_manifest.json').read_text());backup=Path(m['backup_directory'])
source=next(Path(e['path']) for e in m['entries'] if e['resource']=='metabase:H2' and e['path'].endswith('.mv.db'))
target=backup/'metabase-restore-check';target.mkdir(exist_ok=True)
copy=target/'metabase.db.mv.db'
if not copy.exists():shutil.copy2(source,copy)
query='SELECT COUNT(*) AS cards FROM report_card; SELECT COUNT(*) AS dashboards FROM report_dashboard; SELECT COUNT(*) AS collections FROM collection; SELECT id, name, engine FROM metabase_database;'
args=['docker','run','--rm','--network','none','--entrypoint','java','--mount',f'type=bind,source={target},target=/audit','metabase/metabase','-cp','/app/metabase.jar','org.h2.tools.Shell','-url','jdbc:h2:file:/audit/metabase.db;IFEXISTS=TRUE','-user','','-password','','-sql',query]
p=subprocess.run(args,capture_output=True,text=True,timeout=120)
result={'exit_code':p.returncode,'offline':True,'query':'card/dashboard/collection counts and source engine/name only','output':p.stdout,'error_type':'H2_TOOL_FAILED' if p.returncode else None,'diagnostic':p.stderr[:2500],'original_backup_unchanged':True}
(OUT/'metabase_metadata_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
