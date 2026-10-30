# 29 — Canonical product scope entrypoint

Revision 3.0 · 2026-10-27 · Target public launch: **10 January 2027**.

The authoritative scope, engine matrix, exclusions, priorities, release contract, dates and gates are in [43 — Product scope and release roadmap](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md). This file is an entrypoint, not a second independently maintained roadmap. The prior Week-14 commitments are superseded by Product Scope revision dated 2026-10-27; their historical evidence remains in Git and the dated reports.

The exact fourteen capabilities are Foundation / Production Hardening; Multi-Database Integration; PostgreSQL CDC; Semantic Layer & Metrics; Semantic Modeling Agent; Analyst Agent; Trust & Explainability; Limited Data Reliability Agent; Limited MCP Actions with Human Approval; What-if Analysis; AI Presentation & Executive Report Generation; AI Evaluation & Security Testing; Quota / Metering evolution; and Production Deployment / Operations Readiness.

**OUT OF JANUARY 10 RELEASE SCOPE:** Structured & Unstructured RAG; Proactive Monitoring Agent; Arabic & Voice Support expansion. Existing functionality/security/tests remain maintained. Infrastructure monitoring and bounded reliability warnings are still required.

Query is the sole analytical execution authority. BIAVORA owns analysis, semantics, evidence, charts and narrative; providers own slide composition/rendering/export. `PresentationProvider → SlidesGPTProvider / GammaProvider` is transport-independent. Presentation is a logical domain co-deployed with the existing Report deployment; legacy saved reports stay Voice-owned until a separately governed migration. See [44](44_AI_PRESENTATION_AND_EXECUTIVE_REPORT_ARCHITECTURE.md) and [ADR-023](46_ADR_023_PRESENTATION_OWNERSHIP_AND_PROVIDER_ABSTRACTION.md).

Foundation-A/B have scoped closed gates. **Foundation-C Local Engineering: CLOSED. Foundation-C External Deployment Validation: DEFERRED_TO_PRODUCTION_READINESS. Production Readiness: NO-GO.** Previous remote run: **FAILED** (owner-reported Auth production environment and Security Regression dependency conflict). Fix implemented locally; new remote verification: **PENDING_PUSH_AND_RUN**. No repaired remote GREEN is claimed. Current capability evidence is in 45; the mandatory first read is 34 and current phase-closure policy is in 49.
