# P0-C health, readiness, and worker matrix

Final live snapshot: **16/16 HTTP liveness PASS**, **16/16 HTTP readiness PASS**, and **1/1 worker health PASS**. Liveness returns 200 independently of temporary downstream failure. Readiness returns 503 with the sanitized `service_not_ready` envelope when a critical dependency is unavailable.

| Service | Container | Running | `/health` | `/ready` critical checks | Result |
|---|---|---:|---:|---|---|
| API Gateway | `api-gateway` | Yes | 200 | Auth, Workspace, Report, Voice, AI, Query, Visualization, Subscription, Notification routing targets | PASS |
| Auth | `auth-service` | Yes | 200 | PostgreSQL | PASS |
| Workspace | `workspace-service` | Yes | 200 | PostgreSQL, Auth | PASS |
| Report | `report-service` | Yes | 200 | PostgreSQL, ClickHouse, ETL Metadata, Query, Metabase | PASS |
| Voice | `voice-service` | Yes | 200 | PostgreSQL, ClickHouse, Kafka, AI, Query, Visualization, Subscription, Metabase | PASS |
| AI | `ai-service` | Yes | 200 | PostgreSQL, ClickHouse, Redis | PASS |
| Query | `query-service` | Yes | 200 | PostgreSQL, ClickHouse, Kafka, ETL Connector/Metadata, Subscription | PASS |
| Visualization | `visualization-service` | Yes | 200 | PostgreSQL, Query, Report, Metabase | PASS |
| Subscription | `subscription-service` | Yes | 200 | PostgreSQL, Workspace | PASS |
| Notification | `notification-service` | Yes | 200 | PostgreSQL, Voice | PASS |
| ETL Connector | `etl-connector` | Yes | 200 | Kafka, SurrealDB, ClickHouse, ClamAV | PASS |
| ETL Detector | `etl-detector` | Yes | 200 | Kafka, SurrealDB, ClickHouse | PASS |
| ETL Extractor | `etl-extractor` | Yes | 200 | Kafka, SurrealDB, ClickHouse | PASS |
| ETL Transformer | `etl-transformer` | Yes | 200 | Kafka, SurrealDB, ClickHouse | PASS |
| ETL Loader | `etl-loader` | Yes | 200 | Kafka, SurrealDB, ClickHouse | PASS |
| ETL Metadata | `etl-metadata` | Yes | 200 | Kafka, SurrealDB, ClickHouse | PASS |
| Notification expiry worker | `notification-expiry-worker` | Yes | n/a | Heartbeat file newer than 90 seconds | PASS |

All Compose application healthchecks call HTTP readiness, not a TCP-open-only probe. Checks use a 1.5-second default dependency timeout, capped at 10 seconds, and a five-second container probe timeout. Infrastructure has service-appropriate checks (`SELECT 1`, `PING`, Kafka topic list, Surreal `is-ready`, Metabase API health, ClamAV check).

## Worker monitoring

The expiry worker refreshes `/tmp/notification-expiry-heartbeat`; Docker marks it unhealthy when the timestamp is older than 90 seconds or the process cannot update it. PostgreSQL/notification behavior is exercised by the loop, while Docker/supervisor state detects process exit. No public worker control API was added.

## Dependency outage and recovery evidence

Seven safe live stop/start scenarios passed: Redis, SurrealDB, Metabase, Query Service, Workspace Service, Kafka, and ClickHouse. In each case liveness stayed 200, readiness became 503 within the bounded assertion, the body contained the standard error envelope without password/secret/traceback text, and readiness recovered to 200 after restart. Result: **7 passed, 0 failed**.

PostgreSQL failure semantics are covered by the deterministic readiness unit test rather than stopping the shared retained database. AI-provider failure is covered at the provider boundary; default tests and readiness never call paid inference. Persistent volumes were not deleted or corrupted.

The stopped `voice-service-worker` is not in current Compose, does not auto-start, cannot process live work, and is excluded from all counts: **HISTORICAL ORPHAN — NON-ACTIVE**.
