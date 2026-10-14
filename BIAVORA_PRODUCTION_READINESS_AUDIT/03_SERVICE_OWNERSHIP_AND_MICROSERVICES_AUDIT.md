# Service ownership and microservices audit

> **v2 reconciliation:** The target is logical ownership in one managed PostgreSQL cluster using owner schemas/databases and dedicated roles; it is not one physical server per service. Integration/Data Source is a **new logical capability**, initially co-deployed as an isolated module and owned schema in the Query deployment while connector workers remain in the Data Platform deployment. It becomes a separate deployable service only when secret/egress isolation, scale, or team ownership proves the need. HTTP remains the control plane; Kafka/events carry data and long-running lifecycle events. See canonical files `30` and `31`.

## Conclusion

BIAVORA has useful process boundaries but is not currently a true independently deployable microservice system. It is a **distributed modular monolith** because:

- seven business services default to one PostgreSQL database name/account and, in the supplied environment, the same host/schema;
- notification reads four other domains' tables directly;
- report-service is a proxy for voice-service, not an owner;
- voice-service coordinates most product behavior and has direct knowledge of six services plus Kafka, ClickHouse fallback, filesystem, and report state;
- JWT signing, shared environment, schema lifecycle, and readiness chains couple deployments;
- the local Compose file omits the core PostgreSQL runtime while every service expects it.

The ETL services have clearer stage boundaries, but they share a source tree/library, Kafka contracts, credentials, one ClickHouse/SurrealDB environment, and startup/runtime conventions. They are pipeline workers more than autonomous business microservices—which is acceptable if owned as one Data Platform subsystem.

## Service ownership matrix

Abbreviations: PG=PostgreSQL, CH=ClickHouse, SDB=SurrealDB, R=Redis, K=Kafka, MB=Metabase.

| Service/process | Actual responsibility and owned data | Reads/writes and outgoing dependencies | Auth, failure, tests, deployability verdict |
|---|---|---|---|
| API gateway | Static edge routes; SQLite is unused | HTTP to all business services; buffers bodies/responses | Header-presence only; 360s timeout, no streaming; in-memory rate limit; 2 tests; independently replaceable but a weak edge |
| Auth | Users, password-reset codes, JWT/admin | PG `users`, `password_reset_codes`; workspace/notification calls | JWT/password controls; focused invitation tests; logically ownable, not credential-isolated |
| Workspace | Workspaces, members, invitations | PG owned tables; auth internal lookup; notification | JWT/roles plus internal shared token; 4 focused tests; logically ownable, shared PG account |
| Query | Dataset/source snapshot metadata and authorized query definitions; SQL execution | PG `manager_databases`, `authorized_query_definitions`; CH; connector; workspace claims | JWT; fail-closed on cross database but not same-DB foreign table; 79 tests; critical owner but overloaded with Integration |
| Voice | Reports, SQL edits, dashboard pages, assignments, pipeline jobs; product orchestration | PG owned tables; filesystem; AI, query, workspace, subscription, visualization, notification; K; local CH fallback | JWT/roles; 20 maintained focused tests; central monolith, not independently resilient |
| Report | No runtime business data; proxy routes | Raw HTTP to voice. Duplicate models/services are unwired | JWT then forwards; 90s timeout; 5 normalization tests do not test proxy; merge/remove candidate |
| Visualization | Metabase object ownership | PG `visualization_object_ownership`; query; MB; Ollama chart selector | JWT/workspace checks; 63 tests; separate boundary justified if MB integration retained |
| Subscription | Plans, subscriptions, simulated payments, free-tier voice counter | PG owned tables; workspace/auth summaries; notification | JWT/roles; atomic counter; 3 smoke tests; ownership valid but model is demo-grade |
| Notification | Dispatch log and email/expiry processing | Writes PG log; directly reads auth/workspace/subscription tables; voice link | Internal key for event endpoint; 4 smoke tests; violates ownership, tightly schema-coupled |
| AI | Stateless-claimed voice/intent/SQL/forecast compute; local SQLite/Django admin state | R queue/lock, CH schema, Ollama, OpenRouter, TimesFM files | Shared internal API key; 235 deterministic tests; deployable only as one serialized, synchronous worker |
| ETL connector | Upload scan, connector capabilities, test/discover/snapshot kickoff | filesystem, ClamAV, source DB, K, SDB connection log | Internal key; extensive Django tests; should be Integration ingress, but has no durable source owner |
| ETL extractor | Source/file read and raw row publication | K, source DB/files, credential decrypt | Internal HTTP plus K; 220 tests with 5 skips; restart/replay depends on event retention |
| ETL transformer | Clean, schema rules, quality/quarantine | K, CH/SDB-side quality helpers | Internal API/K; 12 tests with 1 skip; side effects can be skipped |
| ETL loader | Batch/dedupe/schema and CH writes | K, CH, in-memory buffers, DLQ | Internal API/K; 14 tests with 1 skip; no CDC update/delete model |
| ETL metadata | Lineage/quality/status APIs and listeners | K, SDB, query callback | Internal key; 4 tests; legacy load status drops tenant scope |
| ETL detector | Observes raw events for distinct/group hints | K; emits metadata | Internal key; 4 tests; not a reliability agent or data mutation owner |
| Notification expiry worker | Periodically invokes a management command | Shared notification PG/domain projections and email | Shell loop/heartbeat; same image/schema; worker process, not a separate service |

Infrastructure containers (Kafka/ZooKeeper, Redis, ClickHouse, SurrealDB/init, Metabase/PostgreSQL, ClamAV, Kafka UI) are development dependencies. None is configured as a production-owned HA service.

## Shared-code and hidden coupling

`bi_platform_shared` is appropriate for transport contracts, SQL parsing, IDs, health, and observability primitives. It should not grow business repositories or rules. ETL's `shared` package is effectively an internal data-platform SDK and is acceptable if released/versioned as one subsystem. Many services bypass `bi_platform_shared.http.client` and use raw `requests`, producing inconsistent timeouts, retries, tracing, error mapping, and circuit behavior.

Readiness is also coupled: gateway checks all downstreams; voice checks AI/query/visualization/subscription/Metabase; report checks metadata/query/Metabase despite only proxying voice; visualization checks query/report/Metabase; notification checks voice. This turns optional/degraded dependencies into broad unavailability.

## Recommended domain owners

| Domain | Recommended owner | Decision |
|---|---|---|
| Identity/User + Authentication | Auth service | KEEP; its schema/account must be isolated |
| Workspace/membership | Workspace service | KEEP; consume identity events/snapshots, never auth tables |
| Data Source / Integration | **New logical Integration capability** | SPLIT ownership from Query/Connector; initially co-deploy module/schema in Query control plane; owns durable sources, opaque secret references, tests, schedules, CDC configuration/status |
| ETL/Ingestion | Data Platform (connector/extractor/transformer/loader/metadata workers) | KEEP as one operational subsystem, not six autonomous teams |
| Query Definition + Execution | Query service | KEEP; enforce dataset/table allowlist and resource policy |
| Semantic Model | Semantic module initially inside AI/control plane with its own schema and API | ADD; extract service only if scaling/ownership proves necessary |
| Reports/dashboard composition | Voice service renamed/refactored to Insights service | KEEP/MERGE report proxy into this owner |
| Visualization | Visualization service | KEEP; owns MB object lifecycle, not SQL authorization |
| Subscription/Billing/Metering | Subscription service | REFACTOR into entitlement + append-only usage ledger; provider webhook owns payment truth |
| Notifications | Notification service | KEEP; use APIs/events/projections it owns, not foreign tables |
| AI/Reasoning + Voice compute | AI service, with separate worker pools by resource profile | REFACTOR internally; do not make every model a service |
| RAG/Knowledge | Knowledge module/service | ADD only for document lifecycle/retrieval; PostgreSQL + pgvector is the default candidate after ADR |
| Agent Execution | AI orchestrator | ADD as a single agent with governed tools |
| MCP/Actions | Tool Gateway | ADD only when an approved action exists; isolate secrets/policies |
| Monitoring | Platform/SRE ownership | ADD collector/backend and SLOs; application services only emit telemetry |
| Data Reliability | Data Platform control plane | ADD rules/runs/incidents; reuse ETL metrics, metadata, and notification |

## Data Source ownership decision

Introduce an **Integration logical capability**, initially as an isolated module/schema in the Query control-plane deployment. The domain is justified by its distinct lifecycle and secret boundary: sources, vault references, network transport, test/discovery, snapshot/CDC modes, connector state, schema history, offsets, rotation, and deletion. It receives a separate deployment only if secret/egress isolation, scale, failure containment, or team ownership proves the need. Query remains the analytical execution authority; connector workers remain the data plane.

For a two-person project, build it pragmatically by extracting current query source endpoints/models into a small service or strongly isolated module/schema and reusing the connector adapter registry. Do not rewrite working extractors. Its public API should expose source IDs and capabilities, never raw credentials; workers should receive short-lived secret leases. It should publish versioned `integration.source.*` and `ingestion.job.*` events and own Kafka Connect/Debezium configuration references. VPN/private-agent transports must implement a `ConnectionTransport` strategy behind this owner.

Migration cost is medium-high: add source rows, import current `manager_databases` records, change workspace→source cardinality, replace raw credential forwarding, and update query/voice dataset binding. The benefit is foundational: CDC, credential rotation, multiple sources per workspace, schedules, private networks, deletion, audit, and metering become coherent.

## Merge/split decisions

- **MERGE/REMOVE report-service proxy** after gateway routes report paths directly to the actual Insights/Voice owner. Archive the unwired duplicate models/services only after import/route/test evidence is captured.
- **SPLIT Integration from Query**, but keep the six ETL processes under one Data Platform ownership boundary.
- **Do not split AI into many microservices.** Use one API/control component plus distinct Whisper/LLM/forecast worker queues when capacity evidence requires it.
- **Do not add a service per agent, metric, connector, or semantic entity.** These are modules/tools until independent scale, security, or ownership is proven.
