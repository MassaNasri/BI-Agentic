# 25 — Release roadmap entrypoint (legacy filename)

Revision 3.0 · 2026-10-27 · Target: **10 January 2027**.

The old rolling fourteen-week plan is **superseded by Product Scope revision dated 2026-10-27**. Its filename is retained for existing links. Do not restart at the old Week 1 or use its obsolete feature deadlines.

The single maintained calendar, phase gates, two-engineer allocation, capacity assumptions, checkpoints and scope-freeze rules are in [43 — Product scope and release roadmap](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md). [45](45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md) maps every capability to tests and deployment proof; [26](26_MASTER_REFACTOR_BUILD_DELETE_PLAN.md) maps implementation/debt IDs to that calendar.

Calendar: P0 27 Oct–2 Nov (CI repair and C local closure); P1 3–16 Nov (local PostgreSQL CDC and durable/AI context spine); P2 17–29 Nov (Semantic); P3 30 Nov–6 Dec (Modeling and governance foundations); P4 7–15 Dec (Analyst, Trust, bounded scenarios/reliability, egress/approval); P5 16–23 Dec (Presentation); P6 24–29 Dec (integration); P7 30 Dec–4 Jan (quality/security/operations freeze); P8 5–9 Jan (staging RC); 10 Jan launch only if all gates pass.

The next implementation phase is **Foundation-D — PostgreSQL CDC**. Foundation-D local implementation requires Foundation-C Local Engineering CLOSED, the required current release CI GREEN, and no A/B/C local-security regression. The local closure record does not satisfy the separate remote CI condition. Until the repaired workflow runs successfully, that condition is pending. External deployment validation gates production certification, not local Foundation-D development. Previous remote run: **FAILED** (owner-reported Auth production environment and Security Regression dependency conflict). Fix implemented locally; new remote verification: **PENDING_PUSH_AND_RUN**. No repaired remote GREEN is claimed. CAP-14 external checkpoints: operator plan 16 Nov, environment/probes 29 Nov, G-C-DEPLOY 15 Dec, final candidate proof before public GO. See 49; no staging provisioning now.

Structured & Unstructured RAG, Proactive Monitoring Agent, and Arabic & Voice Support expansion are OUT OF JANUARY 10 RELEASE SCOPE. Existing voice functionality is maintained. Trust, egress, metering, jobs, evaluation and operations precede or accompany dependent features; they cannot be postponed until after provider access.
