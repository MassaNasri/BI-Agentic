# BI Voice Agent - Unified Microservices + ETL Stack

## Release planning source of truth

The **10 January 2027** release blueprint starts with [the master context](BIAVORA_PRODUCTION_READINESS_AUDIT/34_BIAVORA_MASTER_CONTEXT_FOR_FUTURE_PROMPTS.md) and [scope/roadmap](BIAVORA_PRODUCTION_READINESS_AUDIT/43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md). **Foundation-C Local Engineering: CLOSED. Foundation-C External Deployment Validation: DEFERRED_TO_PRODUCTION_READINESS. Production Readiness: NO-GO.** Next phase: Foundation-D — PostgreSQL CDC after current release CI GREEN; repaired remote verification is PENDING_PUSH_AND_RUN. See the [local closure and CI repair report](BIAVORA_PRODUCTION_READINESS_AUDIT/49_FOUNDATION_C_LOCAL_CLOSURE_AND_CI_REPAIR_REPORT.md).

## Full Architecture

### Business/API Layer (10 services)
1. `api-gateway`
2. `auth-service`
3. `workspace-service`
4. `report-service`
5. `voice-service`
6. `ai-service`
7. `query-service`
8. `visualization-service`
9. `subscription-service`
10. `notification-service`

Root Compose also defines credential-prune and notification-expiry worker processes. Domain ownership is documented separately from deployment count in the canonical ownership map.

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

### Root Compose dependencies

Application PostgreSQL remains externally configured. Root `docker-compose.yml` includes Redis, Metabase and its `metabase-db` PostgreSQL container, alongside the ETL infrastructure. The historical `etl-final/docker-compose.yml` is not the complete unified topology. Local Compose is a development/reference environment, not production certification.

## ETL Components Discovered
Runtime inspection of `etl-final/` found:
- Compose-defined ETL apps and infra listed above.
- Kafka listener workers are embedded inside ETL service startup scripts (`start.sh`) for extractor/transformer/loader/metadata/detector.
- No Redis service and no Celery worker/beat processes defined in ETL compose.

## Startup
From repository root:

```powershell
PowerShell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-microservices.ps1
```

The launcher validates the ignored local `.env`, builds the images, starts the unified stack in detached mode, and prints service status. Create `.env` once from the safe template if it does not exist:

```powershell
Copy-Item .env.example .env
```

Configure every required placeholder, then use the canonical development command:

```powershell
docker compose up --build
```

Docker Compose automatically loads `.env` before interpolating `docker-compose.yml`. Required-variable checks remain enabled, and service containers also receive the same file through `env_file`. Validate without starting containers with `docker compose config --quiet`.

The React frontend is intentionally run as a separate Vite development process:

```powershell
Set-Location .\frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`; it connects to the API gateway at `http://127.0.0.1:8000`.

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
