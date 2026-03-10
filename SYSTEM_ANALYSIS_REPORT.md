# SYSTEM ANALYSIS REPORT

## Executive Summary
This project is a dual-backend BI system: a main Django backend (`config`, `voice_reports`, `database`) and a stateless AI worker (`Small Whisper/backend`) for STT + intent + SQL generation. Static analysis found multiple integration and configuration defects that can directly cause chart rendering failures in the frontend after query execution.

Most critical findings are in the report-to-visualization pipeline: missing/incorrect folder references, non-fatal Metabase failures returned as success, embed URL fallback behavior that is often non-embeddable, chart type contract mismatches across services, and an exception-handling bug in the Small Whisper pipeline that hides intended error classification.

The known symptom (`"Chart not available"`) is strongly consistent with at least one of the following observed conditions:
- Query executes, but Metabase authentication/question creation fails and API still returns `success: true` without a usable embed.
- Embed URL is generated as a direct `/question/{id}` URL (when `METABASE_SECRET_KEY` is unset), which is usually not iframe-embeddable in frontend contexts.
- Chart type values are inconsistent across internal components (`kpi`, `grouped_bar`, `scalar`, `number`), causing visualization fallback or rejection.

## Architecture Observations
- Main backend (`config` + `voice_reports` + `database`) manages auth, workspaces, persistence, ClickHouse execution, and Metabase integration.
- Small Whisper backend (`Small Whisper/backend`) performs transcription, reasoning classification, intent extraction, SQL compilation, and chart recommendation.
- Pipeline flow:
  1. `voice_reports/services/small_whisper_client.py` posts audio to `Small Whisper`.
  2. `Small Whisper/backend/whisper_app/views.py` transcribes and calls `shared.pipeline.process_after_whisper`.
  3. Main backend creates `VoiceReport` with SQL (if analytical).
  4. `QueryExecuteView` validates SQL, executes ClickHouse query, infers chart type, creates Metabase question, generates embed URL.
- There are two independent ClickHouse client implementations (`database/utils.py` and `voice_reports/services/clickhouse_executor.py`) with different behaviors and assumptions.
- There are two question-classification/LLM strategies (Ollama in `reasoning_app`, OpenRouter in `llm_app`), increasing drift risk.

## List of Detected Issues

### Issue ID: SYS-001
- Severity: High
- File Path: `databases` (missing), `voice-report` (missing)
- Description: Requested analysis target folders do not exist at repository root.
- Root Cause Hypothesis: Folder naming drift (`database` vs `databases`, `voice_reports` vs `voice-report`).
- Potential Impact: Tooling, docs, and developer workflows can fail or inspect wrong modules; defects in intended modules may be missed.

### Issue ID: SYS-002
- Severity: Critical
- File Path: `voice_reports/views.py`
- Description: `QueryExecuteView` returns `success: true` when Metabase authentication fails, and still finalizes execution path without guaranteed visualization artifact.
- Root Cause Hypothesis: Metabase unavailability is treated as a warning, not a hard failure for visualization-ready contract.
- Potential Impact: Frontend receives a successful execution state but lacks embeddable chart, leading to `Chart not available` UX.

### Issue ID: SYS-003
- Severity: Critical
- File Path: `voice_reports/services/jwt_embedding.py`
- Description: If `METABASE_SECRET_KEY` is not set, embed URL falls back to direct `.../question/{id}` or `.../dashboard/{id}` URL.
- Root Cause Hypothesis: Optional embedding secret is not enforced, but frontend likely expects iframe-safe embed links.
- Potential Impact: Direct Metabase URLs often fail in embedded frontend contexts (auth/session/X-Frame issues), producing missing chart behavior.

### Issue ID: SYS-004
- Severity: High
- File Path: `voice_reports/views.py`, `voice_reports/models.py`, `Small Whisper/backend/shared/chart_recommender.py`
- Description: Chart type contract mismatch across services (`kpi`, `grouped_bar`, `scalar`, `number`, etc.).
- Root Cause Hypothesis: No shared chart-type enum/schema between Small Whisper, main backend inference, model choices, and Metabase display expectations.
- Potential Impact: Visualization misconfiguration, fallback to table/invalid display, or frontend rendering mismatch causing chart unavailability.

### Issue ID: SYS-005
- Severity: High
- File Path: `Small Whisper/backend/shared/pipeline.py`
- Description: Duplicate `except ValueError` blocks in `process_after_whisper`; the second block is unreachable.
- Root Cause Hypothesis: Copy/paste exception handling where distinct error classes were intended.
- Potential Impact: Misclassified failures, inconsistent error metadata, reduced observability when analytical stage fails.

### Issue ID: SYS-006
- Severity: High
- File Path: `Small Whisper/backend/llm_app/schema_provider.py`, `config/settings.py`, `.env`
- Description: ClickHouse port/env key mismatch (`CLICKHOUSE_HTTP_PORT` vs `CLICKHOUSE_PORT`) and divergent default credentials.
- Root Cause Hypothesis: Different modules evolved independently without centralized configuration contract.
- Potential Impact: Schema loading failures in Small Whisper while main backend connects; SQL generation can fail upstream, preventing chart creation.

### Issue ID: SYS-007
- Severity: Medium
- File Path: `voice_reports/views.py`
- Description: Report status is set to `completed` even if Metabase question creation returns `None` (no card created).
- Root Cause Hypothesis: Completion state tied to query execution, not end-to-end visualization artifact creation.
- Potential Impact: System reports success while no chart entity exists; frontend shows chart missing message.

### Issue ID: SYS-008
- Severity: Medium
- File Path: `voice_reports/views.py`, `voice_reports/services/small_whisper_client.py`
- Description: Conversational/analytical branching can produce reports without SQL but still valid `report_id`; downstream clients may attempt execution/visualization.
- Root Cause Hypothesis: API intentionally always creates reports, but consumer-side contract guards may be incomplete.
- Potential Impact: Frontend flows that assume every report is chartable can hit `Chart not available` states.

### Issue ID: SYS-009
- Severity: Medium
- File Path: `Small Whisper/backend/reasoning_app/llm_intent_client.py`
- Description: Question classification depends on hardcoded local Ollama endpoint/model with fallback to informational on error.
- Root Cause Hypothesis: Availability of local model service is assumed; failure path suppresses SQL/chart generation.
- Potential Impact: Analytical questions can be downgraded to non-analytical, skipping chart generation unexpectedly.

### Issue ID: SYS-010
- Severity: Medium
- File Path: `voice_reports/views.py`
- Description: Health check targets `GET {SMALL_WHISPER_URL}/health/`, but Small Whisper URLs do not define this route.
- Root Cause Hypothesis: Health endpoint contract mismatch between services.
- Potential Impact: False-negative service health, operational confusion, and misdiagnosis of pipeline outages.

### Issue ID: SYS-011
- Severity: Medium
- File Path: `Small Whisper/backend/backend/settings.py`
- Description: CORS configuration is internally inconsistent (`CORS_ALLOW_ALL_ORIGINS=True` plus specific allowlist), and middleware order places CORS late.
- Root Cause Hypothesis: Mixed local-debug and restrictive settings combined without normalization.
- Potential Impact: Cross-origin behavior may be unpredictable, impacting frontend-to-worker connectivity and request failures.

### Issue ID: SYS-012
- Severity: Medium
- File Path: `config/settings.py`
- Description: Application startup hard-fails if `METABASE_USERNAME`/`METABASE_PASSWORD` are missing.
- Root Cause Hypothesis: Strict runtime guard placed in global settings instead of deferred service init.
- Potential Impact: Entire backend can fail to boot even for flows that do not require Metabase immediately.

### Issue ID: SYS-013
- Severity: High
- File Path: `config/settings.py`, `Small Whisper/backend/llm_app/llm_client.py`, `.env`
- Description: Sensitive credentials and API keys are hardcoded/defaulted in code and env file.
- Root Cause Hypothesis: Development secrets committed and unsafe fallback defaults retained.
- Potential Impact: Credential exposure, unauthorized access risk, operational security compromise.

### Issue ID: SYS-014
- Severity: Medium
- File Path: `config/settings.py`
- Description: `ETL_SERVICE_URL` and `SMALL_WHISPER_URL` both default to `http://127.0.0.1:8001`.
- Root Cause Hypothesis: Port allocation overlap between distinct external services.
- Potential Impact: Requests may hit wrong backend, causing upload/transcription/report pipeline failures.

### Issue ID: SYS-015
- Severity: Medium
- File Path: `Small Whisper/backend/shared/sql_compiler.py`
- Description: Compiler enforces post-aggregation `WHERE alias != 0` filtering on numeric aggregates.
- Root Cause Hypothesis: Data-quality safeguard implemented as hard filter.
- Potential Impact: Legitimate zero-valued analytical results are dropped, potentially returning empty datasets and no chart.

### Issue ID: SYS-016
- Severity: Low
- File Path: `Small Whisper/backend/whisper_app/views.py`, `Small Whisper/backend/whisper_app/transcription_task.py`
- Description: Whisper `large-v3` model loads at import/startup and `task="translate"` is forced.
- Root Cause Hypothesis: Performance/accuracy tradeoffs not parameterized.
- Potential Impact: High latency/memory pressure and potential transcription semantics drift before SQL generation.

### Issue ID: SYS-017
- Severity: Medium
- File Path: `voice_reports/views.py`, `voice_reports/services/metabase_service.py`
- Description: Visualization creation has limited transactional guarantees (ClickHouse result saved before Metabase artifact, partial success paths).
- Root Cause Hypothesis: Multi-service orchestration lacks atomic state machine for execution+visualization.
- Potential Impact: Persistent partial states (`executed`/`completed` without valid embed/card) and inconsistent frontend behavior.

### Issue ID: SYS-018
- Severity: Low
- File Path: `Small Whisper/backend/llm_app/response_parser.py`
- Description: JSON extraction uses greedy regex over arbitrary LLM text.
- Root Cause Hypothesis: Simplified parser without strict schema framing.
- Potential Impact: Intermittent parse failures or wrong JSON extraction, leading to upstream SQL/chart generation errors.
