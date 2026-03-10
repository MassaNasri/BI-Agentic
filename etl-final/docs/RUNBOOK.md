# Operational Runbook

This runbook reflects the implemented services and their operational controls.

## Services and Ports

HTTP APIs:
- connector-service: `8001`
- detector-service: `8002`
- extractor-service: `8003`
- transformer-service: `8004`
- loader-service: `8005`
- metadata-service: `8006`

Health and metrics (listener processes):
- extractor metrics: `EXTRACTOR_METRICS_PORT` (default `9101`)
- transformer metrics: `TRANSFORMER_METRICS_PORT` (default `9102`)
- loader metrics: `LOADER_METRICS_PORT` (default `9103`)
- extractor health: `EXTRACTOR_HEALTH_PORT` (default `8083`)
- transformer health: `TRANSFORMER_HEALTH_PORT` (default `8084`)
- loader health: `LOADER_HEALTH_PORT` (default `8085`)

HTTP `/health/` and `/metrics/` are also exposed in connector/extractor/transformer/metadata/detector services.

## Critical Environment Variables

Kafka:
- `KAFKA_BOOTSTRAP_SERVERS` (default `kafka:9092`)
- `KAFKA_VALIDATION_FAIL_OPEN` (default `false`; if `true`, schema validator exceptions do not block publish/consume)
- `KAFKA_CONSUMER_PARALLELISM` (default `1`)
- `KAFKA_REBALANCE_STRATEGY` (`cooperative` supported)
- `KAFKA_MAX_POLL_RECORDS`
- `KAFKA_FETCH_MAX_BYTES`
- `KAFKA_MAX_PARTITION_FETCH_BYTES`
- `KAFKA_CLIENT_ID` (optional)
- `KAFKA_GROUP_INSTANCE_ID` (optional, static membership)

Batching:
- `EXTRACTOR_BATCH_SIZE`
- `TRANSFORMER_BATCH_SIZE`
- `TRANSFORMER_OUTPUT_BATCH_SIZE`
- `LOADER_BATCH_SIZE`
- `LOADER_BATCH_SIZE_OVERRIDES` (JSON mapping table -> size)

Loader reliability:
- `LOADER_TRANSACTIONAL_LOAD` (default true)
- `LOADER_RETRIES`
- `LOADER_BACKOFF_BASE`
- `LOADER_MAX_BACKOFF`
- `LOADER_MAX_BUFFER_ROWS`
- `LOADER_MAX_BUFFER_ROWS_PER_TABLE`

Connector Kafka trigger reliability:
- `CONNECTOR_KAFKA_SEND_RETRIES` (default `3`)
- `CONNECTOR_KAFKA_SEND_BACKOFF_BASE` (default `0.2`)
- `CONNECTOR_KAFKA_SEND_BACKOFF_MAX` (default `2.0`)

Schema contract behavior:
- `SCHEMA_CONTRACT_MODE` in `{strict,warn,quarantine_only}` (default `warn`)
- `SCHEMA_CONTRACT_STORE_ORDER` (default `clickhouse,file,http`)
- `SCHEMA_CONTRACT_CH_TABLE` (default `schema_contract_registry`)
- `SCHEMA_CONTRACT_FILE_PATH` (optional persistent file fallback)
- `SCHEMA_CONTRACT_HTTP_ENDPOINT` (optional metadata service endpoint)
- `SCHEMA_CONTRACT_HTTP_TIMEOUT` (default `3.0`)
- `TRANSFORMER_REQUIRE_SCHEMA_CONTRACT` is still accepted for backward compatibility; when enabled without `SCHEMA_CONTRACT_MODE`, behavior is `strict`.

Database extraction no-PK behavior:
- `DB_NO_PK_MODE` in `{fail,warn,best_effort}` (default `warn`)
  - `fail`: reject tables without PK and without explicit `order_by`
  - `warn`: continue with safe fallback strategy and mark metadata `nondeterministic_paging=true`
  - `best_effort`: continue without warning-level enforcement

Kafka consumer liveness:
- `KAFKA_MAX_POLL_INTERVAL_MS` (default `300000`)

Extractor reliability:
- `EXTRACTOR_MAX_ERROR_ENTRIES` (default `100`; bounds in-memory sampled error list while `error_count` tracks full failures)

Database pooling (extractor):
- `DB_POOL_ENABLED` (default true)
- `DB_POOL_MIN`
- `DB_POOL_MAX`

Stateless mode:
- `STATELESS_MODE` disables in-memory schema/table caches

ClickHouse:
- `CLICKHOUSE_HOST`
- `CLICKHOUSE_PORT`
- `CLICKHOUSE_USER`
- `CLICKHOUSE_PASSWORD`
- `CLICKHOUSE_DATABASE`

## Startup Checklist

1. Kafka, ClickHouse, SurrealDB are running and reachable.
2. Kafka topics exist (or are auto-created).
3. ClickHouse has required tables initialized (see `shared/utils/init_clickhouse_tables.py`).
4. Environment variables set for services.
5. Start services using `docker-compose` or K8s manifests.

## Standard Operations

### Health Checks
- HTTP: `GET /health/` on each service
- Listener health servers (extractor/transformer/loader): port-specific `/health`

### Metrics
- HTTP: `GET /metrics/` on services that expose it
- Listener metrics servers for extractor/transformer/loader

### Scaling
- Scale via `KAFKA_CONSUMER_PARALLELISM` for worker threads
- Horizontal scale via Kubernetes in `etl-final/etl-infra/k8s/`

### Quarantine Review
- Transformer service:
  - `GET /quarantine/?limit=...&offset=...`
  - `POST /quarantine/reprocess/`

### Schema Contract Onboarding
1. Create/verify registry table:
   - `shared/utils/init_clickhouse_tables.py` now ensures `schema_contract_registry` when ClickHouse store is enabled.
2. Insert a contract version entry:
   - Columns: `source_id`, `schema_version`, `schema_id`, `contract_json`, `updated_at`
   - `contract_json` must be a serialized `SchemaContract.to_dict()` payload.
3. Run pipeline with `SCHEMA_CONTRACT_MODE=warn` and verify:
   - `etl_schema_contract_miss_total`
   - `etl_schema_contract_enforcement_total{action="warn_continue"}`
4. Resolve misses, then switch to `SCHEMA_CONTRACT_MODE=strict` for that source/environment.
5. Keep `quarantine_only` as rollback mode during rollout if strict rejection is too aggressive.

### Source/Schema Propagation
- `extracted_rows_topic` and `clean_rows_topic` now carry:
  - `source`
  - `source_id`
  - `schema_version` (explicit or deterministic derived value)
- Consumers should treat `schema_version` as required contract lookup key.

### Identifier Normalization
- Dynamic ClickHouse utilities now sanitize/quote identifiers through `shared/utils/ch_identifiers.py`.
- Source/table/column names containing spaces, unicode, SQL metacharacters, or leading digits may be normalized.
- Operational impact:
  - Silver/loader table and column creation can rename unsafe identifiers.
  - Mapping is logged during creation (`original -> safe`) and retained in creator/listener runtime mappings.

### Lineage Query
- Metadata service:
  - `GET /lineage/{row_id}/`

### Quality Trends
- Metadata service:
  - `GET /quality/trends/`

## Backups and Retention

ClickHouse:
- Quality metrics and quarantine tables should be included in backups.
- Partitioning is used for time-based retention.

SurrealDB:
- Back up metadata and lineage graph.

## On-Call Checklist

1. Check service health endpoints.
2. Check Kafka consumer lag.
3. Inspect Prometheus metrics for error rate and latency.
4. Review ClickHouse availability and disk usage.
5. Inspect quarantine counts if transform errors spike.
