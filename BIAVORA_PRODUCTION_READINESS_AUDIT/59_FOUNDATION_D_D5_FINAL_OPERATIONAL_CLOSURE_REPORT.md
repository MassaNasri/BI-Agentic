# Foundation-D / D5-R3 — Final Operational Closure Report

## Executive Status

**D5 BLOCKED; Foundation-D PARTIAL; G-D OPEN; Production Readiness NO-GO.** The fresh empty-snapshot transaction-overlap acceptance failed. Several required live continuity, schema, credential, restart and concurrency gates were not run. A subsequent zero-row reconciliation of that retained candidate produced a real MATCH certificate, but it does not prove the required transaction overlap or authorize a D5 exit decision. D6 was not started.

## Entry State

Branch `foundation-c-staging`; HEAD `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`. The entry worktree contained 31 tracked modifications, untracked Foundation-D artifacts, and a dirty TimesFM submodule indication. The cached diff was empty. Entry work and reports 50–58 were preserved. No reset, clean, stage, commit or push was performed; TimesFM was not traversed or edited. Historical report 58 failures remain failures.

## D5-R3 Scope

This pass investigated candidate slot provisioning and snapshot timing, persisted capture readiness and reconciliation attempt progress, ran one fresh isolated empty-snapshot probe, reran a zero-row certificate on the retained candidate, completed controlled lost-slot and Kafka retention-gap faults with explicit generation-3/4 recovery and cutover, and ran focused Query and ETL regressions. It did not extend work into D6.

## Remaining Gates from Report 58

Report 58 left the empty-snapshot overlap, in-progress attempt record, enforced source mutation bound, live typed/near-limit/above-limit proofs, compatible and incompatible schema paths, controlled lost-slot and Kafka retention faults, provisioning-phase credential race, complete restart matrix, late physical effect, and orphan matrix open. The mismatch and stale-certificate gates also require preservation. Durable attempt persistence and the controlled lost-slot and Kafka retention-gap recoveries gained live evidence in this pass; the complete exit list is not satisfied.

## Empty-Snapshot Overlap Root Cause

The historical `CDC_SLOT_LOST` and `CDC_SLOT_INVALID` attempts in report 58 lack contemporaneous slot/Connect/notification samples sufficient to assign an exact physical cause. The preflight implementation did treat an applied credential version as evidence that the slot must already exist; that could classify initial provisioning as lost. It also treated a newly visible slot with null LSN fields as invalid. These interpretation races were corrected, but they are **plausible code causes, not a proven reconstruction of either historical attempt**.

The fresh D5-R3 probe has a different, measured timing failure. Candidate generation 2 was created at 13:22:25 UTC; the connector was observed configured at 13:24:05, the slot at 13:24:07, and active at 13:24:08. Debezium's STARTED notification carries source timestamp 13:24:05.302, but Kafka did not receive it until 13:24:08.577. TABLE_SCAN_COMPLETED carries source timestamp 13:24:07.890 and reached Kafka at 13:24:08.579. Thus the empty scan completed about 687 ms **before** STARTED became observable on Kafka. COMPLETED reached Kafka at 13:24:08.749; Integration exposed only COMPLETED in the probe's polling samples. The probe could not use a trusted STARTED signal to open a transaction before the empty scan boundary. This is direct evidence for this run, not a claim about every possible snapshot schedule.

The retained evidence records slot type, plugin, database, PID, restart/flush LSN, WAL status, publication presence, Connect task and offset, generation, controller lease/fence, credential epoch and control state. `../biavora-foundation-d-validation/d5-r3-overlap-3dba1569.json` retains 322 physical/control observations and the notification timestamps. No source offset, slot or connector was reset to make a pass.

## Candidate Capture Readiness

The controller now persists `capture_slot_seen` and `capture_ready` for a candidate generation. Capture readiness requires an active, correctly identified `pgoutput` logical slot with valid WAL state, a running Connect connector/task, initialized source offset, and a trusted snapshot notification. The slot-seen flag makes a missing previously established slot `CDC_SLOT_LOST` while allowing an unprovisioned new slot to remain provisioning. Query binding remains independent. The retained candidate eventually reached `capture_ready=True`, observed STREAMING, and no error; it was not ready while STARTED was still the visible snapshot state. The simultaneous capture-ready/snapshot-start timing gate therefore **failed** in the fresh overlap run.

## Empty-Snapshot Overlap Acceptance

**FAIL.** Generation 1 remained old Query authority while generation 2 was provisioned from an empty source. The required controlled transaction was never opened because the readiness and STARTED boundary was not observable together. No transaction BEGIN/COMMIT, overlap WAL continuation, Loader application of that row, overlap certificate, cutover or authorized exactly-once Query row can be claimed. Later zero-row reconciliation on the same retained candidate returned a real `watermark_reconciliation.v1` MATCH at source LSN `732523104`, with a persisted MATCH attempt. That separately proves the empty-candidate certificate path; the overlap evidence remains `status: FAIL`.

## Reconciliation Attempt Persistence

Generation-scoped JSON persistence and migration `0011` now record attempt UUID, generation, state, source LSN, stage-end offsets, timestamps and safe failure code, without customer row payload. The controller advances REQUESTED → SOURCE_SNAPSHOT_OPEN → WATERMARK_EMITTED → WAITING_CAPTURE → WAITING_LOADER → COMPARING → MATCH/MISMATCH, or FAILED. A new request invalidates the old certificate; the issuer requires the matching persisted COMPARING attempt, LSN and stage ends. A resumed worker that sees a non-REQUESTED attempt records `CDC_RECONCILIATION_INTERRUPTED` and requires a fresh request rather than issuing a certificate from incomplete proof. Focused callback/restart-state tests pass; the actual process-restart-at-watermark live gate remains open. The retained live candidate persisted MATCH and the source LSN above.

## Source Mutation Consistency Rule

The existing operational rule still requires source writes to be quiescent from repeatable-read snapshot establishment through cutover. BIAVORA does not mechanically enforce customer-database write blocking or a deterministic movement detector with bounded retry. Consequently a source movement could occur after the fixed source snapshot and before or after comparison. This gate is **open**; no false-MATCH exclusion is asserted for concurrent writes.

## Concurrent-Write Reconciliation

**Not run live.** No controlled write during comparison was injected. A mutation beyond the snapshot may cause a mismatch, but that possibility is not a deterministic acceptance proof.

## Typed Live Reconciliation

**Not run live.** Prior typed hashing unit coverage remains; this pass did not exercise composite PK, exact Decimal, UUID, dates, timestamp/timestamptz and nested Unicode/high-precision JSON through source → CDC → Loader → Query comparison.

## Near-Limit Bounded Reconciliation

**Not run live.** The implementation still uses 500-row chunks and a 10,000-row launch cap. No several-thousand-row duration or peak-memory evidence was collected in D5-R3.

## Above-Limit Failure

**Not run live.** Unit coverage for the cap remains, but no fresh source above 10,000 rows was exercised in this pass.

## Compatible ADD

**Not run live.** The quiesce/pause/nullable ADD/catalog/resume/new-value/reconciliation sequence remains open.

## Incompatible Schema Reseed

**Not run live.** No fresh incompatible DDL → RESEED_REQUIRED → generation N+1 → real certificate → cutover sequence was exercised.

## Lost Slot Fault

**PASS in the isolated scope.** After the overlap probe had already failed, the disposable generation-2 connector was STOPPED, its exact inactive slot `b_1db8a6b15156460297d2e8b5918cd8016ea027c5` was removed by fixture-admin authority, and the controller was restarted. It naturally persisted `CDC_SLOT_LOST`, `RESEED_REQUIRED`, desired PAUSED and generation 2 FAILED. The slot remained absent; generation 1 Query authority still returned the exact empty result. Authorized `slot_lost` reseed created generation 3 with a fresh slot and snapshot. Capture readiness, a real `watermark_reconciliation.v1` MATCH at source LSN `800603224`, and certificate-gated cutover followed. Final lineage was `(1, SUPERSEDED), (2, FAILED), (3, ACTIVE)`; authorized Query bound generation 3 and returned the exact empty result. The lost generation-2 slot was not recreated. Evidence: `../biavora-foundation-d-validation/d5-r3-lost-slot-0b97b02c.json`. This is a zero-row continuity fault/recovery proof, not the uncommitted transaction-overlap acceptance.

## Kafka Retention Gap

**PASS in the isolated scope.** With Normalizer stopped on disposable generation 3, one source row (ID 77) committed and reached its raw topic. The durable resume position was 0; Kafka's admin delete-records operation advanced that topic partition's retained beginning to 1. Normalizer restarted and naturally persisted `CDC_KAFKA_RETENTION_LOST`, `RESEED_REQUIRED`, desired PAUSED and no checkpoint advance. Generation 3 remained Query authoritative with its prior exact empty result; the missing row was not silently skipped into Query. Explicit authorized reseed created generation 4; its fresh snapshot captured ID 77, candidate state matched source, a real `watermark_reconciliation.v1` MATCH at source LSN `808512112` preceded cutover, and authorized Query returned that one row exactly once. Final lineage: `(1, SUPERSEDED), (2, FAILED), (3, SUPERSEDED), (4, ACTIVE)`. Evidence: `../biavora-foundation-d-validation/d5-r3-retention-gap-fc29923f.json`. The fixture broker prefix was deleted only for the disposable generation-3 raw topic; no offset was rewritten or seeked to latest.

## Credential Revocation Race

**Not run during provisioning.** Report 58's ready-candidate partial result remains the only live evidence. A new-session race is still open.

## Source Retirement Race

**Not rerun during provisioning.** Report 58's ready-candidate retirement PASS remains historical evidence; provisioning-phase retirement remains open.

## Controller Restart

The controller was restarted to observe the generation-2 lost-slot fault, and it reached `CDC_SLOT_LOST` / `RESEED_REQUIRED`. This is a bounded fault-detection result. A controller restart during an in-progress reconciliation with watermark state was **not run live**, so the restart-matrix gate remains open.

## Normalizer Restart

Normalizer was restarted in the controlled Kafka retention-gap fault and correctly failed closed. The broader candidate/slot/offset continuity restart case was **not run**, so the restart-matrix gate remains open.

## Transformer Restart

**Not run live in D5-R3.**

## Loader Restart

**Not run live in D5-R3.**

## Query Restart

**Not run live in D5-R3.**

## Kafka Connect Restart

**Not run live in D5-R3.**

## Reconciliation Restart Recovery

The implementation explicitly fails an interrupted nonterminal attempt and requires a new proof. The requested live restart after persisted source watermark and before Loader barrier was **not run**; this exit gate remains open.

## Multi-Controller Late-Effect Convergence

**Not run live.** Existing lease/fence tests do not show compensation for an external Connect operation completing after takeover.

## Orphan Classification

**Not run as a live matrix.** Existing read-only classification is retained; no orphan resource was automatically deleted.

## Mismatch Regression

Report 58's controlled MISMATCH and cutover denial remain historical PASS. Focused D5 tests still cover mismatch denial, but no new disposable live corruption case was run in D5-R3.

## Certificate Invalidation

Focused tests confirm certificate rejection on checkpoint movement and mismatched attempt state; a new reconciliation request clears the old certificate. The full live schema, retirement, revocation, generation and candidate-data invalidation matrix was **not run**. The certificate issuer and cutover still require `watermark_reconciliation.v1` under production semantics; `local_exact_v1` remains limited to test/explicit development.

## Security

The new attempt stores only safe IDs, LSNs, offsets, timestamps and codes; no customer rows or credentials are persisted in it. The public response exposes only bounded candidate readiness and attempt status, not physical slot names or stage offsets. Internal progress requires the controller identity plus current lease owner/fence and exact generation scope. The existing Query comparison path remains business-view-only. This is focused code/test evidence, not a complete security re-audit.

## Observability

Internal status now carries persisted capture flags and attempt progress. The overlap probe records physical/control samples and durable notification timestamps even on failure. Public status shows candidate capture readiness and a safe attempt summary. The fresh probe demonstrates that polling an Integration status field alone is insufficient to observe a fast empty-snapshot STARTED window.

## Runbook Updates

`docs/remediation/FOUNDATION_D_CDC_RUNBOOK.md` now documents attempt interruption/fresh retry, candidate capture readiness, certificate invalidation and the observed STARTED delivery race. It retains the operational quiescence requirement and production hold.

## D1–D5-R2 Regression

Focused Query CDC lifecycle, binding, cutover and public-boundary tests: **53 passed**. Focused ETL capture/preflight, contract, offsets, processing, ClickHouse and reconciliation tests: **107 passed**. Migration check: no model changes outstanding. `git diff --check`: passed. These 160 tests are focused regression evidence; the complete D1–D5-R2 suite and live fault matrix were not run. Initial attempts to start the ETL suite lacked `pytest` in the worker image; the disposable verifier was completed from locally present dependencies and the final ETL run passed.

## Tests

Final focused runs: **160 passed, 0 failed, 0 skipped**. The fresh empty-snapshot overlap live acceptance **failed**. The retained empty-candidate reconciliation, controlled lost-slot recovery, and real Kafka retention-gap recovery **passed** as separate cases. No live PASS is inferred for unrun gates.

## Files Modified

D5-R3 files: `etl-final/shared/cdc/{postgres.py,worker.py,reconciliation.py}`; `etl-final/tests/test_cdc_capture_preflight.py`; `services/query-service/integration/{models.py,cdc.py,cdc_reseed.py,test_cdc.py,migrations/0011_cdc_capture_and_reconciliation_attempt.py}`; `scripts/{verify_foundation_d_cdc.py,verify_foundation_d5_r3.py}`; `docs/remediation/FOUNDATION_D_CDC_RUNBOOK.md`; this report. The disposable verifier Dockerfile and retained JSON evidence are in the sibling `biavora-foundation-d-validation` fixture directory. Pre-existing dirty files remain preserved.

## Remaining D5 Debt

Design a source-side snapshot boundary fixture where trusted STARTED is observable before scan completion, without offset/slot manipulation, and rerun the required uncommitted transaction overlap through exact-once Query cutover. Implement and prove a deterministic concurrent-source-mutation rule. Run typed and near/above-limit live reconciliation, schema ADD and incompatible reseed, credential/retirement provisioning races, six-component and in-progress reconciliation restarts, late-effect two-controller convergence, orphan matrix, and complete mismatch/stale-certificate live regression. Run the full D1–D5 suite after those fixes.

## Deferred D6 Work

The historical 300-second / 5,000-row end-to-end performance gate remains **NOT CLOSED IN D5**. No D6 implementation or acceptance was started.

## D5 Exit Decision

**D5 BLOCKED.** The mandatory transaction-overlap acceptance failed, source mutation remains operational rather than enforced, and multiple live continuity/restart gates are unproved. Foundation-D remains PARTIAL, G-D OPEN, Production Readiness NO-GO. No commit or push.
