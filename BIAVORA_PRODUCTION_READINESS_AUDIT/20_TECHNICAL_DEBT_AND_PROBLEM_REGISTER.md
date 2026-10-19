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
| BIA-005 | DEFECT / CRITICAL | P0 | RECLASSIFY scope | Shared PostgreSQL role/schema ownership; enforce critical logical owners, not servers-per-service | SE / W1–3 |
| BIA-006 | DEFECT / CRITICAL | P0 | CLOSED (2026-10-18) | Owner attests historical values were development-only and revoked/replaced; current-tree scan, startup validation, and redaction pass | SE / W1 |
| BIA-007 | DEFECT / CRITICAL | P1 | RECLASSIFY priority | Kafka, Redis, ClickHouse need production identity/TLS boundaries | SE / W2–10 |
| BIA-008 | DEFECT / CRITICAL | P0 | RECLASSIFY architecture | Source ownership and credential lifecycle are unsafe; create logical Integration domain first | SE / W1–3 |
| BIA-009 | DEFECT / CRITICAL | P0 | RECLASSIFY evidence | Durable job model exists as an unwired/broken skeleton; active flows remain non-durable | BOTH / W2–3 |
| BIA-010 | DEFECT / CRITICAL | P0 | CLOSED (2026-10-14) | Live ClickHouse bounds/cancellation and real PostgreSQL multi-worker admission/recovery are verified | SE / W1–2 |
| BIA-011 | DEFECT / CRITICAL | P0 | CLOSED (2026-10-18) | Live CSV/XLSX/SQLite/audio, ClamAV, tenant isolation, private-path redaction, bounded TTL, and cleanup pass | SE / W1-W2 |
| BIA-012 | FEATURE | P1 | CONVERT_TO_FEATURE | PostgreSQL-first continuous CDC foundation | SE / W3–6 |
| BIA-013 | DEFECT / HIGH | P1 | KEEP_AS_IS | Report service is a proxy over Voice plus an unwired duplicate | SE / W2–4 |
| BIA-014 | DEFECT / HIGH | P1 | KEEP_AS_IS | Source model permits one source per manager and destructive replacement | SE / W2–4 |
| BIA-015 | DEFECT / HIGH | P1 | KEEP_AS_IS | Gateway rate limiting is process-local; proxy timeout/capacity policy is unsafe | SE / W2, W10 |
| BIA-016 | DEFECT / HIGH | P1 | RECLASSIFY evidence | Invalid Kafka schema records can become poison records without DLQ/terminal policy | SE / W3–5 |
| BIA-017 | DEFECT / HIGH | P1 | KEEP_AS_IS | Legacy metadata projection drops workspace/dataset/job scope from stored status | SE / W3–5 |
| BIA-018 | DEFECT / HIGH | P1 | KEEP_AS_IS | Destination validation retains a DNS rebinding window | SE / W2–3 |
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
| BIA-030 | DEFECT / MEDIUM | P2 | KEEP_AS_IS | APIs expose physical ClickHouse storage identifiers | SE / W3–4 |
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

### BIA-006 — historical secret exposure

**Closed 2026-10-18 on owner operational attestation plus technical verification.** The owner confirms all identified historical values were development-only, none was a production credential, applicable provider/platform credentials were revoked/deleted/replaced, and the historical ETL encryption key has no production ciphertext dependency. Current-tree pinned Gitleaks scanning, production placeholder/startup checks, CI scan dependency, recursive log redaction, and tenant credential protection pass. Historical text may remain in Git history, but is not evidence that an old credential is still valid. History purge is recommended optional hygiene, not a closure requirement; no history rewrite occurred. Provider-side revocation was owner-attested rather than independently rechecked. See `37_FOUNDATION_B_EXTERNAL_BOUNDARY_IMPLEMENTATION.md`.

### BIA-008 — safe source foundation

Query currently owns a one-per-manager `Database`, stores source configuration, exposes physical identifiers, and deletes old physical data before replacement success. ETL encryption derives Fernet from `CREDENTIAL_SECRET_KEY` with static salt `etl-pipeline-salt` and no key version. **Accept:** logical Integration owner, persistent multi-source model, opaque versioned secret refs, staged replace/cutover/rollback, direct-secure transport policy, and audited lifecycle.

### BIA-009 — durable jobs before agent growth

Active Voice views and AI Dagster calls are synchronous. `VoicePipelineJob` and orchestration modules exist, but orchestration imports missing `domain/statuses.py` and three infrastructure clients and is not wired to active routes/workers. **Accept:** one persisted job contract with `QUEUED/RUNNING/RETRYING/SUCCEEDED/FAILED/CANCELLED`, attempts, idempotency/correlation, cancellation, result/error references, outbox/events, workers, and false-success tests.

### BIA-010 — bounded analytical execution

**Closed 2026-10-14.** Query validates bounded startup configuration and applies read-only, execution-time, row, result-byte, bytes-read, and memory settings per request. It wraps results in a bounded page window, caps serialized output, reports explicit truncation/next-page semantics, creates workspace-scoped cancellation IDs, emits safe structured telemetry, and uses PostgreSQL advisory-lock slots for distributed per-workspace admission with connection-close stale recovery. Live validation used the repository Compose stack, ClickHouse `26.2.3.2`, PostgreSQL `18.3`, and the rebuilt Query service. The configured policy was accepted by the real server; normal execution, the 10,000-row window, 1,000-row page ceiling, 5 MiB response bound, read-only mode, real timeout, practical bytes-read and memory limits, and safe typed failures all passed. An authenticated long-running request was visible in `system.processes` under its workspace/request-derived ID; a different workspace received `cancelled=false`, the authorized cancellation stopped the real query with `QUERY_CANCELLED`, the server process disappeared, and a following query succeeded. Four distinct Query worker processes proved same-workspace `A/B admitted, C limited`, different-workspace independence, normal and exception release, and stale-lock recovery after process termination. A bounded 20-request abuse check preserved page limits and rejected all cross-workspace dataset attempts; Query memory moved only from 115.2 MiB to 119 MiB and all temporary metadata/tables were removed. The live run exposed and corrected only the required driver-integration details: per-thread ClickHouse sessions, the driver's supported per-query `query_id` transport parameter, accurate no-target cancellation, and ClickHouse 26 limit-error classification. All maintained regressions then passed with no skips.

### BIA-011 — upload boundary

**Closed 2026-10-18.** Public Gateway CSV, XLSX, and SQLite uploads completed through Query, Connector, Kafka, Extractor, Loader, and ClickHouse with cross-workspace denials and staged-source cleanup. Live ClamAV clean/EICAR/outage checks passed; Connector, Voice, and AI startup cleanup removed old generated files while retaining fresh and unrelated files. A valid WAV completed public Voice → AI under the configured small model (HTTP 200); malformed WAV returned 400 and both private audio areas were empty after processing. Recursive AI trace redaction removed an internal audio path found by the live gate. SQLite prepare has a 24-hour token TTL, snapshot dispatch refreshes the staging clock, and Query/Extractor enforce a 30–3,600 second queue/processing window; near-expiry and stale-token live probes passed. Filename, content, size, archive, duration, tenant, and private-storage tests passed. See `37_FOUNDATION_B_EXTERNAL_BOUNDARY_IMPLEMENTATION.md`.

## Feature—not-defect policy

BIA-012, 022, 023, 024, 025, and 033 are required Week-14 capabilities but their absence is not classified as a current defect. Defects that would make those features unsafe remain separately tracked (for example BIA-008/009/019/021/026). This preserves urgency without inflating severity.

Detailed v1 evidence remains in repository history and the other audit files. Reconciliation decisions and path-level evidence are indexed in `28_AUDIT_RECONCILIATION_CHANGELOG.md`.
