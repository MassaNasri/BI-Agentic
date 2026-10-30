# 26 — Master Refactor, Build, Move, and Delete Plan

> Revision 3 / 2026-10-27. Target: **10 January 2027**. Planning only; no implementation authorization in this reconciliation.
> [43](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md) controls scope/calendar; [45](45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md) controls capability gates. Stable MAP/BIA identifiers are retained.

## Execution rules

SE and AI are the two engineers, with reciprocal review; BOTH means a handoff/review, not extra staffing. Reserve capacity for integration, security and operations. Phase dates and the common Definition of Done are in 43. Each row needs implementation, tests, security review, docs, migrations where applicable, telemetry, CI, acceptance evidence, staging and rollback. Existing closure means preserve and extend evidence, not redo the original defect.

**Next implementation phase: Foundation-D — PostgreSQL CDC.** Foundation-D local implementation requires Foundation-C Local Engineering CLOSED, the required current release CI GREEN, and no A/B/C local-security regression. The local closure record does not satisfy the separate remote CI condition. Until the repaired workflow runs successfully, that condition is pending. External deployment validation gates production certification, not local Foundation-D development. Later Semantic/Modeling/Analyst/Presentation prerequisites remain ordered. Provider access still requires egress/approval/ledger acceptance. External checkpoints and full production gates remain in 43/45.

No deletion is authorized by this map. A later deletion requires imports, routes, Compose, tests, CI, runtime and migrations checked, data/rollback retained, and a separate scoped change. Never alter dirty TimesFM.

## Maintain already-closed controls

| ID / evidence | Target / current state | Owner / phase | Acceptance |
|---|---|---|---|
| MAP-001 | Preserve seven-engine snapshot adapters; certify modes separately, never infer production from registry | SE / P0–P1 | 43 engine matrix and existing regressions agree |
| MAP-002 | Keep manual commit/rewind/idempotency; add poison terminal disposition under CDC | SE / P1 | Restart/duplicate/poison/replay suite |
| MAP-003; MAP-010 / BIA-001 | Exact Query binding, nonempty table allowlist and resource policy CLOSED in Foundation-A | SE / continuous | Cross-tenant/arbitrary-table negatives and deployed authorization |
| MAP-004 | Preserve deterministic compiler/planner behavior under semantic/tool/provider versions | AI / P1–P4 | Golden cases and no bypass |
| MAP-005 | Extend maintained CI, workspace, migration and security regressions | BOTH / continuous | Existing plus new mandatory gates |
| MAP-011 / BIA-002 | Voice local Query fallback removed, CLOSED | SE / continuous | Query outage fails safely; no local execution |
| MAP-012 / BIA-003 | Production payment simulation contained, CLOSED | SE / P0 | Disabled in production; no paid claim without provider gate |
| MAP-013 / BIA-006 | Historical credential incident CLOSED via report 37 evidence | SE / P0 | Preserve attestation/scanner; managed lifecycle remains separate |
| MAP-014 / BIA-010 | Query limits/cancellation CLOSED | SE / continuous | Abuse/concurrency and cancellation regression |
| MAP-015 / BIA-011 | Upload hardening CLOSED | SE / continuous | Scanner, hostile input, limits and retention operate in staging |
| MAP-020 / BIA-005 | Owner-role defect locally CLOSED in C6 | SE / CAP-14 | Exact deployed roles/migrations deny cross-owner access |
| MAP-021 / BIA-008/014 | Integration local engineering complete, replacement CLOSED; BIA-008 technically PARTIAL for deployment evidence | SE / CAP-14 | KMS/store/deployed identities/rotation/public TLS and G-C-DEPLOY by 15 Dec |
| MAP-040 / BIA-008 | Logical Integration now in Query deployment; do not recreate domain | SE / P0 local, CAP-14 external | One source API/write owner; external proof by 15 Dec |
| MAP-042 / BIA-030 | Public physical identifiers locally CLOSED | SE / continuous | Route inventory/logical IDs and new artifact contracts |

## Required implementation sequence

| ID / debt | Action / target | Priority | Dependencies | Owner / phase | Acceptance |
|---|---|---|---|---|---|
| MAP-022 / BIA-009/020 | Replace unwired/synchronous jobs with owned durable state, context, outbox/inbox, cancellation and recovery | P0 | G-C-LOCAL + G-CI | BOTH / P1 | G-J; kill/restart, duplicate, cancellation, no false success |
| MAP-023; MAP-051 / BIA-019 | Consolidate active model calls through in-process provider facade, policy/budget and usage telemetry | P0 | G-C-LOCAL + G-CI; versioned eval cases | AI / P1 | Every active call covered; no facade bypass |
| MAP-024; MAP-041 / BIA-021 | Remove AI broad warehouse schema credentials/cache; authorized Schema/Semantic/Query tools | P0 | G-C-LOCAL + G-CI; maintained Query authority | BOTH / P1 | Tenant/version cache isolation; credential inventory |
| MAP-030 / BIA-012/016/017 | PostgreSQL Debezium/Connect → Kafka → transform → ClickHouse current state | P1 with P0 correctness | G-C-LOCAL + G-CI; event/offset/transport ADRs | SE / P1 | G-D; handoff, insert/update/delete, restart, dedup, drift, reconcile |
| MAP-031 / BIA-023 | Governed metric/entity DSL, versioned publish, deterministic compiler and lineage | P1 | G-D, G-J | BOTH / P2 | G-S; access/type/cycle/formula/drift tests |
| MAP-033 / BIA-025 | Single bounded Analyst orchestrator; Modeling proposals precede Analyst | P1 | G-S, G-J, G-M | AI / P3–P4 | G-M/G-A; human semantic publish, typed tools and evidence |
| MAP-034; MAP-060 / BIA-026 | Separate Entitlements/Metering/Billing/Payments; reserve/commit/release and append-only adjustments | P0 | P1 facade/context; provider pricing contracts | SE / P2–P4 | G-E; token/provider/deck/export usage; concurrent/retry/reconcile tests |
| MAP-036 / BIA-028 | Operational SLOs, redacted telemetry, infrastructure alerts, runbooks | P0 | P0 infrastructure decisions | SE / all phases | Alert drills, correlated journeys, measured thresholds |
| MAP-050 / BIA-013/035 | Maintain Voice legacy report owner; add new Presentation domain/schema/worker in Report deployment | P1 | G-J; ADR-023; G-S | SE / P3 design/spine, P5 feature | One owner per object; no duplicate ORM activation or bulk migration |
| MAP-061 / BIA-025 | Governed MCP execution separate from Analyst; exact human approval, scoped secret/egress and audit | P0 boundary, P1 capability | Identity, G-J, policy, ledger | SE / P4 | G-E; replay/expiry/mutation/denial; approved deck action proves CAP-09 |
| MAP-090 / BIA-022 | Versioned AI/security/factuality corpus, harness and release thresholds | P0 | Start design now; runtime harness follows foundation | AI / P0 onward | Each feature evaluated before its own gate, aggregate G-Q |
| MAP-091 / BIA-004/040 | Supported pinned runtimes/dependencies, production servers, non-root images, isolated staging | P0 | Platform choice and compatibility review | SE / P0 onward | CAP-14 G-C-DEPLOY environment; G-Q/G-R deployment, scan, shutdown, rollback |
| MAP-092 / BIA-029 | Exact-SHA remote CI plus integration/eval/restore/deploy gates, immutable promotion | P0 | Staging and runner credentials | SE / P0 onward | Nine current prerequisites plus new gates; digest evidence |
| MAP-094 | Limited pre-analysis reliability and bounded arithmetic What-if; forecast only under evidence | P1 | G-S, G-M, G-J, trust | AI / P4 | Freshness/missingness warnings; deterministic scenario; uncertainty |
| MAP-095 | Hosted/tokenized real payments only if paid launch is chosen | Conditional | MAP-060; verified webhook/reconciliation | SE / P4–P6 if enabled | Payment gate or server-controlled free entitlements; no simulation |
| MAP-096 (new) | PresentationRequest/AnalysisPlan/evidence → PresentationSpec → governed provider → private artifact | P1 with P0 security | G-A, G-E; ADR-023 | AI + SE review / P5 | G-P; both adapters conform, at least one live-certified export |
| MAP-097 (new) | Presentation product UI, async status/cancel/retry, safe download, audit and usage | P1 | MAP-096; shared job/artifact contracts | SE + AI review / P5–P6 | Tenant E2E, permission revocation, export and safe failure |

## Deferred and conditional cleanup (IDs preserved)

| ID | Disposition | Reason / later acceptance |
|---|---|---|
| MAP-032 / BIA-024; MAP-093 | Structured & Unstructured RAG OUT OF JANUARY SCOPE | No knowledge/vector lifecycle milestone; retain dormant code; separate later approval |
| MAP-035 / BIA-033 | Arabic & Voice Support expansion OUT OF JANUARY SCOPE | Preserve working voice and safety tests; no dialect/RTL expansion milestone |
| MAP-094 historical proactive component | Proactive Monitoring Agent OUT OF JANUARY SCOPE | Limited reliability is request-time signals; operational infrastructure alerts remain required |
| MAP-070 / BIA-036 | Generated artifact cleanup deferred unless a release blocker | Reproducibility and dependency audit before any deletion |
| MAP-080 / BIA-013/038 | Legacy report migration/deletion POST_LAUNCH | ADR-023 keeps Voice ownership; never activate duplicate Report models |
| MAP-081 / BIA-019 | Delete obsolete clients only after facade migration/parity | Security bypass must be disabled before launch; deletion itself is optional |
| MAP-082 / BIA-009/038 | Broken orchestration cleanup after durable path proof | No startup/import/route/migration regression; removal not required for scope |
| MAP-100 | MySQL/MariaDB CDC POST_LAUNCH | PostgreSQL-only CDC commitment; no conditional January CDC breadth |
| MAP-101 | Other continuous engines POST_LAUNCH | Snapshot/local claims follow certified matrix; SQLite is import, not launch CDC |
| MAP-102 / BIA-032/041/042 | Broad cleanup/polish deferred | Only concrete correctness/security/ops blockers enter January |
| MAP-110 | Private-network/customer-agent transport POST_LAUNCH | Preserve discriminator; separate threat model/certification |
| MAP-111 | Multi-region active-active POST_LAUNCH | Requires measured business/SLO need |
| MAP-112 | Physical Integration/Model Gateway/Presentation extraction POST_LAUNCH | Logical ownership first; no automatic new services or vector store |

## Shared-file coordination and acceptance

SE owns migrations, owner roles, Integration/CDC, job persistence, policy/ledger/artifact storage and deployment. AI owns semantic compiler/proposals, Analyst, trust, evaluations and provider mapping. Freeze shared DTO/event/usage/evidence versions together before either changes consumers. Avoid concurrent edits to shared contracts, Query authorization, database routers or release workflow; designate one writer and one reviewer.

Product UI is AI-led with SE integrating authorization and lifecycle APIs, inside existing phases; no third frontend engineer assumed. P6 integrates; P7 proves quality/operations; P8 is release candidate only. A missed gate blocks dependents and triggers re-estimation/P2 cuts, never a silent date or safety change. Every implementation prompt cites CAP/MAP/BIA IDs and exact prerequisite evidence.
