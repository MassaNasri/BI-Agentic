# Data storage and wipe report

Audit: 2026-09-13, **LOCAL DEVELOPMENT**. Active-data reset executed; overall cleanup is **PARTIAL** because historical storage and Metabase metadata are intentionally preserved. No claim of erasing every historical copy is made. See `reset_execution.json` for immediate after-state and `startup_verification.json` for the later runtime check.

## Proven environment and scope

Docker context used a local Windows named pipe. PostgreSQL was reached at 127.0.0.1:5432, database `bi_voice_agent`, through the configured non-superuser `bi_admin`; source configuration uses `host.docker.internal`. All 32 existing containers were stopped when offline backups began. No external database or production resource was modified. Host PostgreSQL and Ollama are outside Compose. Unknown databases, unknown volumes, model caches, secrets, and configuration were excluded from deletion.

The application database was identified from configuration and actual connections, not its directory name. `runtime_inventory.json` records the original container IDs, 555 volume names/mounts/labels, networks, ports, database roles, tables, counts and foreign keys. It is the before-state snapshot. `DATA_WIPE_MANIFEST.json` was generated before reset and lists exact table, key and file targets. Application processes remained stopped while records and files were cleared.

## Stores and disposition

| Store | Actual location / baseline | Backup and cleanup |
| --- | --- | --- |
| PostgreSQL application | Windows PostgreSQL 18.3, `bi_voice_agent`, 27 public tables; nine core configurations share credentials | Custom-format dump; restored into separate `phase0_restore_20260913`, all 27 table counts matched. 21 explicitly listed business/session tables truncated without CASCADE; six framework/configuration tables retained. |
| Other PostgreSQL databases | Server enumeration in runtime inventory | Not application reset targets; no deletion. New restore-check DB intentionally contains the old data and is not configured for application traffic. |
| Current ClickHouse | `clickhouse`, `bi-voice-agent_clickhouse_data`, database `etl`, six tables | Offline data and log archives. Truncated five data/quality/dedup tables; empty schema registry and all schemas preserved. |
| Historical ClickHouse | Two known legacy data volumes and logs, plus tracked `etl-final/etl-infra/clickhouse/data` snapshot | Backed up and intentionally retained. These are historical copies, not currently mounted serving data. Unknown archive provenance prevents blanket deletion. |
| SurrealDB | `surrealdb`, configured `memory`, namespace/database referenced as `bi_etl/etl_logs` | Mounted volume archived; it cannot contain the former in-memory database. Service was already stopped, so prior metadata is **NOT RECOVERABLE FROM THIS VOLUME / NOT VERIFIED**. Started root instance was empty; no namespace deletion performed. |
| Redis | `redis`, named AOF/RDB volume | Offline archive. Native keyspace inspection found four persistent Kombu binding keys in DB 1 and no other populated DBs. Removed only those exact keys with UNLINK; no FLUSHALL. |
| Kafka | `kafka`, anonymous broker data volume; 15 business topics plus consumer offsets | Offline broker archive; 15 business partition end offsets were zero before reset. Retained topics/config and consumer groups; no topic deletion or log truncation was needed. Topic/alias names and offsets are in wipe manifest. |
| ZooKeeper | Anonymous data/log volumes | Both archived; broker coordination state retained. |
| Metabase application metadata | Standalone `metabase`; no mounts or MB_DB_* settings; `/metabase.db/metabase.db.mv.db` in writable container layer | Copied while stopped, with trace file. Original metadata preserved separately from ClickHouse business data. Offline restore-copy result is in `metabase_metadata_verification.json`. Production migration to dedicated PostgreSQL remains required. |
| SQLite | 13 current/legacy configured container paths and one local file | Copied and inspected: integrity check OK; initially no application tables. AI/ETL use container-local files, so replacement loses runtime state. The later migrations/startup results distinguish disposable migration checks from actual service containers. |
| Current ETL uploads | `bi-voice-agent_uploaded-files` | Archive verified, then nine exact backed-up files removed; directories retained. |
| Legacy voice media | `bi-voice-agent_voice_service_media` | Archive verified; 21 backed-up files removed; directories retained. |
| Legacy ETL uploads | `etl-final_uploaded-files` | Archive verified; seven backed-up files removed; directories retained. |
| Current voice media | `/app/media` in original voice container writable layer, two old input files (23 and 16 bytes) | Both copied and hashed before container replacement. Rebuilding/recreating voice removes that old writable layer; no media volume exists in current Compose. This is a durability defect, not an acceptable production reset mechanism. |
| Local media | Root `media/` | Archived; three exact test audio files removed with resolved-path containment and hash verification. |
| Model / malware caches | AI model caches and ClamAV signatures | Preserved as infrastructure assets; no paid inference or model-cache reset. |
| Other Docker volumes | Full list of 555 baseline volumes in runtime inventory | Preserved. No `docker volume prune`, `compose down -v`, or assumption that every anonymous volume belongs to this application. |
| Secrets and source | `.env`, examples, credentials, source, migrations, Git worktree | Preserved. Secret rotation is required separately; ignore rules are not rotation. Existing user changes were not overwritten. |

## Backup evidence

Backup directory: `backups/phase0-20260913T141937Z` inside the repository (ignored by `backups/.gitignore`). **37 manifest entries, 6,246,565,431 bytes (about 5.82 GiB)**. Each file has a recorded SHA-256 and size in `backup_manifest.json`. Archive directories were read successfully before reset. The PostgreSQL dump is 4,672,736 bytes; original Metabase H2 is 19,910,656 bytes plus a 51,504-byte trace file.

**Backup creation/file verification: PASS. Full recovery readiness: PARTIAL.** PostgreSQL has a real restore drill with count parity. Metabase has a separate offline copy verification record. ClickHouse/Kafka/Redis/ZooKeeper archives were checked structurally and by hash, but full service restore drills were not completed. The already-stopped Surreal memory state was unavailable before this audit. Backups remain on the same host, contain sensitive historical data, and are not a substitute for encrypted off-host backups or tested RPO/RTO. No backups were deleted.

Metabase metadata is an explicit preservation exception: saved cards/dashboards/source settings may still refer to now-empty business tables. Its saved configuration and users are not the SaaS `users` table. Before future cleanup, map every card/dashboard to tenant ownership and decide which generated objects can be archived; do not infer that all metadata is disposable. Follow [Metabase backup guidance](https://www.metabase.com/docs/latest/installation-and-operation/backing-up-metabase-application-data) and the [H2 migration procedure](https://www.metabase.com/docs/latest/installation-and-operation/migrating-from-h2).

## Executed reset and immediate checks

PostgreSQL cleared: users/groups memberships, workspaces, workspace members, invitations, reports, dashboard pages, page assignments, SQL edit history, voice jobs, password-reset codes, Django sessions/admin logs, outstanding/blacklisted refresh tokens, notification logs, subscriptions, free-tier usage, test payments and dataset bindings. Every targeted table was zero immediately after commit. Preserved: `auth_group`, `auth_group_permissions`, `auth_permission` (96), `django_content_type` (24), `django_migrations` (56), `subscription_plans` (2). No schema or migration history was dropped. The environment-defined system-admin bootstrap mechanism was retained; no old SaaS users remain.

ClickHouse immediate after-counts were zero for all six tables. Before counts were deduplication_log 540, quality_metrics 2, sales_3months_realistic_csv 180; quality_anomalies, quarantine and schema_contract_registry were already zero. Five explicit TRUNCATE operations preserved table definitions. Active Redis keyspace was empty after four exact UNLINK operations. Kafka business topics were already empty; the reset did not fabricate a queue-cleaning operation.

Forty files were explicitly deleted across three volumes and local media. Two additional old current-voice input files were backed up before that container was replaced. Recreated containers may initialize empty directories, migrations, framework permissions, metadata configuration or queue bindings; those are fresh runtime state, not retained user records. Final checks must assess business tables rather than demand that infrastructure contain no bytes.

## Commands and repeatable workflow

New tooling: `audit_inventory.py`, `audit_runtime.py`, `audit_backup.py`, `audit_storage_detail.py`, `audit_restore_postgres.py`, `audit_metabase_h2.py`, `reset_dev.py`, `reset-dev.ps1`, `audit_migrations.py`, and startup verification tooling under `scripts/`. These are audit helpers, not production orchestration.

The executed reset command was `./scripts/reset-dev.ps1 -Environment development -Apply`, after a dry-run and verified backup/restore preflight. Default without `-Apply` is read-only. The Python guard refuses remote Docker, unrecognized database, nondevelopment environment markers, running application containers, unbacked-up resources, table/schema drift, changed record/file sets, nonempty unknown queue state, and backup hash mismatch. It never sources `.env` as executable shell code.

For each future reset cycle: stop only the identified local applications; refresh read-only inventory; create a new offline backup set with `-Backup`; verify database restore; start only datastores; refresh storage detail; generate and review `-DryRun`; run `-Apply`; run current migrations sequentially; start with the mail-disabled audit override; run startup and after-state validation. `-Verify` on the PowerShell wrapper runs the non-destructive startup checks. A prior manifest is not reusable after new data or container identities change. Refusal on drift is intentional. The legacy `reset_all_databases.sh` remains untouched and must not be used for an unattended reset.

The reset wrapper is a guarded deletion entrypoint plus an explicit verification workflow, not a fully unattended reset of arbitrary future schemas. Kafka topics that gain messages require a new reviewed offset/retention plan. Extending the allowlist, permanent storage changes, reseeding real tenants or migration generation belongs in the next reviewed task. No feature development or bulk architecture migration was performed.

## Acceptance limits

Clean active data is evidenced by counts, exact keys and file hashes. Application startup, migrations and HTTP checks are reported separately; a green TCP probe alone is insufficient. New-empty-PostgreSQL installation, all tenant workflows, paid AI inference, external SMTP delivery, Metabase source connectivity and full warehouse recovery are not implied by reset success. Overall Phase 0 acceptance remains **PARTIAL** wherever these gates fail or remain unverified.
