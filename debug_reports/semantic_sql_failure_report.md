# Semantic SQL Failure Root-Cause Report

## 1) Overview of the Problem

Valid analytical queries are failing before or during SQL generation in the Dagster pipeline, while deterministic planner/compiler unit tests for the same intents pass.

Observed outcomes:
- Failing: Case 1, Case 2, Case 3, Case 4
- Working: Case 5

Key finding: failures are primarily integration-stage failures (preprocessing_high rejection gates, query mutation, and review gating), not core `query_planner` / `sql_compiler` capability limits.

Evidence run during investigation:
- `python -m pytest services/ai-service/llm_app/tests.py -q` -> `23 passed`
- `python -m pytest services/ai-service/reasoning_app/tests.py -q` -> `32 passed`

## 2) Per-Case Deep Analysis

### Case 1: "Show the city with the highest population"

Expected IR (deterministic planner):
- table: `population_distribution_csv`
- dimensions: `[city]`
- metrics: `SUM(total_population)`
- order_by: `sum_total_population DESC`
- limit: `1`
- intent: `ranking`

Expected SQL:
```sql
SELECT city,
       SUM(total_population) AS sum_total_population
FROM etl.population_distribution_csv
GROUP BY city
ORDER BY sum_total_population DESC
LIMIT 1;
```

Actual pipeline behavior (most likely break):
- `preprocessing_low`: usually fine.
- `preprocessing_high`: schema mappings may exist, but diagnostics can still mark query invalid due unresolved ranking tokens (e.g., `highest`).
- Gate rejects before intent extraction/SQL stages.

Mismatch:
- Expected: continue to IR+SQL.
- Actual: rejection at schema-validation gate despite a semantically valid analytical request.

Failure stage:
- `preprocessing_high` -> enforced again in Dagster execution routing guard.

---

### Case 2: "Show the 2regionswith the lowest average age"

Expected IR (if normalized correctly):
- dimensions: `[region]`
- metrics: `AVG(age)`
- order_by: `avg_age ASC`
- limit: `2`

Expected SQL:
```sql
SELECT region,
       AVG(age) AS avg_age
FROM etl.population_distribution_csv
GROUP BY region
ORDER BY avg_age ASC
LIMIT 2;
```

Actual observed:
- Query text remains malformed as `2regionwith` (or similar merged token).
- Semantic extraction and/or ranking limit inference degrade.

Verified behavior:
- Deterministic low cleaner can repair `2regionwith` -> `2 region with`.
- But high correction stage can still re-mutate text (no structural guard).
- If malformed reaches planner: ranking may infer `limit=1` instead of `2`.
- Diagnostics can reject due unresolved `regionwith` / `lowest`.

Failure stage:
- Primary: `preprocessing_high` correction/validation quality.
- Secondary: ranking extraction degraded by malformed token.

---

### Case 3: "Show cities in the North region"

Expected IR:
- dimensions/metric projection for city
- filter: `region = 'north'`
- intent: `filtering`

Expected SQL:
```sql
SELECT city
FROM etl.population_distribution_csv
WHERE region = 'north';
```

Actual likely behavior:
- Mapping identifies `city` and `region`.
- Diagnostics treats literal filter value `north` as unresolved schema term.
- `schema_validation_status` becomes invalid -> request rejected before SQL stages.

Mismatch:
- Expected literal value handling in filters.
- Actual literal value treated as missing schema column.

Failure stage:
- `preprocessing_high` diagnostics-based rejection.

---

### Case 4: "Show total population for cities where employment rate is above 55"

Expected IR:
- dimensions: `[city]`
- metric: `SUM(total_population)`
- filter: `employment_rate > 55`

Expected SQL:
```sql
SELECT city,
       SUM(total_population) AS sum_total_population
FROM etl.population_distribution_csv
WHERE employment_rate > 55
GROUP BY city;
```

Actual likely behavior:
- Mapping detects `employment_rate`.
- Diagnostics may mark `where` / `above` (and similar non-schema tokens) unresolved.
- Query rejected before SQL generation.
- In mutation branch, high correction may drop/alter comparison expression, producing missing filter semantics downstream.

Failure stage:
- Primary: `preprocessing_high` diagnostics rejection.
- Secondary: correction stage may degrade comparison phrase before extraction.

---

### Case 5: "Show male and female population by region" (working)

Why this works more often:
- Strong direct schema anchors (`male_population`, `female_population`, `region` equivalents).
- No literal region value (`north`), no explicit comparator phrase (`above 55`), no ranking token dependency (`highest`/`lowest`).
- Lower chance of unresolved residual-term rejection in `preprocessing_high`.

Result:
- IR reaches planner/compiler and SQL is generated correctly.

## 3) Root Causes (Full List)

### RC-1 (Critical)
- File: `services/ai-service/preprocessing_high/diagnostics.py`
- Function: `_extract_residual_terms`, `build_schema_resolution_diagnostics`
- Issue: non-schema analytical words/literals are treated as unresolved schema terms (e.g., `highest`, `lowest`, `north`, `above`, `where`).

### RC-2 (Critical)
- File: `services/ai-service/preprocessing_high/diagnostics.py`
- Function: `_STOP_WORDS`
- Issue: stop-word set is missing many legitimate analytical/control tokens used in valid queries, causing false unresolved terms.

### RC-3 (Critical)
- File: `services/ai-service/preprocessing_high/preprocess_high_task.py`
- Function: `run_preprocess_high`
- Issue: rejection condition uses diagnostics status (`schema_validation_status != valid`) even when core schema mapping can be otherwise valid.

### RC-4 (Critical)
- File: `services/ai-service/dagster_pipeline/assets/execution.py`
- Function: `pipeline_result_asset`
- Issue: second hard gate rejects pipeline when `preprocessing_high.status == success` but `schema_validation_status != valid`, preventing IR/SQL generation.

### RC-5 (High)
- File: `services/ai-service/preprocessing_high/llm_client.py`
- Function: `correct_query_terms`, `_normalize_correction_output`
- Issue: no semantic/structure guard after LLM correction; corrected text can become malformed (`2regionwith`) or lose operator semantics.

### RC-6 (High)
- File: `services/ai-service/dagster_pipeline/assets/execution.py`
- Function: `query_execution_asset`
- Issue: SQL review rejection (`review_status == rejected`) raises exception and fails pipeline even if compiler SQL was valid.

### RC-7 (Medium)
- File: `services/ai-service/dagster_pipeline/assets/intent_extraction.py`
- Function: `intent_extraction_asset`
- Issue: schema scoping to `selected_columns` can over-narrow schema and reduce semantic extraction quality when selected columns are incomplete.

### RC-8 (Medium)
- File: `services/ai-service/intent_extraction/validation.py`
- Function: `validate_structured_intent`
- Issue: defaults (`aggregation='SUM'`, ranking-driven auto limit/order) can rewrite weak/mutated intents, masking upstream corruption and producing unexpected semantics.

### RC-9 (Medium)
- File: `services/ai-service/llm_app/views.py`
- Function: `intent_test_view`
- Issue: response `intent` is taken from `intent_extraction.normalized_intent` (often absent), reducing observability and making failures appear as "no IR".

### RC-10 (Medium)
- File: `services/ai-service/intent_extraction/intent_extraction_task.py`
- Function: `run_intent_extraction_stage`
- Issue: fallback path can return success after LLM failure; underlying extraction issues may be masked as intermittent behavior.

## 4) Pipeline Breakdown Map

| Stage | Input | Output | Issue |
|---|---|---|---|
| preprocessing_low | raw query | cleaned text | Generally okay; deterministic cleaner can fix merged tokens. |
| preprocessing_high correction | cleaned text + schema | `final_query` | LLM correction can mutate valid text (`2regionwith`) and comparator phrasing. |
| preprocessing_high diagnostics | original/corrected query + mappings | `schema_validation_status` | False unresolved terms for ranking words, literals, and operators. |
| preprocessing_high gate | diagnostics + validation | success/rejected | Over-strict rejection blocks valid analytical queries. |
| intent_extraction | final_query + (scoped) schema | extracted/validated intent | Sometimes skipped due earlier rejection; schema narrowing can reduce quality. |
| routing | validated intent | routed payload | Preserves payload when reached. |
| sql_generation | query + validated intent + schema | compiled SQL | Deterministic path works in tests for all 5 intents. |
| sql_review | generated SQL + intent | reviewed SQL / rejected | Rejection can hard-fail pipeline even on otherwise valid SQL. |
| final response | all stage outputs | API payload | Intent observability mismatch can hide what actually happened. |

## 5) Working vs Failing Comparison

Why Case 5 works while 1-4 fail:
- Case 5 uses direct schema-resembling tokens (`male/female population`, `region`) with less dependence on literals or ranking/comparison words.
- Cases 1-4 include words currently misinterpreted as unresolved schema terms:
  - ranking words: `highest`, `lowest`
  - filter value: `north`
  - comparator phrasing: `where`, `above`
- In failing cases, diagnostics/gating stop the pipeline before SQL compilation, or correction mutates query structure before extraction.

## 6) Recommended Fixes (Not Implemented)

1. Relax diagnostics unresolved-term logic to ignore non-schema analytical keywords and literal filter values.
2. Expand stop-word/keyword handling (`highest/lowest/above/below/where/is/north/...`) with context-aware filtering.
3. Gate on `validation_result.is_valid` (schema references) rather than residual lexical tokens.
4. Add post-correction guardrails for `final_query` (token-boundary, comparator, numeric-limit, and ranking phrase integrity checks).
5. Add a deterministic fallback normalizer before extraction when corrected query contains merged tokens.
6. Change SQL review behavior from hard-fail-on-rejected to fallback-to-compiler-SQL when safety + validator pass.
7. Make schema narrowing optional or confidence-based; keep full-table schema when column confidence is low.
8. Improve trace/response observability: always expose `validated_intent`, `normalized_intent`, and stage rejection reason clearly.
9. Add integration tests for these exact 5 cases through full Dagster pipeline with mocked LLM responses.
10. Add assertion tests that schema diagnostics do not reject queries for ranking tokens, comparator words, and literal values.

## 7) Confidence Level

| Issue | Confidence | Criticality |
|---|---|---|
| RC-1 diagnostics unresolved-term false positives | High | Critical |
| RC-2 incomplete stop-word/keyword coverage | High | Critical |
| RC-3 preprocess_high rejection gate too strict | High | Critical |
| RC-4 execution-level secondary rejection gate | High | Critical |
| RC-5 high correction mutates query semantics | Medium-High | High |
| RC-6 sql_review hard-fail behavior | Medium | High |
| RC-7 schema over-narrowing before extraction | Medium | Medium |
| RC-8 validation defaults rewrite weak intents | Medium | Medium |
| RC-9 response intent observability mismatch | Medium | Medium |
| RC-10 fallback masks root extraction failures | Medium | Medium |

---

## Investigator Notes

This analysis used:
- code-path tracing across preprocessing, extraction, IR normalization, compiler, review, and Dagster orchestration
- deterministic unit-test execution for planner/compiler behavior
- targeted local repro scripts for IR/SQL generation and token handling

No code fixes were applied.
