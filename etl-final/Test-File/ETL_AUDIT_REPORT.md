# ETL Audit Report (Extract → Transform → Load)

**Scope:** `etl-final` end-to-end audit focused on Extract, Transform, and Load layers, plus shared infrastructure used by the ETL flow.  
**Method:** Manual source review of core pipeline code paths, Kafka ingress/egress, validation, idempotency, and ClickHouse load paths.  
**Assumptions:**  
- This audit is based on source code inspection only (no runtime validation).  
- Large data directories under `etl-infra` (ClickHouse/SurrealDB data files) were not interpreted as source code.  
- Where multiple implementations exist (e.g., extraction strategies vs. listener logic), the audit prioritizes the code paths used by the Kafka listeners.

---

## Executive Summary

The pipeline demonstrates strong structure (batching, lineage, observability, schema contracts, quarantine). However, several critical issues remain in the **core Extract and Load flows**, including **memory exhaustion risks**, **data corruption for certain DB sources**, and **data loss on send/flush failures**. The most severe risks are concentrated in:

- **Extractor**: Full-table fetches and full-file reads in the Kafka listener path.  
- **Load**: Batch flush failures drop data.  
- **Kafka consumption**: Auto-commit semantics can lose data on mid-processing failure.  

Recommended immediate remediation: enforce streaming/pagination everywhere, and change Kafka consume/produce semantics to avoid loss on partial failure.

---

## Findings by Layer

### Extract Layer Findings

#### P0 (Critical)
1) **P0 — Extract — `etl-final/extractor-service/extractor/engine/row_extractor.py`**  
   **Issue:** `cursor.fetchall()` loads entire tables into memory; query uses `SELECT *` with no pagination.  
   **Impact:** High risk of OOM, crashes, and extraction failure on large tables.  
   **Fix:** Replace with server-side pagination (`LIMIT/OFFSET` or keyset pagination) or streaming cursors.  
   **Effort:** Medium

2) **P0 — Extract — `etl-final/extractor-service/extractor/engine/kafka_listener.py`**  
   **Issue:** `process_file()` uses `pd.read_csv()`/`read_excel()` to load entire files in memory.  
   **Impact:** OOM and service crashes on large inputs; violates batch O(batch_size).  
   **Fix:** Switch to `CSVExtractionStrategy` / chunked reading with `chunksize` and batch publishing.  
   **Effort:** Medium

3) **P0 — Extract — `etl-final/extractor-service/extractor/engine/kafka_listener.py`**  
   **Issue:** For Postgres tuple results, `row_dict = {"data": str(row)}` loses column names and structure.  
   **Impact:** Data corruption and loss of schema integrity.  
   **Fix:** Always map tuple rows to column names (use cursor description or DictCursor).  
   **Effort:** Small

4) **P0 — Shared/Extract — `etl-final/shared/utils/kafka_consumer.py`**  
   **Issue:** `enable_auto_commit=True` with no processing transaction boundaries.  
   **Impact:** If a consumer crashes after reading but before downstream publish, messages are acknowledged and lost.  
   **Fix:** Disable auto-commit and commit offsets only after successful downstream write.  
   **Effort:** Medium

5) **P0 — Extract — `etl-final/extractor-service/extractor/engine/kafka_listener.py`**  
   **Issue:** Failed Kafka sends drop batches; no retry or requeue.  
   **Impact:** Data loss on transient broker failures.  
   **Fix:** Add retries/backoff for send failures and requeue failed batches.  
   **Effort:** Medium

#### P1 (Major)
6) **P1 — Extract — `etl-final/extractor-service/extractor/engine/csv_extraction_strategy.py`**  
   **Issue:** Schema validation checks only the first row (`rows[0]`).  
   **Impact:** Schema violations later in batch are not caught; inconsistent data passes through.  
   **Fix:** Validate full batch or a configurable sample size.  
   **Effort:** Medium

7) **P1 — Extract — `etl-final/extractor-service/extractor/engine/database_extraction_strategy.py`**  
   **Issue:** Schema validation checks only the first row (`rows[0]`).  
   **Impact:** Same as above: hidden schema violations.  
   **Fix:** Validate full batch or configurable sample.  
   **Effort:** Medium

8) **P1 — Extract — `etl-final/extractor-service/extractor/engine/kafka_listener.py`**  
   **Issue:** Kafka listener uses custom extraction logic instead of the newer strategies (`CSVExtractionStrategy`/`DatabaseExtractionStrategy`).  
   **Impact:** Missing pagination, missing schema validation controls, inconsistent behavior between code paths.  
   **Fix:** Route the Kafka listener through the extraction strategy interface.  
   **Effort:** Medium

#### P2 (Minor)
9) **P2 — Extract — `etl-final/extractor-service/extractor/engine/views.py`**  
   **Issue:** In-memory progress tracker is not durable and shared across requests only within process.  
   **Impact:** Progress state lost on restarts; misleading progress in multi-replica deployments.  
   **Fix:** Persist progress to Redis/ClickHouse or SurrealDB.  
   **Effort:** Medium

---

### Transform Layer Findings

#### P0 (Critical)
10) **P0 — Transform — `etl-final/shared/utils/kafka_consumer.py`**  
   **Issue:** Same auto-commit semantics apply to transformer consumers; failure after consume but before publish loses data.  
   **Impact:** Data loss or dropped transformation outputs.  
   **Fix:** Manual offset commits after successful `clean_rows_topic` produce.  
   **Effort:** Medium

11) **P0 — Transform — `etl-final/transformer-service/transformer/engine/kafka_listener.py`**  
   **Issue:** Send failures to `clean_rows_topic` do not retry and drop data.  
   **Impact:** Data loss on transient Kafka errors.  
   **Fix:** Add retry/backoff and/or dead-letter topic for failed batches.  
   **Effort:** Medium

#### P1 (Major)
12) **P1 — Transform — `etl-final/transformer-service/transformer/engine/cleaning_rules.py`**  
   **Issue:** Boolean coercion uses `bool(value)` fallback; arbitrary strings (`"nope"`) become `True`.  
   **Impact:** Data correctness issues; silently wrong values.  
   **Fix:** Return error or leave as string when unrecognized.  
   **Effort:** Small

13) **P1 — Transform — `etl-final/transformer-service/transformer/engine/cleaning_rules.py`**  
   **Issue:** `_infer_type` converts `"007"` to `7` (loss of leading zeros).  
   **Impact:** Data corruption for identifiers and codes.  
   **Fix:** Only infer numeric types when schema specifies; otherwise preserve strings.  
   **Effort:** Medium

14) **P1 — Transform — `etl-final/transformer-service/transformer/engine/transformer_service.py`**  
   **Issue:** Schema validation is optional; if no schema contract is provided, rows bypass validation.  
   **Impact:** Schema enforcement gaps; invalid data can pass.  
   **Fix:** Require schema contract for all sources or enforce a default contract.  
   **Effort:** Medium

15) **P1 — Transform — `etl-final/transformer-service/transformer/engine/kafka_listener.py`**  
   **Issue:** In-memory `warnings` and `source_stats` accumulate indefinitely.  
   **Impact:** Potential memory growth over long-running processes.  
   **Fix:** Bound memory (ring buffers) or periodically emit and clear.  
   **Effort:** Small

#### P2 (Minor)
16) **P2 — Transform — `etl-final/transformer-service/transformer/engine/transformer_logic.py`**  
   **Issue:** Appears unused and duplicates transformation functionality.  
   **Impact:** Maintenance overhead and confusion.  
   **Fix:** Remove or consolidate into rules engine.  
   **Effort:** Small

---

### Load Layer Findings

#### P0 (Critical)
17) **P0 — Load — `etl-final/loader-service/loader/engine/kafka_listener.py`**  
   **Issue:** On batch insert failure, buffer is cleared and data is dropped.  
   **Impact:** Data loss on transient ClickHouse or network errors.  
   **Fix:** Retry and only drop after max retries; use DLQ for failed batches.  
   **Effort:** Medium

18) **P0 — Load — `etl-final/shared/utils/kafka_consumer.py`**  
   **Issue:** Auto-commit semantics can acknowledge Kafka offsets before load succeeds.  
   **Impact:** Data loss on failure after consume.  
   **Fix:** Manual commits after successful ClickHouse write.  
   **Effort:** Medium

#### P1 (Major)
19) **P1 — Load — `etl-final/loader-service/loader/engine/loader_logic.py`**  
   **Issue:** “Transactional” flow is not atomic for existing tables (`insert_from_select` with no rollback).  
   **Impact:** Partial inserts can happen on failures; retries can duplicate data.  
   **Fix:** Use table swap strategy or idempotent staging key + deduplication.  
   **Effort:** Large

20) **P1 — Load — `etl-final/loader-service/loader/engine/kafka_listener.py`**  
   **Issue:** Table schema inference uses all `String` types.  
   **Impact:** Loss of type fidelity and inefficient queries.  
   **Fix:** Use schema contracts or type mapper to define proper column types.  
   **Effort:** Medium

21) **P1 — Load — `etl-final/loader-service/loader/engine/kafka_listener.py`**  
   **Issue:** No deduplication check in loader; idempotency manager used only for hashing.  
   **Impact:** Duplicate loads on reprocessing or retry.  
   **Fix:** Check `deduplication_log` before insert or enforce unique keys.  
   **Effort:** Medium

22) **P1 — Load — `etl-final/loader-service/loader/engine/kafka_listener.py`**  
   **Issue:** Backpressure is local to loader; upstream extractor/transformer may still overwhelm Kafka.  
   **Impact:** Lag and downstream pressure if upstream emits too quickly.  
   **Fix:** Coordinated backpressure or dynamic batch throttling.  
   **Effort:** Medium

#### P2 (Minor)
23) **P2 — Load — `etl-final/loader-service/loader/engine/clickhouse_client.py`**  
   **Issue:** No explicit timeout/retry configuration for inserts beyond driver defaults.  
   **Impact:** Harder to tune reliability under load.  
   **Fix:** Expose per-call timeouts and retries.  
   **Effort:** Small

---

## Issue Counts by Severity and Layer

| Severity | Extract | Transform | Load | Shared | Total |
|----------|--------:|----------:|-----:|-------:|------:|
| P0       | 5       | 2         | 2    | 0      | 9     |
| P1       | 3       | 4         | 4    | 0      | 11    |
| P2       | 1       | 1         | 1    | 0      | 3     |

---

## Top 10 Highest-Impact Fixes (Ordered)

1) Replace `RowExtractor.fetchall()` with paginated/streaming extraction.  
2) Make Kafka consumers commit offsets only after successful downstream writes.  
3) Fix extractor DB tuple-to-dict mapping for Postgres.  
4) Add retry/backoff + DLQ for extractor/transformer Kafka send failures.  
5) Stop dropping loader batches on failure; implement retry + DLQ.  
6) Replace pandas full-file reads in extractor listener with chunked extraction strategies.  
7) Enforce schema validation for all sources (require contract or default).  
8) Add deduplication checks in loader (idempotency at load).  
9) Correct boolean/type inference to avoid silent corruption.  
10) Replace non-atomic load strategy for existing tables with swap or idempotent merge strategy.

---

## Quick Wins (High Benefit / Low Effort)

- Fix Postgres row mapping in extractor (`dict(zip(columns,row))`).  
- Change boolean coercion to strict mapping only.  
- Bound transformer warnings list and source_stats size.  
- Add schema validation for full batch or sample in extract strategies.  
- Add send retry with limited backoff in extractor/transformer.

---

## Recommendations & Prioritized Roadmap

**Immediate (P0/P1 blockers):**
- Replace full-table and full-file reads with streaming/pagination in extractor listener path.
- Implement manual Kafka offset commits after downstream success.
- Prevent data loss on failed Kafka sends and ClickHouse inserts.

**Short-Term Stability:**
- Enforce schema contracts across pipeline stages.
- Implement loader deduplication or idempotent writes.
- Correct type coercion and inference rules.

**Mid-Term Improvements:**
- Replace transactional load strategy with atomic swap pattern.
- Add coordinated backpressure and rate control across services.
- Consolidate unused transformer logic to reduce maintenance.

---

## Appendix: Scanned Folders / Key Files

**Folders Reviewed (source code):**
- `etl-final/connector-service/`
- `etl-final/extractor-service/`
- `etl-final/transformer-service/`
- `etl-final/loader-service/`
- `etl-final/metadata-service/`
- `etl-final/shared/`
- `etl-final/migration/`
- `etl-final/tests/`
- `etl-final/docs/`

**Key Files Reviewed (core flow):**
- `etl-final/extractor-service/extractor/engine/kafka_listener.py`
- `etl-final/extractor-service/extractor/engine/row_extractor.py`
- `etl-final/extractor-service/extractor/engine/csv_extraction_strategy.py`
- `etl-final/extractor-service/extractor/engine/database_extraction_strategy.py`
- `etl-final/extractor-service/extractor/engine/db_connector.py`
- `etl-final/transformer-service/transformer/engine/kafka_listener.py`
- `etl-final/transformer-service/transformer/engine/transformer_service.py`
- `etl-final/transformer-service/transformer/engine/cleaning_rules.py`
- `etl-final/transformer-service/transformer/engine/transformer_logic.py`
- `etl-final/shared/utils/kafka_producer.py`
- `etl-final/shared/utils/kafka_consumer.py`
- `etl-final/shared/utils/idempotency_manager.py`
- `etl-final/shared/utils/quarantine_manager.py`
- `etl-final/shared/models/rules_engine.py`
- `etl-final/shared/models/schema_contract.py`
- `etl-final/shared/models/schema_validator.py`
- `etl-final/loader-service/loader/engine/kafka_listener.py`
- `etl-final/loader-service/loader/engine/loader_logic.py`
- `etl-final/loader-service/loader/engine/clickhouse_client.py`

Non-code data directories (`etl-final/etl-infra/clickhouse/data`, `etl-final/etl-infra/surreal_data`) were enumerated but not inspected for logic.
