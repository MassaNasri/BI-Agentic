# P0-B implementation report

## Executive Summary

**P0-B IMPLEMENTATION: PASS.** OPS-001, OPS-002, OPS-006, and OPS-016 are fixed for the current local architecture. Fresh and restored-clone migrations pass, all in-scope drift is reconciled, SurrealDB/Metabase/media recreation behavior is proven, changed persistence paths have restore evidence, all 55 P0-A security tests remain green, and a real disposable two-tenant integration passes. The current Compose stack is running.

**PRE-PRODUCTION OPERATIONAL GATE: OPEN.** Seven external credential rotation groups remain pending manual action. Same-host backups must still be transferred to encrypted off-host storage, and the broader Phase 0 production-readiness findings/P0-C architecture decisions remain open. Those items do not reduce the P0-B implementation result.

## Scope

P0-B hardened persistence, migration integrity, recovery, and startup sequencing without beginning the microservices restructuring. No production resource or original data store was destructively tested. Migration testing used a disposable PostgreSQL 18.3 container/volume and an isolated restore of the verified Phase 0 dump. Metabase used an exact-version working copy while the original H2 copy/container stayed preserved. No unknown Docker volume was removed or attached.

## Baseline

- Branch `main`, starting HEAD `1ca062ca…`; the pre-existing dirty worktree was preserved.
- Baseline Docker inventory: 555 volumes. Evidence classified 21; 534 remain `UNKNOWN` and untouched.
- Phase 0 backup: 37 files, 6,246,565,431 bytes, including a verified PostgreSQL dump and immutable original Metabase H2 copy.
- Metabase H2 baseline: 484 cards, 16 dashboards, 4 collections, 2 users, 2 data sources.
- Historical SurrealDB used the memory engine and was already stopped; its former in-memory data was unrecoverable.
- P0-A baseline: 55 new security tests and 158 existing relevant tests passed; current-state clone migration and live two-tenant integration were open.

## OPS-001 SurrealDB

**STATUS: FIXED**

**Root cause.** Compose mounted `/data` but launched SurrealDB with the memory engine. A container restart or removal therefore discarded all metadata despite the misleading volume.

**Implementation.** SurrealDB remains at the pinned 3.0.1 image digest and now uses `rocksdb:///data/biavora/database` on the explicit `surreal_data` volume. A one-shot root initializer creates and recursively owns the path as UID/GID 65532 before Surreal starts.

The shared ETL client now supplies namespace/database through Surreal request headers rather than prepending `USE` statements. This keeps the single query at result index 0 and was verified through real scoped ETL metadata calls.

**Verification.** Both a disposable pre-Compose drill and the active Compose service completed write → restart → read and write → remove/recreate → read. Native export/import into a new isolated volume returned the exact marker. The active verification marker and isolated resources were removed after evidence capture.

**Remaining risk.** Pre-P0-B memory-only history cannot be recovered. SurrealDB is still shared by multiple ETL clients/credentials; ownership separation belongs to P0-C/R3. Backups are currently same-host.

**Rollback.** Keep the pinned version. Restore the native export into a new RocksDB volume and validate before switching. Returning to memory mode is not an acceptable rollback.

## OPS-002 Metabase

**STATUS: FIXED**

**Root cause.** Metabase v0.58.8.5 used an unmounted H2 database inside a container layer, so replacing the container could lose application metadata.

**Implementation.** The original stopped container is preserved as `metabase-h2-preserved`; the Phase 0 H2 primary-file hash remains unchanged. A separate writable working copy was migrated with the same Metabase version into a dedicated PostgreSQL 18.3 service, database, user, and named `metabase_app_data` volume. The active Metabase image is the exact source version/digest. `MB_ENCRYPTION_SECRET_KEY` is supplied from the ignored environment/secret boundary; startup encrypted stored connection details for the supported exact version.

**Verification.** H2 source and PostgreSQL target counts match: 484 cards, 16 dashboards, 4 collections, 2 users, 2 sources. The Metabase container was recreated and counts persisted. A pre-encryption dump restored with count parity. The encrypted dump restored into an isolated database and exact-version Metabase instance; login, data-source health, and a real ClickHouse `SELECT 1` passed.

**Remaining risk.** The original H2 copy diverges once PostgreSQL receives new writes. It is no longer a safe no-loss rollback after cutover. PostgreSQL backup automation/off-host retention and restricted source grants remain operational/deployment work.

**Rollback.** Before new writes, the preserved H2 copy provides a cutover rollback. After new writes, restore the encrypted PostgreSQL dump or forward-fix; do not blindly reactivate H2. Do not combine a Metabase version upgrade with recovery.

## OPS-006 Media/SQLite/Broker Durability

**STATUS: FIXED**

**Root cause.** Voice media had no explicit current persistence guarantee; Kafka/ZooKeeper active data was tied to anonymous historical volumes; SQLite and temporary upload paths needed explicit durability classifications.

**Implementation.** Voice `/app/media` now uses `voice_service_media`. The Connector/Extractor shared `uploaded-files` volume is retained for in-flight handoff. Kafka/ZooKeeper data, logs, and secrets use five explicit named volumes populated from preserved anonymous sources. No source volume was deleted. Redis/ClickHouse existing named volumes remain. Stateful third-party images are digest pinned.

Seven AI/ETL SQLite configurations are explicitly disposable framework/development state: Phase 0 checked thirteen stopped-container files plus one local file, all integrity `ok` with no tables. They contain no proven business history and were not falsely made durable.

**Verification.** Voice marker content survived container replacement, matched its SHA-256, backed up to tar, and restored/read from an isolated volume. The ETL upload marker survived a real Connector recreation and was removed. Kafka/ZooKeeper named copies booted healthy; 15 business topics were at end offset 0, internal offset state was present, and 5 groups were visible.

**Remaining risk.** Full coordinated Kafka/ZooKeeper, ClickHouse, and Redis recovery drills remain Phase 0 production-readiness follow-ups. ETL uploads need an explicit completed-job retention policy. The five broker volumes created during controlled adoption lack Compose ownership labels on this workstation, so Compose emits a harmless warning even though names and mounts are deterministic.

**Rollback.** Anonymous broker source volumes and Phase 0 archives remain preserved. Restore media/uploads to new volumes and validate content before switching. Never prune unknown volumes.

## OPS-016 Migration Drift

**STATUS: FIXED**

**Root cause.** Voice model state differed from intentional physical indexes/choices; Notification represented foreign-owned tables without migration state; historical initial migrations assumed cross-service Auth FKs; Query’s UUID backfill used a statement-level default that duplicated on a real multi-row PostgreSQL clone. Web/worker startup also raced migrations.

**Implementation.** Voice `0013` and Notification `0002` are deliberate state-only migrations. Query `0003` performs nullable add → per-row UUID backfill → unique/required/default alteration. Query `0001` and Workspace `0001`/`0002` now encode historical scalar cross-domain identifiers so fresh shared-database installs are reproducible. Migrations run serially through `scripts/run-migrations.ps1` or `.sh`; API Gateway, Query web, and Notification expiry startup no longer migrate automatically.

**Verification.** All eight in-scope configurations install on a new empty database, upgrade the restored Phase 0 clone, pass integrity checks, and return no drift. A second serialized run is a no-op. Live configured-database migrations also applied and a second run returned no work.

**Remaining risk.** The current shared database/account and Notification’s intentional foreign-table reads remain architecture findings, not migration drift. They are P0-C inputs.

**Rollback.** Voice/Notification state-only migrations perform no DDL. Query/Visualization new tables can be reversed only before dependent writes; restore is preferred. Reversing the populated unique UUID field is destructive and is not the default rollback.

## P0-A Migration Verification Closure

Query `0002 → 0003 → 0004` and Visualization `zero → 0001` both pass on the restored current-state clone. Clone counts remain unchanged outside intended new tables/columns, all UUIDs are non-null/distinct, and the application smokes pass. This closes the P0-A current-state migration gap without weakening `pg_hba.conf` or using the only source database for first-run testing.

## PostgreSQL Clone Verification

The Phase 0 custom dump was restored into `p0b_clone` inside the isolated `p0b-postgres-harness`. Before migration: 5 users, 3 workspaces, 2 manager databases, 331 reports, 6 dashboard pages, 334 assignments, and 223 notification logs. After migration all counts matched. Query/Visualization target tables were correctly created; no unrelated table was created. The harness container and volume were removed after evidence capture.

## Fresh Install Result

**PASS.** All eight serialized owner configurations migrated a new empty PostgreSQL 18.3 database. Historical migration defects were repaired based on actual model ownership rather than faked tables or `--fake` state.

## Upgrade Clone Result

**PASS.** The restored current-state clone upgraded once, passed constraints/counts, and returned no work on a second complete run.

## Two-Tenant Live Result

**PASS.** `scripts/verify-p0b-two-tenant.ps1` used real local Auth, Workspace, Voice, Visualization, Query, ETL Metadata, SurrealDB, and Metabase/embedding configuration—no owner-service mocks. It proved:

- Tenant A receives 404 for Tenant B’s Voice report; Tenant B receives 200 for its own report.
- Tenant A receives 403 for Tenant B’s visualization; Tenant B receives a valid embed response.
- Tenant A’s workspace scope receives 404 when attempting to mutate Tenant B’s ingestion job; Tenant B’s exact scope succeeds.
- Tenant A receives no Tenant B ETL metadata; Tenant B reads its exact scoped record.

The run exposed and fixed a Voice scoped-`Http404` conversion to 500, then exposed a multi-statement Surreal response-index defect. Final execution passed all assertions. Tagged users, workspaces, reports, ownership, dataset/job, Surreal record, and 8 orphaned test JWT rows were removed; post-cleanup domain counts are zero.

## Security Regression Result

- P0-A security tests: **55 passed, 0 failed**.
- Existing relevant baseline: **158 passed, 0 failed**.
- Broader passing selections: Query 50, Visualization 62, Voice 20 plus 5 subtests, Auth 2, Workspace 4, ETL security 15, ETL input/credential/identifier 71, Connector validation 17.
- New regressions: **0**.

Harness-only failures were kept separate: direct `pytest` without Django setup, a container-only Query test path assumption, an initial Voice run without repository `PYTHONPATH`, and a broad legacy ETL selection containing known stale-contract tests. Correct source-tree/`manage.py` runners pass. The first live-harness run treated a native stderr warning as fatal before assertions; that runner issue was fixed.

## External Rotation Status

All seven groups in `SECRET_ROTATION_CHECKLIST.md` remain **PENDING MANUAL ROTATION**:

1. OpenRouter/API provider key.
2. Bootstrap/admin credential.
3. Internal service credentials.
4. Metabase embedding/API credentials.
5. JWT/Django signing credentials.
6. PostgreSQL credentials.
7. ClickHouse/SurrealDB/BI credentials.

No provider rotation is claimed or fabricated.

## Remaining Blockers

- Pre-production operational gate remains open for all seven external credential rotation groups.
- P0-B artifacts are same-host; encrypted off-host transfer, retention ownership, and restore sampling remain manual requirements.
- No approved production RPO/RTO exists; a timed full recovery exercise is still required.
- Full ClickHouse, Kafka/ZooKeeper, and Redis disaster-recovery drills remain unverified from Phase 0.
- P0-C must address the documented shared PostgreSQL credential/database, foreign-domain Notification reads, multi-owner ClickHouse/SurrealDB access, service/worker topology, and production deployment/readiness controls.
- 534 Docker volumes remain `UNKNOWN`; they are preserved and must not be pruned without independent ownership evidence.

## Exact P0-C Inputs

P0-C should start from, and revalidate rather than re-audit, these exact inputs:

1. `docs/remediation/P0B_IMPLEMENTATION_REPORT.md`, `P0B_MIGRATION_MATRIX.md`, `P0B_PERSISTENCE_MATRIX.md`, `P0B_RECOVERY_RUNBOOK.md`, `P0B_BACKUP_MANIFEST.json`, `P0B_VERIFICATION_RESULTS.md`, `P0B_UNKNOWN_VOLUME_REGISTER.md`, and the before/after Git snapshots.
2. The current `docker-compose.yml` topology: persistent pinned Surreal/Metabase/media/broker stores, serialized migrations, 26 running long-lived services, one successful Surreal init job, and one preserved historical Voice-worker orphan.
3. `docs/audit/CURRENT_ARCHITECTURE.md`, `DATABASE_OWNERSHIP_MATRIX.md`, `SERVICE_COMMUNICATION_MATRIX.md`, `TARGET_MICROSERVICES_ARCHITECTURE.md`, and `MICROSERVICES_RESTRUCTURING_PLAN.md` as the architecture decision baseline.
4. Carry-forward violations: shared `bi_voice_agent` PostgreSQL role/database, Notification foreign-domain reads, multi-owner ClickHouse and Surreal access, ETL/Kafka/shared-file business paths, report/voice duplication, service health semantics, and production edge/process/runtime controls.
5. Preservation invariants: do not destroy the Phase 0/P0-B backups, original H2 rollback evidence, anonymous broker source volumes, or the 534 unknown volumes; do not regress the 55/158 security baseline or the live two-tenant pass.
6. Operational gates kept separate from architecture implementation: seven provider/admin credential rotations, encrypted off-host backup copies, approved RPO/RTO, and full ClickHouse/broker/Redis DR exercises.

P0-C and the microservices restructuring were not started.
