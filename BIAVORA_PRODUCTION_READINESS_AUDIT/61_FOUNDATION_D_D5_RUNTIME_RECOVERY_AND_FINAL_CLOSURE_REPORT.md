# Foundation-D / D5-R4B — Runtime Recovery and Final D5 Closure

## Executive Status

**D5 READY FOR D6.** The isolated local D5-R4B lifecycle, restart, reconciliation recovery, controller convergence, orphan, and security gates passed. This is a D5 exit decision, not a production release: Foundation-D remains **PARTIAL**, G-D **OPEN**, and production readiness **NO-GO**. The D6 performance gate is **NOT CLOSED IN D5**. No D6 work was started.

## Entry Repository State

Branch `foundation-c-staging`, HEAD `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`. Before R4B edits, 31 tracked paths were modified, Foundation-D artifacts were untracked, the cached diff was empty, and the TimesFM submodule was dirty. Existing D0–D5-R4A work and reports 50–60 were retained. No reset, clean, stage, commit, or push occurred; TimesFM was not traversed or modified.

## D5-R4B Scope

This pass addressed provisioning lifecycle races, meaningful process restart boundaries, interrupted reconciliation, late effects from two controllers, retained resource classification, stale certificates, and final regression. Disposable PostgreSQL/Connect/ClickHouse scopes were used for controlled faults. The original `biavora_foundation_d` fixture and its evidence remain retained and stopped; a separate `biavora_d5_r4b` fixture holds the R4B runtime evidence. Evidence paths below are relative to the repository root. Historical failed attempts remain recorded rather than reclassified.

## Accepted D5-R4A Baseline

Report 60 established the empty-snapshot/WAL overlap, real MATCH, authorized Query, concurrent mutation invalidation, typed and five-chunk bounded comparison, limit rejection, schema evolution, and preserved lost-slot/retention fault evidence. Those gates were accepted as the entry baseline. Historical failures in reports 56, 58, and 59 remain failed observations. R4B did not weaken the D4 physical order predicate, source movement check, 60-second certificate lifetime, checkpoint binding, generation fencing, or cutover CAS.

## Credential Revocation During Provisioning

A fresh generation-2 candidate was left in `PROVISIONING` before its source capture session was established. After credential revocation and controller restart, the candidate's desired state was `STOPPED`, internal credential lookup returned no active credential, a stale Loader callback returned HTTP 409, no reconciliation certificate or cutover authority appeared, and the generation-1 Query remained exact. Direct cutover returned `CDC_CANDIDATE_NOT_READY`. The test held the controller before its external provisioning call; the separate two-controller test below covers an already in-flight external effect. Evidence: `../biavora-foundation-d-validation/d5-r4b-revoke-20261110a.json`.

## Credential Recovery / Epoch Fencing

The revoked credential was not restored to make the race pass. Old-epoch callbacks remained fenced after controller recovery. Optional fresh credential rotation was not exercised. The two-controller fixture separately proved that a stale secret-file writer cannot regain logical authority and that the current credential file converges to the new fence with mode `0600`.

## Source Retirement During Provisioning

A separate fresh candidate was retired at the same pre-session `PROVISIONING` boundary. The candidate could not certify or cut over, stale Loader callback returned HTTP 409, desired capture converged toward `STOPPED`, and the historical generation-1 Query stayed exact. Direct cutover returned `CDC_CANDIDATE_NOT_READY`; no retained history was deleted. Evidence: `../biavora-foundation-d-validation/d5-r4b-retire-20261110a.json`.

## Restart Matrix Design

The single fresh R4B scope recorded generation, desired/observed state, slot and snapshot lineage, stage offsets, Loader checkpoint, reconciliation attempt and certificate, and Query binding around each restart. Normalizer, Transformer, and Loader were stopped at durable upstream-topic boundaries; downstream Query was checked before and after recovery. Query and Connect were restarted with active CDC data. The Controller was restarted in active streaming and candidate provisioning. Evidence: `../biavora-foundation-d-r4b-validation/d5-r4b-restart-20261110b.json`.

## Controller Restart

Active generation-1 streaming recovered on the same lineage and a fresh source event reached Query. A second Controller restart during generation-2 provisioning reused that candidate, connector, and slot; it did not create generation 3. The pending-cutover and Query-bound recovery paths were exercised in the reconciliation and orphan cases below. **PASS.**

## Normalizer Restart

A raw event reached its topic while Normalizer was stopped. Query did not move prematurely; after restart the persisted offsets advanced monotonically and Query returned each expected row once on the same snapshot and slot lineage. **PASS.**

## Transformer Restart

A normalized event was durable before Transformer resumed. Replay preserved the downstream event and exact Query result, with monotonic checkpoints and unchanged generation/snapshot lineage. **PASS.**

## Loader Restart

A transformed event was durable before Loader resumed; checkpoint and exact Query caught up. An additional controlled `APP_ENV=test` one-shot Loader exit occurred **after ClickHouse apply and before checkpoint/ack**. At that boundary the row had one physical version and the checkpoint was unchanged. Normal Loader replay advanced the checkpoint, retained one version, preserved the snapshot notification, and returned the exact authorized Query result. No resnapshot occurred. Evidence: `../biavora-foundation-d-r4b-validation/d5-r4b-loader-after-apply-20261110a.json`. **PASS.**

## Query Restart

Query reloaded the persisted active generation after restart and returned the same authorized rows. The candidate remained nonpublic; foreign workspace and technical-column denial were also verified in the security regression. **PASS.**

## Kafka Connect Restart

Connect recovered the same connector/slot lineage and retained source offsets. A fresh write reached Query without a new snapshot or generation. **PASS.**

## Restart Matrix Summary

All six components passed in the finalized matrix: Controller, Normalizer, Transformer, Loader, Query, and Kafka Connect. No unexpected generation, resnapshot, silent offset reset, backward Query rebind, or second analytical authority was observed. The initial harness had assertion-shape and old-Query expectation errors; those were corrected and the same retained scope was finalized. The PASS is the final evidence file, not the earlier harness failures.

## Reconciliation Restart at Watermark

The Controller restarted after a persisted `WAITING_LOADER` attempt while a transformed row had not yet crossed the Loader checkpoint. The old attempt persisted `FAILED` with `CDC_RECONCILIATION_INTERRUPTED` and no MATCH certificate. After Loader recovery, an explicit fresh attempt produced a real `watermark_reconciliation.v1` MATCH. Partial attempt state could not certify incomplete history. Evidence: the restart matrix JSON. **PASS.**

## Restart After MATCH / Before Cutover

The Controller restarted after a fresh MATCH and before cutover. The valid persisted certificate was rechecked at binding, and the final cutover made generation 2 ACTIVE with exact Query rows. The old generation became SUPERSEDED. No certificate was resurrected from the interrupted attempt. Evidence: the restart matrix JSON. **PASS.**

## Multi-Controller Late External Effect

Two real Controller instances competed under fences 8 and 9. After the newer fence won, a late old-controller Connect STOP effect occurred. The old post-effect and logical callback were rejected (HTTP 409 for the callback); the new controller restored the connector with task `RUNNING`, the same slot, and generation-2 Query authority. This proves logical fencing and eventual physical convergence in the tested race; it does not claim Kafka Connect natively enforces the database fence. Evidence: `../biavora-foundation-d-r4b-validation/d5-r4b-fence-17c44025.json`. **PASS.**

## Late Credential-File Effect

The same two-controller fixture tested a late writer at old secret fence 10 after new fence 11. The old post-effect was rejected and the current file was repaired to the current credential, with filesystem mode `0600`. Secret contents were not written to evidence. **PASS.**

## Orphan Matrix

The live matrix distinguished a missing pre-progress candidate table, a failed retained candidate, a Query-bound pending integration transition, and a missing logical Dataset binding. Public classification returned bounded repair routes; none granted Query authority from an orphan or automatically deleted a physical resource. Evidence: the four `../biavora-foundation-d-r4b-validation/d5-r4b-orphan-*-20261110b.json` files.

## Recoverable Orphan Repair

Missing candidate storage before durable progress returned `CDC_CANDIDATE_STORAGE_MISSING` / `recoverable_retry`; Controller repaired the same generation and preserved D4 storage and old Query authority. A Query-bound generation-2 cutover interrupted after the binding returned `CDC_QUERY_BOUND_PENDING` / `recoverable_retry`; restart finalized forward to lineage `(1 SUPERSEDED, 2 ACTIVE)` and exact generation-2 Query. It did not rebind backward. **PASS.**

## Manual-Review Orphans

An aborted generation-2 candidate retained its ClickHouse storage and PostgreSQL slot and returned `CDC_FAILED_GENERATION_RETAINED` / `manual_operator_review`; no certificate or active Query binding survived. The Connect connector was physically `FAILED` with zero tasks and an inactive retained slot. Its persisted observed state was still `STOPPING` because Connect had not reported a clean STOPPED transition; the controller continued fenced stop requests. This is a retained failed/manual cleanup state, **not** a claim of physical `STOPPED`. A controlled missing Dataset binding returned `CDC_DATASET_MISSING` / `manual_operator_review`; old Query remained exact. Neither case auto-deleted resources or silently repaired an unsafe binding. **PASS for fail-closed classification; operator cleanup remains manual.**

## Live Mismatch Regression

A fresh real reconciliation on a controlled corrupted candidate returned `watermark_reconciliation.v1` MISMATCH. Live cutover was rejected with `CDC_RECONCILIATION_CERTIFICATE_REQUIRED`; generation-1 Query stayed exact and no automatic repair occurred. A transient Kafka availability error during initial fixture setup was recovered with retained offsets in the same candidate; the final MISMATCH evidence is `../biavora-foundation-d-r4b-validation/d5-r4b-mismatch-20261110b.json`. **PASS.**

## Live Certificate Invalidation Matrix

Six invalidation cases were exercised with live MATCH certificates: (1) expiration beyond 60 seconds; (2) committed source row followed by actual Loader checkpoint movement; (3) actual compatible nullable PostgreSQL ADD and schema-version movement; (4) authorized credential revocation; (5) source retirement; and (6) explicit new generation, whose old-generation certificate could not authorize cutover. Each stale path denied cutover and preserved the previously authoritative Query. The primary, revoke, and retire evidence is in `../biavora-foundation-d-r4b-validation/d5-r4b-certificate-*.json`.

The schema case initially met the existing D4 physical-order guard before the certificate guard because Loader had appended the new business column after technical columns. Loader now inserts compatible columns `FIRST`/`AFTER` the preceding business column. A controlled same-type reorder in the already affected disposable candidate isolated the stale-certificate decision; a **separate fresh generation-3 fixture** then proved the corrected Loader image places the real new business column before technical fields while schema version advances from 1 to 2. Strict D4 validation remained enabled. Evidence: `../biavora-foundation-d-r4b-validation/d5-r4b-schema-placement-20261110a.json`. **PASS.**

## Workspace / Security Regression

Foreign workspace reseed, reconcile, and status returned HTTP 404; foreign Query returned HTTP 403. A technical `_cdc_version` Query returned HTTP 403 with no rows. Public status disclosed no candidate physical table, connector/slot identifier, lease/fence internals, or reconciliation LSN. Evidence: `../biavora-foundation-d-r4b-validation/d5-r4b-security-20261110a.json`. **PASS.**

## Secret Leakage Check

The bounded fixture scan checked 14 known secret values across 19 R4B JSON/report files, including reports 60–61, and the last 1,000 log lines of each of six services. The Kafka scan covered 109 CDC topics, 109 partitions, and 300 records, including DLQs, with zero incomplete partitions and zero matches. This is a known-fixture-value and bounded-log check, not a universal secret-discovery claim. Evidence: `../biavora-foundation-d-r4b-validation/d5-r4b-secret-scan-20261111a.json` and `d5-r4b-kafka-secret-scan-20261110a.json`. **PASS.**

## Full D1–D5 Regression

The final focused Django Query CDC suite passed **60** tests; repo-mounted Query security/source API/Dataset/ClickHouse pytest passed **67**; rebuilt Worker CDC pytest passed **108**. Total: **235 passed, 0 failed, 0 skipped**. D1–D4 and D5-R1–R4A historical acceptance remain in reports 50–60 and their retained evidence; R4B exercised their focused regression surfaces without rerunning expensive R4A fixtures. An initial repo-mounted Query run found three stale test-mock failures after the source-kind contract change; the mock was updated and all 67 passed. Earlier container-path test-runner import errors and fixture setup timeouts were not counted as final passing tests. No remote CI run is claimed.

| Focused regression surface | Final result | Basis |
| --- | --- | --- |
| D1 lifecycle/auth/binding | PASS | Query CDC and public/security tests |
| D2 capture/preflight/control | PASS | Worker CDC tests and live Connect/controller recovery |
| D3 contract/poison/replay | PASS | Worker CDC tests and durable stage replay |
| D4 Loader/ClickHouse/Query authority | PASS | Worker and Query tests; live after-apply replay and strict storage order |
| D5 generation/lease/empty completion | PASS | Query CDC tests and live generation/fence recovery |
| D5-R1 reseed/cutover | PASS | Query CDC tests and live candidate cutover |
| D5-R2 reconciliation | PASS focused regression | Query/Worker tests and live MATCH/MISMATCH; report 58's historical blocked result is retained |
| D5-R3 continuity faults | PASS focused regression | Worker/Query tests and retained lost-slot/retention evidence; report 59's historical blocked result is retained |
| D5-R4A snapshot/schema/bounded reconciliation | PASS focused regression | Query/Worker tests, fresh schema-placement fixture, and report 60 accepted live evidence |
| D5-R4B runtime recovery | PASS | Live R4B matrix and focused tests |

## Migration / Compile / Diff Checks

`makemigrations --check --dry-run --settings=service_config.sqlite_test_settings` in the R4B Query container returned **No changes detected**. Python `compileall` on shared, scripts, Query CDC, and Worker CDC code passed. `docker compose config --quiet` passed. `git diff --check` passed with only Git LF/CRLF conversion warnings on existing tracked paths. Final checks were local only.

## Files Modified

R4B production-path edits: `services/query-service/integration/cdc_reseed.py` and `cdc.py`; `etl-final/shared/cdc/clickhouse.py` and `worker.py`. Focused tests: `services/query-service/integration/test_cdc.py`, `services/query-service/tests/test_query_security_boundary.py`, and `etl-final/tests/test_cdc_clickhouse.py`. New disposable acceptance tools: `scripts/verify_foundation_d5_r4b*.py`, `scripts/run_foundation_d5_r4b_*.ps1`, and `scripts/diagnose_foundation_d5_r4b_failed_stop.py`. This report is new. These are R4B changes layered on the pre-existing dirty D0–R4A work; reports 50–60 were not rewritten.

## Remaining D5 Debt

No tested R4B exit gate remains open. The retained failed candidate requires **manual operator review/cleanup** of its failed Connect connector, inactive slot, and storage; the controller does not label it physically STOPPED or auto-delete it. Credential rotation recovery was optional and not exercised. The provisioning lifecycle fixture stops before an external call; the separate two-controller fixture covers a late in-flight external mutation. These are stated limits of the evidence, not silent passes. No remote CI claim is made.

## Deferred D6 Work

The historical 5,000-row source-to-exact-Query measurement was approximately **624 seconds** against a **less than 300 seconds** gate. That performance gate remains **NOT CLOSED IN D5** and belongs to D6. Foundation-D, G-D, and production readiness remain respectively PARTIAL, OPEN, and NO-GO until their later gates close.

## Final D5 Exit Decision

**D5 READY FOR D6.** The tested lifecycle races, six process restarts, interrupted and post-MATCH reconciliation recovery, late stale-controller effects, orphan classifications, live MISMATCH and certificate invalidations all preserved analytical authority and CDC continuity. D6 is authorized as the next phase by this D5 gate, but was not started in this pass. No commit or push occurred.
