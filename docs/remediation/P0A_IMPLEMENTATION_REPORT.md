# P0-A implementation report

## Executive summary

P0-A closes the audited critical trust-boundary defects without deleting data, splitting databases, removing Kafka, migrating Metabase/SurrealDB, upgrading Django, or restructuring services. Authorization now fails closed, ingestion callbacks use service identity and immutable bindings, invitations cannot recover existing accounts, Visualization relies on application ownership and Query-owned definitions, ETL APIs require scoped identity, connector destinations are policy checked after DNS resolution, and production configuration rejects missing/placeholder secrets.

All 55 new security tests and 158 existing relevant tests pass. Compose validation, compile checks, migration drift checks, and disposable migration upgrades pass. The current local PostgreSQL copy could not be reached from the host because its `pg_hba.conf` rejects the configured host, so that upgrade remains unverified. External secret rotations also remain manual by design. P0-A acceptance is therefore **PARTIAL** on verification, with implementation complete.

## Issues addressed

### SEC-001

- **STATUS:** FIXED
- **Affected files:** Voice workspace client, auth context, report/dashboard views, orchestration, and workspace authorization tests.
- **Root cause:** A caller-supplied workspace hint survived denied or ambiguous Workspace responses.
- **Implementation:** Added explicit `AUTHORIZED`, `DENIED`, `NOT_FOUND`, `DEPENDENCY_UNAVAILABLE`, and `INVALID_RESPONSE` results. Only a matching positive response yields context; every Voice call site unwraps it through a fail-closed guard.
- **Tests:** 401/403, 404, timeout, malformed/mismatched response, and valid membership; all Voice suites pass.
- **Remaining risk:** A live two-tenant deployment test is still recommended after the local stack is available.
- **Compatibility impact:** Workspace dependency outages now return 503 instead of continuing with a request hint.

### SEC-002

- **STATUS:** FIXED
- **Affected files:** Visualization ownership model/migration, views, Metabase service, JWT embedding service, and ownership tests.
- **Root cause:** Metabase IDs were treated as authorization evidence.
- **Implementation:** Added an application-owned card/dashboard registry keyed by workspace, object type, creator, source context, and optional query definition. Embeds and attachments require mapped ownership; card and dashboard are both checked. Persistence failure removes the newly created Metabase object. Missing legacy mappings are denied, which is the safe `UNMAPPED` behavior.
- **Tests:** Foreign/unmapped card and dashboard, both attachment directions, valid same-tenant attach, and five-minute token cap.
- **Remaining risk:** Preserved legacy Metabase objects need an operator-assisted evidence-based inventory before any can be marked mapped.
- **Compatibility impact:** Legacy objects without a proven registry row no longer receive embeds.

### SEC-003

- **STATUS:** FIXED
- **Affected files:** Query authorized-definition model/migration/views/URLs, Visualization query authorization/view, Voice compatibility adapter, and tests.
- **Root cause:** Visualization accepted public raw SQL and could bypass Query authorization.
- **Implementation:** Query Service now issues short-lived definitions bound to workspace, dataset, creator, validated SQL, status, and expiry. Visualization accepts the reference and retrieves it from Query with the caller authorization. Voice first creates a Query definition before requesting a chart. The existing AST policy remains the single SQL security policy.
- **Tests:** Raw SQL rejection, cross-workspace definition rejection, and the existing multiple-statement/DDL/DML/system-table/table-function/database-binding suite.
- **Remaining risk:** Query definitions currently expire after 15 minutes and need normal cleanup/retention operations in a later phase.
- **Compatibility impact:** Callers must send `query_definition_id`; the Voice adapter performs this exchange automatically.

### SEC-005

- **STATUS:** FIXED
- **Affected files:** ETL shared internal auth/scope, all non-health ETL API views, metadata query builder, Query upload caller, compose/settings, and tests.
- **Root cause:** ETL control and metadata endpoints accepted anonymous/global requests.
- **Implementation:** Added constant-time service-credential authentication and mandatory workspace/dataset/job scope. Scope propagates in Kafka/metadata messages. Metadata reads include all three scope predicates and exact-result filtering. Health/metrics remain observable only through loopback-bound development ports.
- **Tests:** Anonymous caller, approved caller, invalid job, and tenant/dataset/job mismatch cases.
- **Remaining risk:** Strong workload identity can replace shared service credentials during the later architecture phase.
- **Compatibility impact:** Direct ETL API callers must supply the internal identity and all three scope fields.

### SEC-006

- **STATUS:** FIXED
- **Affected files:** ETL destination policy, connector/extractor views and connector utility, environment example, and tests.
- **Root cause:** Syntax-valid user hosts could target loopback, metadata, link-local, or private networks.
- **Implementation:** Resolve all addresses, reject unsafe classifications unless an administrator CIDR explicitly allows them, and connect to the validated resolved address to limit DNS rebinding. Database clients use bounded connection/read/write timeouts.
- **Tests:** IPv4/IPv6 loopback, cloud metadata/link-local, private networks, public destination, and explicit private CIDR allowlist.
- **Remaining risk:** Approved CIDRs must be reviewed as privileged deployment configuration.
- **Compatibility impact:** Local/private database connections require `ETL_APPROVED_DESTINATION_CIDRS`.

### SEC-007

- **STATUS:** FIXED
- **Affected files:** Credential encryption utility, ETL runtime settings/compose, loader/metadata credential defaults, and tests.
- **Root cause:** Missing encryption configuration silently used a source-known deterministic key; ETL also contained a runtime ClickHouse password fallback.
- **Implementation:** Credential encryption raises on a missing external key. Connector/extractor production startup requires it. Runtime datastore code no longer supplies the audited password fallback.
- **Tests:** Missing encryption key and encryption round-trip suites pass.
- **Remaining risk:** Historical values still require operator rotation.
- **Compatibility impact:** ETL cannot start/use credential encryption until required secrets are supplied.

### SEC-008

- **STATUS:** FIXED
- **Affected files:** All Django service settings, ETL runtime validator/settings, compose, environment example, and security configuration tests.
- **Root cause:** Source-known Django keys, debug/wildcard patterns, and ambiguous deployment profiles allowed insecure startup.
- **Implementation:** Every service requires `development`, `test`, or `production`. Non-production defaults exist only in explicit non-production profiles. Production rejects missing/placeholder signing keys, debug mode, and wildcard/empty hosts.
- **Tests:** Source assertions, runtime production rejection, compile checks, and Compose rendering.
- **Remaining risk:** Deployment secret-store policy and rotation evidence are operational controls.
- **Compatibility impact:** Direct service startup now requires `APP_ENV`; Compose supplies an explicit development default.

### SEC-009

- **STATUS:** FIXED
- **Affected files:** Root and ETL Compose definitions.
- **Root cause:** Services and datastores published on all host interfaces.
- **Implementation:** Every development host publication is bound to `127.0.0.1`; container-to-container ports and service names are unchanged.
- **Tests:** Compose renders successfully and a static scan finds no unqualified `host:container` publication.
- **Remaining risk:** Production edge/network policy remains a deployment responsibility.
- **Compatibility impact:** Other machines can no longer connect directly to the developer host ports.

### SEC-013

- **STATUS:** FIXED
- **Affected files:** Query ClickHouse utility and credential-redaction tests.
- **Root cause:** ClickHouse credentials could enter URLs/query parameters and exception text.
- **Implementation:** Queries use POST bodies and supported Basic authentication, identifiers are strictly validated/quoted, limits are bounded, and errors/logs disclose only safe classifications.
- **Tests:** URL/parameter absence, auth tuple use, malicious identifier rejection, and credential-bearing exception redaction.
- **Remaining risk:** Central log-platform redaction should remain defense in depth.
- **Compatibility impact:** None for callers.

### SEC-014

- **STATUS:** FIXED
- **Affected files:** Auth invitation serializer/tests and Workspace acceptance view/tests.
- **Root cause:** Invitation possession could replace password/name/role on an existing email account.
- **Implementation:** Existing accounts must authenticate as the exact invited ID/email. Signup rejects the existing-account recovery path. Acceptance uses a row lock, consumes once, checks expiry, and changes membership only; it never patches the global user identity/role.
- **Tests:** Existing-account denial, new identity signup, anonymous/wrong identity, expired, replayed, and matching acceptance.
- **Remaining risk:** End-to-end email-link testing should be repeated in the deployed auth/workspace pair.
- **Compatibility impact:** Existing users must sign in before accepting an invitation.

### SEC-015

- **STATUS:** FIXED
- **Affected files:** Query dataset model/migration, internal authentication, callback view/URL, ClickHouse utility, upload caller, and tests.
- **Root cause:** A frontend-accessible update path used insufficient ownership binding and accepted physical identifiers.
- **Implementation:** Added immutable ingestion job IDs and `POST /internal/v1/ingestion/jobs/{job_id}/dataset-status`. It requires an approved ingestion service, exact job/dataset/workspace lookup, expected state, field allowlist, row lock, legal transition, and idempotence. Physical identifiers cannot be changed through the callback.
- **Tests:** Frontend token, missing service key, wrong binding, unknown field, stale/illegal state, idempotence, and malicious identifiers.
- **Remaining risk:** The configured local PostgreSQL copy upgrade could not be exercised from this host; the disposable 0002-to-0004 upgrade passed.
- **Compatibility impact:** The old dataset status route is removed; ingestion workers must use the versioned callback.

## SEC-004 preparation

`SECRET_ROTATION_CHECKLIST.md` records seven credential groups requiring provider/admin action. None is marked rotated. Rotation evidence must be recorded outside the repository without secret values.

## Validation and classification

- Existing relevant tests: **158 passed, 0 failed**.
- New security tests: **55 passed, 0 failed**.
- New regressions: **0**.
- Query final suite: 50 passed.
- Visualization final suite: 62 passed.
- Voice final suite: 20 passed plus 5 subtests.
- Auth/Workspace invitation security: 6 passed.
- ETL security controls: 15 passed; selected ETL regression/security run: 46 passed.
- Compileall and Compose config: passed.
- Migration drift: no changes detected for Query and Visualization.
- Disposable upgrades: Query 0002 to 0004 and Visualization zero to 0001 passed.
- Current local PostgreSQL upgrade: **NOT VERIFIED** because the configured server rejected the host through `pg_hba.conf`.

## Acceptance blockers

P0-A verification remains **PARTIAL** until:

1. The Query and Visualization migrations are applied to a disposable copy of the current local PostgreSQL database and the service smoke tests pass there.
2. A live two-tenant stack repeats the CRUD/embed/metadata scenarios with real service calls.
3. The seven manual credential rotation groups are completed and independently verified.

No P0-B work was started.
