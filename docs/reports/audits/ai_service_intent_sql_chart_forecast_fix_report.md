# AI Service Intent, SQL, Chart, Forecast Remediation Report

Date: 2026-04-23

## Scope

Audited and remediated the AI-service path:

`question/transcription -> preprocessing_low -> classification -> preprocessing_high -> intent_extraction -> routing -> SQL planning/generation/review -> execution payload -> forecasting payload -> visualization selection -> trace`.

Primary files changed in this pass:

- `services/ai-service/shared/query_planner.py`
- `services/ai-service/shared/chart_recommender.py`
- `services/ai-service/preprocessing_high/diagnostics.py`
- `services/ai-service/preprocessing_high/llm_client.py`
- `services/ai-service/forecasting/pipeline.py`
- `services/ai-service/forecasting/dagster_handler.py`
- `services/ai-service/dagster_pipeline/assets/execution.py`
- `services/ai-service/shared/tests_sql_review.py`
- `services/ai-service/tests/test_forecasting_pipeline.py`
- `services/ai-service/tests/test_preprocessing_high_recovery.py`

## Problems Found And Root Causes

1. Trend wording could collapse into generic aggregation.
   - Root cause: time-grain detection recognized explicit `per day/week/...` language but did not treat `trend/change over time` as a time-series request.
   - Fix: added generic trend-over-time detection and default daily grouping when a business time axis exists.

2. Relationship wording was too narrow.
   - Root cause: relationship detection focused on `relationship/correlation/impact` and missed common comparison phrasing such as `compare A vs B`.
   - Fix: expanded relationship semantics and metric-pair extraction for `compare`, `vs`, `versus`, `with`, `against`, and related wording.

3. Natural-language helper words could leak into schema resolution.
   - Root cause: preprocessing-high diagnostics and deterministic schema validation had stopword sets, but helper verbs and analytical words such as `had`, `trend`, and comparison connectors were incomplete.
   - Fix: expanded general stopword/business-language tolerance in schema diagnostics and deterministic fallback validation. This is token/category based, not table-specific.

4. Metric and dimension phrase extraction kept analytical filler.
   - Root cause: extracted hints could include words like `trend`, `relationship`, `over time`, `number`, or helper verbs, weakening schema matching.
   - Fix: added normalized phrase cleaning before metric/dimension resolution.

5. Time-grouped chart selection could fall back to table if the shape-only layer lacked intent context.
   - Root cause: chart selection needed both intent and result shape.
   - Fix: tests now lock trend/time-grouping to line charts and relationship intents to scatter charts. Existing execution-layer validation preserves this priority.

6. Forecast visualization metadata was too implicit.
   - Root cause: forecast rows had `series_type`, but downstream renderers had to infer labels and colors/styles.
   - Fix: added explicit row-level and chart-level machine-readable metadata:
     - `series_type`
     - `series_label`
     - `preferred_color_role`
     - `chart_series_config`
     - `series_type_field`
     - `series_label_field`
     - `preferred_color_role_field`

7. Forecast SQL review trace could look like a failure.
   - Root cause: `skipped_for_forecasting` was a legitimate SQL-review bypass, but trace status mapping did not recognize it as an intentional skip.
   - Fix: pipeline trace now renders forecast SQL review as `skipped`, while SQL generation and validation remain successful when historical extraction SQL is valid.

## Behavior Changes

- `What is the trend of total sales over time?`
  - Intent: `time_series`
  - SQL: grouped by selected time column as `period`
  - Chart: line

- `What is the relationship between customers and total sales?`
  - Intent: `correlation`
  - SQL: projects paired numeric columns without aggregation/grouping
  - Chart: scatter

- `Compare customers vs total sales`
  - Intent: `correlation`
  - Chart: scatter

- `What are the total sales by/per week?`
  - Intent: weekly time series
  - SQL: `toStartOfWeek(...) AS period`, `GROUP BY period`, `ORDER BY period ASC`
  - Chart: line

- `What is the average number of orders per day?`
  - Intent: daily time series
  - SQL: `AVG(orders)` grouped by `period`
  - Chart: line

- `Which days had the highest number of customers?`
  - `had` and other helper words are ignored by schema validation.
  - Ranking SQL keeps an inferable dimension and orders by the customer metric.

- Predictive/forecasting route:
  - Valid historical extraction SQL is not treated as SQL generation failure.
  - SQL review is marked as intentionally skipped for forecasting.
  - Actual and forecast rows carry explicit series metadata and distinct color roles.

## Generalization

The changes are schema-aware and dataset-neutral:

- time columns are selected from generic date/date-like schema metadata;
- numeric measures are resolved by token overlap, type, and semantic metric hints;
- relationship questions require two numeric columns from the active table;
- grouping/ranking uses inferable date or categorical dimensions rather than one hardcoded table;
- regression coverage includes a non-sales `support_metrics` schema with `created_at`, `tickets`, and `response_minutes`.

No fixes depend on `etl.sales_3months_realistic_csv`.

## Forecasting Series Metadata Contract

Forecast visualization payloads now expose:

```json
{
  "chart_type": "line",
  "series_type_field": "series_type",
  "series_label_field": "series_label",
  "preferred_color_role_field": "preferred_color_role",
  "chart_series_config": [
    {
      "series_type": "actual",
      "series_label": "Actual",
      "preferred_color_role": "actual",
      "preferred_color": "#2563eb",
      "stroke_dasharray": ""
    },
    {
      "series_type": "forecast",
      "series_label": "Forecast",
      "preferred_color_role": "forecast",
      "preferred_color": "#f97316",
      "stroke_dasharray": "6 4"
    }
  ]
}
```

Rows also include:

- `series_type`: `actual` or `forecast`
- `series_label`: `Actual` or `Forecast`
- `preferred_color_role`: `actual` or `forecast`

This lets downstream services render actual and forecast as separate line series with distinct colors/styles without relying on frontend magic.

## Tests Added Or Updated

Added/updated regression coverage for:

- trend question -> time-series intent, grouped SQL, line chart
- relationship question -> paired numeric SQL, scatter chart
- `compare A vs B` -> scatter relationship semantics
- weekly totals -> weekly grouped SQL/chart
- average orders per day -> daily time-series SQL/chart
- `Which days had...` -> helper verb ignored by preprocessing-high diagnostics
- predictive SQL builder -> forecast intent remains valid
- actual vs forecast visualization -> explicit series metadata and distinct color hints
- generalization beyond sales schema -> support metrics trend and relationship

## Verification

Focused regression suite:

`python -m pytest services/ai-service/shared/tests_sql_review.py services/ai-service/tests/test_forecasting_pipeline.py services/ai-service/tests/test_preprocessing_high_recovery.py`

Result: `41 passed`

Broader AI-service suite:

`$env:PYTHONPATH='services/ai-service'; python -m pytest services/ai-service/tests services/ai-service/intent_extraction/tests.py services/ai-service/reasoning_app/tests.py services/ai-service/shared/tests_sql_review.py`

Result: `128 passed`

An initial broader run without `PYTHONPATH` failed during import collection only; rerunning with the service path set passed.

## Remaining Risks

- LLM-based classification can still be ambiguous for highly underspecified questions, but the deterministic planner and trace now preserve safer semantics after routing.
- Downstream services must honor the new chart series metadata to render the explicit color/style distinction.
- Forecast quality still depends on having enough clean, regularly spaced historical points.
