# 29 — Canonical product scope entrypoint

Revision 3.0 · 2026-10-27 · Target public launch: **10 January 2027**.

The authoritative scope, engine matrix, exclusions, priorities, release contract, dates and gates are in [43 — Product scope and release roadmap](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md). This file is an entrypoint, not a second independently maintained roadmap. The prior Week-14 commitments are superseded by Product Scope revision dated 2026-10-27; their historical evidence remains in Git and the dated reports.

The exact fourteen capabilities are Foundation / Production Hardening; Multi-Database Integration; PostgreSQL CDC; Semantic Layer & Metrics; Semantic Modeling Agent; Analyst Agent; Trust & Explainability; Limited Data Reliability Agent; Limited MCP Actions with Human Approval; What-if Analysis; AI Presentation & Executive Report Generation; AI Evaluation & Security Testing; Quota / Metering evolution; and Production Deployment / Operations Readiness.

**OUT OF JANUARY 10 RELEASE SCOPE:** Structured & Unstructured RAG; Proactive Monitoring Agent; Arabic & Voice Support expansion. Existing functionality/security/tests remain maintained. Infrastructure monitoring and bounded reliability warnings are still required.

Query is the sole analytical execution authority. BIAVORA owns analysis, semantics, evidence, charts and narrative; providers own slide composition/rendering/export. `PresentationProvider → SlidesGPTProvider / GammaProvider` is transport-independent. Presentation is a logical domain co-deployed with the existing Report deployment; legacy saved reports stay Voice-owned until a separately governed migration. See [44](44_AI_PRESENTATION_AND_EXECUTIVE_REPORT_ARCHITECTURE.md) and [ADR-023](46_ADR_023_PRESENTATION_OWNERSHIP_AND_PROVIDER_ABSTRACTION.md).

Foundation-A/B have scoped closed gates. **Foundation-C Local Engineering: CLOSED. Foundation-C External Deployment Validation: DEFERRED_TO_PRODUCTION_READINESS. Production Readiness: NO-GO.** The Foundation-D entry mission attests current baseline CI **GREEN**. This is owner-provided entry evidence; the unstaged Foundation-D changes have not been pushed or remotely certified. Local checks and their limits are recorded in report 50. Current capability evidence is in 45; the mandatory first read is 34 and current phase-closure policy is in 49.

## Foundation-D implementation evidence - 2026-10-27

**Foundation-D Local Engineering: PARTIAL. Production Readiness: NO-GO.** [Report 50](50_FOUNDATION_D_POSTGRESQL_CDC_IMPLEMENTATION_REPORT.md) records real PostgreSQL -> Debezium -> Kafka -> Data Platform -> ClickHouse -> authorized Query execution. Inserts, updates, deletes, replay, several restarts/outages, rotation, controlled nullable ADD, incompatible-DDL pause, tenant denial and exact reconciliation passed. Automatic Kafka recovery on pinned Debezium 3.4.3 eventually caught up but exceeded the 120-second acceptance budget; the 5,000-row snapshot race exceeded 300 seconds before eventual exact agreement. These are local test observations, not an invented production SLA. G-D remains open; CAP-14 external validation stays DEFERRED_TO_PRODUCTION_READINESS.


## D6 final acceptance - 2026-11-16

**Foundation-D: PARTIAL. G-D: BLOCKED. Production Readiness: NO-GO.** The optimized fresh 5,000-row authorized Query gate passed in 72.641 seconds (three passing runs; median 132.281 seconds), but full-pipeline broker recovery missed 120 seconds and the clean post-interruption candidate timed out. Full local regression and release CI remain incomplete. No release candidate was committed or pushed. See [report 62](62_FOUNDATION_D_FINAL_ACCEPTANCE_AND_RELEASE_REPORT.md) and root FOUNDATION_D_RESULTS.json; historical D0-D5 evidence remains valid in its stated scope.
