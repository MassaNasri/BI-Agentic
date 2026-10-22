# 42 — Foundation-C C6 hard-gate closure report

Date: 2026-10-20. Branch: `main`. Entry HEAD: `9298d2f25425f880cb56ccdeb2036e65f83f1bcb`. This is an uncommitted working-tree assessment. TimesFM was already dirty and was not touched.

## 1. Executive Summary

**Foundation-C final: BLOCKED_EXTERNAL.** C6 closed the locally actionable restricted-role lifecycle and public physical-binding defects. The user confirmed that no staging infrastructure exists. Canonical `33` requires a managed KMS/secrets manager and separate deployed workload identities before staging; `29` and `30` require the initial production direct source path to use verified TLS and controlled public egress. Neither deployed proof can be inferred from the isolated local stack. No GREEN or remote-CI claim is made.

## 2. Entry State

Report `41` entered with Foundation-C PARTIAL; BIA-005/008/018/030 PARTIAL, BIA-014 CLOSED, Kafka v1 TRANSITIONAL. C1–C5 were uncommitted. Entry branch/HEAD and status, diff/stat/name-status, staged diff, and submodule status were captured before C6 edits. No add, commit, push, reset, clean, history rewrite, user database/volume deletion, or TimesFM edit occurred.

## 3. Documents Read

Read `34`, canonical `29`–`33`, problem register `20`, roadmap `25`, build plan `26`, Foundation-A/B reports `36`/`37`, and Foundation-C reports `38`–`41`; inspected actual URL resolvers, Gateway routing, settings, Compose, migrations, tests, CI and Git state.

## 4. Canonical Closure Interpretation

`20` defines BIA-005 acceptance as owner map/schemas, least-privilege roles, denied cross-domain writes, and reversible migrations. BIA-018 is specifically the DNS-rebinding defect; deployed public egress remains a separate mandatory Foundation-C architecture/security gate under `29`/`30`/`33`. BIA-030 concerns public physical ClickHouse identifiers. `33` expressly requires a real managed secret store and separate workload identities; a mounted-file consumer alone is insufficient. Kafka v1 may remain a bounded, default-off reader, but production backlog/drain must be attested at cutover. Remote CI requires a future reviewed commit and push.

## 5. C6 Scope

Work stayed within restricted ownership, secret/identity evidence, direct transport evidence, public contracts/two-workspace isolation, Kafka v1/v2, and local release gates. No Foundation-D, CDC, durable-jobs, Semantic Layer, RAG, agent, private-network, or agent transport work was started.

## 6. BIA-005 Restricted Runtime

The isolated stack used five actual PostgreSQL runtime roles for Auth, Workspace, Integration, Query and Entitlement. Query used a distinct Integration connection. No broad shared application login was used; the migration principal was separately flagged. `django_migrations` now grants runtime roles read-only startup visibility. Auth's two SimpleJWT blacklist tables were added to its owner map after live login exposed missing grants.

## 7. Full Restricted-Role E2E

With those roles, actual public Gateway signup created two managers/workspaces; login, source create/configure/test/discover/snapshot, Connector → Kafka v2 → Extractor → Transformer → Loader → ClickHouse, two-row preview and analytical count all passed. Query/Connector/Extractor restarted; persisted credentials supported test/discover/another snapshot without password resubmission. Bad rotation failed; valid rotation, revoke denial, reconfigure, replacement candidate snapshot, cutover, rollback, retire, and prior-dataset preview passed. This was a **development-profile private-network/non-TLS source** for the ETL path, not a production direct-transport proof.

## 8. Production-Profile Upgrade

A fresh disposable PostgreSQL database ran Auth, Workspace, Subscription and Query migrations under `APP_ENV=production`, `DB_ACCESS_MODE=migration` and the explicit migration flag. Integration `0001`–`0004` and `database.0006` ran. Query's Integration migration router now uses the single default migration recorder while in migration mode, fixing a fresh-production migration failure. A separate historical `database.0005` upgrade fixture passed forward/reverse/reapply without reconstructing a password.

## 9. Ownership Rollback

After the full live lifecycle, the five app services were stopped. The owner journal reversed from 18 entries to zero; production-profile Query reconnected under the compatible migration principal and read source/dataset HTTP routes. User/workspace/source UUID, credential ciphertext/version, dataset/source relationships, subscription rows, Django migration count, and identity sequence fingerprints were unchanged. Owner reapply restored 18 journal entries; role grants were refreshed, five app services reached healthy, and Gateway two-row preview/schema/query passed again. This proves the disposable rollback, not an unperformed production cutover.

## 10. Cross-Owner Runtime Denials

The C5 actual-role probe and refreshed C6 owner fixture established each role's own CRUD and PostgreSQL-denied foreign INSERT/UPDATE/DELETE, including Integration ↔ Query/Auth/Workspace and Entitlement foreign critical domains. Runtime role identities and search paths were checked internally; no role name appears in a public API. The isolated live application concurrently used those credentials.

## 11. BIA-008 Managed Secret Requirement

Canonical `33` says KMS/secrets manager and a managed secret store with separate staging/production workload identities. No product/provider has been selected and the user confirms no staging infrastructure. **BLOCKED_EXTERNAL** for managed-store and workload-binding evidence; no arbitrary cloud provider was added.

## 12. Secret Provider / Delivery

C5's provider-neutral protected mount consumer, versioned encryption-key contract and fail-closed startup tests remain. C6's isolated stack used synthetic environment values solely for local role/ETL evidence. It is not a managed-secret proof and no inline production secret was accepted as such.

## 13. Workload Identity

Connector and Extractor retain distinct scoped resolver credentials; the browser/Gateway has no resolver route, and the resolver checks service plus grant/workspace/source/job/dataset/version. These are application authentication contracts. Platform-issued, identity-bound secret access remains **BLOCKED_EXTERNAL**.

## 14. Identity Rotation

Maintained tests cover current/previous identity overlap, cross-service impersonation denial, and retired identity rejection. No platform-issued identity rotation or managed-store policy binding could be rehearsed without staging.

## 15. Encryption Key Rotation/Rewrap

Maintained C5 tests cover active N → N+1, new encryption, retained-ciphertext rewrap, denied early retirement, and old-key retirement after rewrap. C6's live password rotation/revoke/reconfigure passed after restart. A managed-store-backed rolling rotation remains **BLOCKED_EXTERNAL**.

## 16. Restart Evidence

Query/Integration, Connector and Extractor restarted in the isolated stack. Source and credential metadata persisted; credential resolution, test/discover/snapshot and two-row Query result worked without browser password resubmission. Kafka source events contained opaque refs and no password/ciphertext. This is local synthetic secret delivery, not a managed-secret restart.

## 17. BIA-018 Production Direct Requirement

Production policy still rejects private/loopback/non-global destinations and unsafe engines; no localhost/CIDR exception, `verify=false`, TLS downgrade or hostname bypass was added. DirectSecureInternetTransport requires safe DNS/IP, pre-connect revalidation/pinning, verified TLS, egress policy, bounded connections/timeouts and read-only source privileges.

## 18. Full PostgreSQL TLS ETL

Separate C4 disposable PostgreSQL and ClickHouse TLS fixtures proved trusted CA/hostname and wrong-hostname/untrusted-CA/insecure-mode rejection. C6's complete Gateway → ETL → Query path used a private, non-TLS PostgreSQL source under an explicit development ETL policy. **The combined production-policy, verify-full, public TLS ETL path remains UNPROVEN/BLOCKED_EXTERNAL.** The local source account denied INSERT.

## 19. Public Egress Evidence

There is no controlled public source, stable BIAVORA egress, customer/source allowlist, public-route observation or staging network log. Docker bridge networking is not public egress. The user confirmed staging does not yet exist.

## 20. DNS/Pinning/Rebinding

Deterministic destination-policy tests cover initial resolution, pre-connect re-resolution, mixed/private answer denial and driver pinning; separate PostgreSQL/ClickHouse TLS fixtures passed earlier. The **BIA-018 DNS-rebinding code defect is CLOSED** against its narrow canonical title. Public-network deployment acceptance remains blocked as a distinct Foundation-C hard gate.

## 21. Engine Matrix

| Engine | C6/local result | Production direct status |
|---|---|---|
| PostgreSQL | Full private development E2E; separate verify-full fixture | Public TLS/egress acceptance blocked externally |
| ClickHouse source | Separate native TLS/hostname fixture | Full source snapshot over public egress unproved |
| MySQL/MariaDB/MSSQL/Oracle | Deterministic safety guards | Production direct blocked pending safe pin/hostname verification |
| SQLite | Local guarded file preparation | Not a public network transport |

## 22. BIA-030 Public Route Inventory

`scripts/verify_foundation_c6_public_routes.py` traverses registered Django URL resolvers and actual Gateway mapping, with a documented AST fallback for AI's unavailable local Whisper import. Reviewed JSON inventory covers Auth 18, Workspace 20, Query/Integration 27, Subscription 14, Voice 21, AI 8, Report 18, Visualization 9, Notification 6 and Gateway 3 routes (144 total). Each is PUBLIC, INTERNAL_ONLY, ADMIN_ONLY, DEPRECATED or UNREACHABLE. Compose binds direct service ports to localhost; Gateway is the public routing boundary. CI fails on new/unclassified routes.

## 23. Public Payload Audit

Query source/dataset serializers omit physical table/database, file path, credential UUID/ref, ciphertext and key version; status messages are generic. Static review traced Voice, Report and Visualization routes and their authoritative Query/definition references. Gateway now rejects forbidden metadata keys and internal diagnostic strings in **all** upstream JSON, including successful responses; it replaces raw 5xx and unsafe/non-JSON 4xx with generic errors and drops internal headers/absolute redirects. Authorized analytical row values remain data, not metadata.

## 24. SQL/Error Audit

Live Query execution initially exposed its internal ClickHouse table in the visible `sql` field. `query_api/public_sql.py` now rewrites authorized physical table/qualifier AST nodes to logical source schema/name at the HTTP boundary while execution still uses the physical binding. Live count remained two and the physical name disappeared. Final review found the same gap in the public authorized-visualization-definition response; it now uses the same logical renderer and has a focused endpoint test. Query success/error, timeout, authorization, preview/schema, Voice Query contract, Report SQL normalization and Visualization definition paths were reviewed with maintained tests. Gateway also fails closed if any upstream success/error JSON contains the known physical binding pattern or an internal diagnostic. No blanket removal of legitimate analytical SQL was made.

## 25. Live Two-Workspace Matrix

Manager A owned source/dataset; manager B's actual Gateway token saw an empty source/dataset list and denial on source get/patch/retire, credential configure/rotate/revoke, test/discover/snapshot, replacement create/test/discover/snapshot/cutover/rollback, dataset detail/delete/preview/schema, query execute/validate/definition creation: **24 distinct route cases**. Dataset status uses the same scoped detail route. Responses contained no source password, internal host or physical binding. A retained completed datasets through cutover, rollback and source retirement.

## 26. Internal Resolver Audit

Gateway has no resolver mapping and blocks other internal Workspace/Notification routes. Browser JWT cannot authorize the direct resolver. Maintained scoped-resolver tests deny wrong Connector/Extractor identity, workspace, source, dataset, job, credential version, revoked grant and expired grant. C6 did not expose the internal Query port publicly.

## 27. Kafka V1 Global Producer Audit

Repository producer search found the governed Query → Connector v2 source publisher and the Connector's old database-publish path. In production the latter returns 410 before Kafka; raw snapshot lacking `credential_ref` returns 403. File ingestion is separate. A new Connector regression tests both production paths. No active production source DB publisher can create a password/ciphertext v1 event in the reviewed tree.

## 28. Kafka V1 Drain/Cutover

Production v1 reader is default OFF; opt-in replay requires an explicit deadline no more than seven days away. Isolated `load_requests` topic had no dynamic retention override and its consumer group showed offset 5/5, lag zero; all four original source events were v2, followed by one controlled v2 replay. **This is not staging/production backlog attestation.** At deployment T0 keep v1 producer disabled; inventory actual topic retention and oldest offsets, set a short approved replay deadline only if necessary, attest v1 backlog drained/expired, then remove the opt-in. Never truncate user topics.

## 29. Kafka V2 Replay

The disposable topic's source events contained `contract_version=2` and opaque credential refs, with no password or ciphertext. One exact event was replayed; the source/config/credential identity tuple stayed fixed and the existing dataset still had two rows. Maintained resolver tests reject tenant/version mismatch. This proves the current idempotent outcome for this replay, not a redesign of BIA-009 durable jobs.

## 30. Failure Drills

Local evidence covers bad source password/rotation, revoked credential, foreign tenant, wrong resolver identity/scope, missing/weak mount, early key retirement, source write denial, unsafe DNS and TLS hostname/CA/insecure settings. Gateway hides upstream 5xx and unsafe 4xx. Kafka or ClickHouse outage under load and staged public network observation were not manufactured in this pass.

## 31. Credential Pruning

C4/C5 maintained tests retain current, pending and rollback-window credentials and deny premature key/identity retirement. C6 lifecycle preserved ciphertext/version fingerprints through owner rollback. No live managed-store prune window was available.

## 32. Migration Verification

Fresh production-profile migrations, historical upgrade-like forward/reverse/reapply, Integration `0001`–`0004`, `database.0006`, owner apply/rollback/reapply, eight-service drift and data/sequence fingerprints passed on disposable PostgreSQL. There is no new C6 migration and no password backfill or duplicate source authority.

## 33. Foundation-C Final E2E

The isolated stack completed the source and credential lifecycle, Kafka v2, ETL, ClickHouse, Gateway two-row Query, restart and owner rollback/reapply under restricted roles. Its secret delivery and source transport were synthetic/local. Final production-representative staging acceptance is **BLOCKED_EXTERNAL**.

## 34. Foundation-A Regression

BIA-001/BIA-002/BIA-010 remain closed. Query's 117 tests and Voice's 27 passed; the live analytical count and foreign Query denial passed. Query remains the analytical authority and resource/Voice fail-closed tests remain in the required workflow.

## 35. Foundation-B Regression

BIA-003/BIA-006/BIA-011 remain closed. Auth 2, Workspace 4, Subscription 11, Notification 4, shared upload/secret/readiness tests, and current-source pinned Gitleaks passed. No production payment mode or historical-secret reclassification occurred.

## 36. Frontend

19 tests, lint, production build and bundle policy passed. Existing source/dataset UX remained. Build emitted only advisory bundle/browser-data warnings.

## 37. Static/Docker/Compose

Static gate compiled 800 maintained Python files with no merge marker. Base and isolated Compose configuration passed. Changed Query/ETL images were rebuilt for the live stack; the final Gateway image rebuilt after its last filter edit. C5's full maintained-image build remains the base full-build evidence. `git diff --check` passed (Windows emitted only LF/CRLF notices).

## 38. CI Workflow

Nine mandatory jobs remain: current-tree secret scan, static/Compose, frontend, backend/AI (including route inventory), ETL, security regression, migration drift, Docker build and owner boundary. `release-gate` requires all nine. The owner job now rehearses fresh production-profile migrations before owner cutover and rollback. The workflow has not run remotely on the uncommitted C6 tree.

## 39. Local CI-Equivalent Results

Maintained results on this tree: Query 117, Integration 20, Gateway 8, Visualization 63, Voice 27, Report 5, AI 238, Auth 2, Workspace 4, Subscription 11, Notification 4, Connector 145, Extractor 225 with 5 skipped, ETL shared models/security 359, 22 ETL utility files individually (their counts overlap no other listed utility suite), Transformer 12/1 skipped, Loader 14/1 skipped, listener 7, Detector 4, Metadata 4, frontend 19/lint/build/bundle. Shared readiness/upload/secret batch 37/1 skipped; owner fixture, C5 actual-role probe, TLS/pinning, migration/drift, route inventory, Compose, static, changed-image build and live Gateway/ETL passed. Counts describe separate commands; they are not summed as a unique grand total.

## 40. Secret/Artifact Scan

Pinned Gitleaks scanned a disposable snapshot of 5,750 current tracked/new source files with redaction and passed. Ignored user `.env`, source databases, runtime volumes and pre-existing TimesFM were excluded. The snapshot and isolated stack/volumes/database/network were removed after verification. No secret values, cert private keys, dumps, Kafka/ClickHouse data or runtime logs belong to the source diff.

## 41. Files Changed

C6: production migration routing; owner Auth token/recorder grants and CI upgrade rehearsal; Gateway internal routing and all-service public response filter; registered route inventory; Query visible-SQL logicalization/tests; production legacy producer test; four ETL Docker/build dependency fixes and Kafka client pin; this report and execution-state documents. Earlier C1–C5 uncommitted changes remain. No intentional source deletion or TimesFM change.

## 42. External User Actions

**USER_ACTION_REQUIRED / BLOCKED_EXTERNAL.** Provision an approved staging managed KMS/secrets manager with staging-only versioned keys, Connector/Extractor identities bound to separate secret access, runtime DB credentials and trusted CA material. Provide deployment location and a safe access/run procedure, never secret values. Provide stable BIAVORA egress IP(s), a controlled publicly routed TLS PostgreSQL source with DNS name matching its certificate, allowlisted egress, read-only source role, trusted CA and network/audit logs. Then run the same Gateway source lifecycle under production destination policy, wrong-hostname/CA/TLS/rebinding drills, managed-key/identity rotation and restart; PASS means two-row ETL/Query, no secret/event leak, rejected invalid paths and preserved datasets. Inspect actual staging Kafka topic retention/offsets and attest v1 drain before removing compatibility. Clean up only operator-approved staging fixtures after evidence capture. No random third-party database or insecure public database is acceptable.

## 43. Out-of-Scope Debt

BIA-009 durable jobs; Semantic Layer; AI/RAG/agents; Notification foreign ORM reads; Query direct physical cleanup; further engine certification; paid provider/operations; dedicated replacement UI; CDC; PrivateNetworkTransport; AgentTransport remain separately tracked. They are not new C6 blockers.

## 44. Final Issue Matrix

| Issue | Entry → final | C6 basis / residual owner |
|---|---|---|
| BIA-005 | PARTIAL → **CLOSED (local canonical defect)** | Full role-bound lifecycle, denied foreign writes, production migration and live rollback/reapply passed; deployment rehearsal belongs to staging operator. |
| BIA-008 | PARTIAL → **PARTIAL / BLOCKED_EXTERNAL** | Source/credential code and local lifecycle pass; managed store and deployed identity binding absent. |
| BIA-014 | CLOSED → **CLOSED** | Non-destructive candidate snapshot/cutover/rollback and retained datasets pass live. |
| BIA-018 | PARTIAL → **CLOSED (DNS defect)** | Deterministic pre-connect pinning/rebinding and TLS fixtures pass; separate public direct-transport gate remains external. |
| BIA-030 | PARTIAL → **CLOSED (local canonical defect)** | All registered routes classified; physical SQL leak fixed; Gateway metadata/diagnostic filter and 24-case live tenant matrix pass. |
| Kafka v1 | TRANSITIONAL → **TRANSITIONAL** | No active production v1 producer; reader default off/short deadline; staging drain unknown. |

## 45. Final Hard Gate Matrix

| Gate | Decision |
|---|---|
| Restricted-role full lifecycle and reversible owner migration | PASS locally |
| Source/credential lifecycle, two-workspace public contract, Kafka v2 | PASS locally |
| Deterministic local release checks and current-source scan | PASS for executed gates; remote CI pending |
| Managed store plus deployed distinct workload identities | BLOCKED_EXTERNAL |
| Public egress plus combined production-policy full TLS ETL | BLOCKED_EXTERNAL |
| Actual staging Kafka v1 backlog/drain attestation | BLOCKED_EXTERNAL |
| Authoritative remote CI on reviewed commit | PENDING_COMMIT_AND_PUSH |

## 46. Foundation-C Decision

**LOCAL ENGINEERING: PASS for the exercised deterministic and isolated runtime gates. RELEASE CANDIDATE: NOT READY. FINAL: BLOCKED_EXTERNAL.** The user has no staging infrastructure; mandatory managed-secret/identity and public TLS/egress gates cannot be shown. This decision does not treat the private Docker network as production evidence and does not claim remote CI passed.

## 47. Exact Next Action

Provision the controlled Foundation-C staging environment specified in §42 and provide its location plus a safe access procedure (without sending secret values), so the external hard-gate probes can run.
