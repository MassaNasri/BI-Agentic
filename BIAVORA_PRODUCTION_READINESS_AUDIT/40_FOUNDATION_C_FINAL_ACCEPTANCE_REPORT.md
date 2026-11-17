# 40 — Foundation-C final acceptance report

Date: 2026-10-19. Decision: **PARTIAL**. This is a C4 implementation and local acceptance record, not a production release attestation.

## 1. Executive Summary

The disposable Gateway → Integration/Query → Connector → Kafka v2 → Extractor → Transformer → Loader → ClickHouse → Query path loaded and analytically returned controlled PostgreSQL rows. Restart persistence, credential rotation, candidate discovery/snapshot/cutover/rollback, revocation, retirement, and selected cross-workspace denials passed. PostgreSQL and ClickHouse each passed separate disposable TLS hostname/CA failure fixtures. Physical owner-role denial passed on a fresh disposable PostgreSQL database. These proofs materially advance C4 but do not establish deployed least-privilege roles, managed key/workload delivery, production public egress/TLS, or a complete public-route and release gate.

## 2. Final Foundation-C Decision

**PARTIAL**, with mandatory physical ownership and production security/deployment gates open. No Foundation-C GREEN or production-direct certification is claimed from local Compose.

## 3. Git/Baseline State

Branch `main`; entry HEAD `9298d2f25425f880cb56ccdeb2036e65f83f1bcb`. C1/C2/C3 were uncommitted at entry. `services/ai-service/forecasting/timesfm` was already dirty and was not edited, staged, or updated. No commit or push. User-owned `.env`, backups, Kafka and ClickHouse volumes were not edited or pruned. The C4 acceptance stack used the isolated Compose project `biavora_c4_disposable` and synthetic data.

## 4. Documents Read

`34` first, then canonical `29`–`33`, debt/roadmap/planning `20`, `25`, `26`, Foundation evidence `36`–`39`, and existing P1/P1-R architecture, matrix, implementation and remediation material. Later canonical v2 rules supersede older P1 encrypted-password-in-event behavior for new production snapshots.

## 5. Canonical Closure Matrix

| Issue/map | Entry | C4 evidence | Decision |
|---|---|---|---|
| BIA-005 / MAP-020 | PARTIAL | Reversible schema/role prototype; owner CRUD and foreign write denial on disposable PostgreSQL | **PARTIAL**: application roles/search paths are not deployed or exercised by production services. |
| BIA-008 / MAP-001, MAP-005, MAP-021 | PARTIAL | Live persistent source, scoped credential refs, rotation, revoke, ETL restart | **PARTIAL**: managed secret/workload delivery and production egress remain unproved. |
| BIA-014 | PARTIAL | Multiple sources/datasets; candidate test, discovery, snapshot, atomic cutover and rollback; datasets preserved | **CLOSED for the canonical source-replacement defect**. The dedicated replacement UI remains separate product work. |
| BIA-018 | PARTIAL | Deterministic DNS/pin tests; both TLS fixtures; unsupported engines fail closed | **PARTIAL**: production egress and real customer-network rebinding/TLS operation unproved. |
| BIA-030 / MAP-042 | PARTIAL | Public dataset serialization, preview, health, upload failure, source responses narrowed | **PARTIAL**: exhaustive public contract/proxy audit and production observation are outstanding. |
| MAP-040 | Transitional | New v2 events verified live without password/ciphertext | Transitional v1 replay remains; production emission cutover not deployed. |
| BIA-009 | Separate P0 debt | No durable-jobs changes | Outside this Foundation-C implementation; roadmap foundation gate still tracks it. |

## 6. Architecture After Foundation-C

Integration is a logical domain co-deployed with Query for source/configuration/credential lifecycle. Query alone owns dataset binding and analytical execution. Connector owns connection test/discovery/snapshot dispatch, Extractor reads sources, Transformer transforms, Loader writes ClickHouse. HTTP carries control, Kafka carries work/data. AI/Voice/Report/Visualization do not receive source credentials.

## 7. Logical Ownership

Source UUID, workspace, selected tables, non-secret metadata and lifecycle are Integration-owned; Query `Database` is a separate dataset. Legacy dataset-scoped ETL `source_id` remains distinct from `integration_source_id`. Multi-source and non-destructive imports are exercised.

## 8. Physical Ownership

`scripts/foundation_c4_owner_schemas.py` stages table moves and grants only after an explicit environment flag. It was **not applied to the user database**. The running disposable application used its existing broad PostgreSQL login; therefore this hard gate is **FAIL/UNPROVEN for deployment** despite the isolated role proof.

## 9. PostgreSQL Roles/Schemas/Grants

Prototype schemas: `biavora_auth`, `biavora_workspace`, `biavora_integration`, `biavora_query`, `biavora_entitlement`; paired NOLOGIN owner/app roles. Critical business tables, including `integration_source_operation_budgets`, are mapped. App roles receive own-schema CRUD and sequence usage. A journal records prior schema and owner for rollback. Actual service credentials, search paths, migration ownership, and any authorized cross-domain projections require deployment cutover.

## 10. Cross-Owner Denial Evidence

`BIAVORA_C4_DISPOSABLE=1 python scripts/verify_foundation_c4_owner_roles.py` passed on fresh PostgreSQL 18.3: each role SELECT/INSERT/UPDATE/DELETE on its own sample table; INSERT/UPDATE/DELETE denied against a foreign owner; rollback restored original schema and marker data. This is GRANT/REVOKE evidence, not proof that running services use these roles. Cross-domain reads: owner reads are granted; authorized projections need an explicit deployment grant; legacy Notification foreign ORM reads are adjacent debt; arbitrary foreign reads are not approved.

## 11. DataSource/Dataset Boundary

The live run produced separate source UUIDs and dataset IDs 1–6 in the disposable database. Source retirement denied new operations while completed datasets remained accessible. Query's public dataset serializer excludes ClickHouse database/table and internal ETL diagnostic text.

## 12. Credential Lifecycle

Source password configured once, encrypted/versioned at rest, never stored in public source metadata. A bad live rotation returned `CREDENTIAL_VALIDATION_FAILED` and preserved the active version. A good rotation activated a new version. Revoke returned success and blocked new test; retirement blocked new source operations. Grant scope includes workspace/source/job/dataset/version.

## 13. Credential Encryption/Key Delivery

Fernet/HKDF and key-version contracts from C3 remain. C4 validates production key strength/presence and supports deployment-provided CA paths. Local Compose supplied environment secrets; **no managed KMS/Vault injection, key rotation/rewrap rehearsal, or least-privilege production secret mount was available**. No key is stored in PostgreSQL.

## 14. Internal Credential Resolver/Auth

Connector and Extractor now use distinct service-scoped resolver keys; previous keys support controlled rotation. Production rejects absent/weak/colliding keys and has no shared-key fallback. Internal resolver still checks exact execution scope, and no Gateway route exposes it. Local scoped keys are a deployment contract, not deployed workload identity or mTLS proof.

## 15. Credential Pruning Scheduler

`credential-prune-worker` runs a bounded 60–86,400-second loop with restart policy and heartbeat. A live `--once` probe removed expired synthetic ciphertext, preserved an active credential and a recent rollback point. Worker health was `healthy`; logs showed counts only. The disposable worker's continued operation is not production scheduler proof.

## 16. ConnectionTransport

`ConnectionTransport` separates reachability from engine adapters. `direct_secure_internet` is the only implemented network mode. SQLite uses private staged files. PrivateNetworkTransport, AgentTransport, VPN and CDC were not added.

## 17. DirectSecureInternetTransport

Initial destination validation and pre-connect revalidation check all A/AAAA answers. PostgreSQL pins `hostaddr` while retaining original TLS hostname; ClickHouse pins numeric address with original `server_hostname`. Network engines lacking a proven pin/hostname contract are blocked in production direct mode.

## 18. Destination / SSRF Policy

Loopback, private/link-local, metadata, non-global and mixed DNS answers are denied in production. Test/development can explicitly allow a CIDR. The local end-to-end Compose run used that development exception for `c4-postgres`; it cannot prove public Internet egress ACLs.

## 19. DNS Rebinding Evidence

Maintained deterministic tests prove safe initial DNS followed by forbidden pre-connect DNS never calls the driver; supported drivers receive a validated pinned address. Resolver caller wait/concurrency are bounded, while an already started OS resolver thread can outlive its caller timeout. A live hostile DNS/network rebind drill against deployed egress was unavailable.

## 20. TLS Evidence

`verify_foundation_c4_tls.py` passed real PostgreSQL TLS with a disposable CA and `verify-full`: trusted hostname/read succeeded; wrong hostname, untrusted CA, `sslmode=disable`, and source-role INSERT were denied. `verify_foundation_c4_clickhouse_tls.py` passed native ClickHouse TLS with trusted hostname/read; wrong hostname, untrusted CA and `secure=false` were denied. Certificates and keys lived in auto-deleted temporary directories; disposable containers were stopped/removed. These were separate fixtures, not the full Gateway ETL run over TLS or deployed customer trust.

## 21. Production Egress Model

Direct source access assumes a defined BIAVORA public egress path that customers allowlist, with network ACL/firewall policy and observability. This repository implements destination checks but provides no deployed fixed public IP, NAT/firewall evidence, customer allowlist drill or production workload network identity. **BLOCKED_EXTERNAL**.

## 22. Engine Certification Matrix

| Engine | Registry/snapshot | Credential/transport | Historical live | C4 live | Production Direct |
|---|---|---|---|---|---|
| PostgreSQL | Yes | Versioned ref, pinned `hostaddr`, verify-full | P1/P1-R | Full local non-TLS ETL plus separate TLS fixture | Code/fixture proven; deployed egress/TLS unproved. |
| MySQL | Yes | Versioned ref; direct production blocked | P1/P1-R | No | Blocked: pin plus hostname proof. |
| MariaDB | Yes | Versioned ref; direct production blocked | P1-R | No | Blocked: pin plus hostname proof. |
| SQLite | Yes | Private file token; network transport N/A | Foundation-B | Regression only | Direct Internet N/A. |
| ClickHouse source | Yes | Versioned ref, pinned TLS hostname | P1/P1-R | Separate TLS source fixture; no C4 snapshot | Code/fixture proven; deployed egress/TLS unproved. |
| MSSQL | Yes | Versioned ref; direct production blocked | Contract | No | Blocked: pinned TLS identity proof. |
| Oracle | Yes | Versioned ref; direct production blocked | Contract | No | Blocked: pinned TCPS identity proof. |

Registry support, contract coverage, historical live evidence, C4 live evidence, and production readiness are distinct claims.

## 23. Kafka v2 Contract

Five actual isolated `load_requests` events (the `connection_topic` alias) for the test workspace were inspected. They contained `credential_ref` and no synthetic password, invalid candidate secret, or ciphertext marker. Connector and Extractor resolved grants separately. Extractor published two rows, Transformer published cleaned data, Loader inserted two rows, and Query executed a two-row aggregate.

## 24. Legacy v1 Cutover Status

v1 reader compatibility remains for existing replay; v2 is used by the new source flow. Production v1 publisher cutoff, topic-drain evidence, and replay-window audit were **not performed**. Rollback must never silently resume new password/ciphertext Kafka emission.

## 25. Full Live PostgreSQL E2E

Isolated project `biavora_c4_disposable`: all required services became healthy. Authenticated manager through Gateway created a source, tested and discovered it, selected `public.c4_sales_a`, dispatched snapshot, and observed Kafka/Extractor/Transformer/Loader/ClickHouse/Query completion. Preview reported two rows and `POST /query/execute/` returned `count()=2`. The source role had SELECT and no INSERT grant. This run used `APP_ENV=development`, a private CIDR exception and non-TLS source connection; the separate TLS fixtures are the TLS evidence.

## 26. Service Restart / Persistence

The isolated Query, Connector and Extractor containers were restarted. The same persisted source then passed test/discovery/snapshot, completed another dataset, previewed two rows and executed the same aggregate without password resubmission. This is local restart evidence, not backup/restore/PITR evidence.

## 27. Two-Workspace Security

Live Workspace B source get/test/snapshot returned 404 and Query execution against A's dataset returned 403. Unit/integration tests cover additional source scope and resolver mismatches. A complete live enumeration of every public source, replacement, dataset and internal resolver route from B was not recorded; the broader hard gate remains partial.

## 28. Credential Rotation

Bad candidate rejected, active credential unchanged; correct password candidate validated and activated. Subsequent tests succeeded. Prior credential retention is bounded by grant/rollback rules and pruning.

## 29. Credential Revocation

Live revoke removed usable active credential; subsequent test returned `CREDENTIAL_NOT_CONFIGURED`. Existing completed dataset metadata remained. No plaintext was returned.

## 30. Source Replacement/Cutover/Rollback

Live candidate for `public.c4_sales_b` passed test and the new candidate discovery action, snapshotted one row, and reached `completed`. Atomic cutover changed selected tables, candidate source tested, rollback restored A, A tested, and completed candidate/prior datasets remained. Failed candidate test left the old active source intact. Dedicated end-user replacement UI is not part of the canonical BIA-014 acceptance text; the maintained public API covers the operation.

## 31. Source/Dataset Delete Semantics

Retiring the live source denied new probes while a completed dataset detail remained available. Dataset deletion remains a separate Query operation. No user-owned dataset was deleted in this acceptance run.

## 32. Public API / BIA-030 Audit

Public source metadata contains no password or credential UUID; dataset serializers remove physical destination fields and mask internal ETL diagnostics. Preview and schema return logical table selectors; database health no longer returns the ETL URL; upload failure no longer echoes upstream text. Connector discovery errors use safe codes. Exhaustive Gateway/proxy and SQL echo review is still required before BIA-030 closure.

## 33. Rate/Abuse Controls

Manager/workspace authorization precedes network operations. PostgreSQL atomic per-actor/workspace/minute budgets bound test/discover (12), snapshot (6), rotate/replace (6); old budgets are pruned. Connector retains HTTP limits; DNS and discovery response work/size are bounded (100 schemas, 500 tables, 256 columns, 1 MiB). Full multi-worker load/abuse staging evidence is pending.

## 34. Failure Drills

Wrong source password, revoked credential, cross-workspace access, TLS hostname/CA/insecure mode, read-only source write, invalid candidate rotation, and candidate-not-ready cutover failed closed. Resolver missing scoped keys initially caused a safe 503 during the disposable run; test-only keys were supplied and the run recovered. Kafka/ClickHouse outage/recovery under load was not performed.

## 35. Secret/Log Leak Check

Relevant isolated Gateway, Query, Connector, Extractor, Transformer, Loader, Metadata and prune-worker logs were checked for known synthetic passwords, synthetic ciphertext markers, Authorization values and password fields: **NOT FOUND** in each scanned service. No real secret value was printed. The pinned redacted Gitleaks directory scan of 5,715 current tracked/new source files passed (exit 0); the source-only scan excluded the ignored local `.env` and runtime artifacts. These are marker/current-tree scans, not universal historical/provider proofs.

## 36. Migration Verification

Disposable PostgreSQL forward/reverse/reapply passed for `integration.0001`–`.0004` and `database.0006`, preserving legacy dataset/source IDs and avoiding fake credential backfill. Fresh isolated service databases applied Auth, Workspace, Subscription and Query migrations. Query `makemigrations --check --dry-run` found no changes. Physical-owner schema migration separately passed apply/rollback on sample data; no production DB was migrated to those roles.

## 37. Rollback Procedure

1. Freeze new source operations and record active source/configuration/credential versions; preserve completed datasets and both current/previous decryption keys.
2. Drain or expire v2 grants and Kafka work before changing resolver keys. Keep the v2 reader during rollback; do not re-enable new plaintext/ciphertext-in-event production writes. Restore previous scoped resolver key only within its overlap window.
3. Roll application images to a version that understands persisted source/dataset links and v2 references; verify Query analytical binding and ETL read-only behavior. If a version lacks that contract, block new ingestion while old datasets remain queryable.
4. Revert `integration.0004`, then credential/candidate migrations only after no live grants/rollback points rely on them. Reverse `database.0006` only after verifying source UUID/dataset links and a backup; never synthesize passwords for legacy rows.
5. If owner schemas/roles were applied, restore service login/search paths first, run the journaled `foundation_c4_owner_schemas.py rollback`, verify row counts/owners/grants, and only then retire replacement roles. No grant revocation precedes a working replacement login.
6. Stop the prune worker during rollback and restart only when retained grants and rollback windows are verified. Revoke compromised credentials explicitly rather than reactivating ciphertext. Validate representative source and Query reads after each stage.

Security-sensitive operations (explicit credential revocation, expired ciphertext pruning, production v1 publisher cutoff) are not undone automatically.

## 38. P1/P1-R Regression

Connector registry and legacy snapshot adapters remain. Connector Django: 144 passed. Extractor: 225 passed, 5 skipped. Transformer: 12 passed, 1 skipped. Loader: 14 passed, 1 skipped. ETL pipeline listener: 7 passed. Shared ETL models/security: 358 passed; all 22 maintained shared utility test files passed individually in the CI style. Focused direct/connector tests after the CA change: 51 passed. Historical P1-R MariaDB live result was not repeated or promoted to production direct support.

## 39. Foundation-A Regression

Query pytest: 114 passed. Live authorized aggregate and cross-workspace denial passed. Voice maintained boundary tests: 27 passed; previous Foundation-A resource/cancel live evidence in report `36` was not re-run in this C4 stack.

## 40. Foundation-B Regression

Shared readiness/secrets/upload/audio: 34 passed. Subscription: 11 passed. Auth/Workspace invitation: 2/4 passed. Local synthetic log marker scan passed. Existing Foundation-B ClamAV/upload and payment live evidence in report `37` remains; current C4 did not repeat every Voice/upload/payment drill.

## 41. Frontend

19 tests passed; ESLint passed; Vite production build and bundle policy passed. Build emitted advisory stale browser-data and bundle-size warnings. Current UI supports source create/test/discover/snapshot, rotation, disable/retire, file import and dataset selection. Replacement remains a managed public API, with no dedicated UI.

## 42. Static / Docker / Compose / CI

Python/static gate compiled 787 maintained files and found no merge markers. Query/Connector Django checks passed. Compose config passed. The full local Docker Compose build passed for every maintained image, including Report and Visualization. CI release-gate now needs the owner-boundary job alongside secret scan, static, frontend, backend/AI, ETL, security, migration drift and image build. Pinned redacted current-source Gitleaks passed locally. Remote CI execution result is not claimed.

## 43. Full Test Matrix

| Area | C4 local result |
|---|---|
| Auth / Workspace / Subscription / Notification / Gateway | 2 / 4 / 11 / 4 / 2 passed |
| Query / Integration | 114 pytest / 16 Django passed |
| Voice / AI / Report | 27 / 238 / 5 passed |
| Connector / Extractor / Transformer / Loader | 144 / 225 / 12 / 14 passed, with 5 / 1 / 1 ETL skips |
| ETL shared models/security / utility files / listener / Detector / Metadata | 358 / 22 files passed / 7 / 4 / 4 passed |
| Frontend | 19 tests; lint/build/bundle policy passed |
| TLS / physical role / live Gateway | PostgreSQL TLS, ClickHouse TLS, role denial/rollback, E2E/lifecycle passed |
| Shared utility suite | The grouped local run stalled; rerun per CI pattern passed all 22 maintained files. |
| Visualization | 63 passed against disposable PostgreSQL. |
| Secret scan | Pinned Gitleaks current-source scan passed (5,715 files). |
| Full image build / remote CI | All maintained Compose images built locally; remote CI release evidence outstanding. |

## 44. Files Changed

C1/C2/C3 work remains uncommitted as entered. C4 adds staged owner-schema/role and TLS verification scripts, operation budget model/migration, scoped resolver keys, prune worker, CA injection, bounded discovery, safer public responses, candidate discovery and CI owner-boundary dependency. Temporary disposable acceptance scripts and Compose override are removed after the run. No `.env`, certificate, DB dump or generated Kafka/ClickHouse data belongs in the final source diff.

## 45. Remaining Non-Foundation-C Debt

BIA-009 durable jobs; AI schema/Semantic tools; Notification foreign ORM reads; Query direct ClickHouse lifecycle cleanup; CDC; PrivateNetworkTransport and AgentTransport; additional production engine certifications; dedicated replacement UI; broader production staging/operations and metering/payment provider work. These do not substitute for the open Foundation-C hard gates above.

## 46. Issue Final Status Matrix

| Issue | Entry → final | Remaining owner/action |
|---|---|---|
| BIA-005 | PARTIAL → **PARTIAL** | Platform/DB: deploy owner roles/search paths and prove running-service cross-owner denial. |
| BIA-008 | PARTIAL → **PARTIAL** | Security/Platform: managed keys/workload identity and public egress/TLS proof. |
| BIA-014 | PARTIAL → **CLOSED** | Product UI remains separate; canonical multi-source/non-destructive cutover/rollback passed live. |
| BIA-018 | PARTIAL → **PARTIAL** | Security/Platform: deployed egress and hostile DNS/TLS evidence. |
| BIA-030 | PARTIAL → **PARTIAL** | Query/Gateway: exhaustive public contract review and staging observation. |

## 47. Final Hard Gate Matrix

| Gate | Result | Reason |
|---|---|---|
| Logical owner/source/dataset separation | PASS | Live and test evidence. |
| Credential lifecycle, v2 Kafka, restart, cutover | PASS locally | Synthetic Gateway/ETL flow and denial probes. |
| TLS driver behavior | PASS in separate disposable fixtures | Not combined with production ingress/egress. |
| Physical database ownership | **FAIL for deployment** | Roles were proved in a fixture, not wired to runtime logins/search paths. |
| Managed keys/workload identity and egress | **BLOCKED_EXTERNAL** | No production secret store, workload identity or public egress deployment evidence. |
| Full two-workspace/public API audit | **PARTIAL** | Representative live denials; exhaustive matrix unrecorded. |
| Full release/CI gate | **PARTIAL** | Workflow dependency and all-image local build passed; remote CI unavailable. |

## 48. Final Foundation-C Status

**PARTIAL.** Exact blockers for GREEN: deploy and rehearse critical-owner schemas/least-privilege application roles with running-service denial and reversible migration; prove managed versioned key and service identity delivery; prove real production public egress and source TLS/host pinning with customer-like network controls; complete public route/two-workspace security and v1 cutover audit; run the full remote release/CI gate. Do not proceed to the next foundation on a false GREEN claim.
