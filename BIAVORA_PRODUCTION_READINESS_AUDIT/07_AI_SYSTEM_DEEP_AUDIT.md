# AI system deep audit

> **v2 canonical alignment:** Current AI production readiness is recalculated to **32%**. Build one in-process `ModelProvider` facade (not a new network service) and emit usage telemetry from its first call in Week 1. AI must not hold broad ClickHouse credentials, enumerate global schema, or execute SQL directly; it receives minimum authorized context through Schema/Semantic tools and executes through Query. The existing `VoicePipelineJob` model is a useful skeleton, but its orchestration imports are missing and the active flow remains synchronous. See `32_CANONICAL_AI_ARCHITECTURE.md`.

## Verdict

BIAVORA has more real AI pipeline code than a typical prototype: Whisper concurrency controls, structured intent, deterministic semantic/temporal rules, schema-aware correction, SQL compilation/review, forecasting, visualization selection, and detailed traces. Its weakness is not absence of code; it is fragmentation, duplication, lack of objective evaluation, broad data access, synchronous execution, and marketing labels (“semantic layer”, “reasoning”, “MCP-ready”) that exceed implemented governance.

Reconciled AI production readiness is **32%** under the stricter public-SaaS baseline. The deterministic core is worth keeping. Production-grade model governance, isolation, cost/latency control, multilingual evidence, and agent/tool boundaries are missing.

## Actual runtime flow

`/api/transcribe/` and `/api/llm/intent/` are internal-key protected and call Dagster jobs through `execute_in_process` inside the Django request.

| Stage | Input/output | Provider / determinism | Failure/fallback and readiness |
|---|---|---|---|
| Request/dataset scope | Audio path or text plus workspace, manager, dataset, selected table | Deterministic validation | Missing scope rejects high preprocessing; good fail-closed seam |
| Transcription | Audio file → text | OpenAI Whisper package, default `large-v3`; nondeterministic/model | Redis FIFO/dedupe/lease, timeout/retry/reload; one global lock serializes work; request waits up to 900s |
| Low preprocessing | Text → cleaned text/change trace | Rules plus Ollama client | Deterministic fallback exists; provider behavior/config fragmented |
| Intent classification | Clean text → analytical/predictive/conversational route | Ollama plus rules | Confidence and routing guards exist; no calibrated benchmark |
| High preprocessing/schema | Query + selected dataset → corrected query/schema diagnostics | Direct ClickHouse schema/value reads, rules, Ollama | Strict selected-table guard is a strength; global all-table cache and broad CH credential are risks |
| Intent extraction | Text/schema → structured intent | Ollama then OpenRouter/raw requests and validators | Structured validation/fallbacks; multiple parser/client semantics |
| Routing/planning | Intent → route and plan | Deterministic | Rules are large, English-lexical, duplicated; no persisted business model |
| SQL generation | Intent/schema → ClickHouse SQL | Deterministic compiler | Strong testability; SQL review may call Ollama |
| SQL review | SQL/question/schema → reviewed SQL | Ollama plus deterministic guards | Rejection can restore compiler SQL; predictive path skips review |
| “Execution” asset | SQL → integration result | Configured callable, empty by default | Empty path returns `pending_integration`, yet the asset marks success and lifecycle “executed”; misleading trace |
| Forecast route | Query rows → TimesFM/fallback forecast rows and inline SQL | TimesFM + fallback rules | Heavy model/capacity artifact unverified; entire rows copied; inline SQL can be huge |
| Visualization | Result/intent → chart hint/spec | AI output then separate visualization-service Ollama selector | Duplicated model call/ownership; Metabase creates actual object |
| Final trace | Every stage → full pipeline trace/confidence | Deterministic aggregation | Valuable for debugging; can expose prompts, schema, errors, data previews, and “reasoning” details |

The actual SQL query shown to users is executed later by voice through query-service. AI's execution integration is normally a placeholder. This creates duplicate concepts and a false “executed” trace.

## Provider and prompt architecture

Provider calls are scattered across:

- `preprocessing_low/llm_client.py` and `preprocessing_high/llm_client.py` (Ollama);
- `reasoning_app/llm_intent_client.py` (Ollama/OpenRouter-style path);
- `intent_extraction/llm_extractor.py` (Ollama then OpenRouter);
- `llm_app/llm_client.py` (OpenRouter through the OpenAI SDK);
- `shared/sql_review.py` (Ollama);
- visualization-service chart selector (Ollama).

There is no unified Model Provider interface, request policy, model registry, structured-output/schema enforcement, token/cost ledger, redaction policy, per-stage deadline, circuit/bulkhead policy, or evaluation tag. Defaults reference free/locally hosted models and `host.docker.internal`; reproducibility depends on mutable external/local model state.

Create one provider facade with typed task contracts, model/version/prompt version, temperature/seed when supported, input classification/redaction, deadline, retry classification, token/latency/cost telemetry, response schema validation, and explicit fallback. The facade is justified; a microservice per model is not.

## Structured output and hallucination controls

Strengths:

- Pydantic/TypedDict-like stage contracts and normalized intent shape;
- validators reject unknown columns/metrics and repair known aggregation mistakes;
- compiler is deterministic and SQL is AST-guarded downstream;
- strict dataset table scope in `get_schema_for_dataset()`;
- compiler output is preserved when LLM SQL review drifts.

Gaps:

- `safe_json_parse` relies partly on greedy extraction rather than provider-native JSON schema;
- degraded schema validation can continue, and confidence numbers are heuristic rather than calibrated probabilities;
- prompts and response traces have no immutable version/evaluation linkage;
- generated SQL safety is undermined by the query boundary's missing table allowlist and voice fallback;
- no prompt-injection suite covers schema names, row values, documents, or tool instructions;
- no result-level semantic verifier compares the answer with returned rows/metric definitions.

## Schema and tenant isolation

AI connects directly to ClickHouse, queries every table in `currentDatabase()` into `_SCHEMA_CACHE`, and then filters to the selected table. Strict filtering is used in the active high-preprocessing path and is a meaningful control. However:

- cache is global, not keyed by database/workspace and not synchronized;
- the service credential can see all workspace schemas and sample values;
- value-index correction queries customer columns directly;
- error/trace payloads can retain schema and value hints;
- legacy calls to `get_schema()` without scope remain possible;
- AI should not be a second data authorization plane.

Target: AI calls a query/semantic schema tool with `(workspace, dataset)` and receives a minimal authorized schema/value dictionary. Use purpose-limited service identity, explicit PII classification, capped value samples, and no customer values in model prompts unless policy permits.

## “Semantic layer” reality

`shared/bi_semantic_layer.py`, temporal semantics, intent sanitizers, and `bi_platform_shared/semantic/intent_priority.py` are hardcoded lexical/type heuristics. They are useful semantic reasoning utilities, but not a governed semantic layer. There are no persisted metrics, dimensions, entities, relationships, formulas, owners, certification, versions, lineage, or workspace publication lifecycle. Multiple modules repeat intent/temporal/semantic concepts, and some contain debug prints/encoding corruption.

## Voice and Arabic

Whisper accepts a `language` and `initial_prompt`, supports common extensions, limits input only inside the AI worker (default 500 MB), and serializes inference through Redis. Voice-service first writes any uploaded content to disk without MIME/magic validation, malware scanning, retention, or cleanup, then asks AI to validate by extension/size. Failed files remain.

No Arabic-specific normalization, diacritic handling, Arabic/Indic digit conversion, currency/date lexicon, dialect/code-switch benchmark, or RTL product mode was found. Frontend HTML declares English and has no i18n framework. Whisper's generic multilingual ability is not evidence of Arabic product support.

## Forecasting and what-if

Forecasting detects temporal/value columns, caps context/horizon, tries TimesFM, and returns fallback metadata/quantiles where available. TimesFM is a dirty submodule with v1/v2-era code and no checked production capacity/model-fetch certification. The AI Docker requirements and forecast-specific heavy requirements are fragmented. Query rows are posted inline; output may be converted to inline ClickHouse SQL for Metabase.

Forecasting is not a what-if engine. There is no scenario entity, baseline version, assumption set, reproducibility hash, elasticity/causal model, or calibration evaluation. Week-14 production should support descriptive recomputation and explicitly labeled forecast scenarios only; causal claims require separate evidence.

## RAG, agents, and MCP

No operational document ingestion, embedding job, vector index, retrieval/reranking, document ACL, citation, or deletion flow was found. LangChain/LangGraph dependencies and a small legacy reasoning graph do not constitute RAG or an agent platform.

There is no tool registry, planner loop, action policy, approval state, MCP client/gateway, or audit execution. `Plan.has_mcp_access` is an entitlement flag only. The target should be one governed analyst orchestrator with typed tools; multi-agent separation is not justified.

## Observability, cost, and reproducibility

Pipeline traces record attempts, timings, models/methods, inputs/outputs, Dagster events, errors, and a UI displays them. This is a solid debugging foundation. Missing are:

- metrics by model/prompt/version, workspace, stage, route, success, timeout, fallback;
- tokens and estimated/actual cost;
- queue depth/GPU memory/model load/cold-start/capacity;
- quality scores linked to evaluation datasets;
- prompt/model registry and reproducible run manifest;
- safe sampling/redaction and retention;
- SLOs and alerts.

Do not expose private chain-of-thought. Replace free-form “reasoning” with concise decision summaries, evidence, selected tools, policy checks, SQL, data sources, assumptions, and warnings.

## Keep / refactor / retire

- **KEEP:** structured intent contracts, deterministic compiler/planner, AST guard concept, schema validation, Whisper queue/idempotency, trace schema, forecast metadata, chart contract.
- **REFACTOR:** provider clients into one facade; Dagster request execution into durable job/worker; schema access into authorized tool; confidence into calibrated/evidenced signals; semantic rules behind a governed model.
- **MERGE:** duplicate intent/semantic priority and query-planning concepts after characterization tests.
- **RETIRE/ARCHIVE after evidence:** legacy `reasoning_app` graph/debug client and unwired alternate orchestration code; do not delete during this audit.
- **ADD:** evaluation harness, prompt/model registry, cost ledger, agent tool policy, Arabic datasets, RAG/knowledge only after semantic/ACL foundations.
