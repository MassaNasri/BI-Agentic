# P0-B recovery runbook

This runbook restores the current P0-B architecture. It does not design or begin the future R3/P0-C service split.

## Safety rules

1. Declare an incident owner and maintenance window. Record UTC start time, suspected failure time, last known-good backup, and expected data-loss window.
2. Never restore over the only copy. Restore to new databases/volumes and validate first.
3. Never run `docker volume prune`, attach an unknown volume, or delete the original H2 container/Phase 0 backup.
4. Keep secrets in an operator-owned secret store or temporary restricted environment file. Do not paste credentials into commands, tickets, logs, or this repository.
5. Stop writers before taking a coordinated snapshot or switching restored stores. A filesystem copy of a live database is not a valid backup unless the engine explicitly supports it.
6. Copy each completed backup, manifest, and checksum to encrypted off-host storage. The repository-local artifacts are same-host evidence only.

## Current recovery order

1. Preserve host/container/volume inventory and current logs read-only.
2. Stop ingress and writers.
3. Restore the shared application PostgreSQL database to an isolated logical database.
4. Restore ClickHouse if warehouse loss is in scope; its full Phase 0 restore drill remains pending.
5. Restore Kafka and ZooKeeper as one compatible broker set if event/offset loss is in scope; do not mix arbitrary data and coordination snapshots.
6. Restore SurrealDB metadata to a new RocksDB volume.
7. Restore Metabase application PostgreSQL to a new database/volume.
8. Restore `voice_service_media` and `uploaded-files` to new named volumes.
9. Restore Redis only if non-reconstructable queue/lock state has been explicitly identified; otherwise start clean under an incident decision.
10. Start infrastructure, run reviewed serialized migrations once, start owner services, then gateway/ingress.
11. Validate counts, constraints, source connectivity, authorization denials, worker progress, and application behavior before reopening traffic.

## 1. Stop writers

From the repository root, record state first:

```powershell
docker compose ps -a
docker volume ls
Get-FileHash -Algorithm SHA256 backups\p0b-20260930T131800Z\* -ErrorAction SilentlyContinue
```

Stop ingress and application writers while keeping data engines available for engine-native backups:

```powershell
docker compose stop api-gateway notification-expiry-worker notification-service voice-service report-service visualization-service query-service subscription-service workspace-service auth-service ai-service etl-connector etl-detector etl-extractor etl-transformer etl-loader etl-metadata
```

If the incident may involve broker or database corruption, stop the affected engine after its supported backup/export is complete. Do not use `docker compose down -v`.

## 2. Verify artifacts before restore

Compare every candidate artifact to `P0B_BACKUP_MANIFEST.json`:

```powershell
Get-FileHash -Algorithm SHA256 backups\phase0-20260913T141937Z\bi_voice_agent.dump
Get-FileHash -Algorithm SHA256 backups\phase0-20260913T141937Z\metabase.db\metabase.db.mv.db
Get-FileHash -Algorithm SHA256 backups\p0b-20260930T131800Z\metabase_app_encrypted.dump
Get-FileHash -Algorithm SHA256 backups\p0b-20260930T131800Z\media\voice_media.tar
Get-FileHash -Algorithm SHA256 backups\p0b-20260930T131800Z\surreal\p0b-compose-surreal-export.surql
```

Mismatch means **STOP**: quarantine the artifact and choose another verified copy.

## 3. Application PostgreSQL

Use PostgreSQL 18.3-compatible tools. Create a new logical database or isolated container; never overwrite `bi_voice_agent` during the first restore. Supply credentials through the process environment, not command arguments.

```powershell
createdb --host 127.0.0.1 --port 5432 --username bi_admin bi_voice_agent_recovery
pg_restore --host 127.0.0.1 --port 5432 --username bi_admin --dbname bi_voice_agent_recovery --exit-on-error --no-owner backups\phase0-20260913T141937Z\bi_voice_agent.dump
```

Point disposable service runs at `bi_voice_agent_recovery`, run `scripts/run-migrations.ps1`, then run the migration and service checks in `P0B_VERIFICATION_RESULTS.md`. Validate all pre-restore table counts, new UUID null/duplicate counts, expected indexes, and migration heads before a connection-string switch. A rollback after write traffic resumes is a database restore/forward-fix decision; reversing the Query UUID migration would discard data and is not the default rollback.

## 4. SurrealDB

The active version is pinned to SurrealDB 3.0.1 and stores RocksDB data at `/data/biavora/database`. Restore to a new named volume and validate it in an isolated container/network. Use the credentials from a restricted environment source.

```powershell
docker volume create biavora_surreal_recovery
docker run --rm -v biavora_surreal_recovery:/data --entrypoint /bin/sh postgres@sha256:7e32e9833a6fb1c92c32552794cb6ed569d51b445a54907d35fc112ef39684db -c "install -d -o 65532 -g 65532 -m 0700 /data/biavora"
docker run -d --name biavora-surreal-recovery -p 127.0.0.1:18008:8000 -v biavora_surreal_recovery:/data surrealdb/surrealdb@sha256:849c9ad548415ddf06b80d834929ddc43fb9c482d2ef9b51113641a8e47fad63 start --user '<from-secret-store>' --pass '<from-secret-store>' rocksdb:///data/biavora/database
docker cp backups\p0b-20260930T131800Z\surreal\p0b-compose-surreal-export.surql biavora-surreal-recovery:/tmp/restore.surql
docker exec biavora-surreal-recovery /surreal import --endpoint http://127.0.0.1:8000 --namespace bi_etl --database etl_logs --username '<from-secret-store>' --password '<from-secret-store>' /tmp/restore.surql
```

Replace the literal placeholders at execution time without committing the resulting command transcript. Read expected record counts/marker IDs, stop the isolated instance, and switch the Compose volume through a reviewed override/change. Importing twice into a non-empty target may legitimately fail on duplicate record IDs; restore into an empty target. The pre-P0-B memory-only Surreal state is unrecoverable and cannot be part of any RPO claim.

## 5. Metabase application database

The active application version must remain v0.58.8.5 while restoring/migrating. Restore the encrypted PostgreSQL dump to a new empty database, set the same encryption key through the secret store, and start an isolated exact-version Metabase instance with schedulers/outbound actions disabled.

```powershell
createdb --host '<recovery-postgres>' --username metabase_app metabase_app_recovery
pg_restore --host '<recovery-postgres>' --username metabase_app --dbname metabase_app_recovery --exit-on-error --no-owner backups\p0b-20260930T131800Z\metabase_app_encrypted.dump
```

Required gates before switching:

- 484 cards, 16 dashboards, 4 collections, 2 users, and 2 data sources;
- `/api/health` returns healthy;
- a real Metabase login succeeds with the recovery secret configuration;
- data source 2 health succeeds and a bounded ClickHouse `SELECT 1` executes;
- application DB details remain encrypted at rest.

The stopped `metabase-h2-preserved` container and Phase 0 H2 files are a pre-cutover rollback boundary only. After new writes land in PostgreSQL, blindly switching back to H2 loses those writes. At that point, prefer the encrypted PostgreSQL backup or a forward fix. Do not upgrade Metabase during recovery.

## 6. Media and ETL upload handoff

Restore to new empty named volumes:

```powershell
docker volume create biavora_voice_media_recovery
docker run --rm -v biavora_voice_media_recovery:/restore -v "${PWD}\backups\p0b-20260930T131800Z\media:/backup:ro" postgres@sha256:7e32e9833a6fb1c92c32552794cb6ed569d51b445a54907d35fc112ef39684db sh -c "cd /restore && tar -xf /backup/voice_media.tar"
```

Validate archive checksum, expected safe path layout, file counts and representative hashes without logging tenant content. Mount the recovery volume into an isolated Voice container and exercise the authorized processing/read path. For ETL uploads, restore the Phase 0 `uploaded-files` archive to a new volume and validate both Connector and Extractor access. These files are durable only for in-flight job handoff; retention/cleanup policy must still remove completed temporary uploads.

## 7. Kafka/ZooKeeper, ClickHouse, and Redis

P0-B replaced anonymous Kafka/ZooKeeper mounts with explicit named volumes and successfully booted the copied state: 15 business topics were empty, internal offset partitions were present, and 5 consumer groups were visible. The original anonymous volumes remain preserved. A full coordinated broker restore, ClickHouse restore, and Redis restore were not completed; use their Phase 0 archives only in an isolated same-version drill before production cutover. Never restore ZooKeeper and Kafka from unrelated points in time.

## 8. Start and validate

Start infrastructure first, apply migrations exactly once, then start the application:

```powershell
docker compose up -d metabase-db clickhouse redis zookeeper kafka surrealdb clamav
.\scripts\run-migrations.ps1
docker compose up -d
docker compose ps -a
```

Run the behavior probes and tests listed in `P0B_VERIFICATION_RESULTS.md`. Confirm the one-shot `surrealdb-volume-init` exited 0, every current long-running Compose service is running/healthy, and no web/worker command contains an automatic migration.

## RPO, RTO, retention, and off-host assumptions

- No production RPO or RTO has been approved. Current RPO equals the age of the latest coordinated, verified backup; records after that point may be lost.
- Current RTO is **not established**. The local drills prove recoverability, not a time objective. Measure a full isolated drill and obtain an operational owner before production.
- Keep at least one pre-migration H2 copy, one pre-encryption Metabase PostgreSQL dump, one encrypted current dump, and the Phase 0 PostgreSQL dump until retention approval.
- Off-host encrypted copies with independent access control are required. P0-B created same-host evidence only; off-host transfer and restore sampling remain manual operational gates.
- Record artifact hash, tool/image version, operator, start/end time, count/integrity results, and the exact cutover/rollback decision for every recovery.
