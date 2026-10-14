# 16 — Production Readiness and SRE Audit

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

## Reconciled verdict

BIAVORA is **NO-GO for public production today**. Its recalculated production-readiness index is **36/100**. This score was recomputed against a public multi-tenant SaaS definition, not copied from v1. Working snapshot ingestion, deterministic tests, basic workspace checks, health endpoints, image builds, and release-gate assets provide a useful base. Verified security boundaries, production runtime, durability, recovery, and operating evidence remain incomplete.

| Dimension | Current | Week-14 release floor | Principal gap |
|---|---:|---:|---|
| Architecture/ownership | 36 | 85 | Shared roles/schema, blurred source/report ownership |
| Backend/API | 50 | 85 | Fail-open query, synchronous flows, resource limits |
| Frontend/product | 40 | 80 | Arabic/RTL and production journeys incomplete |
| AI governance | 32 | 80 | Fragmented providers, broad data access, no eval gate |
| ETL/data movement | 57 | 85 | Snapshot strong; CDC/recovery not implemented |
| Data governance | 38 | 85 | No governed semantic/knowledge lifecycle |
| Security | 31 | 90 | Tenant, secrets, infra identity/TLS, upload controls |
| Testing/release | 54 | 90 | Real-system, recovery, abuse, supply-chain gates |
| Observability | 23 | 85 | No owned SLO/dashboard/alert/on-call system |
| Deployment/runtime | 18 | 90 | `runserver`, root images, dev Compose topology |
| Reliability/recovery | 25 | 85 | No proven restore, durable job, reconciliation drills |
| Scalability/capacity | 22 | 75 | Unbounded query/materialization and no load evidence |
| Documentation/runbooks | 46 | 85 | v2 reference exists; implementation runbooks do not |

The unweighted arithmetic mean is `472 / 13 = 36.3`, rounded to **36**. Documentation improves because this v2 reference exists; stricter production criteria reduce several other dimensions. Feature readiness is separately scored in `23_FEATURE_READINESS_MATRIX.md`.

## Verified runtime evidence

- First-party Dockerfiles and ETL start scripts launch Django `manage.py runserver`; no first-party Dockerfile declares a non-root `USER`.
- Root Compose exposes numerous application and infrastructure ports and supplies shared ClickHouse/SurrealDB credentials; Kafka/Redis/ClickHouse do not yet demonstrate production service identity and encrypted transport.
- Stateful dependencies are single local containers. This is a development integration environment, not the Week-14 production topology.
- Query executes ClickHouse without authoritative max time/rows/bytes/memory settings and materializes full result sets.
- Voice and AI/report work remains request-bound. `VoicePipelineJob` exists, but its orchestration references missing modules and is not wired to active routes/workers.
- Manual Kafka commit/rewind paths are a strength; schema-invalid records are skipped before being yielded and have no explicit DLQ/terminal policy.
- The maintained audit test snapshot passed 1,464 tests plus 17 Node subtests, with 17 expected external integration skips; that is regression evidence, not production operating proof.

## Practical Week-14 deployment choice

Use a managed container platform rather than introducing Kubernetes by default. Use managed PostgreSQL with automated backups/PITR, managed Redis, managed Kafka or a supportable Kafka offering, managed/object storage, a production ClickHouse deployment, a secrets manager, HTTPS edge/WAF, container registry, centralized logs/metrics/traces, and isolated staging/production accounts or projects. Kubernetes is justified only if the chosen platform cannot meet workload, GPU, networking, or operations requirements.

Multi-region active-active, customer VPN/agent transport, and zero-RPO cross-region recovery are post-launch. Tested single-region recovery, restore objectives, rolling/blue-green deploy, and rollback are release requirements.

## Production Deployment Definition of Done

Public release is allowed only when all items below have evidence attached to the release record.

### Security and tenancy

- Query is the only analytical executor; exact workspace/dataset/table binding is checked server-side and enforced in SQL policy and ClickHouse settings.
- Voice, AI, Reports, Visualization, and workers have no direct analytical fallback or broad ClickHouse credential.
- Auth and Workspace authorization negative tests pass; critical PostgreSQL owners use separate roles/schemas and default-deny cross-domain writes.
- Historical secrets are rotated and invalidated; runtime secrets come from a secrets manager with owner, version, and rotation procedure.
- Internet source connectivity uses TLS verification, egress allow policy, DNS revalidation/pinning strategy, timeouts, and auditable secret references.
- Upload type, magic bytes, size, decompression, malware/quarantine, retention, deletion, and tenant storage boundaries are enforced.
- Distributed rate limits and abuse controls cover auth, uploads, query, AI, RAG indexing, jobs, and action approvals.

### Runtime and operations

- Images are immutable, scanned, dependency-locked, non-root, read-only where practical, and run production WSGI/ASGI/worker processes with graceful drain.
- Staging mirrors production contracts. Production has HTTPS/domain readiness, network segmentation, least-privilege identities, health/readiness probes, resource requests/limits, autoscaling policy, and capacity evidence.
- Logs, metrics, traces, SLOs, dashboards, alerts, runbooks, and an accountable responder exist for critical user journeys.
- PostgreSQL, ClickHouse, object/document storage, Kafka durability, semantic data, and metering ledgers have documented and successfully rehearsed backup/restore procedures with recorded RPO/RTO.
- Forward migration and rollback/roll-forward are rehearsed from a production-like snapshot. Deployment and incident rollback are documented and tested.

### Product correctness

- PostgreSQL snapshot + CDC passes initial snapshot, update/delete, restart, duplicate, schema change, lag, reconciliation, credential rotation, and outage recovery tests. Only separately certified engines are advertised for CDC.
- Durable jobs prove idempotent retry, cancellation, terminal states, result references, and no false `SUCCEEDED` outcome.
- Semantic versions, RAG ACL/citations/deletion, Analyst tool policy, trust evidence, constrained reliability/proactive behavior, What-if assumptions, and one approved MCP action pass their gates.
- Provider, voice, embedding, forecasting, and tool telemetry flows to an immutable metering ledger. Reservation/commit/release is concurrency- and retry-safe.
- Simulated checkout cannot activate production access. If paid launch is enabled, a hosted/tokenized provider, verified webhook flow, reconciliation, refund/failure states, and billing runbook pass staging tests.

### Release governance

- CI passes unit, contract, integration, tenant-negative, security, dependency/image, migration, frontend, AI evaluation, and CDC suites.
- Staging passes load/soak, dependency-failure, backup restore, alert, billing, and rollback drills against signed image digests.
- No open P0 exists; release-accepted P1/P2 risks have owner, expiry, mitigation, and are not tenancy/data-loss/financial-integrity exceptions.
- Product claims match the certified engine/capability matrix. Operations, security, and product owners sign `PRODUCTION_GATE`.

## Gates

`FOUNDATION_GATE -> CDC_GATE -> SEMANTIC_GATE -> AI_AGENT_GATE -> SECURITY_GATE -> STAGING_GATE -> PRODUCTION_GATE`

Implementation completion alone never closes a gate. Required evidence includes tests, threat/authorization checks, telemetry, migration, rollback/recovery where relevant, documentation, and owner approval.
