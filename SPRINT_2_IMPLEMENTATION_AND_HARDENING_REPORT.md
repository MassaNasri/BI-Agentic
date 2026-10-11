# Sprint 2 Implementation and Hardening Report

## 1. Executive Summary

Sprint 2 completed the core visualization-state, chart-transformation, Metabase-configuration, SQL-guard, and security-configuration remediation work on top of the existing Sprint 1 contracts and result-shape work.

The most important changes are:

- Added a typed shared `VisualizationSpec` architecture with `MetabaseConfig`, field assignments, result shape, chart contract, recommendation metadata, and timestamps.
- Integrated initial visualization creation and manager chart switching with complete spec generation instead of updating only `chart_type` or Metabase display.
- Added a deterministic chart transformation layer in visualization-service.
- Replaced service-local regex SQL guards with a single shared AST-backed guard using `sqlglot` ClickHouse parsing.
- Hardened active Django service settings for production-safe `DEBUG`, `ALLOWED_HOSTS`, and CORS defaults.
- Removed hardcoded runtime credentials from active compose/config/env files and replaced them with placeholders or required environment variables.
- Added focused regression tests for SQL security, visualization specs, transformation errors, Metabase settings generation, and security config checks.

One item is not fully complete: the physical split of `services/voice-service/voice_reports/views.py` into multiple small view modules remains a larger refactor. The chart-switch behavior itself was remediated, but the view monolith still exists and should be split in a dedicated follow-up with endpoint smoke coverage.

## 2. Initial Repository State and Safety Measures

The repository was already heavily dirty before this continuation. Baseline commands were run from the repository root:

```powershell
git status --short
git diff --stat
git diff --name-only
```

The working tree contained broad pre-existing frontend, AI-service, report-service, voice-service, shared-contract, doc deletion, and Python cache changes. No destructive Git commands were run. No commit was created. Existing unrelated modifications were preserved.

`SYSTEM_AUDIT_AND_REMEDIATION_REPORT.md` and the attached Sprint 2 instructions were inspected before implementation. Relevant paths were searched for visualization flow, chart switching, Metabase mapping, SQL guard, workspace database handling, CORS, DEBUG, and credential defaults.

## 3. Issues Implemented

Implemented or materially remediated:

- `VIZ-002`: Chart switching now regenerates chart contracts, field assignments, Metabase display, and visualization settings from result metadata.
- `VIZ-003`: Added complete `to_metabase_config(...)` generation instead of relying only on lossy display strings.
- `VIZ-004`: Added visualization-service chart transformation facade.
- `ARCH-001`: Added shared `VisualizationSpec` and persistence integration.
- `QRY-002`: Replaced regex-authoritative SQL validation with AST-backed allowlist validation.
- `SEC-001`: Removed production-open CORS defaults from active Django services.
- `SEC-002`: Removed hardcoded active runtime credentials from compose/settings/env examples.
- `SEC-003`: Changed active Django service `DEBUG` defaults to false and removed unsafe host/CORS defaults.
- `TEST-001`: Added focused tests and ran existing nearby suites.

Partially complete:

- `ARCH-002`: Chart-switching business behavior was remediated, but `voice_reports/views.py` is still a large module. A full physical split remains deferred.

## 4. VisualizationSpec Architecture

Added `bi_platform_shared/contracts/viz.py` with:

- `MetabaseConfig`
- `VisualizationSpec`
- `VisualizationSpecError`
- `compatible_chart_types`
- `build_field_assignments`
- `build_chart_contract`
- `to_metabase_config`
- `build_visualization_spec`
- `transform_visualization_spec`

The contract is pure shared code. It does not import service implementations and does not perform Metabase API calls. It serializes cleanly through Pydantic v2 and preserves backward compatibility through `model_dump(mode="json")`.

The voice-service report model now has:

```python
visualization_spec = models.JSONField(null=True, blank=True)
```

New reports store the spec after successful visualization creation. Legacy reports without a spec are derived from stored chart config, result shape, query result metadata, and available columns where possible.

## 5. Chart Transformation Design

Added `services/visualization-service/visualization_api/services/chart_transformer.py`.

Public behavior:

- `build_initial_visualization_spec(...)`
- `transform_chart(...)`
- `ChartTransformationError`

The transformer validates target chart type, checks compatibility through the shared chart compatibility engine, rebuilds mappings from result metadata, regenerates a chart contract, generates new Metabase configuration, and returns a fresh `VisualizationSpec`.

Invalid transformations raise typed, user-safe errors with:

- `error_code`
- `requested_chart_type`
- `compatible_chart_types`
- message

The previous spec is not mutated.

## 6. Metabase Configuration Mapping

`to_metabase_config(...)` now returns both:

- `display`
- complete `visualization_settings`

Examples implemented:

- `bar`, `bar_grouped`, and `bar_stacked` share Metabase display where needed but differ in generated settings such as dimensions, metrics, and stack type.
- `line`, `line_multi`, `area`, and `cumulative_line` generate time-axis settings and metric settings.
- `pie` generates dimension, metric, legend, and percent visibility settings.
- `histogram` maps to Metabase bar display with explicit histogram metadata.
- `heatmap` maps to table/pivot-style settings with explicit `heatmap_mapped_to_table` metadata.
- `card` maps to scalar metric settings.

The legacy `to_metabase_display(...)` remains available for compatibility. `to_metabase_config(...)` is exported through the shared contracts package.

## 7. Chart Switching Flow

`ReportChartTypeSwitchView` was updated to:

1. Authenticate and load the report through the existing safe queryset.
2. Resolve query/result metadata from `query_result`, `chart_config`, or profiled rows/columns.
3. Validate requested chart type against the shared compatibility engine.
4. Load or derive the current `VisualizationSpec`.
5. Transform to the requested chart type.
6. Build fresh Metabase display and visualization settings.
7. Update Metabase.
8. Persist `chart_config` and `visualization_spec` only after Metabase succeeds.
9. Return the updated `chart_contract`, `visualization_spec`, `metabase_visualization_settings`, and legacy response fields.

Incompatible target charts return HTTP 422 with compatible chart types and do not update Metabase or local report state.

## 8. SQL Guard Security Design

Added `bi_platform_shared/sql/guard.py` with AST-backed validation using `sqlglot` in ClickHouse dialect.

The shared guard:

- Allows read-only `SELECT` and `WITH ... SELECT` queries.
- Rejects multiple statements.
- Rejects write/admin statements such as `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `SHOW`, `DESCRIBE`, `SYSTEM`, `SET`, and related operations.
- Rejects `system`, `information_schema`, and metadata table access.
- Rejects dangerous table functions such as `remote`, `cluster`, `s3`, `url`, `file`, `hdfs`, `jdbc`, `odbc`, `mysql`, `postgresql`, `dictionary`, `executable`, `numbers`, and `generateRandom`.
- Rejects `INTO OUTFILE`, `INTO DUMPFILE`, client-controlled `FORMAT`, and client-controlled `SETTINGS`.
- Handles string literals and comments so words like `DROP` inside text do not cause false positives.
- Enforces workspace database isolation and skips CTE aliases during database qualification.

Service-local SQL guard modules in query, voice, and report services now re-export the shared guard, removing divergent regex implementations.

Query execution now treats `workspace_id` as the normal authoritative server-side source. Explicit `workspace_database` is accepted only when `trusted_internal_workspace_database=true`.

## 9. voice-service Refactoring Map

Completed safely:

- Chart-switching behavior was converted to use the shared visualization contract and compatibility engine.
- Duplicate chart compatibility logic now delegates to shared contracts.
- Duplicate SQL guard logic was removed from voice/report/query services in favor of shared AST guard wrappers.

Not fully completed:

- `services/voice-service/voice_reports/views.py` remains a large module.
- A full split into `audio`, `text_query`, `query_execution`, `report_crud`, `chart_switching`, `ai_trace`, `dashboard`, and `health` modules was not performed because the file has cross-class runtime dependencies and the repository did not have sufficient endpoint smoke coverage to safely do a broad physical move in this pass.

Recommended follow-up split:

- Move shared helper functions into `voice_reports/view_support.py`.
- Move chart capability/switch classes into `voice_reports/chart_views.py`.
- Move query execution and SQL edit views into `voice_reports/query_views.py`.
- Move upload/text-query pipeline views into `voice_reports/pipeline_views.py`.
- Move report CRUD and dashboard views into focused modules.
- Keep `voice_reports/views.py` as a compatibility re-export during transition.

## 10. Security Configuration Changes

Active Django settings patched:

- `services/api-gateway/service_config/settings.py`
- `services/auth-service/service_config/settings.py`
- `services/workspace-service/service_config/settings.py`
- `services/report-service/service_config/settings.py`
- `services/voice-service/service_config/settings.py`
- `services/query-service/service_config/settings.py`
- `services/visualization-service/service_config/settings.py`
- `services/subscription-service/service_config/settings.py`
- `services/notification-service/service_config/settings.py`

Pattern applied:

- `DEBUG` defaults to false.
- `ALLOWED_HOSTS` comes from CSV environment variables.
- Localhost host fallback is only enabled when `DEBUG=true`.
- `CORS_ALLOW_ALL_ORIGINS = False`.
- `CORS_ALLOWED_ORIGINS` comes from environment.
- Development localhost CORS fallback is only enabled when `DEBUG=true`.
- `CORS_ALLOW_CREDENTIALS` is true only when explicit allowed origins exist.

Runtime credential defaults were removed from active settings and ClickHouse helpers. `docker-compose.yml` now uses required environment substitutions for ClickHouse and SurrealDB secrets.

`.env.microservices` and `.env.microservices.example` were sanitized to placeholders. `.gitignore` now ignores `.env.microservices`.

## 11. Files Created and Modified

Created:

- `bi_platform_shared/contracts/viz.py`
- `bi_platform_shared/sql/guard.py`
- `services/visualization-service/visualization_api/services/chart_transformer.py`
- `services/visualization-service/visualization_api/tests/test_visualization_spec_contract.py`
- `services/query-service/tests/test_sql_guard.py`
- `services/query-service/tests/test_security_configuration.py`
- `services/voice-service/voice_reports/migrations/0012_add_visualization_spec.py`
- `SPRINT_2_IMPLEMENTATION_AND_HARDENING_REPORT.md`

Modified in scope:

- `.env.microservices`
- `.env.microservices.example`
- `.gitignore`
- `docker-compose.yml`
- `bi_platform_shared/contracts/__init__.py`
- `bi_platform_shared/contracts/chart.py`
- `bi_platform_shared/sql/__init__.py`
- `bi_platform_shared/sql/normalization.py`
- `services/visualization-service/visualization_api/views.py`
- `services/voice-service/voice_reports/models.py`
- `services/voice-service/voice_reports/views.py`
- `services/query-service/query_api/application/query_execution.py`
- `services/query-service/query_api/views.py`
- `services/query-service/query_api/services/sql_guard.py`
- `services/query-service/query_api/services/clickhouse_executor.py`
- `services/query-service/database/utils.py`
- `services/report-service/voice_reports/services/sql_guard.py`
- `services/report-service/voice_reports/services/clickhouse_executor.py`
- `services/voice-service/voice_reports/services/sql_guard.py`
- `services/voice-service/voice_reports/services/clickhouse_executor.py`
- `services/ai-service/preprocessing_high/schemas.py`
- `services/ai-service/llm_app/schema_provider.py`
- active service `settings.py` files listed in Section 10
- `services/report-service/requirements.txt`
- `services/voice-service/requirements.txt`

The repository has many additional pre-existing dirty and untracked files not created by this pass.

## 12. Database Migrations and Backward Compatibility

Added migration:

```text
services/voice-service/voice_reports/migrations/0012_add_visualization_spec.py
```

Migration purpose:

- Add nullable `visualization_spec` JSON field to `VoiceReport`.

Backward compatibility:

- Existing reports can still load without a spec.
- Chart switching derives a spec from legacy `chart_config`, `query_result`, columns, rows, and result-shape metadata when possible.
- Incompatible or under-specified transformations return a clear failure instead of silently producing a broken chart.

Migration command:

```powershell
python manage.py migrate
```

Run it inside the voice-service environment after dependencies are installed.

## 13. API Contract Changes

Visualization-service create-question response now includes:

- `visualization_spec`

Voice-service chart switch success response now includes:

- `chart_contract`
- `visualization_spec`
- `metabase_visualization_settings`
- existing legacy fields such as `chart_type`, `previous_chart_type`, `embed_url`, and `message`

Chart switch incompatible response uses HTTP 422 and includes:

- `success: false`
- `error`
- `error_code`
- `requested_chart_type`
- `compatible_chart_types`
- `unsupported_reason_code`
- `unsupported_reason`

Query-service internal execution now expects normal callers to send `workspace_id`. `workspace_database` is honored only with `trusted_internal_workspace_database=true`.

## 14. Test Strategy and Test Results

Added tests:

- Shared visualization spec serialization/deserialization.
- Chart transformation success and incompatible transform errors.
- Metabase config generation for line, bar, histogram, and card-like cases.
- AST SQL guard allow/reject behavior.
- CTE alias preservation during workspace database enforcement.
- Cross-workspace database rejection.
- Static security config checks for unsafe CORS/DEBUG/credential defaults.

Executed:

```powershell
python -m pytest services\query-service\tests\test_sql_guard.py services\visualization-service\visualization_api\tests\test_visualization_spec_contract.py -q
```

Result after fixes:

```text
12 passed, 3 warnings
```

Executed:

```powershell
python -m pytest services\query-service\tests services\visualization-service\visualization_api\tests -q
```

Result:

```text
75 passed, 3 warnings
```

Warnings were existing Pydantic protected-namespace warnings for forecast/transcription models.

Executed targeted compile checks:

```powershell
python -m py_compile <changed python modules and tests>
```

Result:

```text
passed with exit code 0
```

Executed compose validation:

```powershell
docker compose --env-file .env.microservices config --quiet
```

Result:

```text
exit code 0
```

Docker emitted warnings about access to `C:\Users\massa\.docker\config.json`; compose interpolation still succeeded.

## 15. Exact Commands Run

Important commands run:

```powershell
git status --short
git diff --stat
git diff --name-only
rg -n "ReportChartTypeSwitchView|VisualizationSpec|sql_guard|CORS_ALLOW_ALL_ORIGINS|DEBUG|CLICKHOUSE_PASSWORD|..."
python -m pytest services\query-service\tests\test_sql_guard.py services\visualization-service\visualization_api\tests\test_visualization_spec_contract.py -q
python -m pip install sqlglot
python -m pytest services\query-service\tests\test_sql_guard.py -q
python -m pytest services\visualization-service\visualization_api\tests\test_visualization_spec_contract.py -q
python -m pytest services\query-service\tests services\visualization-service\visualization_api\tests -q
python -m py_compile <changed python modules and tests>
docker compose --env-file .env.microservices config --quiet
rg -n "StrongPassword123|etl_pass123|user_etl|CORS_ALLOW_ALL_ORIGINS = True|DEBUG=True|..."
```

`sqlglot` was installed locally with user-approved elevated network access because the local interpreter did not have the declared query-service dependency.

## 16. Manual Validation Checklist

Manual checks still recommended against a running stack:

1. Show total sales in Damascus.
2. Show revenue for Samsung.
3. Show monthly sales trend.
4. Compare sales across regions over time.
5. Show top 10 products by revenue.
6. Compare revenue and profit by category.
7. Switch Bar to Pie.
8. Switch Pie to Bar.
9. Switch Line to Area.
10. Switch Multi-Line to Grouped Bar.
11. Attempt Single KPI to Scatter and verify HTTP 422 safe rejection.
12. Attempt 20-category result to Pie and verify HTTP 422 safe rejection.
13. Attempt unauthorized report chart switch and verify denial.
14. Verify CORS blocks an unapproved production origin.
15. Verify invalid SQL payload is rejected before execution.

## 17. Known Limitations / Deferred Items

- `ARCH-002` physical view split is not fully complete. `voice_reports/views.py` remains large.
- Full voice-service endpoint smoke tests were not run. A running Django test database and broader fixture setup were not established during this pass.
- Metabase integration was validated through contract/config generation and existing visualization tests, not against a live Metabase instance.
- Docker services were not started; compose config was validated only.
- The working tree contains many pre-existing unrelated changes and Python cache modifications.
- Credentials that were present in `.env.microservices` before sanitization may have been real. They must be rotated manually anywhere they were used.

## 18. Risks and Rollback Notes

Risks:

- `visualization_spec` migration must be applied before code paths attempt to save the new field.
- Services that import the shared SQL guard need `sqlglot` installed. `query-service`, `voice-service`, and `report-service` requirements now include it.
- Sanitized `.env.microservices` placeholders will not run production services until real local secret values are supplied outside committed config.
- Chart settings use the current project Metabase conventions; a live Metabase validation pass is still recommended.

Rollback notes:

- Reverting visualization behavior requires reverting `VisualizationSpec` storage, visualization-service chart transformer integration, and voice-service chart switch changes together.
- Reverting SQL guard behavior requires restoring service-local guards and removing shared guard wrappers, but that would reintroduce the audit finding.
- Do not restore the exposed credentials into tracked files. If local values are needed, use ignored environment files or a secret manager.

No Git commit was created.
