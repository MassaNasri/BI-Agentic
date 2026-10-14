# Database and data ownership audit

> **v2 reconciliation:** Ownership comes before physical separation. Week 14 may use one managed PostgreSQL cluster, but Auth, Workspace, Query, Integration, and Entitlements/Metering must have explicit owner schemas/databases, dedicated least-privilege roles, migration ownership, and denied cross-domain writes. Remaining domains may migrate incrementally when API/event seams and rollback plans exist. No plan requires a separate PostgreSQL server per service.

## Executive finding

Database-per-service is violated at the logical security boundary, not merely because services share a PostgreSQL server. Auth, workspace, query, voice, report, visualization, subscription, and notification all default to `DB_NAME=bi_voice_agent` and `DB_USER=bi_admin`; the root environment supplies one host/name/account. This means migrations share one namespace and a compromised service account can read or mutate other domains. Notification intentionally demonstrates the coupling with unmanaged ORM projections.

Sharing one PostgreSQL cluster is acceptable. Sharing one schema and privileged account is not. The target should use separate schemas/databases, per-owner roles, default-deny grants, and APIs/events for cross-domain access.

## Current table ownership

| Physical table(s) | Intended owner | Other direct readers/writers | Classification |
|---|---|---|---|
| `users`, `password_reset_codes` | Auth | Notification maps `users`; report legacy models reference auth model if installed | CRITICAL ownership violation |
| `workspaces`, `workspace_members`, `invitations` | Workspace | Notification maps workspace/member tables; report legacy models import workspace | CRITICAL ownership violation |
| `manager_databases`, `authorized_query_definitions` | Query | No foreign ORM mutation found; voice/visualization use HTTP | Owner is coherent, but Integration and Query concerns are conflated |
| `voice_reports`, `sql_edit_history`, `dashboard_pages`, `report_page_assignments`, `voice_pipeline_jobs` | Voice/Insights | Report contains duplicate models for four tables but they are not installed | Duplicate schema code; current runtime owner is voice |
| `visualization_object_ownership` | Visualization | No foreign direct ORM found | Acceptable logical owner |
| `subscription_plans`, `workspace_subscriptions`, `subscription_payments`, `subscription_free_tier_usage` | Subscription | Notification maps plans/subscriptions | CRITICAL direct-read coupling |
| `notification_dispatch_logs` | Notification | None found | Acceptable owner |
| AI/ETL SQLite tables | Individual services | Mostly Django framework/local state | Not production-critical, but persistent lifecycle is undefined |
| ClickHouse dataset tables | Query authorization / Data Platform physical write | Loader writes; query and AI read; voice local fallback reads | Authorization is ambiguous and currently unsafe |
| SurrealDB metadata/lineage/quality | Data Platform metadata owner | Metadata API and connector logs | Scope is inconsistent on legacy `load_status` records |
| Metabase application DB | Metabase | Metabase only | Appropriate; separate from business PG |

## Critical tenant-isolation defect

All uploaded datasets normally bind to ClickHouse database `etl`. `QueryExecuteInternalView` validates the requested workspace against the JWT, then `execute_sql_payload()` calls `resolve_workspace_clickhouse_db()` and creates `SQLGuard(workspace_database=...)`. It does **not** resolve the dataset/table or pass `allowed_tables`. The shared guard permits any ordinary table in the allowed database.

Tenant-qualified names (`w{workspace}_d{dataset}_...`) improve collision avoidance but do not prevent a workspace from querying another workspace's table if its name is guessed, logged, or disclosed. `DatabaseSerializer` also returns top-level `clickhouse_table_name` and `clickhouse_database`, despite its method comment promising not to expose the physical storage name.

Required target behavior:

1. Every query is bound to an authoritative dataset/source ID.
2. Query-service resolves `(workspace_id, dataset_id)` to an exact allowlist of physical tables and join paths.
3. The AST guard receives this allowlist; default is deny.
4. The ClickHouse service identity receives row/database/table permissions consistent with that binding where practical.
5. Same-database cross-tenant attempts are first-class security regression tests.
6. AI never receives broader schema/credentials than the bound dataset.

## Fail-open duplicate access

Voice-service validates SQL against the global `CLICKHOUSE_DATABASE` and normally calls query-service. On a `requests.RequestException`, it invokes its own `get_clickhouse_executor()` with global credentials. This bypasses the workspace→dataset binding and recreates query logic in a second service. Report-service carries a third legacy ClickHouse executor, though unwired. Remove all non-query runtime execution paths; query unavailability must fail closed.

## Source/data model limitations

`Database.manager` is unique and the class docstring says one database per manager. Workspace is nullable. This prevents a workspace from managing multiple sources, makes membership/ownership changes awkward, and conflicts with a CDC control plane. `source_tables` is JSON and top-level fields hold one physical table/database, which is inadequate for a durable multi-table source model.

The current snapshot start path replaces prior manager metadata and cleans previous physical state before the new asynchronous job proves successful. That is a destructive cutover/race risk. Use immutable source, dataset version, ingestion job, and table binding records; publish/cut over only after validation, retaining the last good version for rollback.

## Target ownership and schema layout

One managed PostgreSQL cluster is sufficient for Week-14 production:

| Schema/database role | Owner | Principal/grants |
|---|---|---|
| `identity` | Auth | Auth RW; notification consumes API/event projection only |
| `workspace` | Workspace | Workspace RW; no other business service table grant |
| `integration` | Integration | Source metadata, secret references, connectors, CDC configs/status |
| `query` | Query | Dataset/table bindings, authorized definitions, execution audit |
| `insights` | Insights (current Voice) | Reports, pages, jobs, result references |
| `visualization` | Visualization | Metabase object ownership/idempotency |
| `billing` | Subscription | Plans, entitlements, payments, usage ledger/reservations |
| `notification` | Notification | Dispatch/outbox-consumer projections it owns |
| `semantic` | Semantic/AI control plane | Models, versions, entities, metrics, review states |
| `knowledge` | Knowledge | Documents, ACLs, chunks, embeddings, citations |
| `actions` | Tool Gateway | Proposals, approvals, executions, audit |

Use per-schema owner roles and separate runtime roles with only required DML. Migration jobs use owner roles; application pods do not. PostgreSQL row-level security can be defense in depth for workspace-scoped tables, but must not replace service authorization.

## Cross-domain consistency

- Workspace membership changes: Workspace outbox → consumers update owner-specific projections/caches.
- Subscription entitlements: Billing outbox → entitlement projection/API; do not map billing tables.
- Report completion: Insights outbox → notification/usage events.
- Source state: Integration outbox → Data Platform/query projections.
- Cross-service workflows use state machines and idempotency, not cross-schema transactions.

## Database-specific operational gaps

- Core business PostgreSQL is not a root Compose service, yet local runtime depends on `host.docker.internal`; backup, HA, TLS, connection pooling, migration ordering, and recovery ownership are not defined here.
- ClickHouse queries have no proven server-side max rows/bytes/execution time/readonly settings. Full results are loaded into memory and persisted in PG JSON.
- Kafka/Surreal/ClickHouse data retention and backup are not defined; engine data is committed to Git instead.
- Migration drift passes with `--skip-checks`; report-service's duplicate models are not installed, so its pass does not validate them. Several drift checks warn they cannot inspect live migration history.
- There is no data deletion/retention workflow covering audio, reports, query results, Kafka events, DLQ/quarantine, Surreal metadata, Metabase objects, AI traces, and source secrets.

## Migration approach

Do not big-bang split physical servers. First close ClickHouse tenant authorization. Next inventory grants and introduce owner schemas/roles in the existing cluster. Move one domain at a time with reconciliation, dual-read only when explicitly bounded, outbox-backed projection, tested rollback, and a write freeze/cutover plan. Remove notification foreign models after its projections/API are live. Migrate report routing before archiving duplicate code.
