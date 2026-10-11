# Service inventory

24 unified Compose entries: 16 application services, one same-domain notification worker, seven infrastructure entries. React/Vite frontend and host PostgreSQL/Ollama plus standalone Metabase are additional processes. The legacy ETL manifest declares 12 entries, largely alternate deployments of the same code; do not double count them as separate domains.

| Service | Technology | Responsibility | Host:container port | Data | Runtime dependencies | Compose start dependencies | Health check |
| --- | --- | --- | --- | --- | --- | --- | --- |
| api-gateway | Django/requests | route proxy and coarse throttling | 8000:8000 | shared PostgreSQL configured | all nine upstream APIs | auth-service,workspace-service,report-service,voice-service,ai-service,query-service,visualization-service,subscription-service,notification-service | TCP only |
| auth-service | Django/DRF/SimpleJWT | accounts, tokens, profile, system-admin principal | 8001:8001 | bi_voice_agent: users/reset/token state | workspace HTTP; notification HTTP; SMTP fallback |  | TCP only |
| workspace-service | Django/DRF | workspaces, memberships, invitations | 8002:8002 | bi_voice_agent: workspaces/members/invitations | auth HTTP; notification HTTP | auth-service | TCP only |
| report-service | Django/DRF | report/dashboard proxy to voice; legacy inactive models | 8003:8003 | shared PostgreSQL configured; no active report ORM app | voice HTTP | clickhouse,etl-metadata,query-service | TCP only |
| voice-service | Django/DRF | voice/text orchestration, reports, pages, jobs | 8004:8004 | bi_voice_agent: reports/pages/jobs; container media | workspace, AI, query, visualization, subscription, notification; Kafka; Metabase fallback | ai-service,query-service,visualization-service,subscription-service,clickhouse,kafka | TCP only |
| ai-service | Django/Dagster/Whisper/TimesFM | transcription, intent, semantic SQL, forecast | 8005:8005 | SQLite configured; Redis; ClickHouse reads | Ollama/OpenRouter; model cache; Redis | clickhouse,redis | TCP only |
| redis | Redis 7 Alpine | AI transcription queue/locks/results and optional value-index cache | 6379:6379 | redis_data AOF/RDB | AI owner |  | configured; runtime verification required |
| query-service | Django/DRF/sqlglot | dataset metadata, upload forwarding, SQL validation/execution | 8006:8006 | bi_voice_agent: manager_databases; ClickHouse | ETL connector HTTP; ClickHouse; subscription | clickhouse,kafka,etl-connector,etl-metadata,subscription-service | TCP only |
| visualization-service | Django/DRF | chart choice, Metabase cards/dashboards/embeds | 8007:8007 | shared PostgreSQL configured; external Metabase metadata | Metabase HTTP; Ollama | report-service | TCP only |
| subscription-service | Django/DRF | plans, entitlements, free usage, payment records | 8009:8008 | bi_voice_agent: subscription tables | workspace/auth HTTP; notification HTTP | workspace-service | TCP only |
| notification-service | Django/DRF/SMTP | notification dispatch and expiry warning processing | 8010:8010 | bi_voice_agent: dispatch log plus foreign table reads | SMTP; cross-domain PostgreSQL reads | voice-service | TCP only |
| notification-expiry-worker | Django management-command loop | scheduled expiry warnings | internal | same notification persistence boundary | SMTP; same-domain notification code | notification-service | NONE |
| zookeeper | Confluent ZooKeeper 7.5.0 | broker metadata coordination | 2181:2181 | anonymous data/log volumes | Kafka |  | configured; runtime verification required |
| kafka | Confluent Kafka 7.5.0 | ETL business events and voice telemetry | 9092:9092 | anonymous broker data volume | ZooKeeper; ETL and voice | zookeeper | configured; runtime verification required |
| kafka-ui | Kafka UI floating image | broker administration UI | 8081:8080 | no application volume declared | Kafka | kafka | configured; runtime verification required |
| surrealdb | SurrealDB floating image | ETL logs and lineage graph | 8008:8000 | configured memory; /data mount ineffective for memory engine | ETL clients |  | configured; runtime verification required |
| clickhouse | ClickHouse floating image | analytical and ETL operational storage | 8123:8123, 9000:9000 | clickhouse_data; clickhouse_logs | many shared clients |  | configured; runtime verification required |
| clamav | ClamAV floating image | upload malware scanning | 3310:3310 | clamav_data signatures | signature update endpoint |  | configured; runtime verification required |
| etl-connector | Django/DRF | uploads, DB connection tests, source triggers | 8101:8000 | SQLite; SurrealDB; shared uploaded-files; schema store | ClamAV native; Kafka; ClickHouse/SurrealDB | kafka,surrealdb,clickhouse,clamav | TCP only |
| etl-detector | Django/Kafka worker | source schema detection | 8102:8000 | SQLite; shared metadata store | source PostgreSQL/MySQL; Kafka; SurrealDB | kafka,surrealdb,clickhouse | TCP only |
| etl-extractor | Django/Kafka worker | extract rows and write bronze/checkpoints | 8103:8000 | SQLite; ClickHouse; shared uploaded-files | source DBs; Kafka; SurrealDB | kafka,surrealdb,clickhouse | TCP only |
| etl-transformer | Django/Kafka worker | cleaning/rules/schema/quarantine | 8104:8000 | SQLite; ClickHouse schema and quarantine state | Kafka; SurrealDB | kafka,surrealdb,clickhouse | TCP only |
| etl-loader | Django/Kafka worker | schema evolution and final dataset writes | 8105:8000 | SQLite; ClickHouse | Kafka; SurrealDB | kafka,clickhouse,surrealdb | TCP only |
| etl-metadata | Django/DRF/Kafka worker | lineage/logs/quality APIs | 8106:8000 | SQLite; SurrealDB bi_etl/etl_logs; ClickHouse quality | Kafka; ClickHouse | kafka,surrealdb,clickhouse | TCP only |

Runtime snapshot: 32 existing containers, all stopped at initial inspection; 555 Docker volumes. See runtime_inventory.json for all names, mounts, bindings and context. Declared health is not a health PASS.
