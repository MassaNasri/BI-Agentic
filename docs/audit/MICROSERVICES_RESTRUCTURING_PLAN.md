# Microservices restructuring plan

This plan changes architecture only after the Phase 0 baseline. Existing source changes belong to the user and must be reconciled before implementation. Keep public routes working through temporary gateway aliases. Each phase produces its own reviewable change and rollback record. Do not claim a phase complete from a checked-off task alone.

## R0 — Baseline and architecture freeze

**Goal/why:** preserve the working tree, data, runtime identities and failing baseline before more feature work obscures ownership. **Services/files:** entire repository; docs/audit, Compose, existing reset scripts and new reset-dev.ps1. **DB impact:** backed-up targeted development reset only; no schema destruction. **API changes:** none. **Dependencies:** none. **Risks:** unassigned volumes, source secrets, incomplete historical SurrealDB data.

Tasks:
1. Reconcile inventory.json Git snapshot with current changes; keep the user changes intact and establish a review baseline commit when appropriate.
2. Verify backup hashes and restore PostgreSQL/Metabase/ClickHouse/Redis using version-compatible tools. Preserve unknown volumes and the stopped Metabase original.
3. Execute the exact reviewed wipe manifest; record before/after counts and preserved configuration. Repeat refusal tests for remote context, unknown table, missing backup and changed data.
4. Validate startup, owning-service DB connectivity, migrations and safe authentication with external mail/inference disabled. Record failures instead of bypassing dependency checks.
5. Freeze contracts until the P0 authorization, secret and persistence fixes are complete.

**Acceptance/tests:** no unexplained data deletion; restore evidence exists; current architecture and all critical issues have owners; baseline failures are reproducible. **Rollback:** stop writers and restore coordinated data snapshots; preserve evidence and never discard Git changes.

## R1 — Service boundary cleanup

**Goal/why:** make report-service the report owner and stop treating copied domain code as independent services. **Services/files:** report/voice `voice_reports`, gateway routing, ETL stage packages, bi_platform_shared. **DB impact:** ownership decision only initially. **API changes:** introduce report internal command/read endpoints behind existing aliases. **Dependencies:** R0, security fixes SEC-001/002/003/015. **Risks:** DTO drift, duplicated handlers and wrong routing.

Tasks:
1. Inventory reachable handlers versus copied inactive report ORM; remove inactive modules only after import tests prove they are unused.
2. Move report/page/widget/history application logic into report-service; leave voice orchestration separate, preserving resource IDs and serialization.
3. Define etl-connector as ingestion owner with detector/extractor/transformer/loader stage modules; retain legacy deployments until replacement job execution is verified.
4. Move generic HTTP/logging into a versioned transport package and domain repositories/rules into owners. Eliminate sys.path modification and ambiguous `shared`/`kafka` package names.

**Acceptance/tests:** each route has one responsible service; report no longer simply proxies voice; no new foreign ORM imports; old/new response contract comparison passes. **Rollback:** gateway routing flag selects old handlers before data ownership moves.

## R2 — Database ownership definition

**Goal/why:** turn DATABASE_OWNERSHIP_MATRIX.md into enforceable table/grant manifests. **Services/files:** all service models/settings/migrations, notification unmanaged models, ETL persistence helpers. **DB impact:** per-owner table sets, proposed DBs/roles, local foreign-key boundaries. **API changes:** design owner read/command endpoints before moving storage. **Dependencies:** R1. **Risks:** hidden framework tables, migration history incorrectly copied, orphan IDs.

Tasks:
1. Enumerate actual SQL/ORM readers and writers for every PostgreSQL/ClickHouse/SurrealDB entity; distinguish configured credentials from observed domain reads.
2. Assign auth/workspace/report/voice/query/visualization/subscription/notification/ingestion/metadata table and file ownership explicitly.
3. Replace cross-owner foreign keys with scalar IDs only at boundaries; retain intra-owner FK constraints.
4. Define migration-role and runtime-role privileges, connection pools, TLS and credential rotation for each DB.
5. Decide which gateway/stateless components need no DB; remove unused framework DB access rather than provisioning empty business databases.

**Acceptance/tests:** reviewed owner matrix and no ambiguous mutable entity; tests deny one owner's DB role access to another DB. **Rollback:** definition phase has no destructive data change.

## R3 — Database-per-service migration

**Goal/why:** enforce separation with logical databases/roles, initially on the same PostgreSQL server. **Services/files:** owner settings, deployment secret maps, migrations and migration tooling. **DB impact:** create owner DBs, copy owned data and sequence positions; preserve source snapshots. **API changes:** existing owner API contracts remain stable. **Dependencies:** R2 and narrow R5 contracts needed by R4. **Risks:** write races, invalid migration graph, mismatched IDs.

Tasks:
1. Apply each service's corrected migrations to an empty disposable database; do not fake a shared django_migrations history.
2. Migrate auth, workspace, subscription, notification, query, report and voice in dependency-aware increments; create visualization ownership registry and ingestion job schema.
3. Backfill stable IDs, scalar references, tenant ownership and timestamps; reconcile row counts, hash samples and orphan reports.
4. For each cutover, freeze that owner's writes briefly, apply final delta, compare again, switch only its connection/role and monitor.
5. Leave source tables read-only through the rollback window; revoke unnecessary CONNECT and shared credentials after cutover.

**Acceptance/tests:** each owner starts on a clean DB; forbidden DB access fails; all owned rows reconcile; schemas and grants restore successfully. **Rollback:** before new writes, revert connection; after new writes, apply tested reverse delta under write freeze. Never simply point back at stale data.

## R4 — Remove cross-service database access

**Goal/why:** finish enforcement after contracts exist. **Services/files:** notification/models.py and services.py, AI schema/value clients, ETL shared repositories, query metadata lifecycle. **DB impact:** remove foreign mappings/grants; maintain owned snapshots only. **API changes:** recipients, expiry, dataset schema/value, report state and lineage APIs. **Dependencies:** R2, R5 contracts; execute alongside R3 service cutovers. **Risks:** N+1 HTTP calls, stale caches and partial workflow state.

Tasks:
1. Replace notification's five unmanaged foreign-table mappings with paginated recipient/expiry APIs; keep dispatch state local.
2. Replace AI direct ClickHouse reads with query-service schema/value/sample endpoints carrying authorized dataset context.
3. Replace ETL→SurrealDB direct calls with metadata service event APIs; move schema/checkpoint repositories into ingestion ownership.
4. Separate ClickHouse staging from serving; ingestion sends idempotent batches to query's owner endpoint.
5. Remove broad credentials and verify denial using actual service roles, not a source grep alone.

**Acceptance/tests:** no independent service can SELECT/INSERT/UPDATE/DELETE another owner's DB; owner-local workers remain permitted; Metabase projection exception is read-only and documented. **Rollback:** temporary adapter can use old APIs behind a flag; do not restore shared credentials as an untracked permanent workaround.

## R5 — Versioned internal HTTP contracts

**Goal/why:** provide stable owner APIs and failure semantics for R3/R4. **Services/files:** URLs, serializers/DTOs, HTTP clients, gateway aliases. **DB impact:** idempotency/outbox/job tables owned by the caller/receiver where needed. **API changes:** `/internal/v1` and public `/api/v1`. **Dependencies:** R1/R2; start before storage cutovers. **Risks:** retry duplicates, synchronous cycles and schema drift.

Tasks:
1. Publish OpenAPI per service and a gateway catalog; define request/response/error schemas and tenant/service identity requirements.
2. Implement membership decision, user snapshot, recipients, expiring subscriptions, report commands, dataset schema/query, ingestion jobs/batches and metadata events.
3. Adopt connect/read/total deadlines, capped idempotent retry/backoff, request IDs and structured dependency errors through one transport helper.
4. Return 202/job IDs for long work; ensure ingestion batch publication does not synchronously call a caller waiting for that same request.
5. Add caller/receiver contract tests for success, unauthorized, forbidden, not found, timeout, invalid body and unavailable dependency.

**Acceptance/tests:** schema validation and negative contract tests pass; no unsafe POST retry without receiver idempotency; all requests have correlation IDs. **Rollback:** keep versioned old endpoints until clients migrate; no in-place incompatible DTO rewrite.

## R6 — Replace non-HTTP business communication

**Goal/why:** satisfy the requested HTTP-only boundary rule while preserving ingestion correctness. **Services/files:** ETL listeners/start.sh, topic helpers, shared uploads, voice event_bus.py, Compose. **DB impact:** ingestion-owned durable job/checkpoint/retry/dead-letter records replace cross-service broker state. **API changes:** HTTP ingestion/query/metadata contracts; optional replay endpoint. **Dependencies:** R1, R4, R5. **Risks:** lost/duplicated batches, unaccounted topic consumers and path leaks.

Tasks:
1. Inventory producers/consumers/aliases/offsets for connection, schema, extracted/clean/load, metadata and error/DLQ streams.
2. Run a bounded sample through owner-local stage execution and compare output schemas, rows, lineage and idempotency with the old pipeline.
3. Stop new legacy jobs, drain or explicitly snapshot remaining jobs, replay them once with stable idempotency keys, and reconcile output.
4. Replace cross-service file paths with owner-private storage and authenticated HTTP streams/references.
5. Verify report.* event consumers outside the repository; remove unused telemetry events, or replace business consumers with HTTP. Retain Kafka only with a documented infrastructure use and owner.
6. Remove redundant stage containers/topic credentials after a rollback window. Keep original snapshots and topic configuration records.

**Acceptance/tests:** no Kafka/Redis pubsub/shared-file path crosses a business-service boundary; no data loss/duplicate batch on retries. **Rollback:** restore legacy producer routing only after reconciling new processed-job IDs; never run both writers blindly.

## R7 — Gateway consolidation

**Goal/why:** one controlled public entrypoint and independent availability for basic services. **Services/files:** gateway middleware/views/routing/settings, frontend API config, edge/Compose manifests. **DB impact:** gateway-owned rate-limit cache only; remove business DB grants. **API changes:** stable public aliases, structured errors and request IDs. **Dependencies:** R5; port containment can happen during P0. **Risks:** proxy trust errors, CORS/cookie regressions, large uploads.

Tasks:
1. Add TLS edge and public-only routing; bind dev diagnostics to loopback and remove production internal port publications.
2. Verify JWTs centrally as defense in depth while retaining downstream authorization; strip untrusted internal identity headers.
3. Implement route/user/IP quotas and concurrency limits with TTL; enforce body/stream limits and bounded upstream deadlines.
4. Ensure frontend uses gateway for business APIs; expose embedding through a controlled edge with allowed origins.
5. Remove startup dependency on optional AI/visualization/ETL health for gateway/auth readiness.

**Acceptance/tests:** invalid bearer rejected, inaccessible internal ports, CORS/CSRF policy tested, uploads bounded and one dependency outage does not block unrelated APIs. **Rollback:** retain previous edge config and staged hostname cutover; never reopen DB ports publicly.

## R8 — Authentication and authorization hardening

**Goal/why:** eliminate tenant leaks and unify identity trust. **Services/files:** JWT principal classes, workspace client, dataset status, visualization ownership, auth signup/recovery, frontend auth. **DB impact:** refresh sessions/revocation, visualization mapping, immutable dataset binding and workflow state. **API changes:** scoped internal credentials, JWKS/audience, authenticated invitation acceptance. **Dependencies:** urgent SEC-001/002/003/015 fixes are P0 and must not wait for this phase; full design follows R2/R5. **Risks:** invalidating sessions and legacy unmapped objects.

Tasks:
1. Fail closed on membership 403/404/timeouts; apply two-tenant tests to all IDs and mutation paths.
2. Require authenticated ingestion job identity for dataset status; forbid client replacement of physical binding.
3. Enforce Metabase object ownership and approved query IDs; quarantine legacy unmapped cards.
4. Make auth the sole signing-key owner; implement short access expiry, refresh rotation/reuse protection and deactivation/revocation behavior.
5. Make invitation acceptance incapable of overwriting existing account passwords; harden recovery rate limits and verification.
6. Coordinate frontend refresh storage/CSRF and single-flight logic with server rotation.

**Acceptance/tests:** tenant A cannot read/change/sign tenant B resources; revoked users lose required access; no consumer holds auth private signing keys. **Rollback:** preserve secure failure behavior; emergency rollback must not reintroduce known authorization bypasses.

## R9 — Observability and reliability

**Goal/why:** make dependency failures and job progress measurable. **Services/files:** shared logging/HTTP, health endpoints, ETL workers, deployment monitoring. **DB impact:** bounded telemetry retention and owner-local job records. **API changes:** `/health/live`, `/health/ready`, job status/cancel. **Dependencies:** R5/R7. **Risks:** sensitive logs, high-cardinality metrics and false readiness.

Tasks:
1. Return 503 on failed required dependency and separate liveness from readiness; expose migration state and worker heartbeat.
2. Deploy metrics/tracing collectors and dashboards for request latency/error rate, queue age, inference saturation, failed jobs and DB pool exhaustion.
3. Redact tokens/passwords/raw data and cap labels; use one request ID across gateway/HTTP/job transitions.
4. Fix inference cancellation and separate listener/web supervision; define graceful shutdown and bounded retries.
5. Set initial SLOs and alert ownership; exercise AI/Redis/ClickHouse/Metabase/SMTP outages without fake success responses.

**Acceptance/tests:** observed failure behavior matches runbooks and HTTP statuses; no false health PASS; trace spans connect across a representative workflow. **Rollback:** telemetry can be disabled without losing durable application state.

## R10 — Security hardening

**Goal/why:** remove remaining credential/network/runtime exposure. **Services/files:** secret handling, settings, connectors, SQL executors, Git ignore/CI. **DB impact:** least-privileged read/write/migration roles, credential/key versions and TLS. **API changes:** egress policy and validation errors. **Dependencies:** immediate rotations/P0 containment first; full rollout after R8. **Risks:** credential lockout and source connector incompatibility.

Tasks:
1. Rotate historically exposed credentials and record only rotation status/type; distribute per-service secrets.
2. Implement explicit production startup gates for missing keys, DEBUG, hosts, TLS and cookie settings.
3. Enforce connector destination allowlists/resolved-IP checks and least-privileged source access.
4. Apply SQL AST/identifier/read-only/tenant policy to every execution path; prohibit raw visualization SQL.
5. Scan history/images/dependencies; coordinate removal of tracked generated data separately from user work.
6. Test upload/scanner failures, sensitive-log redaction, token leaks and direct-port denial.

**Acceptance/tests:** zero unresolved critical/high security blockers; provider rotation evidence; scoped grants verified. **Rollback:** staged key rotation with short compatibility window; security revocation is not undone merely to simplify rollback.

## R11 — Production infrastructure and data durability

**Goal/why:** reproducible, persistent and recoverable deployments. **Services/files:** Dockerfiles, Compose production/dev overlays, entrypoints, migration scripts and backups. **DB impact:** persistent SurrealDB and Metabase app DB; private media stores, restore strategy and retention. **API changes:** none beyond health semantics. **Dependencies:** R3/R9/R10. **Risks:** incompatible persisted formats, migrations on concurrent startup and unavailable models.

Tasks:
1. Pin compatible image digests and Python locks; upgrade unsupported Django through tested increments.
2. Use non-root production servers, .dockerignore, resource limits, restart/shutdown behavior and separate one-shot migrations.
3. Replace machine-specific model mount paths with documented cache/bootstrap provisioning and version checks.
4. Migrate preserved Metabase H2 through the supported exact-version path; enable persistent SurrealDB and restart/read test.
5. Declare private storage ownership and backup schedules; restore application DB, metadata and files as a consistent set.
6. Implement initial retention for staging/quality/logs and monitor capacity; preserve business retention requirements separately.

**Acceptance/tests:** clean install and repeat deploy work from locked artifacts; all durable stores survive restart/recreation; restoration meets agreed RPO/RTO. **Rollback:** retain previous images and version-compatible data backup; rehearse rollback before storage-format upgrades.

## R12 — Integration, contracts and deployment gates

**Goal/why:** replace isolated passing tests with evidence that the platform works and isolates tenants. **Services/files:** service tests, OpenAPI contracts, frontend tests, CI workflows and disposable fixtures. **DB impact:** private disposable test databases/volumes only. **API changes:** contracts frozen per version. **Dependencies:** R3-R11 increments; run tests throughout, not only at the end. **Risks:** false confidence from mocks and tests touching developer data.

Tasks:
1. Repair ETL imports/UTF-16 collection and fixture mismatch failures; investigate AI semantic/forecast/chart contracts against product intent.
2. Add owner-service integration tests with real disposable PostgreSQL/ClickHouse and mocked outbound email/provider boundaries.
3. Cover create user/workspace → upload → ingestion → query → report/page → embed and delete/retention workflow.
4. Cover all tenant denial, auth expiry, retry-idempotency, timeout-after-commit, malformed dependency responses and unavailable services.
5. Gate PRs on lint, unit/security/contracts, Compose/build checks, migration validation, secret/advisory scan and artifact provenance.

**Acceptance/tests:** all critical workflows and denial cases pass in CI; failures block deployment; published artifacts identify source/lock/image versions. **Rollback:** test environment teardown must never target application/backup resources.

## R13 — Production readiness validation

**Goal/why:** make a release decision from observed behavior. **Services/files:** production manifest, readiness checklist, on-call/restore/runbooks and release evidence. **DB impact:** final grants/backups/capacity verification. **API changes:** none; documented contracts. **Dependencies:** all previous acceptance gates. **Risks:** configuration differences and untested operational procedures.

Tasks:
1. Deploy locked artifacts to isolated staging with production-like network/secret policy and sanitized data.
2. Run the full integration/security suite and modest concurrency/load tests for expected initial usage; measure p95 and job queue age.
3. Conduct dependency failure, process restart, rolling deployment and backup restore drills.
4. Confirm no foreign DB access or non-HTTP business paths, no internal public ports, and all critical/high issues resolved with evidence.
5. Review resource/cost budgets, alerts, support ownership, RPO/RTO and rollback trigger criteria; issue a release decision.

**Acceptance/tests:** PRODUCTION_READINESS_REPORT changes to READY only with linked evidence for every blocker. **Rollback:** tested release rollback with compatible schema and data plan; restore only under a controlled write freeze.

The order is intentionally interleaved where dependencies demand it: R5 owner contracts begin before R3/R4 cutovers, and urgent R8/R10 security containment occurs in P0. Phase labels are workstreams, not permission to defer known critical vulnerabilities.
