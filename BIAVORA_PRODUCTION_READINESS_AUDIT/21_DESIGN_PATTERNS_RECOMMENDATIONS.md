> **SUPERSEDED SUPPORTING PLAN — 2026-10-27.** The body below preserves prior design context, not January commitments. Product Scope revision dated 2026-10-27 in [43](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md), current architecture 22/30–34, and presentation 44/46 control. Structured & Unstructured RAG, Proactive Monitoring Agent and Arabic & Voice Support expansion are OUT OF JANUARY 10 RELEASE SCOPE; do not implement their old milestones. Existing functionality/security remains maintained.

# 21 — Design Pattern Recommendations

Patterns below solve evidenced problems. “Required” means required for the Week-14 production target; it does not mean every service should adopt the pattern. Keep direct functions and ordinary transactions where they remain clearer.

| Pattern | Exact problem and current location | Why appropriate / why simpler code is insufficient | Services | Priority / required | Overengineering boundary |
|---|---|---|---|---|---|
| Strategy + Adapter | Engine conditionals around connectors in `etl-final`; future direct/private/agent transports | Connector registry already validates this shape; CDC engines and transports vary while callers need one contract | Integration, ETL | P0–P1 / Yes | Do not add abstract factories for objects with one implementation |
| `ConnectionTransport` Strategy | Source connection currently assumes direct network reachability | Later VPN/agent modes change dialing, identity and reachability without changing source/connector semantics | Integration, connector workers | P1 / Design now, implement Direct only | Private/Agent implementations are future until proven |
| Factory/registry | Existing connector registry and fragmented model clients | Central selection validates capability/configuration and rejects unsupported combinations | ETL, AI | P1 / Yes | A dictionary-backed typed registry is enough; no plugin framework initially |
| Repository + Unit of Work | Cross-service ORM projections and billing/job state transitions | Aggregate-owned writes and one transaction boundary prevent partial business state | Subscription, Integration, Semantic, Jobs | P0–P1 / Yes | Do not wrap every read query; use for owned aggregates and invariants |
| Transactional Outbox + idempotent Inbox | Voice/report events publish after DB writes; long jobs and CDC need reliable side effects | A local transaction cannot atomically commit to PostgreSQL and Kafka; retries alone duplicate or lose effects | Report, Subscription, Integration, Jobs, Notification | P1 / Yes | Use at state/event boundaries, not for telemetry |
| State Machine | Snapshot replacement, analysis jobs, checkout/webhook, semantic proposal and MCP approval have implicit states | Durable allowed transitions, expiry and recovery are core correctness, not cosmetic branching | Integration, AI Jobs, Billing, Semantic, Actions | P0–P2 / Yes | One small transition table per lifecycle; avoid a general workflow engine unless scale proves need |
| Command | MCP/action execution needs a typed, auditable request | Commands support validation, authorization, idempotency and result records before side effects | Action gateway | P2 / Yes for MCP | Never accept arbitrary shell/URL commands |
| Specification/policy object | SQL table authorization, entitlements, tool permissions and alert conditions are scattered | Composable deterministic policies can be unit tested and explained independently of handlers | Query, Subscription, Actions, Monitoring | P0–P2 / Yes | Keep policies domain-specific; no universal rule language initially |
| Pipeline | ETL already follows extract→transform→load; AI has explicit stages | Typed stage contracts make validation, telemetry and replay visible | ETL, AI, Knowledge | P1 / Yes | Do not force short CRUD requests through pipelines |
| Facade / Anti-Corruption Layer | External LLMs, payment provider, Metabase, Debezium/Kafka Connect expose unstable/vendor contracts | Keeps provider payloads/errors outside domain and supports controlled migration | AI, Billing, Visualization, CDC | P1 / Yes | One facade per external capability, not per endpoint |
| Circuit breaker + bounded retry/backoff | Long HTTP/model/source chains currently amplify failures | External/transient dependencies need deadlines, jitter and open-circuit behavior; plain retry worsens outages | Gateway, AI, Integration, Visualization, Notification | P1 / Yes | No retries on validation, auth, unsafe writes or deadline exhaustion |
| Bulkhead | Whisper serial lock, model calls and analytical queries compete for finite resources | Separate queues/concurrency budgets stop one expensive class starving all work | AI/STT workers, Query, RAG | P1–P2 / Yes | Start with worker pools/semaphores, not separate services per model |
| CQRS-lite | Large analytical reads differ from source/semantic/billing writes | Read projections/results can scale separately while command owners preserve invariants | Semantic, Reports, Monitoring | P2 / Selective | No event sourcing and no CQRS for ordinary CRUD |
| Observer/events | Notifications and post-job consumers need decoupled facts | Durable domain events suit asynchronous follow-up, while control commands stay HTTP/queue commands | Jobs, Notification, Metering | P1–P2 / Yes | Events must not replace synchronous authorization or queries |
| Dependency injection | Current module globals/model clients complicate deterministic tests and tenant-keyed policy | Explicit provider/clock/executor interfaces enable safe fixtures and configuration validation | AI, Query, Billing | P1 / Yes | Constructor/function injection is sufficient; no container framework required |
| Plugin architecture | Many source engines and future approved action tools | A signed/allowlisted registry with capability metadata contains extensibility | Integration, Action gateway | P2 / Partly | Connector registry yes; third-party runtime code loading is not required for Week 14 |
| Saga/compensation | Multi-step checkout, source replacement and action workflows cross owners | Explicit compensation/reconciliation is necessary where one ACID transaction is impossible | Billing, Integration, Actions | P1–P2 / Yes | Prefer orchestration in one owner; no general saga platform |

## Patterns explicitly not recommended now

- **Event sourcing everywhere:** no requirement justifies rebuilding stable CRUD histories. Immutable usage/action ledgers are domain records, not a platform-wide event store.
- **Multi-agent mesh:** a single Analyst orchestrator with typed tools has lower evaluation, latency and authorization complexity.
- **Service mesh:** workload identity, TLS and telemetry can be achieved through the chosen managed platform first.
- **Dedicated database server per service:** logical databases/schemas and roles in managed clusters satisfy ownership until scale/isolation demands more.
- **Abstract factory layers around every provider:** typed adapters plus a registry solve current variation.
- **Chain of Responsibility for authorization:** explicit policies with a clear deny-by-default decision are easier to audit.

## Adoption order

First establish policy/specification for table authorization, owned repositories/UoW, job/payment/source state machines and outbox/inbox. Then introduce provider/transport adapters, bulkheads and breakers. Add command/approval and CQRS-lite only as the dependent feature is built. Every pattern must arrive with contract and failure-path tests.

