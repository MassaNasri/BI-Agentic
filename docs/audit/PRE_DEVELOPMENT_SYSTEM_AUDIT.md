# Pre-development system audit

Audit date: 2026-09-13. Repository: BI-Voice-Agent. Branch main, source HEAD 1ca062c (2026-05-08). The working tree already contained extensive staged/unstaged/untracked changes; snapshot is in inventory.json. The parent folder is not a usable Git repository. No user changes were discarded and no architectural refactor was performed.

## Executive assessment

**NOT READY for production. Phase 0 completion depends on the reset/startup evidence in DATA_STORAGE_AND_WIPE_REPORT.md; generating reports alone is not success.** There are 38 actionable findings: {'CRITICAL': 8, 'HIGH': 23, 'MEDIUM': 6, 'LOW': 1}. Critical findings include fail-open workspace authorization, unscoped Metabase operations/SQL, retained historical secrets, public ETL APIs and insecure persistence. Existing hardening is meaningful in query SQL AST checks, explicit workspace dataset binding, shared HTTP transport, upload validation/ClamAV and ETL idempotency helpers. These controls are incomplete across alternate paths.

Source inventory scanned 819 selected first-party source/config files, 171 route declarations, 76 model classes including inactive/DTO-like classes, 245 environment names and 121 test files. Full file lists are in inventory.json. Database binary contents were inventoried/backed up separately, not treated as source. Vendor TimesFM is a nested upstream checkout; its source/test suite was not exhaustively audited. Generated caches, dependencies, datasets and previous prose audits are not treated as proof. This is broad recursive static inspection plus targeted runtime and behavioral verification, not a guarantee that every possible issue was found.

## Architecture and inventories

The active source is a mixed Django service system, not a strict database-per-service architecture. PostgreSQL is a Windows-host service, Metabase is a standalone stopped container with H2 metadata, and Ollama runs on the host. Unified Compose has 24 entries. The ETL stack uses Django web processes plus Kafka listeners, shared persistence code and shared files. Report-service forwards CRUD to voice-service. AI directly reads ClickHouse and coordinates transcription through Redis. There is a routing gateway but no configured TLS reverse proxy.

See [service inventory](SERVICE_INVENTORY.md), [database ownership](DATABASE_OWNERSHIP_MATRIX.md), [environment inventory](ENVIRONMENT_VARIABLE_INVENTORY.md), [API inventory](API_INVENTORY.md), [communication matrix](SERVICE_COMMUNICATION_MATRIX.md), [current diagrams](CURRENT_ARCHITECTURE.md) and [test evidence](TEST_EXECUTION.md). Runtime_inventory.json enumerates all 555 volumes, 32 containers and Docker networks; unknown resources are preserved.

## Operational and code-quality observations

Core HTTP services use Django runserver, root defaults and broad env_file injection. Startup ordering includes an unnecessary chain through AI/ETL/visualization before the gateway becomes healthy; a ClamAV or AI failure can prevent unrelated auth access. ETL listeners are not separately supervised from web servers. Root and legacy Compose conflict in container names and host ports and must not be launched together.

Largest source modules: voice views 3727 lines; AI query planner 2592; AI execution asset 2034; visualization Metabase client 1482; dashboard shell 1324; transcription task 1249. Repeated Metabase clients, SQL normalization variants, JWT principals, broad exceptions and sys.path mutation make invariants drift. Inactive report ORM is documented as inactive, not falsely classified as an active cross-database join. Query and visualization tests passed, while AI/ETL contracts and lint are not green. No first-party CI/deployment gate was discovered.

Dependency risk includes unsupported Django 4.2, broad Python requirements and floating images. The Django support conclusion was checked against [Django's support table](https://www.djangoproject.com/download/). Metabase H2 handling follows [the vendor backup guidance](https://www.metabase.com/docs/latest/installation-and-operation/backing-up-metabase-application-data). Exact vulnerability inventory, installed-image SBOM, RLS/grant penetration tests, load tests and all end-to-end API behaviors remain NOT VERIFIED.

## Findings

### SEC-001 — Workspace denial retains the untrusted requested workspace

| Field | Finding |
| --- | --- |
| severity | CRITICAL |
| category | Tenant isolation |
| service | voice-service |
| description | Workspace denial retains the untrusted requested workspace |
| why_it_is_a_problem | A mocked workspace HTTP 403 still returned workspace 999999. Report and page queries then scope to that ID. A manager from one tenant can potentially read or change another tenant. This is a reproduced helper-level failure, not a live attack on user data. |
| evidence | services/voice-service/voice_reports/infrastructure/workspace_client.py:125; services/voice-service/voice_reports/infrastructure/auth_context.py:35; services/voice-service/voice_reports/dashboard_builder_views.py:41; services/voice-service/voice_reports/views.py:313 |
| risk | A mocked workspace HTTP 403 still returned workspace 999999. Report and page queries then scope to that ID. A manager from one tenant can potentially read or change another tenant. This is a reproduced helper-level failure, not a live attack on user data. |
| solution | Require a successful membership decision; reject 403/404 and fail closed on timeout. Never retain an unvalidated hint. Add two-tenant tests for page/report read, edit, delete and query history. |
| migration_impact | Changes denied/error requests to 403/503. No schema change; legitimate membership paths need regression tests. |
| estimated_complexity | Medium |
| when | Before development |

### SEC-002 — Metabase embedding and dashboard mutation lack object ownership checks

| Field | Finding |
| --- | --- |
| severity | CRITICAL |
| category | Tenant isolation |
| service | visualization-service |
| description | Metabase embedding and dashboard mutation lack object ownership checks |
| why_it_is_a_problem | Any authenticated principal can supply question/dashboard IDs; the service signs embed URLs or attaches cards using shared Metabase privileges. No tenant-object mapping is checked in these handlers. |
| evidence | services/visualization-service/visualization_api/views.py:237; services/visualization-service/visualization_api/views.py:267; services/visualization-service/visualization_api/views.py:281; services/api-gateway/gateway/routing.py:90 |
| risk | Any authenticated principal can supply question/dashboard IDs; the service signs embed URLs or attaches cards using shared Metabase privileges. No tenant-object mapping is checked in these handlers. |
| solution | Store tenant ownership for every card/dashboard in visualization_db; authorize both objects before mutation or signing; use short-lived scoped embeds. Restrict creation to service callers or authorized tenant roles. |
| migration_impact | Backfill ownership from report records before enforcing. Quarantine unmappable cards; preserve Metabase metadata. |
| estimated_complexity | Large |
| when | Before development |

### SEC-003 — Raw visualization SQL bypasses the query service security boundary

| Field | Finding |
| --- | --- |
| severity | CRITICAL |
| category | SQL security |
| service | visualization-service |
| description | Raw visualization SQL bypasses the query service security boundary |
| why_it_is_a_problem | CreateQuestion accepts user SQL, applies formatting normalization, creates a native Metabase query and validates execution. Formatting is not AST validation or tenant authorization. Actual accessible data depends on Metabase source grants. |
| evidence | services/visualization-service/visualization_api/views.py:36; services/visualization-service/visualization_api/views.py:132; bi_platform_shared/sql/normalization.py:42 |
| risk | CreateQuestion accepts user SQL, applies formatting normalization, creates a native Metabase query and validates execution. Formatting is not AST validation or tenant authorization. Actual accessible data depends on Metabase source grants. |
| solution | Accept an authorized query-result/query-definition ID from query-service, never arbitrary SQL. Execute only an AST-approved tenant-bound definition with a read-only source identity. |
| migration_impact | Changes visualization request contract; migrate voice caller with a compatibility flag and contract tests. |
| estimated_complexity | Medium |
| when | Before development |

### SEC-004 — Historical credentials remain equal to current local credentials

| Field | Finding |
| --- | --- |
| severity | CRITICAL |
| category | Secrets |
| service | platform |
| description | Historical credentials remain equal to current local credentials |
| why_it_is_a_problem | Local ADMIN_PASSWORD, METABASE_SECRET_KEY, NOTIFICATION_SERVICE_API_KEY, AI_SERVICE_INTERNAL_API_KEY and OPENROUTER_API_KEY match nonempty values in the tracked historical file. Exposure risk remains after removing the working file. No external key validity was tested. |
| evidence | Git HEAD:.env.microservices (historical blob); .env (values withheld); docs/audit/runtime_inventory.json |
| risk | Local ADMIN_PASSWORD, METABASE_SECRET_KEY, NOTIFICATION_SERVICE_API_KEY, AI_SERVICE_INTERNAL_API_KEY and OPENROUTER_API_KEY match nonempty values in the tracked historical file. Exposure risk remains after removing the working file. No external key validity was tested. |
| solution | SECRET ROTATION REQUIRED: revoke/replace OpenRouter key, admin password, service keys and embedding key; invalidate sessions/embeds; rotate all historically stored DB/Metabase/JWT credentials if not already done. Coordinate history remediation separately; never rewrite user history automatically. |
| migration_impact | Rotating signing/service keys invalidates sessions and requires coordinated deployment. External provider administration remains outside this audit. |
| estimated_complexity | Medium |
| when | Before development |

### SEC-005 — ETL upload, connection and metadata APIs lack authenticated tenant scope

| Field | Finding |
| --- | --- |
| severity | CRITICAL |
| category | API security |
| service | ETL |
| description | ETL upload, connection and metadata APIs lack authenticated tenant scope |
| why_it_is_a_problem | APIView defaults are public without explicit permissions. The connector writes files and triggers jobs; metadata returns global logs. Host-published ports let clients bypass the gateway. File events use filename/source_id without tenant identity. |
| evidence | etl-final/connector-service/connector/etl_engine/views.py:78; etl-final/connector-service/connector/connector/settings.py:38; etl-final/metadata-service/metadata/api/views.py:19; docker-compose.yml:483 |
| risk | APIView defaults are public without explicit permissions. The connector writes files and triggers jobs; metadata returns global logs. Host-published ports let clients bypass the gateway. File events use filename/source_id without tenant identity. |
| solution | Require scoped service authentication and a verified tenant/dataset/job context at ingress and every stage. Remove public ETL ports. Namespace source IDs and authorize lineage/quality access. |
| migration_impact | Version event/API payloads and backfill or quarantine unowned data; retain old pipeline only on an isolated migration network. |
| estimated_complexity | Large |
| when | Before development |

### SEC-006 — User-provided database hosts allow internal-network connections

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | SSRF |
| service | etl-connector |
| description | User-provided database hosts allow internal-network connections |
| why_it_is_a_problem | Validation accepts localhost and syntactically valid hostnames. ConnectDB connects directly with supplied host/port; no resolved-IP allowlist or egress boundary was found. |
| evidence | etl-final/shared/utils/input_validator.py:237; etl-final/connector-service/connector/etl_engine/views.py:170; etl-final/connector-service/connector/etl_engine/utils.py:7 |
| risk | Validation accepts localhost and syntactically valid hostnames. ConnectDB connects directly with supplied host/port; no resolved-IP allowlist or egress boundary was found. |
| solution | Use a connector network with explicit destination authorization; block loopback/link-local/metadata/private ranges by default, with administrator-approved private connectivity. Validate every resolved address and connection timeout. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | Before development |

### SEC-007 — Credential encryption silently falls back to a source-known key

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Secrets |
| service | ETL |
| description | Credential encryption silently falls back to a source-known key |
| why_it_is_a_problem | Missing CREDENTIAL_SECRET_KEY selects a fixed default and fixed salt; root ETL environment blocks do not provide the key. Encrypted source credentials in Kafka can therefore be recoverable with the source default. |
| evidence | etl-final/shared/utils/credential_encryption.py:29; docker-compose.yml:492 |
| risk | Missing CREDENTIAL_SECRET_KEY selects a fixed default and fixed salt; root ETL environment blocks do not provide the key. Encrypted source credentials in Kafka can therefore be recoverable with the source default. |
| solution | Fail fast on missing key; use a secret reference and key version per connection. Re-encrypt existing connections with a new key and revoke affected source credentials. |
| migration_impact | Keep old decrypt-only key solely for controlled migration; do not lose access to existing encrypted records. |
| estimated_complexity | Medium |
| when | Before development |

### SEC-008 — Development settings and insecure fallback signing keys remain

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Configuration |
| service | ETL and Django services |
| description | Development settings and insecure fallback signing keys remain |
| why_it_is_a_problem | ETL uses hardcoded Django secrets, DEBUG=True and wildcard hosts; core services still have fallback secrets even though root Compose validates several variables. Direct service startup can bypass launcher checks. |
| evidence | etl-final/connector-service/connector/connector/settings.py:28; etl-final/metadata-service/metadata/metadata/settings.py:28; services/auth-service/service_config/settings.py:12; services/ai-service/backend/settings.py:33 |
| risk | ETL uses hardcoded Django secrets, DEBUG=True and wildcard hosts; core services still have fallback secrets even though root Compose validates several variables. Direct service startup can bypass launcher checks. |
| solution | Implement explicit environment profiles and service startup validation; reject missing/placeholder secrets with DEBUG off. Require exact hosts and configure TLS/cookie/HSTS settings for production. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | Before development |

### SEC-009 — Databases, broker, AI and internal APIs bind host ports on all interfaces

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Infrastructure |
| service | platform |
| description | Databases, broker, AI and internal APIs bind host ports on all interfaces |
| why_it_is_a_problem | Runtime PortBindings expose 8001-8010, 8101-8106, Redis 6379, ClickHouse 8123/9000, Kafka 9092, ZooKeeper 2181, SurrealDB 8008 and Kafka UI 8081. Firewall reachability was not tested. Redis has no requirepass in its command and Kafka uses PLAINTEXT. |
| evidence | docker-compose.yml:1; docs/audit/runtime_inventory.json |
| risk | Runtime PortBindings expose 8001-8010, 8101-8106, Redis 6379, ClickHouse 8123/9000, Kafka 9092, ZooKeeper 2181, SurrealDB 8008 and Kafka UI 8081. Firewall reachability was not tested. Redis has no requirepass in its command and Kafka uses PLAINTEXT. |
| solution | Keep only the TLS edge public; bind diagnostic dev ports to 127.0.0.1 in a development override. Segment service/database networks; introduce Redis ACLs and broker authentication if retained. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | Before development |

### SEC-010 — A shared env_file distributes unrelated credentials to every core container

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Secrets |
| service | all core services |
| description | A shared env_file distributes unrelated credentials to every core container |
| why_it_is_a_problem | Auth, notification, AI/provider, database and embedding secrets are broadly distributed. A compromised low-trust proxy can expose credentials unrelated to its responsibility. |
| evidence | docker-compose.yml:118; docs/audit/runtime_inventory.json (env_names) |
| risk | Auth, notification, AI/provider, database and embedding secrets are broadly distributed. A compromised low-trust proxy can expose credentials unrelated to its responsibility. |
| solution | Create service-specific variable allowlists and secret mounts. Separate JWT verification public keys from auth signing keys and limit Metabase credentials to visualization. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | During restructuring |

### SEC-011 — HS256 verification keys also permit signing, with stale stateless user claims

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Authentication |
| service | core services |
| description | HS256 verification keys also permit signing, with stale stateless user claims |
| why_it_is_a_problem | Services share signing material and trust JWT role/active/workspace claims. Revoked membership or deactivated users can retain access until expiry unless the route performs a fresh ownership check. Auth uses a one-hour access lifetime and disables refresh rotation. |
| evidence | services/auth-service/service_config/settings.py:121; services/workspace-service/workspace/authentication.py:39; services/query-service/service_config/settings.py:111 |
| risk | Services share signing material and trust JWT role/active/workspace claims. Revoked membership or deactivated users can retain access until expiry unless the route performs a fresh ownership check. Auth uses a one-hour access lifetime and disables refresh rotation. |
| solution | Auth owns asymmetric signing/JWKS, issuer/audience validation, short access expiry and refresh rotation/reuse detection. Check live membership for sensitive actions through workspace APIs. Test deactivation and revoked invitations. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Large |
| when | During restructuring |

### SEC-012 — Browser tokens are stored in localStorage and refresh has no single-flight handling

| Field | Finding |
| --- | --- |
| severity | MEDIUM |
| category | Frontend security |
| service | frontend |
| description | Browser tokens are stored in localStorage and refresh has no single-flight handling |
| why_it_is_a_problem | XSS would expose both tokens; simultaneous 401s race refresh. Current auth rotation is disabled, so ignoring returned refresh is a future rotation integration defect, not a currently proven logout bug. Axios also has no global timeout. |
| evidence | frontend/src/api/axios.js:18; frontend/src/api/axios.js:40; frontend/src/store/auth.js:25; services/auth-service/service_config/settings.py:124 |
| risk | XSS would expose both tokens; simultaneous 401s race refresh. Current auth rotation is disabled, so ignoring returned refresh is a future rotation integration defect, not a currently proven logout bug. Axios also has no global timeout. |
| solution | Prefer an HttpOnly Secure SameSite refresh cookie with CSRF protection, access token in memory, CSP and one refresh promise. Persist rotated refresh if bearer refresh is retained; bound browser requests. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | Before production |

### SEC-013 — ClickHouse credentials are placed in URL query parameters

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Logging |
| service | query-service |
| description | ClickHouse credentials are placed in URL query parameters |
| why_it_is_a_problem | Requests puts user/password into the URL; error logging includes exception strings that may carry the full URL. Proxy/access logs can expose credentials. |
| evidence | services/query-service/database/utils.py:21 |
| risk | Requests puts user/password into the URL; error logging includes exception strings that may carry the full URL. Proxy/access logs can expose credentials. |
| solution | Use auth headers over TLS, sanitize connection errors, redact URL credentials and query tokens from structured logs. Rotate affected ClickHouse credentials if logged. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Small |
| when | Before development |

### ARC-001 — Nine core Django processes share one logical PostgreSQL database and account

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Database ownership |
| service | core services |
| description | Nine core Django processes share one logical PostgreSQL database and account |
| why_it_is_a_problem | Runtime bi_voice_agent has 27 tables owned by bi_admin, which also has CREATEDB. Independent services can alter each other's data and share Django migration/admin state. A configured DB connection in a stateless proxy is not evidence of domain reads, but still grants access. |
| evidence | services/*/service_config/settings.py DATABASES; docs/audit/runtime_inventory.json postgres; docker-compose.yml env_file |
| risk | Runtime bi_voice_agent has 27 tables owned by bi_admin, which also has CREATEDB. Independent services can alter each other's data and share Django migration/admin state. A configured DB connection in a stateless proxy is not evidence of domain reads, but still grants access. |
| solution | Create logical DBs and least-privileged roles for auth, workspace, report, voice jobs, query, subscription and notification; remove DB dependency from gateway and stateless proxies. Separate migration roles. |
| migration_impact | Use owner APIs first, then snapshot/backfill with IDs preserved and reconciliation before credential cutover. |
| estimated_complexity | Large |
| when | During restructuring |

### ARC-002 — Notifications directly query five tables owned by other domains

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Database ownership |
| service | notification-service |
| description | Notifications directly query five tables owned by other domains |
| why_it_is_a_problem | Unmanaged ORM mappings cover users, workspaces, workspace_members, subscription_plans and workspace_subscriptions. Services and expiry worker rely on joins across domains. |
| evidence | services/notification-service/notification/models.py:41; services/notification-service/notification/services.py:80 |
| risk | Unmanaged ORM mappings cover users, workspaces, workspace_members, subscription_plans and workspace_subscriptions. Services and expiry worker rely on joins across domains. |
| solution | Use authenticated paginated workspace recipient and subscription expiry APIs; store only dispatch/idempotency records in notification_db. Remove unmanaged classes after contract cutover. |
| migration_impact | Five confirmed foreign table mappings; no cross-service SQL joins remain at acceptance. |
| estimated_complexity | Medium |
| when | During restructuring |

### ARC-003 — Report is a proxy while voice owns report/page persistence

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Service boundaries |
| service | report-service and voice-service |
| description | Report is a proxy while voice owns report/page persistence |
| why_it_is_a_problem | Gateway report routes bounce through report to voice. Legacy report models import absent workspace models but are not in active INSTALLED_APPS; do not count them as active table writers. Responsibility and package names mislead future work. |
| evidence | services/report-service/voice_reports/views.py:1; services/report-service/service_config/settings.py:33; services/voice-service/voice_reports/models.py:8; services/report-service/voice_reports/models.py:4 |
| risk | Gateway report routes bounce through report to voice. Legacy report models import absent workspace models but are not in active INSTALLED_APPS; do not count them as active table writers. Responsibility and package names mislead future work. |
| solution | Move report/page/widget persistence and CRUD to report-service; voice owns only orchestration/jobs and calls report internal APIs. Remove inactive persistence modules after imports and tests are reconciled. |
| migration_impact | Preserve IDs, paths and response contracts; temporarily route legacy URLs to owner APIs. |
| estimated_complexity | Large |
| when | During restructuring |

### ARC-004 — ClickHouse storage is a shared implementation across multiple domains

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Database ownership |
| service | AI, ETL, query and Metabase |
| description | ClickHouse storage is a shared implementation across multiple domains |
| why_it_is_a_problem | AI reads schemas/values, ETL stages write bronze/checkpoints/schema state, query executes and drops tables, and Metabase executes SQL. Root Compose hands out one ClickHouse credential. The same DB does not have one enforced owner. |
| evidence | services/ai-service/llm_app/schema_provider.py; services/query-service/query_api/services/clickhouse_executor.py; etl-final/shared/utils/bronze_writer.py; etl-final/loader-service/loader/engine/kafka_listener.py; etl-final/metadata-service/metadata/api/views.py:63 |
| risk | AI reads schemas/values, ETL stages write bronze/checkpoints/schema state, query executes and drops tables, and Metabase executes SQL. Root Compose hands out one ClickHouse credential. The same DB does not have one enforced owner. |
| solution | Make query-service own serving datasets and restricted execution APIs; ingestion owns isolated staging storage and publishes batches by HTTP. AI/metadata receive schema/results through APIs. Metabase reads only an explicitly justified read-only BI projection. |
| migration_impact | Introduce database and role boundaries for staging, serving and BI projection; reconcile row counts and ownership before disabling legacy reads. |
| estimated_complexity | Large |
| when | During restructuring |

### ARC-005 — Kafka and a shared upload volume carry business workflows

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | HTTP-only communication |
| service | ETL |
| description | Kafka and a shared upload volume carry business workflows |
| why_it_is_a_problem | Connector/extractor/transformer/loader/detector/metadata communicate via connection/schema/row/metadata topics; connector and extractor exchange filesystem paths. These violate the requested HTTP-only inter-service rule. |
| evidence | etl-final/connector-service/connector/etl_engine/views.py:114; etl-final/*/start.sh; etl-final/shared/utils/kafka_consumer.py; docker-compose.yml:491 |
| risk | Connector/extractor/transformer/loader/detector/metadata communicate via connection/schema/row/metadata topics; connector and extractor exchange filesystem paths. These violate the requested HTTP-only inter-service rule. |
| solution | Consolidate ingestion stages into modules/workers of the etl-connector bounded service, then remove cross-service topics and shared paths. Use authenticated HTTP batch/job APIs for query and metadata. If stages remain independent, every edge must become a versioned HTTP contract. |
| migration_impact | Drain offsets, checkpoint outstanding jobs and verify replay/idempotency before removing broker dependencies. |
| estimated_complexity | Large |
| when | During restructuring |

### ARC-006 — Shared modules contain business rules and persistence repositories

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Shared libraries |
| service | ETL and bi_platform_shared |
| description | Shared modules contain business rules and persistence repositories |
| why_it_is_a_problem | Bronze writers, lineage repositories, schema storage and transformation rules bind independently deployed services to common domain behavior. DTOs alone are not ORM violations; generic logging/HTTP utilities are appropriate to share. |
| evidence | etl-final/shared/models/rules_engine.py; etl-final/shared/utils/bronze_writer.py; etl-final/shared/utils/schema_contract_store.py; etl-final/shared/utils/lineage_tracker.py; bi_platform_shared/predictive/detector.py; bi_platform_shared/permissions/roles.py |
| risk | Bronze writers, lineage repositories, schema storage and transformation rules bind independently deployed services to common domain behavior. DTOs alone are not ORM violations; generic logging/HTTP utilities are appropriate to share. |
| solution | Move repositories/rules into the owner service; share only transport schemas, generic security primitives and observability. Publish versioned packages without sys.path mutation. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Large |
| when | During restructuring |

### ARC-007 — Remote side effects occur inside a local database transaction

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Transactions |
| service | auth-service and workspace-service |
| description | Remote side effects occur inside a local database transaction |
| why_it_is_a_problem | Registration/invitation performs HTTP workspace creation or attachment before auth transaction commits. Remote success plus local rollback can orphan memberships/workspaces, even while databases share a server. |
| evidence | services/auth-service/users/serializers.py:178; services/auth-service/users/serializers.py:238; services/auth-service/users/serializers.py:272 |
| risk | Registration/invitation performs HTTP workspace creation or attachment before auth transaction commits. Remote success plus local rollback can orphan memberships/workspaces, even while databases share a server. |
| solution | Persist workflow state and idempotency key before remote operations; coordinate explicit confirm/compensate steps over HTTP. Test timeout-after-commit and retry; do not introduce Kafka just for workflow coordination. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Large |
| when | During restructuring |

### OPS-001 — SurrealDB starts in memory mode despite mounting /data

| Field | Finding |
| --- | --- |
| severity | CRITICAL |
| category | Data durability |
| service | surrealdb |
| description | SurrealDB starts in memory mode despite mounting /data |
| why_it_is_a_problem | No persisted storage engine is selected. The daemon was already stopped when inspected; former in-memory metadata cannot be recovered from the /data mount merely by restarting. Data loss is possible and historical completeness cannot be verified. |
| evidence | docker-compose.yml:435; etl-final/docker-compose.yml:48; docs/audit/runtime_inventory.json |
| risk | No persisted storage engine is selected. The daemon was already stopped when inspected; former in-memory metadata cannot be recovered from the /data mount merely by restarting. Data loss is possible and historical completeness cannot be verified. |
| solution | Preserve available archives; pin a compatible version and configure a persistent engine path in the mounted volume; test write/restart/read and native export/restore. Document already-lost metadata explicitly. |
| migration_impact | Storage-mode change needs a version-compatible export/import when a live instance exists; never claim an empty volume is a valid historical backup. |
| estimated_complexity | Medium |
| when | Before development |

### OPS-002 — Metabase H2 metadata exists only in its unmounted container layer

| Field | Finding |
| --- | --- |
| severity | CRITICAL |
| category | Data durability |
| service | Metabase |
| description | Metabase H2 metadata exists only in its unmounted container layer |
| why_it_is_a_problem | No MB_DB_* variables or mounts were present; /metabase.db was successfully copied while stopped. Container replacement/removal could lose cards, dashboards, settings and source connections. |
| evidence | docs/audit/runtime_inventory.json containers.metabase; docs/audit/backup_manifest.json |
| risk | No MB_DB_* variables or mounts were present; /metabase.db was successfully copied while stopped. Container replacement/removal could lose cards, dashboards, settings and source connections. |
| solution | Preserve and restore-test the H2 copy with the exact image, then migrate via the supported Metabase migration workflow to its own PostgreSQL DB/user. Never mix this with business-data reset. |
| migration_impact | Use exact application version for migration; preserve the stopped original and H2 archive for rollback. |
| estimated_complexity | Medium |
| when | Before development |

### OPS-003 — Existing reset script has no environment gate, backups or complete inventory

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Data reset |
| service | scripts |
| description | Existing reset script has no environment gate, backups or complete inventory |
| why_it_is_a_problem | It sources .env as executable shell code and truncates configured PostgreSQL/ClickHouse targets without production exclusion, dry-run or backup checks. Redis/Kafka/Metabase/media are outside its success claim. |
| evidence | scripts/reset_all_databases.sh:23; scripts/clear_postgres.sql; scripts/clear_clickhouse.sql |
| risk | It sources .env as executable shell code and truncates configured PostgreSQL/ClickHouse targets without production exclusion, dry-run or backup checks. Redis/Kafka/Metabase/media are outside its success claim. |
| solution | Retire its use; require the Phase 0 manifest, local identity checks, verified backups, explicit allowlists and after-state checks. Implement an audited dev reset with refusal on drift. |
| migration_impact | Do not modify this already-edited user script silently; introduce a separate guarded entrypoint. |
| estimated_complexity | Medium |
| when | Before development |

### OPS-004 — Images use development servers, root defaults and incomplete production controls

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Docker |
| service | all applications |
| description | Images use development servers, root defaults and incomplete production controls |
| why_it_is_a_problem | Django runserver is the entrypoint, no application Dockerfile sets USER, and service health checks only test a TCP listener. No root .dockerignore existed at baseline; audit added seven context ignore files before the successful 17-image build. Other production controls remain unresolved. |
| evidence | services/*/Dockerfile; etl-final/*/Dockerfile; docker-compose.yml |
| risk | Django runserver is the entrypoint, no application Dockerfile sets USER, and service health checks only test a TCP listener. No root .dockerignore existed at baseline; audit added seven context ignore files before the successful 17-image build. Other production controls remain unresolved. |
| solution | Use pinned multi-stage images, non-root UID, production WSGI/ASGI server, .dockerignore, resource limits, restart strategy, graceful shutdown and separate migration jobs. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Large |
| when | Before production |

### OPS-005 — Port-open health checks do not prove usable service dependencies

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Health and readiness |
| service | platform |
| description | Port-open health checks do not prove usable service dependencies |
| why_it_is_a_problem | All 16 core/ETL application services use TCP checks; notification worker has no healthcheck. ETL web and listener processes can diverge. Query health can return HTTP 200 with success=false. No clean-state startup is implied by Compose validation. |
| evidence | docker-compose.yml:131; services/query-service/query_api/views.py:63; etl-final/loader-service/start.sh:4 |
| risk | All 16 core/ETL application services use TCP checks; notification worker has no healthcheck. ETL web and listener processes can diverge. Query health can return HTTP 200 with success=false. No clean-state startup is implied by Compose validation. |
| solution | Define /health/live and /health/ready with 503 on dependency failure, worker heartbeat and migration state. Keep optional AI/BI outages from preventing auth/gateway startup. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | Before development |

### OPS-006 — Uploads, SQLite and broker data have inconsistent lifecycle ownership

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Data durability |
| service | voice-service and ETL |
| description | Uploads, SQLite and broker data have inconsistent lifecycle ownership |
| why_it_is_a_problem | Current voice has no /app/media volume while a legacy voice worker has one. ETL/AI SQLite defaults live in container layers. Kafka/ZooKeeper data is held in anonymous volumes, and 555 volumes include many unassigned historical resources. |
| evidence | docker-compose.yml:153; docs/audit/runtime_inventory.json mounts; etl-final/*/*/*/settings.py DATABASES |
| risk | Current voice has no /app/media volume while a legacy voice worker has one. ETL/AI SQLite defaults live in container layers. Kafka/ZooKeeper data is held in anonymous volumes, and 555 volumes include many unassigned historical resources. |
| solution | Persist owned media/staging paths, explicitly name broker state if retained, inventory SQLite before replacing containers, and quarantine unknown volumes instead of pruning. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | Before development |

### OPS-007 — Tracing and metrics exist in ETL but lack a complete deployed collection path

| Field | Finding |
| --- | --- |
| severity | MEDIUM |
| category | Observability |
| service | platform |
| description | Tracing and metrics exist in ETL but lack a complete deployed collection path |
| why_it_is_a_problem | ETL metrics/tracing helpers are present, but no Prometheus/Grafana/OTLP collector or alert rules were discovered. Gateway does not establish/propagate one consistent request ID and forwards caller-supplied internal headers. |
| evidence | etl-final/shared/utils/tracing.py; etl-final/shared/utils/django_middleware.py; services/api-gateway/gateway/views.py:43; docker-compose.yml |
| risk | ETL metrics/tracing helpers are present, but no Prometheus/Grafana/OTLP collector or alert rules were discovered. Gateway does not establish/propagate one consistent request ID and forwards caller-supplied internal headers. |
| solution | Generate a request ID at ingress, sanitize trust headers, propagate trace context, redact payloads, scrape metrics and define SLO/error-budget alerts with dashboards. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | Before production |

### OPS-008 — Core Django is unsupported and dependency builds are not reproducible

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Dependencies |
| service | platform |
| description | Core Django is unsupported and dependency builds are not reproducible |
| why_it_is_a_problem | Core pins Django 4.2.7; Django 4.2 support ended April 2026. AI/ETL requirements and several image tags float; no Python lock/hash set defines a reproducible production build. No exhaustive CVE scan was completed. |
| evidence | services/auth-service/requirements.txt:1; services/ai-service/requirements.txt; etl-final/*/requirements.txt; docker-compose.yml:448 |
| risk | Core pins Django 4.2.7; Django 4.2 support ended April 2026. AI/ETL requirements and several image tags float; no Python lock/hash set defines a reproducible production build. No exhaustive CVE scan was completed. |
| solution | Plan a tested supported-Django upgrade; lock transitive Python packages and image digests, produce SBOMs and run advisory scans in CI. Do not upgrade every dependency during Phase 0. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Large |
| when | Before production |

### OPS-009 — No first-party CI workflow or complete green baseline was found

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | CI/CD |
| service | repository |
| description | No first-party CI workflow or complete green baseline was found |
| why_it_is_a_problem | AI/ETL tests fail, full ETL collection has import/encoding errors, and frontend lint lacks config. Source-path mutation shadows kafka-python with shared/kafka. Existing tests are not a deploy gate. |
| evidence | docs/audit/TEST_EXECUTION.md; frontend/package.json; services/ai-service/tests; etl-final/shared/utils/create_bronze_tables.py:26 |
| risk | AI/ETL tests fail, full ETL collection has import/encoding errors, and frontend lint lacks config. Source-path mutation shadows kafka-python with shared/kafka. Existing tests are not a deploy gate. |
| solution | Repair test packaging and fixtures without weakening assertions; add lint/unit/contract/security/Compose/build/migration gates, secret scan and artifact provenance. Preserve failing baseline evidence. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Large |
| when | Before development |

### OPS-010 — Retention and deletion rules are not encoded in warehouse schemas

| Field | Finding |
| --- | --- |
| severity | MEDIUM |
| category | Retention and performance |
| service | ClickHouse |
| description | Retention and deletion rules are not encoded in warehouse schemas |
| why_it_is_a_problem | Monthly partitioning exists for several operational tables, but no TTL appears in their DDL. Generic tables can use ORDER BY tuple(). ReplacingMergeTree deduplication is eventual and is not an immediate uniqueness guarantee. |
| evidence | etl-final/shared/utils/clickhouse_schemas.py:58; etl-final/loader-service/loader/engine/kafka_listener.py:254 |
| risk | Monthly partitioning exists for several operational tables, but no TTL appears in their DDL. Generic tables can use ORDER BY tuple(). ReplacingMergeTree deduplication is eventual and is not an immediate uniqueness guarantee. |
| solution | Specify owner-approved retention per class, e.g. staging 7 days and operational trace/quality 30-90 days subject to product needs. Add tenant/time access keys, bounded queries and idempotent batch keys; test merges and replay. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | Before production |

### OPS-011 — Multiple client implementations produce inconsistent retries, errors and traces

| Field | Finding |
| --- | --- |
| severity | MEDIUM |
| category | HTTP resilience |
| service | platform |
| description | Multiple client implementations produce inconsistent retries, errors and traces |
| why_it_is_a_problem | A useful shared client has timeouts/backoff/circuit breaking, but many callers use requests directly. Gateway buffers bodies and waits up to 360 seconds; report proxy uses a different correlation header and can return success status with invalid upstream JSON. |
| evidence | bi_platform_shared/http/client.py; services/api-gateway/gateway/views.py:13; services/report-service/voice_reports/views.py:67; services/*/*/notification_client.py |
| risk | A useful shared client has timeouts/backoff/circuit breaking, but many callers use requests directly. Gateway buffers bodies and waits up to 360 seconds; report proxy uses a different correlation header and can return success status with invalid upstream JSON. |
| solution | Adopt a common transport with connect/read/total deadlines, bounded idempotent retries, no blind POST retry, structured 4xx/5xx errors and stable request IDs. Use async jobs for long AI work. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | During restructuring |

### OPS-012 — Rate limits are local to a process and retain unbounded path keys

| Field | Finding |
| --- | --- |
| severity | MEDIUM |
| category | Rate limiting |
| service | api-gateway |
| description | Rate limits are local to a process and retain unbounded path keys |
| why_it_is_a_problem | The dictionary key contains the raw path and is never removed; replicas enforce separate quotas and guessed IDs create new buckets. A reverse proxy can collapse everyone to one REMOTE_ADDR. |
| evidence | services/api-gateway/gateway/middleware.py:20 |
| risk | The dictionary key contains the raw path and is never removed; replicas enforce separate quotas and guessed IDs create new buckets. A reverse proxy can collapse everyone to one REMOTE_ADDR. |
| solution | Use trusted proxy handling and gateway-owned shared rate-limit state; normalized route/user/IP keys with TTL. Set separate login/reset/invite/upload/query/AI budgets and concurrency controls. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | Before production |

### OPS-013 — Long synchronous work and false timeout cancellation can exhaust workers

| Field | Finding |
| --- | --- |
| severity | MEDIUM |
| category | Performance |
| service | AI and voice |
| description | Long synchronous work and false timeout cancellation can exhaust workers |
| why_it_is_a_problem | ThreadPoolExecutor context shutdown waits for inference even after future.result times out. Voice has a 3727-line endpoint module; page GET seeds data, unbounded report/page responses and long serial AI/query/Metabase chains increase latency and retry ambiguity. |
| evidence | services/ai-service/whisper_app/transcription_task.py:465; services/voice-service/voice_reports/views.py; services/voice-service/voice_reports/dashboard_builder_views.py:88 |
| risk | ThreadPoolExecutor context shutdown waits for inference even after future.result times out. Voice has a 3727-line endpoint module; page GET seeds data, unbounded report/page responses and long serial AI/query/Metabase chains increase latency and retry ambiguity. |
| solution | Use owner-local durable jobs with cancellation/process isolation and status polling; paginate reports/pages; make GET read-only; measure SQL/AI/embedding time separately. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Large |
| when | During restructuring |

### OPS-014 — Database internals and generated artifacts are tracked or insufficiently ignored

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Git hygiene |
| service | repository |
| description | Database internals and generated artifacts are tracked or insufficiently ignored |
| why_it_is_a_problem | ClickHouse data/preprocessed configuration and bytecode are tracked. .env.production/.env.test, backup dumps and many data artifacts are not generally covered by the current ignore rules. Historical records/secrets can persist after local cleanup. |
| evidence | .gitignore; git ls-files etl-final/etl-infra/clickhouse/data; Git history .env.microservices |
| risk | ClickHouse data/preprocessed configuration and bytecode are tracked. .env.production/.env.test, backup dumps and many data artifacts are not generally covered by the current ignore rules. Historical records/secrets can persist after local cleanup. |
| solution | Add secret-safe ignore rules with example exceptions, remove tracked generated files in a dedicated reviewed commit, scan history and arrange restricted backup retention. Do not discard user modifications or rewrite history during audit. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | Before development |

### OPS-015 — Documented service count and Redis inventory are stale

| Field | Finding |
| --- | --- |
| severity | LOW |
| category | Documentation |
| service | README |
| description | Documented service count and Redis inventory are stale |
| why_it_is_a_problem | README lists eight core services and describes no Redis in ETL, while unified Compose has ten core services, an expiry worker and Redis. Report-service is described as metadata consumer though active endpoints proxy voice. |
| evidence | README.md:5; README.md:43; docker-compose.yml:232 |
| risk | README lists eight core services and describes no Redis in ETL, while unified Compose has ten core services, an expiry worker and Redis. Report-service is described as metadata consumer though active endpoints proxy voice. |
| solution | Use generated inventory and distinguish unified/legacy manifests, external Metabase/PostgreSQL and declared versus active code paths. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Small |
| when | During restructuring |

### SEC-014 — Invitation signup can replace the password of an existing account

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Account lifecycle |
| service | auth-service |
| description | Invitation signup can replace the password of an existing account |
| why_it_is_a_problem | An invitation path finds an existing user by invited email and sets its password/name/role without proving the caller knows the old password. An invitation bearer is a membership grant, not an account recovery credential. End-to-end exploitability depends on token issuance/access. |
| evidence | services/auth-service/users/serializers.py:197; services/auth-service/users/serializers.py:208 |
| risk | An invitation path finds an existing user by invited email and sets its password/name/role without proving the caller knows the old password. An invitation bearer is a membership grant, not an account recovery credential. End-to-end exploitability depends on token issuance/access. |
| solution | Require the existing user to authenticate and accept the invitation, or use the dedicated verified recovery flow. Do not mutate an existing account password/role as part of signup. |
| migration_impact | Deploy behind a flag; retain the previous image and configuration for rollback. |
| estimated_complexity | Medium |
| when | Before development |

### SEC-015 — Dataset status API lets any authenticated user replace another dataset binding

| Field | Finding |
| --- | --- |
| severity | CRITICAL |
| category | Tenant isolation and SQL security |
| service | query-service |
| description | Dataset status API lets any authenticated user replace another dataset binding |
| why_it_is_a_problem | DatabaseStatusView selects by database_id only and trusts caller-supplied clickhouse_database/table/schema/status. There is no owner or scoped ETL caller check. An attacker can corrupt another tenant binding or poison the supposedly authoritative own binding, then reach raw identifier interpolation in preview/delete paths. |
| evidence | services/query-service/database/views.py:753; services/query-service/database/urls.py; services/query-service/database/utils.py:37 |
| risk | DatabaseStatusView selects by database_id only and trusts caller-supplied clickhouse_database/table/schema/status. There is no owner or scoped ETL caller check. An attacker can corrupt another tenant binding or poison the supposedly authoritative own binding, then reach raw identifier interpolation in preview/delete paths. |
| solution | Restrict status updates to the authorized ingestion job identity and immutable tenant/dataset binding; reject unknown fields and state transitions. Validate physical identifiers with owner-controlled mappings and quote them at every raw SQL boundary. Add two-tenant status mutation and poisoned-binding tests. |
| migration_impact | Version callback schema and update ingestion caller; audit existing bindings before accepting them as authoritative. |
| estimated_complexity | Medium |
| when | Before development |

### OPS-016 — Model state differs from checked-in migrations

| Field | Finding |
| --- | --- |
| severity | HIGH |
| category | Migrations |
| service | voice-service and notification-service |
| description | Model state differs from checked-in migrations |
| why_it_is_a_problem | All existing application migrations exited zero. Dry-run drift details propose two voice index renames plus chart_type alteration, and migration state for five unmanaged notification models (not five missing physical tables). AI/ETL SQLite migrations were also applied to their actual service containers. New-empty-PostgreSQL installation and checked-in model/migration parity remain unverified or failing. |
| evidence | docs/audit/migration_verification.json; services/voice-service/voice_reports/models.py; services/notification-service/notification/models.py |
| risk | All existing application migrations exited zero. Dry-run drift details propose two voice index renames plus chart_type alteration, and migration state for five unmanaged notification models (not five missing physical tables). AI/ETL SQLite migrations were also applied to their actual service containers. New-empty-PostgreSQL installation and checked-in model/migration parity remain unverified or failing. |
| solution | Inspect makemigrations --check --dry-run output, classify state-only versus real DDL changes, commit reviewed migrations, and validate a new empty database plus an upgrade clone for each owner. Run SQLite migrations in persistent service containers while legacy SQLite is retained. |
| migration_impact | Do not generate or apply unreviewed model changes during the audit; preserve migration graph and test upgrade/rollback. |
| estimated_complexity | Medium |
| when | Before development |


## Final runtime disposition

The targeted active-data cleanup passed after startup; all 37 original backup hashes still match. All 24 root Compose services are running (23 configured healthy; expiry worker has no probe), 14 HTTP probes and bootstrap-admin authorization pass, and existing migrations executed for all 16 application configurations. Voice/notification model-state checks fail; 46 selected tests fail and frontend lint is unconfigured. Metabase metadata was recovered into a separate running copy; the original remains stopped. Overall Phase 0 acceptance is PARTIAL, production NOT READY. See [startup verification](STARTUP_VERIFICATION.md), [data/reset report](DATA_STORAGE_AND_WIPE_REPORT.md), [action plan](PRE_DEVELOPMENT_ACTION_PLAN.md), and [modification ledger](MODIFICATION_LEDGER.md).
