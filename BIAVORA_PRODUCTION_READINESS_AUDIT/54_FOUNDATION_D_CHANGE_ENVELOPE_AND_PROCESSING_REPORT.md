# BIAVORA — Foundation-D / D3 ChangeEnvelope and Processing Report

Date: 2026-11-06 (Asia/Damascus). Evidence is from the isolated `biavora_foundation_d` local Compose fixture and focused tests. **D3: READY FOR D4.** Foundation-D remains **PARTIAL**, G-D **OPEN**, Production Readiness **NO-GO**. This report makes no claim about D4 ClickHouse current-state correctness or production transport certification.

## Executive Status

ChangeEnvelope.v1 is retained. Normalizer binds the trusted pipeline scope, validates Debezium source position, operation and complete catalog-shaped images, then publishes a deterministic envelope. Transformer revalidates the envelope, schema version and typed row before publishing. Permanent poison is durably written to a scoped payload-free DLQ, reported to the control plane, and only then committed. Transient send/callback failures leave the input uncommitted. A clean final-build source yielded six raw, six normalized and six transformed business events, with one transport tombstone and zero DLQ records. A separate full acceptance source passed reverse replay, worker restart and four poison injections.

## Entry Repository State

Before edits: branch `foundation-c-staging...origin/foundation-c-staging`; HEAD `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`; existing working tree intentionally dirty (28 tracked paths with 268 insertions/40 deletions, D0–D2 reports/code untracked, TimesFM dirty submodule); cached diff empty. No reset, clean, stage, commit or push was performed. D3 did not traverse or modify TimesFM. Earlier work was preserved.

## D3 Scope and Non-Goals

Scope is Debezium raw → trusted Normalizer → `ChangeEnvelope.v1` → validated Transformer → transformed CDC event and the poison/replay boundary. D2 capture/control source code was not changed. D4 Loader/current-state and authorized Query result correctness, D5 generation/reseed/schema history, D6 full release matrix and hosted security remain outside this decision.

## Files Reviewed

Read the two report 50 documents, reports 51–53, canonical context 34/43/45/22/30/31/33/20/49, `bi_platform_shared/cdc_contract.py`, CDC worker/schema/connect/postgres/clickhouse modules, the CDC contract/offset/capture tests, Query CDC model/control code, the isolated Compose definition and the Kafka/live verifiers. The report 53 D2 capture/control boundary and pins were retained.

## Existing ChangeEnvelope Architecture

One shared Python contract is used by Normalizer, Transformer and Loader. The trusted subscription supplies scope and catalog version; Debezium supplies row images and source coordinates. A successful stage sends synchronously, persists a scoped checkpoint callback and commits its Kafka input offset. Kafka transport is at least once; the envelope makes replay deterministic. The Loader's later stale-version and current-state behavior is a D4 concern.

## Trusted Scope Model

`workspace_id`, `source_id`, `pipeline_id`, `dataset_id`, schema and table come from the server-side `Scope`. Raw tenant ID claims at envelope/payload/source levels are compared with that scope and rejected on mismatch. Debezium `source.schema` and `source.table` must match the selected table. The Normalizer only subscribes to its exact scoped raw topic and heartbeat topic. Live foreign-workspace injection produced `CDC_SCOPE_MISMATCH` in the original scope's DLQ, no foreign business output, and the other workspace's source route remained 404.

## ChangeEnvelope.v1 Field Contract

All serialization is canonical JSON (sorted keys, UTF-8, no NaN). Required fields and ownership:

| Field | Owner / source | Validation and representation |
|---|---|---|
| `contract` | Shared contract | Exact string `ChangeEnvelope.v1`. |
| `workspace_id`, `source_id`, `pipeline_id`, `dataset_id` | Trusted pipeline scope | Positive integer IDs; UUID strings for source/pipeline; exact match on validation. |
| `schema`, `table` | Trusted selected table | Identifier grammar and exact Debezium source match; strings. |
| `operation` | Debezium `op` via shared mapping | One of `SNAPSHOT`, `INSERT`, `UPDATE`, `DELETE`; string. |
| `primary_key` | Debezium key checked against catalog PK and row image | Exact key set, non-null scalar values, row equality; JSON object. Composite keys supported. |
| `before`, `after` | Debezium row images | Operation-specific null/dict rules, exact catalog column set and supported values; JSON object or null. |
| `position.lsn` | Debezium `source.lsn` | Unsigned 64-bit integer. Kafka offset is excluded. |
| `position.transaction_id` | Debezium `source.txId` | Unsigned 64-bit decimal string; empty string only for an absent snapshot transaction ID. |
| `position.event_index` | Debezium `transaction.total_order` | Unsigned 32-bit integer, positive for streaming; zero permitted for a snapshot lacking transaction metadata. |
| `source_timestamp_ms` | Debezium `source.ts_ms` | Nonnegative integer milliseconds. Ingestion wall clock is excluded. |
| `schema_version` | Trusted catalog/control item | Positive integer; Transformer requires exact current version. No raw schema version is invented. |
| `snapshot_complete` | Debezium snapshot marker / operation | Boolean; snapshot `last` or any streaming event is true. `first` and `true` snapshots are false. |
| `event_id` | Shared contract | Lowercase SHA-256 hex of canonical trusted scope, PK, position and operation. |
| `version` | Shared contract | UInt128-compatible, base-10 string from LSN and rank; never a JSON float. |

No fingerprint field was added: the current trusted catalog version plus exact column and type validation is the v1 binding. A historical event from an older schema generation is rejected rather than silently rewritten. Durable schema-history migration is D5 work.

## Operation Mapping

Exact mapping is `r→SNAPSHOT`, `c→INSERT`, `u→UPDATE`, `d→DELETE`. A Kafka null value is a transport tombstone: it emits no envelope and is acknowledged after checkpoint. Heartbeats update capture freshness only; they emit no business event or snapshot completion. Transaction/control records without a supported row operation fail closed; the Normalizer subscribes to no transaction metadata topic. TRUNCATE/`t` is `CDC_OPERATION_UNSUPPORTED`. Final live source: `r=3`, `c=1`, `u=1`, `d=1`, one tombstone, six envelopes, six transformed events.

## Event Identity

The same scope/key/LSN/transaction ID/index/operation yields the same SHA-256 ID and envelope on duplicate delivery, restart and replay. Identity excludes Kafka offset, process time and randomness. Distinct keys in a snapshot and distinct transaction order positions have distinct IDs. The proven uniqueness domain is a configured source/table/key/source position/operation from the trusted Debezium producer; it is not a global cross-pipeline ID, and a forged same-position/different-image raw record is outside the authenticated-source assumption. D6 must certify broker producer identity and ACL/TLS for hosted deployment.

## Ordering and Version Model

`version = (lsn << 33) + rank`, where snapshot rank is zero and streaming rank is `2^32 + total_order`. It fits UInt128 and is carried as a decimal string. Snapshot ranks below streaming at the same LSN; increasing LSN and same-LSN transaction order remain deterministic. Live same-key INSERT, UPDATE, DELETE versions increased in that order. Reverse replay carried the original versions; older events were not dropped by Normalizer. This is a per source/table/key ordering key; no cross-source or global transaction order is claimed. Stale suppression belongs at the D4 Loader boundary.

## Primary Key Semantics

The configured PK list must be nonempty and unique; Debezium key fields must match it exactly and agree with the selected row image. Composite keys have a focused test. UPDATE requires the old key and new key to match the Kafka key; a key-changing UPDATE is rejected as `CDC_KEY_MUTATION_UNSUPPORTED`. A Debezium delete plus insert for a changed key remains two explicit changes. Catalog conversion checks PK type and range, including integer bounds and UUID syntax.

## Before / After Semantics

SNAPSHOT and INSERT require `after` and no `before`; UPDATE requires both; DELETE requires `before` and a null `after`. The worker checks the exact current catalog column set and converts each non-null image before publishing the envelope. Missing business fields, an extra field, unavailable TOAST placeholders and wrong types fail with a bounded code. No synthetic after image is created.

## Schema / Type Normalization

Catalog mapping covers bounded smallint/integer/bigint, boolean, text/character/varchar, UUID, date, timestamp, timestamptz, nullable values, JSON/JSONB and bounded `numeric(p,s)` up to precision 76. Numeric inputs reject float and serialize at fixed scale without float conversion. Timestamp without time zone uses Debezium integer microseconds; timestamptz requires an aware ISO value and converts to UTC microseconds. JSON numbers parse as `Decimal`; key sorting and exact decimal formatting make JSON output stable. Unsupported types and invalid values fail closed. Unit vectors include a 76-digit decimal, timezone conversion, canonical JSON, null and invalid values.

## Schema Version / Fingerprint

Normalizer takes the version and columns from the trusted control item, checks exact row shape and types before send, and emits that version. Transformer checks exact current version and shape again. A nullable ADD can pass preflight compatibility when the current catalog and event match; retained old-image records with missing added columns fail safely. Changed PK, missing/extra column and type mismatch are rejected. No arbitrary online evolution or schema-history reconstruction is claimed.

## Tombstone Handling

The null Kafka value does not parse its key, emit a DELETE, or produce a false failure. Focused worker test observed checkpoint then offset commit without a send. Each clean live source had one raw tombstone and no extra business event.

## Heartbeat Handling

Worker test observed a valid heartbeat updating only `capture_timestamp_ms` and then committing the heartbeat offset. No normalized/transformed send occurred. Heartbeat retention behavior remains covered by the D2 offset suite.

## Transaction Metadata Handling

Streaming changes require a bounded positive `total_order` and bounded transaction ID; malformed/missing order is permanent poison. Snapshot records may have no transaction metadata. Real Debezium snapshot markers `first`, `true`, `last` are accepted; the initial live attempt exposed missing `first` support, which was fixed and then verified by a fresh zero-DLQ run. Transaction metadata/control events are not mapped to row mutations.

## Duplicate Delivery Results

The full fresh run replayed one raw event per operation twice. Each chosen operation appeared three times in normalized and transformed topics with identical event ID, decimal version and full canonical payload. No divergent normalized record was observed. The final history contained 15 normalized and 15 transformed deliveries for seven unique IDs after the additional post-restart update.

## Reordered Delivery Results

Representative DELETE, UPDATE, INSERT and SNAPSHOT raw records were injected in reverse order twice. Their transformed payloads remained identical to the original records, and the same key's original INSERT/UPDATE/DELETE versions remained increasing. D3 carried stale records to the D4 boundary without claiming a final ClickHouse result.

## Worker Crash / Replay Results

Unit fault injection at the post-send/pre-checkpoint `os._exit` branch observed a durable send and no commit; replay emitted the identical envelope and then committed. Transformer callback-failure replay emitted identical transformed payload. Live Normalizer restart was followed by a fresh PostgreSQL UPDATE that appeared with the expected stable ID in both stages. This proves at-least-once replay behavior at these boundaries, not Kafka exactly-once processing.

## Permanent vs Transient Failure Classification

Permanent: invalid/oversize/overcomplex JSON, unsupported operation, foreign scope/schema/table, missing/changed PK, invalid source position/timestamp/snapshot marker, impossible row image, unsupported type, schema/version/contract mismatch and malformed transformed row. These become bounded `CDC_*` codes. Transient Kafka send, callback and dependency errors propagate to the retry loop without input commit. Unit tests exercised send and callback failures on both business and poison paths.

## DLQ Safety Contract

`CdcFailure.v1` contains only trusted scope, validated 64-hex event ID or null, bounded `CDC_*` reason, stage, retry count and bounded timestamp. It never copies row images, Kafka bytes, exception text, arbitrary attacker ID, password, ciphertext, token or DSN. Final live foreign payload contained a private-row sentinel; neither normalized/transformed output nor any scoped DLQ contained it. A scan of 53 records across the final source's four topics found none of five fixture secrets, and Connect config used a file password reference.

## Poison Offset Disposition

The worker waits for DLQ send acknowledgment, calls the control plane to pause/fail the scoped pipeline, then commits the poison offset and stops that poll. Unit tests verified this order and no commit when DLQ send or callback fails. Fresh live run offsets: malformed 16→17, foreign 17→18, unsupported 18→19, schema 19→20. Each had a safe DLQ record and pipeline pause intent. The schema incompatibility lifecycle settled at `RESEED_REQUIRED` with an inactive replication slot, matching the D1 sticky policy.

## Foreign Scope Attack Results

A raw event claimed workspace 22 while subscribed under workspace 11. Normalizer rejected it with `CDC_SCOPE_MISMATCH`; no foreign envelope or transformed row was emitted. The original pipeline received the scoped failure and physical pause; workspace 22 could not read the source (404). Contract tests also covered forged source, pipeline and dataset IDs and altered source table/schema.

## Payload Boundary Findings

Consumer JSON bytes are limited to 2 MiB before parse, and parsed containers are limited to depth 64 and 100,000 visited nodes. Kafka request/fetch limits remain 2 MiB. Unit tests covered excessive size, depth, breadth, malformed JSON, and hostile event ID/metadata; all failed with bounded codes. Full production broker/topic quotas and adversarial traffic controls remain D6 transport work.

## Contract Compatibility

No field was added or removed and no wire version was bumped. The existing `ChangeEnvelope.v1` decoder remains in use for retained messages. Validation is stricter: invalid row images and mismatched catalog versions no longer pass onward, and real Debezium `first` snapshot markers are now accepted. An older invalid retained message can terminally fail and require controlled replay/reseed; it is not silently transformed under a new schema.

## Live D3 Acceptance Matrix

| Case | Final evidence |
|---|---|
| Fresh source and operation mapping | Run `bff512e8`: raw/normalized/transformed 6/6/6, `r=3,c=1,u=1,d=1`, one tombstone. Separate clean run `8718b991`: same counts, zero DLQ. |
| Scope and stage correspondence | Six unique IDs matched raw→normalized→transformed; all trusted IDs matched the subscription. |
| Duplicate/reverse replay | Eight reverse raw injections; each representative operation had three identical normalized and transformed deliveries. |
| Restart | Normalizer restarted; fresh UPDATE reached both stages with stable identity. |
| Malformed, foreign, unsupported, schema poison | Four safe scoped DLQ records, callback pause intent and committed offsets; no later record silently processed past poison. |
| Schema lifecycle | `CDC_SCHEMA_INCOMPATIBLE` led to `RESEED_REQUIRED`, slot inactive. |
| Security | No private sentinel in business/DLQ output; five fixture secrets absent from 53 scoped Kafka records; password reference only in Connect config. |

JSON evidence is stored outside the repository beside the fixture env file as `d3-results-bff512e8.json` and `d3-clean-results-8718b991.json`. The earlier development run `a7fe0e8d` exposed the `first` marker defect and proved explicit recovery by replay; it is retained as diagnostic evidence, not the final clean acceptance.

## D1/D2 Regression Results

D1: 45 Django integration/public-boundary/CDC/Foundation-A tests passed with `service_config.sqlite_test_settings` and the legacy resolver test key isolated from live fixture credentials; 17 generic ingestion callback security tests passed on the host. The initial attempt using the live PostgreSQL test database and a second attempt inheriting the live connector key were runner configuration failures, then corrected and green. The D1 sticky reseed and source/pipeline/Dataset binding tests are included. D2: 88 focused CDC contract, processing, offset and capture-preflight tests passed; final live source proved raw `r/c/u/d`, tombstone and exact source/table; poison phases proved pause/resume and slot inactivity. Capture/control implementation was unchanged, so the expensive D2 publication-drift matrix was not repeated; report 53 remains its last live drift evidence.

## Security / Secret-Leakage Results

The worker logs bounded error class/code, not raw payload or exception strings. DLQ sanitizes ID, reason, stage and timestamp. Unit malicious metadata and live private sentinel tests passed. Final scoped scan checked 53 Kafka values against five fixture secrets and found no match. No hosted ACL/TLS or secret-management certification is inferred.

## Tests and Measurements

Focused Python CDC suite: **88 passed, 0 failed, 0 skipped**. D1 Django suite: **45 passed**. Query callback security: **17 passed**. Total final focused tests: **150 passed**. Python compile checks and `git diff --check` passed. Live final run `bff512e8` passed end to end; separate zero-DLQ clean run `8718b991` passed. The initial `first` marker issue and the schema lifecycle assertion were fixed during acceptance, with final reruns green. No 5,000-row latency or D4 current-state measurement is claimed.

## Files Modified

`bi_platform_shared/cdc_contract.py`; `etl-final/shared/cdc/schema.py`, `worker.py`; `etl-final/tests/test_cdc_contract.py`; new `etl-final/tests/test_cdc_processing.py`; `scripts/foundation_d_kafka_probe.py`, `verify_foundation_d_cdc.py`; this report. These D3/D0–D2 paths remain unstaged in the intentionally dirty tree. Evidence JSON and fixture credentials remain outside the repository.

## Remaining D3 Debt

No known core D3 acceptance blocker remains under the trusted Debezium-producer model. A raw producer able to forge a valid same-scope source position can create conflicting row images with the same source-based identity/version; local broker injection is intentionally available for testing. D6 must enforce authenticated producer identity and topic ACL/TLS before hosted enablement. Operational replay of an already committed poison requires controlled raw replay or reseed; the initial development run demonstrates this explicitly. The verifier has local-only recovery phases for that evidence.

## Deferred D4–D6

D4: typed Loader version suppression, tombstone/current-state semantics and authorized Query proof. D5: generation fencing, schema history, safe reseed/cutover, empty snapshot publication and hosted WAL operations. D6: final-pin 5,000-row/recovery budgets, complete A/B/C regressions, remote CI, production transport identity/ACL/TLS and G-D closure. None was declared complete here.

## D3 Exit Decision

**READY FOR D4.** Deterministic v1 contract, trusted scope, four operations, tombstone/heartbeat control separation, exact supported types and schema checks, replay/order, safe terminal poison, transient no-skip behavior, restart proof and focused D1/D2 regression passed. Foundation-D remains PARTIAL; G-D remains OPEN; Production Readiness remains NO-GO. No commit or push was made.
