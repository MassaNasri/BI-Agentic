# BI Voice Agent - Unified Microservices + ETL Stack

## Full Architecture

### Microservices Layer (8 services)
1. `api-gateway`
2. `auth-service`
3. `workspace-service`
4. `report-service`
5. `voice-service`
6. `ai-service`
7. `query-service`
8. `visualization-service`

### ETL Platform (discovered from `etl-final/docker-compose.yml`)
1. `etl-connector` - file upload entrypoint (`/api/upload/`, `/api/connect-db/`) and Kafka trigger publisher.
2. `etl-detector` - Kafka-driven detector listener service.
3. `etl-extractor` - consumes connector events and emits extracted rows.
4. `etl-transformer` - consumes extracted rows and emits transformed/clean rows.
5. `etl-loader` - consumes load events and writes to ClickHouse.
6. `etl-metadata` - metadata/log/lineage API (`/api/logs/*`, `/api/lineage/*`, `/api/quality/*`) backed by SurrealDB.

### ETL Infrastructure (shared)
- `zookeeper`
- `kafka`
- `kafka-ui`
- `clickhouse`
- `surrealdb`
- `clamav`
- volumes: `uploaded-files`, `clickhouse_data`, `clickhouse_logs`, `surreal_data`, `clamav_data`

### External Services (not containerized)
- PostgreSQL (external)
- Metabase (external)

`PostgreSQL` and `Metabase` are intentionally excluded from `docker-compose.yml`.

## ETL Components Discovered
Runtime inspection of `etl-final/` found:
- Compose-defined ETL apps and infra listed above.
- Kafka listener workers are embedded inside ETL service startup scripts (`start.sh`) for extractor/transformer/loader/metadata/detector.
- No Redis service and no Celery worker/beat processes defined in ETL compose.

## Startup
From repository root:

```bash
docker compose up -d
```

This starts the full unified stack (microservices + ETL + infra) in one command.

## Data Flow
`Voice -> AI -> SQL -> ClickHouse -> Visualization`

Detailed path:
1. Client calls `api-gateway`.
2. `voice-service` sends requests to `ai-service` and `query-service`.
3. `query-service` executes validated SQL against ClickHouse.
4. `visualization-service` publishes dashboards/charts (Metabase-backed).

## ETL Flow
`Upload -> Connector -> Extractor -> Transformer -> Loader -> ClickHouse`

Detailed path:
1. `query-service` forwards uploads to `etl-connector`.
2. `etl-connector` validates/scans files, stores upload metadata, and publishes Kafka events.
3. `etl-extractor` reads source events and publishes extracted rows.
4. `etl-transformer` applies transformation rules and publishes cleaned rows.
5. `etl-loader` writes final rows to ClickHouse.
6. `etl-metadata` records lineage/quality/log streams in SurrealDB and exposes metadata APIs.
7. `etl-detector` runs additional Kafka-based detection logic.

## Integration Wiring
- `query-service -> etl-connector`: `ETL_SERVICE_URL=http://etl-connector:8000`
- `report-service -> etl-metadata`: `METADATA_SERVICE_URL=http://etl-metadata:8000`
- `voice/query/report/ai -> clickhouse`: `CLICKHOUSE_HOST=clickhouse`, `CLICKHOUSE_PORT=8123`
- ETL services -> Kafka/ClickHouse/SurrealDB/ClamAV via internal Docker DNS.
