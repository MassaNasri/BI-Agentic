# 51 — Foundation-D / D1 CDC domain and lifecycle review

Date: 2026-11-02 (Asia/Damascus). Scope: the existing, unstaged PostgreSQL CDC implementation, limited to its Integration control plane, Query Dataset binding/publication, authorization, migration, and focused regressions. This is local engineering evidence. Foundation-D remains **PARTIAL**, G-D remains **OPEN**, and Production Readiness remains **NO-GO**.

## Executive Status

**D1 is ready for D2 capture-layer review.** The D1 boundary now has one Integration-owned pipeline per source/schema/table, three constrained desired states, guarded commands, server-derived workspace/source authority, an exact Query Dataset binding, safe pending-record retry/compensation, and Loader-only publication. A generic ingestion callback publication bypass was closed. Stale callbacks after source disable, retirement, or credential revocation are rejected. Same-generation fencing and physical runtime recovery remain explicitly deferred to D5.

## Entry Repository State

Before editing, `git status --short --branch`, `git rev-parse HEAD`, `git diff --stat`, and `git diff --cached --stat` were recorded. Branch `foundation-c-staging` tracked `origin/foundation-c-staging`; HEAD was `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`. There were 24 modified tracked parent paths, 23 untracked first-party paths including the D0 report, and a dirty TimesFM submodule indication. The cached diff was empty. Existing Foundation-D code, reports, CI edits, canonical-document edits, and unrelated work were preserved. TimesFM was neither entered nor edited. No file was staged, committed, pushed, reset, or cleaned.

The baseline CI GREEN and Foundation A/B scoped GREEN are owner-reported/historical as in 34/43/45 and D0; this D1 run did not verify a new remote CI run. Foundation-C local closure is historical evidence in 49. The local regressions below are the new evidence for this change.

## Files Reviewed

Read both Foundation-D 50 documents first, then the D0-listed canonical 34/43/45, 22/30/31/33/20/49 and their relevant ownership/security sections. Reviewed all requested primary paths: `integration/models.py`, `migrations/0005_cdcpipeline_cdcaudit_and_more.py`, `cdc.py`, `credentials.py`, `service.py`, `views.py`, `scope.py`, `test_cdc.py`, `database/models.py`, `cdc.py`, `views.py`, `urls.py`, and `service_config/urls.py`. Supporting inspection covered `bi_platform_shared/db_ownership.py` and `cdc_contract.py`, Query serializer/resolver, generic ingestion callback security tests, Data Platform CDC worker/callback payloads, Foundation-C migration verifier, and the Foundation-D migration verifier. No CDC implementation was recreated in parallel.

## Existing D1 Implementation Found

The dirty tree already contained `CdcPipeline`, `CdcAudit`, CDC public/internal routes, Query live Dataset creation/publication, stage keys, source credentials, CDC workers, and 0005. Its major D1 gaps were that desired and observed states shared one unrestricted choice set; transitions were scattered; the Query Dataset was created inside an Integration transaction despite separate production owner connections; a controller STREAMING report could publish Query without Loader completion; an older generic ingestion status endpoint could publish a CDC Dataset; and source disable/revocation needed persisted convergence. This D1 change hardens those exact paths.

## Ownership Verification

Workspace supplies membership, roles, and authenticated workspace identity. Integration owns `DataSource`, selected tables, credential versions, source lifecycle, `CdcPipeline` intent/observations, checkpoints, and `CdcAudit`. Query owns `database.Database`, the distinct CDC Dataset, its server-derived ClickHouse current-view binding, and analytical readiness. Data Platform owns capture, normalization, transformation, Loader materialization, and stage callbacks. The Integration `dataset_id` remains a logical Query reference, not a cross-owner foreign key. No AI, Voice, Report, Visualization, or new business authority was added.

## CdcPipeline Aggregate Review

Canonical active-generation key: **source UUID + schema + table**. Source UUID identifies one workspace; `CdcPipeline.workspace_id` is checked against the source on public and internal paths. 0005 already enforces unique `(source, table_schema, table_name)` and unique `dataset_id`; those constraints were preserved and tested. A single source can have distinct table pipelines, each with a distinct live Dataset. The existing `source` FK uses `PROTECT`; the source is retired, not physically deleted. An existing pipeline with a missing, foreign-workspace, foreign-source, wrong-kind, wrong-engine, wrong-table, or nonpending orphan Dataset fails closed and is never silently rebound. A selected-table edit cannot drop a table while its pipeline remains bound. Source replacement cutover/rollback returns `CDC_SOURCE_BOUND` until a generation-safe D5 workflow exists.

## Desired vs Observed State Model

Desired state is constrained in the model and 0006 database check to `STREAMING`, `PAUSED`, `STOPPED`. Runtime observations retain the existing values `DISABLED`, `PROVISIONING`, `SNAPSHOTTING`, `STREAMING`, `PAUSING`, `PAUSED`, `DEGRADED`, `FAILED`, `STOPPING`, `STOPPED`, `RESEED_REQUIRED`; `DISABLED` is a legacy observed choice, not an intent command. Public clients cannot submit an observed state. Stage-authenticated internal callbacks alone supply observations, with a controller transition guard. `RESEED_REQUIRED` is sticky; pause, disable, source retirement, and controller reports cannot clear it. Only a future explicit reseed/generation operation may recover it.

`STREAMING` observation is runtime state, not Query readiness. `DEGRADED`/`FAILED` require inspection; `RESEED_REQUIRED` requires operator reseed. A transient DEGRADED error may acknowledge PAUSED and then resume with retained offsets; its safe error code remains until runtime reports active recovery. A capture timestamp older than 30 seconds is publicly displayed as `DEGRADED`/`CDC_CAPTURE_STALE`, but an idle source and a stalled source are not distinguishable by that timestamp alone.

## Transition Matrix

The centralized `integration/cdc_lifecycle.py:command_transition` is the command authority. Every accepted command, including idempotent repeats, records a scoped audit row.

| Command | Allowed condition | Result / repeat |
|---|---|---|
| Enable | Active PostgreSQL source, selected table, active credential; no pipeline | Create or retry the one pending Query Dataset; create pipeline with desired `STREAMING`, observed `PROVISIONING`; 202. Existing exact pipeline returns 202 without new Dataset or state reset. |
| Pause | Desired `STREAMING` | Desired `PAUSED`; observed `PAUSING`, except sticky `RESEED_REQUIRED`. Repeated PAUSED is idempotent. Checkpoints/slot metadata stay stored. |
| Resume | Active source and credential; desired `PAUSED`/`STOPPED`, observed `PAUSED`/`STOPPED` | Desired `STREAMING`, observed `PROVISIONING`; offsets are retained. Repeated STREAMING intent is idempotent. `RESEED_REQUIRED` and in-flight/invalid states return 409. |
| Disable (stop) | Existing exact pipeline | Desired `STOPPED`, observed `STOPPING`, except sticky `RESEED_REQUIRED`; repeated STOPPED is idempotent. Dataset, audit, offsets, slot state, and reconciliation are retained. Route name `disable` remains compatible; no cleanup is implied. |
| Reconcile | Desired and observed `STREAMING` | Sets `reconcile_requested`; repeated request is idempotent until controller result. Other states return 409. |
| Source disable/retire or credential revoke | Existing source with bound pipelines | Integrates STOPPED intent and scoped audit; retains Dataset. Retired/disabled source cannot resume. |

## DataSource / Pipeline / Dataset Binding

`DataSource` is the Integration connection/table authority; `CdcPipeline` is the per-table intent and observation aggregate; `Database` is Query's analytical Dataset. The live Dataset uses `source_kind="cdc"`, a distinct row from snapshots, exact workspace/source/schema/table, and a deterministic `ingestion_job_id` derived from the server-owned source UUID/schema/table. The deterministic key makes a pending Dataset after an interrupted cross-owner create recoverable on retry. A completed unbound orphan is rejected. The server rejects client-supplied connector/topic/slot/physical-table selectors and does not accept a Dataset ID on enable.

## Enable Transaction and Compensation

Order: authenticate and derive manager workspace; resolve exact source; check local CDC gate/rate limit; lock source; validate engine/state/selected table and active credential; find exact pipeline; create or find pending Query Dataset; create Integration pipeline; verify exact binding; audit; then let the Data Platform controller observe intent. The Query and Integration owner aliases are not treated as one atomic transaction. If pipeline creation fails after a newly returned Query Dataset create, compensation deletes only that still-pending, unbound Dataset. If the Query creation reply is lost, its deterministic pending row remains non-Query-ready and is reused on retry. Dataset failure occurs before any pipeline creation; a legacy pipeline with a missing Dataset is rejected rather than rebound. PostgreSQL concurrent duplicate enable returned two 202 responses for one pipeline and one pending Dataset. No destructive cleanup or automatic slot deletion is part of stop.

## Query Publication Contract

Only a scoped `load` callback carrying `snapshot_complete=true`, a nonstale checkpoint, validated columns and primary key can request publication. Integration persists the Loader checkpoint/observation first; Query then validates exact Dataset binding, STREAMING intent/observation and Loader checkpoint before setting `etl_status="completed"` and binding the server-derived current view. A failed Query publication returns an error so the Loader can retry the same checkpoint; the Dataset remains pending. `database/views.py:IngestionDatasetStatusView` now rejects `source_kind="cdc"`, closing its earlier completed-status bypass. Kafka Connect RUNNING and controller STREAMING reports cannot publish. After publication, pause/degradation does not reset Query readiness. Empty-table completion and physical proof of a fully applied snapshot remain D2/D4/D5 work.

## Public API Contract

All routes are under `/database/sources/{source_id}/cdc/`, require authenticated server-derived manager workspace, and resolve the source before the pipeline. GET status is available even after source disable/retire. POST returns 202 for accepted/idempotent commands; invalid input/state/binding returns bounded 400/404/409; disabled transport/persistence returns 503. Production CDC remains explicitly disabled.

| Route | Body | Source/state rule |
|---|---|---|
| `GET /` | None | Exact owned source; returns bounded logical status list. |
| `POST /enable/` | `schema`, `table` only | Active PostgreSQL, selected table, credential; existing exact pipeline is idempotent. |
| `POST /pause/` | `pipeline_id` only | Exact owned pipeline; transition matrix above. |
| `POST /resume/` | `pipeline_id` only | Active source and credential, safe retained state. |
| `POST /disable/` | `pipeline_id` only | Logical stop, retained artifacts; same route name for compatibility. |
| `POST /reconcile/` | `pipeline_id` only | Streaming intent and observation. |

Response fields are logical pipeline/source/Dataset IDs, selected table, desired/observed state, safe error code, heartbeat, schema version, allowlisted health and reconciliation. They exclude credential plaintext/ciphertext/references, Kafka/Connect identifiers, replication slot/publication, physical ClickHouse table, and internal callback keys. Query's Dataset serializer also strips physical destination names from public source tables.

## Internal Callback Contract

`/internal/v1/cdc/` accepts only the corresponding stage key; a public JWT is not an internal identity. Every callback supplies the exact persisted pipeline plus complete workspace/source/pipeline/Dataset/schema/table scope. Allowed fields are stage-specific: controller may report guarded observed state, schema/PK, credential version and bounded health/reconciliation; normalize may add capture time; all stages may provide bounded error/checkpoint; only load may send `snapshot_complete`. Noncontroller callbacks after source disable/retire or STOPPED intent are stale; a late controller error cannot undo STOPPED. Lower offsets cannot overwrite checkpoints; a publication request with an older offset or LSN is rejected. A full generation/epoch fence against an old worker with the **same** scope remains absent and is a D5 blocker.

## Workspace and Role Authorization

`integration/scope.py` derives the workspace and manager role from the authenticated principal. A foreign workspace source is 404; a valid workspace with a foreign source/pipeline pair is 404; viewer/analyst state changes are 403. Unknown source is a safe 404. A client cannot authorize by UUID possession alone. A tampered Query Dataset binding gives 409 and neither command nor enable repairs it. The exact scope check and stage key reject cross-scope internal writes. Production's current static stage-key transport remains disabled pending security certification.

## Audit Model

0006 adds nullable scoped `workspace_id`, `source_id`, `dataset_id`, previous/new desired and observed states, and bounded `result_code` to the existing `CdcAudit` with pipeline, actor, action, timestamp. Nullability preserves existing audit rows on migration. Accepted and idempotent commands, source disable/retire and credential revocation record safe metadata. No row images, passwords, ciphertext, tokens, connector config, or exception dumps are stored. Rejected requests return bounded codes and do not mutate or create a state-change audit row.

## Credential Lifecycle Interaction

Enable/resume require an active Integration credential. Explicit revocation now persists STOPPED intent and audit before any new controller session can be requested; source retirement similarly stops pipelines and revokes credentials. The controller GET already suppresses capture intent and credential delivery when source/credential is unavailable. Rotation leaves source/workspace identity intact and exposes only active credential version to runtime observation; full task-stop/reconnect acceptance and version fencing remain D5. No reusable credential reference is added to Kafka row events or public API.

## Migration Review

0005 was preserved byte-for-byte as possible applied history. New additive 0006 expands audit metadata, narrows desired-state choices, checks for incompatible preexisting desired values, and adds a database `cdc_desired_state_valid` constraint. The existing source/table and Dataset unique constraints remain. On fresh disposable local PostgreSQL `foundation_d_migration_d1_20261102`, the Foundation-C migration sequence and 0005/0006 forward, reverse, and reapply passed; owner source and CDC rows survived 0006 rollback/reapply and an invalid desired state was rejected. `makemigrations --check --dry-run` reported no changes. This did not run against a production database or claim runtime-role deployment certification.

## Tests Added or Modified

`integration/test_cdc.py` now covers command matrix/repeats, transient-error pause/resume, reseed stickiness, source disable/retire/revoke, replacement blocking, exact workspace/source/Dataset binding, physical-selector denial, safe audit, pending orphan retry, creation/publication failures, checkpoint monotonicity and no false Query completion. `tests/test_ingestion_callback_security.py` covers rejection of generic ingestion publication for CDC. `scripts/verify_foundation_d_migration.py` now exercises 0006; `scripts/verify_foundation_d1_concurrency.py` verifies two simultaneous enable requests against disposable PostgreSQL. Existing relevant CDC/ETL contracts remained in their original suites.

## Test Results

| Final check | Result | Limit |
|---|---|---|
| Django `integration.tests`, `integration.test_public_boundary`, `integration.test_cdc`, `database.foundation_a_integration_tests` | 45 passed, 0 failed, 0 skipped | SQLite-focused API/ORM tests. |
| Query `pytest tests` | 119 passed, 0 failed, 0 skipped | Includes generic ingestion publication guard. |
| ETL CDC contract/offset and transform/loader listener suites | 42 passed, 0 failed, 0 skipped | Unit tests, not live broker acceptance. |
| ETL security controls | 16 passed, 0 failed, 0 skipped | Local transport/security contracts. |
| Query security regression runner | 23 pytest + 26 Django passed, 0 failed | Overlaps the above suites. |
| Disposable PostgreSQL duplicate enable | 1 check passed: two 202 responses; one pipeline, one pending Dataset | Same-database test settings exercise PostgreSQL row locks; separate production owner aliases are addressed by compensation/retry logic and still require D6 deployment proof. |
| Disposable PostgreSQL migration; Django model drift; `git diff --check` | PASS / PASS / PASS | No remote CI run. |

An initial ETL collection attempt lacked the ETL `PYTHONPATH`; the corrected run passed. An initial single-alias interrupted-create test incorrectly expected a separate-transaction orphan; the corrected test verifies same-alias rollback, while a separate test verifies retry of a pending orphan. Final scoped runs above have no failures.

## Foundation A/B/C Regression Results

The 45 Django tests cover source ownership, role/workspace isolation, credentials, replacement, snapshot Dataset behavior and CDC routes. The 119 Query pytest tests cover authorized Query binding, redaction, ingestion callback and executor contracts. Query security regression (23 + 26) and ETL security (16) passed; the ETL CDC/listener set (42) passed. These are focused local regressions, not the full release matrix or a new remote CI result.

## Files Modified

| Path | D1 reason |
|---|---|
| `services/query-service/integration/models.py`; new `migrations/0006_cdcaudit_dataset_id_cdcaudit_new_desired_state_and_more.py` | Constrain intent and expand safe audit without changing 0005. |
| `services/query-service/integration/cdc.py`; new `integration/cdc_lifecycle.py`; `integration/test_cdc.py` | Central transitions, scope/callback/publication guards, compensation, D1 tests. |
| `services/query-service/integration/service.py`; `integration/views.py`; `integration/credentials.py` | Source disable/retire/revoke convergence, source response refresh, replacement guard. |
| `services/query-service/database/cdc.py`; `database/views.py`; `tests/test_ingestion_callback_security.py` | Exact Query binding, pending retry/publication rules, generic callback block and test. |
| `scripts/verify_foundation_d_migration.py`; new `scripts/verify_foundation_d1_concurrency.py` | Disposable PostgreSQL migration and duplicate-enable evidence. |
| This report | Required D1 decision and evidence. |

The listed paths that were already dirty/untracked at entry were edited in place; all other dirty work remains untouched. The zero-byte SQLite test artifact created during this run was removed after verifying its creation time, size, and workspace path.

## Open D1 Debt

No known unresolved D1 domain/lifecycle blocker remains. The cross-owner create protocol can leave an intentionally **pending, non-Query-ready** record if the Query create reply is lost; deterministic retry reuses it. A future operations job may identify abandoned pending records, but it must never infer readiness or delete an active binding. Same-scope stale worker fencing is documented below for D5. Historical audit rows from 0005 receive null new metadata rather than fabricated attribution. No live multi-owner runtime-role test or remote CI was claimed here.

## Deferred D2–D6 Work

D2: capture/deployment, Debezium pin, broker recovery and source/WAL behavior. D3: envelope, normalization, ordering and poison handling. D4: typed Loader/current-state and Query-visible correctness at scale. D5: generation/epoch fencing, explicit reseed/cutover, schema/credential runtime acceptance, empty-table completion, slot/retention and operator recovery. D6: full final-pin acceptance, 120-second recovery and 5,000-row catch-up budgets, owner-role and authorized Query end-to-end proof, complete A/B/C regression and new-change remote CI. Production identity, TLS/ACL, managed secrets, hosted WAL operations and deployment proof remain Production Readiness work. Semantic Layer and later product layers were not started.

## D1 Exit Decision

The local D1 control-plane boundary is deterministic, scoped, idempotent, migration-safe and ready for D2 review. Foundation-D overall is still PARTIAL; G-D is OPEN and production remains NO-GO.

D1 READY FOR D2
