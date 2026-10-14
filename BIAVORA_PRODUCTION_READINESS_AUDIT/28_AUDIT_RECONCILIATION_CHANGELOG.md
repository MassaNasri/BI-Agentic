# 28 — Audit Reconciliation Changelog

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

## Method and outcome

All v1 audit files were reread and the high-impact claims were checked against runtime source, executable configuration, tests, models, and Git path history. Original IDs are retained. Six missing capabilities are converted to planned features. No finding was invalidated or removed, and no new issue ID was necessary. One finding (BIA-009) gained material evidence nuance: a durable job schema/skeleton exists, but it is broken/unwired and does not change the active synchronous behavior.

| ID | Original finding | Original severity / priority | New decision | New severity / priority | Reason | Reverified evidence |
|---|---|---|---|---|---|---|
| BIA-001 | CH authorization not table-scoped | BLOCKER / P0 | KEEP_AS_IS | BLOCKER / P0 | Verified tenant boundary defect | `query_execution.py`; `workspace_db_resolver.py`; `sql/guard.py` |
| BIA-002 | Voice local execution fallback | BLOCKER / P0 | KEEP_AS_IS | BLOCKER / P0 | Verified fail-open Query bypass | `voice_reports/views.py::_execute_query_with_query_service` |
| BIA-003 | Simulated checkout activates subscription | BLOCKER / P0 | SPLIT | BLOCKER / P0 | Disable bypass now; hosted provider may land later before paid launch | `subscription/views.py::SubscribeView`; `SubscriptionPlansPanel.jsx` |
| BIA-004 | Dev Compose/runtime | BLOCKER / P0 | RECLASSIFY | BLOCKER / P1 | Real public-release blocker, but production runtime conversion can proceed alongside safe feature work | first-party `Dockerfile*`, ETL `start.sh`, root Compose |
| BIA-005 | Shared PostgreSQL ownership/credentials | CRITICAL / P0 | RECLASSIFY | CRITICAL / P0 | Fix logical critical owners first; do not require physical server per service | service settings; Notification unmanaged models |
| BIA-006 | Historically committed secrets | CRITICAL / P0 | KEEP_AS_IS | CRITICAL / P0 | Git history still contains tracked `.env.microservices`; values not printed | `git log --all -- .env.microservices` |
| BIA-007 | Infra lacks identity/TLS boundary | CRITICAL / P0 | RECLASSIFY | CRITICAL / P1 | Required before staging/production, but not a missing-feature P0 or prerequisite to all coding | root `docker-compose.yml` Kafka/Redis/CH configuration |
| BIA-008 | No Integration owner/vault lifecycle | CRITICAL / P0 | RECLASSIFY | CRITICAL / P0 | Logical domain is prerequisite for safe persistent sources/CDC; no automatic new container | Query `Database` model/views; `credential_encryption.py` |
| BIA-009 | Long flows synchronous/non-durable | CRITICAL / P0 | RECLASSIFY | CRITICAL / P0 | `VoicePipelineJob` exists, but orchestration imports missing modules and active routes do not enqueue it | `voice_reports/models.py`; `application/job_service.py`; `application/orchestration_service.py`; active views |
| BIA-010 | Query/result unbounded | CRITICAL / P0 | KEEP_AS_IS | CRITICAL / P0 | Verified full materialization and no universal CH resource policy | Query and Voice ClickHouse executors |
| BIA-011 | Upload validation/retention absent | CRITICAL / P0 | KEEP_AS_IS | CRITICAL / P0 | Backend writes chunks before production boundary validation | `voice_reports/views.py::VoiceUploadView` |
| BIA-012 | No CDC | CRITICAL / P0 | CONVERT_TO_FEATURE | FEATURE / P1 | Planned foundational product capability, not a current defect | connector capabilities declare snapshot true / CDC false |
| BIA-013 | Report proxy/duplicate | HIGH / P1 | KEEP_AS_IS | HIGH / P1 | Runtime/duplicate ownership remains verified | Report/Voice routes, models, services |
| BIA-014 | One source/manager and destructive resnapshot | HIGH / P1 | KEEP_AS_IS | HIGH / P1 | Verified delete-before-new-success behavior | Query `database/models.py`, `database/views.py` |
| BIA-015 | Gateway rate/proxy unsafe for scale | HIGH / P1 | KEEP_AS_IS | HIGH / P1 | Rate store remains per-process; upstream default is 360 s | `api-gateway/gateway/middleware.py`, `views.py` |
| BIA-016 | Invalid Kafka restart poison | HIGH / P1 | RECLASSIFY | HIGH / P1 | Manual commit/rewind is stronger than v1 wording; invalid messages are skipped before yield with no commit/DLQ policy | `etl-final/shared/utils/kafka_consumer.py::_iter_messages` |
| BIA-017 | Metadata projection drops scope | HIGH / P1 | KEEP_AS_IS | HIGH / P1 | Stored legacy load status omits workspace/dataset/job fields | Metadata `kafka_listener.py::process_load_status` |
| BIA-018 | DNS rebinding window | HIGH / P1 | KEEP_AS_IS | HIGH / P1 | Existing SSRF controls are strengths; destination-to-use binding remains incomplete | connector destination policy/connectors |
| BIA-019 | Fragmented providers | HIGH / P1 | KEEP_AS_IS | HIGH / P1 | Direct Ollama/OpenRouter/OpenAI paths remain distributed | AI preprocessing, intent, LLM, review, visualization clients |
| BIA-020 | Pending integration marked success | HIGH / P1 | KEEP_AS_IS | HIGH / P1 | Tests/runtime permit successful task result with downstream pending | `intent_extraction/routing.py`; related tests/jobs |
| BIA-021 | Broad AI CH schema/cache | HIGH / P1 | KEEP_AS_IS | HIGH / P1 | Direct CH client enumerates all current DB columns; cache process-global | `ai-service/llm_app/schema_provider.py`; `shared/pipeline.py` |
| BIA-022 | AI eval not release discipline | HIGH / P1 | CONVERT_TO_FEATURE | FEATURE / P1 | Required Week-14 foundation; absence is not a present implementation defect | maintained test runner and AI test corpus inventory |
| BIA-023 | No governed semantic layer | HIGH / P1 | CONVERT_TO_FEATURE | FEATURE / P1 | Foundational planned capability; existing heuristics remain useful input | AI schema/intent/compiler models |
| BIA-024 | RAG lifecycle absent | HIGH / P1 | CONVERT_TO_FEATURE | FEATURE / P1 | Planned product capability, not a defect in claimed runtime | repository search, dependencies, data models |
| BIA-025 | Agents/MCP absent | HIGH / P1 | SPLIT + CONVERT_TO_FEATURE | FEATURE / P1 | Separate governed Analyst orchestration from approval/action execution under stable umbrella ID | AI pipeline; `Plan.has_mcp_access`; no tool gateway |
| BIA-026 | Consume-first quota | HIGH / P1 | KEEP_AS_IS | HIGH / P1 | Row lock is atomic, but no idempotent reservation/finalize/release or usage ledger | subscription `_check_and_optionally_consume` |
| BIA-027 | Docs contradict runtime | HIGH / P1 | DOWNGRADE | MEDIUM / P2 | v2 canonical set resolves planning contradiction; source README cleanup remains | audit/repository documentation comparison |
| BIA-028 | Observability not operating system | HIGH / P2 | UPGRADE_PRIORITY | HIGH / P1 | SLO/telemetry must begin early and support every gate | metrics assets, Compose, service health/logging |
| BIA-029 | Release pipeline gaps | HIGH / P2 | UPGRADE_PRIORITY | HIGH / P1 | Supply-chain and deploy/restore gates require lead time before staging | `.github/workflows`, maintained runner |
| BIA-030 | Physical identifiers exposed | MEDIUM / P2 | KEEP_AS_IS | MEDIUM / P2 | Serializer still includes ClickHouse database/table fields | Query `database/serializers.py` |
| BIA-031 | Browser token/CSP posture | MEDIUM / P2 | KEEP_AS_IS | MEDIUM / P2 | Production XSS impact remains; no evidence invalidates v1 | frontend auth/storage and gateway/security settings |
| BIA-032 | Frontend monolith/bundle | MEDIUM / P2 | KEEP_AS_IS | MEDIUM / P3 | Real maintenance/performance debt, behind production safety work | Vite build: 671.84 kB main chunk warning |
| BIA-033 | Arabic/RTL incomplete | MEDIUM / P2 | CONVERT_TO_FEATURE | FEATURE / P2 | Required product completion and benchmark work, not a current defect | frontend/AI language support and missing benchmark evidence |
| BIA-034 | Duplicate HTTP/readiness coupling | MEDIUM / P2 | KEEP_AS_IS | MEDIUM / P2 | Coupling remains visible in clients/readiness fan-out | service client/readiness code |
| BIA-035 | Report events no consumer/outbox | MEDIUM / P2 | KEEP_AS_IS | MEDIUM / P2 | No verified repository consumer/delivery guarantee | report event producer/search |
| BIA-036 | Generated state tracked | MEDIUM / P2 | KEEP_AS_IS | MEDIUM / P3 | Maintenance debt; deletion remains gated by full dependency checks | tracked/generated artifacts inventory |
| BIA-037 | TimesFM lifecycle unverified | MEDIUM / P2 | KEEP_AS_IS | MEDIUM / P2 | Model artifact/capacity evidence remains absent; dirty submodule preserved | `services/ai-service/forecasting/timesfm` |
| BIA-038 | Broken/dead orchestration/duplicates | MEDIUM / P2 | KEEP_AS_IS | MEDIUM / P2 | Missing orchestration imports strengthen “investigate/migrate before delete” | Voice orchestration modules; duplicate report code |
| BIA-039 | Sensitive SQL/prompts/traces | MEDIUM / P3 | UPGRADE | HIGH / P1 | Raw SQL is logged at error and AI trace can contain tenant context; must close before staging | Query executor logging; Voice/AI trace persistence |
| BIA-040 | Images/dependencies not hardened | MEDIUM / P3 | UPGRADE_PRIORITY | MEDIUM / P1 | Production runtime work needs early supply-chain lead time | Dockerfiles, requirements, CI image jobs |
| BIA-041 | Datetime warnings | LOW / P3 | KEEP_AS_IS | LOW / P3 | Valid low-risk signal debt | test output/source search |
| BIA-042 | Encoding/debug/TODO residue | LOW / P3 | KEEP_AS_IS | LOW / P3 | Valid low-risk maintainability debt | repository source/docs search |

## Count reconciliation

| Measure | v1 | v2 |
|---|---:|---:|
| Blocker defects | 4 | 4 |
| Critical defects | 8 | 7 |
| High defects | 17 | 13 |
| Medium defects | 11 | 10 |
| Low defects | 2 | 2 |
| Planned feature entries | 0 | 6 |
| Total tracked entries | 42 | 42 |
| P0 | 12 | 9 |
| P1 | 15 | 21 |
| P2 | 11 | 8 |
| P3 | 4 | 4 |

The severity arithmetic is `4 + 7 + 13 + 10 + 2 = 36 defects`; adding 6 feature entries returns 42 tracked IDs. Priority arithmetic is `9 + 21 + 8 + 4 = 42`.
