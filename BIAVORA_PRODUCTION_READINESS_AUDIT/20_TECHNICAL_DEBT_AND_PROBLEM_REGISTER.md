# 20 — Reconciled Technical Debt, Risk, and Feature Register

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

## Classification rules

Severity describes present harm; priority describes dependency order. `P0` is reserved for a verified security, tenant-isolation, data-integrity, architecture-safety, production-critical reliability, or financial-integrity defect that must close before dependent feature work. `P1` is foundation work that can proceed in the first implementation waves. A planned capability that is absent is `FEATURE`, not a defect severity. Original IDs remain stable.

Reconciled defect counts: **4 BLOCKER, 7 CRITICAL, 13 HIGH, 10 MEDIUM, 2 LOW = 36 defects**. Planned-feature entries: **6**. Total tracked entries: **42**. Priority counts across all entries: **P0 9, P1 21, P2 8, P3 4, POST_LAUNCH 0**.

## Authoritative register

| ID | Kind / severity | Priority | Decision | Finding or capability | Owner / target |
|---|---|---|---|---|---|
| BIA-001 | DEFECT / BLOCKER | P0 | CLOSED (2026-10-14) | Query requires a logical dataset and enforces its exact server-resolved non-empty table set | SE+BOTH / W1 |
| BIA-002 | DEFECT / BLOCKER | P0 | CLOSED (2026-10-14) | Voice fails closed through Query; local product-data ClickHouse execution capability was removed | SE / W1 |
| BIA-003 | DEFECT / BLOCKER | P0 | CLOSED (2026-10-15) | Production activation is disabled; sandbox is test/development only, with server-owned state and idempotency | SE / W1 + W11 |
| BIA-004 | DEFECT / BLOCKER | P1 | RECLASSIFY priority | Compose and development servers are not a production runtime | SE / W10–13 |
| BIA-005 | DEFECT / CRITICAL | P0 | CLOSED locally (2026-10-20) | Critical logical owner schemas/roles, denied foreign writes and reversible migrations proved in C6 | SE / W1–3 |
| BIA-006 | DEFECT / CRITICAL | P0 | CLOSED (2026-10-18) | Owner attests historical values were development-only and revoked/replaced; current-tree scan, startup validation, and redaction pass | SE / W1 |
| BIA-007 | DEFECT / CRITICAL | P1 | RECLASSIFY priority | Kafka, Redis, ClickHouse need production identity/TLS boundaries | SE / W2–10 |
| BIA-008 | DEFECT / CRITICAL | P0 | PARTIAL / BLOCKED_EXTERNAL (2026-10-20) | Local lifecycle passes; canonical managed store and deployed distinct workload identities require staging | SE / W1–3 |
| BIA-009 | DEFECT / CRITICAL | P0 | RECLASSIFY evidence | Durable job model exists as an unwired/broken skeleton; active flows remain non-durable | BOTH / W2–3 |
| BIA-010 | DEFECT / CRITICAL | P0 | CLOSED (2026-10-14) | Live ClickHouse bounds/cancellation and real PostgreSQL multi-worker admission/recovery are verified | SE / W1–2 |
| BIA-011 | DEFECT / CRITICAL | P0 | CLOSED (2026-10-18) | Live CSV/XLSX/SQLite/audio, ClamAV, tenant isolation, private-path redaction, bounded TTL, and cleanup pass | SE / W1-W2 |
| BIA-012 | FEATURE | P1 | CONVERT_TO_FEATURE | PostgreSQL-first continuous CDC foundation | SE / W3–6 |
| BIA-013 | DEFECT / HIGH | P1 | KEEP_AS_IS | Report service is a proxy over Voice plus an unwired duplicate | SE / W2–4 |
| BIA-014 | DEFECT / HIGH | P1 | CLOSED (2026-10-19) | Source model permits one source per manager and destructive replacement | SE / W2–4 |
| BIA-015 | DEFECT / HIGH | P1 | KEEP_AS_IS | Gateway rate limiting is process-local; proxy timeout/capacity policy is unsafe | SE / W2, W10 |
| BIA-016 | DEFECT / HIGH | P1 | RECLASSIFY evidence | Invalid Kafka schema records can become poison records without DLQ/terminal policy | SE / W3–5 |
| BIA-017 | DEFECT / HIGH | P1 | KEEP_AS_IS | Legacy metadata projection drops workspace/dataset/job scope from stored status | SE / W3–5 |
| BIA-018 | DEFECT / HIGH | P1 | CLOSED DNS defect (2026-10-20) | Pre-connect revalidation/pinning passes; public TLS/egress acceptance remains a separate Foundation-C gate | SE / W2–3 |
| BIA-019 | DEFECT / HIGH | P1 | KEEP_AS_IS | LLM/provider calls are fragmented and lack common policy/telemetry | AI / W1–2 |
| BIA-020 | DEFECT / HIGH | P1 | KEEP_AS_IS | AI can report task success while execution status is `pending_integration` | AI+SE / W2–3 |
| BIA-021 | DEFECT / HIGH | P1 | KEEP_AS_IS | AI directly enumerates broad ClickHouse schema; cache is process-global | AI+SE / W1–3 |
| BIA-022 | FEATURE | P1 | CONVERT_TO_FEATURE | AI evaluation, prompt/model registry, and release thresholds | AI / starts W1 |
| BIA-023 | FEATURE | P1 | CONVERT_TO_FEATURE | Governed Semantic Layer | AI+SE / W5–8 |
| BIA-024 | FEATURE | P1 | CONVERT_TO_FEATURE | Permissioned hybrid RAG/knowledge lifecycle | AI / W7–9 |
| BIA-025 | FEATURE | P1 | SPLIT within feature | Governed Analyst tools and one approval-gated MCP action | AI+SE / W8–11 |
| BIA-026 | DEFECT / HIGH | P1 | KEEP_AS_IS | Quota consumes before success and lacks idempotent reservation/commit/release | SE / telemetry W1, ledger W9–11 |
| BIA-027 | DEFECT / MEDIUM | P2 | DOWNGRADE | Documentation contradicted runtime; v2 canonical set resolves planning ambiguity | BOTH / v2 complete, source docs later |
| BIA-028 | DEFECT / HIGH | P1 | UPGRADE priority | Metrics assets are not an owned SLO/dashboard/alert operating system | SE / W2 onward |
| BIA-029 | DEFECT / HIGH | P1 | UPGRADE priority | Release pipeline lacks full supply-chain, real-system, restore, and deployment gates | SE / W10–13 |
| BIA-030 | DEFECT / MEDIUM | P2 | CLOSED locally (2026-10-20) | Query SQL logicalization, all-service Gateway filter, route inventory and live tenant matrix pass | SE / W3–4 |
| BIA-031 | DEFECT / MEDIUM | P2 | KEEP_AS_IS | Browser token/CSP posture magnifies XSS impact | SE / W9–11 |
| BIA-032 | DEFECT / MEDIUM | P3 | KEEP_AS_IS | Frontend monolith and large bundle impede performance/maintenance | AI/FE / W8–12 |
| BIA-033 | FEATURE | P2 | CONVERT_TO_FEATURE | Production-complete Arabic/RTL/voice experience and evidence | AI/FE / W1 eval, W7–11 product |
| BIA-034 | DEFECT / MEDIUM | P2 | KEEP_AS_IS | Duplicate HTTP clients and readiness fan-out amplify coupling | SE / W3–8 |
| BIA-035 | DEFECT / MEDIUM | P2 | KEEP_AS_IS | Report events lack a repository consumer/outbox guarantee | SE / W4–8 |
| BIA-036 | DEFECT / MEDIUM | P3 | KEEP_AS_IS | Generated engine state and bytecode are tracked | SE / W12 |
| BIA-037 | DEFECT / MEDIUM | P2 | KEEP_AS_IS | TimesFM capacity and model artifact lifecycle are unverified | AI / W9–12 |
| BIA-038 | DEFECT / MEDIUM | P2 | KEEP_AS_IS | Broken dead orchestration and duplicate report code obscure runtime truth | BOTH / W3–12 |
| BIA-039 | DEFECT / HIGH | P1 | UPGRADE | Raw SQL/prompts/traces can expose tenant analytical context in logs | BOTH / W2–4 |
| BIA-040 | DEFECT / MEDIUM | P1 | UPGRADE priority | Images/dependencies are not reproducibly hardened | SE / W10–12 |
| BIA-041 | DEFECT / LOW | P3 | KEEP_AS_IS | Datetime deprecation warnings reduce signal | SE / W12 |
| BIA-042 | DEFECT / LOW | P3 | KEEP_AS_IS | Encoding/debug/TODO residue lowers maintainability | BOTH / W12 |

## P0 evidence and acceptance

### BIA-001 — authoritative analytical binding

**Closed 2026-10-14.** Query execution and validation now require authenticated workspace scope plus logical `dataset_id`, reject client physical storage overrides, resolve workspace/dataset ownership and all completed physical destinations server-side, and require a non-empty exact table set in the AST guard. ORM-backed endpoint tests and the SQL bypass matrix prove cross-workspace, cross-dataset, qualified-name, quoted-name, JOIN, subquery, CTE, and arbitrary-table attempts return no data and do not reach the executor. Resource settings are supplied on the authorized execution path; live ClickHouse verification remains recorded under BIA-010 rather than weakening this authorization closure.

### BIA-002 — fail-closed Query authority

**Closed 2026-10-14.** Voice persists the logical dataset binding and sends it to Query; Query outages now return an explicit retryable failure with no local execution. Voice, Report, Gateway, and Visualization no longer package or receive ClickHouse client authority, and Report's dormant duplicate executor was removed. AI's product-data value index can no longer construct a ClickHouse client and fails closed without an injected future authorized provider. AI schema-only metadata readers remain separately tracked by BIA-021/MAP-024 and do not provide a product analytical data execution route.

### BIA-003 — production financial integrity

**Closed for containment; reverified 2026-10-18.** `PAYMENT_MODE=disabled` is the default and the only valid production mode; startup and request guards reject sandbox activation in production. The sole activation path is a manager/admin-authorized development/test sandbox event with a UUID idempotency key and server-owned payment amount/status. Exact Workspace response identity is checked, and sandbox/legacy records are excluded from reported revenue. Migration `subscription.0003` was applied to the local live PostgreSQL database after verifying zero existing subscription rows; the 11-test PostgreSQL suite covered forward/reverse/reapply and negative/idempotency behavior. A live forged payment request returned HTTP 503. **Paid launch remains separate planned work:** hosted/tokenized provider, signed idempotent webhooks, reconciliation, refunds/failures, and staging evidence. See `37_FOUNDATION_B_EXTERNAL_BOUNDARY_IMPLEMENTATION.md`.

### BIA-005 — critical logical data ownership

Auth, Workspace, Query, Voice, Report, Visualization, Subscription, and Notification settings default to `DB_NAME=bi_voice_agent` and `DB_USER=bi_admin`; Notification maps other owners' tables as unmanaged models. **Accept:** freeze owner map; Auth, Workspace, Query, Integration, and Entitlements/Metering get owner schemas/databases and least-privilege roles; cross-domain writes are denied; migration/rollback tests pass. One managed cluster is permitted.

**Foundation-C Part 1, 2026-10-19 — PARTIAL.** Integration now has one logical source writer in the Query deployment and Query retains dataset binding. The source/dataset migration passed forward/reverse/reapply on disposable PostgreSQL. Shared production roles/schema, Notification foreign reads, direct Query ClickHouse dataset cleanup, and denied cross-owner writes remain. See `38_FOUNDATION_C_SERVICE_OWNERSHIP_INTEGRATION_IMPLEMENTATION.md`.

**Foundation-C C4, 2026-10-19 — PARTIAL.** A staged owner-schema/role migration and rollback script passed real PostgreSQL owner CRUD, foreign INSERT/UPDATE/DELETE denial, and data preservation on a disposable database. Running services still use the shared login; owner-role credentials/search paths, deployment migration, and running-service denial are unproved. See `40_FOUNDATION_C_FINAL_ACCEPTANCE_REPORT.md`.

**Foundation-C final closure pass, 2026-10-19 — PARTIAL.** Production-profile Auth, Workspace, Query, Integration (separate Query ORM alias), and Entitlement now require domain-specific runtime logins/search paths. Disposable migrations, owner apply/reapply, actual service-credential `current_user`/`current_schema`, own CRUD and PostgreSQL foreign INSERT/UPDATE/DELETE denial, WSGI `/ready/`, source/credential/dataset split-role flow, and journaled rollback passed. A new identity-sequence fixture verifies sequence use and state after rollback. Full Gateway/Kafka/ETL lifecycle, fresh production-profile migration, application reconnect after rollback, and deployment cutover remain unproved. See `41_FOUNDATION_C_FINAL_CLOSURE_REPORT.md`.

**C6, 2026-10-20 — CLOSED for the canonical local defect.** The complete Gateway→Integration/Query→Connector→Kafka v2→ETL→ClickHouse→Query source lifecycle ran with five actual restricted runtime roles. Fresh production-profile migrations, a historical upgrade rehearsal, foreign PostgreSQL write denial, live owner rollback, compatible Query reconnect, exact row/sequence/migration fingerprint preservation, owner reapply and role-bound Gateway query all passed. Read-only `django_migrations` startup access and Auth blacklist table ownership were corrected from the live findings. A real deployment cutover still needs operator staging and does not substitute for the separate Foundation-C external secret/egress gates. See `42`.

### BIA-006 — historical secret exposure

**Closed 2026-10-18 on owner operational attestation plus technical verification.** The owner confirms all identified historical values were development-only, none was a production credential, applicable provider/platform credentials were revoked/deleted/replaced, and the historical ETL encryption key has no production ciphertext dependency. Current-tree pinned Gitleaks scanning, production placeholder/startup checks, CI scan dependency, recursive log redaction, and tenant credential protection pass. Historical text may remain in Git history, but is not evidence that an old credential is still valid. History purge is recommended optional hygiene, not a closure requirement; no history rewrite occurred. Provider-side revocation was owner-attested rather than independently rechecked. See `37_FOUNDATION_B_EXTERNAL_BOUNDARY_IMPLEMENTATION.md`.

### BIA-008 — safe source foundation

Query currently owns a one-per-manager `Database`, stores source configuration, exposes physical identifiers, and deletes old physical data before replacement success. ETL encryption derives Fernet from `CREDENTIAL_SECRET_KEY` with static salt `etl-pipeline-salt` and no key version. **Accept:** logical Integration owner, persistent multi-source model, opaque versioned secret refs, staged replace/cutover/rollback, direct-secure transport policy, and audited lifecycle.

**Foundation-C Part 1, 2026-10-19 — PARTIAL.** The current model is now Integration `DataSource` (UUID/workspace/non-secret metadata/selected tables/active-disabled-retired) linked to Query datasets. New snapshots/uploads retain prior datasets. ETL carries an additive Integration UUID while preserving the legacy dataset-scoped `source_id`. Opaque versioned secret refs, managed credential lifecycle, transport policy, staged cutover/rollback, and live application proof remain C3/C4 work. Existing transient encrypted Kafka credential handoff is `TRANSITIONAL_C3_DEBT`.

**Foundation-C Part 2, 2026-10-19 — PARTIAL.** Integration now owns encrypted, versioned source credentials, scoped execution grants, internal ciphertext-only resolution, staged validated rotation, and candidate source replacement with snapshot-gated cutover/rollback. New v2 snapshot events contain opaque refs rather than password ciphertext; v1 is retained only for pre-cutover replay, and production Connector rejects new raw-password server operations. DirectTransport revalidates and pins supported engines; other network engines are production-blocked pending safe TLS-hostname pinning. Disposable PostgreSQL migration and focused read-only source checks passed, but the full Kafka/ClickHouse/Query live flow, managed secret/workload identity deployment, and C4 gate remain. See `39_FOUNDATION_C_CREDENTIAL_TRANSPORT_IMPLEMENTATION.md`.

**Foundation-C C4, 2026-10-19 — PARTIAL.** The isolated public Gateway path completed a PostgreSQL source → Kafka v2 → Extractor → Transformer → Loader → ClickHouse → Query snapshot, restart persistence, credential rotation/revocation, and staged replacement/cutover/rollback. Scoped resolver keys, pruning worker, operation budgets, and separate PostgreSQL/ClickHouse TLS fixtures passed. Managed secret/workload identity, deployed physical owner roles, production public egress/TLS and complete release audit remain open. See `40`.

**Foundation-C final closure pass, 2026-10-19 — PARTIAL.** Application secret consumption now accepts protected external file mounts for versioned encryption and separate resolver identities, with safe startup failure and local v1→v2 ciphertext rewrap/retirement checks. The production resolver test covers Connector/Extractor overlap and old-key rejection; production v1 Kafka source replay defaults off and has an explicit maximum seven-day drain window. Canonical `33` still requires a managed KMS/secrets manager and separate deployed workload identities. No external store/identity was deployed or attested. See `41`.

**C6, 2026-10-20 — PARTIAL / BLOCKED_EXTERNAL.** Restricted-role live source lifecycle, restart without password resubmission, rotation/revocation, scoped resolver and v2 replay passed locally. The user confirmed no staging infrastructure exists. Canonical `33`'s managed KMS/secrets manager and separately deployed, identity-bound Connector/Extractor access have not been proven; synthetic local keys and file mounts are not that proof. Staging provisioning and managed-key/identity rotation are the exact next operator work. See `42`.

**Kafka v1 transition, C6.** Global source-producer audit and production tests show no active database v1 publisher; the production reader remains default OFF with an explicit maximum seven-day opt-in deadline. The isolated v2 topic had zero consumer lag and an exact replay retained a two-row dataset, but actual staging/production v1 retention and backlog are unknown. Transition remains **TRANSITIONAL / BLOCKED_EXTERNAL for drain attestation**; no user topic was deleted or truncated. See `42`.

### BIA-014 / BIA-030 — Part-1 progress

**PARTIAL, 2026-10-19.** `Database.manager` is no longer unique; multiple sources and datasets per workspace are supported, and the frontend can select prior datasets. Snapshot/file creation no longer deletes the previous dataset. A complete staged source replacement and live gate remain. Dataset public serialization and delete response no longer expose physical ClickHouse table/database identifiers, but all public contracts have not yet passed the BIA-030 closure audit. See report `38`.

**Part-2 update.** Replacement now stages and tests candidate configuration/credential, requires a completed candidate snapshot for atomic cutover, and offers a 24-hour rollback point while preserving prior datasets. BIA-014 remains PARTIAL until the full live cutover/rollback path passes. BIA-030 remains PARTIAL pending the broader public contract audit. See report `39`.

**C4 update.** BIA-014 is **CLOSED** against its canonical multi-source/non-destructive replacement acceptance: live candidate test/discovery/one-row snapshot, cutover, rollback, and prior dataset retention passed through Gateway; the dedicated UI is separate product work. BIA-030 remains **PARTIAL**: public dataset, preview, health, upload failure and source responses were narrowed, but exhaustive Gateway/SQL contract review and production observation remain. See report `40`.

**Final closure pass.** BIA-014 remains **CLOSED**. BIA-030 remains **PARTIAL**: an explicit 22-route Query inventory, public source/dataset payload checks, Workspace B route matrix and Gateway upstream-error scrub pass; exhaustive Voice/Report/Visualization/SQL response and full live Gateway matrix are unproved. See report `41`.

**C6 update, 2026-10-20.** BIA-014 remains **CLOSED** after another live candidate snapshot/cutover/rollback with prior datasets previewable. BIA-030 is **CLOSED for its canonical physical-identifier defect**: registered URLs across ten services are classified and checked in CI, Query's live SQL echo now renders logical source names, Gateway rejects internal metadata/diagnostic strings on success and failure, and 24 distinct actual Gateway Workspace-B source/dataset/query route cases deny or list empty without disclosure. See report `42`.

### BIA-018 — destination/DNS rebinding

**PARTIAL, 2026-10-19.** The central destination policy now rejects non-global IPv4/IPv6 and mixed DNS answers, bounds resolver wait/concurrency, and revalidates immediately before each driver socket. PostgreSQL uses pinned `hostaddr` with original TLS hostname; ClickHouse uses pinned IP with original TLS `server_hostname`. MySQL, MariaDB, MSSQL, and Oracle are blocked in production direct mode until safe pin/hostname verification is proven. Deterministic rebinding tests and a local disposable PostgreSQL direct-read test passed. Production TLS/egress and complete engine/live security evidence remain C4 closure work; no closed claim. See report `39`.

**C4 update.** Separate disposable PostgreSQL and ClickHouse TLS fixtures passed trusted hostname/read and rejected wrong hostname, untrusted CA and insecure mode. Live full ETL used a development-only private CIDR/non-TLS source; production egress ACL, customer-like TLS path and hostile DNS drill are unproved. BIA-018 remains **PARTIAL**. See report `40`.

**Final closure pass — PARTIAL.** Deterministic DNS revalidation/pinning and separate TLS fixtures remain valid; C5 made no private-CIDR production bypass. No fixed public egress/customer allowlist or combined production-policy TLS Gateway→ETL→Query run exists in the local environment. See report `41`.

**C6, 2026-10-20 — CLOSED for BIA-018's DNS-rebinding defect.** Initial and pre-connect DNS validation, unsafe-address denial, pinning and separate verify-full TLS fixtures pass; no production bypass was added. The distinct canonical DirectSecureInternetTransport deployment gate remains **BLOCKED_EXTERNAL**: there is no controlled public TLS source, stable egress, customer allowlist, or full production-policy Gateway→ETL→Query attestation. See `42`.

### BIA-009 — durable jobs before agent growth

Active Voice views and AI Dagster calls are synchronous. `VoicePipelineJob` and orchestration modules exist, but orchestration imports missing `domain/statuses.py` and three infrastructure clients and is not wired to active routes/workers. **Accept:** one persisted job contract with `QUEUED/RUNNING/RETRYING/SUCCEEDED/FAILED/CANCELLED`, attempts, idempotency/correlation, cancellation, result/error references, outbox/events, workers, and false-success tests.

### BIA-010 — bounded analytical execution

**Closed 2026-10-14.** Query validates bounded startup configuration and applies read-only, execution-time, row, result-byte, bytes-read, and memory settings per request. It wraps results in a bounded page window, caps serialized output, reports explicit truncation/next-page semantics, creates workspace-scoped cancellation IDs, emits safe structured telemetry, and uses PostgreSQL advisory-lock slots for distributed per-workspace admission with connection-close stale recovery. Live validation used the repository Compose stack, ClickHouse `26.2.3.2`, PostgreSQL `18.3`, and the rebuilt Query service. The configured policy was accepted by the real server; normal execution, the 10,000-row window, 1,000-row page ceiling, 5 MiB response bound, read-only mode, real timeout, practical bytes-read and memory limits, and safe typed failures all passed. An authenticated long-running request was visible in `system.processes` under its workspace/request-derived ID; a different workspace received `cancelled=false`, the authorized cancellation stopped the real query with `QUERY_CANCELLED`, the server process disappeared, and a following query succeeded. Four distinct Query worker processes proved same-workspace `A/B admitted, C limited`, different-workspace independence, normal and exception release, and stale-lock recovery after process termination. A bounded 20-request abuse check preserved page limits and rejected all cross-workspace dataset attempts; Query memory moved only from 115.2 MiB to 119 MiB and all temporary metadata/tables were removed. The live run exposed and corrected only the required driver-integration details: per-thread ClickHouse sessions, the driver's supported per-query `query_id` transport parameter, accurate no-target cancellation, and ClickHouse 26 limit-error classification. All maintained regressions then passed with no skips.

### BIA-011 — upload boundary

**Closed 2026-10-18.** Public Gateway CSV, XLSX, and SQLite uploads completed through Query, Connector, Kafka, Extractor, Loader, and ClickHouse with cross-workspace denials and staged-source cleanup. Live ClamAV clean/EICAR/outage checks passed; Connector, Voice, and AI startup cleanup removed old generated files while retaining fresh and unrelated files. A valid WAV completed public Voice → AI under the configured small model (HTTP 200); malformed WAV returned 400 and both private audio areas were empty after processing. Recursive AI trace redaction removed an internal audio path found by the live gate. SQLite prepare has a 24-hour token TTL, snapshot dispatch refreshes the staging clock, and Query/Extractor enforce a 30–3,600 second queue/processing window; near-expiry and stale-token live probes passed. Filename, content, size, archive, duration, tenant, and private-storage tests passed. See `37_FOUNDATION_B_EXTERNAL_BOUNDARY_IMPLEMENTATION.md`.

## Feature—not-defect policy

BIA-012, 022, 023, 024, 025, and 033 are required Week-14 capabilities but their absence is not classified as a current defect. Defects that would make those features unsafe remain separately tracked (for example BIA-008/009/019/021/026). This preserves urgency without inflating severity.

Detailed v1 evidence remains in repository history and the other audit files. Reconciliation decisions and path-level evidence are indexed in `28_AUDIT_RECONCILIATION_CHANGELOG.md`.
