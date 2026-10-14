# 30 — Canonical Architecture Rules

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

These rules are mandatory for future implementation plans and reviews. `MUST NOT` has the same force as a failed architecture gate. An exception requires a versioned ADR, threat/operations impact, migration/rollback plan, and canonical-document update before implementation.

## 1. Service and domain ownership

- A business object and its authoritative writes **MUST** have one logical owner, API/event contract, migration owner, and on-call owner.
- Deployment boundaries **SHOULD** follow security isolation, independent scaling, failure containment, or durable team ownership—not nouns.
- Integration/Data Source **MUST** be a logical domain. It **SHOULD** initially be an isolated module/schema in the Query control-plane deployment while connector workers remain in Data Platform.
- Report ownership **MUST** be singular: Query executes; Report owns saved report lifecycle; Visualization owns chart/spec generation.
- A capability **MUST NOT** read/write another owner's tables through ORM models. Read models require an explicit event/materialization contract.
- A new network microservice **MUST NOT** be introduced without an ADR proving benefit exceeds latency, deployment, data, and operational cost.

## 2. Database and data ownership

- Production **MAY** use one managed PostgreSQL cluster.
- Critical domains **MUST** use owner schemas/databases, dedicated least-privilege roles, owned migrations, default-deny grants, backup classification, and tested rollback.
- Auth, Workspace, Query, Integration, and Entitlements/Metering ownership **MUST** be enforceable before public release.
- Physical separation **SHOULD** be incremental after logical ownership and contracts exist.
- Services **MUST NOT** share a privileged application role or mutate another owner's schema.
- Public APIs **MUST** expose logical IDs; physical table/database names **MUST NOT** be client authority.

## 3. Control plane and event/data plane

- REST/HTTP **MUST** remain the normal control plane for create/test/status/authorize/submit/read/cancel operations.
- Kafka/events **MUST** carry CDC records and **SHOULD** carry long-running lifecycle/completion, alerts, usage, and schema-change events.
- HTTP handlers **MUST NOT** hold a request open for unbounded AI, ingestion, indexing, forecast, or action work.
- Teams **MUST NOT** replace suitable HTTP APIs with Kafka merely to appear event-driven.

## 4. Analytical Query authority and ClickHouse

- Query **MUST** be the sole product authority for analytical execution.
- Every request **MUST** derive workspace membership and dataset/table binding server-side, supply an exact non-empty table allowlist, and enforce read-only/resource policy.
- Query **MUST** enforce time, rows, bytes, memory, concurrency, cancellation, pagination/result-reference, and audit controls.
- Voice, AI, Report, Visualization, Gateway, and frontend **MUST NOT** hold a direct analytical ClickHouse credential or fall back to local execution.
- Loaders **MAY** hold separate write-only ingestion identities; those identities **MUST NOT** be usable by product query paths.
- Users/models **MUST NOT** select arbitrary physical databases/tables.

## 5. Integration/Data Source and transport

- Integration **MUST** own engine, connection metadata, opaque secret reference, TLS, transport mode, table selection, capabilities, snapshot/CDC state, and lifecycle.
- Source replacement **MUST** stage/test/snapshot then atomically cut over; prior data **MUST NOT** be destroyed before success and rollback point.
- The initial production mode **MUST** be `DirectSecureInternetTransport` with TLS validation, egress allow policy, DNS resolution/revalidation defense, timeouts, least privilege, and audit.
- Source contracts **MUST** carry a transport discriminator compatible with later private-network/customer-agent modes.
- Production architecture **MUST NOT** depend on localhost, `host.docker.internal`, a developer LAN, or Windows host behavior.

## 6. CDC and Kafka contracts

- PostgreSQL **MUST** be the first certified CDC engine using Debezium + Kafka Connect + Kafka + BIAVORA normalizer.
- Engine capabilities **MUST** distinguish snapshot, CDC, incremental, conditional, and unsupported. Adapter presence **MUST NOT** imply CDC support.
- Events **MUST** include version, tenant/workspace/source/dataset/job identity as applicable, idempotency key, correlation/trace ID, occurred-at, producer, classification, and payload/reference.
- Owners **MUST** define partition key/order, compatibility, retries/backoff, terminal DLQ/quarantine, replay, retention, schema-change, deletion/tombstone, and redaction policy.
- Consumers **MUST** commit only after owned processing succeeds or a documented terminal disposition succeeds; poison records **MUST NOT** spin or disappear silently.
- CDC **MUST** pass snapshot-to-stream handoff, update/delete, duplicate, restart, outage, rotation, schema, lag, reconciliation, and recovery tests before the production claim.

## 7. Long-running jobs

- Voice analysis, large query/report, ingestion, indexing, semantic proposal, forecast/What-if, proactive investigation, and action execution **MUST** use a durable job.
- The canonical states are `QUEUED`, `RUNNING`, `RETRYING`, `SUCCEEDED`, `FAILED`, and `CANCELLED` with validated transitions.
- A job **MUST** store workspace/actor, type/version, idempotency/correlation, attempt, timestamps, deadline/budget, input/result refs, error class, and relevant semantic/model/prompt versions.
- State and event publication **MUST** use a transactional outbox/inbox or an equivalently proven pattern.
- A job **MUST NOT** report success while required downstream work is pending or failed.

## 8. AI provider and permissions

- Active model calls **MUST** go through one in-process `ModelProvider` facade with timeouts, bounded retry, fallback policy, structured outputs, budgets, test doubles, and prompt/model versioning.
- From its first production call, the facade **MUST** emit provider, model, input/output/cached tokens, latency, estimated cost, fallback, prompt/version, workspace/job, and outcome.
- AI **MUST** receive minimum workspace-scoped schema/semantic context via authorized tools and execute via Query Tool.
- AI **MUST NOT** enumerate global ClickHouse schema, hold ClickHouse credentials, read arbitrary tables, bypass entitlements, or treat model output as authorization.
- Prompts/traces **MUST** be classified, permissioned, minimized, redacted, and retained by policy; chain-of-thought **MUST NOT** be exposed or logged as a product requirement.

## 9. Semantic Layer

- The Semantic Layer **MUST** be the governed source for entities, metrics, dimensions, relationships, time dimensions, business terms, synonyms, formulas, ownership, versions, status, certification, and lineage.
- SQL, Analyst, Modeling, Trust, Proactive, RAG orchestration, What-if, Reports, and Visualization **SHOULD** bind to a published semantic version.
- Semantic proposals **MUST** validate permissions/references/types/cycles/ambiguity and follow `PROPOSE -> VALIDATE -> EXPLAIN -> HUMAN REVIEW -> APPROVE -> VERSION -> PUBLISH`.
- AI **MUST NOT** auto-publish business semantics or silently edit a published version.

## 10. RAG and knowledge

- Structured facts **MUST** use Semantic/Query; unstructured business knowledge **MUST** use the Knowledge/RAG path. Hybrid answers **MUST** distinguish evidence.
- PostgreSQL + pgvector **SHOULD** be first; a new vector database requires benchmark/operations evidence.
- Retrieval **MUST** enforce workspace/document permissions before candidate content enters a prompt and again before citations are returned.
- Documents/chunks **MUST** have version, source, ACL, retention, deletion/re-index, metadata filters, and lineage.
- Ingested content **MUST** be treated as untrusted; instructions in documents **MUST NOT** override system/tool policy.
- RAG **MUST NOT** embed all structured warehouse data by default.

## 11. Agents, proactive behavior, reliability, and What-if

- Week 14 **MUST** use one governed Analyst Orchestrator with typed tools and durable state. Multiple conversational agents require later evidence.
- The orchestrator **MUST** enforce tool schemas, authorization, step/time/cost budgets, idempotency, cancellation, and explicit degraded/failure states.
- Proactive flow **MUST** be metric change → data-health check → bounded investigation → evidence → alert → optional action proposal.
- Reliability **MUST** remain constrained to the canonical checks unless separately planned.
- What-if **MUST** label calculation, forecast, scenario, and causal inference; record baseline, assumptions, model, uncertainty, comparison, and reproduction data.
- Models **MUST NOT** claim causality without a validated causal design.

## 12. MCP/actions

- The only allowed write flow is proposal → deterministic policy → exact human approval → isolated Tool Gateway → verified/audited result.
- Approvals **MUST** be actor/workspace/tool/parameters bound, short-lived, single-use, idempotent, revocable, and fully audited.
- The Tool Gateway **MUST** hold scoped third-party credentials, enforce egress/policy, and return structured results.
- AI/orchestrators **MUST NOT** receive write credentials, broaden approved parameters, replay approval, or execute ambiguous/high-risk actions.

## 13. Entitlements, Metering, Billing, and Payments

- These four concepts **MUST** have distinct states and contracts even if initially co-deployed.
- Usage **MUST** be immutable/auditable, workspace/job/idempotency scoped, pricing-versioned, and resource-aware across LLM, voice, embeddings/RAG, agents/tools, forecasting, and relevant data volume.
- Expensive work **MUST** use idempotent `Reservation -> Commit` or `Release`; corrections use append-only adjustments.
- Entitlement decisions **MUST** fail predictably and **MUST NOT** trust a client-provided paid state.
- Simulated payment **MUST NOT** activate production access. Paid launch **MUST** use hosted/tokenized collection, signed idempotent webhooks, reconciliation, and failure/refund states.
- BIAVORA **MUST NOT** store raw PAN/CVV.

## 14. Secrets, tenant isolation, and security

- Secrets **MUST** use managed references, encryption in transit/at rest, version/key ID, rotation, audit, owner, and least-privilege delivery.
- Static derivation salt without key version/rotation **MUST NOT** be the final credential design.
- Workspace authorization **MUST** be rechecked at source, dataset, semantic, document, job, result, report, usage, approval, and action boundaries.
- Internal API keys **SHOULD** be replaced by workload identities/mTLS where platform support exists; shared global keys **MUST NOT** authorize broad lateral access.
- Uploaded and remote content **MUST** be treated as hostile.

## 15. Logging and observability

- Every request/job/event **MUST** carry correlation and trace context without using it as authorization.
- Logs **MUST** be structured, redacted, tenant-safe, bounded, access-controlled, and retention-defined. Raw secrets, tokens, card data, full sensitive rows, or unrestricted prompts/SQL **MUST NOT** be logged.
- Critical journeys **MUST** have service-level indicators/objectives, dashboards, actionable alerts, named owner, and tested runbook.
- Provider cost, query resources, CDC lag/reconciliation, job states, retrieval quality, action approvals, metering reconciliation, and payment webhooks **MUST** be observable.

## 16. Testing and release

- Unit tests **MUST NOT** substitute for tenant-negative, contract, integration, real-provider/environment, CDC recovery, backup/restore, load/soak, migration/rollback, abuse/security, AI evaluation, and billing reconciliation evidence.
- AI evaluation **MUST** start Week 1 and every AI feature **MUST** add versioned cases and thresholds before its gate.
- Release artifacts **MUST** be immutable/scanned, dependency-locked, SBOMed/signed where platform permits, and promoted by digest.
- Product claims **MUST** be generated/reviewed against certified capabilities.
- A fixed deadline **MUST NOT** waive `PRODUCTION_GATE`.

## 17. Production configuration

- Production **MUST** use production WSGI/ASGI/worker processes, non-root containers, graceful shutdown, health/readiness, resource limits, secure secrets, HTTPS/TLS, isolated staging/production, backups/PITR, restore/migration/rollback procedures, observability, rate limits, and CI/CD approvals.
- Stateful production dependencies **SHOULD** be managed when this reduces operational risk for a two-person team.
- Kubernetes **MUST NOT** be required by fashion; choose it only with a documented workload/operations need.
- Local Compose **MUST NOT** be represented as the production architecture.
- Multi-region active-active **SHOULD** remain post-launch unless business/SLO evidence makes it mandatory.
