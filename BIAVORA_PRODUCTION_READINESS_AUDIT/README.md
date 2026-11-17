# BIAVORA canonical release blueprint

Revision 3 / 2026-10-27. **Target: 10 January 2027. Current production decision: NO-GO.**
Foundation-A/B are CLOSED within their recorded scope. **Foundation-C Local Engineering: CLOSED. Foundation-C External Deployment Validation: DEFERRED_TO_PRODUCTION_READINESS. Production Readiness: NO-GO.** Previous remote run: **FAILED** (owner-reported Auth production environment and Security Regression dependency conflict). Fix implemented locally; new remote verification: **PENDING_PUSH_AND_RUN**. No repaired remote GREEN is claimed.

## Start here and precedence

Read [34 — Master context](34_BIAVORA_MASTER_CONTEXT_FOR_FUTURE_PROMPTS.md) before implementation.
Authority: **43 scope/calendar → 34 context → current architecture/rules/security and accepted ADRs → 20 debt → applicable Foundation evidence → historical reports**. Planning never overrides observed facts. Next implementation phase: Foundation-D — PostgreSQL CDC, after current required CI GREEN and preserved local A/B/C boundaries. External C proof is CAP-14, due before public release. See 49; no staging provisioning first.

| Current document | Purpose |
|---|---|
| [43 — Product scope and release roadmap](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md) | Exact 14 capabilities, engine matrix, exclusions, P0/P1/P2, phases, dependencies and launch gates |
| [44 — Presentation architecture](44_AI_PRESENTATION_AND_EXECUTIVE_REPORT_ARCHITECTURE.md) | Internal analysis/evidence, provider-neutral spec, egress, approval, artifacts, factuality, tests and rollout |
| [45 — Release traceability](45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md) | Every capability's owner, current state, dependencies, tests and deployment proof |
| [46 — ADR-023](46_ADR_023_PRESENTATION_OWNERSHIP_AND_PROVIDER_ABSTRACTION.md) | New Presentation domain in Report deployment; legacy Voice ownership preserved |
| [49 — Local closure and CI repair](49_FOUNDATION_C_LOCAL_CLOSURE_AND_CI_REPAIR_REPORT.md) | Current local closure decision, CI fixes/results and deferred deployment gates |
| [47 — Historical reconciliation report](47_SCOPE_ARCHITECTURE_RECONCILIATION_REPORT.md) | Repository baseline, changes, conflicts, risks and validation |
| [48 — Inventory and retained references](48_DOCUMENTATION_INVENTORY_AND_SCOPE_REFERENCES.md) | Document classification, review coverage and every old-scope match |
| [20 — Debt register](20_TECHNICAL_DEBT_AND_PROBLEM_REGISTER.md) | Stable BIA IDs, scoped closures, residual launch risks |
| [22 — Target architecture](22_TARGET_ARCHITECTURE.md) | System/owner/analytical/CDC/MCP diagrams and implementation gaps |
| [23 — Readiness entrypoint](23_FEATURE_READINESS_MATRIX.md) | Redirect to evidence-based capability matrix; historical scores retired |
| [24 — ADR register](24_ARCHITECTURE_DECISION_RECORDS_NEEDED.md) | Required/deferred decisions, including ADR-023 |
| [25 — Roadmap entrypoint](25_14_WEEK_IMPLEMENTATION_ROADMAP.md) | Legacy filename retained; dated roadmap in 43 supersedes rolling weeks |
| [26 — Implementation map](26_MASTER_REFACTOR_BUILD_DELETE_PLAN.md) | Stable MAP IDs, sequencing, maintained controls and deferred cleanup |
| [29 — Product scope entrypoint](29_CANONICAL_PRODUCT_SCOPE.md) | Approved scope/exclusions; details in 43 |
| [30 — Architecture rules](30_CANONICAL_ARCHITECTURE_RULES.md) | Mandatory ownership, Query, jobs, AI, security and release rules |
| [31 — Ownership map](31_CANONICAL_SERVICE_OWNERSHIP_MAP.md) | Actual owners versus intended domain placement |
| [32 — AI architecture](32_CANONICAL_AI_ARCHITECTURE.md) | Single governed Analyst, Semantic/Trust/tools/evaluation/provider facade |
| [33 — Security baseline](33_PRODUCTION_SECURITY_BASELINE.md) | Current hard gates, egress/approval/artifact and operating security |

## Historical evidence and superseded plans

Reports **36–42** remain unchanged evidence; 42 records the historical C6 assessment, while 49 records the current local-closure decision. Reports **00–07, 15–19, 27 JSON, 28, 35 and 47** remain historical snapshots, not today's scope, percentages or release checklist. In particular **27_FINAL_AUDIT_RESULTS.json is historical**, not a current machine-readable production result. Their original claims are qualified by their date and scope.

Supporting plans **08–14 and 21** and the earlier `docs/audit` planning documents are explicitly marked superseded. Their retained bodies explain earlier design thinking; they cannot add January requirements. Remediation/P1/P1-R and ETL implementation reports remain evidence of the specific tests/features recorded, not full launch certification. Operational reference docs still require revalidation against deployed topology. See 48 for the file-by-file inventory.

**Structured & Unstructured RAG, Proactive Monitoring Agent, and Arabic & Voice Support expansion are OUT OF JANUARY 10 RELEASE SCOPE.** Existing code, Voice functionality and security regressions remain maintained. Infrastructure monitoring/alerts remain mandatory.

Query is the sole analytical authority. HTTP remains control plane; Kafka remains asynchronous data/event plane. PresentationProvider has SlidesGPTProvider and GammaProvider adapters, independent of MCP/REST transport. BIAVORA computes facts/evidence/storyline; vendors render. A future implementation must use 43/45 gates and may not infer readiness from an old GREEN, filename, class, or dependency.
