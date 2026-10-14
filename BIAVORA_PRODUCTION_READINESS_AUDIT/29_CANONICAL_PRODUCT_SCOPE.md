# 29 — Canonical Product Scope

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

## Product definition

At Week 14, BIAVORA is a publicly deployable, multi-tenant SaaS for small and mid-sized organizations that connect operational databases/files and business documents, govern business metrics, ask analytical questions by text or voice in English or supported Arabic, receive evidence-bearing answers/visualizations/forecasts, monitor a constrained set of reliability/metric conditions, and optionally approve one supported external action.

It is not declared production-ready today. Release occurs only if `PRODUCTION_GATE` passes. “Production deployable” means real tenant/security, runtime, recovery, operational, financial, and release controls—not merely an architecture diagram or demonstration.

## Target customers and load assumption

- Initial customers: SMB/mid-market teams with a modest number of workspaces, production PostgreSQL sources, CSV/supported snapshot sources, business documents, and analyst/admin users.
- Initial deployment: single production region with managed services, tested recovery, and bounded/conservative quotas. Capacity limits are measured and published before launch.
- Regulated/high-assurance, on-premises, data-residency-multiple-region, private-agent-only, and very-high-throughput enterprises are outside the Week-14 promise unless separately contracted and certified.

## WEEK_14_PRODUCTION

### Supported source and ingestion modes

| Engine/source | Snapshot | Continuous CDC | Incremental refresh | Week-14 claim |
|---|---|---|---|---|
| PostgreSQL | Production | **Production, mandatory** | Via CDC/scheduled snapshot as appropriate | Certified only after `CDC_GATE` |
| MySQL | Production snapshot | Conditional | Conditional | CDC only if full PostgreSQL-equivalent certification passes; otherwise snapshot |
| MariaDB | Production snapshot | Conditional | Conditional | CDC only if full certification passes; otherwise snapshot |
| MSSQL | Production snapshot if real environment passes | Not promised | Optional scheduled snapshot | Snapshot-only claim |
| Oracle | Production snapshot if real environment passes | Not promised | Optional scheduled snapshot | Snapshot-only claim |
| ClickHouse source | Production snapshot if acceptance passes | Not promised | Optional strategy | Snapshot source, not BIAVORA CDC claim |
| SQLite | Production snapshot | No enterprise CDC | Scheduled incremental/snapshot where safe | Local/file-style source |
| CSV | Production upload | Not applicable | Re-upload/new version | Type/size/malware/retention controlled |
| Documents | Not tabular ingestion | Not applicable | Versioned re-index | PDF/DOCX/text subset proven by tests |

The production source path is Direct Secure Internet/Cloud Connection with verified TLS, egress policy, timeouts, audit, least-privilege source credentials, and opaque BIAVORA secret references. UI/API capabilities derive from the same server-side registry and cannot advertise uncertified modes.

### Product capabilities

1. **Multi-DB + CDC:** preserves P1-R snapshot connectors; adds certified PostgreSQL CDC, lifecycle/status/lag, deletes, schema policy, restart/reconciliation, and honest capability claims.
2. **Semantic Layer:** workspace-scoped Entity, Metric, Dimension, Relationship, TimeDimension, BusinessTerm, Synonym, Formula, Owner, Version, Status, Certification, and Lineage.
3. **Semantic Modeling Agent:** proposes and explains models; deterministic validation and human approval are mandatory before version/publish.
4. **Trust/Explainability:** answers expose authorized SQL/tables/columns, metric definitions, filters, time range, semantic version, freshness, citations, assumptions, warnings/degraded state, and uncertainty where applicable.
5. **Analyst Agent:** one governed orchestrator with typed tools, durable jobs, step/time/cost budgets, retries/cancellation, and explicit degraded/failure states.
6. **Structured + Unstructured RAG:** structured facts use Semantic/Query; documents use permission-filtered PostgreSQL/pgvector retrieval, citations, versions, deletion/re-index, and injection defenses; hybrid answers label evidence.
7. **Proactive Monitoring:** schedules governed metric checks, verifies data health, investigates within budgets, attaches evidence, and creates alerts; it does not act autonomously.
8. **Arabic + Voice:** tested English and explicitly supported Arabic/RTL user journeys, safe upload/transcription, and published benchmark limits. Unsupported dialect/quality conditions degrade visibly.
9. **Limited Data Reliability:** freshness, ingestion failure, CDC lag, source availability, null/row-count/duplicate/schema drift, and bounded distribution checks.
10. **Limited MCP Action:** at least one useful action path with proposal, deterministic policy, exact human approval, isolated execution, idempotency, verification, and audit.
11. **What-if:** calculation/forecast/scenario are labeled; baseline, assumptions, model, comparison, uncertainty, and reproduction record are mandatory; no unsupported causal claim.
12. **AI evaluation:** versioned English/Arabic voice, intent, schema, text-to-SQL, RAG, tool, safety, forecast/What-if, action, latency, and cost suites gate releases.
13. **Security:** the controls in `33_PRODUCTION_SECURITY_BASELINE.md` pass.
14. **Production runtime:** managed production/staging, immutable non-root images, production process servers/workers, secrets, TLS, health/readiness, graceful drain, resource/rate limits, telemetry, SLO/alerts/runbooks, backup/restore, migrations/rollback, CI/CD and release gate.
15. **Ownership:** critical data owners and roles are enforceable; Query is sole analytical authority; Integration is a logical owner; Report/Visualization responsibilities are unambiguous.
16. **Hybrid metering/subscription:** Entitlements, immutable usage ledger, reservation/commit/release/adjustment, cost attribution, billing state, and a real hosted/tokenized payment path when paid access is enabled.

## Security and deployment baseline

- Organization/workspace membership and role are checked at every object/tool/job/result boundary; tenant IDs from clients are never sufficient authority.
- Product services do not choose physical ClickHouse tables. AI/Voice/Reports/Visualization cannot directly execute analytical SQL.
- Critical PostgreSQL domains use owner schemas/databases and least-privilege roles in a managed cluster; secrets are managed/versioned/rotatable.
- Staging and production are isolated. HTTPS edge, centralized logs/metrics/traces, backups/PITR, restore/rollback rehearsals, rate limits, abuse controls, vulnerability/image gates, and incident ownership are mandatory.
- Single-region production with tested restore is sufficient for launch. Kubernetes and multi-region active-active are not mandatory.

## Metering model

Raw `UsageEvent`s include workspace/job/idempotency, operation type, provider/model/version, LLM input/output/cached tokens and estimated cost, voice seconds/model/compute, embedding/indexing usage, agent/tool/expensive operations, forecast series/horizon/model, and optionally processed data volume where pricing needs it. An immutable ledger supports reservation, commit, release, adjustment, retries, concurrency, price versions, reconciliation, and audit. Entitlements consume ledger-derived state; payment webhooks drive Billing State, not direct UI claims.

## Operational expectations

- Published SLOs cover authentication, source health/ingestion, query/analysis jobs, alert/action delivery, and billing/usage integrity.
- Every long operation is observable and durable; every critical alert has owner/runbook; capacity and cost ceilings are documented.
- Recovery evidence covers PostgreSQL, ClickHouse/rebuild strategy, object/doc storage, Kafka durability/replay, semantic state, job state, and usage ledger.
- Customer-visible status, support/escalation, retention/deletion, and incident communication procedures exist.

## POST_LAUNCH

- Certify MySQL/MariaDB CDC if not completed by Week 14.
- Add source private-network transport and customer-hosted agent.
- Add document types/languages, actions, reliability checks, and richer proactive workflows based on evidence.
- Extract Integration, Model Gateway, or vector storage into separate deployments only for measured security/scale/ownership reasons.
- Improve frontend chunking/performance and broaden Arabic dialect benchmarks.

## FUTURE_ENTERPRISE

- Multi-region active-active and advanced disaster recovery.
- Customer-managed keys, private link/VPN/on-prem agent, advanced data residency and regulated-industry controls.
- Enterprise SSO/SCIM and fine-grained policy extensions beyond the initial production contract.
- Broad action marketplace, multi-agent specialization, causal inference products, and full enterprise data-observability platform.
- Dedicated vector database, service mesh, or Kubernetes only when benchmarks/operations justify them.

## Explicit non-goals for Week 14

True CDC for every engine; unrestricted autonomous agents/actions; auto-published semantics; embeddings for all structured facts; causal claims from correlation; raw card storage/CVV processing; one physical database server per service; one Docker service per logical capability; multi-region active-active; and hiding failed gates behind optimistic marketing.
