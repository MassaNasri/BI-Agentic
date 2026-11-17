# Foundation-D / D5-R4A — Snapshot Boundary and Reconciliation Closure

## Executive Status

**D5-R4A READY FOR D5-R4B. Foundation-D remains PARTIAL; G-D remains OPEN; production readiness remains NO-GO.** The deterministic empty-snapshot overlap, concurrent source mutation, typed comparison, five-chunk 2,500-row comparison, above-10,000-row rejection, compatible nullable ADD, and incompatible schema reseed/cutover all passed in the isolated local stack. This is the D5-R4A gate only. D6 was not started.

## Entry State

Branch `foundation-c-staging`; HEAD `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`. Before editing, 31 tracked paths were modified, the cached diff was empty, Foundation-D artifacts were untracked, and the TimesFM submodule showed dirty. Reports 50–59 and prior work were retained. There was no reset, clean, stage, commit, or push, and TimesFM was not traversed or edited. Historical failed overlap attempts in reports 58 and 59 remain failed attempts.

## Why Kafka STARTED Was Not a Valid Test Synchronization Barrier

Report 59 measured an empty scan completing before Kafka delivered its STARTED notification. Debezium's source lifecycle timestamp and Kafka receipt timestamp refer to different moments. The acceptance harness therefore synchronized on a PostgreSQL advisory wait by the actual snapshot SELECT. The notification still proves lifecycle, but its asynchronous receipt does not open the transaction window.

## Debezium 3.4 Fixture Mechanism

Debezium 3.4 supports table-specific `snapshot.select.statement.overrides`; the override affects the snapshot SELECT for that table, while subsequent changes continue through logical streaming. `snapshot.query.mode` and a custom `SnapshotQuery` were reviewed but were unnecessary. The fixture kept the configured notification channel and used exact candidate notification history for STARTED, TABLE_SCAN_COMPLETED, and COMPLETED. See the [Debezium PostgreSQL connector reference](https://debezium.io/documentation/reference/3.4/connectors/postgresql.html) and [notification reference](https://debezium.io/documentation/reference/3.4/configuration/notification.html).

## Test-Only Snapshot Gate

The isolated fixture creates `public.biavora_d5_r4a_snapshot_orders(bigint)` as a `SECURITY INVOKER` function returning `SETOF public.orders`. It acquires `pg_advisory_xact_lock` and then returns `SELECT * FROM public.orders` without a predicate or projected-column change. The harness holds the matching session advisory lock before candidate creation. The snapshot backend waits on `Lock/advisory`; normal table INSERT is not locked by the fixture. The overridden SELECT is a fixed server-built string containing only the server-derived candidate token's integer lock key. The first fresh attempt failed on transient Connect availability and is retained at `../biavora-foundation-d-validation/d5-r4a-overlap-ad8beac7.json`; the harness was corrected to retain the lock through transient Connect errors. The second fresh attempt passed at `../biavora-foundation-d-validation/d5-r4a-overlap-250f5545.json`.

## Production Safety of the Gate

`CDC_D5_R4A_GATE_SCOPE_TOKEN` is accepted only with `APP_ENV=test`, the exact server-derived generation-2 `public.orders` scope, fixture host `postgres`, and a `source_d2_` database. Any nonempty gate token outside that boundary raises `CDC_FIXTURE_GATE_FORBIDDEN`; ordinary configuration has no snapshot override. The public enable and reseed endpoints reject arbitrary connector properties and snapshot SQL with HTTP 400. Production configuration remains unchanged. Tests compare all non-override fields of gated and ordinary configuration and verify wrong scope, host, and production fail closed. The additional reconciliation pause is similarly scoped to `APP_ENV=test`, exact generation 2, and the fixture host/database; it was disabled after the mutation run.

## Candidate Capture Readiness

The overlap candidate was generation 2 of pipeline `860d784d-2133-4f67-b02f-479228be588e`, scope token `b3bb0b369b6526d4b0ab0fb4c4d8c90a38de922c`, source `source_d2_f59056d0`. At the gate the connector and task were RUNNING, and the exact logical `pgoutput` slot existed in that database with `restart_lsn=0/32A18308`, `confirmed_flush_lsn=0/32A18340`, `wal_status=reserved`. The gate backend PID 44812 began its SELECT at 16:14:35.165868 UTC and was observed waiting on `Lock/advisory` at 16:14:35.427 UTC. **The slot was `active=false` during the gated snapshot scan**: Debezium had reserved the valid slot but had not yet opened streaming replication. Slot activity and persisted `capture_ready=true` were observed after snapshot completion and WAL continuation, by the 16:14:52 candidate/Loader check. The fixture records no exact slot-creation or first-active timestamp, so those are bounded observations rather than invented instants.

## Deterministic Empty-Snapshot Overlap

Generation 1 authorized Query was empty at 16:11:02.923 UTC. The fixture lock was held at 16:11:47.828, generation 2 was created at 16:11:48.083, and the snapshot SELECT reached the advisory gate at 16:14:35.427. Transaction T began at 16:14:35.458 and inserted ID 1 at 16:14:35.462 without committing. Another ordinary source transaction saw zero rows. The gate was released at 16:14:35.503. The exact candidate emitted TABLE_SCAN_COMPLETED with `empty=true` and COMPLETED. T committed only after completion was observed, at 16:14:46.650. No synthetic row, manual offset/LSN change, or resnapshot was used.

## Transaction Timeline

All wall times below are UTC. Notification source and Kafka receipt times are shown separately; the wall-time observation of COMPLETED was 16:14:46.513.

| Event | Timestamp or position |
| --- | --- |
| Candidate created | 16:11:48.083 |
| Snapshot gate reached | 16:14:35.427; backend PID 44812, `Lock/advisory` |
| STARTED source / Kafka receipt | 16:14:34.925 / 16:14:35.777 |
| T BEGIN / uncommitted INSERT | 16:14:35.458 / 16:14:35.462 |
| Gate released | 16:14:35.503 |
| TABLE_SCAN_COMPLETED source / Kafka receipt | 16:14:35.507 / 16:14:36.286; empty |
| COMPLETED source / Kafka receipt | 16:14:35.510 / 16:14:36.650 |
| T COMMIT | 16:14:46.650 |
| Candidate current view / Loader exact | 16:14:52.264 |
| Raw / normalized / transformed observed | 16:14:52.394 / 16:14:52.521 / 16:14:52.655 |
| Fresh MATCH certificate | 16:22:38.916; source and Loader watermark 855795808 |
| Authorized Query verified | 16:23:39.736 |

## WAL Continuation

The raw topic held one business create record (`op=c`, offset 0) after T committed. Normalized and transformed topics each held one INSERT at offset 0 with the same event ID `ab70c89a07d3a5ffd8e969781f539b19182202a99335dbaf62f897b6b1d960a5`. The Loader and candidate current view contained the exact one row. The active slot and capture-ready state followed the snapshot; no snapshot business record was substituted for the WAL INSERT.

## Overlap Reconciliation Certificate

The first real MATCH at 16:16:40.753 had source/Loader LSN 851276872, count 1/1. Its 60-second prebind validity elapsed before cutover; the attempted cutover correctly returned `CDC_RECONCILIATION_CERTIFICATE_REQUIRED`. A fresh attempt `30290454-84eb-4819-b4c8-27ac7de8088d` issued a real `watermark_reconciliation.v1` MATCH at 16:22:38.916 with source/Loader LSN 855795808 and source/Query count 1/1. The accepted cutover used that fresh certificate.

## Authorized Query Exactly-Once Result

After cutover, authorized Query bound generation 2 and returned exactly ID 1 once, with the expected business values. Lineage was `(1, SUPERSEDED), (2, ACTIVE)`. The result was verified at 16:23:39.736 UTC. Evidence is the overlap JSON cited above.

## Concurrent Source-Mutation Rule

A candidate attempt establishes a repeatable-read source snapshot, hashes the source in 500-row chunks, emits a transactional logical marker, waits for capture and each stage's durable end offset, and compares through Query's authorized candidate executor. D5-R4A adds a fresh repeatable-read source read after candidate comparison. A changed count or digest fails the attempt with persisted `CDC_RECONCILIATION_SOURCE_MOVED`; it issues no MATCH and requires explicit resume plus a new request. The issuer also requires the durable checkpoint at issuance to equal the checkpoint sampled for the proof; movement fails with `CDC_RECONCILIATION_CHECKPOINT_MOVED`. Prebind cutover checks certificate age, scope/schema, and unchanged checkpoint. Commits after the final source observation are treated as streaming beyond the certified prefix; if a stage checkpoint advances before binding, the certificate is invalidated. This policy does not freeze customer writes and does not claim that every later source commit is part of the older certificate.

## Concurrent-Mutation Live Result

On the typed candidate, reconciliation snapshot attempt `459648e9-cdad-4123-9f7b-eb91031c15bd` was held at an explicit test advisory gate after source snapshot establishment. The backend waited on `Lock/advisory` at 17:07:34.305 UTC; an `exact_amount` UPDATE committed at 17:07:34.343 while blocked. The gate was released at 17:07:34.344. The first attempt persisted FAILED with `CDC_RECONCILIATION_SOURCE_MOVED`, source LSN 920757032, and no new MATCH. An initial retry exposed a candidate resume transition bug; a durable Loader checkpoint now permits the controller to restore STREAMING from PROVISIONING after explicit resume. Retry attempt `4a64475e-41bb-49b5-87cc-330c6ecef90a` issued MATCH at source/Loader LSN 951739656 for 2/2 rows. **False MATCH observed: NO.** Evidence: `../biavora-foundation-d-validation/d5-r4a-mutation-86007c84.json`.

## Typed Reconciliation

A fresh `typed_orders` source and generation-2 candidate used composite `(tenant_id integer, order_id bigint)` primary key and two rows. The contract included `smallint`, signed and >2^53 `bigint`, `numeric(30,10)`, boolean, varchar/text, UUID, Date, timestamp, timestamptz, nullable text, JSONB with nested Unicode and `0.12345678901234567890123456789`. PostgreSQL JSON/JSONB decoding now uses `Decimal` for fractional values, avoiding binary-float loss. Debezium, ChangeEnvelope, Transformer, Loader, candidate view, authorized Query digest, and `watermark_reconciliation.v1` produced MATCH: attempt `1c80a9b3-a2d7-4416-9f5b-4683c13f641d`, source/Query 2/2, one chunk, source/Loader LSN 874578144, total proof 6485 ms, Query comparison 387 ms. The first API request returned a transient 409 before capture readiness; the accepted subsequent request and MATCH are separately retained at `../biavora-foundation-d-validation/d5-r4a-typed-38fa8f05.json` and `../biavora-foundation-d-validation/d5-r4a-typed-match-4b49cf41.json`.

## Near-Limit Reconciliation

A disposable 2,500-row source loaded into a generation-2 candidate. The first generation-1 wait timed out while Loader was still at offset 1050; it later completed at offset 2499. The first candidate certificate was MISMATCH despite equal 2,500-row counts because Query's `toString(id) AS id` shadowed the numeric PK in `ORDER BY id`, causing lexical ordering. All five chunks differed; this failure remains at `../biavora-foundation-d-validation/d5-r4a-bounded-resume-d4c48577.json`. Query now casts to distinct `__cdc_value_*` aliases and orders by the original numeric PK. A direct first-page comparison then produced identical 500-row SHA-256 digests. Fresh attempt `c8b52df2-126c-4574-bc0d-688e694f1135` returned MATCH with 2,500 source and Query rows, five 500-row chunks, no mismatches, source/Loader LSN 981048224, total proof 11,200 ms, Query comparison 4,786 ms, and 42.36 seconds request-to-observed-certificate including controller scheduling. Evidence: `../biavora-foundation-d-validation/d5-r4a-bounded-retry-e3140ada.json`. The implementation uses a named source cursor and 500-row pages.

A supplemental read-only benchmark on the same retained source and candidate's first 2,500 IDs measured source fetch 116.135 ms, source digest 640.942 ms, direct candidate page reads 1,116.569 ms, and candidate digest 722.564 ms, with five equal chunk hashes. Python `tracemalloc` peak was 324,113 bytes after source paging and 482,624 bytes after candidate paging. The direct physical candidate benchmark is not the internal authorized Query executor; its 4,786 ms comparison time above comes from the real MATCH certificate. The sub-times and Python memory are supplementary measurements, not metrics embedded in that earlier certificate. Evidence: `../biavora-foundation-d-validation/d5-r4a-near-limit-page-benchmark.json`.

## Above-Limit Failure

The same disposable source was extended to 10,001 committed rows after its 2,500-row MATCH. A new attempt `36f5d3f6-63a3-45d7-a750-040066de20a7` persisted FAILED with `CDC_RECONCILIATION_LIMIT`, source LSN 0, and no partial certificate. Generation 2 remained CANDIDATE; authorized Query remained bound to generation 1. The cap was not increased. Evidence: `../biavora-foundation-d-validation/d5-r4a-above-limit-52bac0ec.json`.

## Compatible ADD

The overlap fixture's active generation 2 was quiesced and paused, then `public.orders.note text NULL` was added. The controller inspected the trusted catalog, advanced schema version to 2, and updated D4 storage on resume without reseeding. A new row with `note='nullable-value'` passed CDC. Authorized Query showed old row `note=NULL` and new row with that value. After correcting active generation routing (generation number alone had incorrectly selected the candidate issuer), same-generation bounded reconciliation returned MATCH, source/destination 2/2, and generation 2 remained active. The initial reconcile 409 and eventual PASS are retained in `../biavora-foundation-d-validation/d5-r4a-schema-add-b3bb0b36.json`.

## Incompatible Schema Reseed

A separate disposable source changed `amount numeric(20,4)` to `numeric(22,4)`. Generation 1 persisted `CDC_SCHEMA_INCOMPATIBLE`, `RESEED_REQUIRED`, desired PAUSED; its retained Query result still returned the original row. Explicit authorized `schema_incompatible` reseed created generation 2 with the new catalog. Fresh snapshot/WAL and D4 current state reached exact one-row equality. A real MATCH certificate used the new `numeric(22,4)` column contract. An expired certificate correctly blocked an initial cutover; a fresh certificate and immediately chained cutover succeeded. Authorized Query returned the row, and lineage became `(1, SUPERSEDED), (2, ACTIVE)`. Evidence: `../biavora-foundation-d-validation/d5-r4a-schema-incompatible-d7c07c4e.json`.

## Preserved Lost-Slot Evidence

Report 59's controlled lost-slot fault and explicit generation-3 recovery remain a historical isolated PASS. Evidence `../biavora-foundation-d-validation/d5-r3-lost-slot-0b97b02c.json` was not rerun or rewritten. D5-R4A did not change slot continuity classification.

## Preserved Kafka-Retention Evidence

Report 59's controlled raw-topic retention gap and explicit generation-4 recovery remain a historical isolated PASS. Evidence `../biavora-foundation-d-validation/d5-r3-retention-gap-fc29923f.json` was not rerun or rewritten. D5-R4A did not change the retention-loss classifier.

## Regression Results

Final focused Query suite: **57 passed, 0 failed** across CDC lifecycle, physical binding, Query guard, and public boundary. Final focused ETL suite: **108 passed, 0 failed** across capture preflight, reconciliation, offsets, processing, ClickHouse current state, and contract. An intermediate Query suite had one test setup error from the single-active-generation uniqueness constraint; the test was corrected. A later intermediate suite found the new checkpoint-movement test reached the existing generic validation first; the issuer now returns the specific movement code, and the final 57-test suite passed. `makemigrations --check --dry-run` reported no changes. `compileall` and `git diff --check` passed; Git emitted only existing LF/CRLF conversion warnings. No focused test was skipped.

## Security Results

The fixed snapshot SELECT cannot be supplied by a public caller. The public enable and reseed negative tests passed; production, wrong host, wrong generation/scope, and ordinary connector configuration checks passed. The gate function has invoker privileges and returns the whole selected table, without a row filter or alternate columns. The reconciliation gate requires the same isolated test boundary and was removed from the running controller environment after the live test. No credentials or row payloads were stored in reconciliation attempt state. Production remains under the pre-existing uncertified transport gate.

## Files Modified

This pass changed `etl-final/shared/cdc/connect.py`, `postgres.py`, `reconciliation.py`, and `worker.py`; `docker-compose.cdc-local.yml`; `services/query-service/database/cdc_reconciliation.py`; `services/query-service/integration/cdc.py`, `cdc_reseed.py`, and `test_cdc.py`; `etl-final/tests/test_cdc_capture_preflight.py`; and added disposable D5-R4A scripts `verify_foundation_d5_r4a.py`, `verify_foundation_d5_r4a_remaining.py`, `verify_foundation_d5_r4a_mutation.py`, `verify_foundation_d5_r4a_schema.py`, `verify_foundation_d5_r4a_diagnose.py`, and `verify_foundation_d5_r4a_benchmark.py`. This report is new. Reports 50–59 were not modified.

## Remaining D5 Gates

D5-R4A closes the requested snapshot, movement, typed, bound, and schema gates. Report 59's broader D5 exit list still includes provisioning-phase credential/retirement races, the full restart matrix, reconciliation restart at watermark, multi-controller late external-effect convergence, and live orphan classification. Those belong to D5-R4B or later scoped D5 work. Foundation-D is not accepted wholesale by this report.

## D5-R4A Exit Decision

**READY FOR D5-R4B.** Every live D5-R4A exit gate passed in the isolated fixture. The slot was valid but inactive at the blocked snapshot SELECT; its first-active instant was not captured. The separate timing/memory benchmark supplements the earlier certified reconciliation, rather than modifying its historical metrics. D6 remains unopened.
