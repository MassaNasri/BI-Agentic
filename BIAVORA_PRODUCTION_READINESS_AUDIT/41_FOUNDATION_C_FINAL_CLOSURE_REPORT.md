# 41 — Foundation-C final closure report

Date: 2026-10-19. Decision: **PARTIAL**. This is local engineering evidence on an uncommitted tree, not a production deployment or remote release attestation.

## 1. Executive Summary

C5 wires the five critical logical owners to distinct PostgreSQL runtime logins in the production profile, adds an opt-in, reversible owner cutover, proves actual Django service credentials and running HTTP readiness on disposable PostgreSQL, and adds mounted secret consumption, key rewrap, bounded Kafka v1 replay, and public-route checks. Local maintained suites, image builds, secret scan, and migration drift passed. Mandatory managed secret-store deployment, public egress and integrated TLS source path, complete public/tenant audit, Kafka backlog cutover, and authoritative remote CI remain unproved. Foundation-C is **PARTIAL**; no GREEN candidate is claimed.

## 2. Entry State

Branch `main`, entry HEAD `9298d2f25425f880cb56ccdeb2036e65f83f1bcb`. C1–C4 were uncommitted. `services/ai-service/forecasting/timesfm` was dirty before this pass and was left untouched. No staging, commit, push, reset, clean, user database migration, or user-volume change occurred.

## 3. Documents Read

`34` first; canonical `29`–`33`; debt/roadmap/planning `20`, `25`, `26`; Foundation evidence `36`–`40`; actual implementation, Compose, tests, and `.github/workflows/p0c-release-gate.yml`. Report 40 was the entry execution state; canonical v2 documents control closure.

## 4. Canonical Closure Interpretation

`20` defines BIA-005 owner schemas/roles, denied cross-domain writes, and reversible migration; `33` requires those controls before dependent features. `33` also names **KMS/secrets manager** in BIA-008 pre-feature acceptance and a **managed secret store plus separate workload identities** before staging. A provider-neutral mounted-file consumer is necessary engineering, but does not satisfy that external deployment. `29` and `30` require the initial direct source path to validate TLS and egress; `34` explicitly carries deployed identity/key/egress/TLS as Foundation-C gates. Local code fixtures may prove driver behavior but not deployed public egress or customer allowlisting. `20` defines BIA-018 as a DNS rebinding defect; code and deterministic tests address that portion, while the canonical production direct path remains unproved. BIA-030 requires safe public contracts; incomplete route/SQL and live tenant audit prevent closure. These are not moved to a later phase merely to turn Foundation-C green.

## 5. Report-40 Blocker Reconciliation

| Gate | Report 40 | C5 change | Final |
|---|---|---|---|
| BIA-005 | Fixture-only role proof | Production Django role/search-path configuration, actual role login and HTTP readiness, reversible cutover | PARTIAL pending full service lifecycle under roles and deployment migration proof |
| BIA-008 | Environment key delivery | External mount consumer, versioned rewrap, scoped resolver rotation checks | PARTIAL: no managed store/workload identity deployment |
| BIA-014 | CLOSED | Preserved | CLOSED |
| BIA-018 | Separate TLS fixtures | Production policy retained; no bypass added | PARTIAL: no full public-egress TLS ETL proof |
| BIA-030 | Select responses narrowed | Query route inventory, success/foreign workspace tests, Gateway 5xx scrub | PARTIAL: other public surfaces and full live route matrix unproved |
| Kafka v1 | Reader retained | Explicit short production replay window; default deny | TRANSITIONAL: backlog/drain unknown |

## 6. BIA-005 Physical Ownership

The owner map moves Auth (`users`, `password_reset_codes`), Workspace (`workspaces`, `workspace_members`, `invitations`), Integration (source, credential, execution, candidate, budget tables), Query (datasets and authorized definitions), and Entitlement (subscription tables) into dedicated `biavora_<domain>` schemas. `scripts/foundation_c4_owner_schemas.py` journals former schema/owner, moves existing tables transactionally, assigns owner/app grants and sequences, verifies idempotent reapply, and reverses on an explicit operator flag. It was applied only to disposable PostgreSQL. Other shared-database domains, including Notification foreign reads, remain separate debt.

## 7. Runtime Service Roles

Production Auth, Workspace, Subscription, and Query default connections require exact `biavora_<domain>_runtime` logins. Query Integration ORM uses a second `integration` alias and `biavora_integration_runtime`, with domain routing and its own atomic transactions. A separate flagged migration mode permits a deployment principal without granting owner powers to application logins. The disposable probe generated five distinct passwords, configured LOGIN roles, and observed `current_user` and `current_schema()` through each service's Django connection. Standard-library WSGI processes under production settings returned HTTP 200 from each `/ready/` endpoint. This is real process/DB proof, but not a full live Gateway/Kafka stack under new roles.

## 8. Cross-Owner Denials

For each of five service connections, a disposable SQL probe succeeded on own SELECT and zero-row INSERT/UPDATE/DELETE and received PostgreSQL `InsufficientPrivilege` on foreign INSERT/UPDATE/DELETE. Query's Integration alias separately used the Integration role; an ORM source/credential plus Query dataset write exercised the split. The proof is stronger than app-level authorization but covers mapped critical tables, not every legacy shared table or deployment-specific grant.

## 9. Migration Role vs Runtime Role

Owner and migration roles remain separate from app roles. Production settings reject an incorrect runtime username, absent DB password, non-PostgreSQL critical connection, and migration mode without `BIAVORA_ALLOW_MIGRATION_ROLE=1`. The CI fixture migrates with a disposable administrator **before** owner cutover, then verifies restricted app logins. Query has explicit Integration migration routing. A fresh production-profile migration and full application upgrade with least-privilege roles were not rehearsed; this is BIA-005 residual work.

## 10. Ownership Rollback

Apply/reapply and rollback passed on disposable PostgreSQL. The journal returned tables to prior schemas/owners; source and credential records remained, and the test's marker/sequence checks passed. The independent C4 owner fixture also passed rollback. Application reconnect after an entire stack rollback and production backup validation remain unproved. Rollback must restore compatible service credentials first, then invoke the journaled rollback and verify data/permissions.

## 11. BIA-008 Secret Delivery Contract

`read_secret(NAME)` consumes either an inline value or absolute `NAME_FILE` mount, never both. It rejects symlinks, non-regular files, oversize/empty files, and group/world-readable production POSIX mounts, and emits errors without values. Query/ETL credentials, resolver identities, and relevant DB passwords consume it; Compose allows file-only credential-key injection. Missing required production keys fail closed through existing settings/crypto checks. This is an **application consumption contract**. No KMS, Vault, cloud secret manager, identity-bound mount, or managed rotation was deployed; the canonical managed-store gate is **BLOCKED_EXTERNAL**.

## 12. Key Version Delivery

`CREDENTIAL_KEY_VERSION=vN` selects `CREDENTIAL_SECRET_KEY_VN` or its `_FILE` mount; legacy v1 fallback remains for migration. Startup validates inline and mounted versioned keys for strength, rejects ambiguous delivery, and redacts loaded values. The mount test passes; its POSIX permission test is skipped on Windows and must run in Linux CI. No real provider/version inventory exists here.

## 13. Key Rotation/Rewrap

`rewrap_source_credentials --from-version v1 --apply` locks and transactionally re-encrypts retained ciphertext under the active next key; `--check-retire` refuses retirement while old-version ciphertext remains. A synthetic test passed v1→v2, resolution after rewrap, old-key removal, and unsafe retirement denial. This is a local cryptographic/ORM rehearsal, not a managed provider rotation or full deployed restart/rollback exercise.

## 14. Resolver Workload Identity

Connector and Extractor retain separate current/previous scoped resolver keys; production forbids shared fallback and weak/colliding keys. Exact service, grant, workspace, source, job, dataset, and version scopes are checked by the internal Query endpoint. Gateway exposes no resolver route. Scoped static keys are a workload **authentication contract**; they are not evidence of a platform-issued workload identity or mTLS deployment.

## 15. Resolver Identity Rotation

The maintained Query test accepts current and previous Connector/Extractor identities during overlap, rejects cross-service impersonation and the legacy shared key, then removes both previous keys and confirms rejection while current keys still succeed. This proves policy transitions in a test process. A rolling multi-instance deployment and secret-store rotation drill are pending.

## 16. BIA-018 Egress Classification

Destination admission, DNS revalidation, pinned PostgreSQL/ClickHouse connections, hostname/CA validation, and insecure production option denial are repository controls. A true public Internet source through a controlled production egress boundary, customer allowlist, firewall, and audit is external infrastructure. Docker private addressing cannot stand in for that gate without weakening production policy. No private-CIDR exception was added for C5.

## 17. Full PostgreSQL TLS Path

Report 40's separate TLS PostgreSQL fixture passed verify-full trusted CA/hostname and rejected wrong hostname, untrusted CA, insecure mode, and source-role write. Its full Gateway→Kafka v2→ETL→ClickHouse→Query run used a development private CIDR/non-TLS source. C5 did not rerun that full path under TLS and production public egress. Therefore the requested combined path is **UNPROVEN**, not inferred from two passing fixtures.

## 18. DNS/Pinning/Rebinding

Maintained tests cover initial and pre-connect A/AAAA validation, forbidden/mixed answer denial before driver invocation, PostgreSQL `hostaddr` pinning with original TLS name, and ClickHouse pinned numeric address with original SNI. C4 separate TLS fixtures exercised driver hostname/CA behavior. A live hostile DNS rebinding drill at a deployed egress boundary remains unavailable.

## 19. Production Egress Requirement

`29`/`30` make Direct Secure Internet the initial production source mode; `33` requires safe DNS/IP, egress policy, TLS, timeouts and least-privilege source accounts. `34` carries deployed egress/TLS as an open Foundation-C gate. No fixed public egress, customer allowlist, controlled NAT/firewall, or external TLS source attestation is present. **BLOCKED_EXTERNAL** for deployment evidence.

## 20. Engine Capability Matrix

| Engine | Current evidence | Production direct status |
|---|---|---|
| PostgreSQL | Full C4 local non-TLS snapshot; separate verify-full fixture; pinning tests | Driver contract proven; public egress/full TLS ETL unproved |
| ClickHouse source | Separate native TLS fixture and pinning tests | Driver contract proven; full source snapshot/public egress unproved |
| MySQL | Historical adapter/registry tests | Blocked pending pin plus TLS hostname proof |
| MariaDB | Historical adapter and P1-R live result | Blocked pending pin plus TLS hostname proof |
| MSSQL | Contract/adapter tests | Blocked pending pin plus TLS identity proof |
| Oracle | Contract/adapter tests | Blocked pending pinned TCPS identity proof |
| SQLite | Private staged file token | Public network direct mode not applicable |

## 21. BIA-030 Public Route Inventory

An automated Query URL inventory locks the 22 `database/` and `query/` patterns, including source/credential/replacement, dataset, SQL, health and definition routes. It fails if a new matching route appears without test review. Gateway routing was inspected; the internal resolver has no public Gateway mapping. Route inventories and success/error schemas of Voice, Report, Visualization and other public services are not yet exhaustive.

## 22. Public Response Classification

Integration source and Query dataset success payload tests exclude physical ClickHouse database/table, file path, ciphertext, credential UUID and upstream diagnostic markers. Gateway replaces upstream 5xx bodies with generic 502 and rejects forbidden metadata keys on `/database/` and `/query/` JSON. Voice was changed to use the public logical dataset/explicit selector after physical table removal. Query SQL echo and non-Query public payloads still need a comprehensive audited inventory and staging observation; BIA-030 stays PARTIAL.

## 23. Two-Workspace Full Route Matrix

An automated Workspace B matrix covers source list/detail/edit/retire, configure/rotate/revoke, replacement create/test/discover/snapshot/cutover/rollback, source test/discover/snapshot, dataset list/detail/preview/schema/delete, and query execute. It checks denials or empty lists before mocked upstream contact and no internal fields in errors. Report 40 separately observed representative live Gateway denials. This is broad Query domain coverage, but not a **full live Gateway matrix** for every public route/service; no claim of exhaustive tenant audit is made.

## 24. Internal Resolver Audit

The resolver route is internal Query-only and absent from Gateway public routes. Tests reject wrong service identity, mismatched grant/workspace/source/job/dataset/version and legacy shared key. C5 rotation test covers previous-key retirement. No independent production network ACL/mTLS audit is available.

## 25. Kafka v1 Producer Audit

The new source snapshot path emits contract v2 with opaque `credential_ref`, and production Connector database entry points reject raw-password v1 operations. Static inspection found legacy file/database trigger code and v1 compatibility paths; it does not establish every production caller or a deployed publisher inventory. No new v1 production emission is claimed from the C4 source flow, but global producer cutoff is **UNPROVEN**.

## 26. Kafka v1 Retirement/Drain Status

Production Extractor v1 source consumption is disabled by default. An explicit `KAFKA_V1_SOURCE_REPLAY_UNTIL` future date permits at most a seven-day drain window, with safe warning fields; an expired/too-long window rejects. Tests pass. Existing topic backlog, deployed producer cutoff, and drain/expiry attestation are unknown. V1 must not be enabled indefinitely.

## 27. Kafka v2 Replay

C4 inspected five live v2 events containing references without synthetic password/ciphertext and completed the ETL load. Tests cover exact grant/version scope and denial of stale/mismatched references. A full live retry/replay with duplicate-load and all failure semantics under new roles was not rerun; BIA-009 durable jobs remain separate.

## 28. Credential Pruning

Report 40's disposable prune-worker `--once` removed expired ciphertext, preserved active/rollback records, and reported healthy. C5 retained this worker. No production scheduler/retention attestation or repeat live prune after C5 was performed.

## 29. Failure Drills

C4 passed bad source password, bad/good rotation, revoke, foreign workspace, source read-only write denial, candidate-not-ready cutover, TLS hostname/CA/insecure options, and safe logs. C5 adds weak/missing/ambiguous mount, role mismatch, forbidden PostgreSQL writes, old-key retirement, and bounded v1 replay tests. Kafka/ClickHouse outage under load, public egress/DNS attack, and managed identity rotation remain untested in deployment.

## 30. Migrations

Earlier C1–C4 disposable PostgreSQL proved `integration.0001`–`.0004` and `database.0006` forward/reverse/reapply without synthesized passwords. C5 adds no model migration. Four critical service migration sets were freshly applied to `biavora_c5_runtime` under a disposable administrator; owner apply/reapply/rollback and role login checks passed. Query default/Integration aliases reported no pending plan after cutover. Eight-configuration drift checks passed locally. A fresh production-profile split migration, complete upgrade from pre-C user data, and application restart after rollback remain open.

## 31. Foundation-C E2E Regression

The full C4 disposable Gateway→Integration/Query→Connector→Kafka v2→Extractor→Transformer→Loader→ClickHouse→Query run proved source create/configure/test/discover/snapshot, two-row load, preview/aggregate, restart persistence, rotation, revoke, staged replacement/cutover/rollback, and retire. C5 separately proved real production-profile HTTP readiness and split-role ORM source/credential/dataset flow. **The full C4 E2E was not rerun after C5 under restricted roles or mounted secrets**; this is a local acceptance gap.

## 32. Foundation-A Regression

Query 114 pytest and Voice 27 pytest passed after C5; prior Foundation-A live aggregate and cross-tenant denial are in report 40 and full security context is in report 36. BIA-001/BIA-002/BIA-010 remain closed on maintained evidence; no new direct Voice/AI/Report/Viz analytical credential was introduced.

## 33. Foundation-B Regression

Auth 2, Workspace 4, Subscription 11, Gateway 4, Notification 4, Report 5 and Visualization 63 tests passed; AI 238 passed. Earlier upload/payment/provider containment is recorded in report 37. BIA-003/BIA-006/BIA-011 remain closed; no full live upload or payment drill was repeated in C5.

## 34. Frontend

19 tests, ESLint, Vite production build and bundle policy passed locally. Existing source/dataset UX remained; no C5 UI redesign. Vite emitted advisory bundle-size and stale browser-data warnings.

## 35. Static/Docker/Compose

Static compile/merge-marker check passed for 797 maintained Python files before the final small C5 test/probe edits; targeted edited modules were then executed or compiled in final checks. `docker compose config --quiet` passed. Full local `docker compose build` passed all maintained images after C5 application code edits; later edits to tests/probe/security validation did not repeat the full build. No generated cert, CA key, DB dump, `.env` or service runtime volume was added to source.

## 36. CI Workflow

`.github/workflows/p0c-release-gate.yml` contains nine required jobs: current-tree secret scan, static/Compose, frontend, backend/AI, ETL, security regression, migration drift, Docker build, and Foundation-C owner boundary. `release-gate` uses `if: always()` and requires nine successes. The owner job provisions a disposable PostgreSQL service, migrates Auth/Workspace/Subscription/Query, applies owner schemas, runs actual Django service role plus HTTP readiness proof, and rolls back. Query public contract and mount tests are included in deterministic jobs. Workflow YAML parsed locally; no GitHub Actions run occurred on this uncommitted tree.

## 37. Local CI-equivalent Gate

Local maintained results: Query 114 pytest; Integration 20 Django; Auth 2, Workspace 4, Subscription 11, Gateway 4, Notification 4, Voice 27, AI 238, Report 5, Visualization 63; Connector 144, Extractor 225/5 skipped, ETL shared models/security 359, 22 shared utility files individually, Transformer 12/1 skipped, Loader 14/1 skipped, listener 7, Detector 4, Metadata 4. Frontend 19/lint/build/bundle, Compose, full image build, migration drift, mounted-secret tests (3 passed/1 Windows-only skip), Query identity retirement test, disposable owner fixture, split-role service/Wsgi readiness, and public contract tests passed. Some suite counts precede the last narrow edits, which received focused reruns; no remote aggregation result is inferred.

## 38. Secret/Artifact Scan

Pinned Gitleaks current tracked/new source scan passed after replacing two synthetic test key literals with generated test values; the final scan covered 5,745 source files. This does not prove historical or external provider state. Scope excludes ignored user `.env` and local runtime data. Temp scan copies were removed within the workspace. The final diff audit must still exclude certificate/private key, database dump, Kafka/ClickHouse data and logs.

## 39. Rollback Procedure

Freeze new source work and record active versions. Preserve both old/new credential keys and scoped resolver identities through grant drain and rollback windows; never revive production v1 publishing. Restore compatible service DB credentials before schema rollback, then execute flagged journaled owner rollback and verify owner/schema, row counts, source UUIDs, dataset IDs, credentials and sequences. Reverse Integration/Query migrations only after backups and absence of dependent grants. Retain v2 reader and completed datasets, stop/restart prune worker around the retention check, and revalidate source/Query reads. Deployment operations and backup validation require an operator runbook and actual environment proof.

## 40. Files Changed

Earlier C1–C4 files remain uncommitted. C5 creates `bi_platform_shared/secret_delivery.py`, `bi_platform_shared/db_ownership.py`, `bi_platform_shared/public_contract.py`, `etl-final/shared/security/legacy_kafka.py`, `scripts/verify_foundation_c5_service_roles.py`, Query credential rewrap command/tests, public boundary tests and mounted-secret tests. It updates critical service settings, Query Integration routing/transactions, owner deployment/probe scripts, Gateway response filtering, Voice public dataset consumption, ETL secret/replay handling, Compose/example configuration, release workflow, and this audit. No file was intentionally deleted; TimesFM remains pre-existing dirty.

## 41. Remaining OUT-OF-SCOPE Debt

BIA-009 durable jobs; Semantic/AI/RAG/Agents; Notification foreign ORM reads; Query direct ClickHouse dataset cleanup; further engine certifications; production payment/provider and operations; dedicated replacement UI; CDC; PrivateNetworkTransport; AgentTransport. They were not implemented in C5 and do not erase the Foundation-C blockers listed here.

## 42. Final Issue Matrix

| Issue | Entry → final | Exact residual |
|---|---|---|
| BIA-005 | PARTIAL → **PARTIAL** | Restricted service logins and denial pass locally; fresh production-profile migration, full live lifecycle under roles, and deployment cutover/rollback are unproved. |
| BIA-008 | PARTIAL → **PARTIAL** | Lifecycle/rewrap/mount contract pass; canonical managed secret store and separate deployed workload identity absent. |
| BIA-014 | CLOSED → **CLOSED** | C4 multi-source non-destructive replacement/cutover/rollback evidence preserved. |
| BIA-018 | PARTIAL → **PARTIAL** | Deterministic DNS/pin and TLS fixtures pass; public egress and combined production TLS ETL proof absent. |
| BIA-030 | PARTIAL → **PARTIAL** | Query route/tenant matrix and Gateway scrub pass; exhaustive public service/SQL and live matrix absent. |
| Kafka v1 | TRANSITIONAL → **TRANSITIONAL** | Default-deny bounded reader added; deployed backlog/drain and global producer cutoff unproved. |

## 43. Final Hard Gate Matrix

| Gate | Result |
|---|---|
| Logical Integration/Query separation and source lifecycle | PASS locally, from C4 live + maintained tests |
| Physical role wiring and PostgreSQL foreign-write denial | PASS on disposable production-profile services |
| Full app lifecycle/migration/rollback under roles | PARTIAL |
| External mounted-secret consumer and local rewrap | PASS locally |
| Managed store and deployed workload identities | BLOCKED_EXTERNAL |
| DNS/pinning and separate PostgreSQL/ClickHouse TLS fixtures | PASS as code/fixture evidence |
| Public egress and combined TLS ETL path | BLOCKED_EXTERNAL / UNPROVEN |
| Exhaustive public/two-workspace contracts | PARTIAL |
| Kafka v1 production drain/replay attestation | PARTIAL |
| Deterministic local CI equivalent | PASS for exercised jobs, subject to noted live gaps |
| Authoritative remote release gate | PENDING_PUSH |

## 44. Foundation-C Local Closure Decision

**FAIL for complete closure.** Several repository and external gates remain. **Foundation-C release candidate: NOT READY. Foundation-C final: PARTIAL.** C5's local improvements do not convert report 40's partial state into GREEN.

## 45. Remote CI Requirement

`REMOTE_CI = PENDING_PUSH`. A review, commit, and push of this exact final tree would be needed for authoritative GitHub Actions evidence. This task explicitly forbids committing/pushing, so no remote CI success is asserted. Remote CI alone would still not close the external deployment and live audit gaps.

## 46. Exact Next Action

Review C5 changes and this report; complete the full restricted-role E2E and production-profile migration/rollback rehearsal, exhaustive public/tenant and Kafka cutover audits, and staging with managed secrets/workload identities plus controlled public egress/full TLS source flow. Then review, commit, push, and reconcile the nine required GitHub Actions jobs. Keep Foundation-C PARTIAL and do not start Foundation-D until these mandatory results are recorded.
