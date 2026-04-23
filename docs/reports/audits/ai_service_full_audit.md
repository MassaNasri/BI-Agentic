# AI Service Full Audit Report

## 1. Executive Summary
The `services/ai-service` module has strong progress in deterministic SQL hardening, schema-aware preprocessing, and end-to-end tracing, but it is still **fragile for production** due to inconsistent stage contracts, broad fallback-to-success behavior, mixed legacy/new pipelines, and security defaults that are unsafe if exposed directly.

Overall assessment:
- Reliability: **Medium-Low** (works for many happy paths, but degrades non-deterministically under errors)
- Safety: **Medium** (SQL guardrails are present; service-level security defaults are weak)
- Maintainability: **Medium-Low** (duplicated/legacy code paths increase regression risk)
- Production readiness: **Not fully ready** without targeted hardening.

Most critical issues:
1. Contract mismatch between query execution and visualization (`query` field dropped) causing heuristic blind spots.
2. Deferred schema validation still marked as success, which can mask real schema mismatch until later stages.
3. Forecasting downstream failures frequently converted to success/historical-only, reducing fault transparency.
4. Coexistence of Dagster and legacy pipelines creates drift and inconsistent behavior.
5. Django security posture (`DEBUG=True`, wildcard hosts/CORS, CSRF-exempt endpoints) is unsafe unless strictly isolated behind trusted internal routing.

## 2. Service Architecture Overview
Primary flow (current intended Dagster path):
1. `whisper_app`/`llm_app` views call Dagster orchestration (`run_full_ai_pipeline`).
2. `transcription_asset` obtains text (or direct text input path).
3. `preprocessing_low_asset` cleans filler/noise and normalizes text.
4. `intent_classification_asset` classifies analytical/predictive/conversational.
5. `preprocessing_high_asset` performs schema-aware correction/validation and routing hints.
6. `intent_extraction_asset` extracts structured intent (LLM + deterministic fallback).
7. `routing_asset` chooses `metabase` (analytical) or `forecasting`.
8. `query_execution_asset` builds/reviews/validates SQL and executes ClickHouse query.
9. `visualization_asset` (metabase route) or `forecasting_asset` (forecast route) prepares downstream payload.
10. `pipeline_result_asset` composes final response and full trace.

Legacy/parallel flow still present:
- `whisper_app/transcription_task.py` can fall back to `_run_legacy_whisper_transcription_preprocess_intent`.
- `shared/pipeline.py`, `llm_app/generator.py`, `llm_app/intent_service.py` remain as older non-Dagster path components.

Architecture sketch:
```text
HTTP (whisper/llm endpoints)
  -> Dagster Job (jobs.py)
      -> transcription
      -> preprocessing_low
      -> intent_classification
      -> preprocessing_high
      -> intent_extraction
      -> routing
      -> query_execution (SQL build/review/validate/execute)
      -> visualization OR forecasting
      -> pipeline_result + pipeline_trace
```

## 3. Files Inspected
### Entrypoints / API
- `services/ai-service/backend/urls.py`
- `services/ai-service/whisper_app/views.py`
- `services/ai-service/whisper_app/urls.py`
- `services/ai-service/llm_app/views.py`
- `services/ai-service/llm_app/urls.py`
- `services/ai-service/reasoning_app/views.py`
- `services/ai-service/reasoning_app/urls.py`

### Dagster orchestration
- `services/ai-service/dagster_pipeline/__init__.py`
- `services/ai-service/dagster_pipeline/definitions.py`
- `services/ai-service/dagster_pipeline/jobs.py`
- `services/ai-service/dagster_pipeline/assets/__init__.py`
- `services/ai-service/dagster_pipeline/assets/transcription.py`
- `services/ai-service/dagster_pipeline/assets/preprocessing_low.py`
- `services/ai-service/dagster_pipeline/assets/intent_classification.py`
- `services/ai-service/dagster_pipeline/assets/preprocessing_high.py`
- `services/ai-service/dagster_pipeline/assets/intent_extraction.py`
- `services/ai-service/dagster_pipeline/assets/routing.py`
- `services/ai-service/dagster_pipeline/assets/execution.py`

### Whisper / transcription
- `services/ai-service/whisper_app/transcription_task.py`

### Preprocessing low
- `services/ai-service/preprocessing_low/preprocess_task.py`
- `services/ai-service/preprocessing_low/llm_client.py`
- `services/ai-service/preprocessing_low/cleaners.py`
- `services/ai-service/preprocessing_low/error_handler.py`
- `services/ai-service/preprocessing_low/schemas.py`

### Preprocessing high
- `services/ai-service/preprocessing_high/preprocess_high_task.py`
- `services/ai-service/preprocessing_high/llm_client.py`
- `services/ai-service/preprocessing_high/schema_loader.py`
- `services/ai-service/preprocessing_high/diagnostics.py`
- `services/ai-service/preprocessing_high/error_handler.py`
- `services/ai-service/preprocessing_high/schemas.py`

### Intent extraction / routing
- `services/ai-service/intent_extraction/intent_extraction_task.py`
- `services/ai-service/intent_extraction/llm_extractor.py`
- `services/ai-service/intent_extraction/validation.py`
- `services/ai-service/intent_extraction/routing.py`
- `services/ai-service/intent_extraction/predictive_parser.py`
- `services/ai-service/intent_extraction/error_handler.py`
- `services/ai-service/intent_extraction/schemas.py`

### Classification / reasoning
- `services/ai-service/reasoning_app/intent_classification_task.py`
- `services/ai-service/reasoning_app/llm_intent_client.py`
- `services/ai-service/reasoning_app/graph.py`
- `services/ai-service/reasoning_app/runner.py`
- `services/ai-service/reasoning_app/states.py`
- `services/ai-service/reasoning_app/nodes/intent_llm_node.py`
- `services/ai-service/reasoning_app/nodes/routing_node.py`

### Shared SQL / schema / chart / trace / guards
- `services/ai-service/shared/query_planner.py`
- `services/ai-service/shared/sql_compiler.py`
- `services/ai-service/shared/sql_review.py`
- `services/ai-service/shared/sql_validator.py`
- `services/ai-service/shared/chart_recommender.py`
- `services/ai-service/shared/schema_utils.py`
- `services/ai-service/shared/schema_filtering.py`
- `services/ai-service/shared/dataset_binding.py`
- `services/ai-service/shared/pipeline_guards.py`
- `services/ai-service/shared/pipeline_trace.py`
- `services/ai-service/shared/preprocessing_transparency.py`
- `services/ai-service/shared/error_response.py`
- `services/ai-service/shared/input_classifier.py`
- `services/ai-service/shared/pipeline.py` (legacy)
- `services/ai-service/shared/intent_normalizer.py` (legacy)
- `services/ai-service/shared/intent_schema.py` (legacy)
- `services/ai-service/shared/intent_validator.py` (legacy)
- `services/ai-service/shared/intent_sanitizer.py` (legacy)

### Forecasting
- `services/ai-service/forecasting/pipeline.py`
- `services/ai-service/forecasting/timesfm_service.py`
- `services/ai-service/forecasting/dagster_handler.py`

### LLM app legacy/support
- `services/ai-service/llm_app/intent_service.py`
- `services/ai-service/llm_app/llm_client.py`
- `services/ai-service/llm_app/prompt_builder.py`
- `services/ai-service/llm_app/response_parser.py`
- `services/ai-service/llm_app/schema_provider.py`
- `services/ai-service/llm_app/generator.py`

### Settings / misc
- `services/ai-service/backend/settings.py`
- `services/ai-service/backend/asgi.py`
- `services/ai-service/backend/wsgi.py`
- `services/ai-service/manage.py`
- `services/ai-service/reasoning_app/debug_openrouter.py`
- `services/ai-service/requirements.txt`
- `services/ai-service/forecasting/requirements.txt`

### Tests inspected
- `services/ai-service/tests/test_pipeline_integration.py`
- `services/ai-service/tests/test_bi_hardening.py`
- `services/ai-service/tests/test_pipeline_guards.py`
- `services/ai-service/tests/test_whisper_llm_chart_propagation.py`
- `services/ai-service/tests/test_forecasting_pipeline.py`
- `services/ai-service/tests/test_preprocessing_high_recovery.py`
- `services/ai-service/preprocessing_high/tests_recovery.py`
- `services/ai-service/preprocessing_high/tests_llm_client.py`
- `services/ai-service/intent_extraction/tests.py`
- `services/ai-service/llm_app/tests.py`
- `services/ai-service/reasoning_app/tests.py`
- `services/ai-service/shared/tests_sql_review.py`
- `services/ai-service/whisper_app/tests.py`

## 4. End-to-End Pipeline Mapping
1. Voice/transcription intake:
- `whisper_app/views.py:95` receives audio; `whisper_app/transcription_task.py` orchestrates.
- If Dagster fails, legacy fallback is used (`whisper_app/transcription_task.py:1183-1193`).

2. Preprocessing low:
- `preprocessing_low/preprocess_task.py` removes fillers/noise, can fallback on LLM failure.

3. Preprocessing high:
- `preprocessing_high/preprocess_high_task.py` loads schema + validates references + corrections.
- Can defer schema failure as warning and continue.

4. Classification:
- `reasoning_app/intent_classification_task.py` combines deterministic + LLM classification.

5. Intent extraction:
- `intent_extraction/intent_extraction_task.py` uses LLM extraction then validation, with deterministic fallback.

6. Routing:
- `dagster_pipeline/assets/routing.py` emits route (`metabase`/`forecasting`) with `status="routed"`.

7. SQL generation:
- `shared/query_planner.py` normalizes analytical IR.
- `shared/sql_compiler.py` compiles SQL.

8. SQL review/safety:
- `shared/sql_review.py` LLM-based review and alignment safeguards.
- `shared/sql_validator.py` read-only policy checks.

9. SQL execution handoff:
- `dagster_pipeline/assets/execution.py` executes ClickHouse query and constructs downstream payload.

10. Forecasting:
- `forecasting/pipeline.py` dataset validation + model fallback (TimesFM/Prophet/naive).
- Integrated via `dagster_pipeline/assets/execution.py` forecasting branch.

11. Chart recommendation:
- `shared/chart_recommender.py` intent + shape-based recommendation.
- Additional priority overrides in `execution.py` downstream stage.

12. Trace/observability:
- `shared/pipeline_trace.py` builds stage-by-stage trace payloads.
- `pipeline_result_asset` aggregates trace and final status.

13. Downstream payload output:
- `llm_app/views.py` and `whisper_app/views.py` package SQL + chart + trace for external services.

## 5. Problems Found
### P1. Query/visualization contract mismatch (fixed in this audit)
- Severity: **High**
- Files: `dagster_pipeline/assets/execution.py`
- Functions: `query_execution_asset`, `_run_downstream_stage`
- Why: `_run_downstream_stage` reads `query_execution_result.get("query", "")` (`execution.py:1134`), but successful `query_execution_asset` payload previously omitted `query`.
- Failure: time-series textual heuristics can silently not trigger when intent metadata is weak.
- Scenario: user asks “sales over time”; if time flags are partial, chart may degrade from line to table/card.
- Type: bug/contract inconsistency.

### P2. Deferred schema invalidity still marked successful
- Severity: **High**
- Files: `preprocessing_high/preprocess_high_task.py`
- Function: `run_preprocess_high`
- Why: unresolved/unsupported terms can produce `schema_validation_deferred` warnings (`:677`), yet stage logs/returns success with `schema_valid=True` (`:695`) and success payload.
- Failure: upstream appears green while semantic mismatch is pushed downstream, causing late hard failures or wrong SQL.
- Scenario: unresolved business metric passes preprocessing, fails later in routing/execution.
- Type: weakness/design inconsistency.

### P3. Mixed status contracts (`routed` vs `success`)
- Severity: **Medium**
- Files: `dagster_pipeline/assets/routing.py`, `dagster_pipeline/assets/execution.py`
- Function: `routing_asset`, `pipeline_result_asset`
- Why: routing returns `status="routed"` (`routing.py:121-122`) while most stages use `success/failed/skipped`; downstream must special-case this (`execution.py:1681-1683`, `1875`).
- Failure: fragile cross-stage checks and increased regression risk.
- Scenario: new consumer expects standardized status and misinterprets route output.
- Type: inconsistency.

### P4. Forecasting downstream exception mapped to success
- Severity: **High**
- Files: `dagster_pipeline/assets/execution.py`
- Function: `_run_downstream_stage`
- Why: on forecasting branch exceptions, return can be `status="success"` with historical-only fallback (`execution.py:1262-1271`).
- Failure: production monitoring undercounts failures; silent quality degradation.
- Scenario: forecasting backend outage appears as successful request with fallback line chart.
- Type: robustness/observability weakness.

### P5. Visualization status expression is logically redundant
- Severity: **Low**
- Files: `dagster_pipeline/assets/execution.py`
- Function: `_run_downstream_stage`
- Why: `visualization_status = "success" if expected_next_step == "metabase" else "success"` (`execution.py:1136`).
- Failure: intent of branching is unclear, hides probable missing condition.
- Scenario: future maintainers assume branch-specific behavior exists when it does not.
- Type: logic smell.

### P6. Legacy fallback path bypasses modern pipeline invariants
- Severity: **High**
- Files: `whisper_app/transcription_task.py`, `shared/pipeline.py`, `llm_app/generator.py`
- Functions: `whisper_transcription_preprocess_intent_flow`, `_run_legacy_whisper_transcription_preprocess_intent`, `process_question`
- Why: Dagster failure falls back to legacy path (`transcription_task.py:1183-1193`) with different schema/routing/review contracts.
- Failure: non-deterministic behavior between requests depending on orchestration health.
- Scenario: same question produces different SQL/chart after transient Dagster import/runtime issue.
- Type: architectural weakness.

### P7. Broad exception handling with silent fallback is pervasive
- Severity: **High**
- Files: multiple (`intent_extraction/*`, `forecasting/pipeline.py`, `execution.py`, preprocessing modules)
- Why: many `except Exception` branches downgrade to fallback flow (often success-like) with limited classification precision.
- Failure: root causes obscured; hard to distinguish model failure, schema failure, infra failure.
- Scenario: model malformed output repeatedly occurs but user sees “success” with heuristic result.
- Type: robustness/observability weakness.

### P8. Retry policies are globally conservative and often capped to 1
- Severity: **Medium**
- Files: `preprocessing_high/schemas.py:117`, `intent_extraction/schemas.py:92`, `reasoning_app/intent_classification_task.py:57`, `dagster_pipeline/__init__.py:6`
- Why: max retries hard-capped to `1` in several stages despite remote-model/network volatility.
- Failure: transient failures escape recovery too early.
- Scenario: one temporary LLM timeout fails stage where a second retry would likely succeed.
- Type: production resilience gap.

### P9. Security defaults are unsafe for externally reachable deployment
- Severity: **Critical** (if service exposed beyond trusted internal network)
- Files: `backend/settings.py`, `whisper_app/views.py`, `llm_app/views.py`, `reasoning_app/views.py`
- Why: `DEBUG=True` (`settings.py:35`), `ALLOWED_HOSTS=["*"]` (`:37`), `CORS_ALLOW_ALL_ORIGINS=True` (`:69`), and multiple `@csrf_exempt` endpoints.
- Failure: expanded attack surface and potential data leakage/debug exposure.
- Scenario: accidental public exposure of AI worker service.
- Type: production/security weakness.

### P10. Stale/duplicate legacy intent modules with corrupted text and prints
- Severity: **Medium**
- Files: `shared/intent_validator.py`, `shared/intent_sanitizer.py`, `shared/intent_normalizer.py`, `shared/intent_schema.py`
- Why: legacy modules contain mojibake and debug prints (`intent_validator.py:175`, `180`, etc.), and are not integrated into modern path.
- Failure: maintenance confusion, accidental imports, behavior drift.
- Scenario: future developer reuses legacy validator and reintroduces inconsistent semantics.
- Type: architectural debt.

### P11. Test discovery breaks without Dagster installed
- Severity: **Medium**
- Files: `dagster_pipeline/__init__.py`
- Why: unconditional `from dagster import ...` import (`__init__.py:3`) causes `unittest discover` to error in lean environments.
- Failure: CI and local audit runs can fail before tests execute.
- Scenario: unit-only environment without Dagster cannot run full discovery.
- Type: tooling/robustness issue.

### P12. Forecasting fallback favors continuity over explicit failure taxonomy
- Severity: **Medium**
- Files: `forecasting/pipeline.py`, `dagster_pipeline/assets/execution.py`
- Why: multiple failure modes collapse to `historical_only` payloads.
- Failure: consumers cannot reliably differentiate “forecast unavailable” from “forecasting subsystem unhealthy.”
- Scenario: model unavailable for days but dashboards still appear healthy.
- Type: observability/contract weakness.

### P13. Hidden production debug script leaks environment key names/values
- Severity: **Low-Medium**
- Files: `reasoning_app/debug_openrouter.py`
- Why: script prints environment keys/values containing OPEN/ROUTER (`:6-9`).
- Failure: accidental credential leakage if executed/logged.
- Scenario: debug run in shared CI log artifacts.
- Type: security hygiene issue.

### P14. Trace/status harmonization still partially manual
- Severity: **Medium**
- Files: `dagster_pipeline/assets/execution.py`, `shared/pipeline_trace.py`
- Why: stage status normalization logic is hand-mapped in many places (e.g., route `routed` -> trace `success`, SQL lifecycle status remapping).
- Failure: future stage additions may emit inconsistent trace semantics.
- Scenario: monitoring dashboards aggregate mismatched statuses.
- Type: architectural inconsistency.

## 6. Root Cause Analysis
Systemic patterns driving many issues:
1. **Dual-stack evolution without full deprecation**: legacy non-Dagster flow coexists with modern Dagster flow.
2. **Availability-over-correctness bias in fallback design**: many branches choose “continue with fallback” and mark success.
3. **Contract drift between stages**: payload fields/statuses evolved independently (e.g., `routed`, missing `query`, manual remaps).
4. **Error taxonomy dilution**: broad exception catches reduce actionable diagnostics.
5. **Security posture assumed internal** but not technically enforced by defaults.

## 7. Missing Capabilities / Gaps
1. Central stage contract schema (typed models for every stage payload and status vocabulary).
2. Strong failure taxonomy and severity channel (degraded vs failed vs fallback-success).
3. Explicit “degraded_success” mode for forecasting/LLM fallback instead of plain success.
4. End-to-end contract tests for every stage handoff (especially visualization inputs).
5. Mandatory runtime guard that disables insecure Django settings in non-dev environments.
6. Formal deprecation plan for legacy pipeline modules and endpoints.
7. Structured observability metrics (fallback_rate, defer_rate, semantic_repair_rate, model_error_rate).

## 8. Recommended Fixes
1. **P0 (Safe/Minimal)**: Standardize stage status enum (`success|failed|rejected|skipped|degraded`) and remove `routed` special-case.
- Files: `routing.py`, `execution.py`, trace consumers.
- Benefit: lower contract fragility.

2. **P0 (Safe/Minimal)**: Introduce explicit `degraded=true` and `degradation_reason` for fallback-success outputs.
- Files: `execution.py`, `forecasting/pipeline.py`, `intent_extraction_task.py`.
- Benefit: honest reliability telemetry.

3. **P1 (Safe/Minimal)**: Stop reporting `schema_valid=True` when status is deferred-invalid; use `schema_valid=False` + `deferred=true`.
- Files: `preprocess_high_task.py`.
- Benefit: earlier and clearer error semantics.

4. **P1 (Safe/Minimal)**: Tighten exception classes and avoid broad `except Exception` where domain exceptions are known.
- Files: preprocessing/intent/forecasting/execution modules.
- Benefit: better retries + diagnosis.

5. **P1 (Safe/Minimal)**: Make unit-test discovery independent of Dagster installation.
- Files: `dagster_pipeline/__init__.py` (lazy import/guard) or test bootstrap.
- Benefit: reliable CI.

6. **P1 (Larger Refactor)**: Retire or isolate legacy pipeline code paths (`shared/pipeline.py`, legacy transcription fallback).
- Benefit: deterministic behavior and lower cognitive load.

7. **P0 (Security)**: production-safe settings profile with `DEBUG=False`, explicit hosts/CORS, restricted CSRF strategy.
- Files: `backend/settings.py`, deployment env.
- Benefit: safer runtime posture.

8. **P2 (Larger Refactor)**: Formal typed contracts (Pydantic/dataclass) per stage and shared compatibility tests.
- Benefit: catches drift before runtime.

## 9. Safe Fixes Applied
### Fix A: Restored `query` field contract from query execution -> visualization
- Changed files:
  - `services/ai-service/dagster_pipeline/assets/execution.py`
- Change:
  - Added `"query": normalized_query` to both success and failed return payloads of `query_execution_asset`.
- Why safe:
  - Additive field only; no existing key behavior changed.
  - Aligns with existing downstream read in `_run_downstream_stage` (`execution.py:1134`).
- Issue addressed:
  - P1 contract mismatch and heuristic blind spot.
- Validation:
  - `python -m unittest services/ai-service/tests/test_pipeline_integration.py` passed (9/9).

## 10. Remaining Risks
1. Forecasting outage may continue to appear as success unless degraded semantics are introduced.
2. Deferred schema validation may still allow semantically broken requests deeper into pipeline.
3. Legacy fallback path can reintroduce inconsistent SQL/chart behavior under orchestration failures.
4. Status contract inconsistency remains (`routed`, manual remaps).
5. Security defaults remain risky if boundary controls are misconfigured.

## 11. Production Readiness Assessment
- NLP robustness: **6/10**
- Intent accuracy: **7/10**
- SQL reliability/safety: **7/10**
- Chart reliability: **6/10**
- Error handling/retry: **5/10**
- Observability/transparency: **6/10**
- Maintainability: **5/10**
- Extensibility: **6/10**

Overall: **6/10 (needs hardening before full production confidence).**

## 12. Roadmap
### Immediate fixes (0-3 days)
1. Adopt degraded-success fields in fallback branches.
2. Correct preprocessing-high schema validity semantics.
3. Harden production settings profile and deployment checks.
4. Guard Dagster imports for test discoverability.

### Short-term improvements (1-2 weeks)
1. Standardize stage status contract and trace mapping.
2. Add stage contract tests for all handoffs.
3. Add fallback-rate metrics and alert thresholds.

### Medium-term architectural improvements (2-6 weeks)
1. Remove/retire legacy non-Dagster execution path.
2. Centralize typed payload models and shared validators.
3. Consolidate duplicate intent logic into one canonical module.

### Advanced future enhancements
1. Confidence-calibrated fallback routing (hard-fail vs degraded-success policy).
2. Semantic benchmark suite with typo/relationship/distribution/time-series/derived-metric scenarios.
3. End-to-end chaos testing for model/API/database outages with SLO instrumentation.