# 31 — Canonical Service Ownership Map

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

## Boundary policy

A **logical capability** owns decisions/data/contracts. A **deployment** is a process/container scaling and security boundary. They are intentionally not one-to-one. Week 14 minimizes deployable proliferation while enforcing logical owners, schemas/roles, credentials, and APIs/events.

## Current and proposed capability map

| Capability / current location | Domain action | Week-14 logical owner and owned state | Initial deployment action | Allowed interactions |
|---|---|---|---|---|
| Frontend `frontend/` | KEEP + REFACTOR | Presentation/session UX; no authority | KEEP static/web deployment | Gateway APIs only; no infrastructure credentials |
| API Gateway `services/api-gateway` | KEEP + REFACTOR | Edge routing, request ID, coarse auth presence, distributed rate/size policy | KEEP deployable edge service | Routes control APIs; does not own business state or trust bearer presence as authorization |
| Auth `auth-service` | KEEP + REFACTOR | Users, credentials, sessions/tokens, reset/MFA policy | KEEP deployable; owner schema/role | Workspace membership lookup by owned API/token claims; events for identity changes |
| Workspace `workspace-service` | KEEP + REFACTOR | Organizations/workspaces/members/invitations/roles | KEEP deployable; owner schema/role | Authoritative authorization API/events; no other ORM owner |
| Query `query-service` query path | KEEP + REFACTOR | Logical dataset binding, authorized analytical execution, query policy/result refs | KEEP deployable; owner schema/role | Sole ClickHouse product query identity; typed Query/Schema tools |
| Data Source currently in Query `Database` | NEW LOGICAL CAPABILITY + MOVE | Integration owns source, engine, secret ref, TLS/transport, selected tables, capability, snapshot/CDC lifecycle | Initially co-deploy isolated module/schema in Query deployment; **not** a new container | Connector control API/events; secret manager; no raw secret in events |
| Report currently split Voice/Report | MERGE + MOVE | One Report owner for saved report metadata/lifecycle/evidence refs | Prefer Query/Report control deployment initially; retire Report proxy after migration | Query result refs; Visualization spec; report events via outbox |
| Report service proxy/duplicate | REMOVE after migration | No separate authority | DELETE_AFTER_MIGRATION after route/data/runtime checks | Compatibility redirect only during migration |
| Voice `voice-service` | KEEP + REFACTOR | Upload/transcription/input normalization and voice artifact lifecycle | KEEP deployable/worker due compute and upload boundary | Submits durable analysis job; never executes ClickHouse directly |
| AI `ai-service` | KEEP + REFACTOR | Analyst orchestration, intent, provider adapters, evaluation integration | KEEP API + worker deployment; GPU pools separable | Authorized typed tools only; no CH/source/payment/action credentials |
| ModelProvider calls across AI | MERGE | Internal provider facade owns model policy, invocation, usage telemetry | In-process library in AI deployment; **not** network service | External model APIs/Ollama adapters; emits usage events |
| Semantic Layer | NEW LOGICAL CAPABILITY | Semantic models, versions/status/certification/lineage and review | Initially module/API/worker in AI control deployment with owner schema/role | Schema Tool/Query compiler/Report/RAG/Trust consume published versions |
| Semantic Modeling | NEW LOGICAL CAPABILITY | Proposals/validation/explanation/review workflow | AI worker using Semantic API; no standalone service | Cannot publish without authorized human review |
| Knowledge/RAG | NEW LOGICAL CAPABILITY | Documents, ACLs, versions, chunks/index jobs/citations/deletion | Initially AI/knowledge worker + PostgreSQL/pgvector + object storage | Authorized RAG Tool; no direct warehouse dump |
| Analyst Orchestrator | REFACTOR | One governed durable orchestrator with typed tool state | AI worker | Semantic/Schema/Query/RAG/Forecast/Stats/Viz/Trust/WhatIf/ActionProposal tools |
| Visualization `visualization-service` | KEEP + REFACTOR | Chart/spec validation and rendering integration | KEEP deployable only if Metabase isolation/scale justifies; otherwise merge module later | Bounded Query result/spec; no direct CH query authority |
| Forecast/What-if in AI | KEEP + REFACTOR | Forecast jobs and reproducible scenario contracts | AI worker; compute pool may scale separately | Query input refs, semantic metric versions, Trust evidence |
| Proactive/limited reliability | NEW LOGICAL CAPABILITY | Schedules, governed checks, investigations, alerts | AI/job worker plus Data Platform signals | Semantic metrics, CDC health, Notification; no autonomous action |
| Action policy/approval | NEW LOGICAL CAPABILITY | Proposals, policy, approval tokens, audit | Control-plane module with owner state | Identity/Workspace and isolated Tool Gateway |
| Tool Gateway | NEW DEPLOYABLE SERVICE | Executes approved third-party actions with scoped credentials/egress | Separate minimal deployable security boundary | Accepts single-use bound approvals; emits result/audit/usage |
| Subscription `subscription-service` | SPLIT logical concepts | Entitlements, Metering Ledger, Billing State, Provider adapter each own distinct state | Initially one deployable service with separated modules/schemas/roles as practical | Usage events in; entitlement API out; provider webhooks in |
| Payment collection | NEW LOGICAL CAPABILITY | Hosted/tokenized provider session/webhook/reconciliation | Adapter in Subscription deployment; provider-hosted UI | Never receives/stores raw PAN/CVV |
| Notification `notification-service` | KEEP + REFACTOR | Notification preferences/delivery/read model | KEEP API + worker; owner schema/role | Consumes events/read projections; removes cross-domain ORM maps |
| ETL connector `etl-connector` | KEEP + REFACTOR | Connector control adapter/registry and safe test command | Data Platform deployment | Integration commands; secret resolution at execution boundary |
| ETL detector `etl-detector` | KEEP | Ingestion observation/detection metadata | Data Platform worker | Versioned scoped events |
| ETL extractor `etl-extractor` | KEEP + REFACTOR | Snapshot extraction | Data Platform worker | Integration command; raw rows event/object reference |
| ETL transformer `etl-transformer` | KEEP + REFACTOR | Deterministic normalization/transformation | Data Platform worker | Versioned row/CDC envelopes |
| ETL loader `etl-loader` | KEEP + REFACTOR | Idempotent ClickHouse writes/schema policy | Data Platform worker with write-only CH identity | No product query authority |
| ETL metadata `etl-metadata` | KEEP + REFACTOR | Ingestion lineage/status projection | Data Platform worker/store | Preserves workspace/dataset/job scope; callbacks/events |
| CDC capture/normalize | NEW DEPLOYABLE SERVICE | Debezium/Kafka Connect capture plus BIAVORA canonical normalizer | Managed/supportable Kafka Connect + normalizer worker | Source TLS/secret ref; canonical Kafka envelopes |
| Durable Job capability | NEW LOGICAL CAPABILITY | Job state/attempts/idempotency/result/error/outbox | Common library + owner schema/API; workers in owning deployments | HTTP submit/read/cancel; queue/events for execution |
| Observability | NEW LOGICAL CAPABILITY | Telemetry conventions, SLOs, dashboards, alerts, runbooks | Managed telemetry platform + per-deployment collectors | Receives redacted logs/metrics/traces; no business authority |

## Storage and authority map

| Store | Authoritative writers | Readers | Rule |
|---|---|---|---|
| Managed PostgreSQL owner schemas | Owning capability role only | Owned API/projection roles | No cross-domain ORM mutation |
| ClickHouse analytical tables | ETL Loader write identity | Query read identity only | AI/Voice/Report/Viz have no credential |
| PostgreSQL + pgvector | Knowledge owner | Authorized Knowledge/RAG Tool | ACL filter before prompt and citation |
| Object/quarantine storage | Upload/document/ingestion owners | Authorized workers/tools | Tenant prefixes, malware state, retention/deletion |
| Kafka | Declared topic producers | Declared consumer groups | Versioned schema, ACL, retry/DLQ/replay owner |
| Usage ledger | Metering consumer/adjustment authority | Entitlements/Billing/support projections | Append-only, idempotent, pricing-versioned |
| Secret manager | Security/owner automation | Exact workload identity | Opaque refs; no secret in DB/event/log |

## Extraction triggers

Integration becomes a separate deployable service only if source secrets/egress demand a harder boundary, connector-control scaling differs materially, failure containment requires it, or durable team ownership exists. ModelProvider becomes a network gateway only if multiple deployments need common policy and the added availability/latency burden is justified. Semantic/Knowledge/Visualization similarly remain logical owners before separate services. Any extraction requires contract tests, data migration, rollback, SLO/on-call, and an ADR.
