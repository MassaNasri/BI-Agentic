# AI Service Post-Fix Re-Audit

## 1. Current Architecture Overview
Primary path is Dagster orchestration:
`transcription -> preprocessing_low -> classification -> preprocessing_high -> intent_extraction -> routing -> query_execution -> visualization/forecasting -> pipeline_result`.

Key post-fix architectural properties:
- Canonical stage contract normalization is centralized (`shared.stage_contract`).
- Trace status normalization is centralized in `shared.pipeline_trace`.
- Forecast fallback and LLM fallback paths are explicit degraded paths.
- Legacy pipeline execution is default-disabled and env-gated.

## 2. Current Strengths
- Status contract is now materially more consistent across stages.
- Degraded semantics are explicit in preprocessing-high, forecasting downstream, classification fallback, and intent-extraction fallback.
- Routing no longer relies on non-canonical `routed` status for pipeline progression.
- Pipeline final result and trace are more truthful for degraded runs.
- Production defaults are safer: no wildcard hosts/CORS/debug by default.
- CSRF-exempt endpoints now have explicit internal API key trust-boundary enforcement.
- Test coverage improved for critical regressions.

## 3. Remaining Weaknesses
- Broad exception handling remains in several modules (some necessary wrappers, some debt).
- Legacy `shared/intent_*` modules still exist and can confuse maintainers.
- Environment discipline is now critical (internal API key + host/CORS envs must be correctly configured).
- Non-Dagster/legacy modules remain in repository and should be formally deprecated/removed.

## 4. Newly Discovered Risks (Post-Fix)
- Some external clients may treat top-level `degraded` as failure if they hard-coded `status == "success"`.
- Discovery/test execution without explicit import-path setup may still be environment-sensitive.

## 5. Focused Review Areas

### 5.1 Acceptance/Rejection Logic
- Classification now still rejects invalid/noise/conversational inputs as before.
- Degraded classification fallback remains non-fatal but is explicitly marked degraded, reducing false-success masking.
- Residual risk: heuristics can still be tuned further for edge conversational-vs-analytical ambiguity.

### 5.2 Classification Correctness
- Predictive consistency guard remains enforced (`predictive` -> `requires_forecast=true`, `route=forecasting`).
- LLM-failure fallback no longer claims full success; now degraded.

### 5.3 Predictive Routing
- Routing stage now uses canonical status while preserving legacy marker.
- Progress checks use normalized status gates, reducing route/status mismatch drift.

### 5.4 Chart-Type Correctness
- Priority logic remains strict (scatter/time-series/histogram/bar/card, then safe fallbacks).
- Contract propagation improved with degraded handling on predictive fallback routes.

### 5.5 Schema-Aware Correction Safety
- Deferred schema-invalid no longer reports `schema_valid=true` success.
- Preprocessing-high now reports deferred-invalid as degraded with explicit reason.

### 5.6 Fallback Honesty
- Forecasting handler and downstream execution now expose degraded semantics.
- Legacy orchestration fallback is no longer silent by default.

### 5.7 Trace Consistency
- Stage and overall statuses normalized centrally in trace writer.
- Reduced manual remapping burden and contradiction risk.

### 5.8 Production Security Posture
- Debug/wildcard defaults removed.
- Hosts/CORS/CSRF are env-driven.
- Internal API key decorator added to previously unauthenticated CSRF-exempt endpoints.

## 6. Explicit Verification Against Critical Failure Modes
- Incorrectly accept bad question: **reduced risk**, not fully eliminated (heuristic edge cases remain possible).
- Incorrectly reject valid question: **reduced risk**, with better degraded fallbacks and schema diagnostics.
- Predictive misclassified as analytical: **reduced risk**, predictive consistency guards still enforced.
- Wrong chart type: **reduced risk**, priority + shape validation remains and regression tests cover key cases.
- Failure hidden behind success: **substantially reduced**, degraded status now used in key fallback paths.
- Misleading AI Trace: **reduced risk**, status normalization now centralized.
- Dagster vs legacy drift: **substantially reduced**, legacy fallback now opt-in.

## 7. Production Readiness Score (Post-Fix)
- Reliability: 8/10
- Safety: 8.5/10
- Maintainability: 7.5/10
- Observability/Truthfulness: 8.5/10
- Security posture: 8/10

Final score: **8.1/10**

## 8. Recommended Next Follow-Ups
- Full removal of stale legacy intent modules (`shared/intent_*`).
- Broader replacement of remaining generic exception catches with domain-specific taxonomies.
- Add explicit compatibility note and rollout plan for top-level `degraded` response handling in downstream services.
