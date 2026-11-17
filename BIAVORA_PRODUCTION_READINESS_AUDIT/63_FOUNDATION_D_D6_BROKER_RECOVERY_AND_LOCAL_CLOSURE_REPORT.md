# Foundation-D / D6-R1 broker recovery and local closure

## Executive Status

**D6-R1: LOCAL READY FOR RELEASE CANDIDATE. Foundation-D: LOCAL READY, remote gate pending. G-D: BLOCKED. Production Readiness: NO-GO.** Two independent fresh 5,000-row fixtures recovered retained and fresh writes to exact authorized Query in 19.469 and 17.672 seconds from confirmed Kafka health. A later 75-second outage exposed Kafka Connect's five-minute cooperative rebalance delay; after reducing that measured delay to 10 seconds, the same active candidate recovered exact state in 32.579 seconds. This is local evidence only. D6-R2 remote CI has not run.

## Entry Repository State

Branch `foundation-c-staging`, entry HEAD `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`, staged diff empty. The working tree was intentionally dirty with Foundation-A/B/C and D0-D6 changes. TimesFM was already dirty at submodule commit `d720daa6786539c2566a44464fbda1019c0a82c0`; it was neither entered nor modified. No reset, clean, staging, commit, push, or remote CI occurred.

## D6-R1 Scope

This run measured broker recovery on the optimized CDC path, performed a real post-broker candidate reconciliation, exercised live worker crash/replay and pause/resume, verified local owner and security boundaries, and reran local release checks. All source and Query fixtures were disposable. Fixture credentials and detailed timestamped JSON are outside the repository under `C:\Users\massa\Desktop\senior 1\biavora-foundation-d6-r1-{clean1,clean2}-validation`.

## Accepted Performance Baseline

Report [62](62_FOUNDATION_D_FINAL_ACCEPTANCE_AND_RELEASE_REPORT.md) retains the original optimized fresh runs: 72.641, 132.281 and 135.906 seconds, median 132.281, all below 300 seconds. D6-R1 clean fixtures independently reached exact authorized 5,000-row Query in 53.594 seconds (`clean1/d6-baseline-1f0d13a5.json`) and 45.719 seconds (`clean2/d6-baseline-d2726791.json`), with no worker restart during either baseline.

## Broker Failure Reproduction

The prior D6 report's two 120-second failures and post-broker candidate timeout remain historical failures. A first D6-R1 setup fixture also stalled at Normalizer/Transformer boundaries under accumulated local Docker load; its baseline was never accepted. A diagnostic Transformer restart occurred **before** its broker interruption, so that fixture's later 22.516-second broker measurement is diagnostic only. After isolating two new projects, the accepted short broker runs both passed. An additional 75-second outage on the active clean2 candidate failed the 120-second gate and timed out at 300 seconds; its Query caught up afterward. The failure file `clean2/d6-r1-candidate-postfix-r1-long-broker.json` is preserved.

## Recovery Timeline

All times below are seconds after confirmed broker health, derived from timestamped T0-T18 marks. T8/T10 and T11-T16 are first observed topic/checkpoint advances, so sampling gives an upper bound rather than an exact event emission instant.

| Observation | Clean run 1 | Clean run 2 | Long outage after fix |
| --- | ---: | ---: | ---: |
| Kafka metadata and both raw writes | 2.344 | 1.765 | 13.125 |
| Normalized retained/fresh | 11.687 | 11.203 | 21.891 |
| Transformed retained/fresh | 11.703 | 11.219 | 21.907 |
| Loader retained/fresh checkpoint | 11.703 | 11.219 | 26.141 |
| Authorized Query both writes | 11.859 | 11.375 | 26.297 |
| Exact source versus authorized Query | **19.469** | **17.672** | **32.579** |

The long failed run had Kafka metadata by 2.111 seconds but Connect reported `UNASSIGNED` for roughly five minutes, with an inactive source slot and no raw advance. Its log then recorded a rebalance assignment with `delay=300000`; it did not satisfy the gate even though it eventually converged.

## Connect / Debezium Recovery

The accepted short runs observed a healthy Connect worker, connector and task RUNNING, and advancing slot restart LSN. The long failed run showed why REST health and a task label alone are insufficient: connector `UNASSIGNED` and slot inactive meant no capture. Connect logs showed a 300,000 ms delayed cooperative reassignment. The worker's generated configuration after remediation contains `scheduled.rebalance.max.delay.ms=10000`. The post-fix long run showed RUNNING connector/task and raw capture by 13.125 seconds. No test script restarted Connect, recreated a connector or slot, or reset an offset during an accepted run.

## Kafka Client Recovery

The initial setup stall was isolated to one nonaccepted fixture: raw/normalized had 5,150 events while transformed had none; a separate diagnostic consumer could transform 100 records in 0.034 seconds, and a separate diagnostic producer sent a message in 0.715 seconds. That did not establish a deterministic client-library root cause. The later clean fixtures and post-fix long run demonstrate Kafka metadata, consumer assignment and producer recovery through the actual pipeline. The 75-second failure showed Connect internal group reassignment, rather than a downstream Kafka producer or Loader bottleneck, dominated its delay.

## Stage Catch-Up

All accepted broker runs moved retained and fresh source changes through raw, normalized, transformed, Loader checkpoint and authorized Query. The two clean runs reached downstream stage advances around 11 seconds after broker health. The post-fix 75-second run reached raw at 13.125 seconds and Loader by 26.141 seconds. The final full source/Query comparison had exactly 5,000 current rows. Kafka group inspection after recovery showed active Normalizer, Transformer and Loader members with committed offsets at topic ends. No latest seek was used.

## Low-Traffic Batch Behavior

The broker drills intentionally used one retained update and one fresh update. Even though the optimized worker can batch up to 100 events, those two low-traffic updates reached Loader and Query within the budget. No batching change was needed. The prior D6 bounded batch and exact-version semantics remain in place.

## Root Cause

The **measured long-outage delay** was Kafka Connect cooperative rebalance scheduling: a `delay=300000` assignment held the connector `UNASSIGNED` for about five minutes after broker health. [Apache Kafka documents the default](https://kafka.apache.org/39/configuration/kafka-connect-configs/) and that tasks remain unassigned during it. Separately, a later Kafka producer timeout caused a Connect source task to fail and the controller to pause; this delayed incident occurred after the initial rotation PASS, so that first rotation result was insufficient proof of sustained continuity. These observations do not prove that every historical report-62 timeout had the same mechanism.

## Remediation

`docker-compose.cdc-local.yml` now sets `CONNECT_SCHEDULED_REBALANCE_MAX_DELAY_MS: 10000`; the generated Connect properties confirmed the exact value. The controller now fences a failed-task stop when the replication slot is inactive, then resumes the retained connector on a later poll. It still fails closed with `CDC_CONNECT_TASK_ORPHANED` if the slot remains active. Focused tests cover both branches; the failed-task branch was not directly triggered in the final live drills. No timeout was reduced without a measured five-minute delay. The fixture's Connect setting is local; production orchestration must carry an equivalent reviewed value before deployment.

## Recovery Correctness

All passing runs compared the full 5,000 source rows with an authorized Query of the generation-bound current table. Retained and fresh writes were distinct. The source slot remained the same, restart LSN advanced, offsets were neither reset nor sought to latest, and no new snapshot notification appeared. The candidate stayed generation 2 ACTIVE through subsequent outage and rotation checks. The failed 75-second run remains recorded as FAIL despite its later exact convergence.

## Final Broker Recovery Run 1

Fresh project `biavora_d6_r1_clean1`, evidence `d6-baseline-1f0d13a5-r1-broker.json`: broker health to raw retained/fresh 2.344 seconds, Loader checkpoint 11.703, both writes in Query 11.859, full exact Query **19.469 seconds**. No manual Connect restart or intervention after outage. PASS.

## Final Broker Recovery Run 2

Independent fresh project `biavora_d6_r1_clean2`, evidence `d6-baseline-d2726791-r1-broker.json`: broker health to raw retained/fresh 1.765 seconds, Loader checkpoint 11.219, both writes in Query 11.375, full exact Query **17.672 seconds**. No manual Connect restart or intervention after outage. PASS. After the measured Connect fix, the active candidate additionally passed a short outage in 15.0 seconds and a 75-second outage in 32.579 seconds; these are supplemental, not replacements for the independent clean runs.

## 120-Second Decision

**PASS for the final accepted local runs:** 19.469 and 17.672 seconds, each independently below 120. The supplemental post-fix long outage also passed at 32.579 seconds. The preserved pre-fix long outage failed at the 300-second observation limit. No averaging, retroactive relabeling, or subtraction of pipeline time was used. Timing begins at confirmed Kafka health, as required.

## Post-Broker Candidate Reconciliation

Each accepted clean broker run was followed by a generation-2 candidate on the same source. Both reached exact D4 state, requested real reconciliation, obtained MATCH and cut over to authorized Query. Evidence: `clean1/d6-baseline-1f0d13a5-reconciliation.json` and `clean2/d6-baseline-d2726791-reconciliation.json`. The previous report-62 candidate timeout remains historical evidence.

## Watermark Certificate

Both certificates use `watermark_reconciliation.v1`, 5,000 source/current rows and 10 chunks. Clean1: source LSN 38,867,656, capture LSN 38,867,704, Loader LSN 38,867,656. Clean2: source LSN 45,578,288, capture LSN 45,578,336, Loader LSN 45,578,288. Both were MATCH before generation-2 ACTIVE cutover; no local-exact substitute was used.

## Normalizer Live Kill

`clean1/d6-baseline-1f0d13a5-r1-normalize-crash.json`: the optimized worker exited 86 after its durable downstream effect and before progress callback/commit. On restart it replayed from the retained position, advanced its checkpoint, preserved the generation and slot, and reached exact authorized Query. PASS.

## Transformer Live Kill

`clean1/d6-baseline-1f0d13a5-r1-transform-crash.json`: the same test-only after-effect/before-checkpoint boundary was exercised on Transformer. Replayed input did not corrupt current state; exact authorized Query and no resnapshot were observed. PASS.

## Loader Crash-After-Write

`clean1/d6-baseline-1f0d13a5-r1-load-crash.json`: a two-row Loader batch was durably applied, then the worker exited 86 before checkpoint/commit. Both physical row-version counts moved from one to two before replay and remained two afterward, proving idempotent replay. Checkpoint and authorized Query converged without a new snapshot. PASS.

## Optimized Pause / Resume

`clean1/d6-baseline-1f0d13a5-r1-pause-resume.json`: physical PAUSED state and inactive slot in 4.234 seconds, retained write after resume in 5.875 seconds, same slot, fresh write, exact Query and no resnapshot. Both transitions remained within the D2 120-second local budget. PASS.

## Owner-Role Local Acceptance

The C4 owner-role apply/login/rollback script passed against disposable PostgreSQL `foundation_d6_r1_owner`, with `BIAVORA_C4_DISPOSABLE=1`. Live ClickHouse `cdc_query` grants remained SELECT-only. The CDC source role was non-superuser with REPLICATION and table SELECT for capture. This is local owner evidence, not production role certification.

## Security Matrix

Live `clean2/d6-baseline-d2726791-r1-security.json` passed foreign CDC status/reseed/reconcile 404, viewer CDC 403, foreign and physical Query 403, technical-column Query 403, Query DELETE 400, public callback 403, stale-generation callback 409 and redacted public status. The v2 rotation result (`clean2/d6-baseline-d2726791-r1-rotation-v2.json`) passed old-password denial, rotated-password source access, stale-epoch callback 409, same slot, no resnapshot, 30-second settled observation, second post-rotation write, STREAMING state and exact Query. The initial rotation result is retained but not treated as sustained proof. SSRF and prohibited host checks passed in the ETL security/direct transport suite. The explicit security regression runner also passed; its cases overlap the suite totals.

## Full Local Regression

After the controller and Connect changes, the affected ETL matrix passed: worker/tests/models/security 487, canonical utilities 328 with 10 skips, Extractor 225 with 5 skips, Transformer 12 with 1 skip, Loader 14 with 1 skip, Connector 145, Detector 4, Metadata 4: **1,219 ETL passes, 17 skips**. The full earlier D6-R1 matrix before these narrow changes passed 1,801 distinct tests, zero failures, 17 skips; adding the two new failed-task boundary cases yields 1,803 distinct cases across the final tree. The unchanged backend, AI, voice, report, visualization and frontend suites were completed in this D6-R1 work; their counts are detailed below and are not added again for focused security reruns. The forecasting test that may traverse TimesFM was excluded.

Backend: Query pytest 120; Query Django database/Integration 77; Gateway 8; owner environment 16; shared readiness 6; Auth 2; Workspace 4; Subscription 11; Notification 4 = 248. AI 226, Voice 23, Report 5, Visualization 63, frontend 19 = 336; together with ETL 1,219 gives 1,803. AI and Voice also reported 12 and 5 nested subtests, not counted as distinct suite cases. No failed completed suite remains.

The final Query pytest rerun passed 120 and the final Query Django database/Integration rerun passed 77. The first Django rerun needed two empty external compatibility tables for historical migration 0002 in the disposable test database. The next run exposed a test harness issue: the scheduled-prune command's connection cleanup closed its enclosing `TestCase` transaction and caused five test-order errors. The test now mocks only that cleanup while still checking pruning and heartbeat; production command behavior is unchanged. The complete 77-case rerun passed afterward.

## Frontend

Frontend test suite 19 passed, ESLint passed, Vite production build passed with 1,929 modules transformed, and `scripts/verify_frontend_bundle.py` passed. Existing size/browser-data warnings did not fail the build.

## Migration

Disposable PostgreSQL forward/reverse/reapply passed for Foundation-C, Integration 0005-0011 and Query Dataset 0007, using the pinned Query image. The eight-service migration drift checker reported no changes. No applied migration file was rewritten.

## Secret Scan

The live Kafka known-fixture scan covered 11 topics and 30,976 records with zero matches and no incomplete partitions (`clean2/d5-r4b-kafka-secret-scan-d6-r1-clean2.json`). The release gate's pinned gitleaks image scanned the first-party archive and exited zero with **zero findings** (`biavora-foundation-d6-r1-secret-scan-final-v2/gitleaks-redacted.json`, outside the repo). TimesFM and external fixture credentials were excluded. Two Windows Docker tree-copy attempts timed out; the final scanner mounts a single archive, unpacks it inside the pinned container and preserves the redacted report. No secret value was printed or added to the repository.

## Documentation / Release Checks

`scripts/p0c_static_check.py` passed: 883 maintained files compiled, no merge markers. `scripts/verify_release_workflow.py` passed all nine mandatory jobs, six native security environments and the no-continue-on-error contract. `scripts/check_release_documentation.py` checked 28 changed Markdown files and reported only the two pre-existing table-width errors in report 50 at lines 131-132; this report added no finding. Historical report 50 was not rewritten.

## Files Modified

D6-R1 added isolated broker, telemetry, live-restart, pause/resume, security and rotation acceptance harnesses under `scripts/`; added the failed-task boundary tests in `etl-final/tests/test_cdc_capture_preflight.py`; updated `etl-final/shared/cdc/worker.py` and `docker-compose.cdc-local.yml` for measured recovery; isolated Query's scheduled-prune test transaction in `services/query-service/integration/tests.py`; updated `scripts/scan_foundation_d6_first_party.py` to mount a single archive; added this report; and updated root `FOUNDATION_D_RESULTS.json`. Other dirty Foundation-D files predate D6-R1 and remain unstaged. External validation JSON and fixture secrets are not repository files.

## Remaining Local Blockers

None identified in the required local gate after the measured rebalance fix and supplemental 75-second pass. The initial setup stall and pre-fix long-outage failure remain preserved as diagnostic evidence; they were not counted as accepted final runs. A production environment must still supply the reviewed Connect setting and validate its own failure domain.

## Deferred Remote CI

No release candidate commit or push was made. The nine-job remote workflow was not run. D6-R2 must review the final tree, commit and push an approved candidate, and run the remote matrix before G-D can become GREEN or production readiness can change from NO-GO.

## D6-R1 Exit Decision

**LOCAL READY FOR RELEASE CANDIDATE; G-D BLOCKED until D6-R2 remote CI.** No TimesFM touch, silent offset reset, unexpected resnapshot, generation corruption, staging, commit or push occurred in D6-R1.
