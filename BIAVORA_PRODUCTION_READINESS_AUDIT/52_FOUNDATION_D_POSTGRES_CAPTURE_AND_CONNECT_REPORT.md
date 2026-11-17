# BIAVORA Foundation-D / D2 — PostgreSQL capture and Kafka Connect report

Evidence date: 2026-11-03 (Asia/Damascus). Local, isolated fixture only. Paths are relative to the repository root. `OBSERVED` denotes this run; earlier results in report 50 remain historical. No commit or push was made.

## Executive Status

**D2 BLOCKED.** The final pinned PostgreSQL 18.3 → Debezium 3.4.3.Final → Kafka Connect → scoped raw Kafka path captured a fresh 5,000-row snapshot, concurrent writes, `r/c/u/d`, a null tombstone, and post-snapshot WAL changes. Connect, task, PostgreSQL, controller, and broker restart/outage probes captured fresh raw writes without an offset reset or unexpected resnapshot. The broker-health-to-fresh-raw measurement was 22.25 seconds. However, two live pause attempts exceeded 120 seconds before the PostgreSQL slot was observed inactive, a retained-write resume probe exceeded its 120-second raw-event wait and recovered only after a controller restart, and publication drift was reported only after its 90-second probe timed out. These are D2 capture-control failures, not downstream Query latency. Foundation-D remains PARTIAL, G-D remains OPEN, and production remains NO-GO.

## Entry Repository State

Before changes, `git status --short --branch`, `git rev-parse HEAD`, `git diff --stat`, and `git diff --cached --stat` were recorded. Branch `foundation-c-staging` tracked `origin/foundation-c-staging`; HEAD was `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`. The parent tree had 28 modified tracked paths, untracked D0/D1 and partial D2–D6 implementation, and a dirty `services/ai-service/forecasting/timesfm` submodule indication. The cached diff was empty. No reset, clean, stage, commit, push, or TimesFM traversal/edit occurred. Existing fixture volumes and offsets were retained.

## D2 Scope and Non-Goals

D2 inspected and tested PostgreSQL preflight, exact publication and slot policy, server-generated Debezium configuration, protected local credential delivery, Connect control, raw topic scope, snapshot/WAL capture, and focused recovery. It ends at raw Kafka. D3 owns normalized ChangeEnvelope and poison semantics; D4 owns ClickHouse current state; D5 owns generation/reseed, mature pause/slot operations and lifecycle recovery; D6 owns complete G-D and authorized Query acceptance. Neither the historical 120-second full-Query broker failure nor 300-second 5,000-row Query catch-up failure was reinterpreted as a D2 pass.

## Files Reviewed and Modified

Read the three required Foundation-D reports in order, then canonical 34/43/45, 22/30/31/33/20/49. Inspected `etl-final/shared/cdc/{connect,postgres,worker,schema}.py`, `bi_platform_shared/cdc_contract.py`, `docker-compose.cdc-local.yml`, both existing CDC scripts, D1 Integration CDC/credential/model/lifecycle boundaries, and relevant tests.

| D2-edited path | Reason |
|---|---|
| `etl-final/shared/cdc/connect.py` | Unique atomic credential-file replacement, restrictive mode, stale-file removal and existence check. |
| `etl-final/shared/cdc/postgres.py` | Reject wrong slot type/plugin/database, absent LSN, and `unreserved`/`lost` WAL status. |
| `etl-final/shared/cdc/worker.py` | Contain one pipeline's control failure, preserve sticky reseed, avoid repeat STOP/callback on already stopped pipelines, restore missing secret file before resume, and check task absence separately. |
| `etl-final/tests/test_cdc_contract.py`; new `etl-final/tests/test_cdc_capture_preflight.py` | Secret-file lifecycle, slot/publication/preflight and controller isolation checks. |
| `scripts/verify_foundation_d_cdc.py`; `scripts/foundation_d_kafka_probe.py` | Reuse the existing harness for fresh raw/empty/recovery/WAL/publication probes and bounded secret/ciphertext checks. |
| This report | D2 evidence and decision. |

No D1 model, migration, public API, Compose pin, or canonical status file was changed in D2.

## Final Runtime Version Verification

`docker inspect` of the *running* isolated containers agreed with Compose, rather than relying on report 50:

| Component | Actual version / image digest |
|---|---|
| PostgreSQL | `18.3 (Debian 18.3-1.pgdg13+1)`; `sha256:7e32e9833a6fb1c92c32552794cb6ed569d51b445a54907d35fc112ef39684db` |
| Debezium Connect | Connector status `3.4.3.Final`; `sha256:4f807bd409b47268077e1142524f368db170560d5caceaee48a6a7a7fd288570` |
| Kafka | `7.5.0-ccs`; `sha256:fbbb6fa11b258a88b83f54d4f0bddfcffbf2279f99d66a843486e3da7bdfbf41` |
| ZooKeeper | Confluent 7.5.0 fixture pin; `sha256:02f6c042bb9a7844382fc4cedc513a44585d8a5acae873fb9e510e3ca9dcabc6` |
| ClickHouse | Client `26.2.3.2`; `sha256:0b2d7824347397b2ba6fcb216f0ae772568105f1f47e19f0d3247e24c79bc10a` |
| Data Platform worker | Running Python `3.11.15`; base `python:3.11-slim@sha256:233de06753d30d120b1a3ce359d8d3be8bda78524cd8f520c99883bfe33964cf`; final local controller build `sha256:66c2b60709de3c85216ebd1a64f617280a7c3b9c0c44a8bc907ab5c1dfe0ceaa` |

The local worker build is not a published immutable release artifact. Dependencies were not upgraded.

## PostgreSQL Logical Replication Preflight

Live source `source_d2_2cecf19c` reported `wal_level=logical`, ten configured replication slots, ten WAL senders and `max_slot_wal_keep_size=512MB`. `public.orders` was an ordinary relation (`relkind=r`), `REPLICA IDENTITY FULL` (`f`), no RLS, and had one primary key. The preflight also checks PostgreSQL 15–18, the selected table's SELECT grant, exact publication table/columns and no row filter, capacity, and supported schema types. It is read-only; fixture setup, not BIAVORA runtime, created the role/table/publication and set WAL/replica identity. Unit negatives covered wrong WAL level, superuser role, wrong replica identity, RLS and publication extra-table drift. Unsupported states fail with bounded `CDC_*` codes.

## Replication User and Privilege Model

The fixture administrator created `cdc_d2_2cecf19c` with LOGIN/REPLICATION, NOSUPERUSER, NOCREATEDB and NOCREATEROLE, then granted schema USAGE and SELECT on `public.orders`. Live checks returned `rolreplication=true`, `rolsuper=false`, selected-table SELECT=true and extra-table SELECT=false. A customer/operator must supply a supported source, logical WAL capacity, an appropriately privileged replication user and the exact publication. BIAVORA runtime only validates and runs the connector. The public client chooses a persisted selected table through the D1 API; it cannot submit SQL, role grants, publication name or Connect config. A single fixture role does not certify every external customer's grant graph.

## Publication Policy

The physical publication is `b_<trusted Scope token>`, derived from workspace/source/pipeline/Dataset/schema/table, with `publication.autocreate.mode=disabled`. Live `pg_publication_tables` returned exactly `public|orders` after fixture restoration. Preflight rejects all-table publications, missing operation flags, added tables, column-list drift and row filters. The live drift probe added `public.extra` under administrator authority and later observed `CDC_PUBLICATION_REQUIRED`/PAUSED, but **not within its 90-second wait**; the extra table was removed from the publication after the timeout. This proves eventual rejection, not bounded control. The final publication again listed only `public.orders`. The extra fixture table remains outside the publication.

## Replication Slot Policy

The slot is `b_<trusted Scope token>` and persists on STOP (`slot.drop.on.stop=false`). Preflight now rejects a physical slot, wrong plugin, wrong database, temporary slot, null restart/confirmed position, and `unreserved`/`lost` WAL. A previously applied pipeline with a missing slot receives `CDC_SLOT_LOST`, which D1 maps to sticky `RESEED_REQUIRED`; no slot or LSN was recreated or moved manually. Connect owns the source offset. In the passing restart sequence, the Connect source offset advanced from LSN `128958752` to `154668528`, and raw snapshot count stayed 5,000. A first-start race between persisted credential version and slot creation still needs a focused fault injection; no offset/slot-loss drill was used to claim reseed recovery.

## Debezium Connector Configuration

`connect.py:configuration` fixes PostgresConnector, `pgoutput`, one task, host/port/database/user from the persisted Integration source, provider-based password, derived publication/slot/topic, escaped exact table include, initial snapshot, transaction metadata, five-second heartbeat, tombstones, decimal strings, microsecond temporal precision, no error tolerance, no skipped operations, retained slot, connector LSN flush and `offset.mismatch.strategy=no_validation`. Key/value JSON converters disable schemas. Controller compares persisted Connect config with the generated map and stops/reconfigures/resumes on drift without offset deletion. Public CDC enable accepts only schema/table; no Connect REST passthrough or raw connector options were found. Fixed config does not itself prove that a RUNNING task has emitted the expected raw change.

## Credential Delivery Review

Integration provides active ciphertext only to the authenticated controller stage while streaming. Controller decrypts in memory and atomically replaces a per-scope Java properties file; the Connect config contains `${file:/run/cdc-secrets/<token>.properties:password}`. Live mode was `600` on a streaming empty-source file; the directory is restricted to `700` by code/init, and Connect mounts the volume read-only. The file was absent after a stopped D2 pipeline. Resume rewrites a missing file before Connect RESUME. The new unit test covers rotation replacement and cleanup without a fixed shared temporary filename. The local file provider is **not** production managed-secret proof.

## Kafka Connect Control Boundary

Connect REST has no host-published port (`docker port` returned no mapping). The controller is the only BIAVORA code path inspected that writes connector config; names are server-derived. `ConnectClient` uses private configured REST, bounded ten-second requests, no redirects and safe error codes. Connector and task status are inspected separately; an absent task under RUNNING is now rejected. A stale retired fixture pipeline produced repeated 409 control reports, and live pause/restart timing remained unbounded despite per-pipeline exception containment. A STOPPED connector with no tasks was observed while its PostgreSQL slot stayed active until later. Thus Connect status is not accepted as proof of slot release or raw capture correctness.

## Raw Topic Scope

`Scope.token` hashes trusted workspace/source/pipeline/Dataset/schema/table state; `raw_topic` appends only the validated schema/table. Connect `topic.prefix`, connector name, publication and slot derive from that scope. The public API does not accept a physical topic. A foreign workspace live status request returned 404; focused D1 scope tests passed. The local broker has one partition, 24-hour/512-MiB business-topic retention and separate Connect config/offset/status topics. Production ACL/TLS isolation remains CAP-14 work.

## Raw Debezium Event Evidence

The fresh final-pin source produced **5,467 raw records**: 5,000 `r`, one `c`, 464 `u`, one `d`, and one null Kafka tombstone. The probe checked schema/table and LSN in non-null raw events, a final snapshot row, streaming operation metadata, and absence of known fixture secrets. After the recovery sequence the topic held 5,473 records, still exactly 5,000 snapshot rows. This is raw boundary evidence; it does not judge D3 envelope or D4 current-state results.

## Snapshot-to-Stream Capture Evidence

The harness created a new PostgreSQL table with 5,000 rows and a new persisted source/pipeline/Dataset scope. A controlled 20-second writer updated row 2500 during Debezium's initial snapshot, then inserted row 5001, updated row 2 and deleted row 1. Raw snapshot timestamps overlapped the measured writer interval, and `c/u/d` arrived as WAL events after the `snapshot=last` record. No synthetic wall-clock handoff, connector recreation, offset manipulation or second capture manager was used. The first two fresh probes timed out because retained stale pipelines blocked the old controller loop; their evidence was preserved. Per-pipeline error containment enabled the subsequent passing fresh run.

## Empty-Table Capture Findings

A separate fresh empty selected table emitted **zero raw records** after 20 seconds. Connect and its task were RUNNING, and Connect `/offsets` returned an LSN/transaction/timestamp offset (`lsn=143321504`) with **no `snapshot` field or explicit completion marker**. These observations do not distinguish completed empty snapshot from a connector that has not yet produced a row with sufficient authority to publish Query. No Query Dataset was automatically published. An explicit trusted completion observation and Loader coordination remain D5 work; D2 makes no empty-table readiness claim.

## Connector / Task Restart Results

With the retained slot and offset, a Connect worker restart captured a fresh row-2 update in 5.844 seconds from source write through acceptance-container raw observation. A task-0 REST restart captured another in 7.625 seconds. Controller restart captured a fresh update in 6.156 seconds. These durations include probe startup; the raw probe itself observed matching events in 0.10–0.15 seconds once running. No unexpected initial resnapshot appeared. The controller was later restarted during diagnosis of the separate paused-slot timeout; that later restart cannot turn that failed bounded pause/resume case into a pass.

## PostgreSQL Outage and Recovery

After a temporary PostgreSQL container stop/start, the source reconnected and a fresh update appeared in raw Kafka in 10.844 seconds from write to observed raw event. Connect status during the outage still listed a RUNNING task; this was **not** counted as source availability or capture success. The matching post-recovery raw LSN was `154613800`. No offset reset occurred.

## Kafka Broker Recovery Investigation

During a broker stop, the source accepted update `9105` while its logical slot remained `reserved`. After Kafka health returned, Connect connector/task reported RUNNING at 0.359 seconds, the retained outage write was observed raw at 12.25 seconds, and a fresh post-restore write was observed raw at **22.25 seconds**. Slot WAL status remained `reserved`, Connect offsets advanced, and no Connect restart was used to manufacture the pass. The historical full Query 120-second broker test in report 50 remains failed; D2's measurement excludes Transformer, Loader and Query. The later paused-slot control failure is distinct from this broker-to-raw measurement.

## WAL / Slot Retention Evidence

The local source cap is 512 MiB and the code's warning threshold is 256 MiB; these are fixture settings, not a production SLA. In the passing restart sequence the slot was active/reserved with 26,238,512 retained WAL bytes before, 16,960 during broker interruption and 27,496 after recovery. During a later pause timeout, PostgreSQL still showed an active slot after Connect had reported STOPPED; it eventually became inactive/reserved with 2,391,720 retained bytes, later 3,524,544. One hundred controlled updates were accepted while paused and the terminal update `9299` eventually appeared in raw Kafka after controller restart. The 120-second pause/resume acceptance failed, so this is **not** a bounded WAL-pressure pass. No `unreserved`/`lost` slot or cap breach was observed; slot-loss behavior is enforced by unit preflight and remains to be drilled live.

## Final-Pin Capture Matrix

| Final 3.4.3.Final local check | Result |
|---|---|
| Nonempty snapshot; raw `r/c/u/d`; tombstone; controlled write overlap; subsequent WAL | PASS, 5,467 raw records and exact operation counts above |
| Connect restart; task restart; PostgreSQL outage; controller restart | PASS at raw boundary, fresh LSNs and no resnapshot |
| Broker interruption to fresh raw event | PASS, 22.25 seconds from broker healthy |
| Exact publication/role/table preflight | PASS static/unit and live initial state; live drift error observed only after 90-second timeout |
| Protected credential reference, known secret and active ciphertext scan | PASS in tested local fixture |
| Offset and slot continuity through the passing recovery sequence | PASS; LSN advanced, reserved slot retained, no manual manipulation |
| Empty-table trustworthy publication completion | UNRESOLVED; no raw row or explicit marker |
| Paused-slot inactive state and retained-write resume within 120 seconds | FAIL twice / FAIL once respectively |
| Bounded publication-drift control response | FAIL at 90 seconds; eventual `CDC_PUBLICATION_REQUIRED` observed |

## Security and Secret-Leakage Tests

The existing secret probe scanned 16,717 scoped fixture business records and persisted connector configs. It found provider references only and none of the known source/rotated passwords, credential key or stage key bytes. A controller-identity probe compared one active Integration ciphertext against the same 16,717 Kafka records and found no match. The fresh raw capture probe independently checked fixture secrets in its own topic and connector config. These checks use known fixture values, not arbitrary business-row classification. Live file mode was `600`; stopped-scope file removal was observed; no Connect host port existed. D1 tests cover public option denial, internal stage authentication, exact source/Dataset binding and foreign workspace denial; live foreign-workspace status returned 404. Production managed-secret, Java reconnect/DNS, ACL/TLS and workload-identity controls remain unproven and disabled.

## D1 Regression Results

The focused Django run passed **45/45** covering Integration CDC lifecycle/idempotency, workspace authorization, source/Dataset binding and Foundation-A Dataset paths. Query ingestion callback security passed **17/17**, including generic CDC publication rejection. These tests preserve D1's sticky `RESEED_REQUIRED` and Loader-only Query publication rules. They do not excuse the live stale-retired-pipeline 409 loop or the bounded pause failure found below D1.

## Test Results

| Check | Passed | Failed / limit |
|---|---:|---|
| ETL CDC contract/offset/new capture-preflight unit tests | 49 | 0 |
| D1 focused Django tests | 45 | 0 |
| Query ingestion callback security | 17 | 0 |
| Python syntax; isolated Compose configuration | PASS | 0 |
| Fresh final-pin raw capture and recovery sequence | PASS | Two earlier fresh-source attempts timed out before controller isolation fix; retained. |
| Empty source | Observation recorded | Completion signal absent; not a readiness pass. |
| Paused slot/WAL combined phase | 0 | Two 120-second inactive-slot waits timed out; one 120-second resumed-raw wait timed out. |
| Publication drift | Eventual safe error | 90-second expected-error wait timed out; publication restored. |
| Secret and ciphertext probes | PASS | Known fixture values only. |

The initial Django test invocation lacked root `PYTHONPATH`; the corrected command passed. The first secret probe assumed every retained pipeline had a raw topic; the corrected probe scanned all scopes and passed. The final controller stop-loop patch was unit-tested and rebuilt, but the full passing capture/restart matrix was not rerun after that patch because the subsequent bounded lifecycle probes failed. No remote CI run is claimed.

Machine-readable local evidence is retained outside the repository in the sibling `biavora-foundation-d-validation` directory: `d2-capture-results-e7b7188a.json`, `d2-empty-results-6b1e766f.json`, and `d2-recovery-results-e7b7188a.json`, with matching scope-state files. The failed WAL/publication phases have console trace evidence above and no fabricated result JSON. `git diff --check` passed, the cached diff remained empty, and HEAD stayed `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`.
The isolated `biavora_foundation_d` Compose project was stopped after evidence collection without removing volumes, Kafka offsets, PostgreSQL slots or sibling evidence files.

## Performance / Recovery Measurements

Raw recovery write-to-observation: Connect restart 5.844 s; task restart 7.625 s; PostgreSQL outage 10.844 s; controller restart 6.156 s. Broker restored → task healthy 0.359 s; broker restored → retained outage write raw 12.25 s; broker restored → fresh write raw 22.25 s. These measurements include container/probe startup where noted and are local observations, not production SLAs. Pause-to-inactive-slot and pause/resume-to-raw exceeded the 120-second test budget; publication drift exceeded 90 seconds. No 5,000-row downstream Query catch-up measurement was attempted in D2.

## Open D2 Debt

1. A STOPPED connector/no-task observation preceded actual PostgreSQL slot release; two PAUSED/inactive-slot checks exceeded 120 seconds. Persisted `PAUSED` can be ahead of physical slot inactivity. Define and enforce an explicit bounded slot-release observation before asserting capture has stopped.
2. A retained-write resume timed out at 120 seconds with Connect still STOPPED; raw capture eventually resumed after controller restart. Diagnose the controller/Connect control path and prove bounded automatic recovery without operator restart.
3. Exact publication drift eventually emitted `CDC_PUBLICATION_REQUIRED`, but later than 90 seconds. Bound control polling/retry across retained stale pipelines and ensure drift status does not wait behind unrelated scope failures. A historical retired fixture pipeline still produces repeated 409 reports despite per-pipeline containment.
4. Fault-inject initial slot creation versus persisted credential-version callback and live slot-loss/`unreserved` WAL behavior; avoid both premature reseed and silent source-history skipping.
5. Rerun the final capture matrix after closing these defects on one frozen worker build, with an approved bound and evidence IDs. The last controller patch currently has focused unit/live failure evidence, not a complete passing final candidate.

## Deferred D3–D6 Work

D3: normalized envelope, ordering and poison acceptance. D4: typed ClickHouse current state and authorized Query correctness/performance. D5: explicit empty-snapshot completion and Loader publication, generation/reseed, multi-instance controller fencing, bounded pause/slot operations, schema history and hosted WAL monitoring. D6: entire pinned end-to-end matrix, downstream 120-second Query broker recovery and 300-second race budget, A/B/C regression, remote CI, migration/owner-role acceptance and G-D closure. No downstream outcome was inferred from raw Kafka alone.

## Production-Readiness Deferred Evidence

Production CDC remains disabled by Integration and worker/Connect transport gates. CAP-14 still requires Java/JDBC hostile DNS and reconnect protection, real public PostgreSQL TLS verify-full, managed KMS/secrets and workload identities, Kafka ACL/TLS, separate ClickHouse identities, hosted slot/WAL operations, backup/restore, staging deployment, immutable build evidence and operational cutover/rollback. The local FileConfigProvider and admin-created fixture publication are not certification for those requirements.

## D2 Exit Decision

The PostgreSQL-to-raw-Kafka path is correct for the demonstrated fresh snapshot, CRUD/tombstone and restart/broker scenarios. The repeated unbounded pause/slot and delayed publication-control observations prevent a deterministic, restart-safe capture-control acceptance on the final candidate. Foundation-D remains PARTIAL and production enablement remains DISABLED.

D2 BLOCKED
