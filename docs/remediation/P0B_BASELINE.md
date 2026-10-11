# P0-B baseline

Captured before P0-B source/configuration changes on 2026-09-30 (Asia/Damascus).

## Repository identity

- Repository: `BI-Voice-Agent`
- Branch: `main`
- HEAD: `1ca062ca330655fc68b5f363e9d6d0b4fad19a6c`
- Upstream state: one commit ahead of `origin/main`, zero behind.
- The repository root is `C:\Users\massa\Desktop\senior 1\BI-Voice-Agent`; the parent workspace contains an incomplete, nonfunctional `.git` directory and is not the project repository.

## Preservation state

The worktree is intentionally and extensively dirty. Before this file was created, `git status --porcelain=v1 --untracked-files=all` reported:

- 369 status entries.
- 209 tracked changes.
- 160 untracked files.
- 1 staged entry.
- 208 worktree entries.

The exact pre-P0-B status is preserved in `P0B_GIT_STATUS_BEFORE.txt`. All existing changes are treated as user/P0-A work. P0-B will not reset, clean, stash, check out over, or commit them automatically.

P0-A artifacts present before P0-B:

- `docs/remediation/P0A_BASELINE.md`
- `docs/remediation/P0A_IMPLEMENTATION_REPORT.md`
- `docs/remediation/P0A_MODIFICATION_LEDGER.md`
- `docs/remediation/P0A_SECURITY_TEST_MATRIX.md`
- `docs/remediation/SECRET_ROTATION_CHECKLIST.md`

P0-A migrations present and preserved:

- Query `0003_database_ingestion_job_id.py`
- Query `0004_authorizedquerydefinition.py`
- Visualization `0001_visualizationobjectownership.py`

All three are untracked at this baseline and therefore especially protected from cleanup.

## Existing migration files

The full current migration file inventory is captured in the command transcript. Application heads before P0-B are:

- Auth: `0003`
- Workspace: `0006`
- Subscription: `0002`
- Notification: `0001`
- Query: `0004` (P0-A)
- Visualization: `0001` (P0-A)
- Voice: `0012`
- API Gateway, AI application modules, Report, and ETL Django modules have no first-party domain migration beyond framework or empty migration packages.

## Backup preservation

- Phase 0 backup directory present: `backups/phase0-20260913T141937Z`.
- The audit manifest records 37 verified files totaling 6,246,565,431 bytes.
- The original Metabase H2 copy and trace are present under that backup directory and must remain unchanged.
- No backup, historical volume, or unknown volume is authorized for deletion.

## Docker/Compose baseline

Read-only Docker access was obtained after the initial sandbox denial.

- Docker Desktop 4.45.0, Engine 28.3.3, Linux/WSL2 backend.
- 33 containers exist; all are stopped/exited.
- The extra `phase0-metabase-restore` verification container is stopped.
- 555 Docker volumes exist: 15 human-named volumes and 540 anonymous/hash-named volumes.
- No volume was removed, pruned, renamed, or attached by this baseline step.
- Root Compose currently declares memory-only SurrealDB with a mounted `surreal_data` volume.
- Root Compose currently has no active Voice `/app/media` mount; only the stopped legacy Voice worker uses `bi-voice-agent_voice_service_media`.
- Kafka and ZooKeeper use anonymous data volumes in the inspected runtime.
- Metabase is a standalone stopped container with no application-database mount or `MB_DB_*` settings.

Known named volumes:

- `bi-voice-agent_clamav_data`
- `bi-voice-agent_clickhouse_data`
- `bi-voice-agent_clickhouse_logs`
- `bi-voice-agent_redis_data`
- `bi-voice-agent_surreal_data`
- `bi-voice-agent_uploaded-files`
- `bi-voice-agent_voice_service_media`
- `bi-voice-agent_whisper_cache`
- `etl-final_clamav_data`
- `etl-final_clickhouse_data`
- `etl-final_clickhouse_logs`
- `etl-final_clickhouse-data`
- `etl-final_clickhouse-logs`
- `etl-final_surreal_data`
- `etl-final_uploaded-files`

## Starting blockers and safety constraints

- The original PostgreSQL source is host PostgreSQL 18.3 and must not be used for first-run migration validation.
- Current host access previously failed through `pg_hba.conf`; P0-B will use disposable restored/empty PostgreSQL instances instead of weakening authentication.
- Historical SurrealDB memory-only state is not recoverable from the archived empty mounted volume.
- External credential rotation remains pending and no provider action is claimed.
- The working tree and the 555-volume inventory are preservation boundaries for all P0-B work.


