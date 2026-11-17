# BIAVORA Foundation-D / D2-R — capture control closure

Date: 2026-11-06 (Asia/Damascus). Branch: `foundation-c-staging`. Entry and closing HEAD: `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`. This report describes local engineering evidence, not a production deployment or a remote CI run. `OBSERVED` means this run measured the pinned local fixture; `HISTORICAL` means report 52's failed attempt; `DEFERRED` means a later Foundation-D gate owns the proof. Report 52 is preserved unchanged.

## Executive Status

**D2 READY FOR D3.** The frozen D2-R worker passed fresh PostgreSQL-to-raw-Kafka capture, recovery, physical pause, retained-write resume, drift detection, and stale-scope fairness within the original 120-second pause/resume and 90-second drift bounds. Empty-table Query publication remains pending and is explicitly deferred to D5. Foundation-D is **PARTIAL**, G-D is **OPEN**, and Production Readiness remains **NO-GO**. D3 was not started.

## Entry State

`git status --short --branch`, `git rev-parse HEAD`, `git diff --stat`, and `git diff --cached --stat` were recorded before editing. The parent working tree contained pre-existing D0/D1/D2 untracked code and modified files, plus the dirty TimesFM submodule. The cached diff was empty. No reset, clean, stage, commit, push, TimesFM edit, or historical report rewrite occurred. The isolated `biavora_foundation_d` Compose project retained its volumes, slots, Kafka offsets, and earlier evidence. Read precedence followed reports 50/51/52 and their referenced canonical architecture, ownership, scope, and security documents.

## Blockers from Report 52

| Historical D2 blocker | Report 52 result | D2-R disposition |
|---|---|---|
| A: PAUSED before physical slot inactivity | Two 120-second waits failed | PAUSED now requires stopped Connect task **and** inactive valid PostgreSQL slot for an active source; final pause 19.688 s, restart-during-pause 30.203 s. |
| B: retained-write resume | Exceeded 120 s; later captured after manual controller restart | Final unique retained write captured in 7.843 s; fresh write captured; no manual restart. |
| C: publication drift | Detected after 90-second wait | Extra table 8.265 s; selected table removal 16.375 s; row filter 18.422 s; column list 19.469 s. |
| D: empty-table completion | Zero raw rows, RUNNING task, offset with no marker | Confirmed on final build; Dataset remains `pending`. Safely deferred to D5; no Query-readiness claim. |

These are new D2-R observations. They do not turn report 52's failed gates into passes.

## Root-Cause Analysis

The old controller polled every 2 seconds **after** a sequential pass over all pipelines. A single scope could spend up to 10 seconds on each Connect/control REST call, up to 15 stop-status iterations, 5-second source connection/statement limits, and ClickHouse `prepare` DDL on every pass. Thus the nominal 2-second interval was not a per-pipeline detection bound. The old non-streaming branch accepted Connect `STOPPED`/no tasks as PAUSED and removed the credential file without inspecting `pg_replication_slots.active`. The old streaming branch treated a transient Connect REST conflict/unavailability as a fatal `CDC_CONNECT_UNAVAILABLE`: `control_one` sent another STOP, reported the error, and Integration changed desired state to PAUSED. The first D2-R diagnostic candidate reproduced this path: a fresh connector was STOPPED, the pipeline became `PAUSED|PAUSED|CDC_CONNECT_UNAVAILABLE`, and the raw capture probe timed out. This is direct evidence for the transient-error path; report 52 did not retain enough timestamps to prove which exact REST response occurred in its earlier resume failure.

The retired fixture had `source.state=retired`, persisted `desired_state=PAUSED`, and `observed_state=DEGRADED`. The control GET correctly substituted effective STOPPED intent, but the old controller then sent a STOPPED callback against the incompatible persisted PAUSED intent. Report 52 observed repeated rejected callbacks. The final fixture retained this one stale scope, so the fairness checks ran with the problematic history present.

**Historical pause timeline (report 52):** T0 pause requested; T1 desired PAUSED/observed PAUSING; T2 Connect STOP issued; T3 Connect `STOPPED`, no tasks; T4 controller persisted PAUSED; T5 slot was still active; T6 two physical-inactivity waits exceeded 120 s. The original record has no reliable T2–T5 sub-second timestamps. **Final measured path:** T0 request; controller STOP; subsequent poll sees `STOPPED`/no tasks; read-only slot inspection sees an inactive, reserved slot; only then callback persists PAUSED. This completed in 19.688 s; the controller-restart version completed in 30.203 s.

**Historical retained resume timeline (report 52):** T0 100 writes made during pause; T1 resume requested; T2 Connect remained STOPPED; T3 raw wait exceeded 120 s; T4 manual controller restart; T5 retained terminal write eventually appeared. **Final measured path:** T0 unique 100-write batch committed while the same slot was inactive; T1 resume requested; T2 controller verifies source/config and restores mode-600 credential file; T3 Connect RESUME starts one task and reactivates the same slot; T4 terminal retained write appears raw at 7.843 s; T5 a distinct fresh write appears raw. No operator restart or offset manipulation occurred.

**Historical drift timeline (report 52):** T0 publication gained an extra table; T1 90-second wait elapsed without expected error; T2 `CDC_PUBLICATION_REQUIRED` appeared later. **Final extra-table timeline:** T0 catalog mutation; T1 next isolated preflight rejects exactness at 8.265 s; T2 Connect stops and the slot is inactive by 10.453 s. The other mutation timings are recorded below.

## Controller Scheduling / Fairness

`ControllerScheduler` uses a fixed four-thread pool, at most one in-flight check per pipeline and at most four submitted checks in total, a rotating start index, isolated per-thread control/Connect/Loader clients, and bounded retry delays. The main 2-second poll no longer waits for a slow source or Connect request. A transient Connect failure retries without changing desired state. A rejected 409 callback backs off. Repeated ClickHouse DDL is avoided when the persisted schema already matches. Unit tests force one blocked scope while another executes. In the live final run, one stale retired scope coexisted with a healthy scope whose pause/restart and resume/restart converged in 30.203 s and 15.937 s respectively. The pool is bounded; no new service or unbounded queue was added.

## Pause Physical-State Contract

For an active PAUSED pipeline, the controller requests Connect STOP asynchronously, then requires connector `STOPPED`, no tasks, a read-only PostgreSQL slot inspection with the expected logical plugin/database/slot identity and retained WAL status, and `active=false` before posting authoritative PAUSED. It leaves PAUSING in place while the slot is active or source observation is unavailable. The slot is never dropped. `unreserved`/`lost` fails closed as `CDC_SLOT_LOST`/RESEED_REQUIRED. The protected password file is removed after physical confirmation. A stopped retired scope can be contained without claiming active-source PAUSED; STOPPED is a separate terminal observation.

## Resume Recovery Contract

Resume retains the existing Connect offset and PostgreSQL slot. The controller performs source/role/publication/slot preflight, verifies or prepares storage when schema changes, restores the protected password file, checks generated Connect config, and uses the supported `PUT /connectors/{name}/resume` action after STOP. The action is asynchronous per [Apache Kafka Connect's documented lifecycle](https://kafka.apache.org/37/kafka-connect/user-guide/); the controller waits for a RUNNING connector/task and an existing slot before persisting applied schema/observation. On first creation, the credential-version callback no longer turns a not-yet-created slot into a false slot-loss diagnosis: the existing-slot preflight condition also requires persisted columns. Transient REST failures retry rather than STOP/PAUSE. The no-write resume probe reached a running task and active slot in 15.937 s after a controller restart; a subsequent fresh write appeared raw. The retained-write probe captured both the unique write made while paused and a separate fresh write without controller restart.

## Stale / Retired Pipeline Handling

The internal controller item now states when effective STOPPED intent differs from persisted historical intent. The controller stops that connector and removes its secret file, but suppresses an invalid state callback and waits five minutes before another terminal check. Historical pipeline and audit rows remain intact. A unit test verifies no rejected callback; a final live run confirmed one retired mismatched scope was present while healthy control converged within the original bound. Credentialless scopes follow the same fail-closed stop rule. This is terminal backoff, not deletion or an offset reset.

## Publication Drift Detection

Read-only preflight still requires exactly the selected publication table, all columns, no row filter, and insert/update/delete support. On the final source, an extra table was detected in 8.265 s and the slot became inactive by 10.453 s. Selected-table removal was detected in 16.375 s (`CDC_PUBLICATION_REQUIRED`); a row filter in 18.422 s and a column list in 19.469 s (`CDC_PUBLICATION_FILTER_UNSUPPORTED`). Each mutation was restored to the exact publication, followed by a controlled resume and a unique raw update. The local detection target remains the original **90 seconds**; it was not raised.

## Empty-Table Completion Investigation

The separate final empty source (`d2-empty-results-51582d72.json`) emitted zero raw rows while Connect and its task were RUNNING. Connect `/offsets` had a source offset, but the inspected snapshot marker was null. This is not a trusted per-generation completion signal. Query Dataset 13 remained `source_kind=cdc`, `etl_status=pending`; it was not published. Debezium documents that an initial snapshot records completion in connector offsets and exposes snapshot JMX metrics, and it supports snapshot notifications ([PostgreSQL connector](https://debezium.io/documentation/reference/3.4/connectors/postgresql.html), [notifications](https://debezium.io/documentation/reference/3.4/configuration/notification.html)). This fixture's REST offset did not expose an explicit completion marker, JMX was not wired to durable scoped state, and no notification consumer/generation binding exists. A volatile metric or RUNNING state cannot safely authorize Query publication after restart. D5 must define a durable, scope/generation-bound completion signal and coordinate it with Loader materialization and Query publication. This is Option B: safe pending behavior, with no empty-table Query-readiness claim in D2-R.

## Slot and WAL Continuity

The final nonempty source used one derived slot and one Connect offset partition throughout. Source offset LSN advanced from `213703592` to `223292448` across the recovery matrix; raw snapshot count stayed exactly 5,000, with no unexpected resnapshot. The slot remained `reserved` before, during broker outage, and after recovery. During pause it was inactive/reserved with 8,535,576 retained WAL bytes; after 100 writes it remained inactive/reserved with 8,552,080 bytes; after resume it was active/reserved. The maximum measured paused retention was below the fixture's 512 MiB cap. No slot recreation/drop, offset rewrite, source-position reset, or manual history skip occurred. Live `unreserved`/lost injection was not performed because it would require damaging the retained fixture slot; unit preflight fails closed to RESEED_REQUIRED for those states.

## Changes Implemented

Added read-only physical slot health/identity inspection; made PAUSED wait for slot inactivity; separated asynchronous STOP and RESUME observations; prevented first-start credential/slot race from asserting applied capture too early; isolated per-pipeline controller work in a bounded four-worker scheduler; changed transient Connect errors to retry without changing intent; suppressed invalid callbacks and backed off stale terminal scopes; and avoided repeated unchanged ClickHouse `prepare` work. The isolated fixture increased `max_replication_slots`/`max_wal_senders` from 10 to 20 after ten preserved historical slots exhausted the former capacity. The 512 MiB local WAL cap and acceptance timing bounds were unchanged. No new microservice was introduced.

## Fault-Injection Results

| Fault | Final observed result |
|---|---|
| Pause healthy pipeline; inspect Connect/task/slot | PASS, 19.688 s to PAUSED with inactive reserved slot; no early PAUSED callback. |
| Controller restart during PAUSING | PASS, 30.203 s to physical pause. |
| Resume with no writes while paused; controller restart during provisioning | PASS, task RUNNING and slot active in 15.937 s; fresh update raw. |
| 100 writes while paused; retained plus fresh update | PASS, unique terminal retained update raw in 7.843 s; separate fresh update raw. |
| Retired mismatched pipeline in control list | PASS, no invalid callback in unit; healthy pipeline met bounds with one live stale scope. |
| Add extra table, remove selected table, add row filter, column list | PASS, exact drift rejected within 90 s; slot inactive; restored publication/resume captured fresh raw update. |
| Connect restart; task restart; PostgreSQL outage; controller restart; broker outage | PASS at raw boundary with same slot/offset lineage. |

## Final-Pin Frozen Candidate

One final worker image ID was used by **controller, normalizer, transformer, and loader**: `sha256:1d3348cc01a718479d551700e5f7244fb70e8fd231db1212f00da2ea245ad526`. It is a local image ID, not a published release digest. Running PostgreSQL was `18.3 (Debian 18.3-1.pgdg13+1)`, image `postgres@sha256:7e32e9833a6fb1c92c32552794cb6ed569d51b445a54907d35fc112ef39684db`. Running Connect reported Debezium `3.4.3.Final`, image `quay.io/debezium/connect@sha256:4f807bd409b47268077e1142524f368db170560d5caceaee48a6a7a7fd288570`. The final nonempty source evidence ID is `6fce8542`; final empty-source evidence ID is `51582d72`. Earlier D2-R diagnostic sources and report 52 evidence are not merged into this passing candidate.

## Final Capture Matrix

| Final source `6fce8542` | Result |
|---|---|
| Fresh snapshot `r`; insert `c`; update `u`; delete `d`; tombstone; controlled snapshot/write overlap | PASS: 5,233 initial raw records, 5,000 `r`, 1 `c`, 230 `u`, 1 `d`, 1 tombstone; snapshot-last and WAL continuation observed. |
| Connect restart | PASS, fresh raw in 28.687 s. |
| Task restart | PASS, fresh raw in 7.703 s. |
| PostgreSQL outage/recovery | PASS, fresh raw in 7.484 s. |
| Controller restart while streaming | PASS, fresh raw in 7.563 s. |
| Broker outage/recovery | PASS, retained raw in 6.812 s and fresh raw in 15.297 s after broker health. |
| Physical pause, retained/fresh resume, publication variants, stale fairness | PASS with measurements above. |
| Empty table `51582d72` | SAFELY DEFERRED: zero raw rows, no trusted completion marker, pending Query Dataset. |

After recovery, the nonempty raw topic held 5,239 records and still exactly 5,000 snapshot rows. These are capture/control observations, not D3 envelope, D4 current-state, D5 publication, or D6 authorized Query correctness results.

## Security Results

The final known-secret scan checked 35,466 business records and persisted Connect configs: no known fixture password/key bytes appeared, and connector passwords were FileConfigProvider references. A separate scan compared 12 active Integration ciphertexts against the same 35,466 records and found none. The active controller credential file had mode `600`; it was removed at physical pause. Connect REST had no host-published port. Foreign-workspace CDC status returned 404. These are local fixture checks; production workload identity, Java reconnect/TLS/egress and Kafka ACL/TLS remain gated.

## D1 Regression

The focused Django lifecycle/authorization suite passed **45/45** using `service_config.sqlite_test_settings`; Query ingestion callback security passed **17/17**. The ETL CDC contract/offset/preflight/controller suite passed **54/54**. Python compilation and `git diff --check` passed. Final scoped counts: **116 passed, 0 failed, 0 skipped**. A host Django invocation with default PostgreSQL settings and a fixture-container invocation with nonmatching test migrations failed before running assertions; the corrected repository SQLite test settings passed. The first post-change capture candidate exposed a transient Connect failure path and timed out; it was fixed and is not part of this closing build. A later fresh candidate hit the historical fixture's 10-of-10 slot capacity; capacity was raised to 20 without dropping slots, and a new fresh source passed. One post-matrix secret scan hit a transient Connect REST error; its repeat passed, followed by the ciphertext scan.

## Timing Measurements

| Final-candidate control gate | Measured | Original bound |
|---|---:|---:|
| Physical pause | 19.688 s | 120 s |
| Pause with controller restart during PAUSING | 30.203 s | 120 s |
| Retained-write resume | 7.843 s | 120 s |
| No-write resume with controller restart | 15.937 s | 120 s |
| Extra-table drift detection / physical stop | 8.265 / 10.453 s | 90 s detection |
| Remove selected / row filter / column list drift detection | 16.375 / 18.422 / 19.469 s | 90 s detection |

These are local fixture measurements, not production SLAs. The 2-second nominal controller poll is now independent of each in-flight source operation; individual REST calls retain their 10-second timeout and PostgreSQL connections/statements their 5-second limits. No timeout was raised to turn a failed historical gate green.

## Files Modified

`etl-final/shared/cdc/worker.py`, `etl-final/shared/cdc/postgres.py`, `etl-final/tests/test_cdc_capture_preflight.py`, `services/query-service/integration/cdc.py`, `docker-compose.cdc-local.yml`, `scripts/verify_foundation_d_cdc.py`, `scripts/foundation_d_kafka_probe.py`, and this new report. All other pre-existing dirty-tree work was preserved. The final local evidence JSON remains in the sibling `biavora-foundation-d-validation` directory. The isolated Compose project was stopped after evidence collection; no fixture volume was removed.

## Remaining D2 Debt

No blocker from report 52 remains in the measured local D2-R matrix. The final build is not a production artifact or a remote CI result. Destructive live slot-loss/WAL-`unreserved` injection and multi-controller fencing remain unproved; preflight unit coverage fails closed, and operational reseed/fencing proof belongs to later gates. The empty-table capture/publication boundary remains intentionally pending, not a D2 pass for Query readiness.

## Deferred D3–D6

D3 owns normalized envelope, order, poison and replay acceptance. D4 owns typed ClickHouse current state and authorized Query correctness/performance. D5 owns durable empty-snapshot completion, Loader/Query publication, generation/reseed, multi-instance fencing, schema history and hosted WAL operations. D6 owns the full pinned end-to-end Query matrix, downstream broker/race budgets, A/B/C regression, remote CI, migration/role deployment and G-D closure. CAP-14 production transport, managed secrets/identities, ACL/TLS and hosted recovery evidence remains required before public CDC enablement.

## D2 Exit Decision

**D2 READY FOR D3.** This decision is limited to the final pinned local capture/control candidate and the safe pending empty-table boundary. Foundation-D remains PARTIAL; G-D remains OPEN; Production Readiness remains NO-GO. No D3 or Semantic Layer work was started, and no commit or push was made.
