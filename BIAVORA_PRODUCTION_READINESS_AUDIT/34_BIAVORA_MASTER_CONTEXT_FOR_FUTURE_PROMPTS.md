# BIAVORA master context for future prompts

Revision 3.1 · Product Scope revision **2026-10-27** · Public launch target **10 January 2027**.
Read this first, then [43](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md), [45](45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md) and the task-relevant architecture/evidence. This is a production SaaS plan, not a demo. **Production NO-GO today.**

## Authority and current state

Precedence: 43 scope/calendar → this context → 22/30/31/32/33 and accepted ADRs → 20 register → latest applicable Foundation reports → historical reports. 44/46 govern presentation detail; 45 traces scope. Later plans supersede commitments, never facts. Old Week-14 plans and readiness percentages are historical; [48](48_DOCUMENTATION_INVENTORY_AND_SCOPE_REFERENCES.md) classifies retained references.

Original scope-reconciliation baseline: `foundation-c-staging`, `9ed2439512179b032736c6f1917521fb7c0dce71`, only pre-existing dirty TimesFM at that earlier entry. The CI-repair entry already includes the unstaged scope reconciliation; see 49. Preserve user work and never stage/reset/clean/edit/commit `services/ai-service/forecasting/timesfm`. The prior scope reconciliation is preserved; the current run repairs CI/test fixtures and updates sequencing only. No commit/push or Foundation-D implementation.

- Foundation-A: CLOSED / scoped GREEN, BIA-001/002/010, report 36.
- Foundation-B: CLOSED / scoped GREEN, BIA-003/006/011, report 37. Payment containment is not a real paid checkout.
- **Foundation-C Local Engineering: CLOSED. Foundation-C External Deployment Validation: DEFERRED_TO_PRODUCTION_READINESS. Production Readiness: NO-GO.**
- BIA-005/014/030 and BIA-018 DNS local defects remain CLOSED. BIA-008 implementation is LOCAL ENGINEERING COMPLETE, but the issue remains technically PARTIAL until deployment proof; that proof is DEFERRED_TO_PRODUCTION_READINESS under CAP-14.
- Managed external secret store/KMS, deployed workload identities and real identity rotation, stable controlled public egress, customer-like PostgreSQL TLS verify-full and allowlist proof, combined full public production-policy ETL, deployed Kafka v1 backlog/drain attestation, and deployment cutover/rollback proof remain mandatory under CAP-14 before public GO. Previous remote run: **FAILED** (owner-reported Auth production environment and Security Regression dependency conflict). Fix implemented locally; new remote verification: **PENDING_PUSH_AND_RUN**. No repaired remote GREEN is claimed.
- Kafka v1 is TRANSITIONAL: production producer cutoff in code, reader default OFF with bounded replay; actual deployed backlog unknown.
- BIA-009 jobs skeleton is unwired/broken; active Voice/AI is request-bound. BIA-019/020/021 provider fragmentation/false-success/schema access, metering and production runtime/operations remain open.

## Final scope

1. Foundation / Production Hardening.
2. Multi-Database Integration.
3. PostgreSQL CDC.
4. Semantic Layer & Metrics.
5. Semantic Modeling Agent.
6. Analyst Agent.
7. Trust & Explainability.
8. Data Reliability Agent — Limited.
9. MCP Actions with Human Approval — Limited.
10. What-if Analysis.
11. AI Presentation & Executive Report Generation.
12. AI Evaluation & Security Testing.
13. Quota / Metering evolution.
14. Production Deployment / Operations Readiness.

**OUT OF JANUARY 10 RELEASE SCOPE:** Structured & Unstructured RAG; Proactive Monitoring Agent; Arabic & Voice Support expansion. Preserve existing voice, language behavior, security fixes and tests. No new Knowledge/vector service, dialect/RTL milestone or proactive business-investigation loop. Operational alerts remain required.

Keep existing seven snapshot adapters plus guarded CSV/XLSX/SQLite import. PostgreSQL is the sole mandatory CDC engine. PostgreSQL direct production requires C external proof; ClickHouse-source is optional after its own proof. MySQL/MariaDB/MSSQL/Oracle direct production remain blocked until pinning plus verified hostname certification. SQLite is a private-file import, not network CDC. Never infer production support from registry or historical non-TLS snapshots.

## Non-negotiable architecture

Query alone authorizes and executes analytical queries: trusted workspace/actor, logical dataset IDs, exact nonempty table allowlist, read-only resource/time/row/byte/memory/concurrency/cancel policy. AI/Voice/Report/Presentation/Visualization/providers/MCP never gain arbitrary database access. Existing Metabase downstream rendering of Query-authorized definitions is a bounded compatibility path requiring least-privilege/tenant certification, not independent analytical authority.

Logical ownership precedes physical service/database separation; one managed PostgreSQL cluster with owner schemas/roles is acceptable. HTTP is control plane; Kafka is data/event pipeline. Integration in Query owns DataSource, encrypted/versioned credentials, transport and lifecycle; Query Dataset is separate. A persisted source is not a permanent TCP socket. No reusable customer passwords/ciphertext in new Kafka source events. Direct connections require TLS, DNS revalidation/pinning, SSRF policy, controlled egress and least privilege.

Semantic owns published business definitions. Modeling proposes → validates → explains → human approval → version/publish. One Analyst orchestrator uses authorized typed tools, durable jobs, budgets and evidence; no unrestricted agent. ModelProvider is an internal facade with per-call token/cost/version telemetry. Preserve deterministic compiler/planner and VisualizationSpec.

## Ownership and presentation

Auth owns identity; Workspace owns membership/roles. Integration owns sources/credentials; Query owns dataset bindings/analytics. Data Platform owns Connector, snapshot/CDC, Transformer/Loader and scoped metadata. Semantic and Analyst are logical AI/control modules with explicit persistence ownership. Voice maintains existing input and legacy saved-report lifecycle. Report is currently a proxy; **new Presentation logical domain is co-deployed in Report** with owned schema/worker and API references to legacy reports. Do not silently activate duplicate report ORM models, move legacy tables, delete Report or create a Presentation microservice. ADR-023 in 46 explains the decision.

BIAVORA analysis → metrics → evidence → charts/narrative → PresentationSpec → egress/policy/approval → PresentationProvider → artifact.

```text
PresentationProvider
├── SlidesGPTProvider
└── GammaProvider
```

MCP-first when suitable, optional official Gamma REST transport; transport independent of analytical domain. Official contracts/auth/export/privacy/cost must be reverified before implementation and certified before enablement. Both adapters/conformance are required; at least one live certified export path is launch-required. No self-built slide/PPTX engine.

Providers receive only minimum approved aggregates, safe labels/assets and sanitized narrative/evidence summaries; never credentials/refs, tokens, internal URLs, physical table names or dumps. Exact approval for policy-controlled egress; explicit create intent can suffice only for policy-preapproved safe creation. January MCP acceptance includes a real approval-required deck path. Unknown remote dispatch must reconcile before retry/failover. Private artifacts require current authorization, safe fetch/validation, retention/deletion and factuality checks.

Never invent causes. Distinguish observed facts, contributions, correlation, likely drivers and causal conclusions. Label OBSERVED, FORECAST and SCENARIO; retain metric/data/query/result/method evidence.

Entitlements, Metering, Billing and Payments stay separate. Tokens, analytical/forecast work, provider credits/cost, presentation/export/actions and maintained voice usage feed an idempotent reserve/commit/release/adjustment ledger. Paid launch is disabled unless real hosted payments and signed reconciled webhooks pass.

## Order and exact next action

**P0 C local closure + current CI GREEN → P1 PostgreSQL CDC + durable/scoped AI spine → P2 Semantic → P3 Modeling and policy/evidence/metering → P4 Analyst + bounded Trust/What-if/Reliability + egress/approval → P5 Presentation → P6 convergence → P7 quality/security/ops freeze → P8 staging RC → 10 January GO/NO-GO.**

Foundation-D local implementation requires Foundation-C Local Engineering CLOSED, the required current release CI GREEN, and no A/B/C local-security regression. The local closure record does not satisfy the separate remote CI condition. Until the repaired workflow runs successfully, that condition is pending. External deployment validation gates production certification, not local Foundation-D development. All later semantic/Analyst/Presentation/egress prerequisites remain unchanged.

**Next implementation phase: Foundation-D — PostgreSQL CDC.** Check current release CI GREEN before local implementation; do not provision staging first. [49](49_FOUNDATION_C_LOCAL_CLOSURE_AND_CI_REPAIR_REPORT.md) records local closure and the CI repairs. CAP-14 checkpoints are operator/platform plan by 16 November, environment/probes by 29 November, G-C-DEPLOY by 15 December; final candidate evidence is still mandatory before January 10 GO.

Each phase needs implementation/review, tests, security, docs, migrations as applicable, telemetry, CI, acceptance/staging proof and rollback. Only immutable-candidate evidence closes release gates. Supported dependencies, production servers/non-root images, backups/restore, migrations/rollback, alerts/runbooks/support, tenant/secret correctness and cost controls are mandatory. A missed checkpoint triggers re-estimation; reduce optional depth before safety and never silently drop a promised launch capability.
