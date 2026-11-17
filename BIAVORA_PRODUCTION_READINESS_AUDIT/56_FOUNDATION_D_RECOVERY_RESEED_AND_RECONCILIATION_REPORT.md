# BIAVORA Foundation-D / D5 — recovery, reseed and reconciliation

Date: 2026-11-07 (Asia/Damascus). This is a scoped local engineering report on the intentionally dirty, unstaged working tree. **D5 BLOCKED.** Foundation-D remains PARTIAL, G-D OPEN, Production Readiness NO-GO. A generation fence and empty-snapshot path now have evidence; controlled reseed, generation cutover and watermark-scoped reconciliation do not. Historical D6 performance failures remain failures.

## Executive Status

D5 cannot be READY FOR D6. The implemented work persists generation identity, denies stale callback epochs, uses a database controller lease, and publishes a genuinely empty initial PostgreSQL table after ordered Debezium notifications and D4 storage proof. Fresh live evidence also shows an immediate subsequent INSERT reaches authorized Query and a nonempty D4 source still supports mutable current state. No candidate generation can be requested or cut over safely, so the principal D5 legacy migration gate is unpassed.

## Entry Repository State

Before edits: branch `foundation-c-staging...origin/foundation-c-staging`; HEAD `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`; cached diff empty. The working tree already contained 30 modified tracked files, untracked D0–D4 reports/code/fixture/tests, and the pre-existing dirty TimesFM submodule. The tracked diff stat was 313 insertions and 50 deletions at entry; untracked D work is excluded from that stat. Nothing was reset, cleaned, staged, committed or pushed. TimesFM was not traversed or modified. Retained Docker volumes, slots and historical evidence were not deleted.

## D5 Scope and Non-Goals

This run changed only CDC generation/fencing, initial-snapshot completion, local fixture capacity, focused tests, migration verification and the runbook. The 5,000-row/300-second gate, production capacity, hosted TLS/ACL/identity, final remote CI, retention/erasure and Semantic Layer remain outside D5 closure. Their absence does not turn a D5 failure into a pass.

## Files Reviewed

Read reports 50 architecture, 50 implementation, 51, 52, 53, 54 and 55 in order; then canonical 34/43/45/22/30/31/33/20/49. Inspected Integration source/credential/CDC models and migrations, lifecycle/actions/callbacks, Query Dataset binding and authorization, the shared envelope, controller/Normalizer/Transformer/Loader, PostgreSQL preflight, Connect config, D4 ClickHouse storage, Compose, focused tests and runbook. The empty-snapshot mechanism was checked against [Debezium 3.4 notifications](https://debezium.io/documentation/reference/3.4/configuration/notification.html) and actual pinned 3.4.3 fixture records.

## Existing Recovery Gaps

Entry callbacks carried only the pipeline scope, with no generation, configuration or credential epoch. Controller scheduling was process local. Empty snapshots had no row callback and could not publish. Reconciliation compared up to 10,000 source rows with direct ClickHouse reads under a quiescent-source assumption, without a Loader watermark. Legacy `ReplacingMergeTree` storage correctly failed closed but had no replacement path.

## Generation Model

`CdcPipeline.generation` is a server-owned positive integer, initialized at 1. `CdcGeneration` retains one physical lineage record per pipeline/number with source/workspace/Dataset/table, schema version, catalog, PK, checkpoints, snapshot signal, predecessor, reason and times. Existing pipelines are backfilled as generation 1. The model admits ACTIVE, CANDIDATE, SUPERSEDED, FAILED and RESEED_REQUIRED states, but **candidate creation and active/candidate transition are not implemented**. Do not interpret a choice value as an accepted lifecycle.

## Generation Persistence

Migrations 0007–0009 add the lineage, controller lease and durable snapshot signal. The disposable PostgreSQL forward/reverse/reapply rehearsal passed 0005–0009, including exactly one generation-1 backfill for an existing pipeline. The retained local Query container applied 0007–0009 successfully. The owner-schema inventory now includes `integration_cdc_generations`.

## Callback Fencing

Internal scope now carries generation, source configuration epoch and active credential epoch. A callback must match all three under the Integration pipeline row lock. Generation-1 topic, storage name, `ChangeEnvelope.v1` content and event identity remain stable; a later generation derives a different physical token and `ChangeEnvelope.v2` identity. A test advances the persisted generation and verifies late controller, Normalizer, Transformer and Loader callbacks all receive `CDC_STALE_CALLBACK` without checkpoint, schema, state or Dataset binding changes. An additional test rejects callbacks after configuration and credential changes. Query publication takes a fresh Integration row lock and rechecks the generation after the durable Loader checkpoint, closing the checkpoint-to-publication race. **No actual generation-2 reseed was executed.**

## Multi-Controller Fencing

A controller claims a database row lease under `select_for_update`; another owner receives `CDC_CONTROLLER_LEASE_HELD`. A monotonically increased fence and owner token are required on controller callbacks. Threads in one controller process share one owner; the first live implementation exposed and fixed a per-thread owner error. Serial two-owner/lease-expiry tests pass. The 90-second lease may delay recovery after a crash. Connect REST and the protected credential file do not consume the fence token, so an expired controller paused between lease check and a physical side effect is not fully fenced. **The multi-controller physical-authority acceptance gate remains open.**

## Controlled Reseed Design

Required sequence remains: manager plus explicit operator authorization; stop and drain old capture; create a server-numbered candidate with new slot/topic/storage; fresh snapshot and WAL; watermark-scoped Query reconciliation; one logical Dataset binding update; mark old generation superseded; retain old resources. No operation performs this sequence yet. `resume` stays denied for RESEED_REQUIRED; no offset/slot/table reset shortcut was added.

## Reseed Authorization and Idempotency

No reseed endpoint was exposed. Manager-only source actions retain existing authorization. Concurrent/retried reseed requests and response-loss recovery have **no passing evidence**. The generation number is server-owned when creating the initial lineage.

## Legacy Storage Recovery

D4's `CDC_STORAGE_INCOMPATIBLE` fail-closed check remains intact. Existing legacy scopes remain RESEED_REQUIRED. A live legacy `ReplacingMergeTree` → new D4 storage → Query cutover acceptance was **not run** because the candidate/reseed path is absent. No unsafe in-place DDL conversion was attempted.

## Candidate Generation Provisioning

Not implemented. `CdcGeneration.CANDIDATE` is reserved state only. Physical names for generation >1 can be derived without colliding with generation 1, but no candidate resource creation or orphan repair is available.

## Query Cutover

The existing Query Dataset binding continues to point at the D4 current view after Loader evidence or a trusted empty-snapshot signal. No candidate-generation binding update exists. Atomic old/new cutover, workspace and validation predicates for a candidate, and post-cutover authority recovery remain unproved.

## Cutover Failure Recovery

Not implemented or fault injected. A current-generation publication failure leaves its checkpoint durable and the Dataset pending for a replay, as the existing focused test proves. This is not candidate cutover recovery.

## Rollback Boundary

No post-reseed rollback promise is made. Until candidate cutover exists, the old Dataset binding is retained. Any future rollback must prove old source continuity; merely retaining a view is insufficient.

## Empty-Table Completion

Connect now enables Debezium's sink notification topic for each scope. Normalizer validates the pinned PostgreSQL connector's topic prefix, exact initial-snapshot aggregate, table, successful zero-row table scan and ordered STARTED → TABLE_SCAN_COMPLETED → COMPLETED events. Integration persists the sequence and notification offset in the generation and pipeline, and rejects a new initial snapshot after completion as `CDC_UNEXPECTED_RESNAPSHOT`. Heartbeats, elapsed time and Connect RUNNING cannot publish. The first fresh live scope exhausted the fixture's 20 retained slots; the second exposed actual numeric timestamps/topic-prefix connector names; the third exposed kafka-python's new-partition no-offset case. All were diagnosed without deleting retained evidence. The parser and explicit checked seek were corrected, then that third scope completed and published.

## Empty Dataset Publication

Query still checks the exact D4 MergeTree versions table, ranked current view, schema and PK before binding. The durable empty signal is an alternative to a Loader row checkpoint only for an initial zero-row scan. Authorized Query returned zero rows for the fresh scope and then one real row after the subsequent source INSERT. Evidence: external retained `d5-empty-results-52a8f643.json`. No synthetic business row was inserted for completion.

## Empty Snapshot / Immediate WAL Continuity

The fresh source was empty when published; an INSERT immediately afterward became visible through authorized Query. PASS for that ordering. An INSERT transaction deliberately spanning the completion boundary was **not executed**, so the overlapping-boundary gate remains open. Debezium's documented PostgreSQL snapshot-to-stream continuity is a design basis, not a substitute for that test.

## Schema Generation Policy

The accepted D3/D4 policy remains: controlled nullable ADD with drain/pause/catalog update/resume; incompatible DROP/RENAME/type/PK change fails to RESEED_REQUIRED. Historical old-schema events remain rejected. Durable generation-specific catalog and PK metadata now exist, but a new generation cannot yet recover from incompatible schema. The compatible ADD live procedure was not rerun in this D5 run.

## Credential Rotation / Revocation Fencing

The callback scope includes the current active credential version and source configuration version; a late old-epoch callback fails closed. The worker recreates its consumer on an epoch change. Source disable/retire permits only a fenced controller STOPPED observation, and non-controller callbacks are rejected. Historical D2 rotation and D1 revocation tests remain recorded; a fresh live rotation/revocation race was not run here. A durable Kafka event applied just before a rejected callback may be replayed; the new generation never binds its old physical scope.

## Reconciliation Consistency Model

Current comparison remains bounded and requires a quiescent source. It is not a distributed ACID snapshot and is insufficient to authorize candidate cutover. Destination reads remain direct Loader-owned ClickHouse, not authorized Query output; this is an explicit D5 blocker.

## Reconciliation Watermark

Pipeline stage checkpoints retain offsets/maximum LSNs. There is no recorded source reconciliation LSN with a proof that Loader reached it, and no Query generation stamp. **Watermark-scoped MATCH is not implemented.**

## Exact Small-Source Reconciliation

Existing `reconcile` converts and compares up to 10,000 ordered rows including typed values, but uses direct ClickHouse and the quiescent-source assumption. No new authorized-Query exact reconciliation test passed in D5. The fresh live D4 source/Query values were compared separately, not as a cutover reconciliation certificate.

## Chunked / Bounded Large-Source Reconciliation

Not implemented. The current 10,000-row limit still fails closed. No unlimited scan or misleading MATCH was added.

## Reconciliation Mismatch Policy

The old bounded result can report MISMATCH, but no candidate cutover exists and no generation/watermark-scoped mismatch audit was added. A mismatch must block future cutover; this remains an implementation gate.

## Restart Recovery

The local controller was replaced during acceptance; its persisted lease delayed takeover and the fresh scope ultimately advanced. Normalizer was replaced after notification parser/offset fixes and then consumed the retained notification sequence to completion. A new nonempty source subsequently passed through Query. This is limited evidence, not the complete controller/Normalizer/Transformer/Loader/Query/Connect restart matrix.

## Slot/WAL Loss Policy

Existing preflight marks missing, lost or unreserved slots `CDC_SLOT_LOST`/RESEED_REQUIRED; no D5 destructive slot-loss injection was made against retained evidence. The new fixture's 20-slot limit was reached by retained historical scopes, so the local-only capacity was raised to 40 without deleting slots or changing production claims.

## Kafka Retention-Gap Policy

`ResumeOffsets` still checks committed/checkpoint positions against retained beginnings and ends and raises `CDC_KAFKA_RETENTION_LOST`; the notification topic uses the same check. A newly assigned partition with no position receives an explicit checked seek, never an implicit latest reset. Focused tests pass. A fresh live retention-expiry fault was not run.

## Pause / Stop / Retire / Supersede Semantics

Existing pause, stop/disable and retire tests passed. RESEED_REQUIRED remains sticky. A manually superseded generation's four old callback stages were rejected. No real reseed has exercised candidate/supersede transitions end to end.

## Resource Cleanup Policy

No automatic cleanup was added. Old slots, topics, versions tables, views, Datasets and audits remain retained. The local fixture diagnostic scopes and three disposable migration databases were left intact; no historical evidence was destroyed.

## Orphan Detection / Repair

Not implemented. The current pending Dataset compensation remains for initial enable. Candidate/connector/slot/storage orphan detection needs the controlled reseed model.

## Observability

Authenticated status now includes the current generation; safe snapshot signal and controller fence are persisted internally. Existing slot/WAL/checkpoint/capture health remains. No tenant IDs were added to public Prometheus labels. Candidate generation, applied watermark and last cutover are unavailable because their lifecycle is not implemented.

## Runbook Changes

`docs/remediation/FOUNDATION_D_CDC_RUNBOOK.md` now describes generation/credential callback rejection, the controller lease, the durable empty-snapshot signal and the safe hold procedure for RESEED_REQUIRED/legacy storage. It explicitly says reseed is unavailable and prohibits offset manipulation or in-place storage conversion.

## Legacy ReplacingMergeTree Live Migration Acceptance

**FAIL / NOT RUN.** No generation-2 candidate, snapshot/WAL replacement, reconciliation or Query cutover exists. This alone requires D5 BLOCKED.

## Fault-Injection Results

PASS (focused ORM/worker): four stale old-generation callback stages; configuration and credential epoch callbacks; two-controller claim conflict and expired-fence rejection; notification order/foreign connector rejection; notification retention-gap check; existing Loader replay, conflict and poison tests. LIVE: a per-thread controller lease defect and two empty-notification integration defects were exposed and corrected. NOT RUN: reseed twice, candidate creation crash, pre/post-cutover crash, Query cutover failure, mismatch block, lost slot, live retention gap, revocation during capture, retirement during candidate, overlapping completion write.

## Empty-Table Live Acceptance

PASS for the final fresh scope: durable zero-row initial snapshot signal, D4 storage publication, authorized zero-row Query, then real INSERT visible through authorized Query. External evidence `d5-empty-results-52a8f643.json`. Earlier failed diagnostic scopes remain as evidence, not passes.

## D1–D4 Regression Results

Focused ETL contract/offset/processing/ClickHouse/capture suite: **102 passed**. Focused Django Integration/Query CDC suite: **38 passed**. Query callback/executor pytest: **27 passed** before the final worker-only patch. Fresh nonempty D4 source: snapshot and update/delete/insert matched authorized Query, foreign workspace denied; evidence `d5-nonempty-results-32846b96.json`. Full D4 outage/crash/equal-version/typed live matrix and expensive D2 drift matrix were not rerun. Historical D4 performance numbers remain approximately 624 seconds source creation → exact Query, 112 seconds transformed-ready → final Loader, and 1.9 seconds final Loader → exact Query; no D5 replacement measurement is claimed.

## Security Results

The scope/epoch fence rejected forged old callbacks in focused tests. The new notification parser rejects a foreign connector and wrong table before authority is recorded. Query's foreign-workspace denial passed live on a fresh nonempty source. No new source password or row image is placed in snapshot notifications, DLQ or callback evidence by this code. A fresh full secret scan and hosted Kafka ACL/TLS/workload identity certification were not performed.

## Test Results

Focused suites above: **167 passed, 0 failed, 0 skipped** across 102 ETL, 38 Django and 27 Query pytest checks (separate runs). `makemigrations --check --dry-run`, Python compile, Compose config and `git diff --check` passed. Disposable PostgreSQL 0005–0009 forward/reverse/reapply passed after correcting the verifier's historical-state lookup. Fresh empty and nonempty live acceptance passed with the external evidence files named above. The aborted/failed development runs are not counted as passing acceptance. `scripts/check_release_documentation.py` failed on pre-existing table-width findings at report 50 architecture lines 131–132; report 50 was not changed. The isolated Compose stack was stopped after testing without removing its containers or volumes.

## Files Modified

`bi_platform_shared/cdc_contract.py`; `services/query-service/integration/{models.py,cdc.py,test_cdc.py,migrations/0007_cdc_generation.py,migrations/0008_cdc_controller_lease.py,migrations/0009_cdc_snapshot_signal.py}`; `services/query-service/database/cdc.py`; `etl-final/shared/cdc/{connect.py,worker.py}`; `etl-final/tests/{test_cdc_contract.py,test_cdc_offsets.py,test_cdc_processing.py,test_cdc_capture_preflight.py}`; `scripts/{foundation_c4_owner_schemas.py,verify_foundation_d_migration.py,verify_foundation_d5.py}`; `docker-compose.cdc-local.yml`; `docs/remediation/FOUNDATION_D_CDC_RUNBOOK.md`; this report. Entry-dirty files not listed here remain preserved.

## Remaining D5 Debt

Implement and prove: server-authorized idempotent candidate reseed; old connector/worker physical fencing; real legacy-layout recovery; generation-safe Query cutover and crash recovery; post-cutover authority/rollback boundary; source/Loader/Query watermark reconciliation and bounded larger-source chunks; mismatch gate/audit; overlapping empty-snapshot write; multi-controller physical side-effect fence; full restart/retention/slot/credential/retirement fault matrix; orphan/resource lifecycle and authenticated health. Until these pass, do not begin D6 final acceptance.

## Deferred D6 / Production Readiness Work

D6 retains the historical 5,000-row <300-second performance/release gate, final pinned full matrix, A/B/C release regression and reviewed remote CI. CAP-14/Production Readiness retains hosted transport, identities, KMS, broker ACL/TLS, operational capacity, retention/erasure and deployment certification. D5 did not reinterpret either historical failure as a pass.

## D5 Exit Decision

**D5 BLOCKED.** Generation-1 fencing and empty-snapshot publication are real progress, but no controlled reseed can replace a lost slot or legacy `ReplacingMergeTree` lineage, no reconciliation result can authorize candidate cutover, and no atomic candidate Query binding has been proved. Foundation-D remains PARTIAL; G-D OPEN; Production Readiness NO-GO. No commit or push.
