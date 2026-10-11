# Security audit

**NOT READY.** Critical authorization and credential exposure issues are documented in `issues.json` with file/line evidence and remediation. No external key was exercised, no external data source was contacted for cleanup, and no secret values are included here. Source findings and helper-level reproductions are distinguished from full live exploitation.

## Immediate security boundaries

1. **SEC-001:** voice workspace resolution keeps a client hint after a denied membership lookup. A local mocked call returned workspace `999999` after HTTP 403. Page/report handlers consume that result; failure must deny access instead of retaining the hint.
2. **SEC-015:** query's dataset-status endpoint accepts arbitrary dataset IDs and replacement ClickHouse bindings from any authenticated principal. This can undermine otherwise sound SQL dataset-binding checks and raw-identifier preview/deletion paths.
3. **SEC-002 / SEC-003:** visualization signs embeds and mutates cards/dashboards without tenant ownership checks, and creates/exercises Metabase native SQL after formatting-only normalization.
4. **SEC-005 / SEC-006:** public ETL upload/connection/log APIs lack tenant identity. Arbitrary host/port connection testing permits internal-network SSRF; source filenames alone are not tenant namespaces.
5. **SEC-004:** credential values in Git history still match current local settings. Treat them as exposed until rotated.

## Secrets and rotation

`HEAD:.env.microservices` was inspected in memory and compared without emitting its contents. Current nonempty admin password, Metabase embedding secret, notification key, AI internal key and OpenRouter key match historical values. Historical DB, Metabase login and Django signing credentials also require rotation evidence. Password-reset attempt/expiry settings matched too, but are policy numbers, not secrets, and are excluded from credential counts.

**SECRET ROTATION REQUIRED.** Revoke the OpenRouter key at its provider, provision a replacement with a budget, and update only AI's secret source. Change the environment admin credential and invalidate its sessions. Rotate internal service keys together; support a brief old/new acceptance window only where necessary. Rotate Metabase embedding keys and invalidate previously signed embeds. Rotate historical DB/Metabase login/JWT credentials unless prior rotation can be demonstrated. Remove broad shared `.env` distribution. Production secrets belong outside Git; examples contain placeholders only. A history rewrite requires a separate coordinated repository operation and was not performed.

External provider/source endpoints are **CRITICAL — POSSIBLE PRODUCTION RESOURCE** for reset purposes and are excluded. Local host identity alone does not prove every historical record was disposable; the wipe manifest limits actions to identified development data and preserves Metabase/unknown stores.

CredentialEncryption falls back to a fixed source-known key if CREDENTIAL_SECRET_KEY is absent; root ETL definitions do not pass this key. Require a key at startup and version encrypted records. The ClickHouse helper sends its password in query parameters and logs exceptions; move authentication out of URLs and redact errors. Some provider debug/test modules and tracked ClickHouse preprocessed configs require a history scan before publication. No exhaustive entropy/CVE/history scanner result is claimed.

## Authentication and account lifecycle

Auth uses Django password hashing and SimpleJWT, verified-email workflow, signed activation tokens, refresh blacklist tables and recovery-code models. A special administrator is an environment-configured principal, not necessarily a row in users. Downstream services implement multiple stateless JWT principal classes; shared HS256 verification material also allows token signing. Issuer/audience and live revocation behavior need integration tests. Current auth access tokens last one hour, refresh tokens seven days, and rotation is disabled. The frontend only stores refreshed access, so enabling rotation later requires a coordinated client change. Both tokens are currently in localStorage.

The gateway checks Authorization presence, not validity. Downstream verification therefore remains security-critical. Auth/workspace and notification have internal shared-key checks; AI's require_internal_api_key defaults to required and returns 503 if missing. Notification AllowAny is **not** by itself proof of an unauthenticated event endpoint: its handler explicitly validates the key. AI comments claiming no authentication are stale; inspect decorators, not comments.

Invitation signup can overwrite an existing invited user's password and role. Invitations must grant membership only; existing accounts must authenticate or complete the separate recovery flow. Registration performs remote workspace operations inside a local transaction and needs durable workflow/idempotency and compensation. Account deletion/deactivation, admin login/logout, recovery throttling and token reuse require end-to-end tests; no real account email was sent by this audit.

## Authorization and multitenancy

Query execution compares request workspace with JWT claims and resolves database bindings server-side; its AST guard tests passed. DatabasePreview selects by the authenticated manager, which is a useful control. Workspace/report/page code often filters by workspace or owner, but a filter is only as trustworthy as the resolved workspace. SEC-001 and SEC-015 poison these prerequisites.

Metabase IDs must map to verified tenant resources before signing or mutation, including both sides of an attach operation. Never trust an AI trace, client workspace_database, dataset_id, report_id, page_id, source_id or subscription_id without checking authority. Unmapped legacy data must be quarantined or manually assigned, not globally exposed. Add test tenants with identical source filenames and report titles to detect namespace collisions. Audit cached AI schema/value data and signed embed URLs for tenant scoping and expiry.

## SQL, uploads and AI

The query AST guard covers single-statement read-only SELECT/WITH, dangerous table functions/system tables and workspace DB qualifiers. This does not cover all paths: visualization's sanitize_sql_for_metabase is formatting logic; query metadata status accepts raw physical names; ClickHouseClient interpolates names in DROP/SELECT statements. Restrict identifiers to an owner registry and apply explicit quoting, table authorization and read-only database grants. LLM outputs are untrusted proposals; never execute them just because they parse.

Upload validation includes extension/MIME/size checks and ClamAV scanning; tests show fixture drift, not proof malware scanning works in production. Confirm fail-closed scanner errors, zip/decompression budgets, content sniffing, collision-resistant file naming, path resolution and download authorization. ETL validates hostname syntax but permits localhost and does not enforce resolved-IP network boundaries. Source connectors need least-privileged read-only accounts, TLS, bounded result sizes, connection pooling or bounded connection lifetimes and explicit egress authorization.

AI uses host Ollama and optional external OpenRouter; Whisper/TimesFM rely on local/model-cache assets. No paid inference was invoked for security validation. Add per-tenant concurrency/token/cost budgets, provider allowlists, protected prompt construction, response schema validation and retention rules. Avoid sensitive prompts/rows/audio in logs. Python thread timeout currently does not reliably stop inference; use process-level cancellation or bounded job workers.

## Infrastructure, web and operational controls

Published database/model/ETL/admin ports bypass gateway controls. Redis is unauthenticated at its published endpoint; Kafka is PLAINTEXT and single-replica; SurrealDB credentials are global across ETL. Application containers default to root and use runserver. Add TLS edge, network segmentation, non-root/pinned builds, resource limits, production server and service-specific secrets.

Core CORS is closed by default and accepts an origin allowlist; ETL still uses DEBUG/wildcard hosts. Browser bearer headers mean CSRF is not the main control for those API paths; Django admin/session cookies still need Secure/HttpOnly/SameSite and CSRF checks. Gateway is csrf_exempt and forwards headers, so any cookie-based design needs deliberate CSRF enforcement. No blanket XSS/CSRF PASS is claimed. Configure CSP, secure headers and controlled embedding origins. Gateway rate limits are per process/path, have unbounded key retention and can be bypassed through published services.

No root .dockerignore or first-party CI secret/advisory scan was discovered. Many services pin Django 4.2.7, and [Django 4.2 support ended in April 2026](https://www.djangoproject.com/download/). Plan a supported upgrade and lock transitive dependencies; do not automatically upgrade the whole platform. Metabase recommends preserving H2 then [migrating to a production application database](https://www.metabase.com/docs/latest/installation-and-operation/migrating-from-h2); retain the current metadata through that operation.

Full issue metadata and priorities are canonical in issues.json and PRE_DEVELOPMENT_SYSTEM_AUDIT.md. Security acceptance requires two-tenant negative tests, secret rotation evidence, scoped service identity, network/grant verification and a green deployment pipeline, not merely configuration files.
