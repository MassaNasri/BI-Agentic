# 24 — Architecture Decision Records Needed

> **v2 freeze:** The recommended directions in the canonical `29`–`33` documents are approved for implementation planning. ADRs record implementation-specific choices and exceptions; they must not reopen tenant-scoped Query authority, one Analyst Orchestrator, logical data ownership, PostgreSQL-first CDC, direct-secure transport first, or the separation of Entitlements/Metering/Billing/Payments without an explicit versioned architecture review.

ADRs should record a concrete choice, alternatives, consequences, security/operations impact and a review trigger. They are implementation prerequisites where noted, not paperwork after the fact.

| ADR | Decision to make | Recommended direction | Deadline / dependencies |
|---|---|---|---|
| ADR-001 Capability ownership and logical data isolation | Owner and database/schema/role for each domain | Owned logical schemas/databases in managed clusters; no cross-service ORM mutation | Week 1; precedes migrations |
| ADR-002 Analytical authorization invariant | How workspace/dataset permission becomes ClickHouse access | Query is sole executor; logical IDs resolve server-side to exact physical allowlist plus DB limits | Immediate; BIA-001/002 |
| ADR-003 Report ownership | Report service, voice, visualization boundaries | One Report owner; Voice is input/transcription, Visualization produces specs; retire proxy/duplicate | Week 1 |
| ADR-004 Integration/Data Source ownership | Source definition, secrets, lifecycle and APIs | New logical Integration capability; move Query's source concerns; opaque vault refs | Week 1; CDC prerequisite |
| ADR-005 Connectivity transports | Direct internet now versus private/agent later | `ConnectionTransport` contract; implement Direct with strict egress/TLS; reserve Private/Agent | Week 2 |
| ADR-006 Durable jobs and messaging | Orchestrator/store/queue, state, cancellation and idempotency | Owned job state machine, workers and outbox/inbox; HTTP submit/read, async execution | Week 2 |
| ADR-007 Event governance | Topic ownership, schema/version, partition, retry/DLQ/replay | Canonical versioned envelopes and registry/compatibility gate; tenant/source keying | Week 2–3 |
| ADR-008 CDC scope and engine certification | Engines and correctness promise | PostgreSQL production CDC; MySQL/MariaDB conditional; MSSQL/Oracle snapshot-only unless certified; SQLite scheduled incremental; ClickHouse source strategy | Before Week 3 |
| ADR-009 ClickHouse mutable-state model | Updates/deletes/history/current views and dedup | Versioned records/tombstones with explicit current-state view, reconciliation and retention | Before CDC loader work |
| ADR-010 Secret/key management | Store, envelope encryption, rotation, worker access | Managed KMS/Vault references; no reusable source credential in Kafka; per-service identity | Week 2 |
| ADR-011 Production platform | Managed container/runtime/stateful services, networking, rollout | Managed containers first; no Kubernetes/service mesh without ops need | Week 1–2 |
| ADR-012 Semantic model ownership and DSL | Storage, formula/compiler, versions, publish and lineage | Dedicated capability, relational version model, deterministic compiler, human publish | Before Week 8 |
| ADR-013 AI provider gateway | Providers, routing, privacy, structured output, telemetry/cost | One typed gateway/registry with policy, versioning, deadlines, usage events | Before Analyst build |
| ADR-014 Analyst execution model | Single versus multi-agent and tool contract | Single governed orchestrator with typed tools and budgets | Before Week 10 |
| ADR-015 Knowledge/vector storage | Document store/parser/index and vector technology | Object storage + relational metadata; benchmark PostgreSQL/pgvector before specialist DB | Before RAG build |
| ADR-016 Trust/evidence contract | Answer provenance fields and retention | Immutable execution evidence with semantic/query/document versions; expose summaries, not CoT | Before semantic/agent API freezes |
| ADR-017 Billing, entitlements and metering | Source of truth, provider, units, reserve/commit/refund | Hosted payment + webhook truth; immutable multi-dimensional ledger/reservations | Week 2 design; implement by Week 12 |
| ADR-018 MCP approval/action boundary | Tool hosting, states, authorization and audit | Separate typed action gateway after explicit approval; no arbitrary code/network tool | Before Week 12 |
| ADR-019 Authentication/session design | Browser tokens, internal identity and delegated context | Short access tokens, rotated secure refresh cookie; per-workload identity and signed minimal context | Before external launch |
| ADR-020 Retention, deletion, backup and DR | Data classes, TTL, tenant deletion, RPO/RTO | Policy per source/audio/document/prompt/result/event/usage; tested restore/deletion | Before staging soak |
| ADR-021 Observability and SLOs | Telemetry backend, redaction, identifiers and objectives | OTel with job/tool/event correlation; separate API/job/data SLIs and measured SLOs | Week 2 baseline, finalize Week 14 |
| ADR-022 Arabic product scope | Dialects, normalization, UI locale and acceptance data | MSA + selected Levantine/Syrian business domain, mixed English, native evaluation | Before Arabic implementation |

## ADR governance

Assign one accountable owner and one reviewer to each ADR. Link code/migrations/tests and threat model from the accepted record. Supersede rather than silently edit a shipped decision. Review ADR-008 after real source demand, ADR-015 after vector benchmarks, and ADR-011 after measured scale/operational constraints.

