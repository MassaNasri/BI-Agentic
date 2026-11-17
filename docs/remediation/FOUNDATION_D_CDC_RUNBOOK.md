# Foundation-D local CDC runbook

Status: **PARTIAL; production disabled**. Evidence and limitations: [report 50](../../BIAVORA_PRODUCTION_READINESS_AUDIT/50_FOUNDATION_D_POSTGRESQL_CDC_IMPLEMENTATION_REPORT.md). Use only the dedicated `biavora_foundation_d` project. Never point this fixture script at customer databases or delete existing Docker volumes to make a test pass.

## D5 recovery checkpoint (2026-11-07)

The D5-R1 control plane persists generation lineage, fences callbacks by generation/configuration/credential epoch, and grants one database-backed controller lease at a time. A superseded callback receives `CDC_STALE_CALLBACK`; a second controller receives `CDC_CONTROLLER_LEASE_HELD` until the first lease expires. The controller lease is 90 seconds, so restart recovery can wait for expiry. Do not clear lease fields manually. Controlled reseed and recoverable Query cutover are implemented. D5-R2 adds the candidate watermark certificate. D5-R3 adds durable candidate capture and reconciliation attempt state, but the live overlap and fault matrix in report 59 remain open. Production CDC remains disabled.

On `RESEED_REQUIRED`, record the source/pipeline/Dataset IDs, generation, error code, stage checkpoints, slot health, Query binding and safe reconciliation summary. Confirm the connector is stopped and retain its slot, topics, versions table, view, Dataset and audit. Do not call `resume`, alter offsets or rebind Query. An authorized operator may request a new candidate generation through the logical `reseed/` route after reviewing the cause and source schema. A legacy `CDC_STORAGE_INCOMPATIBLE` scope needs a fresh D4 candidate; there is no safe in-place conversion.

The new empty-source path enables Debezium's sink notification topic. Normalizer accepts only this connector's `Initial Snapshot` STARTED, successful zero-row TABLE_SCAN_COMPLETED, then COMPLETED in order; Integration stores the signal with the generation. Query publication still validates the D4 storage and catalog. If no durable completion appears, leave the Dataset pending and inspect the scoped notification topic, Normalizer offset, connector task and bounded error code. If an initial snapshot unexpectedly starts again after completion, the pipeline becomes `RESEED_REQUIRED`. A heartbeat or RUNNING connector is never completion evidence. The live acceptance result and limitations are in report 56.

## Local prerequisites and bootstrap

Docker Desktop/Linux containers, Python with the Query service dependencies plus `clickhouse-connect`, and an external writable fixture directory are required. Ports 18094/18095/18096 bind only to loopback. Compose uses no repository `.env`; supply an explicit external file. The following creation uses exclusive mode and fails if the file already exists. It prints no secret values.

```powershell
@'
from pathlib import Path
import secrets
path = Path('../biavora-foundation-d-validation')
path.mkdir(exist_ok=True)
names = ['CDC_PG_PASSWORD','CDC_CH_PASSWORD','CDC_QUERY_CH_PASSWORD',
         'CDC_SOURCE_PASSWORD','CDC_SOURCE_ROTATED_PASSWORD','CDC_JWT_KEY',
         'CDC_CREDENTIAL_KEY','CDC_CONTROLLER_KEY','CDC_NORMALIZE_KEY',
         'CDC_TRANSFORM_KEY','CDC_LOAD_KEY','CDC_QUERY_KEY','CDC_ETL_KEY','CDC_RESOLVER_KEY']
with (path/'fixture.env').open('x', encoding='utf-8') as output:
    output.write('\n'.join(name+'='+secrets.token_urlsafe(40) for name in names)+'\n')
'@ | python -
```

From the repository, use this prefix for every Compose operation:

```powershell
docker compose --project-name biavora_foundation_d --env-file '..\biavora-foundation-d-validation\fixture.env' -f docker-compose.cdc-local.yml build
docker compose --project-name biavora_foundation_d --env-file '..\biavora-foundation-d-validation\fixture.env' -f docker-compose.cdc-local.yml up -d query connector
```

Query's dependencies apply the real Auth and Workspace migrations before Query's historical data-copy migrations. Then run `scripts/verify_foundation_d_cdc.py --env-file <external-file> --phase bootstrap` with the Query venv. It creates two separate source databases, non-superuser replication roles, exact publications and persisted source/pipeline/dataset scopes, and grants the fixture Query user SELECT on the warehouse. State/results remain next to the external env file. Bootstrap refuses an existing state file.

Start `controller normalizer transformer loader` with the same Compose prefix and `up -d`; this also starts private Connect and its dependencies. Run phase `check` to validate initial snapshot, insert/update/delete, exact Query state, tenant denial and reconciliation. Subsequent phases are `recovery`, `storage_recovery`, `race`, `race_verify`, `lifecycle`, and `broker_recovery`; inspect their source prerequisites before running. `lifecycle` deliberately leaves source A reseed-required and retires B. `broker_recovery` uses the race source after that. Tests mutate only these owned fixtures. A failed phase is not a pass because a later continuation succeeds.

The observed race budget is 300 seconds and broker catch-up budget 120 seconds. Both failed in the recorded run. Do not silently raise these budgets and erase the failures; diagnose and record any revised acceptance decision and new measurements.

## Source preflight

The current preflight accepts PostgreSQL 15-18 with `wal_level=logical`, available slots/WAL senders, a non-superuser replication login, SELECT on the selected ordinary table, a primary key, REPLICA IDENTITY FULL, and an exact precreated publication with all selected columns and no row filter. Unsupported types, RLS/partitioned tables and unconstrained numeric are rejected. FULL identity increases WAL volume; it does not make tables without a primary key supported.

An administrator, not the replication login, provisions the publication after Integration assigns the pipeline. The generation-1 publication and slot identifier is `b_` plus the server-derived scope token. A candidate shares that exact table publication, while its slot, connector, topics and ClickHouse objects use a new generation token. The identifiers are available to the private controller/operator, never a public input. Conceptual administrator SQL:

```sql
ALTER TABLE public.orders REPLICA IDENTITY FULL;
GRANT USAGE ON SCHEMA public TO selected_replication_role;
GRANT SELECT ON public.orders TO selected_replication_role;
CREATE PUBLICATION server_derived_publication FOR TABLE public.orders;
```

Do not copy the conceptual names as real identifiers. No public user supplies a connector name, topic, slot, publication or destination table.

## Lifecycle and credentials

Manager-authenticated routes follow `/database/sources/{source_uuid}/cdc/`: GET status; POST `enable/` with exactly schema/table; POST `pause/`, `resume/`, `reconcile/`, `disable/` with exactly pipeline_id. `CDC_ENABLED=1` is required and production refuses CDC. No HTTP API accepts arbitrary Connect options.

Pause maps to Connect STOP, waits for stopped tasks and retains config, source offsets, slot, publication and warehouse data. Resume uses those positions. Disable/retire retain the same resources; retirement prevents new polling work but does not provide instantaneous cancellation of already in-flight writes. Check the source slot is inactive before maintenance. Public stale capture is DEGRADED; inspect heartbeat age and checkpoints instead of trusting process liveness.

Rotate through the existing Foundation-C credential route. Controller stops the task before replacing the protected FileConfigProvider file and resuming. Do not paste source passwords into Connect JSON, Kafka, shell history or logs. The local test changes the source password and validates activation; real provider-managed rotation and identity revocation are CAP-14 work.

## Schema maintenance and reconciliation

Quiesce writes, request a new reconciliation and require MATCH with a new checked_at timestamp. Confirm private stage offsets reached topic ends, then pause, confirm inactive source slot, apply a nullable ADD and resume. Confirm schema version and new exact reconciliation before treating the source as current. No arbitrary online DDL/replay-across-generation promise exists. DROP/RENAME/type/PK changes require reseed; never edit the error state or offsets to bypass it.

Candidate reconciliation uses a PostgreSQL repeatable-read source snapshot, then emits a source-database logical WAL marker without changing customer rows. It waits for the generation slot to flush through that marker and records Kafka raw, normalized and transformed topic ends only after that flush. Each stage must have a persisted checkpoint through the corresponding end offset. The internal Query comparator reads only the generation's business-only current view through SQLGuard and the bounded Query executor. Source and Query rows are compared in stable primary-key chunks with typed SHA-256 digests. The launch limit is 10,000 rows; larger sources fail closed. Supported reconciliation PK ordering is integer or C-collated text, including composites. Other PK orders fail closed pending proof. A concurrent write beyond the marker can cause a safe mismatch; for deterministic operations, quiesce source writes from the source snapshot through cutover. A match proves the captured prefix at the recorded marker, not cross-database ACID consistency.

## Failure handling

Transient failures retain uncommitted positions and retry. Poison records receive a payload-free scoped DLQ, terminal acknowledgement and pause. Investigate the safe reason code; do not replay arbitrary DLQ content into business topics. Business-topic retention gaps and lost WAL slots require reseed. Never advance a slot, edit Connect offsets, or reset to latest to make lag disappear.

For the observed Kafka delay: first record source value, Query value, Kafka ends/commits, capture heartbeat, Connect task state and bounded error codes. Preserve the timeout evidence. 3.4.3 eventually recovered automatically; 3.3.1 was also recovered by a controlled worker restart. If a task is failed while its slot remains active, stop the controller, restart only this project's Connect container, then resume the controller and verify exact state/reconciliation. This is an operator recovery procedure, not proof that automatic recovery meets the gate.

## D5-R1 candidate reseed and cutover

An authenticated workspace manager with the separate `CDC_RESEED_OPERATOR_KEY` may POST `reseed/` with exactly `pipeline_id`, `intent: "reseed"`, and an allowlisted reason (`legacy_storage`, `schema_incompatible`, `slot_lost`, or `operator_reseed`). POST `abort/` requires exactly `pipeline_id` and `intent: "abort_candidate"` with the same operator key. GET `status/` returns logical generation states and safe repair classifications. Repeating a request returns the same candidate while it remains nonterminal. No public route accepts a generation number, physical resource, offset or force-cutover flag.

The candidate takes the pipeline's new control generation. Old callbacks are fenced; the candidate controller stops the old connector before provisioning its fresh slot and snapshot. The old Query Dataset remains bound to the prior view until cutover, so Query may show a frozen historical state during candidate build. Do not delete or rebind legacy physical objects. Abort stops candidate capture and retains its evidence; the old Query binding stays authoritative.

To certify a candidate, wait for its trusted snapshot completion and D4 current view, then POST `reconcile/` with exactly `pipeline_id`. The authenticated leased controller establishes the source marker and stage proof; Query computes the candidate digests. A `MISMATCH` records bounded chunk identifiers and counts, leaves the old Query binding authoritative, and blocks cutover. Inspect source/catalog/checkpoints and candidate storage without overwriting either side; request reconciliation again after a reviewed correction. A `MATCH` issues `watermark_reconciliation.v1` for the exact generation, Dataset, schema, view, source LSN and Loader offset barrier. Candidate checkpoint or schema changes invalidate a pre-bind certificate; pre-bind certificates expire after 60 seconds. The old `local_exact_v1` remains test/development only and cannot satisfy production semantics. Internal cutover requires a valid certificate and the D5-R1 physical prerequisites. No public force-cutover route exists.

The generation now records an attempt ID, state, source watermark, stage ends, timestamps and safe failure code as reconciliation proceeds. If the controller restarts during a nonterminal attempt, the next owner explicitly fails that attempt with `CDC_RECONCILIATION_INTERRUPTED`; an operator must request a fresh reconciliation and source snapshot. A new request invalidates the old certificate. Never treat a retained MATCH certificate as valid if its attempt ID, schema, checkpoint or 60-second pre-bind window no longer matches.

Candidate `capture_ready` requires a valid active generation slot, running Connect task, initialized source offset and trusted snapshot notification. It is capture evidence, not Query authority. On an empty snapshot, STARTED may arrive at Kafka after TABLE_SCAN_COMPLETED was already produced. The D5-R3 fresh overlap probe in report 59 observed that timing and failed; do not reclassify its later zero-row certificate as an overlap pass. Keep source writes quiescent for reconciliation until the source-mutation gate is proven.

A D5-R3 disposable lost-slot fault did reach `CDC_SLOT_LOST` / `RESEED_REQUIRED`; the removed generation-2 slot was not recreated. Authorized `slot_lost` reseed built generation 3, obtained a fresh real MATCH certificate and cut over while retaining the failed generation's evidence. This validates that one isolated continuity recovery path. Do not remove slots from a live source as a routine test or recovery step.

A D5-R3 disposable Kafka retention fault moved the generation-3 raw topic's retained beginning beyond Normalizer's durable resume position while Normalizer was stopped. Restart produced `CDC_KAFKA_RETENTION_LOST` / `RESEED_REQUIRED` without a checkpoint advance. The old Query binding remained deterministic; authorized reseed built generation 4 from a fresh snapshot, certified it and cut over with the previously missing row exactly once. Never fix a retention gap by seeking to latest or editing checkpoints.

The Integration generation records READY/PENDING/QUERY_BOUND/COMPLETE; Query's Dataset generation stamp and view binding determine analytical authority. A controller's first poll after restart retries PENDING/QUERY_BOUND cutovers. If Query is already bound to the candidate, recovery completes ACTIVE/SUPERSEDED bookkeeping without rebinding backward. If Query remains old and the certificate expired or checkpoints changed, issue a new reconciliation certificate before retrying the compare-and-swap. Inspect `status/` for manual-review findings; never auto-delete orphan resources. `abort/` is repeatable before Query binding and retains the failed candidate's connector, slot, topics, view and audit for reviewed cleanup. Superseded resources remain retained.

Use `scripts/verify_foundation_d5_r1.py --env-file <external-file> --case legacy` to create an isolated actual ReplacingMergeTree scope and exercise generation-2 recovery. `--case crash_restart`, `--case empty`, and `--case concurrent` exercise the other D5-R1 local cases. These create fresh fixture sources and retain all earlier evidence. The local certificate must not be interpreted as final reconciliation or production readiness.

Use `scripts/verify_foundation_d5_r2.py --env-file <external-file> --case legacy`, `--case empty`, and `--case boundary_overlap` for the new isolated watermark paths. `--case retry` resumes only the latest retained candidate after a recoverable local fixture failure; inspect its state first. `--case empty_insert` verifies post-cutover INSERT on the latest empty candidate. These scripts retain JSON evidence next to the external env file. A lost slot or Kafka retention gap must reach `RESEED_REQUIRED`; an operator requests a fresh candidate and must never rewrite offsets or seek to latest. Do not interpret an incomplete fault matrix as D5 closure.

## WAL, storage and shutdown

Watch retained WAL, slot activity, capture age and Kafka retention. The local warning is 256 MiB and slot cap 512 MiB; local Kafka business retention is 24 hours/512 MiB. Paused slots still retain WAL. Production thresholds require capacity evidence and operators. The current-state view hides logical deletes; physical versions/tombstones have no automatic erasure policy.

Use `stop` with the dedicated project prefix to stop the acceptance stack while retaining volumes and evidence. No `down -v`, prune, slot drop or publication drop is part of this runbook's automatic sequence. Slot/publication removal requires explicit authorization after stop confirmation, retained-data/replay assessment and a documented decision that resumability may be abandoned. Never remove another project's resources.

## Production boundary

Local shared Kafka PLAINTEXT, fixture metadata bootstrap grants and loader administration rights are not production identities. Before deployment require broker ACL/TLS, least-privilege warehouse/runtime roles, managed secrets and workload identities, Java DNS/SSRF/TLS reconnect certification, stable egress, real public PostgreSQL, backup/restore and failover, immutable candidate CI, capacity/soak and operator incident/slot-retention ownership under CAP-14. Production remains NO-GO.
