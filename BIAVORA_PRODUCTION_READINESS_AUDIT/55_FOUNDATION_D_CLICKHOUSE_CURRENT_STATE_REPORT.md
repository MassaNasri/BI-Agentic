# BIAVORA Foundation-D / D4: ClickHouse Current-State Correctness

## Executive Status

**D4 READY FOR D5 for newly provisioned D4 storage.** Fresh isolated sources passed current-state, replay, recovery, exact type, and authorized Query checks. The old `ReplacingMergeTree` layout loses prior version identities during merges; the D4 Loader now rejects that layout and requires the D5 controlled reseed/migration path. Foundation-D remains **PARTIAL**, G-D **OPEN**, and Production Readiness **NO-GO**. This report makes no exactly-once transport or production-capacity claim.

## Entry Repository State

Branch `foundation-c-staging`, HEAD `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`. Before D4 edits, 28 tracked files were dirty (268 insertions, 40 deletions), D0-D3 files and reports 50-54 were untracked, the TimesFM submodule was dirty, and the cached diff was empty. All pre-existing work was preserved. Nothing was staged, committed, pushed, reset, or cleaned.

## D4 Scope and Non-Goals

D4 owns the Loader's physical current-state materialization, deterministic replay/conflict behavior, and Query-visible proof. Empty-table completion, generation fencing, safe reseed/cutover, multi-controller epochs, arbitrary schema-history replay, hosted deployment, and final performance/release budgets remain D5/D6 work.

## Files Reviewed

Read reports 50 architecture, 50 implementation, 51, 52, 53, and 54 in the requested order, then the relevant rules in canonical documents 34, 43, 45, 22, 30, 31, 33, and 20. Inspected the CDC contract, schema, worker, ClickHouse adapter, Query Dataset publication, binding resolver, SQL guard/executor, Dataset model, schema/preview endpoints, snapshot loader boundary, tests, and local acceptance harnesses.

## Existing ClickHouse CDC Architecture

At entry, the versions table was `ReplacingMergeTree(_cdc_version) ORDER BY (source PK)` and the current view read `versions FINAL WHERE _cdc_deleted=0`. This selected a tombstone before filtering, so logical latest-state reads worked. Live reverse replay revealed the flaw: background merges erased older version identities, and stale exact deliveries then inserted those versions again. A conflicting old version could no longer be compared with its original identity. D4 changed new tables to an immutable `MergeTree` history ordered by the complete key plus version.

## Versions Table DDL

The fresh simple source used the following effective DDL (scope token shortened here):

```sql
CREATE TABLE etl.cdc_<scope>_versions (
  id Int32, customer String, amount Decimal(20, 4), status String,
  _cdc_version UInt128, _cdc_deleted UInt8,
  _cdc_event_id FixedString(64)
) ENGINE = MergeTree ORDER BY (id, _cdc_version);
```

The typed source's actual sorting key was `id, part, _cdc_version`. The Loader's `cdc_loader` identity creates/writes these objects. Its first apply verifies engine and full sorting key and fails closed with `CDC_STORAGE_INCOMPATIBLE` on the old merge-losing layout.

## Current View Definition

The Loader creates a Query-facing `View` selecting only business columns from an inner `row_number() OVER (PARTITION BY complete_PK ORDER BY _cdc_version DESC)` result, then filters `_cdc_rank=1 AND _cdc_deleted=0`. ClickHouse's actual generated DDL placed the rank and deleted predicates after the inner query. **`FINAL` is not used or required** in D4. Query publication verifies the physical engine, full key, view ranking/delete order, and exact business/technical column schemas before binding.

## Ownership and Query Boundary

Data Platform Loader owns the versions table, current view, and writes. Query owns the logical Dataset binding, workspace authorization, SQL guard, resource limits, executor, and sanitized output. The local Query ClickHouse identity has `SELECT ON etl.*` from fixture bootstrap and uses read-only query settings; it does not mutate CDC data. Public Query allowlists only the derived current view. Tightening the fixture's broad read grant is a D6 least-privilege review item.

## Version Suppression Model

For each full key, the view ranks all retained versions descending, selects one latest row, then applies the delete marker. Older accepted versions remain physically present but cannot replace a newer value or resurrect a deleted row. Ten reverse/duplicate transformed deliveries advanced the Loader input offset while the fresh table stayed at eight physical rows. The store checks existing key/version identity before insertion, so exact replay is physically skipped. One Loader per scope is the D4 operating assumption; D5 owns multi-writer fencing.

## Event-ID Idempotency

An exact same-ID/version/payload replay returns without inserting. Tests reject a changed payload with the same ID, a different ID at the same version, and a changed delete marker. A test-only exact physical duplicate was also inserted directly into the Loader-owned table: physical rows rose 14 to 15, the Loader skipped subsequent exact replay, and the current view still returned one logical key row.

## Equal-Version Conflict Policy

`apply` reads retained identity and business values for the full key and version. Any ID, delete flag, or row mismatch raises `CDC_VERSION_CONFLICT` before warehouse write. A live transformed-topic event changed the row while retaining the source-based version and ID. Loader wrote a bounded scoped `CdcFailure.v1`, committed that poison offset, left 15 physical rows unchanged, and Query reported `PAUSED / RESEED_REQUIRED`. Resume returned 409; authorized Query still matched source truth. `CDC_STORAGE_INCOMPATIBLE` is likewise sticky.

## INSERT Correctness

Fresh three-row snapshot published Dataset 19 only after Loader materialization. A new key 4 insert with amount 100 appeared through authorized Query, with business fields only.

## UPDATE Correctness

Key 4 progressed 100 to 200 to 300 in source and authorized Query. Replays of old versions did not change the current result. A fresh update after Loader restart also caught up without resnapshot.

## DELETE Correctness

Deleting key 4 wrote a physical `_cdc_deleted=1` version and removed the row from the current view and Query. Replaying stale insert/update versions left it absent. The raw Kafka null tombstone did not become another business delete; the D3 transport-only handling remained unchanged. No physical erasure is claimed.

## Delete/Reinsert Correctness

A legitimate newer key 4 insert after its delete became visible with amount 400. Replaying the older insert, updates, and delete twice in reverse order left the newer row current. The typed composite key was likewise deleted, held absent through six reverse deliveries, and later reinserted with a newer source position.

## Multi-Key Correctness

The quiescent simple source ended with key 1 updated, key 2 updated through recovery, key 3 deleted, key 4 reinserted, and key 5 newly inserted. Exact ordered PostgreSQL key/value/null state matched the authenticated Query result for the four current rows. This bounded comparison does not claim cross-key transaction atomicity.

## Composite PK

Fresh typed Dataset 20 used `(id, part UUID)` as its complete primary key and ClickHouse sorting key `id, part, _cdc_version`. Snapshot, update, delete, six reverse duplicate deliveries, and newer reinsert behaved correctly. No component was omitted from the version lookup, ranking, or storage key.

## Exact Type Round Trip

The fresh typed source traversed PostgreSQL, Debezium, ChangeEnvelope.v1, Transformer, ClickHouse, and authenticated Query. Checked `smallint`, `integer`, `bigint`, boolean, text/varchar, UUID, Date, timestamp, timestamptz, nullable text, JSON/JSONB, and bounded `numeric(30,10)`. A fixture's initial explicit `timestamp(6)` spelling was rejected by the existing D3 supported-type contract; changing the fixture to unqualified timestamp types and resuming succeeded. No unsupported type is claimed.

## Decimal Correctness

`12345678901234567890.1234567890` survived source to Query as exact decimal text. The subsequent update and newer reinsert were checked through Query. The warehouse uses `Decimal(30, 10)` and JSONEachRow decimal strings, with no float conversion in Loader. Query's existing exact-decimal serialization remains covered by executor tests.

## JSON Correctness

JSON/JSONB with reordered object keys, nested arrays/objects, nulls, Unicode, and `12345678901234567890.123456789` was returned by Query as canonical JSON text. Parsing the Query string with decimal-aware JSON produced the exact numeric value and object meaning. No binary float was introduced for that JSON number.

## Timestamp Correctness

Microseconds survived for both timestamp forms. Query showed `2024-02-29T12:34:56.123456` for local timestamp and `2024-02-29T12:34:56.654321` for a source `+02:00` timestamptz normalized to UTC. The API representation uses `T` and no explicit zone suffix for these D3 UTC-backed ClickHouse columns.

## Loader Checkpoint Contract

The observed sequence is validate/transform, durable ClickHouse effect, test-only crash point, Query control checkpoint/publication callback, then Kafka input commit. An outage or failed callback did not commit the input. Publication retry exposed a D4 edge case: Query had persisted a maximum LSN on a higher offset before publication failed, while replay sent the event's older raw LSN. Loader now reports `max(event LSN, persisted load checkpoint LSN)` on replay, preserving Query's monotonic callback rule. A focused worker test checks apply-before-callback-before-commit and this retry.

## Crash-After-Write Replay

Test-only `CDC_CRASH_AFTER_APPLY=load` exited 86 after writing the target update but before checkpoint/ack. Physical count was 11 after the crash and 11 after Loader restart/replay. The input was uncommitted at the fault point, then Query returned exactly one current key 2 value of 253.

## Loader Restart

The Loader restarted with retained Kafka offsets; a fresh PostgreSQL update to key 2 materialized and appeared through Query without resnapshot or stale resurrection.

## ClickHouse Outage Recovery

After stopping only the isolated ClickHouse service, a fresh transformed event reached offset 20. Loader checkpoint and committed input did not falsely advance. Once ClickHouse started, replay caught up and authorized Query matched the source value 252. No outage event was classified as poison.

## Background-Merge Independence

Repeated authorized Query calls were identical while merges were stopped and after an explicit `OPTIMIZE TABLE ... FINAL` with merges resumed. `MergeTree` retained the exact physical duplicate, while the ranked view stayed at one current row for that key.

## Physical vs Logical Duplicates

Fresh simple source: ten reverse duplicate transformed deliveries, no new warehouse rows (8 before/after). Separate operator injection: one identical physical row added (14 to 15), four logical current rows remained, and the Loader's idempotent path skipped it. The typed source's six reverse deliveries also left three physical rows unchanged and its deleted key absent. Kafka at-least-once delivery is not described as exactly-once transport.

## Query Authority Verification

Workspace 11 queried its logical CDC Dataset through the real Query resolver, SQL guard, resource policy, ClickHouse executor, and sanitizer. Workspace 22 received 403. Physical versions table and unrelated table received 403; caller-supplied physical database override received 400. A CDC technical-column selector received 403 before warehouse execution. Dataset 19, 20, and 21 bindings were exactly their server-derived `cdc_<scope>_current` views, with `etl_status=completed` and `source_kind=cdc`.

## Query Schema / Preview Safety

Authenticated Dataset schema and preview returned only `id, customer, amount, status` for the simple source. Neither response contained a physical identifier or CDC technical column. Query also rejects `_cdc_` column references on CDC Datasets while allowing the same text as a string literal.

## Publication Safety and Retry

Nonempty snapshot publication requires a persisted Loader checkpoint, streaming state, matching catalog/PK, actual `MergeTree` versions table, and the ranked current view with exact business schema. An initial D4 development attempt exposed ClickHouse's added parentheses in view DDL; the predicate was corrected and the retained callback replay published the same Dataset. A controlled later failure changed Dataset 19 to `failed` after durable data, injected a snapshot-complete replay, and observed persisted checkpoint with uncommitted Kafka offset 19. Restoring `pending` plus the Loader LSN fix led to committed offset 20 and the same completed Dataset/view, with no logical or physical duplicate. Empty-table safe-pending remains D5.

## Bounded Source-vs-Query Comparison

The four-row mixed source and the 5,000-row snapshot were compared by key and exact values against authenticated Query after quiescence. The 5,000-row Query used a single bounded `groupArray(tuple(...))` result to remain within the Query row policy; every tuple matched PostgreSQL. This is an acceptance fixture, not a transactional reconciliation service.

## 5,000-Row Loader/Catch-Up Measurements

Fresh Dataset 21 in the isolated 20-slot local fixture, measured from source creation: first observed Loader apply **25.30 s**; transformed topic fully ready **510.25 s**; final Loader apply **111.91 s after transformed readiness**; exact authorized Query **1.89 s after final apply**; total **624.05 s**. At measurement, physical/logical counts were 5,000/5,000. The exact Query call took 1,890 ms. A later final-pin source update appeared in raw capture (LSN 365680472) and authorized Query. This exceeds the historical 300-second local budget and is not a production SLA result.

## Batching Findings

Loader currently performs one identity lookup, one warehouse insert for a new event, and one checkpoint callback per accepted event. The 5,000-row run showed transformed production consumed 510.25 seconds and the final Loader backlog 111.91 seconds; Loader batching alone cannot close the 300-second total. A batch must isolate poison, preserve full-key/version conflict checks, remain scope-bounded, and acknowledge only after durable write. No batching was introduced without that proof. D6 owns the end-to-end budget and a measured batch design if warranted.

## FINAL Cost Measurements

`FINAL` is unused in D4. Direct local current-view `count()` medians across five reads were **15.17 ms** for the replay-heavy simple table (15 physical/4 logical), **20.09 ms** for the typed table before reinsert (3/0), and **18.42 ms** for the 5,000-row table (5,000/5,000). The 5,000-row first five direct reads were 35.78, 24.45, 20.64, 20.46, and 23.37 ms in the acceptance run; a later five-read sample was 17.30, 18.75, 18.77, 18.42, and 15.99 ms. These local counts do not establish production capacity.

## Retention/Tombstone Safety

No version or tombstone TTL/cleanup was added. The newest delete marker must remain available for at least as long as old Kafka events can replay; retained key/version identities must cover the replay and reseed window. Kafka retention, CDC version/tombstone retention, and D5 reseed history policy must be reviewed together before cleanup. Physical customer erasure is separate.

## D1-D3 Regression Results

D3 deterministic IDs/versions, normalization, scope, poison/DLQ, replay, and type tests plus D2 offsets/capture preflight passed in the focused **97-test** CDC suite. D1 lifecycle, binding, workspace isolation, loader-only publication, generic callback controls, and sticky reseed passed in the **52-test** Django suite and **17** callback-security tests. A fresh final-pin update on the D4 5,000-row source appeared in raw capture and Query. Pause/resume was exercised when the initial typed fixture declared an unsupported type; capture/control implementation was otherwise unchanged, so the expensive D2 drift matrix was not rerun.

## Security Results

The live foreign workspace, physical table, unrelated table, physical override, and technical-column probes were denied. The equal-version DLQ contained only trusted scope/identity, reason, stage, retry count, and timestamp fields, not row content. A scan of **15,003** raw/normalized/transformed/DLQ Kafka values against five fixture secrets found no leak; Connect config retained a password file reference. Hosted broker ACL/TLS and production grants remain D6.

## Test Results

Final focused tests: **97 CDC pytest + 52 Django + 17 callback-security pytest + 10 Query-executor pytest = 176 passed, 0 failed, 0 skipped**. Python compile checks and `git diff --check` passed. Live isolated gates passed for snapshot, CRUD, stale/duplicate/reverse replay, conflict, types/composite key, restart, crash, outage, publication retry, authority, schema/preview, merge independence, exact source comparison, and 5,000-row investigation. Development attempts exposed the merge-losing table, view-DDL formatting, and checkpoint-LSN retry defects; each received a targeted fix and a final passing run.

## Files Modified

`etl-final/shared/cdc/clickhouse.py`, `worker.py`; `etl-final/tests/test_cdc_clickhouse.py`, `test_cdc_processing.py`; `services/query-service/database/cdc.py`, `test_cdc_physical.py`, `test_cdc_query_guard.py`; `services/query-service/integration/cdc.py`, `test_cdc.py`; `services/query-service/query_api/application/query_execution.py`, `services/workspace_db_resolver.py`, `clickhouse_executor.py`; `services/query-service/tests/test_clickhouse_executor.py`; `scripts/foundation_d4_store_probe.py`, `foundation_d4_kafka_probe.py`, `verify_foundation_d4.py`; this report. Earlier dirty files and reports 50-54 were preserved.

## Remaining D4 Debt

No known failing D4 correctness gate remains for fresh D4-layout sources under one scoped Loader. The fixture's old `ReplacingMergeTree` tables cannot supply erased version identities; the Loader fails them closed on a new event, and D5 must provide controlled migration/reseed rather than an unsafe in-place assumption. Query's exact large-int response is now decimal text outside the JavaScript safe range, including nested results; clients must honor that representation.

## Deferred D5/D6 Work

D5: generations, reseed/cutover of legacy scopes, empty-table completion, schema-history strategy, multi-writer/epoch fencing, and mature reconciliation. D6: 300-second final-pin performance budget, bounded batching if justified, retention/TTL and erasure policy, tighter read grants, hosted Kafka ACL/TLS/producer identity, remote CI and full A/B/C release regression. No D5/D6 implementation or production deployment is claimed here.

## D4 Exit Decision

**READY FOR D5 on fresh D4 storage.** Newest version wins, delete and newer reinsert are correct, stale/duplicate delivery and physical duplicates do not change Query state, equal-version conflict fails closed, supported values survive Query, restart/crash/outage/publication retry recover, and D1-D3 focused regressions pass. The 5,000-row local total remains over the D6 budget. Foundation-D remains PARTIAL; G-D remains OPEN; Production Readiness remains NO-GO. No commit or push was made.
