# Foundation-C Part 2 — Credential Lifecycle and Connection Transport

> Date: 2026-10-19  
> Status: **PARTIAL**  
> Foundation-C overall: **PARTIAL**  
> Baseline: `main` at `9298d2f25425f880cb56ccdeb2036e65f83f1bcb`  
> Commit/push: **none**

## 1. Executive Summary

Integration now stores source-scoped encrypted credential versions, authorizes an immutable source/credential/configuration binding per operation, and exposes ciphertext only through a separate authenticated internal resolver. New Connector snapshot events use a v2 opaque credential reference; Extractor resolves the frozen execution binding and no new v2 event carries reusable tenant ciphertext. Source credential rotation validates a candidate before atomic activation. Replacement stages and tests a separate candidate, requires a completed candidate snapshot before cutover, and retains a 24-hour rollback point. The shared `DirectSecureInternetTransport` revalidates DNS immediately before a pinned driver connection. PostgreSQL and ClickHouse have supported production pin/TLS contracts; other network engines fail closed in production direct mode until their hostname/pinning contracts are certified.

This is **PARTIAL** because the full Gateway → Connector → Kafka → Extractor → Loader → ClickHouse → Query run did not execute, the stock disposable PostgreSQL image had no TLS, C4 physical roles and deployment egress/managed-secret controls are absent, and MySQL/MariaDB/MSSQL/Oracle direct production modes remain blocked. Do not mark Foundation-C GREEN.

## 2. Baseline / Worktree State

`main`, baseline HEAD above. Foundation-C Part 1 files were uncommitted at entry: 13 tracked modifications and Integration/migration/report additions. The pre-existing dirty TimesFM submodule was untouched. This part added C3 files and modified C1/C2 paths in place. No staging, commit, push, reset, clean, history rewrite, or TimesFM change occurred.

## 3. Documents Read

Master context `34` first; canonical scope/architecture/ownership/AI/security `29`–`33`; register `20`; roadmap `25`; map `26`; Foundation-A/B reports `36`/`37`; mandatory C1/C2 report `38`; P1/P1-R architecture, audit, implementation, acceptance matrix, and remediation documents. The later v2 canonical rules govern the older P1 password-in-event design. P1-R evidence records a live MariaDB snapshot in addition to PostgreSQL, MySQL, SQLite, and ClickHouse; MSSQL and Oracle are contract-only in this environment.

## 4. Canonical C3 Issue Map

| Issue / map | Entry finding/status | C3 responsibility/evidence | Closure / C4 or later |
|---|---|---|---|
| BIA-005 / MAP-020 | Shared PostgreSQL owner role/schema; PARTIAL | Integration-owned credential tables and contracts | **PARTIAL**. C4 owner schemas/roles, denied cross-owner writes, reversible deployment proof. |
| BIA-008 / MAP-021, MAP-040 | Unsafe source/credential lifecycle; PARTIAL | Versioned credential, ref resolution, direct transport, staged replace | **PARTIAL**. C4 managed key/identity/egress deployment and full live proof. |
| BIA-014 / MAP-021 | One source and destructive replacement; PARTIAL | Candidate test/load/cutover/rollback; old datasets preserved | **PARTIAL** pending full live cutover/rollback gate. |
| BIA-018 | DNS rebinding window; open | Central policy, pre-connect revalidation and pinning; unsafe production engines blocked | **PARTIAL** pending real production TLS/egress and engine gate. |
| BIA-030 / MAP-042 | Physical API identifiers; PARTIAL | No new physical/credential fields exposed publicly | **PARTIAL** pending full API audit in C4/later. |
| MAP-001 | Preserve registry/engine contracts | Registry retained, transport is a separate axis | C4 source-engine live matrix. |
| MAP-005 | Preserve security/regression gates | Extended tests and changed-source scan | C4 complete release gate. |

BIA-009 durable jobs, BIA-017 metadata, BIA-021 AI schema tools, Notification foreign ORM access, and Query direct ClickHouse delete remain separate work.

## 5. Credential Flow Before

| Operation | Previous path/problem |
|---|---|
| Create source | Non-secret metadata only; browser retained password. |
| Test/discovery | Browser password → Query HTTP → Connector driver on every call. |
| Snapshot/retry | Browser password → Query → Connector → reusable Fernet ciphertext in `connection_topic` → Extractor decrypt; replay reused event secret. |
| Restart/rotation | No stored secret, version, or governed rotation; browser resubmission required. |
| Disable/retire | Prevented new source selection but had no credential revocation lifecycle. |

No browser password was intentionally persisted by C1/C2. The legacy ETL Fernet envelope used `CREDENTIAL_SECRET_KEY` with a static derivation salt and no key version. Logs/responses already had Foundation-B redaction, but an encrypted reusable tenant password lived in each snapshot event.

## 6. Credential Ownership Decision

`integration` in the Query deployment is the sole credential lifecycle writer. Query analytical modules authorize datasets; they do not encrypt/decrypt source credentials. Connector and Extractor consume an exact Integration grant; AI, Voice, Report, Visualization, and frontend never receive source secrets. Existing shared PostgreSQL physical access remains C4 debt.

## 7. Credential Model / Versioning

`SourceCredential`: opaque UUID, source FK, monotonic source-local version, key version, Fernet ciphertext, candidate/active/superseded/revoked state, created/activated/deactivated/revoked times. `DataSource` carries a transport discriminator and monotonic configuration version. `SourceExecution` freezes source, workspace, dataset, job UUID, credential version, engine, non-secret connection metadata, transport, and expiration. New source rows are **not** silently backfilled with invented passwords. Public source JSON contains only `credential_configured`, never credential ID/ciphertext/password.

## 8. Encryption at Rest

`bi_platform_shared.credential_crypto` uses `cryptography` Fernet authenticated encryption and HKDF domain separation from a deployment-supplied high-entropy `CREDENTIAL_SECRET_KEY[_Vn]`. Ciphertext records its key version; missing/invalid keys and malformed ciphertext fail closed with safe messages. No key is stored in PostgreSQL. Old key versions must remain available until all corresponding source credentials are rewrapped/expired. C4 must provision these secrets through a managed secret store/workload identities; local Compose environment injection is **not** that production proof.

## 9. Credential Create / Rotation / Revocation

Source POST may accept a password once; Integration encrypts it inside the creation transaction. Existing C1 sources can use `credential/configure/` once. `credential/rotate/` creates a candidate, issues a scoped Connector test, then atomically activates it only if the prior active credential is unchanged. Failed validation or concurrency conflict revokes and erases the candidate ciphertext, leaving the old active version. Explicit revoke and source retirement erase all active, superseded, and candidate ciphertext, invalidating old in-flight grants too. Otherwise superseded ciphertext is retained only for live grants/rollback and pruned after the 24-hour window by `prune_source_credentials`; deployment must schedule that command at least daily.

## 10. Execution Consistency During Rotation

A grant is created at the Query operation boundary under a source row lock. It binds exactly one source configuration and credential version. New work after rotation selects the new active version; an already authorized grant continues with its frozen version until its 24-hour expiry unless explicitly revoked. A retry after grant expiry must become a new attempt; durable BIA-009 job/retry policy remains separate. Rotation concurrency uses an expected-active-version check.

## 11. Credential Resolution Boundary

`POST /internal/v1/source-credentials/resolve/` accepts only `etl-connector` or `etl-extractor` with a separate resolver key. It requires exact workspace/source/dataset/job/credential/version match to a live grant; Extractor is limited to snapshot/candidate grants. The response contains encrypted ciphertext and frozen configuration, **not plaintext**. The ETL shared client checks echoed scope and decrypts only in process memory. Wrong workspace/source/service/malformed ref fails closed. C4 must replace the shared resolver key/network trust with production workload identity and owner DB grants.

## 12. Kafka Contract Before / After

Before: unversioned snapshot event with encrypted password in `configuration`, `_password_encrypted=true`, legacy dataset-scoped `source_id`, optional Integration UUID. After: new `contract_version=2`, `credential_ref` (source/workspace/dataset/job/credential UUID/version), `configuration_version`, retained `integration_source_id`, and retained legacy dataset-scoped `source_id`; `configuration` contains no password/ciphertext. Extractor ignores event connection configuration for v2 and resolves the frozen grant; a missing/mismatched v2 reference fails closed. Legacy v1 consumer support remains only for already queued events; production Connector rejects new raw-password server operations and the legacy `/api/connect-db/` path returns 410. The v1 removal gate is draining/expiring queued events and C4 replay acceptance. The credential ref is removed before metadata projection.

## 13. ConnectionTransport Architecture

`ConnectionTransport.before_connect(configuration, engine)` represents reachability, independent of the seven engine adapters in the existing registry. The only implemented mode is `direct_secure_internet`; other modes return `TRANSPORT_UNAVAILABLE`. SQLite is file-scoped and bypasses network transport. No VPN, agent, SSH, or tunnel code was added.

## 14. DirectTransport Architecture

Initial registry validation resolves all A/AAAA answers. Immediately before each driver connection, DirectTransport re-resolves and validates every candidate, then supplies one validated numeric address. PostgreSQL sends original `host` plus pinned `hostaddr` so libpq verifies the hostname without a second DNS lookup ([PostgreSQL libpq documentation](https://www.postgresql.org/docs/current/libpq-connect.html)). ClickHouse uses a numeric address with original `server_hostname` and hostname checking ([clickhouse-driver API](https://clickhouse-driver.readthedocs.io/en/latest/api.html)). No application code claims a fixed public egress IP.

## 15. Destination Policy

One `shared.security.destination_policy` applies to Connector test/discovery/snapshot and Extractor connection. It rejects non-global IPv4/IPv6, loopback, link-local, private, CGNAT, unspecified, multicast, cloud metadata and mixed allowed/forbidden DNS results. An explicit CIDR exception is allowed in test/development; production direct mode does not honor private CIDR overrides. Host and port are mandatory; port range is 1–65535. DNS work has a three-second wait and four bounded worker slots. Network egress ACL/firewall and customer allowlisted BIAVORA egress remain deployment requirements.

## 16. DNS Rebinding Containment

Deterministic tests make initial DNS public then pre-connect DNS loopback; the driver is not called. The destination actually used by production-supported PostgreSQL/ClickHouse is pinned to a validated IP. A bounded resolver thread can remain running after caller timeout; four slots cap concurrent stalled lookups. Production MySQL/MariaDB/MSSQL/Oracle direct use is blocked until IP pinning **and** original-host TLS verification are proven together. BIA-018 remains partial pending C4 live/network evidence.

## 17. TLS Policy

Production PostgreSQL requires `verify-full`, disables GSS encryption substitution, and uses original host for certificate identity. Production ClickHouse requires `secure=true`, `verify=true`, `check_hostname=true`, and original `server_hostname`. Drivers that cannot safely preserve both pinning and hostname verification are blocked in production direct mode. The disposable local PostgreSQL image did not support SSL; its focused test used `APP_ENV=test`, an explicit loopback CIDR, and `sslmode=disable`, so it is **not** TLS certification. Customer CA/trust material must be deployment managed; no CA material was invented.

## 18. Engine Support Matrix

| Engine | C3 credential/ref contract | Direct production security | C3 live | Status |
|---|---|---|---|---|
| PostgreSQL | Yes | Pinned `hostaddr` + `verify-full` contract | Local non-TLS disposable source | Pending C4 verified-TLS/full pipeline. |
| MySQL | Yes | Blocked: pinned IP loses proven hostname validation | No C3 live | P1/P1-R snapshot retained in test/development. |
| MariaDB | Yes | Same block as MySQL | No C3 live | Prior P1-R live snapshot; no C3 promotion. |
| ClickHouse source | Yes | Pinned IP + `server_hostname` contract | No C3 live | Pending C4 verified-TLS/full pipeline. |
| SQLite | File token, no reusable DB password | Not applicable | No C3 live | Existing upload/snapshot contract unchanged. |
| MSSQL | Yes | Blocked until pinned TLS host validation proved | No C3 live | P1 contract-only here. |
| Oracle | Yes | Blocked until pinned TCPS host validation proved | No C3 live | P1 contract-only here. |

Production capabilities suppress connection/discovery/snapshot claims for the blocked network engines. There is no CDC claim.

## 19. Connection Test Flow

Authenticated manager → active source → Integration grant → Connector scoped resolution → central DirectTransport → engine test. An existing source rejects client host/password/configuration overrides. Connector has existing bounded HTTP rate middleware; Query scope blocks anonymous/non-manager attempts. Distributed rate enforcement remains C4/pre-staging work.

## 20. Discovery Flow

The same active-source grant/resolution/transport path is used. Client may supply only schema/table selectors. Connector owns actual discovery and validates table existence on snapshot. Discovery result size is still the existing P1 contract; C4 should measure/bound large catalogs.

## 21. Snapshot Flow

Query creates a new dataset without deleting prior datasets, binds a source/credential/configuration grant to its job/dataset, then dispatches an opaque ref. Connector validates selected tables against discovery and publishes v2. Extractor resolves the same frozen grant and uses its exact engine/config/credential. Loader and ClickHouse binding are unchanged. SQLite retains its private prepared-token path and no DirectTransport. Live Kafka/ClickHouse/preview proof remains pending.

## 22. Source Configuration Replacement

`PATCH /sources/{id}/` now handles display name, table selection, and active/disabled state only. Host/database/username/engine cannot be silently edited there; credentials have separate configure/rotate/revoke operations. `POST /sources/{id}/replacement/` accepts a candidate engine, non-secret metadata, tables, and new credential; candidate test must pass before it becomes validated.

## 23. Staged Cutover / Rollback

`replacement_id` snapshot uses candidate metadata and credential without touching the active source. Cutover requires its dataset to reach `completed`, then updates source configuration/version and active credential in one transaction. The candidate row becomes a 24-hour rollback point containing prior non-secret config and credential reference. Rollback atomically restores prior config and credential while incrementing the configuration version; imported datasets remain untouched. Failed test/load/cutover leaves the old active config. A later replacement requires expiry/pruning of the rollback point or explicit rollback. The current Query dataset completion projection is the cutover evidence; BIA-009 durable downstream completion remains a risk to verify in C4.

## 24. Workspace / Service Authorization

Public source operations derive manager/workspace from the authenticated principal; a foreign/disabled/retired source cannot authorize new execution. Internal resolution validates exact tenant/source/job/dataset/version and service name/key. Revoked credentials cannot resolve. Source retirement does not delete linked datasets. Physical database role separation is still C4.

## 25. Migrations

`integration.0002` adds credential/execution/candidate tables plus transport/config version; `integration.0003` adds retention timestamps. Both are additive. A disposable PostgreSQL database ran C1/C2 plus C3 forward → reverse → reapply, preserving source UUID, dataset ID, workspace ID, and empty credential tables for old rows. No plaintext or fake credential migration exists. The container was stopped/removed. Django drift check passed.

## 26. Frontend Changes

The existing DatabaseManagement UI now creates a source with one-time password entry, tests/discovers/snapshots by source ID, clears password state, shows configured/unconfigured status, offers validated rotation, and exposes disable/retire actions. Existing source host/engine fields are read-only. SQLite upload and dataset selection remain. No credential ID/ciphertext/password is rendered from a stored source. The staged destination replacement API has no dedicated frontend workflow yet.

## 27. P1 Regression

Shared connector/security/credential tests: 62 passed in the earlier combined run and 25 focused direct/client tests passed after DNS timeout, invalid-port, missing-key, and ClickHouse pin/TLS additions. Connector Django suite: 144 passed. Full Extractor engine suite: 225 passed, 5 skipped, including the final three v2 downgrade/resolution tests. P1 source registry retains PostgreSQL, MySQL, MariaDB, ClickHouse, SQLite, MSSQL, Oracle; only PostgreSQL received a new disposable real-source run. P1-R historical live MariaDB evidence is preserved, not falsely repeated here.

## 28. Foundation-C C1/C2 Regression

Integration ORM: 12 passed (source/dataset separation, workspace isolation, non-destructive import, rotation, resolver, replacement/rollback, retention). Query pytest: 114 passed. C1/C2 migration forward/reverse/reapply repeated with C3. `integration_source_id` and legacy dataset `source_id` remain distinct. Public dataset physical IDs remain hidden.

## 29. Foundation-A Regression

Query pytest 114 passed, including dataset/table allowlist, resource policy, and workspace scope. Voice Query/fail-closed focused suite: 13 passed plus 5 subtests. No analytical execution authority moved from Query; prior Foundation-A live evidence remains the baseline, not rerun.

## 30. Foundation-B Regression

Shared secret/upload/audio tests: 28 passed. Subscription payment tests: 11 passed. Connector upload tests are included in the 144-test full app suite. New resolver key is included in production weak-secret validation; changed-source Gitleaks scan passed. Prior ClamAV/payment/voice live drills were not repeated. Ignored user-owned local `.env` and backup files were untouched.

## 31. Focused Runtime Verification

Docker daemon and cached PostgreSQL image available. Query, Connector, and Extractor images built. Disposable PostgreSQL migration container and a separate source container were created and stopped. The source check proved real connector test, schema/table/PK discovery, two-row chunked read, and denied INSERT for a SELECT-only role. Stock container SSL was off; the first TLS-required attempt failed safely, then the explicit test-profile non-TLS exception passed. Service restart/API persistence, authenticated Gateway flow, Kafka v2 delivery, Extractor resolution in a running worker, ClickHouse load, Query preview, and live bad/good rotation were **NOT RUN** because the application stack was stopped. These are not claimed as C3 or C4 live passes.

## 32. Security Test Matrix

Passed automated checks: public secret/ciphertext/ref absence; wrong workspace/source/service; malformed ref/ciphertext; production missing-key failure; rotation failure preservation; successful version change; in-flight version binding; revoke invalidates superseded grants; 24-hour pruning; source retire preserves datasets; candidate cutover/rollback; IPv4/IPv6 forbidden/public/mixed DNS; DNS rebind before connect; invalid ports; unsupported transport/production engine; PostgreSQL and ClickHouse pin/TLS driver kwargs; no password/ciphertext in v2 event; v2 missing-ref/mismatch rejection and resolved configuration use; v1 compatibility. Residual: production CA/hostname live probe, egress ACL, distributed abuse controls, full workload identity, and Kafka replay with real infrastructure.

## 33. Files Changed

Created generic shared credential crypto; Integration credential service/internal resolver/management command and migrations; ETL credential client, transport and tests; C3 direct-source verification script; this report. Modified Query source/snapshot APIs, Integration model/metadata/views/service/tests, Connector/Extractor event paths, destination policy/engine adapters, frontend source page/endpoints, Compose/Dockerfiles/requirements/settings, and shared secret validation. C1/C2 files remain uncommitted and preserved. No file deletion or TimesFM change.

## 34. C4 Remaining Work

Physical Integration/Query/Auth/Workspace/Entitlement roles and schemas; denied cross-owner writes; deployment-managed key/resolver identities; TLS CA and real public egress; full two-workspace source lifecycle and Kafka/ClickHouse/Query preview; all source engines honestly certified or blocked; rate/abuse/security/secret scans and operational release gate; final BIA-005/008/014/018/030 reconciliation. Query direct ClickHouse cleanup, Notification foreign ORM reads, and BIA-009 durable jobs remain separate tracked debt.

## 35. Deferred PrivateNetwork / Agent

Only a transport discriminator and explicit unavailable error exist. PrivateNetworkTransport, AgentTransport, VPN, SSH, tunnels, customer agents, and CDC were **not implemented**.

## 36. Known Limitations

The C3 secret store is encrypted PostgreSQL plus deployment-supplied key, not a deployed managed secrets service/KMS; Compose still injects secrets as environment variables. Resolver key is shared by two ETL workloads until C4 workload identities. Grants expire after 24 hours; expired retries require a new attempt. The pruning command requires a deployment scheduler. DNS timeout bounds caller wait and concurrency, not an already running OS resolver thread. MySQL/MariaDB/MSSQL/Oracle direct production are blocked. Source replacement has API support but no dedicated frontend flow. Full stack and verified TLS live tests remain pending.

## 37. Final C3 Status

**PARTIAL**. C3 implementation has strong focused automated, migration, image-build, and disposable PostgreSQL direct-read evidence. It lacks full live event/data path and production TLS/identity/managed-secret/egress proof. Foundation-C overall remains **PARTIAL** pending C4. No CDC, private-network, or agent implementation; no commit or push.
