# AI Service Final System Audit

Date: 2026-04-23

## Executive Summary
The AI service was re-audited against `ai_service_post_fix_reaudit.md` and hardened across degraded semantics, confidence propagation, schema-to-SQL safety, chart validation, routing consistency, and text/voice response contracts.

Final production readiness score: 9.0/10

## Issues From Post-Fix Audit
- Broad exception handling remained in orchestration, LLM, schema, forecasting, and view boundaries.
- Legacy non-Dagster paths still existed and could drift from canonical stage semantics.
- External clients could misread `degraded` as failure or receive inconsistent confidence fields.
- Schema-invalid high preprocessing could still be allowed to progress into intent extraction and SQL generation in analytical flows.
- Chart fallback behavior needed clearer validation and adjustment reasons.
- Test execution remained import-path sensitive without explicit `PYTHONPATH`.

## Additional Hidden Issues Found
- Low preprocessing LLM fallback returned successful output even though the LLM leg failed, which could inflate trust in cleaned text.
- Pipeline-level degraded aggregation did not include all degraded-capable stages.
- Top-level API responses still preferred classification confidence instead of full pipeline confidence.
- Legacy voice flow used strict `status == "success"` gates and could reject degraded-but-safe stages.
- AI Trace did not consistently expose confidence in stage debug metadata.
- Analytical schema-invalid degraded output had no hard SQL safety gate before intent extraction.

## Root Causes
- Degraded was treated as a status label but not as a contract with downstream meaning.
- Confidence existed locally in classification but not as a shared cross-stage scoring system.
- Schema validation and SQL generation were separated by stage boundaries without an explicit safety link.
- Chart selection trusted upstream visualization output unless shape logic overrode it, but the override reason was not explicit enough.
- Legacy compatibility code did not consistently use canonical status normalization.

## Fixes Applied
- Added shared confidence scoring in `services/ai-service/shared/confidence.py`.
- Added low preprocessing degraded fallback semantics for LLM-preprocessor failure.
- Added high preprocessing confidence and marked deterministic schema fallback as degraded.
- Added analytical schema-to-SQL safety gate in `dagster_pipeline/assets/intent_extraction.py`.
- Added confidence propagation into intent extraction, query execution, visualization, final payloads, views, and trace debug metadata.
- Updated pipeline final status aggregation to include low preprocessing and classification degraded states.
- Updated text and voice API responses to return `confidence` plus `confidence_breakdown`.
- Updated legacy voice flow to use canonical degraded-aware progression and to block schema-invalid analytical SQL.
- Improved chart validation reasons with `adjusted_from_<chart>:` prefixes when an invalid upstream chart is corrected.
- Added regression tests for schema-invalid SQL blocking and confidence penalties.

## Files Changed
- `services/ai-service/shared/confidence.py`
- `services/ai-service/preprocessing_low/preprocess_task.py`
- `services/ai-service/preprocessing_low/schemas.py`
- `services/ai-service/preprocessing_high/preprocess_high_task.py`
- `services/ai-service/preprocessing_high/schemas.py`
- `services/ai-service/dagster_pipeline/assets/preprocessing_low.py`
- `services/ai-service/dagster_pipeline/assets/preprocessing_high.py`
- `services/ai-service/dagster_pipeline/assets/intent_extraction.py`
- `services/ai-service/dagster_pipeline/assets/execution.py`
- `services/ai-service/intent_extraction/intent_extraction_task.py`
- `services/ai-service/intent_extraction/schemas.py`
- `services/ai-service/llm_app/views.py`
- `services/ai-service/whisper_app/views.py`
- `services/ai-service/whisper_app/transcription_task.py`
- `services/ai-service/tests/test_final_system_hardening.py`
- `services/ai-service/tests/test_pipeline_integration.py`
- `services/ai-service/reasoning_app/tests.py`

## Confidence System
Confidence is now a 0.0 to 1.0 score based on:
- Preprocessing quality and LLM fallback use.
- Classification confidence and degraded classifier fallback.
- Schema validity, deferred validation, unresolved terms, unsupported terms, and invalid mappings.
- Intent extraction fallback or failure state.
- Query execution success and SQL validation status.
- Visualization status.
- Forecast availability and historical-only fallback.

The final response includes:
- `confidence`: aggregate pipeline score.
- `confidence_breakdown`: component scores and weights.

## Schema-SQL Safety
If `schema_valid=false` on an analytical route, SQL generation is blocked before intent extraction can produce a validated intent or query. The stage returns `rejected` with `error_type=schema_mismatch`, `validated_intent={}`, and `sql_generation_allowed=false`.

Predictive routes remain allowed through the forecasting path because forecasting uses its own schema-aware historical SQL and time-series validation rules.

## Chart Validation
Chart output is validated against:
- Result row count.
- Numeric columns.
- Time-like columns.
- Single-value shape.
- Intent semantics: relationship, time series, distribution, ranking/category comparison.

When an upstream chart is invalid, the selected chart records an explicit reason such as `adjusted_from_card:priority_time_series_line`.

## Degraded Semantics
`degraded` now means:
- The stage produced a usable output.
- A fallback or reduced-capability path was used.
- Downstream stages may proceed if their safety gates pass.
- The final response must expose confidence and degradation reasons.

`degraded` does not mean:
- Silent success.
- Hard failure.
- Permission to generate SQL from invalid schema assumptions.

## Validation
Focused validation:
`python -m pytest services/ai-service/tests/test_stage_contracts.py services/ai-service/tests/test_final_system_hardening.py services/ai-service/tests/test_pipeline_integration.py services/ai-service/tests/test_bi_hardening.py services/ai-service/tests/test_preprocessing_high_recovery.py`

Result: 24 passed.

Broad AI-service validation:
`$env:PYTHONPATH='services/ai-service'; python -m pytest services/ai-service/tests services/ai-service/intent_extraction/tests.py services/ai-service/reasoning_app/tests.py services/ai-service/shared/tests_sql_review.py`

Result: 119 passed.

## Critical Failure Mode Review
- Valid text or voice question incorrectly rejected: reduced; degraded stages now progress when safe.
- Invalid question incorrectly accepted: reduced; classification and schema gates still stop invalid/noise/non-analytical inputs.
- Analytical/predictive route mismatch: reduced; predictive invariants still force forecasting.
- Schema correction breaking SQL: blocked for analytical routes when schema validity is false.
- Forecasting silent failure: reduced; forecast unavailability is degraded with explicit fallback metadata.
- Wrong chart type: reduced; shape and intent validation correct invalid upstream chart choices.
- Degraded masking real failure: reduced; confidence, warnings, degradation reasons, and trace metadata are surfaced.
- Trace misleading user: reduced; stage confidence and normalized statuses are attached.
- Missing fields breaking downstream behavior: reduced; API payloads now include pipeline confidence and chart payload normalization.

## Remaining Risks
- Some exception wrappers remain at boundary layers, but they classify errors into structured failed/degraded responses instead of silently swallowing them.
- Import-path setup is still required for direct pytest execution unless tests inject `services/ai-service` into `PYTHONPATH`.
- External clients must treat `degraded` as a usable-but-reduced state, not as simple success or simple failure.
- Classification ambiguity can never be mathematically eliminated for natural language, but confidence now reflects uncertainty and fallback use.

## Final Assessment
The AI service is materially more deterministic, truthful, and production-ready. The most important safety change is the schema-SQL gate: invalid analytical schema assumptions can no longer flow into SQL generation. The most important observability change is pipeline-wide confidence, which gives downstream systems and users a meaningful signal for degraded chains.
