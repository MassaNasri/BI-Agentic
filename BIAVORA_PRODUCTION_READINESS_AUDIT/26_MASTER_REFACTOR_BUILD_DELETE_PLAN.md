# 26 — Master Refactor, Build, Move, and Delete Plan

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

## How to use this map

This is the implementation map, not evidence that work is complete. `SE`, `AI`, and `BOTH` are the two-person team allocation. “Risk” is the production harm if omitted. Every deletion requires imports, routes, Compose, tests, CI, runtime, and migration dependencies to be checked first. No deletion is authorized by this document alone.

## KEEP

| ID | Current location | Problem → target state / reason | Priority / risk | Dependencies | Owner / week | Acceptance criterion |
|---|---|---|---|---|---|---|
| MAP-001 | `etl-final` connector registry/adapters | Strong snapshots → preserve behind versioned capability/transport contract; avoid redesigning P1-R | P1 / regression | Integration API | SE / W2–6 | All current snapshot regression tests and engine capability claims pass |
| MAP-002 | ETL manual commit, rewind, idempotency utilities | Useful recovery pieces → retain and add terminal invalid-record semantics | P1 / loss or poison | Event ADR | SE / W3–5 | Restart/duplicate/poison/replay suite passes |
| MAP-003 | `bi_platform_shared/sql/guard.py` parser | Database-only invocation is unsafe → keep parser but require exact allowlist/resource policy | P0 / tenant breach | Query binding | BOTH / W1–2 | No call can execute without authorized table set |
| MAP-004 | Deterministic AI compiler/planner/tests | Valuable behavior lacks governance → retain under semantic/provider/tool versions | P1 / quality drift | Provider + semantic | AI / W1–10 | Golden suites improve without bypass paths |
| MAP-005 | Workspace checks, CI/migration/security regression assets | Incomplete but valuable → extend, do not replace | P1 / release regression | Owner map | BOTH / all | New gates reuse and expand maintained runner |

## FIX_NOW

| ID | Current location | Current problem → target state / reason | Priority / risk | Dependencies | Owner / week | Acceptance criterion |
|---|---|---|---|---|---|---|
| MAP-010 / BIA-001 | Query execution + SQL guard call | Database-scoped policy → logical dataset binding + exact table allowlist + CH limits | P0 / tenant breach | None | SE+BOTH / W1–2 | Cross-tenant and arbitrary-table tests fail closed |
| MAP-011 / BIA-002 | Voice query fallback | Local CH execution on Query outage → Query-only durable failure/retry | P0 / auth bypass | MAP-010, jobs | SE / W1–2 | Voice holds no execution credential/fallback |
| MAP-012 / BIA-003 | Subscription view/frontend | Simulated success activates access → production simulation disabled; provider later | P0 / financial integrity | Config/entitlement | SE / W1 | Production-mode test rejects simulated activation |
| MAP-013 / BIA-006 | Git/runtime secrets | Historical tracked env → rotate/invalidate and managed references | P0 / credential compromise | Secret inventory | SE / W1 | Rotation evidence and clean secret scan |
| MAP-014 / BIA-010 | Query/Voice executors | Unbounded query/materialization → enforced limits, page/result ref, cancellation | P0 / outage/cost | MAP-010 | SE / W1–2 | Abuse/load tests prove bounded resources |
| MAP-015 / BIA-011 | Voice upload endpoint/storage | Writes untrusted file before validation → streaming validation/quarantine/retention | P0 / malware/DoS/data leak | Object storage/AV | SE / W1–2 | Adversarial upload suite and deletion evidence pass |

## REFACTOR_BEFORE_FEATURE

| ID | Current location | Current problem → target state / reason | Priority / risk | Dependencies | Owner / week | Acceptance criterion |
|---|---|---|---|---|---|---|
| MAP-020 / BIA-005 | Django DB settings/models | Shared owner role/schema → critical owner schemas/roles; one cluster allowed | P0 / lateral data access | Owner ADR | SE / W1–3 | Cross-owner writes denied; reversible migration passes |
| MAP-021 / BIA-008/014 | Query `Database`, source lifecycle | One source/manager, raw config, destructive replace → persistent Integration aggregate, secret refs, staged cutover | P0 / loss/secrets/CDC unsafe | MAP-020 | SE / W1–4 | Multi-source, rotation, failed-cutover tests pass |
| MAP-022 / BIA-009/020 | Voice jobs, AI Dagster request path | Unwired job skeleton/synchronous false success → common durable worker state machine | P0 / lost/false work | Outbox/queue | BOTH / W2–3 | Retry/cancel/idempotency/terminal tests pass |
| MAP-023 / BIA-019 | AI provider clients | Direct fragmented calls → in-process provider facade + telemetry | P1 / cost/reliability blind | Eval registry | AI / W1–2 | Active calls use facade; usage fields complete |
| MAP-024 / BIA-021 | AI schema provider/cache | Broad direct CH enumeration/global cache → authorized Schema/Semantic tools, tenant/version key | P1 / tenant leak | MAP-010 | BOTH / W1–3 | AI has no CH credential; tenant cache tests pass |

## REFACTOR_DURING_FEATURE

| ID | Current location | Current problem → target state / reason | Priority / risk | Dependencies | Owner / week | Acceptance criterion |
|---|---|---|---|---|---|---|
| MAP-030 / BIA-012/016/017 | ETL/Kafka pipeline | Snapshot plus incomplete terminal/scoped semantics → PostgreSQL CDC, versioned envelope, DLQ/replay/status | P1 / corrupt/stuck pipeline | MAP-021, event ADR | SE / W3–6 | `CDC_GATE` passes |
| MAP-031 / BIA-023 | AI/schema/query context | Heuristics only → governed semantic owner, versions/status/certification/lineage | P1 / inconsistent answers | Query owner | BOTH / W4–8 | `SEMANTIC_GATE` passes |
| MAP-032 / BIA-024 | No knowledge lifecycle | No RAG → ACL/version/delete/re-index/citations on pgvector | P1 / tenant/content risk | Jobs, object store | AI / W7–9 | ACL, delete, injection, citation tests pass |
| MAP-033 / BIA-025 | AI pipeline/subscription flag | No governed tools/actions → one bounded orchestrator + proposal/approval gateway | P1 / autonomous writes | Semantic, jobs, identity | BOTH / W8–11 | `AI_AGENT_GATE`; replay/expiry fail closed |
| MAP-034 / BIA-026 | Quota counters | Consume-first counter → usage events + reservation/commit/release ledger | P1 / over/under billing | Provider telemetry | SE / W1, W9–11 | Concurrent retry/reconciliation tests pass |
| MAP-035 / BIA-033 | Voice/frontend | Partial language support → benchmarked Arabic voice + RTL user journey | P2 / exclusion/quality | Evaluation + upload | AI / W1, W7–11 | Accepted corpus thresholds and RTL E2E pass |
| MAP-036 / BIA-028 | Metrics/logs | Assets without operating ownership → SLOs, dashboards, alerts, runbooks | P1 / undetected incidents | Telemetry backend | SE / W2–14 | Alert drills route to named owner |

## MOVE

| ID | Current location | Current problem → target state / reason | Priority / risk | Dependencies | Owner / week | Acceptance criterion |
|---|---|---|---|---|---|---|
| MAP-040 / BIA-008 | Query source model/API | Query owns source business lifecycle → Integration logical module/schema, initially same deployment | P0 / ownership drift | MAP-021 | SE / W2–4 | Public APIs and migrations have one owner; no duplicated write path |
| MAP-041 / BIA-002/021 | Voice/AI direct CH paths | Multiple execution authorities → authorized Query/Schema tools | P0/P1 / bypass | MAP-010/024 | BOTH / W1–3 | Credential inventory proves sole product executor |
| MAP-042 / BIA-030 | Public serializers | Physical database/table names leak → internal binding record only | P2 / reconnaissance/coupling | Integration/Query API | SE / W3–4 | Public contract exposes logical IDs only |

## MERGE

| ID | Current location | Current problem → target state / reason | Priority / risk | Dependencies | Owner / week | Acceptance criterion |
|---|---|---|---|---|---|---|
| MAP-050 / BIA-013/035 | Report proxy + Voice report persistence | Proxy/duplicate/no consumer → one Report owner; Query executes, Visualization specifies | P1 / split truth | Jobs/events | SE / W3–8 | One write model/route; migration and event consumer/outbox pass |
| MAP-051 / BIA-019 | Multiple LLM/OpenAI/Ollama clients | Policy/telemetry fragments → provider facade library | P1 / cost/safety drift | MAP-023 | AI / W1–3 | Direct-call allowlist is empty except facade adapters |

## SPLIT

| ID | Current location | Current problem → target state / reason | Priority / risk | Dependencies | Owner / week | Acceptance criterion |
|---|---|---|---|---|---|---|
| MAP-060 / BIA-003/026 | Subscription service | Plan, entitlement, counter, fake payment conflated → Entitlements, Metering Ledger, Billing State, Provider adapter | P0/P1 / financial error | Usage telemetry | SE / W1, W9–12 | Owned states/events and reconciliation tests pass |
| MAP-061 / BIA-025 | Agent/action scope | “Agents and MCP” conflated → Analyst tool orchestration vs separately isolated approval/action execution | P1 / unsafe autonomy | Identity/policy | BOTH / W8–11 | Analyst cannot execute write action directly |

## DELETE_SAFE

| ID | Current location | Current problem → target state / reason | Priority / risk | Dependencies | Owner / week | Acceptance criterion |
|---|---|---|---|---|---|---|
| MAP-070 / BIA-036 | Tracked bytecode/generated engine state | Noise/stale artifacts → ignore and remove only generated files proven reproducible | P3 / drift | Inventory | SE / W12 | Import/route/CI/runtime checks clear; clean regeneration works |

## DELETE_AFTER_MIGRATION

| ID | Current location | Current problem → target state / reason | Priority / risk | Dependencies | Owner / week | Acceptance criterion |
|---|---|---|---|---|---|---|
| MAP-080 / BIA-013/038 | Duplicate report models/routes | Unwired alternative obscures truth → remove after Report data/route migration | P2 / accidental revival | MAP-050 | SE / W8–12 | No import/route/Compose/test/CI/migration dependency; backup retained |
| MAP-081 / BIA-019 | Direct provider clients | Legacy paths bypass facade → delete after call-site migration/eval parity | P2 / policy bypass | MAP-051 | AI / W3–10 | Static scan + runtime tests show no bypass |
| MAP-082 / BIA-009/038 | Broken Voice orchestration modules | Missing imports/unwired skeleton → either migrate useful state model or remove obsolete implementation | P2 / confusion | MAP-022 | BOTH / W3–12 | Runtime/route/import/migration audit and job migration complete |

## ADD

| ID | Current location | Current problem → target state / reason | Priority / risk | Dependencies | Owner / week | Acceptance criterion |
|---|---|---|---|---|---|---|
| MAP-090 / BIA-022 | Test/eval tooling | No model-quality release gate → corpora, harness, registry, thresholds, reports | P1 / silent AI regression | Provider facade | AI / starts W1 | Every AI feature has versioned cases and gate |
| MAP-091 / BIA-004/040 | Docker/deployment | Dev runtime/root/unlocked → production servers, non-root immutable images, managed staging/prod | P1 / public outage/compromise | Platform choice | SE / W10–14 | Runtime/scan/deploy/rollback gates pass |
| MAP-092 / BIA-029 | CI/CD | Incomplete release evidence → SBOM/sign/scan/integration/eval/restore/deploy approvals | P1 / unsafe release | Staging | SE / W10–13 | Signed candidate satisfies release policy |
| MAP-093 | Knowledge plane | No document owner/vector lifecycle → PostgreSQL+pgvector, object store, ACL jobs | P1 / RAG absent/unsafe | MAP-022/031 | BOTH / W7–9 | RAG production tests pass |
| MAP-094 | Reliability/proactive/What-if | Partial signals/forecast only → bounded governed capabilities | P1 / misleading product | Semantic/Trust | AI / W8–11 | Evidence/uncertainty/alert tests pass |
| MAP-095 | Payment provider | Fake payment only → hosted/tokenized provider + signed webhooks if paid launch | P1 / financial integrity | MAP-060 | SE / W11–12 | Staging reconciliation/refund/failure tests pass or paid launch disabled |

## DEFER

| ID | Current location | Current problem → target state / reason | Priority / risk | Dependencies | Owner / week | Acceptance criterion |
|---|---|---|---|---|---|---|
| MAP-100 | MySQL/MariaDB CDC | Adapter does not prove CDC → certify only after PostgreSQL; otherwise snapshot claim | P2 / overcommit | CDC Gate + capacity | SE / conditional W6–9 | Same production CDC suite passes before claim |
| MAP-101 | MSSQL/Oracle/ClickHouse/SQLite continuous modes | Contracts/snapshots only → keep honest mode matrix | POST_LAUNCH / false claims | Engine labs | SE / later | Marketing/API capability agrees with certified tests |
| MAP-102 / BIA-032/041/042 | Broad cleanup/performance polish | Useful but not critical path → address only within release headroom | P3 / maintainability | Gates stable | BOTH / W12 | No release-critical work displaced |

## POST_LAUNCH

| ID | Current location | Current problem → target state / reason | Priority / risk | Dependencies | Owner / week | Acceptance criterion |
|---|---|---|---|---|---|---|
| MAP-110 | Transport | Direct secure only → private network and customer agent without source-model redesign | FUTURE / enterprise reach | Transport discriminator | SE / post | Separate threat model and production certification |
| MAP-111 | Deployment | Single-region managed production → multi-region/active-active only from SLO/business evidence | FUTURE / cost/complexity | Scale evidence | SE / post | Approved business/RTO case |
| MAP-112 | Architecture | Co-deployed logical modules → extract Integration/Model Gateway/vector store only for scale/security/team evidence | FUTURE / microservice sprawl | Metrics/ownership | BOTH / post | ADR proves extraction benefit and migration plan |

## Release traceability

All map rows trace to the weekly gates in `25`, the Definition of Done in `16`, the security stages in `33`, and the issue IDs in `20`. Any implementation prompt that changes a target state must update the canonical set before code is merged.
