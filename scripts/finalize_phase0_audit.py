"""Validate audit artifacts and generate the final evidence index/console summary."""
from pathlib import Path
import ast,collections,datetime,json,re,subprocess
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs'/'audit'
required=['PRE_DEVELOPMENT_SYSTEM_AUDIT.md','SECURITY_AUDIT.md','DATA_STORAGE_AND_WIPE_REPORT.md','CURRENT_ARCHITECTURE.md','TARGET_MICROSERVICES_ARCHITECTURE.md','MICROSERVICES_RESTRUCTURING_PLAN.md','DATABASE_OWNERSHIP_MATRIX.md','SERVICE_COMMUNICATION_MATRIX.md','PRODUCTION_READINESS_REPORT.md','PRE_DEVELOPMENT_ACTION_PLAN.md','issues.json']
issues=json.loads((OUT/'issues.json').read_text());counts=collections.Counter(x['severity'] for x in issues)
assert len({x['id'] for x in issues})==len(issues)
for i in issues:
    assert all(i.get(k) for k in ['id','severity','category','service','description','solution','phase','evidence','risk','migration_impact','estimated_complexity'])
    assert i['phase'] in ['P0','P1','P2','P3']
assert all((OUT/f).is_file() and (OUT/f).stat().st_size for f in required)
startup=json.loads((OUT/'startup_verification.json').read_text());storage=json.loads((OUT/'final_storage_verification.json').read_text())
assert all(r['status']=='PASS' for r in startup['http']) and startup['postgres_clean']=='PASS'
assert storage['backup_files_status']=='PASS' and storage['active_file_stores_empty']
assert not any(storage['clickhouse_after_startup'].values())
business_offsets=[s for s in storage['kafka_offsets'].splitlines() if s and not s.startswith('__consumer_offsets:')]
assert all(s.rsplit(':',1)[1]=='0' for s in business_offsets)
backup=json.loads((OUT/'backup_manifest.json').read_text())
backup['status']='FILES VERIFIED; POSTGRESQL RESTORE AND METABASE RESTORED-COPY STARTUP PASS; OTHER FULL RESTORE DRILLS NOT VERIFIED'
backup['final_sha256_verification']='All 37 original entries match after startup; final_storage_verification.json'
backup['restore_evidence']=['postgres_restore_verification.json','metabase_metadata_verification.json','startup_verification.json']
for entry in backup['entries']:
    if entry['resource']=='postgres:bi_voice_agent':entry['verification']='pg_restore --list and isolated restore/count parity PASS'
    if entry['resource']=='metabase:H2':entry['verification']='offline copy/hash PASS; H2 database copy opens and same-image application startup PASS'
(OUT/'backup_manifest.json').write_text(json.dumps(backup,indent=2),encoding='utf-8')
reset=json.loads((OUT/'reset_execution.json').read_text());reset['status']='ACTIVE DATA CLEANED; LOCAL STARTUP SMOKE PASS; OVERALL PHASE 0 ACCEPTANCE PARTIAL'
reset['post_startup_evidence']=['startup_verification.json','final_storage_verification.json','STARTUP_VERIFICATION.md']
reset['limitations']=['Historical volumes and Metabase metadata intentionally preserved','Model/migration parity fails in voice and notification','Full functional workflow and new-empty-PostgreSQL migration NOT VERIFIED']
(OUT/'reset_execution.json').write_text(json.dumps(reset,indent=2),encoding='utf-8')
summary={'environment':'LOCAL DEVELOPMENT','audit_status':'COMPLETE','phase0_acceptance':'PARTIAL','data_cleanup':'PARTIAL overall; active application data PASS','backup':'PASS file verification; PostgreSQL/Metabase scoped recovery PASS; full DR PARTIAL','services_discovered':'24 Compose entries + frontend, PostgreSQL, Ollama, Metabase = 28 runtime roles','database_inventory':'6 data engine families (PostgreSQL, ClickHouse, SurrealDB, Redis, H2, SQLite); Kafka/ZooKeeper additional state stores','issues':dict(counts),'cross_service_db_violations':'4 grouped: shared PostgreSQL identity; notification foreign ORM (5 tables); multi-owner ClickHouse; multi-owner SurrealDB','non_http_business_paths':'6 grouped: 5 ETL Kafka workflow paths + shared uploaded files; voice events UNDECIDED','services_without_proper_health_checks':'17 application/worker entries: 16 TCP-only + one missing; ZooKeeper also uses TCP-only infrastructure probe','production_blockers':counts['CRITICAL']+counts['HIGH'],'blocker_definition':'unresolved CRITICAL + HIGH findings; do not add overlapping category counts','production_readiness':'NOT READY','microservices_architecture':'NOT COMPLIANT','database_per_service':'NOT COMPLIANT','http_only_business_communication':'NOT COMPLIANT','tests':{'passed':411,'failed':46,'additional_passing_subtests':17,'collection_errors':'separate; see TEST_EXECUTION.md'},'startup':'PASS: 24 Compose containers running, 14 HTTP probes, bootstrap login and authorized route','migrations':'Existing commands PASS; voice/notification model-state parity FAIL','backup_directory':backup['backup_directory']}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
blockers=['Retained exposed credentials','Voice workspace fail-open','Unowned dataset binding mutation','Unscoped Metabase object access','Visualization raw-SQL bypass','Public ETL / SSRF / fallback encryption / exposed ports','Existing-account invitation password mutation','Surreal, Metabase and media durability','Shared databases and non-HTTP workflows','Migration drift, failing tests and weak readiness']
tasks=['Rotate all exposed credentials and verify revocation','Make voice workspace authorization fail closed','Authorize ingestion callbacks and harden physical dataset identifiers','Enforce tenant ownership for Metabase cards/dashboard embeds','Replace arbitrary visualization SQL with authorized query IDs','Authenticate/isolate ETL and restrict connectors/secrets','Require existing-user authentication for invitation acceptance','Persist and restore-test metadata, Metabase and media','Review and reconcile voice/notification migrations','Repair test/lint baseline, implement readiness and gate CI']
lines=['BIAVORA PHASE 0 AUDIT COMPLETE','Phase 0 acceptance: PARTIAL','']+[f'{k}: {v}' for k,v in summary.items() if k not in ['audit_status','phase0_acceptance','backup_directory']]
lines += ['','TOP 10 BLOCKERS']+[f'{i}. {v}' for i,v in enumerate(blockers,1)]+['','THE EXACT FIRST 10 TASKS']+[f'{i}. {v}' for i,v in enumerate(tasks,1)]+['','Reports:']+['docs/audit/'+f for f in required]
(OUT/'CONSOLE_SUMMARY.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
intro='''# Phase 0 audit index

**Audit complete; Phase 0 acceptance PARTIAL; production NOT READY.** Active business data is cleared and local startup smoke passes. Historical archives and Metabase metadata are intentionally preserved. Voice/notification migration parity, failing tests and critical security findings remain open.

Start with [the practical action plan](PRE_DEVELOPMENT_ACTION_PLAN.md), [console summary](CONSOLE_SUMMARY.txt), [main audit](PRE_DEVELOPMENT_SYSTEM_AUDIT.md), [data/backup report](DATA_STORAGE_AND_WIPE_REPORT.md), and [startup evidence](STARTUP_VERIFICATION.md).

## Required reports

'''
intro+='\n'.join(f'- [{f}]({f})' for f in required)
intro+='\n\n## Supporting evidence\n\n'+ '\n'.join(f'- [{f}]({f})' for f in ['SERVICE_INVENTORY.md','API_INVENTORY.md','ENVIRONMENT_VARIABLE_INVENTORY.md','TEST_EXECUTION.md','STARTUP_VERIFICATION.md','MODIFICATION_LEDGER.md','inventory.json','runtime_inventory.json','storage_detail.json','DATA_WIPE_MANIFEST.json','backup_manifest.json','postgres_restore_verification.json','metabase_metadata_verification.json','migration_verification.json','container_migration_verification.json','migration_drift_detail.json','startup_verification.json','final_storage_verification.json','summary.json'])
intro+='\n\nBefore-state files are immutable snapshots of the original deployment. Startup/final-storage files describe the later verification. Counts are scoped and explained; NOT VERIFIED is not PASS. Backups are ignored and intentionally not linked as public downloadable artifacts.\n'
(OUT/'README.md').write_text(intro,encoding='utf-8')
scripts=sorted(p for p in (ROOT/'scripts').glob('*.py') if p.name.startswith('audit_') or p.name in ['reset_dev.py','write_phase0_reports.py','finalize_phase0_audit.py'])
for p in scripts:ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
ignores=['.dockerignore','etl-final/.dockerignore']+[f'services/{s}/.dockerignore' for s in ['api-gateway','auth-service','workspace-service','subscription-service','notification-service']]
ledger='''# Modification and runtime ledger

Repository branch `main`, HEAD `1ca062c`; existing user edits were retained. `inventory.json.git_status_before` and `git_status_after.txt` record status snapshots. No commits, history rewrite, hard reset, or architecture/feature implementation occurred.

## Added files

All files in `docs/audit/` were added by this audit, including the mail-disabled startup override and generated evidence. New audit/reset scripts:

'''+ '\n'.join('- `'+p.relative_to(ROOT).as_posix()+'`' for p in scripts)+'\n- `scripts/reset-dev.ps1`\n- `backups/.gitignore`\n'+ '\n'.join('- `'+s+'`' for s in ignores)
ledger+='''

## Files/data changed

Three ignored local test audio files under root `media/` were backed up and removed. Exact names and hashes are in DATA_WIPE_MANIFEST.json. Thirty-seven backed-up volume files were removed; two current-voice writable-layer inputs were backed up before recreation. Generated frontend `dist/` and normal ignored test/runtime artifacts may have been refreshed. Source application files, existing Compose, existing `.gitignore`, existing reset scripts, credentials and migrations were not edited.

The nested TimesFM repository already had an untracked `run.py` (April 2026). Its outer Git status renders differently in short versus porcelain output; nested status confirms no tracked vendor edits. It was preserved.

## Runtime operations

Created 37 backup files (~5.82 GiB), a separate Metabase restore-check working copy, and PostgreSQL `phase0_restore_20260913` containing the restored pre-reset database. Truncated 21 active PostgreSQL and five ClickHouse tables, removed four exact Redis keys, verified Kafka business offsets zero, and removed only manifest-listed files. Unknown/historical volumes were preserved.

Built 17 images and started/recreated the 24 root Compose services with mail disabled. Ran existing migrations and read-only migration drift checks; no new migration applied. Started `phase0-metabase-restore` from the verified copy with scheduler disabled; original Metabase remains stopped. Started frontend Vite bound to 127.0.0.1:5173. Host PostgreSQL/Ollama were already available. All source changes remain uncommitted for review.

No SMTP messages, external tickets, paid inference calls or production deployment were performed. External provider key validity was not probed. The required credential rotation remains a user/provider administration task in the next action plan.
'''
(OUT/'MODIFICATION_LEDGER.md').write_text(ledger,encoding='utf-8')
main=OUT/'PRE_DEVELOPMENT_SYSTEM_AUDIT.md'
append='''

## Final runtime disposition

The targeted active-data cleanup passed after startup; all 37 original backup hashes still match. All 24 root Compose services are running (23 configured healthy; expiry worker has no probe), 14 HTTP probes and bootstrap-admin authorization pass, and existing migrations executed for all 16 application configurations. Voice/notification model-state checks fail; 46 selected tests fail and frontend lint is unconfigured. Metabase metadata was recovered into a separate running copy; the original remains stopped. Overall Phase 0 acceptance is PARTIAL, production NOT READY. See [startup verification](STARTUP_VERIFICATION.md), [data/reset report](DATA_STORAGE_AND_WIPE_REPORT.md), [action plan](PRE_DEVELOPMENT_ACTION_PLAN.md), and [modification ledger](MODIFICATION_LEDGER.md).
'''
content=main.read_text(encoding='utf-8');content=content.split('\n## Final runtime disposition')[0];main.write_text(content.rstrip()+'\n'+append,encoding='utf-8')
env=dotenv_values(ROOT/'.env');secret_values=[v for k,v in env.items() if v and len(v)>=8 and any(s in k.upper() for s in ['SECRET','PASSWORD','TOKEN','API_KEY'])]
hits=[]
for p in OUT.rglob('*'):
    if p.is_file():
        text=p.read_text(encoding='utf-8',errors='replace')
        if any(v in text for v in secret_values):hits.append(p.name)
assert not hits,'Secret value found in audit artifacts; filenames only: '+str(hits)
broken=[]
for p in OUT.glob('*.md'):
    for dest in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf-8')):
        if '://' not in dest and not dest.startswith('#') and not (p.parent/dest.split('#')[0]).exists():broken.append((p.name,dest))
assert not broken,str(broken)
validation={'required_reports':len(required),'unique_issues':len(issues),'script_ast':'PASS','internal_report_links':'PASS','current_env_secret_value_scan':'PASS; values never serialized','scope':'No exhaustive historical/provider secret scan claim','timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(OUT/'artifact_validation.json').write_text(json.dumps(validation,indent=2),encoding='utf-8')
print('\n'.join(lines))
