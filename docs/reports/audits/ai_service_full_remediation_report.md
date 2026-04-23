# AI Service Full Remediation Report

## 1. Summary Of Issues Fixed From Original Audit
- Standardized stage-status handling across the pipeline to canonical states (`success`, `failed`, `skipped`, `degraded`, `rejected`) via a shared contract utility.
- Removed runtime dependence on `status="routed"` and replaced with canonical `success` while preserving `legacy_status` for compatibility.
- Fixed preprocessing-high deferred schema behavior to stop reporting fully valid success on unresolved schema terms.
- Fixed forecasting downstream error masking so forecasting failures/degradations are explicit instead of plain success.
- Removed silent legacy fallback from default runtime path; legacy fallback is now explicit opt-in only.
- Hardened security defaults in Django settings (no production wildcard defaults; debug off by default).
- Added internal API trust-boundary enforcement for CSRF-exempt endpoints.
- Increased retry robustness (bounded) for intent classification, intent extraction, preprocessing-high, and Dagster retry policy.
- Improved trace consistency by normalizing statuses before trace persistence.
- Fixed test discoverability risk when Dagster is unavailable by guarding `dagster_pipeline/__init__.py` imports.

## 2. Additional Issues Discovered Beyond The Audit
- Classification and intent-extraction fallback paths were still returning `success` on model failure fallbacks, hiding degraded quality.
- Pipeline result assembly treated only `success` as pass-through and did not uniformly support `degraded` as truthful non-fatal progression.
- LLM/Whisper API views only treated top-level `success` as non-error even when pipeline quality was degraded.
- Legacy `shared/pipeline.py` remained executable without explicit safety gating.

## 3. Root Cause Per Issue
- **Status drift**: Stage modules evolved independently with ad-hoc status values and special-case checks.
- **Availability-over-truth bias**: Fallback paths optimized continuity but suppressed degraded/failure semantics.
- **Dual pipeline drift**: Legacy and Dagster flows coexisted with different invariants and no hard boundary.
- **Weak production defaults**: Security assumptions were implicit (internal-only) but not enforced by default configuration.
- **Retry fragility**: Hard cap of one retry under transient model/network variability.

## 4. Files Changed
- `services/ai-service/shared/stage_contract.py` (new)
- `services/ai-service/shared/internal_api_auth.py` (new)
- `services/ai-service/dagster_pipeline/assets/execution.py`
- `services/ai-service/dagster_pipeline/assets/routing.py`
- `services/ai-service/dagster_pipeline/assets/preprocessing_high.py`
- `services/ai-service/dagster_pipeline/assets/intent_extraction.py`
- `services/ai-service/dagster_pipeline/__init__.py`
- `services/ai-service/dagster_pipeline/jobs.py`
- `services/ai-service/preprocessing_high/preprocess_high_task.py`
- `services/ai-service/preprocessing_high/schemas.py`
- `services/ai-service/intent_extraction/intent_extraction_task.py`
- `services/ai-service/intent_extraction/schemas.py`
- `services/ai-service/reasoning_app/intent_classification_task.py`
- `services/ai-service/forecasting/dagster_handler.py`
- `services/ai-service/whisper_app/transcription_task.py`
- `services/ai-service/whisper_app/views.py`
- `services/ai-service/llm_app/views.py`
- `services/ai-service/reasoning_app/views.py`
- `services/ai-service/shared/pipeline_trace.py`
- `services/ai-service/shared/pipeline.py`
- `services/ai-service/backend/settings.py`
- `services/ai-service/reasoning_app/debug_openrouter.py`
- Tests updated/added:
  - `services/ai-service/tests/test_pipeline_integration.py`
  - `services/ai-service/tests/test_preprocessing_high_recovery.py`
  - `services/ai-service/tests/test_forecasting_pipeline.py`
  - `services/ai-service/tests/test_stage_contracts.py` (new)
  - `services/ai-service/reasoning_app/tests.py`
  - `services/ai-service/intent_extraction/tests.py`

## 5. Exact Behavior Changes Introduced
- Routing now emits canonical `status="success"` and `legacy_status="routed"`.
- Pipeline continuation gates now accept canonical progress states (`success`, `degraded`) consistently.
- Preprocessing-high deferred schema mismatch now returns:
  - `status="degraded"`
  - `schema_valid=false`
  - `degraded=true`
  - `deferred=true`
  - `degradation_reason="schema_validation_deferred"`
- Forecasting downstream exceptions now return explicit degraded contract instead of hidden success.
- Forecasting handler now marks non-available forecasts as degraded (not plain success).
- Pipeline final response now returns top-level `status="degraded"` when any non-fatal degraded stage occurred; includes `degraded` and `degradation_reasons`.
- AI Trace stage statuses are normalized at write-time.
- Legacy full-pipeline fallback in Whisper flow is disabled by default and only enabled with `AI_SERVICE_ENABLE_LEGACY_FALLBACK=true`.
- Legacy non-Dagster `shared/pipeline.py` is explicitly disabled by default (`AI_SERVICE_ENABLE_LEGACY_PIPELINE=true` required).

## 6. Contract/Status Changes
- Introduced canonical status normalization contract in `shared.stage_contract`.
- Added explicit degraded semantics to multiple stage payloads (`degraded`, `degradation_reason`, `deferred` where applicable).
- Top-level pipeline response can now be `degraded` (breaking semantic change for strict `success`-only consumers).

## 7. Security Changes
- `DEBUG` now defaults to `false` unless `DJANGO_DEBUG=true`.
- `ALLOWED_HOSTS` now env-driven (`DJANGO_ALLOWED_HOSTS`), not wildcard by default.
- CORS now defaults to restrictive (`CORS_ALLOW_ALL_ORIGINS=false`) with env-driven allowlist (`DJANGO_CORS_ALLOWED_ORIGINS`).
- CSRF trusted origins now env-driven (`DJANGO_CSRF_TRUSTED_ORIGINS`).
- Added internal API key protection decorator for CSRF-exempt endpoints (`X-Internal-Api-Key`, controlled by `AI_SERVICE_REQUIRE_INTERNAL_AUTH` / `AI_SERVICE_INTERNAL_API_KEY`).
- Removed debug secret-value printing pattern from `reasoning_app/debug_openrouter.py` (redacted output only).

## 8. Legacy Pipeline Changes
- `whisper_transcription_preprocess_intent_flow` no longer silently falls back to legacy full flow by default.
- Legacy fallback is explicitly gated by `AI_SERVICE_ENABLE_LEGACY_FALLBACK=true`.
- `shared/pipeline.py` is now explicit opt-in (`AI_SERVICE_ENABLE_LEGACY_PIPELINE=true`) and returns deterministic error when disabled.

## 9. Tests Added/Updated
- Added `test_stage_contracts.py` for status normalization and progress gating.
- Added forecasting degraded regression in `test_pipeline_integration.py`.
- Added preprocessing-high deferred-invalid truthfulness regression in `test_preprocessing_high_recovery.py`.
- Added forecasting handler degraded regression in `test_forecasting_pipeline.py`.
- Updated reasoning and intent-extraction tests to assert degraded fallback semantics (instead of fake success).

## 10. Test Results
Executed:
- `PYTHONPATH=services/ai-service python -m unittest discover -s services/ai-service/tests -p "test_*.py"` -> **36 passed**
- `PYTHONPATH=services/ai-service python -m unittest services/ai-service/reasoning_app/tests.py services/ai-service/intent_extraction/tests.py services/ai-service/llm_app/tests.py services/ai-service/whisper_app/tests.py` -> **85 passed**

Notes:
- Running discovery without `PYTHONPATH` still depends on local import layout; test commands above use explicit `PYTHONPATH` for deterministic discovery.

## 11. Remaining Risks
- Broad `except Exception` usage still exists in several non-critical and lower-level modules (including third-party TimesFM integration paths); many are now semantically safer but not fully domain-specific everywhere.
- Legacy code artifacts (`shared/intent_*` modules) remain present and should be fully retired in a follow-up cleanup PR.
- Internal API key trust boundary requires deployment-side key management (`AI_SERVICE_INTERNAL_API_KEY`) to be effective.
- Some external consumers may require adaptation for top-level `degraded` status handling.

## 12. Production Readiness Reassessment
- Determinism: **Improved** (legacy fallback no longer silently changes runtime path by default).
- Truthfulness/observability: **Improved** (degraded/fallback semantics now explicit).
- Contract consistency: **Improved** (canonical status normalization introduced).
- Security posture: **Improved** (safe defaults + internal API gate).
- Test robustness: **Improved** (new regression coverage for critical semantics).

Post-remediation readiness score: **8.1/10** (up from 6/10 in original audit), with remaining work mostly in legacy retirement and deeper exception-taxonomy tightening.
