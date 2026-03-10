# ETL Pipeline Architecture (Implemented)

**Scope:** This document reflects the code currently implemented in `etl-final` as of Phase 5 completion.

## System Overview

The ETL pipeline is a microservices architecture built on Kafka, ClickHouse, and SurrealDB.

Services:
- `connector-service` (HTTP ingress for file uploads and DB connections)
- `detector-service` (optional schema detection)
- `extractor-service` (extraction + Kafka publishing + bronze writes)
- `transformer-service` (rule-driven cleaning + schema validation + quarantine + quality metrics)
- `loader-service` (ClickHouse loading + transactional staging + retries)
- `metadata-service` (metadata queries + lineage + quality trends)

Infrastructure:
- Kafka (topics for extraction, transformation, loading, metadata)
- ClickHouse (bronze/silver data + quarantine + quality metrics)
- SurrealDB (metadata + lineage graph)

## Data Flow (Actual)

```
Client -> connector-service
  POST /upload/ or /connect-db/
  -> Kafka: connection_topic

extractor-service
  consumes connection_topic
  emits schema_topic + extracted_rows_topic (batched)
  writes bronze directly (in extraction strategies)

transformer-service
  consumes extracted_rows_topic (batched)
  applies CleaningRules + RulesEngine + SchemaValidator
  quarantines invalid rows
  emits clean_rows_topic (batched)
  writes quality metrics to ClickHouse

loader-service
  consumes clean_rows_topic (batched)
  transactional-like staging + insert-from-select
  emits load_rows_topic + metadata_topic

metadata-service
  reads SurrealDB logs + lineage
  queries ClickHouse quality_metrics
```

## Kafka Topics (Implemented)

- `connection_topic` (connector -> extractor)
- `schema_topic` (extractor -> metadata/detector)
- `extracted_rows_topic` (extractor -> transformer)  
  Supports batched payloads using `rows` + `row_count`.
- `clean_rows_topic` (transformer -> loader)  
  Supports batched payloads using `rows` + `row_count`.
- `load_rows_topic` (loader -> metadata)
- `metadata_topic` (all services -> metadata)

## Storage (Implemented)

ClickHouse tables:
- `deduplication_log` (idempotency)
- `quarantine` (invalid rows)
- `quality_metrics`, `quality_anomalies`
- bronze/silver tables created per source (see `shared/utils/clickhouse_schemas.py`)

SurrealDB:
- log tables for connector/extractor/transformer/loader activity
- lineage graph via `LineageTracker`

## Architecture Decisions (Actual)

1. **Batch-first Kafka messaging**  
   Extractor and transformer emit batched rows to reduce broker load and improve throughput.

2. **Stateless processing by default**  
   Services avoid shared mutable state. Optional in-memory caches (SchemaValidator, table schemas) can be disabled using `STATELESS_MODE=true`.

3. **Transactional-like loading**  
   ClickHouse has no transactions; loader uses staging tables + `insert_from_select` and `RENAME` for new tables.

4. **Idempotency at each stage**  
   Deduplication keys are generated and tracked in ClickHouse.

5. **Deterministic lineage IDs**  
   Lineage IDs use deterministic UUIDv5 to avoid duplicates across retries.

6. **Structured logging + correlation IDs**  
   Logging is JSON-formatted and correlation-safe.

7. **Observability built in**  
   Prometheus metrics and OpenTelemetry tracing are integrated in all services.

## Observability (Implemented)

- `/metrics/` and `/health/` endpoints for most services.
- Prometheus exporters started in listeners with configurable ports:
  - extractor: `EXTRACTOR_METRICS_PORT` (default 9101), `EXTRACTOR_HEALTH_PORT` (8083)
  - transformer: `TRANSFORMER_METRICS_PORT` (9102), `TRANSFORMER_HEALTH_PORT` (8084)
  - loader: `LOADER_METRICS_PORT` (9103), `LOADER_HEALTH_PORT` (8085)
- Distributed tracing context propagation via Kafka headers.

## Scaling (Implemented)

- Parallel Kafka consumers per service via `KAFKA_CONSUMER_PARALLELISM`.
- Kafka cooperative rebalancing support via `KAFKA_REBALANCE_STRATEGY=cooperative`.
- Kubernetes manifests and HPAs exist in `etl-final/etl-infra/k8s/`.
