# Foundation-D / D5-R2 — Watermark Reconciliation and Final D5 Gate

## Executive Status

**D5 BLOCKED; Foundation-D PARTIAL; G-D OPEN; Production Readiness NO-GO.** A real, versioned watermark certificate now gates candidate cutover. Isolated live legacy and empty candidates obtained MATCH certificates and became Query authoritative; a deliberate candidate mismatch produced MISMATCH and could not cut over. The required empty-snapshot transaction-overlap probe failed before candidate snapshot start/completion. The remaining live continuity, schema, restart and two-controller fault gates have not passed. D6 was not started.

## Entry Repository State

Branch `foundation-c-staging`; HEAD `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`. Before edits, `git status --short --branch`, `git rev-parse HEAD`, `git diff --stat` and `git diff --cached --stat` were recorded. The working tree was intentionally dirty: 31 tracked paths changed (359 insertions, 50 deletions), untracked Foundation-D reports/code/evidence, and a dirty TimesFM submodule indication. The index was empty. All entry-dirty work was preserved; no reset, clean, stage, commit or push occurred. Reports 50–57 and TimesFM were not edited.

## D5-R2 Scope

This pass adds source/transport watermark proof, Query-owned candidate comparison, typed chunk digests, a durable MATCH/MISMATCH certificate, certificate verification at the existing D5-R1 cutover gate, focused tests, isolated live probes and operator instructions. It does not implement D6.

## Existing D5-R1 Baseline

D5-R1 already had one server-created candidate, isolated generation resources, old-worker/controller fencing, legacy-storage reseed, candidate abort, empty generation support, and recoverable Integration/Query cutover. Those mechanisms remain the cutover path. `local_exact_v1` is still accepted only in test or explicitly enabled development; it is rejected under production semantics.

## Reconciliation Consistency Model

The controller opens a PostgreSQL repeatable-read source snapshot and scans source business rows in PK order. It then emits a transactional logical WAL marker on a separate source connection, waits until the candidate's logical slot confirms flush through that marker, records Kafka stage ends, and waits for durable normalize, transform and load offsets through those ends. Query computes candidate current-view digests. A MATCH proves the materialized captured prefix associated with that fixed source snapshot and marker; it does **not** assert cross-database ACID. Writes during the comparison can cause a safe MISMATCH. Operators must quiesce source writes from snapshot establishment through cutover for deterministic acceptance. This operational write fence has not been enforced mechanically or proved in a live concurrent-write test, so D5 stays blocked.

## Source Watermark

The server derives the numeric PostgreSQL LSN from `pg_logical_emit_message(true, 'biavora_reconcile', 'watermark')`; clients cannot submit an LSN. Successful and mismatched attempts persist source LSN, candidate lineage and issuance time in the generation certificate and safe pipeline reconciliation summary. The marker does not change customer rows. An attempt that fails before certificate issuance has no separate durable in-progress watermark record; this remains D5 debt.

## Capture / Stage Watermarks

The generation-specific slot's `confirmed_flush_lsn` must reach the marker before topic ends are sampled. The controller samples raw, normalized and transformed generation topic end offsets, then waits for the next stage's persisted per-partition checkpoint through each sampled end. It renews and verifies its database lease while waiting. The live legacy and empty fixtures recorded capture LSN beyond the marker. A dedicated live retention-gap fault has not yet passed.

## Loader Applied Watermark

`loader_applied_through_lsn` in the certificate is the source marker justified by slot flush plus all stage-end offset barriers, **not** a claim that the highest business-row LSN equals the marker. This matters for empty tables and logical markers with no business row. The exact checkpoint map and stage ends are persisted in the certificate and rechecked for equality before pre-bind cutover; later candidate checkpoint movement invalidates it. The transport ordering assumption needs a targeted live retention/restart proof before D5 is READY.

## Candidate Query Validation Path

An internal, leased-controller-only Query action derives the candidate view from workspace, source, pipeline and generation. It checks the Query Dataset binding and D4 view layout, then uses Query's SQLGuard, workspace database, resource policy and executor against the business-only current view. No client selects a physical identifier or receives raw versions-table rows. The public reconciliation request accepts only the logical pipeline ID and checks workspace ownership. The comparator is read-only.

## Small Exact Reconciliation

Source and Query read all supported business columns in stable PK order, including nulls and deleted-row absence, into matching typed chunk digests. The live legacy 3-row and empty 0-row candidates returned MATCH. A controlled high-version candidate delete produced source count 2, Query count 1 and MISMATCH. Numeric values are retained as exact decimal strings.

## Bounded Large-Source Reconciliation

Both sides page at 500 rows with a 10,000-row launch cap and bounded per-page memory. A source beyond the cap fails closed; no count-only MATCH is issued. Integer and C-collated text primary keys, including composites, are supported; other PK orderings fail closed. This implementation has focused unit coverage but no live near-limit/composite benchmark, so the large-source exit gate is not closed.

## Canonical Row Hash

SHA-256 consumes length-prefixed deterministic JSON serialization of ordered `[column, typed-cell]` pairs. It distinguishes null/empty text, integer/text, numeric scale, booleans and composite PK fields; JSON keys are sorted and decimals rendered without binary float conversion. Date/timestamp values are rendered with microsecond precision; timezone-aware Python values are UTC-normalized. Additional live type-fidelity coverage, especially timestamp and JSON round trips through ClickHouse, remains required.

## Concurrent Source-Change Handling

The source snapshot is fixed before the marker. A later captured write that changes candidate state can make the chunk digests differ and safely block cutover; a later checkpoint movement invalidates a pre-bind certificate. There is no live write-during-comparison acceptance result and no enforced source write fence. The consistency claim is consequently limited to the controlled quiescent fixtures.

## Mismatch Policy

Any count or chunk-digest difference records MISMATCH, leaves the candidate non-authoritative and refuses cutover. There is no automatic overwrite of source or candidate data. The live mismatch fixture retained generation 1 Query authority.

## Mismatch Evidence

The certificate stores counts, at most 20 mismatching chunk indices, stage offsets, lineage, LSN and durations. It does not persist row payloads, credentials or raw versions-table contents. Local fixture evidence may include known synthetic values.

## watermark_reconciliation.v1 Contract

The generation-owned certificate binds workspace, source, pipeline, Dataset, generation, scope token, schema version/catalog, candidate Query view/generation, source and capture LSN, Loader stage-end/checkpoint proof, row/chunk counts, SHA-256 method, status, timestamp and durations. A MATCH certificate is required before Query CAS. Pre-bind validity lasts 60 seconds; an already bound candidate can complete the D5-R1 recovery protocol without reversing Query.

## Certificate Issuance

Only the authenticated leased controller can submit its proof to Integration. Integration validates exact proof keys/types, capture LSN, stage offsets against persisted checkpoints, candidate prerequisites, source/credential health and D4 storage. It writes MATCH or MISMATCH and safe audit. Public callers cannot submit status, LSN, count, hash, certificate or view.

## Certificate Verification

The D5-R1 cutover gate now verifies MATCH, exact workspace/source/pipeline/Dataset/generation/scope, schema/catalog, Query view/generation, capture and Loader proof, equal row counts, no mismatching chunks, current checkpoint and 60-second pre-bind lifetime. Missing, stale, MISMATCH and local-only certificates fail under production semantics. Focused tests cover these rejections.

## Certificate Invalidation

Schema/catalog or checkpoint changes invalidate a pre-bind certificate; expiry requires a new reconciliation. Source retirement and credential revocation block new binding. There is no durable event-triggered invalidation for a source write that has not yet advanced the candidate checkpoint; quiescence is therefore required operationally. This limitation blocks final readiness.

## Cutover Gate

The existing D5-R1 Integration PENDING → Query compare-and-swap → Integration ACTIVE/SUPERSEDED protocol is unchanged. The Query CAS is reached only after the real certificate passes. The live legacy and empty candidates cut over with `watermark_reconciliation.v1`; the mismatch candidate did not.

## Empty Candidate Reconciliation

An isolated empty source produced trusted generation-2 snapshot completion, zero-row D4 current view, marker and stage proof, MATCH with 0 source/Query rows, Query cutover to generation 2, then a later INSERT appeared exactly once in Query. Evidence: `../biavora-foundation-d-validation/d5-r2-empty-c725e595.json` and `d5-r2-empty_insert-0da86680.json`.

## Empty Snapshot Boundary-Overlap Live Test

**FAIL.** The first isolated probe held an INSERT uncommitted while waiting for snapshot completion; after 240 seconds the candidate failed closed with `CDC_SLOT_LOST`, generation 1 remained Query authoritative and generation 2 failed. A second fresh probe waited only for snapshot STARTED before committing, but timed out at 120 seconds; retained diagnostic state was `CDC_SLOT_INVALID`, generation 1 ACTIVE, generation 2 CANDIDATE, Query generation 1, inactive reserved candidate slot. Neither probe issued a certificate or passed the requested overlap. This is a D5 exit blocker; no PASS is inferred from Debezium documentation.

## Legacy Recovery With Real Certificate

**PASS in isolated scope.** An actual generation-1 `ReplacingMergeTree(_cdc_version)` table was detected as `CDC_STORAGE_INCOMPATIBLE` / `RESEED_REQUIRED`; authorized reseed created generation 2 with fresh slot/topics and D4 MergeTree/current view. Candidate snapshot/WAL, source marker 513439144, capture 513439192, stage barriers, 3-row Query comparison and real MATCH certificate preceded cutover. Query returned exact source state, generation 1 became SUPERSEDED, and the old legacy engine remained retained. Evidence: `../biavora-foundation-d-validation/d5-r2-retry-84e325bc.json`. The initial attempt on a separate scope failed closed because global WAL advanced ahead of an idle slot; the logical marker corrected the procedure without resetting offset history.

## Compatible ADD Regression

Not rerun live in D5-R2. Existing focused schema tests pass, but the requested controlled nullable ADD / resume / new certificate probe remains open.

## Incompatible Schema Reseed

Not rerun live in D5-R2. D5-R1 focused and isolated paths remain intact; the requested fresh incompatible DDL → reseed → real certificate → cutover path remains open.

## Lost Slot Live Fault

The failed overlap scope reported `CDC_SLOT_LOST`, but it was not the controlled continuity fault requested here and did not complete a clean reseed/reconciliation. This gate remains **FAIL / unproved**. No retained slot was deleted for this probe.

## Kafka Retention-Gap Live Fault

Not run. No offset was manually advanced or silently skipped; the dedicated `CDC_KAFKA_RETENTION_LOST` → `RESEED_REQUIRED` live fault remains open.

## Credential Revocation Live Race

**Partial PASS in isolated scope.** During a generation-2 candidate, revocation stopped candidate capture, a later stage callback returned HTTP 409, cutover was refused and the old Query binding remained readable. Evidence: `../biavora-foundation-d-validation/d5-r2-revoke_latest-6e781de3.json`. This was a ready candidate with an existing controlled mismatch, so it does not independently prove a race during provisioning or that every possible new source session is prevented.

## Source Retirement Live Race

**PASS in isolated ready-candidate scope.** Retirement stopped candidate capture, cutover was refused and the old zero-row historical Query binding remained readable. Evidence: `../biavora-foundation-d-validation/d5-r2-retire_candidate-11787baf.json`.

## Full Restart Matrix

Not completed for controller, Normalizer, Transformer, Loader, Query and Kafka Connect with a watermark-certified candidate. Earlier D5/D5-R1 restart results are retained, but do not close this D5-R2 gate.

## Multi-Controller Late-Effect Reconciliation

Not run. D5-R1's lease and guarded Connect operation tests remain green; an already-in-flight external effect across lease takeover still needs the requested live compensating-reconciliation proof. No distributed ACID claim is made.

## Orphan / Repair Classification

The D5-R1 read-only classification remains. Missing Dataset, failed candidate resources, Query-bound pending Integration and aborted retained resources require recoverable retry, abort or manual review; no physical auto-delete was added. Focused regression passes; no new live orphan matrix was run.

## Security

Foreign-workspace reconciliation is rejected by the logical public boundary; internal digest requires an exact candidate lineage and server-derived business view. Audit persists only bounded counts/chunk indices and codes. Public callers cannot submit physical names or certificate contents. The Query resource policy and SQLGuard remain in the internal comparison path. Focused API/security tests passed.

## Observability

Safe status now exposes active/candidate generation, reconciliation state/source watermark/Loader watermark/Query generation, certificate status and last cutover. Tenant IDs are not added to public metric labels. Detailed stage offsets and physical names stay internal.

## Runbook Changes

`docs/remediation/FOUNDATION_D_CDC_RUNBOOK.md` now describes authorized reseed, snapshot wait, marker, stage barriers, Query comparison, MISMATCH handling, certificate, cutover recovery, abort and retained superseded resources. It explicitly forbids manual offset rewriting and still holds production CDC because this report's exit gates are incomplete.

## Reconciliation Performance

Live legacy: 3 source/Query rows, 1 chunk, 6,580 ms total and 284 ms Query comparison. Live empty: 0 rows/chunks, 6,392 ms total and 166 ms Query comparison. Live mismatch: source 2/Query 1, 7,035 ms total and 207 ms Query comparison. Per-page memory is capped at 500 rows and total scan at 10,000; peak process memory was not measured. These are D5 reconciliation observations, not the D6 300-second / 5,000-row end-to-end gate.

## D1–D5-R1 Regression

Focused Django CDC lifecycle/auth/binding/controller/cutover tests: 52 passed. ETL capture/offset/poison/processing/ClickHouse/reconciliation tests: 106 passed. Query executor/callback/credential security tests: 30 passed. `makemigrations --check --dry-run` reported no changes; `git diff --check` passed. These focused suites do not replace the live fault matrix.

## Test Results

188 focused tests passed, 0 failed, 0 skipped in the final correctly configured runs. The initial two commands had Python import-path collection errors; both were rerun with explicit `PYTHONPATH` and passed. Live: legacy MATCH/cutover PASS; empty MATCH/cutover/post-INSERT PASS; mismatch rejection PASS; credential revocation partial PASS; source retirement PASS; boundary overlap FAIL twice. Other specified live gates remain unrun.

## Files Modified

D5-R2 work: `bi_platform_shared/cdc_reconciliation.py`; `etl-final/shared/cdc/{postgres.py,reconciliation.py,worker.py}`; `etl-final/tests/test_cdc_reconciliation.py`; `services/query-service/database/cdc_reconciliation.py`; `services/query-service/integration/{cdc.py,cdc_reseed.py,test_cdc.py}`; `scripts/verify_foundation_d5_r2.py`; `docker-compose.cdc-local.yml` (isolated fixture replication-slot capacity); `docs/remediation/FOUNDATION_D_CDC_RUNBOOK.md`; this report. Entry-dirty paths remain preserved.

## Remaining D5 Debt

Resolve and pass the empty-snapshot overlap with a candidate slot; persist an in-progress marker before certificate completion; enforce/prove source mutation bounds; live verify typed JSON/timestamp/composite PK and near-limit bounded comparison; complete compatible ADD, incompatible-schema reseed, lost-slot and Kafka retention faults; complete six-service restart matrix, new-session credential revocation race, two-controller late-effect convergence and orphan live classification. Do not infer a PASS from the current focused tests.

## Deferred D6 / Production Work

The historical 300-second 5,000-row end-to-end performance gate, final production retention/cleanup policy and broader operational rollout remain D6/production work. D6 must not start while D5 is blocked.

## D5 Exit Decision

**D5 BLOCKED.** The real certificate is now the cutover gate and the key legacy/empty/mismatch fixtures pass, but the required overlap and remaining live fault matrix do not. Foundation-D remains PARTIAL, G-D OPEN, Production Readiness NO-GO. No commit or push.
