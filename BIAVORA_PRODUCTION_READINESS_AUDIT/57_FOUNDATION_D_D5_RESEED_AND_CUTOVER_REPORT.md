# BIAVORA Foundation-D / D5-R1 — Candidate generation, reseed and Query cutover

Date: 2026-11-07 (Asia/Damascus). Evidence scope: this dirty, unstaged repository and the retained isolated `biavora_foundation_d` Compose project. **D5-R1 READY FOR D5-R2.** Foundation-D remains PARTIAL, G-D remains OPEN and Production Readiness remains NO-GO. The final watermark reconciliation certificate is not implemented; no production cutover is enabled.

## Executive Status

An authenticated, operator-authorized reseed now creates one server-numbered candidate on the existing `CdcGeneration` model. Candidate capture uses a fresh Debezium slot/connector/topic/ClickHouse lineage, while the single Query Dataset retains its old binding. A guarded local certificate can take that binding to the candidate D4 current view. Integration records a durable intent before the Query compare-and-swap and uses the Query generation stamp to recover after a crash. The real legacy ReplacingMergeTree fixture reached generation 2, exact authorized Query output and generation 1 SUPERSEDED. D5-R2 must replace the local certificate with a source/Loader/Query watermark proof before production semantics are complete.

## Entry Repository State

Before editing: `foundation-c-staging...origin/foundation-c-staging`, HEAD `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`; cached diff empty. `git status --short --branch` showed the pre-existing modified canonical/release/Query files, untracked Foundation-D reports 50–56 and CDC implementation, and the dirty TimesFM submodule indication. The tracked diff stat showed 30 paths, 348 insertions and 50 deletions, excluding untracked D work. No reset, clean, stage, commit or push was performed. Reports 50–56 and TimesFM were not edited. Retained fixture volumes, slots and earlier evidence were not removed.

## D5-R1 Scope

Implemented the candidate/reseed/validation/Query cutover/supersede path, a recoverable cross-owner protocol, candidate abort, logical orphan classification, and a controller physical-effect fence. No D6 work was started. The final D5-R2 watermark reconciliation algorithm, large-source certification, hosted transport and retention/cleanup policy remain separate work.

## Existing D5 Baseline

The existing generation-1 identity, epoch callback fence, database controller lease, ordered durable empty-snapshot notification, zero-row Query publication and immediate INSERT continuity were retained. Generation 1 still uses its prior physical token and `ChangeEnvelope.v1`; no prior offset was advanced or rewritten.

## Generation Lifecycle

`CdcGeneration` retains ACTIVE, CANDIDATE, SUPERSEDED, FAILED and RESEED_REQUIRED. Partial unique database constraints permit at most one ACTIVE and one CANDIDATE per pipeline. The pipeline row lock serializes transitions. A reseed-required generation can remain the old Query authority until the candidate is bound. Aborting a candidate marks it FAILED and leaves the old generation authoritative; a later authorized attempt gets the next unused server number. A successful cutover marks the old generation SUPERSEDED permanently.

## Candidate Persistence

Migration `integration.0010` adds the uniqueness constraints, certificate, cutover phase and creation/ready/binding/failure timestamps to the existing generation table. Candidate number, predecessor and scope are derived under the locked Integration source/pipeline rows. The pipeline's runtime projection advances to the candidate and resets checkpoint, schema, snapshot, credential and health observations. The old generation record retains its catalog/checkpoints and physical lineage. Migration `database.0007` adds the Query Dataset generation stamp and backfills existing completed CDC bindings as generation 1.

## Reseed Authorization

The public logical `reseed/` and `abort/` actions require the existing authenticated manager/workspace check plus a separate server secret `CDC_RESEED_OPERATOR_KEY` and exact intent. Reseed accepts only an allowlisted reason; extra fields, cross-workspace requests and analyst/viewer roles fail. No caller supplies generation, slot, connector, Kafka topic, ClickHouse name, Dataset binding or LSN. The route remains behind `CDC_ENABLED=1` and the existing production transport refusal. Cutover and local certification are internal functions, with no public force flag.

## Reseed Idempotency

The locked source/pipeline and single-candidate database constraint return the existing candidate on repeated requests. A live two-request race and response-loss retry yielded one candidate generation, one Dataset and one new PostgreSQL slot. The candidate is reused while provisioning. The fixture evidence is `../biavora-foundation-d-validation/d5-r1-results-d995ab82.json`.

## Physical Generation Isolation

Generation 2 derives a distinct scope token: raw/normalized/transformed/DLQ/notification topics, consumer groups, Connect name, PostgreSQL slot, password file, ClickHouse versions/current objects and stage checkpoints are separate. The exact generation-1 publication is shared as a table selection, not an offset lineage; preflight still requires its exact table and safe publication properties. Old and new slots were both present after legacy cutover. Old events cannot validate against `ChangeEnvelope.v2`, and old callbacks cannot update the pipeline projection. No old offset/slot reset or legacy in-place DDL was used.

## Generation-Aware Event Scope

The shared contract preserves generation-1 `ChangeEnvelope.v1` bytes and topic token. Generation greater than 1 includes its number in event identity and uses the existing v2 decoder expectation. Focused contract tests reject v1 replay under a generation-2 consumer and v2 replay under generation 1. The candidate's event ID differs for an otherwise identical source record.

## Old-Worker Physical Fencing

At candidate build, the current controller first stops the old connector using its candidate authority before provisioning the new connector. Physical names prevent old workers from addressing candidate topics, slot or storage. The controller now verifies its database lease/fence immediately before and after Connect stop/configure/resume, password-file writes/removal and Loader storage preparation. It rewrites the protected candidate password file on subsequent polls to repair a late in-flight stale writer. An external REST or file operation already in flight between checks cannot be made transactional with Integration; the after-check rejects stale logical authority and the next controller reconciles the desired physical configuration.

## Multi-Controller Physical Fencing

Two owner UUIDs were exercised against the actual Integration lease. A's expired fence was rejected by `verify`; its guarded Connect stop was denied before REST. B acquired a higher fence and performed actual private Connect stop and resume. Evidence: `../biavora-foundation-d-validation/d5-r1-fence-results-4635912b.json`. Focused tests also cover takeover, stale callback denial and the guarded Connect call. The residual already-in-flight external-effect race is handled by the separate physical names, post-effect verification and B's reconciliation, not represented as distributed ACID.

## Candidate Dataset Strategy

The candidate uses internal physical storage outside the existing logical Query Dataset binding (strategy B). It creates no duplicate Dataset row. The one Query Dataset remains bound to generation N until a successful compare-and-swap. The authenticated status exposes the control `generation` and separate `query_generation`; public clients cannot select the candidate physical view through the Dataset authorization boundary.

## Candidate Capture

The candidate uses Debezium `snapshot.mode=initial`, a fresh server-derived slot and connector, the shared exact table publication, generation-specific Kafka scope, D4 MergeTree versions table and ranked business-only current view. The observed controller stops old capture before candidate setup; Query can show a frozen prior state during candidate construction. Candidate normalization/Loader checkpoints and empty notification belong to generation 2. The old Query view stays readable until binding changes.

## Legacy Storage Detection

The isolated source was seeded with a real `ReplacingMergeTree(_cdc_version)` versions table before starting its controller. Loader detected `CDC_STORAGE_INCOMPATIBLE`, paused capture and persisted `RESEED_REQUIRED`. No in-place conversion was attempted.

## Legacy ReplacingMergeTree Recovery

An authorized `legacy_storage` reseed created generation 2. A fresh snapshot and WAL lineage produced a separate D4 `MergeTree` table and ranked current view. The limited local exact validator confirmed source/current equality, then internal cutover bound Query to generation 2. Authorized Query returned exact source rows; generation 1 became SUPERSEDED. Both old ReplacingMergeTree and old slot remained intact. The checked retained result is `../biavora-foundation-d-validation/d5-r1-results-bdc08b9a.json`.

## Candidate Validation Contract

Cutover requires the exact candidate/predecessor, active source and credential before a new bind, streaming healthy capture, trusted completed snapshot signal, Loader checkpoint or durable zero-row completion, candidate catalog/PK, no sticky error, D4 MergeTree/ranked view and business-only schema, and a persisted certificate tied to generation, scope, schema version and Loader checkpoint. `local_exact_v1` is issuable only in `APP_ENV=test` or explicitly limited development fixture mode. The acceptance driver compares exact source and candidate rows before issuance. A production-mode test proves that the local certificate is refused even if the local flag is set. `_certificate_valid` has an explicit unimplemented `watermark_reconciliation.v1` branch: D5-R2 must add the real issuer and verifier; this report does not claim a final reconciliation pass.

## Query Cutover Protocol

The internal cutover locks Integration pipeline/candidate/old rows, validates the certificate and records durable PENDING. Query then compares its workspace/source/Dataset/generation/old server-derived view and atomically stamps the candidate generation, candidate server-derived current view, business schema and `etl_status=completed`. Integration next records QUERY_BOUND, old SUPERSEDED and candidate ACTIVE/COMPLETE with safe audit entries. The Query Dataset is the single analytical authority. The Query update is a separate owner write and is never described as one physical transaction with Integration.

## Cross-Owner Cutover Recovery

On the controller's first poll after restart, pending phases are retried. Recovery reads the actual Query stamp/view. If Query still points to old, it retries the guarded compare-and-swap; if already bound to the candidate, it verifies the D4 view and finalizes Integration without rebinding backward. A completed cutover is idempotent. If a source retires after Query was bound, recovery finalizes the observed Query authority while capture remains stopped. A one-time partially published local Dataset discovered during development was repaired only after checking exact active generation/view and D4 publication prerequisites.

## Failure Before Query Binding

Injected after PENDING persistence and before Query write. The old Query view remained readable and the same candidate was returned on reseed retry. No new generation or Dataset appeared. The live crash fixture then proceeded to the post-bind fault. Evidence: `../biavora-foundation-d-validation/d5-r1-results-daa28fac.json`.

## Failure After Query Binding

Injected after Query's generation-2 write and before Integration final bookkeeping. A real controller restart recovered the persisted phase, finalized generation 2 ACTIVE and generation 1 SUPERSEDED, and authorized Query returned the expected rows. No backward Query rebind occurred. Evidence: `../biavora-foundation-d-validation/d5-r1-results-daa28fac.json`.

## Candidate Abort

Before cutover, abort marks the candidate FAILED, stops candidate intent, invalidates the controller lease and retains resources/evidence. Repeated abort is idempotent. Live concurrent/abort evidence shows the prior Query view remained readable. There is no automatic slot/topic/table deletion.

## Superseded Generation Rules

The old lineage is retained as SUPERSEDED. Its controller, Normalizer, Transformer and Loader callbacks are rejected by generation/epoch comparison and the state gate. Old v1 Kafka records fail generation-2 contract validation. Old physical names cannot address candidate resources. Resume uses only the current generation and cannot promote a superseded one.

## Credential Revocation During Reseed

Focused tests revoke the active credential during candidate provisioning and after candidate readiness. Internal controller polling returns STOPPED without credential material; certification and a new Query binding fail. Old-credential callbacks remain epoch-fenced. A new capture session cannot receive revoked ciphertext from Integration. A fresh live revocation race was not run in this D5-R1 fixture.

## Source Retirement During Reseed

Focused tests retire the source while candidate work exists and after readiness. Internal polling returns STOPPED, local validation/new cutover fails, and the old Query Dataset retains its historical binding. A separate post-bind recovery test proves retirement after Query has already moved does not leave ambiguous Integration authority. A fresh live retirement race was not run.

## Schema-Incompatible Reseed

A focused fail-closed scenario sets generation 1 to `RESEED_REQUIRED` for `CDC_SCHEMA_INCOMPATIBLE`, then authorizes a candidate with a fresh catalog/PK, completes local validation and binds the new business schema. Old retained events remain scoped to generation 1. The final live DDL/approval matrix remains a D5-R2 integration follow-up, not claimed here.

## Empty Candidate Generation

The isolated empty source produced a generation-2 ordered durable zero-row completion, D4 empty current view and authorized zero-row Query binding. A subsequent real source INSERT appeared through generation 2. The first diagnostic attempt exposed that an empty candidate with an old completed Query Dataset could stay SNAPSHOTTING; the candidate-only transition and durable-signal recovery were fixed and the same retained candidate completed. Evidence: `../biavora-foundation-d-validation/d5-r1-results-c053e712.json`.

## Empty Snapshot Boundary-Overlap Findings

The immediate post-snapshot INSERT passed. A transaction deliberately held across the Debezium snapshot-completion boundary was not executed. **DEFERRED**; D5-R2 must observe its event path and include it in the final watermark certificate. No overlap PASS is claimed.

## Candidate Orphan Detection

Authenticated status classifies a missing Query Dataset, missing current generation, misplaced/multiple candidate, Query bound to a non-active generation, Query-bound PENDING phase and pending active Dataset. It distinguishes `recoverable_retry` from `manual_operator_review`; the guarded active-publication repair rechecks generation/view and D4 storage. No automatic physical deletion occurs. Connector/slot/storage inventory outside the Integration catalog still needs a full operator inventory scanner and retention decision; retained aborted/superseded resources are intentional, not silently cleaned.

## Resource Retention

Old connector definitions, slots, Kafka topics, versions/current objects, generation rows, Dataset metadata and audits remain retained after cutover. Candidate failure likewise retains evidence. Cleanup policy and eventual deletion authorization are deferred to D6/Production Readiness; none was exercised here.

## Audit

Integration audit rows record actor, workspace/source/pipeline/Dataset, reseed/abort/validate/cutover/repair action and bounded result code. Generation rows record predecessor, reason, ready/attempt/bound/superseded/failure timestamps, phase and certificate metadata. No credential, customer row or physical identifier is added to public audit output.

## API / Operator Contract

`POST /database/sources/{source_id}/cdc/reseed/` requires manager, operator key, `pipeline_id`, exact intent and reason. `POST .../abort/` requires the same authority and abort intent. `GET .../status/` reports logical generations/repair classification. Cutover/certificate issuance stays internal. No endpoint accepts physical resource names or `force_cutover=true`. The runbook documents the local fixture and recovery protocol.

## Live Legacy-Recovery Acceptance

**PASS:** actual ReplacingMergeTree generation 1 → `CDC_STORAGE_INCOMPATIBLE` → `RESEED_REQUIRED` → authorized generation-2 CANDIDATE → fresh snapshot/WAL → separate MergeTree/current view → local exact comparison → Query generation-2 binding → old SUPERSEDED. The second corrected run reached authorized Query. A retained verification independently checked both engines, both slots, lineage and exact Query rows (`d5-r1-results-bdc08b9a.json`). The initial diagnostic cutover exposed a missing `etl_status=completed` write; it was fixed and its partial local Dataset was guardedly repaired, not counted as the corrected-run PASS.

## Fault-Injection Results

PASS: two concurrent reseed requests and response-loss retry; pre-bind crash; post-bind crash plus actual controller restart; old callback rejection; old v1 event replay rejection; two-controller lease takeover and stale guarded Connect stop denial; actual new-owner Connect stop/resume; candidate abort twice; empty candidate and post-snapshot INSERT. The first healthy-candidate diagnostic exposed an old-Dataset resnapshot check incorrectly applied to a candidate; the corrected fresh run passed. The initial empty diagnostic timed out; the corrected code resumed from the retained durable notification and passed. No failed diagnostic run was reclassified as a pass.

## D1–D5 Regression

D1 manager/workspace/source binding and lifecycle are in the 48-test Django suite. D2 capture, pause/resume and source preflight are in the 104-test ETL suite and retained live fixture. D3 v1/v2 identity, poison/replay and generation scopes are in the ETL contract/processing suite. D4 MergeTree/ranked-current/equal-version conflict and Query guard are in ETL and Query suites; the live candidate uses D4 storage. Existing D5 stale callback, credential/config epoch, controller lease and empty notification/zero-row publication tests remain green. The historical full D4 outage/performance matrix was not rerun and its prior failures are not erased.

## Security Results

Foreign workspace and analyst/viewer reseed denial, missing operator key, extra field rejection, old-generation callbacks, expired controller fence and public Query candidate access were exercised in focused/live paths. Local certificate issuance refuses production mode. Connector/slot/view names are server-derived and absent from the public reseed payload. No customer row or credential is written to the report/evidence files. Hosted Java transport, broker ACL/TLS and workload identity remain CAP-14 obligations.

## Tests

Final focused regression: **48 Django + 104 ETL + 30 Query pytest = 182 passed, 0 failed, 0 skipped**. `makemigrations --check --dry-run`, Python compilation and `git diff --check` passed. Query's live startup applied the new migrations. The documentation checker still reports only the pre-existing width findings at report 50 architecture lines 131–132; report 50 was preserved. Live evidence: legacy `d5-r1-results-bdc08b9a.json`; crash/restart `d5-r1-results-daa28fac.json`; empty `d5-r1-results-c053e712.json`; concurrency/abort `d5-r1-results-d995ab82.json`; physical fence `d5-r1-fence-results-4635912b.json`, all outside the repository under the retained fixture directory. The first failed diagnostic runs are described above. The isolated Compose stack was stopped without deleting its containers or volumes.

## Files Modified

`bi_platform_shared/cdc_contract.py`; `etl-final/shared/cdc/{connect.py,postgres.py,worker.py}`; `etl-final/tests/{test_cdc_contract.py,test_cdc_capture_preflight.py}`; `services/query-service/integration/{models.py,cdc.py,cdc_reseed.py,test_cdc.py,migrations/0010_cdc_candidate_cutover.py}`; `services/query-service/database/{models.py,cdc.py,migrations/0007_database_cdc_generation.py}`; `scripts/{verify_foundation_d5_r1.py,verify_foundation_d5_r1_fence.py}`; `docker-compose.cdc-local.yml`; `docs/remediation/FOUNDATION_D_CDC_RUNBOOK.md`; this report. Other entry-dirty files were preserved.

## Remaining D5-R1 Debt

Automate a full physical orphan inventory across Connect, PostgreSQL slots, Kafka and ClickHouse; current authenticated status classifies persisted logical inconsistencies and leaves external physical cleanup to operator review. Add a deliberate empty-snapshot boundary-overlap transaction and fresh live retirement/revocation/incompatible-DDL probes. External side effects cannot consume a database fence atomically; late in-flight REST/file effects require the documented post-check and new-controller reconciliation. These limits do not change the proved local generation replacement and Query authority gates.

## D5-R2 Requirements

Issue and verify a source reconciliation LSN, prove Loader applied through it, compare exact authorized Query candidate state at that watermark, handle bounded large-source chunks and mismatch audit, and replace `local_exact_v1` with a production-safe `watermark_reconciliation.v1` certificate. Include the overlap and live lifecycle probes, plus final regression. Do not infer D5-R2 completion from the D5-R1 local exact comparator.

## Exit Decision

**D5-R1 READY FOR D5-R2** on the isolated local evidence: a real legacy scope safely reached a new Query-authoritative generation, old callbacks/events and stale physical operations were fenced, both cutover crash points recovered, and the focused D1–D5 suite stayed green. **Foundation-D PARTIAL; G-D OPEN; Production Readiness NO-GO.** No D6 work, commit or push.
