# 22 — Week-14 Deployable Target Architecture

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

## Decision summary

BIAVORA evolves into a small set of owned capabilities, not one container per noun. REST/HTTP is the control plane. Kafka/events carry ingestion records, durable job transitions, alerts, usage events, and long-running completion. Query is the sole analytical execution authority. Integration/Data Source becomes a logical owner initially co-deployed in the Query control-plane deployment, with its own module/schema/role; connector workers remain the Data Platform. One Analyst Orchestrator invokes typed governed tools. Entitlements, Metering, Billing, and Payment are separate concepts even when initially co-deployed.

## Plane model

```mermaid
flowchart TB
  U[Users / Organizations] --> EDGE[HTTPS Edge: WAF, rate limits, request IDs]

  subgraph SB[Security boundary: authenticated workspace context, least privilege, policy, audit]
    subgraph CP[Control plane — REST/HTTP]
      IAM[Identity + Workspace]
      INT[Integration / Data Source]
      SEM[Semantic Model]
      JOB[Durable Job API]
      QRY[Query]
      REP[Report]
      ENT[Entitlements + Billing State]
    end

    subgraph DP[Data plane — Kafka/events + workers]
      KC[Kafka Connect + Debezium]
      NORM[CDC Normalizer]
      ETL[Snapshot/Transform/Load workers]
      CH[(ClickHouse)]
    end

    subgraph AIP[AI plane]
      VOI[Voice + Normalization]
      AO[One Analyst Orchestrator]
      MPG[In-process ModelProvider facade]
      TOOLS[Typed tools: Semantic, Schema, Query, RAG, Forecast, Stats, Viz, Trust, WhatIf, ActionProposal]
    end

    subgraph KP[Knowledge plane]
      DOC[Document lifecycle + ACL]
      VEC[(PostgreSQL + pgvector)]
    end

    subgraph AP[Action plane]
      POL[Policy + Approval]
      TG[Isolated Tool Gateway]
    end

    subgraph MP[Metering plane]
      UE[Usage events]
      LED[(Immutable usage ledger)]
      PAY[Hosted payment provider]
    end

    subgraph OP[Observability plane]
      OTel[Logs + metrics + traces]
      SLO[SLOs, dashboards, alerts, runbooks]
    end
  end

  EDGE --> IAM
  EDGE --> INT
  EDGE --> JOB
  INT --> KC
  INT --> ETL
  KC --> NORM --> ETL --> CH
  JOB --> AO
  VOI --> JOB
  AO --> TOOLS
  TOOLS --> SEM
  TOOLS -->|Authorized Query Tool only| QRY
  QRY -->|logical dataset/table binding + policy| CH
  QRY --> REP
  TOOLS --> DOC --> VEC
  AO --> MPG
  TOOLS --> POL --> TG
  MPG --> UE
  VOI --> UE
  TOOLS --> UE --> LED
  PAY --> ENT
  LED --> ENT
  CP --> OTel
  DP --> OTel
  AIP --> OTel
  AP --> OTel
```

Query executes; Report owns saved report lifecycle. Visualization consumes safe result/spec contracts and never queries ClickHouse directly.

## Runtime deployment topology

```mermaid
flowchart LR
  EDGE[Managed HTTPS edge] --> WEB[Frontend]
  EDGE --> API[Gateway + control APIs]
  API --> PG[(Managed PostgreSQL: owner schemas/roles + pgvector)]
  API --> REDIS[(Managed Redis)]
  API --> KAFKA[(Managed/supportable Kafka)]
  KAFKA --> WORK[Connector / CDC / ETL / analysis workers]
  WORK --> CH[(Production ClickHouse)]
  API --> OBJ[(Object/quarantine storage)]
  WORK --> OBJ
  API --> SEC[Secrets manager / KMS]
  WORK --> SEC
  API --> OBS[Central telemetry]
  WORK --> OBS
```

Use a managed container platform with separate staging/production environments. Kubernetes is not required unless workload/GPU/network needs justify its operational cost.

## Plane contracts

### Control plane

Synchronous APIs create/test sources, submit/cancel/read jobs, manage semantic/document/report objects, request approvals, inspect usage, and administer entitlements. Responses must be bounded and must not proxy long work in a request.

### Data/event plane

Versioned events carry tenant/workspace/source/job identity, schema version, idempotency key, correlation/trace context, occurred-at time, producer, payload reference, and classification. Owners define partition keys, compatibility, retry, terminal DLQ/quarantine, replay, retention, and PII/logging policy.

### Query boundary

Clients submit logical dataset/table identities. Query resolves immutable authorized physical bindings, requires an exact allowlist, applies read-only/resource settings, executes, and stores or pages bounded results. AI/Voice/Reports/Visualization have no direct ClickHouse credential or fallback. Physical identifiers are not public API fields.

### Integration and transport

Integration owns source definition, engine, secret reference, TLS, transport, table selection, capabilities, snapshot/CDC state, and lifecycle. Initial transport is `DirectSecureInternetTransport`; source models also carry a transport discriminator so `PrivateNetworkTransport` and `AgentTransport` can be added post-launch without changing CDC, metering, UI ownership, or events.

PostgreSQL CDC is `remote PostgreSQL -> TLS -> Debezium -> Kafka Connect -> Kafka -> BIAVORA normalizer -> Transformer -> Loader -> ClickHouse`. Engine claims follow certification, not adapter presence.

### Durable jobs

All voice analysis, large query/report, document indexing, semantic proposal, forecast/What-if, proactive investigations, actions, and large ingestion operations use the common state machine:

`QUEUED -> RUNNING <-> RETRYING -> SUCCEEDED | FAILED | CANCELLED`

Each job has `job_id`, workspace/actor, type/version, idempotency/correlation IDs, attempt, timestamps, deadline/budget, input/result references, error class, semantic/model/prompt versions, and audit trail. State transitions use transactional outbox/inbox or an equivalent proven delivery pattern.

## Ownership and storage

- One managed PostgreSQL cluster is allowed. Critical domains use owner schemas/databases and dedicated roles; no owner writes another domain's tables.
- ClickHouse is analytical storage, accessed only through Query for product analysis and through owned loader identities for ingestion.
- PostgreSQL + pgvector is the initial knowledge store; a new vector database needs benchmark evidence.
- Object storage owns raw/quarantined uploads and document artifacts with tenant keys and retention policy.
- The usage ledger is immutable/auditable and separated from mutable entitlement/billing state.

## Required Week-14 production properties

Exact controls and release evidence are normative in `30_CANONICAL_ARCHITECTURE_RULES.md` and `33_PRODUCTION_SECURITY_BASELINE.md`. The architecture is not considered delivered without staging, secrets management, production process servers/non-root images, resource/rate limits, TLS, observability/SLOs, backup/restore, migration/rollback rehearsal, AI/CDC/security gates, and a real payment path when paid launch is enabled.

## Explicit post-launch scale enhancements

Private network/customer agent transport, MySQL/MariaDB CDC unless already certified, additional action integrations, a dedicated Integration deployment, dedicated Model Gateway service, separate vector database, multi-region active-active, and service mesh are evidence-driven future options—not Week-14 assumptions.
