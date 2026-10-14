# Foundation-A Query Security Implementation

> **Phase:** BIAVORA FOUNDATION-A  
> **Date:** 2026-10-14  
> **Final status:** GREEN  
> **Issues:** BIA-001 CLOSED, BIA-002 CLOSED, BIA-010 CLOSED

## Scope

This slice implements the authoritative analytical security boundary defined by BIA-001, BIA-002, and BIA-010, with the directly necessary portions of MAP-003, MAP-010, MAP-011, MAP-014, and MAP-041. It does not implement CDC, the Semantic Layer, RAG, agents/MCP, metering redesign, payment integration, broad AI restructuring, durable jobs, or production runtime conversion.

The phase establishes Query as the sole application authority for product analytical data execution. ETL retains its distinct write authority. AI schema metadata access remains BIA-021/MAP-024 work and is not represented as closed here.

## Safety baseline

- Branch: `main`.
- Baseline commit: `0b9ee0b`.
- Pre-existing state preserved: dirty `services/ai-service/forecasting/timesfm` submodule and the untracked `BIAVORA_PRODUCTION_READINESS_AUDIT/` directory.
- Baseline focused Query tests: 29 passed, 0 failed, 0 skipped, 3 warnings.
- Baseline focused Voice tests: 12 passed plus 5 subtests, 0 failed, 0 skipped, 3 warnings.
- No commit or push was performed.

## Execution-path classification before the change

| Caller/path | Classification | Evidence and disposition |
|---|---|---|
| Voice `QueryExecuteView` → Query API → Query ClickHouse executor | `AUTHORIZED_QUERY_PATH` until outage | Query performed execution, but did not require an exact logical-dataset table allowlist. |
| Voice request-exception handler → local `ClickHouseExecutor` | `SECURITY_BYPASS` | Active fail-open path; removed. |
| Query database preview/schema/count | `AUTHORIZED_QUERY_PATH` | Query-owned, workspace/dataset-resolved metadata/preview operations; retained and bounded. |
| Query upload cleanup/drop | `ADMIN/INGESTION_LIFECYCLE` | Query-owned destructive ingestion cleanup, not ordinary product analytical execution; retained. |
| ETL connectors/loaders → ClickHouse | `INGESTION_WRITE_PATH` | Dedicated write authority; unchanged. |
| Report duplicate executor | `SECURITY_BYPASS` capability, dormant at runtime | Active Report routes are proxy/presentation paths; dormant executor removed. |
| Visualization → Query definition → Metabase | `AUTHORIZED_QUERY_PATH` / governed presentation | Definition is created and revalidated by Query. Visualization has no application ClickHouse client. |
| Gateway/frontend | `ADMIN/CLIENT_ONLY` | No direct ClickHouse execution. Unused client dependencies/credentials removed. |
| AI schema providers | `UNVERIFIED` for broad metadata scope | Direct `system.columns`-style schema reads remain BIA-021/MAP-024. |
| AI value index | `SECURITY_BYPASS` capability when enabled | Default and Compose setting disabled; runtime self-construction of a ClickHouse product-data client removed. |

## Architecture before

```text
Voice ──► Query ──► ClickHouse
  └──── outage fallback ──► local ClickHouse client

Query(workspace database only) ──► SQLGuard(optional table membership) ──► unbounded materialization

Report dormant executor ──► ClickHouse
AI optional value index ──► ClickHouse tenant values
```

The physical database could be workspace-scoped while the referenced table remained unconstrained. Ordinary result execution had no universal server policy for time, rows, bytes, memory, concurrency, pagination, or cancellation.

## Architecture after

```text
authenticated actor/workspace
          │
          ▼
logical dataset_id
          │
          ▼
Query server-side binding resolver
  ├─ workspace ownership
  ├─ dataset ownership/lifecycle
  └─ exact non-empty completed destination tables
          │
          ▼
SQLGuard(AST + exact allowlist + read-only)
          │
          ▼
PostgreSQL workspace admission slots
          │
          ▼
Query ClickHouse executor
  ├─ readonly=1
  ├─ time/row/read-byte/result-byte/memory limits
  ├─ bounded LIMIT/OFFSET materialization
  ├─ explicit truncation/next page
  ├─ workspace-scoped query ID/cancellation
  └─ safe structured telemetry
```

Voice has one outcome path: authorized Query success or an explicit failure. Report, Gateway, Voice, and Visualization no longer package a ClickHouse client or receive a usable ClickHouse environment through Compose. AI cannot construct a direct tenant-value index client. Metabase remains the downstream visualization execution engine for Query-authorized definitions; it is not an alternate application authorization endpoint.

## BIA-001 evidence — CLOSED

- `execute_sql_payload` and the validation/definition endpoints require authenticated workspace scope and logical `dataset_id`.
- Client-supplied `workspace_database`, `database_name`, `clickhouse_database`, and `physical_table_name` are rejected. A legacy `table_name` is only an untrusted exact-match hint to the server-resolved dataset binding.
- `resolve_workspace_dataset_binding` validates positive IDs, dataset existence, workspace ownership, completed lifecycle, ClickHouse database metadata, and every completed multi-table destination.
- Product SQL guards use `require_allowed_tables=True`; `None` or an empty set fails closed.
- The sqlglot AST policy checks all table nodes, including qualified/quoted identifiers, aliases, JOINs, CTE bodies, nested queries, and subqueries, and blocks table functions, system sources, mutations, client `SETTINGS`, client `FORMAT`, and multiple statements.
- ORM-backed endpoint tests create real Query `Database` rows for two workspaces. Cross-workspace dataset, arbitrary table, and physical-override attempts return empty rows and never call the executor.
- Unit/security tests additionally cover both tenants in both directions, unknown/missing/empty/processing/failed bindings, quoted identifiers, qualified names, JOINs, subqueries, and CTEs.

## BIA-002 evidence — CLOSED

- Voice stores `VoiceReport.dataset_id` when a voice/text report is created and sends it on execution.
- Voice marks SQL validated only after Query returns success.
- Query service network failure produces `CLICKHOUSE_UNAVAILABLE`, HTTP 503, and `retryable=true`; no local client is invoked.
- Legacy Voice rows without a logical dataset fail closed with `FORBIDDEN_DATASET` before network execution.
- Voice health checks Query rather than ClickHouse; Voice settings, dependency, Compose readiness/dependency, and credential wiring no longer require ClickHouse.
- Report's dormant duplicate executor was deleted, and Report's ClickHouse dependency/configuration was removed.
- Gateway and Visualization no longer package `clickhouse-connect`; Compose explicitly blanks inherited ClickHouse variables for all four non-authority services.
- AI value indexing defaults off and cannot construct its own product-data ClickHouse client even if the flag is changed; it returns no index without a future injected authorized provider.
- AI schema-only metadata clients remain visible and explicitly deferred to BIA-021/MAP-024. They do not expose a product analytical data execution endpoint.
- ETL ClickHouse clients remain unchanged as dedicated ingestion writers.

## BIA-010 evidence — CLOSED

Central `QueryResourcePolicy` values and safe defaults:

| Control | Default | Enforcement |
|---|---:|---|
| Execution time | 30 seconds | ClickHouse `max_execution_time`; timeout category `QUERY_TIMEOUT`. |
| Total result window | 10,000 rows | Server page-window validation and ClickHouse row limit. |
| Default/max page | 500 / 1,000 rows | Client may reduce but cannot raise server maximum. |
| Serialized response | 5,242,880 bytes | ClickHouse `max_result_bytes` plus application JSON-byte cap. |
| Bytes read | 1,073,741,824 bytes | ClickHouse `max_bytes_to_read`, overflow mode `throw`. |
| Memory | 536,870,912 bytes | ClickHouse `max_memory_usage`. |
| Workspace concurrency | 2 | PostgreSQL session advisory-lock slots per workspace. |
| Read-only | enabled | ClickHouse `readonly=1` and executor SELECT/WITH check. |

Configuration is loaded by Django settings and rejects zero, negative, non-integer, inconsistent, or unsafe-high values at startup. The executor fetches only `page_size + 1`, returns at most the authorized page, and reports `returned_count`, `truncated`, `next_page`, `limit_reached`, and `max_rows`. It never materializes an unbounded ordinary result in application memory.

Cancellation derives a ClickHouse query ID from authenticated workspace plus the original request ID and restricts `KILL QUERY` to the current ClickHouse user. Error categories distinguish validation, dataset denial, timeout, limit, cancellation, ClickHouse outage, and internal failure without returning credentials, physical connection details, stack traces, or cross-tenant object existence. The PostgreSQL admission lock is distributed across Query workers, releases in `finally`, and recovers stale leases when the database session closes.

### Live infrastructure and connectivity

- The repository's existing Compose stack was used; no alternate environment was invented.
- Docker Desktop `4.45` / Engine `28.3.3`, ClickHouse `26.2.3.2`, and PostgreSQL `18.3` backed the run.
- Query `/health/` and `/ready/` returned HTTP 200. Readiness confirmed the live PostgreSQL connection plus ClickHouse, Kafka, ETL connector, ETL metadata, and Subscription dependencies. All started Compose dependencies reported healthy.
- Query does not use Redis for this admission path, so no Redis dependency was required.
- No `pg_hba.conf`, credential, role, network, or production security default was weakened. The Query image was rebuilt from the current worktree so the live container exercised the implementation under review.

### Live ClickHouse resource results

- The running service loaded the actual defaults shown above and a normal real query succeeded with the complete expected settings map.
- A client request for 100,000 rows was clamped to the configured 1,000-row page; a page beyond the 10,000-row authorized window was rejected; a direct server row-limit overflow was rejected.
- A result above the configured 5,242,880-byte ceiling returned the safe typed `QUERY_LIMIT_EXCEEDED` response with no raw engine error.
- API mutation was rejected with `VALIDATION_REJECTED`, and a benign direct DDL probe with `readonly=1` was rejected by ClickHouse without creating the table.
- A real one-second bounded timeout drill returned `QUERY_TIMEOUT` and `aborted_due_to_timeout=true`; the configured production value remained 30 seconds and was accepted on normal execution.
- Deliberately reduced per-query probes verified real `max_bytes_to_read` and `max_memory_usage` enforcement without attempting a destructive 1 GiB/512 MiB stress. Both returned `QUERY_LIMIT_EXCEEDED`; the configured 1 GiB and 512 MiB values remained loaded and accepted on the normal path.
- ClickHouse 26's result/read-byte error phrases were mapped to the existing safe limit category. No credentials, host details, or raw engine exception text appeared in client errors.

### Live authenticated cancellation

- A sufficiently long query was started through authenticated `/query/execute/`, holding the real PostgreSQL workspace lease and carrying the workspace/request-derived ID into ClickHouse.
- The exact ID was observed in `system.processes`. A token for another workspace, using the same request ID, received HTTP 200 with `cancelled=false`; the target remained running.
- The authorized workspace cancellation returned HTTP 200 with `cancelled=true`. ClickHouse removed the process and the executing request returned HTTP 409 with `QUERY_CANCELLED`.
- A normal authenticated query succeeded immediately afterward, proving service, client-session, and admission-slot recovery.

### Real PostgreSQL multi-worker admission and recovery

- Four distinct Query worker processes used real PostgreSQL sessions. With the configured limit of two for one workspace, A and B acquired slots and C was bounded; a different workspace acquired independently.
- After normal completion, a replacement worker was admitted.
- After an intentional exception, two workers could again acquire both slots.
- A worker was terminated with `SIGTERM` while holding a slot; after its database session closed, two replacement workers acquired both slots. No permanent stale lock remained.

### Bounded abuse/load sanity

- Twenty authenticated requests were issued: eight oversized page requests all remained capped at 1,000 rows, and twelve cross-workspace dataset attempts all returned `FORBIDDEN_DATASET` without data.
- The same run included a real slow timeout, cancellation while running, different-workspace cancellation denial, multi-process admission pressure, and post-failure recovery.
- Query container memory was 115.2 MiB before the final run and 119 MiB after it; no obvious unbounded growth appeared. The uniquely named ClickHouse tables and PostgreSQL metadata rows were removed and verified at count zero.

### Corrections required by live verification

The live run exposed four narrow driver-integration defects and they were corrected without redesigning Foundation-A: clickhouse-connect sessions are now thread-local so execution and cancellation cannot issue concurrent operations on one HTTP session; `query_id` is sent through the pinned driver's supported per-query settings/URL-transport path so it is the real server process ID; cancellation reports `cancelled=false` when that scoped process is absent; and ClickHouse 26 result/read-byte limit wording maps to `QUERY_LIMIT_EXCEEDED`. Focused regression tests cover these corrections.

Implementation uses the pinned driver's per-query `settings` interface, including its recognized `query_id` HTTP transport parameter: [ClickHouse Connect driver API](https://github.com/ClickHouse/clickhouse-docs/blob/main/docs/integrations/language-clients/python/driver-api.md), [0.15.1 client source](https://github.com/ClickHouse/clickhouse-connect/blob/v0.15.1/clickhouse_connect/driver/client.py), and [0.15.1 HTTP client source](https://github.com/ClickHouse/clickhouse-connect/blob/v0.15.1/clickhouse_connect/driver/httpclient.py).

## Safe telemetry and result contract

Each Query execution logs request ID, workspace ID, logical dataset ID, outcome, duration, rows, output bytes, error category, and service version. The ClickHouse layer logs query ID plus a SQL hash, not raw SQL. Credentials, tokens, prompts, full result data, infrastructure exception strings, and raw stack traces are not logged by the new boundary.

Success responses contain logical scope, request/query IDs, bounded rows, column metadata, result shape, execution metrics, applied non-secret limits, and pagination completeness. Failures return stable empty result fields, typed error code, retryability, and safe text.

## Files changed

### Shared and deployment

- `.env.example`
- `docker-compose.yml`
- `bi_platform_shared/sql/guard.py`

### Query

- `services/query-service/query_api/resource_policy.py` (new)
- `services/query-service/query_api/application/query_execution.py`
- `services/query-service/query_api/services/workspace_concurrency.py` (new)
- `services/query-service/query_api/services/workspace_db_resolver.py`
- `services/query-service/query_api/services/clickhouse_executor.py`
- `services/query-service/query_api/views.py`
- `services/query-service/query_api/urls.py`
- `services/query-service/database/utils.py`
- `services/query-service/service_config/settings.py`
- `services/query-service/service_config/sqlite_test_settings.py` (new test harness)
- `services/query-service/database/foundation_a_integration_tests.py` (new)
- Query unit/security test modules listed by the final diff.

### Voice and Report

- Voice settings, requirements, model, migration `0014_voicereport_dataset_id.py`, views, service exports/result sanitization helper, contract tests, and runtime overview.
- Report settings, requirements, service exports, redacted transcription/SQL logging, and removal of the dormant `voice_reports/services/clickhouse_executor.py`.

### AI, Gateway, Visualization

- AI high-preprocessing configuration/value-index provider boundary and tests.
- Gateway and Visualization requirements; Compose credential blanking.

### Evidence

- This report.
- BIA-001/BIA-002/BIA-010 status/evidence in `20_TECHNICAL_DEBT_AND_PROBLEM_REGISTER.md`.
- Current phase/blockers/verified baseline in `34_BIAVORA_MASTER_CONTEXT_FOR_FUTURE_PROMPTS.md`.

## Test evidence

| Area | Result |
|---|---|
| Shared SQL guard | PASS — 11 passed, 0 failed, 0 skipped, 3 warnings. |
| Query full pytest suite | PASS — 113 passed, 0 failed, 0 skipped, 3 warnings. |
| Query focused security/resource rerun | PASS — 45 passed, 0 failed, 0 skipped, 3 warnings. |
| Query ORM endpoint integration | PASS — 3 passed with actual workspace/dataset rows. |
| Voice full pytest suite | PASS — 23 passed plus 5 subtests, 0 failed, 0 skipped, 3 warnings. |
| Voice focused Query/security contracts | PASS — 18 passed, 0 failed, 0 skipped, 3 warnings. |
| AI maintained suite excluding TimesFM | PASS — 236 passed plus 12 subtests, 0 failed, 0 skipped, 3 warnings. |
| Report | PASS — 5 passed, 0 failed, 0 skipped, 3 warnings. |
| Visualization | PASS — 63 passed, 0 failed, 0 skipped, 3 warnings. |
| Gateway maintained Django runner | PASS — 2 passed. |
| Workspace maintained Django runner | PASS — 4 passed. |
| Frontend tests | PASS — 19 passed, 0 failed, 0 skipped. |
| Frontend production build | PASS — 1,929 modules transformed; existing chunk-size/browser-data warnings only. |
| Python compile | PASS. |
| Django Query/Voice system checks | PASS — no issues. |
| Query/Voice migration drift | PASS — no changes detected; Query was also checked against its live PostgreSQL connection. The direct-host Voice check retained the known `pg_hba.conf` history warning but exited cleanly. |
| Voice migration operation | PASS — `0013 → 0014 → 0013 → 0014`; column add/remove/add verified in an isolated schema. |
| Compose parse | PASS — `docker compose config --quiet`. |
| Diff whitespace | PASS — `git diff --check`; line-ending warnings only. |
| Live infrastructure | PASS — Query and all required Compose dependencies healthy; Query health/readiness HTTP 200. |
| Live ClickHouse resource/cancellation suite | PASS — 17 checks, 0 failed; real limits, timeout, cancellation, PostgreSQL multi-worker admission/recovery, and bounded abuse verified. |

The maintained AI command explicitly excluded the preserved TimesFM submodule, which was not modified. Gateway and Workspace used their maintained Django runners. The frontend build initially hit the managed filesystem sandbox and passed unchanged when rerun with approved filesystem access.

Warnings are pre-existing Pydantic protected-namespace warnings for forecast/transcription models. No test was skipped or xfailed in the recorded maintained suites.

## Security test evidence

- Cross-workspace logical dataset IDs: denied before executor, empty rows.
- Cross-dataset table references: denied before executor, empty rows.
- Physical parameter manipulation: rejected.
- Qualified, quoted, JOIN, subquery, and CTE bypass attempts: rejected by AST table membership.
- Unknown, missing, empty, processing, and failed dataset bindings: fail closed.
- Mutating statements, system tables, table functions, client settings/format, comments, and multiple statements: regression coverage passes.
- Query outage from Voice: explicit retryable failure; local execution cannot be instantiated.
- ClickHouse outage/timeout/limits: safe typed failures with no returned data.
- Real authenticated cancellation: other workspace cannot cancel; authorized cancellation stops the ClickHouse process and releases the path for the next query.
- Concurrent workspace overflow: real PostgreSQL-backed workers reject the third same-workspace query; normal, exception, and terminated-session paths release slots.
- Response-byte overflow: rejected without returning rows.
- Repeated oversized pages stay bounded and repeated cross-workspace dataset requests return no data.
- AI value index without an authorized injected provider: returns an empty index.

## Migration impact

Voice adds nullable, indexed `VoiceReport.dataset_id`. It is nullable so deployment is additive and legacy rows remain readable, but legacy rows fail closed for new analytical execution until a logical dataset is supplied through a controlled remediation. New voice/text reports persist the binding at creation.

The migration operation is reversible and was rehearsed forward, backward, and forward again. Full historical fresh migration on SQLite is not claimed: existing Voice migration `0008` and Query migration `0002` contain PostgreSQL-specific historical SQL. The maintained production-graph drift checks passed, including Query against the live PostgreSQL connection. A production-like full fresh/upgrade rehearsal remains separate release-hardening evidence and is not a BIA-010 blocker.

## Rollback procedure

1. Stop or drain Voice analytical requests.
2. Revert application/configuration changes as one release unit so the contract is not split across services.
3. Reverse Voice migration `0014_voicereport_dataset_id` to `0013_reconcile_chart_type_state` if the application rollback no longer reads the field. The column is additive and contains only logical IDs.
4. Restore previous dependency images only if required by the rolled-back Voice/Report code.
5. Do not selectively restore the Voice local ClickHouse fallback in production; if Query is unavailable, retain fail-closed behavior while diagnosing the incident.
6. Re-run Query, Voice, security, migration, Compose, and frontend gates.

No data backfill or destructive data rewrite is required for forward deployment. The migration rollback drops only the newly added `dataset_id` column and its index, so export those logical bindings first if rollback occurs after new reports have been created.

## Known limitations

- The completed abuse check is deliberately bounded and non-destructive; it is not a replacement for the later production-like staging soak/capacity program.
- AI still holds schema metadata access and a ClickHouse credential for BIA-021/MAP-024; direct tenant-value lookup now fails closed. Do not interpret Foundation-A as closing BIA-021.
- Metabase still executes visualization queries downstream from Query-authorized definitions. Its database role/network least privilege must remain part of BIA-007/runtime hardening; no alternate application endpoint can submit unvalidated SQL through this change.
- The deterministic Query endpoint integration test still uses real ORM records on SQLite and mocks only its ClickHouse boundary; the separate live authenticated flow covers the real PostgreSQL and ClickHouse path.
- Durable retry/job persistence remains BIA-009. Voice exposes a retryable failure state but this slice does not invent a durable job subsystem.

## Deferred items

- BIA-021/MAP-024 authorized Schema/Semantic tool and removal of AI ClickHouse credentials.
- BIA-007 least-privilege ClickHouse roles/TLS/network controls, including Metabase.
- BIA-009 durable jobs, BIA-011 upload boundary, and the Foundation-B subscription/secret containment work.
- Physical identifier removal from public database serializers remains BIA-030/MAP-042; physical client overrides are already rejected for analytical execution.

## Final status

**GREEN.** BIA-001, BIA-002, and BIA-010 are closed. Query is the sole application authority for product analytical data queries, exact table binding is enforced, Voice is fail closed, application-side alternative executors are removed, and the authoritative bounded resource policy now has real ClickHouse enforcement/cancellation, real PostgreSQL multi-worker admission/recovery, bounded abuse, and complete maintained regression evidence. Foundation-B is ready to begin.
