# 25 — Release roadmap entrypoint (legacy filename)

Revision 3.0 · 2026-10-27 · Target: **10 January 2027**.

The old rolling fourteen-week plan is **superseded by Product Scope revision dated 2026-10-27**. Its filename is retained for existing links. Do not restart at the old Week 1 or use its obsolete feature deadlines.

The single maintained calendar, phase gates, two-engineer allocation, capacity assumptions, checkpoints and scope-freeze rules are in [43 — Product scope and release roadmap](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md). [45](45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md) maps every capability to tests and deployment proof; [26](26_MASTER_REFACTOR_BUILD_DELETE_PLAN.md) maps implementation/debt IDs to that calendar.

Calendar: P0 27 Oct–2 Nov (CI repair and C local closure); P1 3–16 Nov (local PostgreSQL CDC and durable/AI context spine); P2 17–29 Nov (Semantic); P3 30 Nov–6 Dec (Modeling and governance foundations); P4 7–15 Dec (Analyst, Trust, bounded scenarios/reliability, egress/approval); P5 16–23 Dec (Presentation); P6 24–29 Dec (integration); P7 30 Dec–4 Jan (quality/security/operations freeze); P8 5–9 Jan (staging RC); 10 Jan launch only if all gates pass.

The current phase is **Foundation-D - PostgreSQL CDC: PARTIAL (50)**. Foundation-D local implementation requires Foundation-C Local Engineering CLOSED, the required current release CI GREEN, and no A/B/C local-security regression. The owner attested that baseline entry condition GREEN for this Foundation-D run. New changes require their own reviewed CI result before release. External deployment validation gates production certification, not local Foundation-D development. The Foundation-D entry mission attests current baseline CI **GREEN**. This is owner-provided entry evidence; the unstaged Foundation-D changes have not been pushed or remotely certified. Local checks and their limits are recorded in report 50. CAP-14 external checkpoints: operator plan 16 Nov, environment/probes 29 Nov, G-C-DEPLOY 15 Dec, final candidate proof before public GO. See 49; no staging provisioning now.

Structured & Unstructured RAG, Proactive Monitoring Agent, and Arabic & Voice Support expansion are OUT OF JANUARY 10 RELEASE SCOPE. Existing voice functionality is maintained. Trust, egress, metering, jobs, evaluation and operations precede or accompany dependent features; they cannot be postponed until after provider access.

## Foundation-D implementation evidence - 2026-10-27

**Foundation-D Local Engineering: PARTIAL. Production Readiness: NO-GO.** [Report 50](50_FOUNDATION_D_POSTGRESQL_CDC_IMPLEMENTATION_REPORT.md) records real PostgreSQL -> Debezium -> Kafka -> Data Platform -> ClickHouse -> authorized Query execution. Inserts, updates, deletes, replay, several restarts/outages, rotation, controlled nullable ADD, incompatible-DDL pause, tenant denial and exact reconciliation passed. Automatic Kafka recovery on pinned Debezium 3.4.3 eventually caught up but exceeded the 120-second acceptance budget; the 5,000-row snapshot race exceeded 300 seconds before eventual exact agreement. These are local test observations, not an invented production SLA. G-D remains open; CAP-14 external validation stays DEFERRED_TO_PRODUCTION_READINESS.


## D6 final acceptance - 2026-11-16

**Foundation-D: PARTIAL. G-D: BLOCKED. Production Readiness: NO-GO.** The optimized fresh 5,000-row authorized Query gate passed in 72.641 seconds (three passing runs; median 132.281 seconds), but full-pipeline broker recovery missed 120 seconds and the clean post-interruption candidate timed out. Full local regression and release CI remain incomplete. No release candidate was committed or pushed. See [report 62](62_FOUNDATION_D_FINAL_ACCEPTANCE_AND_RELEASE_REPORT.md) and root FOUNDATION_D_RESULTS.json; historical D0-D5 evidence remains valid in its stated scope.
