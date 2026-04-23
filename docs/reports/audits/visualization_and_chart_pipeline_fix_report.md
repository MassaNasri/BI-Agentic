# Visualization and Chart Pipeline Fix Report

Date: 2026-04-23

## Summary

Audited and remediated chart selection, visualization metadata propagation, Metabase mapping, forecast visualization semantics, and time-series SQL shaping across AI service, voice service, visualization service, report service, frontend-facing payloads, and regression tests.

## Problems Found and Root Causes

1. Daily-grain trend SQL could over-aggregate.
   - Root cause: time grouping caused metric inference to treat additive metrics such as `total_sales` as roll-up candidates even when the selected time column already represented the requested day grain.
   - Effect: daily trend questions could produce `SUM(total_sales) ... GROUP BY period` when direct `total_sales` over `period` was the truthful shape.

2. Chart type could be silently downgraded or become unobservable downstream.
   - Root cause: downstream services did not consistently persist the selected chart type, selected reason, Metabase display, or fallback reason in `chart_config`.
   - Effect: AI trace could say line/scatter while the created artifact gave no durable explanation for any fallback.

3. Metabase mapping fallback was too implicit.
   - Root cause: unsupported or malformed display settings were normalized internally but the chosen display and fallback reason were not returned to callers.
   - Effect: valid chart intent could be lost without report-visible diagnostics.

4. Forecast visualization success could be confused with degradation.
   - Root cause: forecast rendering status was coupled to predictive/fallback semantics rather than the actual availability of forecast points.
   - Effect: a normal actual-plus-forecast line chart could be treated like reduced capability in downstream contracts.

5. Actual vs forecast distinction was not explicit enough in the persisted visualization contract.
   - Root cause: series rows had `series_type`, but boundary/config metadata was incomplete at service handoffs.
   - Effect: downstream renderers had to infer styling and forecast boundary.

6. Relationship and grouped visual questions needed stronger preservation across service boundaries.
   - Root cause: voice/report-service chart inference and Metabase settings did not always carry axes, shape metadata, and upstream chart preference.
   - Effect: scatter/line/bar choices were more likely to be replaced by generic table behavior.

## Files Changed

- `services/ai-service/shared/query_planner.py`
- `services/ai-service/forecasting/pipeline.py`
- `services/ai-service/tests/test_bi_hardening.py`
- `services/ai-service/tests/test_forecasting_pipeline.py`
- `services/visualization-service/visualization_api/services/metabase_service.py`
- `services/visualization-service/visualization_api/views.py`
- `services/visualization-service/visualization_api/tests/test_metabase_service.py`
- `services/voice-service/voice_reports/views.py`
- `services/report-service/voice_reports/views.py`
- `docs/reports/audits/visualization_and_chart_pipeline_fix_report.md`

## Behavior Changes

- Daily trend questions over day-grain date columns now project the metric directly and order by period.
- Weekly/monthly/quarterly/yearly rollups still aggregate when the source grain does not match the requested grain.
- Relationship questions preserve numeric-vs-numeric shape and map to scatter when valid.
- Time-series questions preserve line chart intent through voice-service visualization settings.
- Forecast responses include explicit actual/forecast series metadata, colors/styles, `forecast_start_date`, and `forecast_boundary_index`.
- Forecast visualizations are `success` when forecast points are available; `degraded` is reserved for historical-only or failed forecast fallback.
- Visualization service returns actual Metabase display, `fallback_applied`, and `fallback_reason`.
- Voice report `chart_config` now persists selected chart type, selection reason, Metabase display, fallback reason, and forecast series config.

## Generic Trend SQL Fix

The AI planner now computes:

- `source_grain_matches_requested`
- `time_rollup_required`

This is schema-based and dataset-agnostic:

- `Date` columns or columns named like `ds`, `date`, or `*_date` satisfy requested day grain.
- Datetime/timestamp columns do not automatically satisfy day grain because multiple rows per day are common.
- Week/month/quarter/year are considered matching only when the selected time column name clearly represents that grain.

When source grain matches the requested time grain, metric inference suppresses implicit `SUM`/`AVG` rollups and emits direct metric projection. When grain does not match, existing aggregation behavior remains.

## Forecast Success vs Degraded

Forecast status now follows capability:

- `success`: actual and forecast series were generated.
- `degraded`: forecast unavailable, invalid input for forecasting, historical-only fallback, or forecast handler failure.

Predictive mode alone no longer implies degraded visualization.

## Actual vs Forecast Metadata

Forecast datasets and voice-service visualization settings now preserve:

- `series_type`: `actual` / `forecast`
- `series_label`: `Actual` / `Forecast`
- `preferred_color_role`: `actual` / `forecast`
- `chart_series_config`
- `forecast_start_date`
- `forecast_boundary_index`
- `graph.breakout`: `series_type` for forecast line charts where available

## Metabase Fallback Policy

Supported mappings:

- `line` -> Metabase `line`
- `scatter` -> Metabase `scatter`
- `bar` -> Metabase `bar`
- `card` / `kpi` / `number` -> Metabase `scalar`
- `histogram` -> Metabase `histogram`
- `table` -> Metabase `table`

Fallbacks are now explicit:

- Missing display uses result shape to choose line/scatter/bar/histogram/scalar/table.
- Unsupported display records `unsupported_display:<type>`.
- Invalid scatter shape falls back to the safest valid display and records `invalid_scatter_shape`.
- Invalid histogram shape records `invalid_histogram_shape`.
- Explicit line displays are preserved when axes are unresolved and no safer non-table shape is known, with `line_axes_unresolved_preserved`.

## Tests Added or Updated

- Daily trend over time -> line chart and no incorrect `SUM`.
- Weekly totals -> line chart with correct roll-up aggregation.
- Average per day on daily grain -> line chart and no incorrect `SUM`.
- Forecast success -> `success`, not degraded.
- Actual vs forecast metadata includes boundary and styling metadata.
- Metabase valid scatter stays scatter.
- Missing display with time-series shape becomes line, not table.
- Unsupported/invalid fallback records a truthful fallback reason.
- Voice chart-selection tests continue to pass for line/scatter/bar/card/histogram and upstream chart propagation.

## Verification

Commands run:

```powershell
$env:PYTHONPATH='services/ai-service'; python -m pytest services/ai-service/tests/test_bi_hardening.py services/ai-service/tests/test_forecasting_pipeline.py
python -m pytest services/visualization-service/visualization_api/tests/test_metabase_service.py
python -m pytest services/voice-service/voice_reports/tests_chart_selection.py
python -m py_compile services/voice-service/voice_reports/views.py services/report-service/voice_reports/views.py services/visualization-service/visualization_api/views.py services/visualization-service/visualization_api/services/metabase_service.py services/ai-service/shared/query_planner.py services/ai-service/forecasting/pipeline.py
```

Results:

- AI service focused tests: 18 passed.
- Visualization service Metabase tests: 15 passed.
- Voice chart-selection tests: 14 passed.
- Python compile check: passed.

## Remaining Risks

- Metabase support for multi-series native SQL charts can vary by version; the service now preserves `series_type` and `graph.breakout`, but final visual styling depends on Metabase behavior.
- Report-service has a legacy direct-Metabase path; it was improved for intent-aware line/scatter selection, but the voice-service plus visualization-service path remains the stronger canonical path.
- Frontend currently renders Metabase embeds rather than local chart primitives, so actual/forecast visual distinction is primarily supplied through Metabase settings and persisted metadata.
