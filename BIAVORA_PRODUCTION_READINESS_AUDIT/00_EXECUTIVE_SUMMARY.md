# Executive summary

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

## Reconciled v2 decision

The repository remains a **NO-GO for public production today**, but the implementation target is now a publicly deployable SaaS in Week 14, not a graduation demo. The production-readiness index recalculates to **36%** under stricter production criteria. The Week-14 scope averages **24% implemented** and **18% production-ready**; those feature averages are not interchangeable with whole-platform readiness. Six absent capabilities (CDC, AI evaluation discipline, semantic layer, RAG, governed agent/MCP capabilities, and Arabic product completion) are planned features rather than current defects. The verified tenant-isolation, fail-open query, financial-integrity, ownership, durability, resource-bound, and upload defects remain real blockers.

Canonical decisions are in `29`–`34`; `34_BIAVORA_MASTER_CONTEXT_FOR_FUTURE_PROMPTS.md` is the entrypoint for every future implementation task.

## What BIAVORA is today

BIAVORA is a Docker Compose-based voice/text business-intelligence prototype. It accepts a file or database snapshot, moves rows through a Kafka ETL pipeline into ClickHouse, uses Whisper plus deterministic and LLM-assisted intent/SQL stages, executes analytical queries, and creates Metabase-backed reports. Ten Django business services, six ETL applications, one notification worker process, and ten infrastructure containers are described by the root Compose file.

The platform is best classified as a **distributed modular monolith with event-driven ETL**, not a set of independently owned microservices. The HTTP services share one PostgreSQL database name, account, and physical schema in the supplied environment. Notification reads other domains' tables through unmanaged models. Report-service is an extra HTTP hop that proxies voice-service, while carrying a large, unwired duplicate report implementation. Voice-service orchestrates most of the interactive product in one synchronous request and directly knows AI, query, visualization, subscription, notification, Kafka, ClickHouse fallback, and report persistence.

## Overall health

| Area | Index | Assessment |
|---|---:|---|
| Production readiness | **36%** | Not releasable; tenant, durability, runtime, and recovery blockers remain |
| Week-14 scope implementation | **24%** | Feature implementation only; absence is not automatically a defect |
| Week-14 scope production readiness | **18%** | Current feature slices lack production evidence |
| Architecture/ownership | 36% | Clear components, weak ownership and long synchronous chains |
| Backend/API | 50% | Useful APIs and authorization work; critical query fail-open/isolation defects |
| Frontend/product | 40% | Broad surface; thin tests, monoliths, incomplete Arabic/RTL |
| AI governance | 32% | Rich deterministic pipeline; no governed eval or provider/tool architecture |
| ETL/data movement | 57% | Strongest subsystem for snapshots; not CDC-ready operationally |
| Data governance | 38% | Analytical storage exists; ownership, CDC state, lineage, and bounds are incomplete |
| Security | 31% | Many controls, but tenant, secrets, transport, upload, and payment risks remain |
| Testing/release | 54% | 1,464 maintained tests passed; live, load, recovery, CDC, and AI-quality gates absent |
| Observability | 23% | IDs/metrics/tracing helpers exist; no complete SLO/alert operating system |
| Deployment/runtime | 18% | Development server images and single-node integration infrastructure only |
| Reliability/recovery | 25% | Snapshot recovery pieces exist; interactive jobs, outbox, DR, and replay guarantees do not |
| Scalability | 22% | Synchronous chains, local limits, heavy workers, and single-node state cap safe growth |
| Documentation/runbooks | 46% | Canonical v2 exists; implementation/operator runbooks remain incomplete |

These are engineering indices, not measurements of delivered work. Component evidence and weighting appear in `23_FEATURE_READINESS_MATRIX.md`.

## Biggest strengths

1. A real multi-engine **one-time snapshot** path exists for PostgreSQL, MySQL, MariaDB, SQLite, SQL Server, Oracle, and ClickHouse, with connector capability metadata, selected-table extraction, tenant-qualified destination names, credential redaction, and SSRF destination policy.
2. The maintained offline gate is meaningful: 1,464 tests passed, with focused SQL, tenant, ETL reliability, AI semantic, security, migration-drift, frontend, and build checks.
3. The shared AST SQL guard blocks non-read-only statements, system sources, table functions, multi-statements, comments, formats, and settings clauses.
4. ETL has manual offset commit/rewind, producer acknowledgements and idempotence, bounded in-memory loader buffers, retry/DLQ paths, schema contracts, lineage, quality calculations, and quarantine foundations.
5. AI has structured intent contracts, deterministic planning/compiler logic, schema-aware correction, temporal semantics, trace construction, Whisper queue/idempotency logic, and forecasting fallbacks.
6. Recent P1-R work explicitly and honestly marks CDC as false; the repository does not falsely implement it behind a capability flag.

## Top verified blockers

1. **Cross-tenant ClickHouse reads are possible inside the shared `etl` database.** `execute_sql_payload()` resolves a workspace's database, but constructs `SQLGuard` without `allowed_tables`; table names encode tenants, but knowing another table name is sufficient. Evidence: `query_api/application/query_execution.py`, `workspace_db_resolver.py`, and `bi_platform_shared/sql/guard.py`.
2. **Voice fails open around that boundary.** A query-service network exception invokes voice-service's local ClickHouse executor using the global database, bypassing the authoritative dataset binding. Evidence: `voice_reports/views.py::_execute_query_with_query_service`.
3. **Paid plans are not paid.** The frontend validates card/bank text locally but sends only the payment method; subscription-service immediately creates a successful payment and activates the plan. Evidence: `SubscriptionPlansPanel.jsx` and `subscription/views.py::SubscribeView`.
4. **Critical logical data ownership is not isolated.** Business services receive the same PostgreSQL database/account; Notification directly maps Auth/Workspace/Subscription tables. One managed cluster is acceptable, but critical owner roles/schemas are mandatory.
5. **Data Source / Integration has no safe durable owner.** The Query `Database` model allows one row per manager, carries source configuration/physical identifiers, and replacement deletes old physical data before new success. This is unsafe foundation work, not a reason to create a container per domain.
6. **The active interactive workflow is synchronous/non-durable.** A `VoicePipelineJob` model exists, but the orchestration imports missing modules and is not wired to active routes/workers; required downstream work can remain pending while tasks report success.
7. **Analytical resources are not authoritatively bounded.** Query/Voice execute and materialize full results without a universal max time/rows/bytes/memory/concurrency policy.
8. **The upload boundary is not production-safe.** Voice writes uploaded chunks before backend MIME/magic/size/malware/quarantine/retention enforcement.
9. **Historical secrets require incident closure.** `.env.microservices` exists in Git history; rotation/invalidation evidence is not current. Connector encryption uses a static derivation salt with no key-version lifecycle.

Production runtime, infrastructure identity/TLS, observability, recovery, and supply-chain gates are also release blockers, but may be built in parallel with safe product features. CDC, Semantic, RAG, governed agents/MCP, AI evaluation, and Arabic completion are required **planned features**, not current P0 defects.

## Recommended strategy

Close the nine pre-feature P0s while AI evaluation/provider work proceeds from Week 1. Make Query/identity/source/job boundaries fail closed, disable simulated production checkout, rotate secrets, bound queries/uploads, define critical logical PostgreSQL owners, and establish Integration and usage contracts. Production engineering/telemetry begins immediately; full runtime conversion and staging occur before release.

Build one governed Analyst Orchestrator with typed tools, not a multi-agent network. Reuse snapshot ETL, SQL compiler, visualization, notification, and forecasting foundations. Add a governed versioned semantic model before agent/RAG dependency gates; use SQL for structured truth and RAG for approved unstructured knowledge. Implement/certify PostgreSQL CDC first; advertise MySQL/MariaDB CDC only if the same gate passes; keep other engines honestly snapshot/incremental.

Week 14 includes one genuinely useful approval-gated action and reproducible What-if scenarios with explicit assumptions/uncertainty, not unrestricted writes or causal claims. Safety breadth may be constrained, but production gates may not be waived.

## Release decision

**NO-GO for production today.** A release candidate requires all seven gates in `25`, the Definition of Done in `16`, and the security baseline in `33`. No P0 may remain. PostgreSQL CDC and the final product slices must pass their gates; a planned feature is not “closed” as a defect. Paid activation requires a real provider path or must remain disabled.
