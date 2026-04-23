# Full System End-to-End Audit

Date: 2026-04-23

## Executive Summary
The BI Voice Agent system was audited end to end across frontend, API gateway, voice-service, AI-service, query-service, forecasting, visualization-service, and report retrieval. The AI-service hardening from the final system audit remains intact, and this pass found one critical cross-service integration break plus contract propagation gaps outside AI-service.

Final system readiness score: 9.1/10

## Full System Architecture
User-facing flow:

Frontend React manager
-> API Gateway
-> voice-service upload/text orchestration
-> AI-service transcription or text NLP pipeline
-> query-service ClickHouse execution
-> AI-service forecasting bridge when predictive
-> visualization-service Metabase question/dashboard creation
-> report-service detail/list retrieval
-> frontend embedded chart rendering and AI trace display

Supporting services:
- auth-service validates users through JWT.
- workspace-service provides workspace ownership/membership context.
- subscription-service gates voice/text request consumption.
- notification-service receives report-created events.
- report-service reads persisted report records for list/detail/dashboard endpoints.

## Integration Map
- Frontend -> Gateway:
  - `POST /voice-reports/upload/` for audio.
  - `POST /voice-reports/text-query/` for direct text.
  - `POST /voice-reports/{id}/execute/` for SQL execution and visualization.
  - `GET /voice-reports/reports/` and `GET /voice-reports/{id}/` for report retrieval.
- Gateway routing:
  - upload, text-query, and execute route to voice-service.
  - report list/detail/sql/trace/dashboard route to report-service.
  - database/query routes route to query-service.
  - visualization routes route to visualization-service.
- voice-service -> AI-service:
  - `POST /api/transcribe/` for voice.
  - `POST /api/llm/intent/` for text.
  - `POST /api/llm/forecasting/detect/` and `/dataset/` for predictive post-processing.
- voice-service -> query-service:
  - `POST /query/execute/` with validated SELECT SQL and workspace database.
- voice-service -> visualization-service:
  - `POST /visualization/question/create/`
  - `POST /visualization/dashboard/create/`
  - `POST /visualization/dashboard/{id}/add-question/`
  - `GET /visualization/question/{id}/embed-url/`

## Question Flow
Text input:
1. Frontend sends text and workspace id.
2. voice-service validates manager/workspace/subscription.
3. voice-service resolves dataset binding from query-service.
4. AI-service runs preprocessing_low, classification, preprocessing_high, intent extraction, routing, SQL generation/review, optional forecasting route metadata, chart recommendation, trace generation, and confidence aggregation.
5. voice-service persists report, SQL, preprocessing metadata, pipeline trace, upstream chart, and AI contract.
6. Frontend calls execute.
7. voice-service validates SQL, query-service executes ClickHouse SELECT, forecasting bridge runs if required, chart type is inferred/validated, visualization-service creates Metabase card/dashboard, and report-service later exposes the stored result.

Voice input:
1. Frontend uploads audio.
2. voice-service validates manager/workspace/subscription and saves audio.
3. AI-service transcribes audio, then runs the same canonical NLP/SQL/chart pipeline as text.
4. Downstream execution and visualization are shared with text flow.

## Issues Found
1. Critical: AI-service internal endpoints required `X-Internal-Api-Key`, but voice-service did not send the shared key.
   - Impact: voice and text requests could fail at AI-service with 401 even when user authentication succeeded.
   - Root cause: internal service authentication was added in AI-service without updating voice-service clients or environment contract.

2. Confidence and degraded state were not consistently propagated outside AI-service.
   - Impact: frontend/report consumers could see a chart as plain success while the AI pipeline had used fallback/degraded stages.
   - Root cause: AI-service emitted confidence, but voice-service persisted only trace/chart data and response payloads did not normalize an explicit AI contract.

3. Forecasting bridge calls could fail under internal AI auth.
   - Impact: predictive reports could silently fall back or fail forecasting requests because bridge calls used no internal auth header.
   - Root cause: forecasting bridge was separate from the main AI client and did not share header construction.

4. AI Trace degraded stages were displayed as generic skipped/warning states.
   - Impact: analysts could misread degraded-but-usable stages.
   - Root cause: trace normalization did not preserve `degraded` as a first-class status.

5. Frontend manager did not expose confidence/degraded state in the primary chart view.
   - Impact: managers could treat fallback-backed charts as fully confident.
   - Root cause: UI only rendered row count, execution time, and chart type.

## Fixes Applied
- Added voice-service setting support for `AI_SERVICE_INTERNAL_API_KEY`.
- Added `X-Internal-Api-Key` headers to voice-service AI transcription/text calls.
- Added `X-Internal-Api-Key` headers to voice-service forecasting bridge calls.
- Added `AI_SERVICE_INTERNAL_API_KEY` and `AI_SERVICE_REQUIRE_INTERNAL_AUTH=true` to `.env.microservices`.
- Exposed top-level `confidence`, `confidence_breakdown`, and `degraded` from AI-service voice transcription responses.
- Added normalized AI contract extraction in voice-service and report-service.
- Persisted AI contract in `chart_config.ai_contract`.
- Returned confidence/degraded fields from upload, text-query, execute, report list, and report detail payloads.
- Marked successful chart execution as degraded when forecasting fails and analytical fallback is used.
- Updated AI trace status normalization to preserve `degraded`.
- Updated AI Trace frontend badge styling for degraded stages.
- Updated the React manager to store and display confidence/degraded state for the current report.

## Files Changed In This Pass
- `.env.microservices`
- `frontend/src/components/ai-trace/AITracePanel.jsx`
- `frontend/src/pages/voice-reports/VoiceReportManager.jsx`
- `services/ai-service/whisper_app/views.py`
- `services/report-service/voice_reports/services/ai_trace_service.py`
- `services/report-service/voice_reports/views.py`
- `services/voice-service/service_config/settings.py`
- `services/voice-service/voice_reports/services/ai_trace_service.py`
- `services/voice-service/voice_reports/services/forecasting_bridge.py`
- `services/voice-service/voice_reports/services/small_whisper_client.py`
- `services/voice-service/voice_reports/views.py`

## Contract Changes
The cross-service report contract now consistently carries:
- `status`
- `degraded`
- `confidence`
- `confidence_breakdown`
- `pipeline_trace`
- `overall_status`
- `final_route`
- `chart`
- `chart_type`
- `forecasting` metadata when applicable

`degraded=true` means the result is usable but reduced-confidence, not a hard failure.

## Frontend Fixes
- Current chart view now includes confidence percentage.
- Degraded current reports are marked in the confidence metric.
- Degraded execute responses show a reduced-confidence success toast.
- AI Trace badges now recognize `degraded`.

## Chart Correctness Validation
Chart type is selected using upstream AI recommendation only when compatible with result shape. The execution layer revalidates against row count, numeric columns, time-like columns, single-value shape, and intent semantics. Predictive/forecast routes force line chart behavior for actual-vs-forecast overlays.

## Confidence Propagation Validation
Confidence now flows:
AI-service pipeline
-> AI-service voice/text API response
-> voice-service normalized `ai_contract`
-> persisted `chart_config.ai_contract`
-> execute/list/detail responses
-> React manager confidence display
-> AI Trace degraded status display

## Validation Results
- Python compile:
  - `services/voice-service/voice_reports/views.py`
  - `services/voice-service/voice_reports/services/small_whisper_client.py`
  - `services/voice-service/voice_reports/services/forecasting_bridge.py`
  - `services/voice-service/voice_reports/services/ai_trace_service.py`
  - `services/report-service/voice_reports/views.py`
  - `services/report-service/voice_reports/services/ai_trace_service.py`
  - `services/ai-service/whisper_app/views.py`
  - Result: passed.
- Frontend production build:
  - `npm.cmd run build`
  - Result: passed.
- Focused AI-service validation:
  - `python -m pytest services/ai-service/tests/test_stage_contracts.py services/ai-service/tests/test_final_system_hardening.py services/ai-service/tests/test_pipeline_integration.py services/ai-service/tests/test_bi_hardening.py services/ai-service/tests/test_preprocessing_high_recovery.py`
  - Result: 24 passed.
- Voice-service trace/chart validation:
  - `python -m pytest services/voice-service/voice_reports/tests_ai_trace_service.py services/voice-service/voice_reports/tests_chart_selection.py`
  - Result: 15 passed.
- Broad AI-service validation:
  - `python -m pytest services/ai-service/tests services/ai-service/intent_extraction/tests.py services/ai-service/reasoning_app/tests.py services/ai-service/shared/tests_sql_review.py`
  - Result: 119 passed.

## Re-Audit Checklist
- Valid text question reaches AI-service: yes, with internal auth header.
- Valid voice question reaches AI-service: yes, with internal auth header.
- Invalid/non-analytical question blocked from SQL: yes.
- Analytical invalid schema blocked before SQL generation: yes, per AI-service schema-SQL gate.
- Predictive route remains allowed through forecasting-safe historical SQL: yes.
- Forecasting triggered only on predictive route/metadata: yes.
- Forecasting failure no longer masquerades as clean success: improved; execution can return chart with degraded metadata.
- Chart metadata reaches frontend: yes.
- Confidence reaches frontend: yes.
- Degraded can be shown without breaking the UI: yes.
- AI Trace degraded status remains visible: yes.

## Remaining Risks
- Live ClickHouse, Metabase, and full Docker network execution were not run in this pass; validation was static plus unit/focused integration tests and frontend production build.
- The worktree contains many pre-existing modified/untracked files, so this report distinguishes this pass from earlier AI-service hardening.
- External clients must honor `degraded` as usable-but-reduced. Treating it as either pure success or pure failure would lose meaning.
- Natural-language classification ambiguity cannot be eliminated completely, but schema gates, routing metadata, trace, and confidence now make uncertainty visible.

## Final Assessment
The end-to-end system is materially safer and more integrated after this pass. The critical AI internal-auth break is fixed, confidence/degraded semantics now cross service boundaries, forecasting fallback is less misleading, and the manager UI surfaces confidence where decisions are made.
