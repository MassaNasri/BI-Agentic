# P0-B modification ledger

This ledger records P0-B-owned changes only. The repository began with 369 short-status entries (209 tracked changes, 160 untracked paths, one staged entry, and 208 worktree changes). Existing user/P0-A work was preserved; Git history was not rewritten and no commit was created.

## Configuration and startup

| File | Action | P0-B purpose |
| --- | --- | --- |
| `.env.example` | Modified in worktree (Git currently sees the whole P0-A-era file as untracked) | Document dedicated Metabase application DB password/key and internal URL |
| `.env` | Modified locally, ignored | Generate missing local-only Metabase DB/encryption and ETL runtime values without printing them |
| `docker-compose.yml` | Modified | Persistent Surreal RocksDB/init, dedicated Metabase PostgreSQL, Voice/Kafka/ZooKeeper named volumes, digest pins, Metabase dependencies/internal URLs, and removal of automatic expiry-worker migration |
| `services/api-gateway/Dockerfile` | Modified | Remove web-start migration execution |
| `services/query-service/Dockerfile` | Modified | Remove web-start migration execution |
| `scripts/run-migrations.ps1` | Created | Serialized reviewed migration runner for Windows |
| `scripts/run-migrations.sh` | Created | Serialized reviewed migration runner for POSIX environments |
| `scripts/start-microservices.ps1` | Created in the current dirty worktree / modified for P0-B | Build, run serialized migrations once, then start services |
| `scripts/start_project.sh` | Modified | Build, run serialized migrations once, then start services |
| `scripts/verify-p0b-two-tenant.ps1` | Created | Real disposable local two-tenant verification with exact cleanup |

## Migration integrity

| File | Action | P0-B purpose |
| --- | --- | --- |
| `services/query-service/database/migrations/0001_initial.py` | Modified | Represent external manager identity as a scalar; remove invalid Auth migration dependency |
| `services/query-service/database/migrations/0003_database_ingestion_job_id.py` | Modified in worktree (Git sees P0-A file as untracked) | Per-row UUID backfill safe for real multi-row PostgreSQL clones |
| `services/workspace-service/workspace/migrations/0001_initial.py` | Modified | Represent external owner/user IDs as scalars; remove invalid Auth dependency |
| `services/workspace-service/workspace/migrations/0002_alter_workspacemember_unique_together_and_more.py` | Modified | Preserve scalar external user state in historical graph |
| `services/voice-service/voice_reports/models.py` | Modified | Match intentional existing index names so model state and physical DB agree |
| `services/voice-service/voice_reports/migrations/0013_reconcile_chart_type_state.py` | Created | State-only chart choices reconciliation without DDL |
| `services/notification-service/notification/migrations/0002_unmanaged_foreign_model_state.py` | Created | State-only `managed=False` reconciliation for five foreign-owned models |

## Live verification fixes

| File | Action | P0-B purpose |
| --- | --- | --- |
| `services/voice-service/voice_reports/views.py` | Modified (narrow P0-B branch within a pre-existing large dirty diff) | Return non-disclosing 404 for a scoped report miss instead of converting `Http404` to 500 |
| `etl-final/shared/utils/surreal_client.py` | Modified | Send namespace/database as request context and keep the actual query at result index 0 |

## Evidence and operations

| File | Action | P0-B purpose |
| --- | --- | --- |
| `docs/remediation/P0B_BASELINE.md` | Created | Starting Git/runtime/data constraints and preservation boundary |
| `docs/remediation/P0B_GIT_STATUS_BEFORE.txt` | Created | Exact pre-change short status snapshot |
| `docs/remediation/P0B_UNKNOWN_VOLUME_REGISTER.md` | Created | Evidence-only classification of all 555 baseline volumes; 534 remain unknown |
| `docs/remediation/P0B_IMPLEMENTATION_REPORT.md` | Created | Issue-by-issue result, risks, rollback, tests, and blockers |
| `docs/remediation/P0B_MIGRATION_MATRIX.md` | Created | Fresh/clone/drift/smoke matrix and data integrity results |
| `docs/remediation/P0B_PERSISTENCE_MATRIX.md` | Created | Current store durability, recreation, backup, restore, and SQLite classifications |
| `docs/remediation/P0B_RECOVERY_RUNBOOK.md` | Created | Current-architecture recovery order and safe restore/cutover rules |
| `docs/remediation/P0B_BACKUP_MANIFEST.json` | Created | Credential-free artifact metadata, hashes, sizes, versions, restore status |
| `docs/remediation/P0B_VERIFICATION_RESULTS.md` | Created | Commands, exact results, classifications, and cleanup evidence |
| `docs/remediation/P0B_MODIFICATION_LEDGER.md` | Created | This file |
| `docs/remediation/P0B_GIT_STATUS_AFTER.txt` | Created at finalization | Exact post-change short status snapshot |

## Backup artifacts (ignored by Git)

| Path | Action | Purpose |
| --- | --- | --- |
| `backups/p0b-20260930T131800Z/metabase_app.dump` | Created | Pre-encryption Metabase PostgreSQL recovery point |
| `backups/p0b-20260930T131800Z/metabase_app_encrypted.dump` | Created | Active encrypted Metabase PostgreSQL recovery point |
| `backups/p0b-20260930T131800Z/metabase-h2-working/` | Created | Writable H2 migration working copy; not the immutable rollback source |
| `backups/p0b-20260930T131800Z/media/voice_media.tar` | Created | Voice media restore artifact |
| `backups/p0b-20260930T131800Z/surreal/p0b-compose-surreal-export.surql` | Created | Active Compose Surreal native export |
| `backups/p0b-20260930T131800Z/surreal/p0b-surreal-export.surql` | Created | Preliminary isolated Surreal drill export |

## Runtime state changes

- Created active named volumes: `metabase_app_data`, `surreal_data`, `voice_service_media`, `kafka_data`, `kafka_secrets`, `zookeeper_data`, `zookeeper_logs`, and `zookeeper_secrets` under the Compose project naming convention.
- Copied Kafka/ZooKeeper state from five known anonymous sources into named targets; source volumes remain untouched.
- Preserved and renamed the original stopped Metabase container to `metabase-h2-preserved`; active `metabase` now uses PostgreSQL.
- Built current application images and left the 26 current long-running Compose services running; the Surreal init one-shot exited 0.
- Removed only the named disposable P0-B harness containers/volumes listed in `P0B_VERIFICATION_RESULTS.md` and the exact tagged live-test fixtures.
- Left the historical stopped `voice-service-worker`, all original backup files, anonymous broker source volumes, and all unknown volumes untouched.

## Deletions

No repository file was deleted by P0-B. No original datastore, original backup, historical container, known source volume, or unknown volume was deleted. Disposable markers, test records/tokens, and isolated harness resources were intentionally removed after evidence capture; they were created by P0-B and were not recovery sources.
