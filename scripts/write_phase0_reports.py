"""Generate the reviewable Phase 0 report set from captured evidence."""
from pathlib import Path
import collections
import json

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs'/'audit'
INV=json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))
RUN=json.loads((OUT/'runtime_inventory.json').read_text(encoding='utf-8'))

ISSUES=[]
def issue(id,severity,category,service,title,evidence,why,solution,phase='P2',complexity='Medium',impact='Deploy behind a flag; retain the previous image and configuration for rollback.'):
    ISSUES.append(dict(id=id,severity=severity,category=category,service=service,title=title,description=title,evidence=evidence,affected_files=evidence.split('; '),why_it_is_a_problem=why,risk=why,solution=solution,migration_impact=impact,estimated_complexity=complexity,phase=phase,when={'P0':'Before development','P1':'During restructuring','P2':'Before production','P3':'After MVP'}[phase]))

issue('SEC-001','CRITICAL','Tenant isolation','voice-service','Workspace denial retains the untrusted requested workspace',
 'services/voice-service/voice_reports/infrastructure/workspace_client.py:125; services/voice-service/voice_reports/infrastructure/auth_context.py:35; services/voice-service/voice_reports/dashboard_builder_views.py:41; services/voice-service/voice_reports/views.py:313',
 'A mocked workspace HTTP 403 still returned workspace 999999. Report and page queries then scope to that ID. A manager from one tenant can potentially read or change another tenant. This is a reproduced helper-level failure, not a live attack on user data.',
 'Require a successful membership decision; reject 403/404 and fail closed on timeout. Never retain an unvalidated hint. Add two-tenant tests for page/report read, edit, delete and query history.', 'P0','Medium','Changes denied/error requests to 403/503. No schema change; legitimate membership paths need regression tests.')
issue('SEC-002','CRITICAL','Tenant isolation','visualization-service','Metabase embedding and dashboard mutation lack object ownership checks',
 'services/visualization-service/visualization_api/views.py:237; services/visualization-service/visualization_api/views.py:267; services/visualization-service/visualization_api/views.py:281; services/api-gateway/gateway/routing.py:90',
 'Any authenticated principal can supply question/dashboard IDs; the service signs embed URLs or attaches cards using shared Metabase privileges. No tenant-object mapping is checked in these handlers.',
 'Store tenant ownership for every card/dashboard in visualization_db; authorize both objects before mutation or signing; use short-lived scoped embeds. Restrict creation to service callers or authorized tenant roles.', 'P0','Large','Backfill ownership from report records before enforcing. Quarantine unmappable cards; preserve Metabase metadata.')
issue('SEC-003','CRITICAL','SQL security','visualization-service','Raw visualization SQL bypasses the query service security boundary',
 'services/visualization-service/visualization_api/views.py:36; services/visualization-service/visualization_api/views.py:132; bi_platform_shared/sql/normalization.py:42',
 'CreateQuestion accepts user SQL, applies formatting normalization, creates a native Metabase query and validates execution. Formatting is not AST validation or tenant authorization. Actual accessible data depends on Metabase source grants.',
 'Accept an authorized query-result/query-definition ID from query-service, never arbitrary SQL. Execute only an AST-approved tenant-bound definition with a read-only source identity.', 'P0','Medium','Changes visualization request contract; migrate voice caller with a compatibility flag and contract tests.')
issue('SEC-004','CRITICAL','Secrets','platform','Historical credentials remain equal to current local credentials',
 'Git HEAD:.env.microservices (historical blob); .env (values withheld); docs/audit/runtime_inventory.json',
 'Local ADMIN_PASSWORD, METABASE_SECRET_KEY, NOTIFICATION_SERVICE_API_KEY, AI_SERVICE_INTERNAL_API_KEY and OPENROUTER_API_KEY match nonempty values in the tracked historical file. Exposure risk remains after removing the working file. No external key validity was tested.',
 'SECRET ROTATION REQUIRED: revoke/replace OpenRouter key, admin password, service keys and embedding key; invalidate sessions/embeds; rotate all historically stored DB/Metabase/JWT credentials if not already done. Coordinate history remediation separately; never rewrite user history automatically.', 'P0','Medium','Rotating signing/service keys invalidates sessions and requires coordinated deployment. External provider administration remains outside this audit.')
issue('SEC-005','CRITICAL','API security','ETL','ETL upload, connection and metadata APIs lack authenticated tenant scope',
 'etl-final/connector-service/connector/etl_engine/views.py:78; etl-final/connector-service/connector/connector/settings.py:38; etl-final/metadata-service/metadata/api/views.py:19; docker-compose.yml:483',
 'APIView defaults are public without explicit permissions. The connector writes files and triggers jobs; metadata returns global logs. Host-published ports let clients bypass the gateway. File events use filename/source_id without tenant identity.',
 'Require scoped service authentication and a verified tenant/dataset/job context at ingress and every stage. Remove public ETL ports. Namespace source IDs and authorize lineage/quality access.', 'P0','Large','Version event/API payloads and backfill or quarantine unowned data; retain old pipeline only on an isolated migration network.')
issue('SEC-006','HIGH','SSRF','etl-connector','User-provided database hosts allow internal-network connections',
 'etl-final/shared/utils/input_validator.py:237; etl-final/connector-service/connector/etl_engine/views.py:170; etl-final/connector-service/connector/etl_engine/utils.py:7',
 'Validation accepts localhost and syntactically valid hostnames. ConnectDB connects directly with supplied host/port; no resolved-IP allowlist or egress boundary was found.',
 'Use a connector network with explicit destination authorization; block loopback/link-local/metadata/private ranges by default, with administrator-approved private connectivity. Validate every resolved address and connection timeout.', 'P0')
issue('SEC-007','HIGH','Secrets','ETL','Credential encryption silently falls back to a source-known key',
 'etl-final/shared/utils/credential_encryption.py:29; docker-compose.yml:492',
 'Missing CREDENTIAL_SECRET_KEY selects a fixed default and fixed salt; root ETL environment blocks do not provide the key. Encrypted source credentials in Kafka can therefore be recoverable with the source default.',
 'Fail fast on missing key; use a secret reference and key version per connection. Re-encrypt existing connections with a new key and revoke affected source credentials.', 'P0','Medium','Keep old decrypt-only key solely for controlled migration; do not lose access to existing encrypted records.')
issue('SEC-008','HIGH','Configuration','ETL and Django services','Development settings and insecure fallback signing keys remain',
 'etl-final/connector-service/connector/connector/settings.py:28; etl-final/metadata-service/metadata/metadata/settings.py:28; services/auth-service/service_config/settings.py:12; services/ai-service/backend/settings.py:33',
 'ETL uses hardcoded Django secrets, DEBUG=True and wildcard hosts; core services still have fallback secrets even though root Compose validates several variables. Direct service startup can bypass launcher checks.',
 'Implement explicit environment profiles and service startup validation; reject missing/placeholder secrets with DEBUG off. Require exact hosts and configure TLS/cookie/HSTS settings for production.', 'P0')
issue('SEC-009','HIGH','Infrastructure','platform','Databases, broker, AI and internal APIs bind host ports on all interfaces',
 'docker-compose.yml:1; docs/audit/runtime_inventory.json',
 'Runtime PortBindings expose 8001-8010, 8101-8106, Redis 6379, ClickHouse 8123/9000, Kafka 9092, ZooKeeper 2181, SurrealDB 8008 and Kafka UI 8081. Firewall reachability was not tested. Redis has no requirepass in its command and Kafka uses PLAINTEXT.',
 'Keep only the TLS edge public; bind diagnostic dev ports to 127.0.0.1 in a development override. Segment service/database networks; introduce Redis ACLs and broker authentication if retained.', 'P0')
issue('SEC-010','HIGH','Secrets','all core services','A shared env_file distributes unrelated credentials to every core container',
 'docker-compose.yml:118; docs/audit/runtime_inventory.json (env_names)',
 'Auth, notification, AI/provider, database and embedding secrets are broadly distributed. A compromised low-trust proxy can expose credentials unrelated to its responsibility.',
 'Create service-specific variable allowlists and secret mounts. Separate JWT verification public keys from auth signing keys and limit Metabase credentials to visualization.', 'P1')
issue('SEC-011','HIGH','Authentication','core services','HS256 verification keys also permit signing, with stale stateless user claims',
 'services/auth-service/service_config/settings.py:121; services/workspace-service/workspace/authentication.py:39; services/query-service/service_config/settings.py:111',
 'Services share signing material and trust JWT role/active/workspace claims. Revoked membership or deactivated users can retain access until expiry unless the route performs a fresh ownership check. Auth uses a one-hour access lifetime and disables refresh rotation.',
 'Auth owns asymmetric signing/JWKS, issuer/audience validation, short access expiry and refresh rotation/reuse detection. Check live membership for sensitive actions through workspace APIs. Test deactivation and revoked invitations.', 'P1','Large')
issue('SEC-012','MEDIUM','Frontend security','frontend','Browser tokens are stored in localStorage and refresh has no single-flight handling',
 'frontend/src/api/axios.js:18; frontend/src/api/axios.js:40; frontend/src/store/auth.js:25; services/auth-service/service_config/settings.py:124',
 'XSS would expose both tokens; simultaneous 401s race refresh. Current auth rotation is disabled, so ignoring returned refresh is a future rotation integration defect, not a currently proven logout bug. Axios also has no global timeout.',
 'Prefer an HttpOnly Secure SameSite refresh cookie with CSRF protection, access token in memory, CSP and one refresh promise. Persist rotated refresh if bearer refresh is retained; bound browser requests.', 'P2')
issue('SEC-013','HIGH','Logging','query-service','ClickHouse credentials are placed in URL query parameters',
 'services/query-service/database/utils.py:21',
 'Requests puts user/password into the URL; error logging includes exception strings that may carry the full URL. Proxy/access logs can expose credentials.',
 'Use auth headers over TLS, sanitize connection errors, redact URL credentials and query tokens from structured logs. Rotate affected ClickHouse credentials if logged.', 'P0','Small')
issue('ARC-001','HIGH','Database ownership','core services','Nine core Django processes share one logical PostgreSQL database and account',
 'services/*/service_config/settings.py DATABASES; docs/audit/runtime_inventory.json postgres; docker-compose.yml env_file',
 'Runtime bi_voice_agent has 27 tables owned by bi_admin, which also has CREATEDB. Independent services can alter each other\'s data and share Django migration/admin state. A configured DB connection in a stateless proxy is not evidence of domain reads, but still grants access.',
 'Create logical DBs and least-privileged roles for auth, workspace, report, voice jobs, query, subscription and notification; remove DB dependency from gateway and stateless proxies. Separate migration roles.', 'P1','Large','Use owner APIs first, then snapshot/backfill with IDs preserved and reconciliation before credential cutover.')
issue('ARC-002','HIGH','Database ownership','notification-service','Notifications directly query five tables owned by other domains',
 'services/notification-service/notification/models.py:41; services/notification-service/notification/services.py:80',
 'Unmanaged ORM mappings cover users, workspaces, workspace_members, subscription_plans and workspace_subscriptions. Services and expiry worker rely on joins across domains.',
 'Use authenticated paginated workspace recipient and subscription expiry APIs; store only dispatch/idempotency records in notification_db. Remove unmanaged classes after contract cutover.', 'P1','Medium','Five confirmed foreign table mappings; no cross-service SQL joins remain at acceptance.')
issue('ARC-003','HIGH','Service boundaries','report-service and voice-service','Report is a proxy while voice owns report/page persistence',
 'services/report-service/voice_reports/views.py:1; services/report-service/service_config/settings.py:33; services/voice-service/voice_reports/models.py:8; services/report-service/voice_reports/models.py:4',
 'Gateway report routes bounce through report to voice. Legacy report models import absent workspace models but are not in active INSTALLED_APPS; do not count them as active table writers. Responsibility and package names mislead future work.',
 'Move report/page/widget persistence and CRUD to report-service; voice owns only orchestration/jobs and calls report internal APIs. Remove inactive persistence modules after imports and tests are reconciled.', 'P1','Large','Preserve IDs, paths and response contracts; temporarily route legacy URLs to owner APIs.')
issue('ARC-004','HIGH','Database ownership','AI, ETL, query and Metabase','ClickHouse storage is a shared implementation across multiple domains',
 'services/ai-service/llm_app/schema_provider.py; services/query-service/query_api/services/clickhouse_executor.py; etl-final/shared/utils/bronze_writer.py; etl-final/loader-service/loader/engine/kafka_listener.py; etl-final/metadata-service/metadata/api/views.py:63',
 'AI reads schemas/values, ETL stages write bronze/checkpoints/schema state, query executes and drops tables, and Metabase executes SQL. Root Compose hands out one ClickHouse credential. The same DB does not have one enforced owner.',
 'Make query-service own serving datasets and restricted execution APIs; ingestion owns isolated staging storage and publishes batches by HTTP. AI/metadata receive schema/results through APIs. Metabase reads only an explicitly justified read-only BI projection.', 'P1','Large','Introduce database and role boundaries for staging, serving and BI projection; reconcile row counts and ownership before disabling legacy reads.')
issue('ARC-005','HIGH','HTTP-only communication','ETL','Kafka and a shared upload volume carry business workflows',
 'etl-final/connector-service/connector/etl_engine/views.py:114; etl-final/*/start.sh; etl-final/shared/utils/kafka_consumer.py; docker-compose.yml:491',
 'Connector/extractor/transformer/loader/detector/metadata communicate via connection/schema/row/metadata topics; connector and extractor exchange filesystem paths. These violate the requested HTTP-only inter-service rule.',
 'Consolidate ingestion stages into modules/workers of the etl-connector bounded service, then remove cross-service topics and shared paths. Use authenticated HTTP batch/job APIs for query and metadata. If stages remain independent, every edge must become a versioned HTTP contract.', 'P1','Large','Drain offsets, checkpoint outstanding jobs and verify replay/idempotency before removing broker dependencies.')
issue('ARC-006','HIGH','Shared libraries','ETL and bi_platform_shared','Shared modules contain business rules and persistence repositories',
 'etl-final/shared/models/rules_engine.py; etl-final/shared/utils/bronze_writer.py; etl-final/shared/utils/schema_contract_store.py; etl-final/shared/utils/lineage_tracker.py; bi_platform_shared/predictive/detector.py; bi_platform_shared/permissions/roles.py',
 'Bronze writers, lineage repositories, schema storage and transformation rules bind independently deployed services to common domain behavior. DTOs alone are not ORM violations; generic logging/HTTP utilities are appropriate to share.',
 'Move repositories/rules into the owner service; share only transport schemas, generic security primitives and observability. Publish versioned packages without sys.path mutation.', 'P1','Large')
issue('ARC-007','HIGH','Transactions','auth-service and workspace-service','Remote side effects occur inside a local database transaction',
 'services/auth-service/users/serializers.py:178; services/auth-service/users/serializers.py:238; services/auth-service/users/serializers.py:272',
 'Registration/invitation performs HTTP workspace creation or attachment before auth transaction commits. Remote success plus local rollback can orphan memberships/workspaces, even while databases share a server.',
 'Persist workflow state and idempotency key before remote operations; coordinate explicit confirm/compensate steps over HTTP. Test timeout-after-commit and retry; do not introduce Kafka just for workflow coordination.', 'P1','Large')
issue('OPS-001','CRITICAL','Data durability','surrealdb','SurrealDB starts in memory mode despite mounting /data',
 'docker-compose.yml:435; etl-final/docker-compose.yml:48; docs/audit/runtime_inventory.json',
 'No persisted storage engine is selected. The daemon was already stopped when inspected; former in-memory metadata cannot be recovered from the /data mount merely by restarting. Data loss is possible and historical completeness cannot be verified.',
 'Preserve available archives; pin a compatible version and configure a persistent engine path in the mounted volume; test write/restart/read and native export/restore. Document already-lost metadata explicitly.', 'P0','Medium','Storage-mode change needs a version-compatible export/import when a live instance exists; never claim an empty volume is a valid historical backup.')
issue('OPS-002','CRITICAL','Data durability','Metabase','Metabase H2 metadata exists only in its unmounted container layer',
 'docs/audit/runtime_inventory.json containers.metabase; docs/audit/backup_manifest.json',
 'No MB_DB_* variables or mounts were present; /metabase.db was successfully copied while stopped. Container replacement/removal could lose cards, dashboards, settings and source connections.',
 'Preserve and restore-test the H2 copy with the exact image, then migrate via the supported Metabase migration workflow to its own PostgreSQL DB/user. Never mix this with business-data reset.', 'P0','Medium','Use exact application version for migration; preserve the stopped original and H2 archive for rollback.')
issue('OPS-003','HIGH','Data reset','scripts','Existing reset script has no environment gate, backups or complete inventory',
 'scripts/reset_all_databases.sh:23; scripts/clear_postgres.sql; scripts/clear_clickhouse.sql',
 'It sources .env as executable shell code and truncates configured PostgreSQL/ClickHouse targets without production exclusion, dry-run or backup checks. Redis/Kafka/Metabase/media are outside its success claim.',
 'Retire its use; require the Phase 0 manifest, local identity checks, verified backups, explicit allowlists and after-state checks. Implement an audited dev reset with refusal on drift.', 'P0','Medium','Do not modify this already-edited user script silently; introduce a separate guarded entrypoint.')
issue('OPS-004','HIGH','Docker','all applications','Images use development servers, root defaults and incomplete production controls',
 'services/*/Dockerfile; etl-final/*/Dockerfile; docker-compose.yml',
 'Django runserver is the entrypoint, no application Dockerfile sets USER, and service health checks only test a TCP listener. No root .dockerignore existed at baseline; audit added seven context ignore files before the successful 17-image build. Other production controls remain unresolved.',
 'Use pinned multi-stage images, non-root UID, production WSGI/ASGI server, .dockerignore, resource limits, restart strategy, graceful shutdown and separate migration jobs.', 'P2','Large')
issue('OPS-005','HIGH','Health and readiness','platform','Port-open health checks do not prove usable service dependencies',
 'docker-compose.yml:131; services/query-service/query_api/views.py:63; etl-final/loader-service/start.sh:4',
 'All 16 core/ETL application services use TCP checks; notification worker has no healthcheck. ETL web and listener processes can diverge. Query health can return HTTP 200 with success=false. No clean-state startup is implied by Compose validation.',
 'Define /health/live and /health/ready with 503 on dependency failure, worker heartbeat and migration state. Keep optional AI/BI outages from preventing auth/gateway startup.', 'P0','Medium')
issue('OPS-006','HIGH','Data durability','voice-service and ETL','Uploads, SQLite and broker data have inconsistent lifecycle ownership',
 'docker-compose.yml:153; docs/audit/runtime_inventory.json mounts; etl-final/*/*/*/settings.py DATABASES',
 'Current voice has no /app/media volume while a legacy voice worker has one. ETL/AI SQLite defaults live in container layers. Kafka/ZooKeeper data is held in anonymous volumes, and 555 volumes include many unassigned historical resources.',
 'Persist owned media/staging paths, explicitly name broker state if retained, inventory SQLite before replacing containers, and quarantine unknown volumes instead of pruning.', 'P0','Medium')
issue('OPS-007','MEDIUM','Observability','platform','Tracing and metrics exist in ETL but lack a complete deployed collection path',
 'etl-final/shared/utils/tracing.py; etl-final/shared/utils/django_middleware.py; services/api-gateway/gateway/views.py:43; docker-compose.yml',
 'ETL metrics/tracing helpers are present, but no Prometheus/Grafana/OTLP collector or alert rules were discovered. Gateway does not establish/propagate one consistent request ID and forwards caller-supplied internal headers.',
 'Generate a request ID at ingress, sanitize trust headers, propagate trace context, redact payloads, scrape metrics and define SLO/error-budget alerts with dashboards.', 'P2')
issue('OPS-008','HIGH','Dependencies','platform','Core Django is unsupported and dependency builds are not reproducible',
 'services/auth-service/requirements.txt:1; services/ai-service/requirements.txt; etl-final/*/requirements.txt; docker-compose.yml:448',
 'Core pins Django 4.2.7; Django 4.2 support ended April 2026. AI/ETL requirements and several image tags float; no Python lock/hash set defines a reproducible production build. No exhaustive CVE scan was completed.',
 'Plan a tested supported-Django upgrade; lock transitive Python packages and image digests, produce SBOMs and run advisory scans in CI. Do not upgrade every dependency during Phase 0.', 'P2','Large')
issue('OPS-009','HIGH','CI/CD','repository','No first-party CI workflow or complete green baseline was found',
 'docs/audit/TEST_EXECUTION.md; frontend/package.json; services/ai-service/tests; etl-final/shared/utils/create_bronze_tables.py:26',
 'AI/ETL tests fail, full ETL collection has import/encoding errors, and frontend lint lacks config. Source-path mutation shadows kafka-python with shared/kafka. Existing tests are not a deploy gate.',
 'Repair test packaging and fixtures without weakening assertions; add lint/unit/contract/security/Compose/build/migration gates, secret scan and artifact provenance. Preserve failing baseline evidence.', 'P0','Large')
issue('OPS-010','MEDIUM','Retention and performance','ClickHouse','Retention and deletion rules are not encoded in warehouse schemas',
 'etl-final/shared/utils/clickhouse_schemas.py:58; etl-final/loader-service/loader/engine/kafka_listener.py:254',
 'Monthly partitioning exists for several operational tables, but no TTL appears in their DDL. Generic tables can use ORDER BY tuple(). ReplacingMergeTree deduplication is eventual and is not an immediate uniqueness guarantee.',
 'Specify owner-approved retention per class, e.g. staging 7 days and operational trace/quality 30-90 days subject to product needs. Add tenant/time access keys, bounded queries and idempotent batch keys; test merges and replay.', 'P2')
issue('OPS-011','MEDIUM','HTTP resilience','platform','Multiple client implementations produce inconsistent retries, errors and traces',
 'bi_platform_shared/http/client.py; services/api-gateway/gateway/views.py:13; services/report-service/voice_reports/views.py:67; services/*/*/notification_client.py',
 'A useful shared client has timeouts/backoff/circuit breaking, but many callers use requests directly. Gateway buffers bodies and waits up to 360 seconds; report proxy uses a different correlation header and can return success status with invalid upstream JSON.',
 'Adopt a common transport with connect/read/total deadlines, bounded idempotent retries, no blind POST retry, structured 4xx/5xx errors and stable request IDs. Use async jobs for long AI work.', 'P1')
issue('OPS-012','MEDIUM','Rate limiting','api-gateway','Rate limits are local to a process and retain unbounded path keys',
 'services/api-gateway/gateway/middleware.py:20',
 'The dictionary key contains the raw path and is never removed; replicas enforce separate quotas and guessed IDs create new buckets. A reverse proxy can collapse everyone to one REMOTE_ADDR.',
 'Use trusted proxy handling and gateway-owned shared rate-limit state; normalized route/user/IP keys with TTL. Set separate login/reset/invite/upload/query/AI budgets and concurrency controls.', 'P2')
issue('OPS-013','MEDIUM','Performance','AI and voice','Long synchronous work and false timeout cancellation can exhaust workers',
 'services/ai-service/whisper_app/transcription_task.py:465; services/voice-service/voice_reports/views.py; services/voice-service/voice_reports/dashboard_builder_views.py:88',
 'ThreadPoolExecutor context shutdown waits for inference even after future.result times out. Voice has a 3727-line endpoint module; page GET seeds data, unbounded report/page responses and long serial AI/query/Metabase chains increase latency and retry ambiguity.',
 'Use owner-local durable jobs with cancellation/process isolation and status polling; paginate reports/pages; make GET read-only; measure SQL/AI/embedding time separately.', 'P1','Large')
issue('OPS-014','HIGH','Git hygiene','repository','Database internals and generated artifacts are tracked or insufficiently ignored',
 '.gitignore; git ls-files etl-final/etl-infra/clickhouse/data; Git history .env.microservices',
 'ClickHouse data/preprocessed configuration and bytecode are tracked. .env.production/.env.test, backup dumps and many data artifacts are not generally covered by the current ignore rules. Historical records/secrets can persist after local cleanup.',
 'Add secret-safe ignore rules with example exceptions, remove tracked generated files in a dedicated reviewed commit, scan history and arrange restricted backup retention. Do not discard user modifications or rewrite history during audit.', 'P0')
issue('OPS-015','LOW','Documentation','README','Documented service count and Redis inventory are stale',
 'README.md:5; README.md:43; docker-compose.yml:232',
 'README lists eight core services and describes no Redis in ETL, while unified Compose has ten core services, an expiry worker and Redis. Report-service is described as metadata consumer though active endpoints proxy voice.',
 'Use generated inventory and distinguish unified/legacy manifests, external Metabase/PostgreSQL and declared versus active code paths.', 'P1','Small')
issue('SEC-014','HIGH','Account lifecycle','auth-service','Invitation signup can replace the password of an existing account',
 'services/auth-service/users/serializers.py:197; services/auth-service/users/serializers.py:208',
 'An invitation path finds an existing user by invited email and sets its password/name/role without proving the caller knows the old password. An invitation bearer is a membership grant, not an account recovery credential. End-to-end exploitability depends on token issuance/access.',
 'Require the existing user to authenticate and accept the invitation, or use the dedicated verified recovery flow. Do not mutate an existing account password/role as part of signup.', 'P0','Medium')

issue('SEC-015','CRITICAL','Tenant isolation and SQL security','query-service','Dataset status API lets any authenticated user replace another dataset binding',
 'services/query-service/database/views.py:753; services/query-service/database/urls.py; services/query-service/database/utils.py:37',
 'DatabaseStatusView selects by database_id only and trusts caller-supplied clickhouse_database/table/schema/status. There is no owner or scoped ETL caller check. An attacker can corrupt another tenant binding or poison the supposedly authoritative own binding, then reach raw identifier interpolation in preview/delete paths.',
 'Restrict status updates to the authorized ingestion job identity and immutable tenant/dataset binding; reject unknown fields and state transitions. Validate physical identifiers with owner-controlled mappings and quote them at every raw SQL boundary. Add two-tenant status mutation and poisoned-binding tests.', 'P0','Medium','Version callback schema and update ingestion caller; audit existing bindings before accepting them as authoritative.')

issue('OPS-016','HIGH','Migrations','voice-service and notification-service','Model state differs from checked-in migrations',
 'docs/audit/migration_verification.json; services/voice-service/voice_reports/models.py; services/notification-service/notification/models.py',
 'All existing application migrations exited zero. Dry-run drift details propose two voice index renames plus chart_type alteration, and migration state for five unmanaged notification models (not five missing physical tables). AI/ETL SQLite migrations were also applied to their actual service containers. New-empty-PostgreSQL installation and checked-in model/migration parity remain unverified or failing.',
 'Inspect makemigrations --check --dry-run output, classify state-only versus real DDL changes, commit reviewed migrations, and validate a new empty database plus an upgrade clone for each owner. Run SQLite migrations in persistent service containers while legacy SQLite is retained.', 'P0','Medium','Do not generate or apply unreviewed model changes during the audit; preserve migration graph and test upgrade/rollback.')

def write(name,text):
    (OUT/name).write_text(text.strip()+'\n',encoding='utf-8')

def table(headers,rows):
    def clean(v):return str(v).replace('|','\\|').replace('\n','<br>')
    return '| '+' | '.join(headers)+' |\n| '+' | '.join('---' for _ in headers)+' |\n'+'\n'.join('| '+' | '.join(clean(v) for v in row)+' |' for row in rows)+'\n'

def issue_text(i):
    return f"### {i['id']} — {i['title']}\n\n"+table(['Field','Finding'],[(k,i[k]) for k in ['severity','category','service','description','why_it_is_a_problem','evidence','risk','solution','migration_impact','estimated_complexity','when']])+'\n'

RESP={
 'api-gateway':('Django/requests','route proxy and coarse throttling','shared PostgreSQL configured','all nine upstream APIs'),
 'auth-service':('Django/DRF/SimpleJWT','accounts, tokens, profile, system-admin principal','bi_voice_agent: users/reset/token state','workspace HTTP; notification HTTP; SMTP fallback'),
 'workspace-service':('Django/DRF','workspaces, memberships, invitations','bi_voice_agent: workspaces/members/invitations','auth HTTP; notification HTTP'),
 'report-service':('Django/DRF','report/dashboard proxy to voice; legacy inactive models','shared PostgreSQL configured; no active report ORM app','voice HTTP'),
 'voice-service':('Django/DRF','voice/text orchestration, reports, pages, jobs','bi_voice_agent: reports/pages/jobs; container media','workspace, AI, query, visualization, subscription, notification; Kafka; Metabase fallback'),
 'ai-service':('Django/Dagster/Whisper/TimesFM','transcription, intent, semantic SQL, forecast','SQLite configured; Redis; ClickHouse reads','Ollama/OpenRouter; model cache; Redis'),
 'query-service':('Django/DRF/sqlglot','dataset metadata, upload forwarding, SQL validation/execution','bi_voice_agent: manager_databases; ClickHouse','ETL connector HTTP; ClickHouse; subscription'),
 'visualization-service':('Django/DRF','chart choice, Metabase cards/dashboards/embeds','shared PostgreSQL configured; external Metabase metadata','Metabase HTTP; Ollama'),
 'subscription-service':('Django/DRF','plans, entitlements, free usage, payment records','bi_voice_agent: subscription tables','workspace/auth HTTP; notification HTTP'),
 'notification-service':('Django/DRF/SMTP','notification dispatch and expiry warning processing','bi_voice_agent: dispatch log plus foreign table reads','SMTP; cross-domain PostgreSQL reads'),
 'notification-expiry-worker':('Django management-command loop','scheduled expiry warnings','same notification persistence boundary','SMTP; same-domain notification code'),
 'etl-connector':('Django/DRF','uploads, DB connection tests, source triggers','SQLite; SurrealDB; shared uploaded-files; schema store','ClamAV native; Kafka; ClickHouse/SurrealDB'),
 'etl-detector':('Django/Kafka worker','source schema detection','SQLite; shared metadata store','source PostgreSQL/MySQL; Kafka; SurrealDB'),
 'etl-extractor':('Django/Kafka worker','extract rows and write bronze/checkpoints','SQLite; ClickHouse; shared uploaded-files','source DBs; Kafka; SurrealDB'),
 'etl-transformer':('Django/Kafka worker','cleaning/rules/schema/quarantine','SQLite; ClickHouse schema and quarantine state','Kafka; SurrealDB'),
 'etl-loader':('Django/Kafka worker','schema evolution and final dataset writes','SQLite; ClickHouse','Kafka; SurrealDB'),
 'etl-metadata':('Django/DRF/Kafka worker','lineage/logs/quality APIs','SQLite; SurrealDB bi_etl/etl_logs; ClickHouse quality','Kafka; ClickHouse'),
 'redis':('Redis 7 Alpine','AI transcription queue/locks/results and optional value-index cache','redis_data AOF/RDB','AI owner'),
 'clickhouse':('ClickHouse floating image','analytical and ETL operational storage','clickhouse_data; clickhouse_logs','many shared clients'),
 'surrealdb':('SurrealDB floating image','ETL logs and lineage graph','configured memory; /data mount ineffective for memory engine','ETL clients'),
 'kafka':('Confluent Kafka 7.5.0','ETL business events and voice telemetry','anonymous broker data volume','ZooKeeper; ETL and voice'),
 'zookeeper':('Confluent ZooKeeper 7.5.0','broker metadata coordination','anonymous data/log volumes','Kafka'),
 'kafka-ui':('Kafka UI floating image','broker administration UI','no application volume declared','Kafka'),
 'clamav':('ClamAV floating image','upload malware scanning','clamav_data signatures','signature update endpoint'),
}

COMM=[
 ('frontend','gateway','HTTP bearer JWT','all frontend/src/api/endpoints.js paths','KEEP; add TLS, timeout and refresh coordination'),
 ('gateway','auth/workspace/report/voice/query/visualization/subscription/notification/AI','HTTP routing','services/api-gateway/gateway/routing.py','KEEP; validate identity and sanitize trust headers'),
 ('auth','workspace','HTTP shared-key','/internal/workspaces/* and invitation/member APIs (users/services/workspace_client.py)','VERSION /internal/v1; idempotent workflow'),
 ('workspace','auth','HTTP shared-key','workspace/services/auth_client.py internal user APIs','KEEP; bulk user snapshots, no DB join'),
 ('auth/workspace/subscription/voice','notification','HTTP shared-key','/notification/events/','MOVE /internal/v1/events; durable delivery/idempotency'),
 ('subscription','workspace/auth','HTTP bearer forwarding','/workspace/{id}/; /admin/workspaces/; /admin/users/','replace administrative list fan-out with narrow internal APIs'),
 ('report','voice','HTTP bearer forwarding','/voice-reports/*','REVERSE ownership: voice calls report'),
 ('voice','workspace','HTTP bearer forwarding','/workspace/{id}/; /workspace/members/; /workspace/','FIX fail-closed membership result'),
 ('voice','AI','HTTP shared-key','small_whisper_client.py transcription/intent; forecasting_bridge.py','KEEP; bounded async job contract'),
 ('voice','query','HTTP bearer forwarding','/query/* validation/execution and dataset binding','KEEP; authorized dataset and query IDs'),
 ('voice','visualization','HTTP bearer forwarding','/visualization/question/create/ and question/dashboard embed-url endpoints','KEEP; use authorized query-definition IDs'),
 ('voice','subscription','HTTP bearer','subscription_client.py limits API','KEEP; atomic usage reservation/idempotency'),
 ('voice','Metabase','HTTP session/embedding','voice_reports/services/metabase_service.py and views fallback','REMOVE; visualization owns integration'),
 ('visualization','Metabase','HTTP session/signed embeds','/api/card; /api/dashboard; /api/session; /embed/*','KEEP; scoped read-only source projection and ownership registry'),
 ('query','ETL connector','HTTP multipart','/api/upload/','KEEP as ingestion HTTP; enforce identity/tenant'),
 ('AI','Ollama/OpenRouter','HTTP model inference','configured /api/generate and provider completion APIs','KEEP external inference; cost/egress controls'),
 ('visualization','Ollama','HTTP','chart_type_selector.py','KEEP optional; deterministic fallback'),
 ('auth','SMTP','native fallback','users/utils.py','REMOVE fallback after notification delivery contract'),
 ('notification','SMTP','native infrastructure','EMAIL_HOST','KEEP owned infrastructure; delivery retry/idempotency'),
 ('nine core Django configurations','PostgreSQL','native shared credentials','bi_voice_agent','SPLIT service DBs; remove proxy database dependencies'),
 ('notification','auth/workspace/subscription tables','direct ORM joins','users; workspaces; workspace_members; subscription_plans; workspace_subscriptions','REPLACE WITH HTTP owner APIs'),
 ('query','ClickHouse','native HTTP SQL','dataset schemas/data and execution','KEEP only owner access; separate roles'),
 ('AI','ClickHouse','native SQL/schema reads','llm_app/schema_provider.py; preprocessing_high/value_index.py','REPLACE WITH HTTP query schema/value API'),
 ('ETL extractor/transformer/loader','ClickHouse','native shared writes','bronze; deduplication; checkpoints; schema_contracts; quality/quarantine; final tables','split staging owner from serving; HTTP publish batches'),
 ('ETL metadata','ClickHouse','native reads/writes through helpers','quality_metrics and lineage helpers','REPLACE WITH HTTP owner queries/projections'),
 ('Metabase','BI source databases','native source protocol','H2 metadata confirms Sample Database (h2) and ClickHouse source; physical grants/connectivity NOT VERIFIED','EXCEPTION only read-only dedicated BI projection; no operational service DB access'),
 ('ETL stages','SurrealDB','HTTP database protocol','/sql namespace bi_etl database etl_logs','Still direct DB coupling despite HTTP transport; metadata service alone owns repository'),
 ('connector','extractor','shared filesystem','uploaded-files:/app/uploaded_files plus path in event','REMOVE inter-service sharing; ingestion-owner private file store'),
 ('connector','detector/extractor','Kafka','connection_topic / schema_topic / aliases','REPLACE WITH HTTP if separate; in-process pipeline after consolidation'),
 ('extractor','transformer','Kafka','extracted_rows_topic / raw_data','REPLACE WITH HTTP or owner-local pipeline'),
 ('transformer','loader','Kafka','clean_rows_topic / load_rows_topic / transformed_data / load_requests','REPLACE WITH HTTP or owner-local pipeline'),
 ('ETL stages','metadata','Kafka','metadata_topic / metadata_updates','REPLACE WITH HTTP batched metadata endpoint'),
 ('ETL stages','error handling','Kafka','errors / quarantine / *_dlq','REMOVE cross-service broker; owner-local durable failed-job records and replay API'),
 ('voice','unidentified event consumers','Kafka','report.voice.received; report.text.received; report.intent.generated; report.sql.generated; report.query.executed; report.visualization.ready','UNDECIDED; no in-repo consumer proved. Remove if redundant telemetry; HTTP if business consumer exists'),
 ('AI process/worker','Redis','native owner-local queue/locks/cache','whisper:transcription:* and optional value-index keys','KEEP private to AI; not a cross-service business bus'),
 ('ETL stages','shared persistence code','direct imports','etl-final/shared/models and shared/utils repositories','MOVE into domain owner; keep generic transport packages'),
]

TEST_ROWS=[
 ('query','services/query-service/tests',32,0,0,'3 warnings; isolated host pytest'),
 ('visualization','visualization_api/tests',54,0,0,'3 warnings'),
 ('AI','services/ai-service/tests',106,10,0,'12 subtests passed; semantic SQL/chart/forecast mismatches'),
 ('voice','3 voice_reports/tests_*.py contract/trace files',12,0,0,'5 subtests passed'),
 ('report','tests_sql_normalization.py',5,0,0,'isolated unit tests'),
 ('frontend','2 node test files',9,0,0,'node --test'),
 ('ETL shared selected','schema_contract/rules_engine/ch_identifiers/input_validator/credential_encryption',136,3,0,'PYTHONPATH includes ETL and shared/utils; rule warnings versus errors mismatch'),
 ('ETL loader selected','engine/test_etl_remediation_loader.py',7,1,0,'identifier trailing underscore mismatch'),
 ('ETL extractor selected','remediation, SQL injection, pagination contract',12,19,0,'19 failures use non-iterable Mock cursor.description; not evidence of 19 real SQL injection bugs'),
 ('ETL connector selected','file validator and Kafka publish reliability',38,13,0,'Mock uploaded_file.chunks not iterable'),
 ('ETL shared full','shared/models shared/utils','NOT RUN','6 collection errors','NOT VERIFIED','encoding/import errors and kafka package shadowing'),
 ('ETL transformer selected','cleaning/rules/remediation','NOT RUN','1 collection error','NOT VERIFIED','after correcting PYTHONPATH; local kafka module shadows dependency'),
 ('auth/workspace/subscription/notification/gateway','no dedicated first-party test files inventoried','NOT VERIFIED','NOT VERIFIED','NOT VERIFIED','requires isolated service/contract/security suite'),
 ('ETL detector/metadata','placeholder tests.py present','NOT VERIFIED','NOT VERIFIED','NOT VERIFIED','no comprehensive suite executed'),
]

def baseline_reports():
    write('issues.json',json.dumps(ISSUES,indent=2))
    counts=collections.Counter(i['severity'] for i in ISSUES)
    svcrows=[]
    for name,s in INV['compose']['docker-compose.yml']['services'].items():
        tech,job,db,deps=RESP[name]
        health=s.get('healthcheck',{}).get('test',[])
        typ='TCP only' if 'socket.create_connection' in str(health) else ('configured; runtime verification required' if health else 'NONE')
        svcrows.append((name,tech,job,', '.join(map(str,s.get('ports',[]))) or 'internal',db,deps,','.join(s.get('depends_on',{})),typ))
    inventory=table(['Service','Technology','Responsibility','Host:container port','Data','Runtime dependencies','Compose start dependencies','Health check'],svcrows)
    write('SERVICE_INVENTORY.md','# Service inventory\n\n24 unified Compose entries: 16 application services, one same-domain notification worker, seven infrastructure entries. React/Vite frontend and host PostgreSQL/Ollama plus standalone Metabase are additional processes. The legacy ETL manifest declares 12 entries, largely alternate deployments of the same code; do not double count them as separate domains.\n\n'+inventory+'\nRuntime snapshot: 32 existing containers, all stopped at initial inspection; 555 Docker volumes. See runtime_inventory.json for all names, mounts, bindings and context. Declared health is not a health PASS.\n')
    envrows=[]
    examples=set(INV['local_env_names'].get('.env.example',[]))
    for e in INV['environment']:
        refs=e['references'];key=e['name']
        envrows.append((key,'secret-like name; inspect semantic use' if any(r.get('secret') for r in refs) else 'configuration','required by Compose' if any(r.get('required') for r in refs) else 'required/default varies by caller','yes' if key in examples else 'no','; '.join(f"{r['file']}:{r['line']}" for r in refs)))
    write('ENVIRONMENT_VARIABLE_INVENTORY.md','# Environment variable inventory\n\nStatic extraction identified 245 names before audit tooling. Values are deliberately omitted. This is an explicit-call/interpolation inventory, not proof that dynamically assembled environment names do not exist. Secret-like matching includes policy values such as PASSWORD_RESET_MAX_ATTEMPTS; those are not credentials.\n\nThe existing .env.example is retained. It is incomplete for ETL/runtime defaults and broad shared env_file distribution violates least privilege. Use .env.development and .env.test (ignored), sanitized per-service examples, explicit APP_ENV and externally managed production secrets. Fail fast at service startup as well as Compose interpolation. Existing naming duplicates include DEBUG/DJANGO_DEBUG, ALLOWED_HOSTS/DJANGO_ALLOWED_HOSTS, CORS_ALLOWED_ORIGINS/DJANGO_CORS_ALLOWED_ORIGINS and multiple LLM timeout/model families. Do not remove variables merely because absent from this static scan; compare actual container env_names and runtime paths first.\n\n'+table(['Variable','Sensitivity','Requirement','Root example','References'],envrows))
    write('API_INVENTORY.md','# API inventory\n\n171 static route declarations, including include mounts and duplicate/legacy URL modules; this is not a count of reachable endpoints. Resolve root URLConf and gateway routing together. No first-party canonical OpenAPI document was found. Request/response validation is distributed across serializers, Pydantic DTOs and manual request.data extraction; full generated schemas and live behavior are NOT VERIFIED for every route.\n\nCore DRF defaults generally require bearer authentication; auth public routes explicitly AllowAny, notification validates its internal key manually despite AllowAny, AI uses require_internal_api_key decorators, ETL DRF defaults are public. Route-specific object authorization remains necessary (SEC-001/002/005).\n\n'+table(['URL module','Line','Declaration'],[(r['file'],r['line'],r['declaration']) for r in INV['routes']])+'\nTarget: /api/v1 for public endpoints and /internal/v1 for service APIs, one error envelope {code,message,request_id,details}, documented pagination, idempotency and timeouts. Keep old public URLs as temporary gateway aliases. Contract tests must cover success, 401, 403, 404, timeout, invalid response and unavailable dependency.\n')
    write('TEST_EXECUTION.md','# Test execution — 2026-09-13\n\nHost Python 3.12.3; source services build Python 3.10/3.11 images, so host test success is not container parity. Commands use python -X utf8 -B -m pytest <paths> -q -p no:cacheprovider --tb=short. ETL selected suites required PYTHONPATH=<repo>/etl-final; selected shared tests additionally require <repo>/etl-final/shared/utils. Initial import failures remain documented; path fixes do not fix the kafka shadowing defect.\n\n'+table(['Service','Scope','Passed','Failed','Skipped','Notes'],TEST_ROWS)+'\nExecuted non-overlapping selected tests: 411 passed, 46 failed, plus 17 passing subtests. Collection failures are separate, not skipped tests. No result claims full coverage. Frontend npm run build passed after retry outside sandbox; bundle JS 661.70 kB / 191.89 kB gzip. npm run lint failed: ESLint configuration absent. docker compose config --quiet passed. Static AST parse found no syntax errors in first-party scanned Python files.\n\nFailing groups: AI daily trend/distribution SQL and forecast/chart selection; ETL rules error/warning contract; loader identifier contract; extractor cursor mocks; connector upload chunk mocks. Reconcile intended contracts rather than blindly changing expectations. Full ETL collection additionally encounters UTF-16 test_file.txt, top-level imports and shared/kafka shadowing kafka-python.\n\nThe workspace-client security reproduction returned caller hint 999999 after a mocked HTTP 403; no live tenant record was accessed. Existing SQL guard tests cover AST statements, table functions, system tables and workspace DB binding and passed. Their pass does not secure visualization paths that bypass that guard.\n\nRequired next tests: two-tenant CRUD/embeds/files/AI/query history; revoked membership; JWT expiry/reuse/admin denial; new-install migration graph per owner; dependency outage readiness; restore drills; full disposable upload→ETL→query→report workflow with mail disabled and no paid model calls.\n')
    write('SERVICE_COMMUNICATION_MATRIX.md','# Service communication matrix\n\nHTTP transport to a database is still direct database access, not an owner-service API. Worker processes within one declared owner are not independent microservices. Configured dependencies are separated from observed source calls.\n\n'+table(['Caller','Target','Current method','Endpoint/resource','Target/action'],COMM)+'\nKafka policy: REPLACE the five grouped inter-service ETL workflow paths (connection/schema, extracted rows, clean/load rows, metadata, error/DLQ). The two row topics and aliases are alternatives/branches, not necessarily independent consumers. Voice report.* events are UNDECIDED pending consumer discovery; no business consumer is proved. No Kafka usage is approved for retention merely because the payload is called analytics. Redis transcription coordination is KEEP within AI ownership; no Redis pub/sub cross-service business path was found.\n')
    write('PRE_DEVELOPMENT_SYSTEM_AUDIT.md',f'''# Pre-development system audit

Audit date: 2026-09-13. Repository: BI-Voice-Agent. Branch main, source HEAD 1ca062c (2026-05-08). The working tree already contained extensive staged/unstaged/untracked changes; snapshot is in inventory.json. The parent folder is not a usable Git repository. No user changes were discarded and no architectural refactor was performed.

## Executive assessment

**NOT READY for production. Phase 0 completion depends on the reset/startup evidence in DATA_STORAGE_AND_WIPE_REPORT.md; generating reports alone is not success.** There are {len(ISSUES)} actionable findings: {dict(counts)}. Critical findings include fail-open workspace authorization, unscoped Metabase operations/SQL, retained historical secrets, public ETL APIs and insecure persistence. Existing hardening is meaningful in query SQL AST checks, explicit workspace dataset binding, shared HTTP transport, upload validation/ClamAV and ETL idempotency helpers. These controls are incomplete across alternate paths.

Source inventory scanned 819 selected first-party source/config files, 171 route declarations, 76 model classes including inactive/DTO-like classes, 245 environment names and 121 test files. Full file lists are in inventory.json. Database binary contents were inventoried/backed up separately, not treated as source. Vendor TimesFM is a nested upstream checkout; its source/test suite was not exhaustively audited. Generated caches, dependencies, datasets and previous prose audits are not treated as proof. This is broad recursive static inspection plus targeted runtime and behavioral verification, not a guarantee that every possible issue was found.

## Architecture and inventories

The active source is a mixed Django service system, not a strict database-per-service architecture. PostgreSQL is a Windows-host service, Metabase is a standalone stopped container with H2 metadata, and Ollama runs on the host. Unified Compose has 24 entries. The ETL stack uses Django web processes plus Kafka listeners, shared persistence code and shared files. Report-service forwards CRUD to voice-service. AI directly reads ClickHouse and coordinates transcription through Redis. There is a routing gateway but no configured TLS reverse proxy.

See [service inventory](SERVICE_INVENTORY.md), [database ownership](DATABASE_OWNERSHIP_MATRIX.md), [environment inventory](ENVIRONMENT_VARIABLE_INVENTORY.md), [API inventory](API_INVENTORY.md), [communication matrix](SERVICE_COMMUNICATION_MATRIX.md), [current diagrams](CURRENT_ARCHITECTURE.md) and [test evidence](TEST_EXECUTION.md). Runtime_inventory.json enumerates all 555 volumes, 32 containers and Docker networks; unknown resources are preserved.

## Operational and code-quality observations

Core HTTP services use Django runserver, root defaults and broad env_file injection. Startup ordering includes an unnecessary chain through AI/ETL/visualization before the gateway becomes healthy; a ClamAV or AI failure can prevent unrelated auth access. ETL listeners are not separately supervised from web servers. Root and legacy Compose conflict in container names and host ports and must not be launched together.

Largest source modules: voice views 3727 lines; AI query planner 2592; AI execution asset 2034; visualization Metabase client 1482; dashboard shell 1324; transcription task 1249. Repeated Metabase clients, SQL normalization variants, JWT principals, broad exceptions and sys.path mutation make invariants drift. Inactive report ORM is documented as inactive, not falsely classified as an active cross-database join. Query and visualization tests passed, while AI/ETL contracts and lint are not green. No first-party CI/deployment gate was discovered.

Dependency risk includes unsupported Django 4.2, broad Python requirements and floating images. The Django support conclusion was checked against [Django's support table](https://www.djangoproject.com/download/). Metabase H2 handling follows [the vendor backup guidance](https://www.metabase.com/docs/latest/installation-and-operation/backing-up-metabase-application-data). Exact vulnerability inventory, installed-image SBOM, RLS/grant penetration tests, load tests and all end-to-end API behaviors remain NOT VERIFIED.

## Findings

'''+''.join(issue_text(i) for i in ISSUES))

if __name__=='__main__':baseline_reports()
