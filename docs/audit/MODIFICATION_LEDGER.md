# Modification and runtime ledger

Repository branch `main`, HEAD `1ca062c`; existing user edits were retained. `inventory.json.git_status_before` and `git_status_after.txt` record status snapshots. No commits, history rewrite, hard reset, or architecture/feature implementation occurred.

## Added files

All files in `docs/audit/` were added by this audit, including the mail-disabled startup override and generated evidence. New audit/reset scripts:

- `scripts/audit_backup.py`
- `scripts/audit_container_migrations.py`
- `scripts/audit_final_storage.py`
- `scripts/audit_inventory.py`
- `scripts/audit_metabase_h2.py`
- `scripts/audit_migrations.py`
- `scripts/audit_restore_postgres.py`
- `scripts/audit_runtime.py`
- `scripts/audit_storage_detail.py`
- `scripts/audit_verify_startup.py`
- `scripts/finalize_phase0_audit.py`
- `scripts/reset_dev.py`
- `scripts/write_phase0_reports.py`
- `scripts/reset-dev.ps1`
- `backups/.gitignore`
- `.dockerignore`
- `etl-final/.dockerignore`
- `services/api-gateway/.dockerignore`
- `services/auth-service/.dockerignore`
- `services/workspace-service/.dockerignore`
- `services/subscription-service/.dockerignore`
- `services/notification-service/.dockerignore`

## Files/data changed

Three ignored local test audio files under root `media/` were backed up and removed. Exact names and hashes are in DATA_WIPE_MANIFEST.json. Thirty-seven backed-up volume files were removed; two current-voice writable-layer inputs were backed up before recreation. Generated frontend `dist/` and normal ignored test/runtime artifacts may have been refreshed. Source application files, existing Compose, existing `.gitignore`, existing reset scripts, credentials and migrations were not edited.

The nested TimesFM repository already had an untracked `run.py` (April 2026). Its outer Git status renders differently in short versus porcelain output; nested status confirms no tracked vendor edits. It was preserved.

## Runtime operations

Created 37 backup files (~5.82 GiB), a separate Metabase restore-check working copy, and PostgreSQL `phase0_restore_20260913` containing the restored pre-reset database. Truncated 21 active PostgreSQL and five ClickHouse tables, removed four exact Redis keys, verified Kafka business offsets zero, and removed only manifest-listed files. Unknown/historical volumes were preserved.

Built 17 images and started/recreated the 24 root Compose services with mail disabled. Ran existing migrations and read-only migration drift checks; no new migration applied. Started `phase0-metabase-restore` from the verified copy with scheduler disabled; original Metabase remains stopped. Started frontend Vite bound to 127.0.0.1:5173. Host PostgreSQL/Ollama were already available. All source changes remain uncommitted for review.

No SMTP messages, external tickets, paid inference calls or production deployment were performed. External provider key validity was not probed. The required credential rotation remains a user/provider administration task in the next action plan.
