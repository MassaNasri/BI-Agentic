# End-to-End NL-to-SQL Fix Report

## 1) Root Causes Found

1. False schema failures in `preprocessing_high` diagnostics
- Analytical language (`highest`, `lowest`, `where`, `above`) and literal values (`north`, numeric constants) were misclassified as unresolved schema references.

2. Duplicate/over-strict rejection gates
- The pipeline could reject in `preprocessing_high`, then reject again in Dagster orchestration based on `schema_validation_status` even after success status.

3. High-level correction could mutate semantics
- Post-LLM correction lacked structural guards for ranking direction, limits, comparison expressions, and filter clauses.

4. IR contract not explicitly enforced at execution boundary
- Query execution accepted any non-empty `validated_intent` object without strict shape validation.

5. SQL review could block valid compiler SQL
- Review-stage rejections could fail execution even when compiler SQL was valid and safe.

6. Schema scoping could over-narrow context
- Intent extraction sometimes narrowed schema down to selected columns, risking loss of relevant fields.

7. Observability gaps
- API and trace outputs did not consistently expose normalized/validated intent and lexical-vs-schema diagnostics.

## 2) Files Modified

1. `services/ai-service/preprocessing_high/diagnostics.py`
2. `services/ai-service/preprocessing_high/llm_client.py`
3. `services/ai-service/preprocessing_high/schemas.py`
4. `services/ai-service/dagster_pipeline/assets/execution.py`
5. `services/ai-service/dagster_pipeline/assets/intent_extraction.py`
6. `services/ai-service/shared/sql_review.py`
7. `services/ai-service/llm_app/views.py`
8. `services/ai-service/reasoning_app/tests.py`
9. `services/ai-service/shared/tests_sql_review.py`
10. `services/ai-service/tests/test_pipeline_integration.py` (new)

## 3) Exact Logic Changed Per File

### `preprocessing_high/diagnostics.py`
- Expanded analytical/control stopword handling.
- Added literal-filter extraction (`_extract_literal_filter_terms`) so literal values and comparison connectors are not treated as schema misses.
- Added token-level schema semantic lookup (`_column_token_lookup`) to map terms like `male` -> `male_population` when unambiguous.
- Split unresolved semantics:
  - `unresolved_terms`: schema-relevant unresolved terms only
  - `unresolved_lexical_terms`: residual lexical terms tracked for transparency
- Changed `schema_validation_status` to derive from true schema unresolved/unsupported conditions, not harmless analytical vocabulary.

### `preprocessing_high/llm_client.py`
- Added correction structural guardrails:
  - preserves ranking language/direction
  - preserves numeric limits
  - preserves filter/comparison signals
  - preserves explicit numeric constants
- If corrected output violates structural guardrails, fallback to original cleaned query.

### `preprocessing_high/schemas.py`
- Added `unresolved_lexical_terms` to typed result payload.

### `dagster_pipeline/assets/execution.py`
- Removed secondary hard rejection path (`status=success && schema_validation_status!=valid`) to eliminate duplicate false rejections.
- Added IR contract validator at query execution boundary requiring complete semantic fields.
- Changed SQL review behavior in execution stage:
  - if review rejects, preserve compiler SQL and continue (`sql_review_outcome=fallback_compiler`) instead of failing.
- Expanded trace payloads for preprocessing and analytical intent stages with richer diagnostics/query context.

### `dagster_pipeline/assets/intent_extraction.py`
- Changed schema scoping behavior:
  - still narrows by selected table
  - avoids column-level over-narrowing by default to keep relevant semantic context.

### `shared/sql_review.py`
- Added semantics-safe fallback:
  - when LLM review returns `rejected`, preserve compiler SQL if valid/safe and return approved fallback notes.

### `llm_app/views.py`
- Fixed intent handoff observability:
  - prefer `query_execution.normalized_intent`
  - include `validated_intent` explicitly
  - avoids "no IR" confusion in API response.

## 4) Preprocessing-High Diagnostics Redesign

The redesigned diagnostics now separates:
- true schema references
- analytical control words
- ranking/comparison language
- literal filter values
- unresolved schema terms

Result:
- valid analytical language no longer triggers schema rejection
- unresolved schema terms still correctly fail
- transparency still shows lexical residue (`unresolved_lexical_terms`) without blocking execution.

## 5) Rejection Gate Fixes

- Removed Dagster duplicate gate that re-rejected successful preprocessing output by lexical status.
- Pipeline now trusts stage status from `preprocessing_high` as source of truth.
- Gate conditions now align to real schema/safety errors.

## 6) IR Completeness Guarantee

Added execution-boundary IR contract checks requiring:
- `intent`, `operations`, `table`
- `metrics`, `dimensions`, `filters`
- `aggregation`, `ranking`, `order_by`, `limit`, `ambiguities`

If contract fails, pipeline fails explicitly with a deterministic IR error (no silent partial-IR progression).

## 7) SQL Review Semantics Safety

- Review rejection no longer destroys valid compiler output.
- Compiler SQL is preserved when review drifts or rejects.
- SQL safety validation remains enforced (`validate_sql` still mandatory).
- Semantic drift is prevented by compiler-preserving fallback path.

## 8) Schema Scoping Improvements

- Retained table-level narrowing for relevance and noise control.
- Removed default column-level narrowing that could hide needed fields.
- This reduces schema flooding while avoiding semantic starvation.

## 9) Observability Improvements

Added/expanded observable fields across pipeline:
- original vs corrected term diagnostics
- unresolved schema vs unresolved lexical terms
- extracted and validated intent visibility
- query and schema table context at analytical-intent stage
- normalized intent surfaced at API layer
- explicit review fallback outcome (`fallback_compiler`)

## 10) Test Coverage Added/Updated

### Updated tests
- `services/ai-service/reasoning_app/tests.py`
  - added coverage for ranking words, literal filter values, and comparison language not being treated as unresolved schema references.

- `services/ai-service/shared/tests_sql_review.py`
  - added test verifying review rejection preserves compiler SQL.

### New integration-style tests
- `services/ai-service/tests/test_pipeline_integration.py`
  - pipeline does not double-reject on secondary schema status when stage success is present.
  - query execution falls back to compiler SQL when review rejects.

## 11) Before vs After Behavior (Diverse Examples)

Before:
- "Show cities in the North region" -> often rejected in preprocessing_high due `north` unresolved.
- "Show total population ... employment rate is above 55" -> often rejected due `where/above` unresolved.
- review rejection could fail pipeline despite valid compiler SQL.

After:
- literal values/comparison/ranking language are not schema-fatal by default.
- valid analytical queries continue to extraction/IR/SQL stages.
- review rejection preserves compiler SQL if safe.
- IR contract errors are explicit and stage-bounded.

## 12) Why This Is Domain-Agnostic

The implementation avoids hardcoded schema/domain assumptions by using:
- schema-driven column/table resolution
- generalized analytical-language classification
- generic comparator/ranking/filter semantics
- IR contract validation independent of dataset names
- table-level schema relevance filtering without domain-specific exceptions

This supports heterogeneous schemas (finance, healthcare, sales, HR, logistics, etc.) while preserving safety and semantic correctness.

## Test Run Summary

Executed successfully:
- `python -m pytest services/ai-service/llm_app/tests.py -q`
- `python -m pytest services/ai-service/reasoning_app/tests.py services/ai-service/shared/tests_sql_review.py services/ai-service/tests/test_pipeline_integration.py -q`

Combined outcome:
- 67 tests passed in the targeted suites.
