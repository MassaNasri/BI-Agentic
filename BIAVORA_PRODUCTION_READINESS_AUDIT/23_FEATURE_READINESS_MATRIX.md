# 23 — Reconciled Feature Readiness Matrix

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

## Method

`Current Implementation` estimates how much of the user-facing capability exists. `Production Readiness` asks whether the existing portion is secure, tested, operable, recoverable, and supportable for real tenants. `Week-14 Target` is the minimum engineering index expected at release; it is not permission to waive a hard gate. An absent planned feature scores low but is not labeled a defect. The unweighted scope averages are **24% implementation** (`380/16 = 23.75`) and **18% production readiness** (`286/16 = 17.875`). The target average is **83%** (`1320/16 = 82.5`). Whole-platform production readiness is separately **36%**.

| Capability | Current Implementation | Production Readiness | Week-14 Target | Production blockers | Dependencies | Owner | Planned week |
|---|---:|---:|---:|---|---|---|---|
| Multi-DB + CDC | 50% | 42% | 85% | No CDC/recovery certification; source lifecycle/secret issues | Integration owner, transport, Kafka contracts, CH loading | SE | W2–6 |
| Semantic Layer | 20% | 15% | 85% | No persistent governed/versioned semantics | Ownership, Query bindings, migrations | BOTH | W5–8 |
| Semantic Modeling Agent | 0% | 0% | 80% | Planned feature; review/publish workflow absent | Semantic API, eval, durable jobs | AI | W6–8 |
| Trust / Explainability | 30% | 22% | 85% | Debug traces are not permissioned answer evidence | Query/semantic versions, freshness, RAG citations | AI | W6–10 |
| Analyst Agent | 20% | 12% | 80% | Fixed pipeline, broad AI data access, no governed tools/jobs | Query Tool, semantic, provider facade, eval | AI | W7–10 |
| Structured + Unstructured RAG | 0% | 0% | 80% | Planned feature; no document ACL/index/citation lifecycle | pgvector, document owner, object storage, eval | AI | W7–9 |
| Proactive Monitoring Agent | 5% | 3% | 75% | No governed metric schedule/investigation/alert lifecycle | Semantic, reliability signals, jobs, alerts | AI | W9–11 |
| Arabic + Voice | 30% | 18% | 80% | No Arabic benchmark/RTL production journey; upload unsafe | Eval corpus, upload controls, provider facade, frontend | AI | W1, W7–11 |
| Limited Data Reliability Agent | 40% | 30% | 80% | Signals exist but no scoped product/incident workflow | CDC telemetry, semantic metrics, alerting | BOTH | W8–11 |
| Limited MCP Actions | 0% | 0% | 75% | Planned feature; no policy/approval/tool gateway | Analyst, identity, audit, secret isolation | BOTH | W9–11 |
| What-if Agent | 30% | 18% | 75% | Forecast pieces exist; no reproducible scenario contract | Semantic metrics, forecast evaluation, Trust | AI | W9–11 |
| AI evaluation/testing framework | 30% | 22% | 90% | Strong deterministic tests but no versioned model-quality gate | Provider facade, corpora, registry, CI budget | AI | Starts W1 |
| Full platform security hardening | 35% | 31% | 90% | BIA-001/002/005/006/008/010/011 and infra controls | All platform boundaries | SE+BOTH | W1–14 |
| Production deployment/runtime | 20% | 18% | 90% | Dev servers/root images; no proven staging/recovery/ops | Managed platform, observability, release pipeline | SE | W2, W10–14 |
| Correct ownership/boundaries | 40% | 35% | 80% | Shared schema/roles; blurred Report/Integration ownership | ADR freeze, owner roles, API/events | SE | W1–8 |
| Hybrid metering/subscription | 30% | 20% | 90% | Simulation bypass; counter-only non-idempotent accounting | Telemetry, ledger, entitlements, provider | SE | W1, W9–12 |

## Certification rules

- A target score never overrides a P0, security, recovery, data-correctness, or financial-integrity gate.
- PostgreSQL is the only mandatory production CDC engine. MySQL/MariaDB receive CDC claims only if the same certification suite passes. Other current adapters remain honestly labeled snapshot/incremental.
- Week-14 product breadth is deliberately constrained: one Analyst Orchestrator, one useful approval-gated action, a bounded reliability rule set, governed proactive alerts, and reproducible rather than causal What-if.
- If a feature misses its gate, it must be disabled behind server-side entitlements/capability flags and removed from production claims; core public launch still requires the user-promised Week-14 scope accepted by product leadership.
