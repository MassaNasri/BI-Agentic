# 31 — Canonical service and domain ownership

Revision 3.0 · 2026-10-27 · Target **10 January 2027**. [43](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md) governs scope; [ADR-023](46_ADR_023_PRESENTATION_OWNERSHIP_AND_PROVIDER_ABSTRACTION.md) supersedes prior Report deletion/migration assumptions.

| Domain | Current repository reality | January target owner / deployment | Data and allowed interactions |
|---|---|---|---|
| Frontend / Edge | React and application Gateway | Existing deployments, hardened edge | UX/routing only; trusted context never inferred from header presence |
| Auth | Identity/JWT/password reset | Auth owner schema/role | User/session state; owned APIs/events |
| Workspace | Workspace/member/invitation | Workspace owner schema/role | Membership/role authority at every protected boundary |
| Integration | Implemented app in Query deployment | Keep logical Integration, separate DB alias/role | Sources, encrypted credential versions/grants, configuration/transport, snapshot/CDC lifecycle; Connector/Connect control |
| Query | Dataset, query definitions, execution | Keep Query | Dataset bindings, exact analytical allowlist, read-only bounded Query/Schema APIs; sole analytical authority |
| Data Platform | Six ETL applications and shared library | Keep subsystem; add PostgreSQL Connect/Debezium/normalizer after G-C-LOCAL plus G-CI | Snapshot/WAL events, transforms, loader writes, scoped metadata, checkpoints/recovery |
| Semantic | Lexical helpers, no governed persistent model | Logical owner in AI/control deployment with owned schema/role | Versioned definitions/formula validation/review/publication; Query compiles/executes |
| Modeling Agent | Missing governed proposal workflow | AI worker | Propose/explain/validate; only authorized human workflow may publish |
| Analyst / ModelProvider | Fixed AI pipeline, fragmented providers | One durable AI orchestrator + in-process facade | Typed authorized tools, minimum schema/results, evidence/narrative, token/cost telemetry |
| Trust / What-if | Traces and forecast helpers | Logical contracts in Analyst, evidence referenced by owning analysis/report | Reproducible evidence, metric/query/data versions, separate observed/forecast/scenario |
| Limited Reliability | ETL signals/quality helpers | Data Platform owns signals; Analyst consumes warning contract | On-demand/pre-analysis freshness/lag/null/missing-field checks; no business-monitor investigation loop |
| Voice and legacy saved reports | Voice owns actual report/page/job tables | Maintain existing owner and secured input path | Existing reports remain through authorized APIs; job/context hardening still required |
| Report proxy | Existing service forwards to Voice | Preserve compatibility during January | No foreign ORM ownership; do not delete deployment based on old map |
| Presentation | Not implemented | New logical domain co-deployed with Report + worker | New jobs/specs/manifests/artifacts/retention; references legacy reports by API |
| Visualization | Governed chart contracts and Metabase object mapping | Existing logical owner/deployment | Reuse VisualizationSpec; Query-authorized definitions/results only |
| PresentationProvider | No adapters | SlidesGPTProvider and GammaProvider | Vendor contract mapping, no analytics; MCP or approved REST through governed egress |
| Action policy / approval | Missing runtime; entitlement flag only | Owned control module/state, isolated governed execution gateway | Bound proposals/approvals/audit; exact tool/schema/origin allowlist; external credentials never AI |
| Entitlements / Metering / Billing / Payments | Subscription containment and coarse counters | Distinct modules/state in Subscription initially | Trusted feature limits; immutable resource ledger; separate billing/payment truth |
| Notification | Dispatch plus foreign unmanaged ORM projections | Owned event/read projections, existing deployment | Remove foreign table dependency before required operations rely on it |
| Operations | CI/health/assets, development Compose | Platform owner across deployments | Supported runtime, secrets/identity/TLS, logs/metrics/traces, backups/restore, release/support |

One authoritative writer per aggregate. Managed PostgreSQL owner schemas/roles may share a cluster; no foreign ORM mutations. Runtime roles cannot migrate. Loader write identity and Query analytical identity are distinct. Existing Metabase rendering is a controlled, Query-authorized compatibility path needing least-privilege certification; external deck vendors never inherit it.

Presentation owns new-domain persistence; Voice owns legacy report persistence. This temporary distinction is intentional and does not create duplicate writers. Legacy report consolidation requires a separate migration/cutover/rollback decision. Logical contracts come first; extract deployments only after measured security/failure/scaling benefit.

Object storage is private, tenant scoped and retention controlled. Kafka is a versioned scoped event/data plane with declared producer/consumer, ACL, ordering/replay/DLQ policy. Metering has append-only usage and reservation transitions. Secrets manager access is per workload, with separate staging/production identities.

Knowledge/RAG, Proactive Monitoring Agent and Arabic & Voice Support expansion are outside January scope; no ownership row here authorizes those features. Existing dormant code is preserved. See 48 for historical plans and references.
