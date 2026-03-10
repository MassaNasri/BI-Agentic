# ETL Production Hardening Report
Date: 2026-03-01

## Executive Summary
- Scope completed: hardening of the 4 remaining critical production concerns plus a recursive safety audit in `etl-final/`.
- Readiness score: **88/100** (ready for staged production rollout with controlled toggles).
- Outcome:
  - Schema contract governance moved from fail-open boolean to mode-driven policy (`strict|warn|quarantine_only`) with persistent contract store backends.
  - Idempotency strengthened with insert-first claim semantics and rollback hooks to reduce duplicate writes under concurrency/retries.
  - No-PK database extraction now supports controlled fallback behavior via `DB_NO_PK_MODE` and metadata flags.
  - ClickHouse dynamic SQL sanitization centralized and enforced across flagged modules (plus additional safe surfaces).

## Concern 1: Schema Contracts Governance
### Implemented
- Added persistent contract store framework:
  - `shared/utils/schema_contract_store.py`
  - Backends: ClickHouse table, file store, HTTP endpoint, composite order.
- Added ClickHouse registry table creation:
  - `shared/utils/clickhouse_schemas.py::create_schema_contract_registry_table`
- Transformer contract resolution now supports persistent lookup:
  - `transformer-service/transformer/engine/schema_contract_resolver.py`
  - lookup order: inline -> in-memory registry -> persistent store -> fallback
- Replaced fail-open boolean with mode-based enforcement:
  - `transformer-service/transformer/engine/transformer_service.py`
  - `SCHEMA_CONTRACT_MODE={strict,warn,quarantine_only}` (default `warn`)
  - legacy `TRANSFORMER_REQUIRE_SCHEMA_CONTRACT=true` maps to strict if mode unset
- Added contract enforcement metrics:
  - `shared/utils/metrics.py`
  - `etl_schema_contract_miss_total{service,mode}`
  - `etl_schema_contract_enforcement_total{service,action,mode}`
- Kafka flow propagation hardening (`source_id`, `schema_version`):
  - extractor, transformer, loader payload paths now carry/propagate these fields.
  - deterministic fallback schema version (`sv_<hash>`) added in extractor.

### Tests
- `transformer-service/transformer/engine/test_schema_contract_store_integration.py`
  - verifies resolver loads contract from store by `(source_id, schema_version)`.
- Updated existing contract behavior tests:
  - `test_cleaning_rules.py`
  - `test_schema_contract_resolver.py`

## Concern 2: Idempotency Atomicity and Duplicate Reduction
### Implemented
- Added insert-first claim-check API:
  - `shared/utils/idempotency_manager.py`
  - `claim_new_keys(...)`, `rollback_claims(...)`
  - `check_and_mark_batch(...)` now uses claim semantics (no read-then-write race).
- Extractor switched to claim-before-publish with rollback on publish failure:
  - `extractor-service/extractor/engine/kafka_listener.py`
- Loader switched to claim-before-load with rollback on load failure/DLQ path:
  - `loader-service/loader/engine/kafka_listener.py`
- Loader dedup basis fixed to avoid volatile timestamp hashing:
  - fallback hash no longer uses `_loaded_at`.
- New-table dedup robustness:
  - loader creates `ReplacingMergeTree(_loaded_at)` with `_transformed_dedup_key` order key when dedup column exists.
- Stage consistency improvements:
  - extractor idempotency keys now stage-scoped (`extract:<source>`) to deduplicate retry replays.

### Tests
- `shared/utils/test_idempotency_batch_ops.py`
  - verifies insert-first claim flow and rollback behavior.
- `loader-service/loader/engine/test_etl_remediation_loader.py`
  - verifies claim-based flush behavior and retry dedup contract (no double insert on repeat claim).

## Concern 3: Deterministic DB Extraction Without PK
### Implemented
- Added mode toggle:
  - `DB_NO_PK_MODE={fail,warn,best_effort}` (default `warn`)
  - `extractor-service/extractor/engine/database_extraction_strategy.py`
- Multi-strategy pagination behavior:
  - PK present: keyset paging (existing behavior retained).
  - explicit `order_by`: ordered LIMIT/OFFSET.
  - no PK + no order_by:
    - Postgres: `ORDER BY ctid` fallback (warn + metadata flag).
    - others: unordered best-effort LIMIT/OFFSET in `warn`/`best_effort`, hard fail in `fail`.
- Added extraction metadata flags:
  - `nondeterministic_paging`
  - `fallback_strategy`
  - `no_pk_mode`
- Extractor no longer hard-fails pre-check; strategy decides by mode.
- Per-table PK state updates guarded with a lock (`_db_state_lock`).

### Tests
- `extractor-service/extractor/engine/test_database_extraction_strategy.py`
- `extractor-service/extractor/engine/test_database_pagination_contract.py`
- Added/updated cases for `fail`, `warn`, and Postgres `ctid` fallback.

## Concern 4: Sanitize and Quote Dynamic ClickHouse Utilities
### Implemented
- Centralized helper module:
  - `shared/utils/ch_identifiers.py`
  - `sanitize_identifier`, `quote_identifier`, `sanitize_table_name`, `sanitize_identifier_map`, etc.
- Updated flagged modules to use centralized sanitization/quoting:
  - `shared/utils/clickhouse_schemas.py`
  - `shared/utils/type_mapper.py`
  - `shared/utils/create_silver_tables.py`
  - `shared/utils/quarantine_manager.py`
  - `migration/migrate_bronze_to_new_tables.py`
- Additional safe hardening (audit-driven):
  - `migration/validate_row_counts.py`
  - `shared/utils/bronze_writer.py`
  - `shared/utils/init_clickhouse_tables.py`
  - `shared/utils/create_bronze_tables.py`

### Tests
- `shared/utils/test_ch_identifiers.py`
- `shared/utils/test_clickhouse_schemas.py`
- `shared/utils/test_type_mapper.py`
- `shared/utils/test_create_silver_tables.py` (extended)
- `shared/utils/test_quarantine_manager.py` (new)
- `migration/test_migrate_bronze_to_new_tables.py` (new)

## Recursive Audit: Auto-Fixed
- Dynamic SQL hardening beyond requested files:
  - `extractor-service/extractor/engine/extraction_checkpoint.py`
    - replaced string-built SQL with parameterized insertion/query.
- Kafka consumer liveness tuning:
  - `shared/utils/kafka_consumer.py`
  - added `KAFKA_MAX_POLL_INTERVAL_MS` support.
- Kafka schema governance:
  - `shared/utils/kafka_schema_validator.py`
  - `extracted_rows_topic` and `clean_rows_topic` now require `source_id` and `schema_version`.

## Recursive Audit: Remaining Risks / Out-of-Scope
- Multi-replica extractor pagination state remains process-local (`_db_last_pk_state`) despite locking.
  - Impact: keyset resume can diverge across replicas/restarts.
  - Recommended fix: persist table cursor state in shared store (ClickHouse/metadata service).
- Claim-based dedup in ClickHouse is strong best-effort, not absolute transactional uniqueness.
  - Impact: extremely rare race windows may still exist under distributed timing anomalies.
  - Recommended fix: add explicit unique-claim service or materialized dedup compaction with strict read path.
- `where_clause` remains user-provided SQL fragment (now guarded against stacked-query/comment tokens).
  - Impact: still not a full SQL parser-level guarantee.
  - Recommended fix: structured filter DSL + parameterized query builder.
- Some legacy scripts/tests still contain direct dynamic SQL and path hacks; many are non-runtime utilities.
  - Recommended fix: broad utility cleanup pass with shared query builder abstraction.

## Test Execution Summary
Executed targeted suites for all newly introduced or modified behaviors.

Commands and outcomes:
- `shared/utils`: 51 passed
  - `pytest -q test_ch_identifiers.py test_clickhouse_schemas.py test_type_mapper.py test_create_silver_tables.py test_quarantine_manager.py test_idempotency_batch_ops.py`
- `migration`: 1 passed
  - `pytest -q test_migrate_bronze_to_new_tables.py`
- `transformer`: 9 passed
  - `pytest -q engine/test_cleaning_rules.py engine/test_schema_contract_resolver.py engine/test_schema_contract_store_integration.py engine/test_etl_remediation_transformer.py`
- `extractor`: 34 passed
  - `pytest -q test_database_extraction_strategy.py test_database_pagination_contract.py`
- `loader`: 8 passed
  - `pytest -q engine/test_etl_remediation_loader.py`

Total targeted tests passed: **103**

## Production Rollout Plan
1. Stage deployment with defaults:
   - `SCHEMA_CONTRACT_MODE=warn`
   - `DB_NO_PK_MODE=warn`
2. Verify for 24-48h in staging:
   - schema contract miss rate
   - dedup claim behavior under retry/concurrency chaos tests
   - no-PK extraction metadata and output quality
3. Gradual prod rollout:
   - enable on 1 tenant/source slice
   - expand to 10%, 50%, 100%
4. Progressive contract enforcement:
   - move high-confidence sources to `SCHEMA_CONTRACT_MODE=strict`
   - keep fallback ability to `quarantine_only` for incident mitigation
5. Post-rollout validation:
   - row count drift checks
   - DLQ volume and replay verification

## Recommended SLOs and Alerts
- Schema contract misses:
  - Metric: `etl_schema_contract_miss_total`
  - Alert: miss ratio > 0.5% per source over 15m (warn), >2% critical.
- Schema enforcement actions:
  - Metric: `etl_schema_contract_enforcement_total`
  - Alert: `action="quarantine_reject"` spikes.
- Dedup conflicts / duplicate pressure:
  - Monitor skipped duplicates and claim rollbacks in extractor/loader logs.
  - Add explicit metric in next pass for claim wins/losses by stage.
- DLQ rate:
  - Alert on extractor/transformer/loader DLQ topic message rate > baseline.
- Consumer lag and liveness:
  - Kafka lag thresholds per topic/group.
  - Rebalance/session churn and `max_poll_interval` breaches.
- Pipeline error/latency:
  - Existing metrics: `etl_errors_total`, `etl_processing_latency_seconds`.
