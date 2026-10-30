# 22 — January 2027 target architecture

Revision 3.0 · 2026-10-27 · Target **10 January 2027**. Design, not deployment proof.
[43](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md) controls scope and dependencies; [45](45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md) separates current implementation from target.

## Context

```mermaid
flowchart LR
  U[Business users] --> F[Frontend]
  F --> E[HTTPS edge / API Gateway]
  E --> B[BIAVORA owned domains and workers]
  Sources[Customer databases / private uploads] --> I[Governed Integration / Data Platform]
  I --> B
  B --> G[Policy-controlled model and MCP egress]
  G --> L[Approved model providers]
  G --> P[SlidesGPT / Gamma renderers]
  B --> O[Managed stores / secrets / telemetry]
  B --> A[Authorized reports / private artifacts]
  A --> U
```

External databases are ingestion sources, not reachable by the LLM or presentation vendor. No external presentation provider becomes an analytical authority.

## Logical domains and initial deployment

```mermaid
flowchart TB
  Edge[Gateway] --> Auth[Auth identity]
  Edge --> W[Workspace permissions]
  Edge --> QD
  Edge --> AI
  Edge --> RD
  Edge --> Sub[Subscription: Entitlement / Metering / Billing / Payments]
  subgraph QD[Existing Query deployment]
    Int[Integration source / credential / transport owner]
    Q[Query dataset / analytical owner]
  end
  subgraph AI[Existing AI API and worker deployment]
    Sem[Semantic owner / versions / publication]
    Model[Modeling proposals]
    Analyst[One Analyst / model facade / evaluation]
    Trust[Evidence / What-if / limited reliability]
    Model --> Sem
    Analyst --> Sem
    Analyst --> Trust
  end
  subgraph RD[Existing Report deployment]
    Proxy[Legacy report proxy]
    Pres[New Presentation logical domain / worker / artifact lifecycle]
  end
  Proxy --> Voice[Voice: maintained input and legacy saved-report owner]
  Pres --> Analyst
  Analyst --> Q
  Analyst --> Viz[VisualizationSpec / governed charts]
  Pres --> Tool[Isolated governed MCP / provider execution boundary]
  Tool --> Vendor[SlidesGPTProvider / GammaProvider]
  Int --> Data[Connector / Debezium-Kafka Connect / ETL workers]
  Data --> K[(Kafka versioned records)]
  K --> Load[Transformer / Loader / scoped metadata]
  Load --> CH[(ClickHouse)]
  Q --> CH
  Pres --> Obj[(Private artifact storage)]
  Data --> N[Notification owned projection]
```

Each owner writes its own PostgreSQL schema with a least-privilege role and separate migration principal; one managed cluster is allowed. Integration already exists in Query with separate role routing. Semantic, durable jobs, usage ledger, MCP and Presentation are target capabilities, not claimed deployed boxes. Report/Voice coexistence is bounded in [ADR-023](46_ADR_023_PRESENTATION_OWNERSHIP_AND_PROVIDER_ABSTRACTION.md). No automatic new Presentation, Semantic or ModelProvider microservice.

Metabase remains an existing downstream consumer of Query-authorized definitions through Visualization. Its actual query execution is a legacy rendering mechanism, not independent authorization. Keep it within scoped read-only grants/tenant object checks; assess that path during operations hardening. Presentation vendors receive approved result projections/assets only and never Metabase credentials or native warehouse access.

## Governed analytical request

```mermaid
sequenceDiagram
  actor User
  participant G as Gateway
  participant A as Analyst/job owner
  participant S as Semantic
  participant Q as Query
  participant C as ClickHouse
  participant V as Visualization/Trust
  User->>G: Question and logical dataset
  G->>A: Authenticated context
  A->>A: Reauthorize / budget / durable job
  A->>S: Resolve published metric/version
  S-->>A: Typed semantic plan and approved definitions
  A->>Q: Plan with actor/workspace/dataset and deadline
  Q->>Q: Resolve exact tables / read-only AST / limits
  Q->>C: Authorized bounded execution
  C-->>Q: Results
  Q-->>A: Bounded result reference / execution evidence
  A->>V: Reproducible findings and chart request
  V-->>A: VisualizationSpec / evidence manifest
  A-->>User: Answer, limitations, facts/forecast/scenario labels
```

AI's existing direct schema readers and process-global cache must be removed from authority before G-J/G-A. Authorized Schema tools provide minimum workspace/dataset context. A logical data ID from a client or model is a selector, never authorization.

## PostgreSQL CDC sequence and correctness contract

```mermaid
sequenceDiagram
  participant I as Integration
  participant C as Kafka Connect/Debezium
  participant P as PostgreSQL source
  participant K as Kafka
  participant T as Normalizer/Transformer
  participant L as Loader
  participant H as ClickHouse
  participant Q as Query
  I->>I: Authorize source, configuration version and desired state
  I->>C: Governed connector configuration / managed secret reference
  C->>P: Verified TLS, logical replication slot/publication
  P-->>C: Consistent initial snapshot and WAL continuation
  C->>K: Source records and durable connector offsets
  K->>T: Scoped versioned change envelope
  T->>L: Key / source position / operation / schema / values
  L->>H: Idempotent versioned row or tombstone
  H-->>L: Durable application acknowledgement
  L->>K: Commit consumed position after durable disposition
  L-->>I: Scoped watermark / lag / reconciliation status
  Q->>H: Authorized current-state read semantics
```

Foundation-C local closure, current release CI GREEN and preserved local security boundaries are prerequisites to local CDC. External validation is CAP-14/G-C-DEPLOY before production certification (49). Integration owns desired connector lifecycle; Kafka Connect owns capture offsets; Data Platform owns canonical normalization/materialization; Query owns published analytical bindings. PostgreSQL replication credentials require separately scoped replication/publication privileges, not an unexamined reuse of snapshot SELECT-only credentials. Managed delivery and safe DNS/TLS/egress must cover Connect's own driver; the Python connector pinning proof does not certify a Java Debezium connection.

Choose/test mutable-state storage before loader code: stable primary key, per-key source position/version, duplicate/reorder handling, delete tombstones and a Query-visible current-state view. Background ClickHouse merges alone do not guarantee immediate logical deduplication. Source transactions across tables require an explicit consistency level; January must disclose per-table/per-key eventual consistency unless stronger snapshot visibility is proven. Freeze a repeatable watermark/result reference for multi-query evidence or disclose drift; never claim an atomic multi-table view without tests.

Partition for per-key order, handle snapshot-to-WAL handoff without gaps, commit only after durable write or auditable terminal quarantine, and retain restart checkpoints. Quarantine invalid envelopes with scoped references and a controlled replay path; do not silently skip poison records. Require PKs for mutable release tables; reject unsupported no-key updates/deletes. Additive nullable columns can be a tested supported change; drop/rename/type/PK changes pause ingestion pending reviewed mapping/reseed. Source slot/WAL growth, lag, retention, credential rotation and source/target counts/hashes need alerts/runbooks. No blanket exactly-once marketing claim.

## MCP policy and approval sequence

```mermaid
sequenceDiagram
  participant A as Analyst/Presentation
  participant P as Policy and approval owner
  actor H as Authorized human
  participant G as Tool gateway
  participant V as Provider
  A->>P: Immutable sanitized proposal + provider/tool/payload hash
  P->>P: Scope / entitlement / classification / cost / egress validation
  alt Denied
    P-->>A: POLICY_DENIED
  else Explicit approval required
    P->>H: Exact preview, destination, data and cost
    H->>P: Approve or reject
    P->>G: Single-use bounded authorization
  else Preapproved safe create intent
    P->>G: Audited operation consent
  end
  G->>G: Recheck permission/policy/hash/expiry and dispatch idempotency
  G->>V: Allowlisted invocation
  V-->>G: Result or uncertain outcome
  G-->>P: Audit / verify / reconcile / meter
```

January includes a tested explicit approval-required deck operation; safe internal analytical calls do not need repeated confirmation. No destructive arbitrary tool/SQL/financial action is in the minimum.

## Presentation sequence and data egress

The normative [presentation sequence, Data Egress Boundary, typed contracts and state machine are in 44](44_AI_PRESENTATION_AND_EXECUTIVE_REPORT_ARCHITECTURE.md). They complete this architecture's required context, ownership, analytical, CDC, approval, presentation and egress views without duplicating vendor logic. Provider adapters are transport-independent and run only after sanitized payload policy. No slide engine is built.

## Platform and deployment

HTTP submits/reads/cancels short control operations; Kafka transports versioned asynchronous records and reliable lifecycle/usage facts. Jobs use owned persisted state and transactional outbox/inbox, not HTTP-held orchestration. Correlation IDs connect calls/events without granting permissions.

Single-region managed containers/state are preferred for the two-person team; Kubernetes is not required. Use isolated staging/production, production process servers/workers, supported pinned dependencies, non-root immutable images, TLS/least-privilege identities, managed secrets/rotation, private artifact/quarantine storage, bounded resources/rates, redacted logs/metrics/traces, measurable SLOs and responder runbooks. Recover PostgreSQL/ClickHouse/Kafka/object storage/metadata/semantic/job/ledger state coherently. Prove migration/rollback and restore/RPO/RTO before launch.

Notification consumes owned events/read projections rather than foreign ORM. Entitlements, immutable Metering, Billing and Payments remain distinct even within Subscription. Paid activation is disabled unless its separate real-provider gate passes. No pgvector/Knowledge plane, Proactive Monitoring Agent or Arabic/Voice expansion is part of this release; existing code remains maintained. All boxes require the tests/deployment evidence in 45 before they can be called production-ready.
