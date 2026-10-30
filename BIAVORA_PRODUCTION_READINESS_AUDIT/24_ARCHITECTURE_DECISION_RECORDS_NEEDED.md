# 24 — Architecture Decision Register

> Revision 3 / 2026-10-27. January scope and dates: [43](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md). Entries are decision prerequisites, not evidence of implementation.

Stable ADR IDs are retained. Query authority, logical ownership, direct secure transport, PostgreSQL-first CDC, single Analyst orchestration and separated entitlement/metering/billing/payment concepts remain frozen. The old Week-14 deadlines are superseded.

| ADR | Decision / current direction | Deadline / state |
|---|---|---|
| ADR-001 | Logical owner schemas/roles, owned migrations, no foreign ORM writes | Foundation-C local evidence in 42; deployed proof CAP-14 by 15 Dec |
| ADR-002 | Authorized logical binding → exact physical allowlist + Query limits | Foundation-A CLOSED; preserve continuously |
| ADR-003 | Legacy Report ownership | January placement superseded by ADR-023: Voice keeps legacy records; Report hosts new Presentation domain |
| ADR-004 | Integration aggregate, credentials, lifecycle and APIs in Query deployment | Existing local implementation; external proof CAP-14 by 15 Dec |
| ADR-005 | Direct secure transport first; future private/agent discriminator | Local implementation; combined public TLS/egress proof CAP-14 by 15 Dec; Debezium separate P1 |
| ADR-006 | Durable job/store/worker/outbox, context, cancellation and idempotency | Decide before P1 implementation; G-J |
| ADR-007 | Event/topic owner, schema, partition, retry/DLQ/replay/retention | Before P1 CDC; G-D; v1 staging drain CAP-14 by 15 Dec |
| ADR-008 | PostgreSQL-only launch CDC; other engine modes explicit in 43 | Before P1; no MySQL/MariaDB or SQLite CDC commitment |
| ADR-009 | Mutable ClickHouse current-state view, versions/tombstones, dedup and reconciliation | Before P1 loader work; Query exclusively selects current state |
| ADR-010 | Managed store/KMS, versioned keys, workload identities and rotation | CAP-14 G-C-DEPLOY by 15 Dec |
| ADR-011 | Managed production platform/runtime/network, staging and deployment | P0 design; operator plan by 16 Nov, environment by 29 Nov; no Kubernetes requirement |
| ADR-012 | Semantic owner/DSL/versions/publish/lineage | Before P2; human publish and deterministic compiler |
| ADR-013 | In-process ModelProvider, policy/deadline/budget/usage and test doubles | Before P1 facade; versioned eval cases P0 |
| ADR-014 | Single governed Analyst with typed tools | Before P4; Semantic and durable context prerequisites |
| ADR-015 | Knowledge/vector storage | DEFERRED: RAG OUT OF JANUARY SCOPE; no pgvector prerequisite |
| ADR-016 | Immutable evidence and trust contract; no chain-of-thought exposure | P2 freeze before Modeling/Analyst; extend to Presentation evidence |
| ADR-017 | Immutable usage ledger/reserve/commit/release; payments conditional | P2 contract, P3–P4 implementation before paid provider dispatch |
| ADR-018 | Isolated MCP gateway, deterministic policy, exact approval, egress/audit | P3 design, P4 G-E before live presentation provider |
| ADR-019 | Browser session and delegated/workload identity, reauthorization | P0 risk/design; complete required controls before release |
| ADR-020 | Retention/deletion/backup/RPO/RTO by data class including artifacts | P0 policy, P3 artifacts, rehearsed by G-Q/G-R |
| ADR-021 | Redacted telemetry/SLOs, correlation, ownership and alert drills | P0 baseline; each phase instruments; G-Q/G-R measured |
| ADR-022 | Arabic product expansion | DEFERRED: Arabic & Voice Support expansion OUT OF JANUARY SCOPE; maintained functionality only |
| ADR-023 | Presentation generation ownership and provider abstraction | ACCEPTED FOR PLANNING in [46](46_ADR_023_PRESENTATION_OWNERSHIP_AND_PROVIDER_ABSTRACTION.md); implementation NOT STARTED |

## Governance

Each implementation ADR needs accountable owner, reviewer, alternatives, consequences, security/operations impact, migration/rollback, tests and review trigger. An implementation choice is not a production certification. Scope changes update 43/45/34 first. No ADR authorizes deletion or bypasses production gates. Owner decision 49 separates local Foundation-C closure/current CI from CAP-14 external certification.
