# Service communication matrix

HTTP transport to a database is still direct database access, not an owner-service API. Worker processes within one declared owner are not independent microservices. Configured dependencies are separated from observed source calls.

| Caller | Target | Current method | Endpoint/resource | Target/action |
| --- | --- | --- | --- | --- |
| frontend | gateway | HTTP bearer JWT | all frontend/src/api/endpoints.js paths | KEEP; add TLS, timeout and refresh coordination |
| gateway | auth/workspace/report/voice/query/visualization/subscription/notification/AI | HTTP routing | services/api-gateway/gateway/routing.py | KEEP; validate identity and sanitize trust headers |
| auth | workspace | HTTP shared-key | /internal/workspaces/* and invitation/member APIs (users/services/workspace_client.py) | VERSION /internal/v1; idempotent workflow |
| workspace | auth | HTTP shared-key | workspace/services/auth_client.py internal user APIs | KEEP; bulk user snapshots, no DB join |
| auth/workspace/subscription/voice | notification | HTTP shared-key | /notification/events/ | MOVE /internal/v1/events; durable delivery/idempotency |
| subscription | workspace/auth | HTTP bearer forwarding | /workspace/{id}/; /admin/workspaces/; /admin/users/ | replace administrative list fan-out with narrow internal APIs |
| report | voice | HTTP bearer forwarding | /voice-reports/* | REVERSE ownership: voice calls report |
| voice | workspace | HTTP bearer forwarding | /workspace/{id}/; /workspace/members/; /workspace/ | FIX fail-closed membership result |
| voice | AI | HTTP shared-key | small_whisper_client.py transcription/intent; forecasting_bridge.py | KEEP; bounded async job contract |
| voice | query | HTTP bearer forwarding | /query/* validation/execution and dataset binding | KEEP; authorized dataset and query IDs |
| voice | visualization | HTTP bearer forwarding | /visualization/question/create/ and question/dashboard embed-url endpoints | KEEP; use authorized query-definition IDs |
| voice | subscription | HTTP bearer | subscription_client.py limits API | KEEP; atomic usage reservation/idempotency |
| voice | Metabase | HTTP session/embedding | voice_reports/services/metabase_service.py and views fallback | REMOVE; visualization owns integration |
| visualization | Metabase | HTTP session/signed embeds | /api/card; /api/dashboard; /api/session; /embed/* | KEEP; scoped read-only source projection and ownership registry |
| query | ETL connector | HTTP multipart | /api/upload/ | KEEP as ingestion HTTP; enforce identity/tenant |
| AI | Ollama/OpenRouter | HTTP model inference | configured /api/generate and provider completion APIs | KEEP external inference; cost/egress controls |
| visualization | Ollama | HTTP | chart_type_selector.py | KEEP optional; deterministic fallback |
| auth | SMTP | native fallback | users/utils.py | REMOVE fallback after notification delivery contract |
| notification | SMTP | native infrastructure | EMAIL_HOST | KEEP owned infrastructure; delivery retry/idempotency |
| nine core Django configurations | PostgreSQL | native shared credentials | bi_voice_agent | SPLIT service DBs; remove proxy database dependencies |
| notification | auth/workspace/subscription tables | direct ORM joins | users; workspaces; workspace_members; subscription_plans; workspace_subscriptions | REPLACE WITH HTTP owner APIs |
| query | ClickHouse | native HTTP SQL | dataset schemas/data and execution | KEEP only owner access; separate roles |
| AI | ClickHouse | native SQL/schema reads | llm_app/schema_provider.py; preprocessing_high/value_index.py | REPLACE WITH HTTP query schema/value API |
| ETL extractor/transformer/loader | ClickHouse | native shared writes | bronze; deduplication; checkpoints; schema_contracts; quality/quarantine; final tables | split staging owner from serving; HTTP publish batches |
| ETL metadata | ClickHouse | native reads/writes through helpers | quality_metrics and lineage helpers | REPLACE WITH HTTP owner queries/projections |
| Metabase | BI source databases | native source protocol | H2 metadata confirms Sample Database (h2) and ClickHouse source; physical grants/connectivity NOT VERIFIED | EXCEPTION only read-only dedicated BI projection; no operational service DB access |
| ETL stages | SurrealDB | HTTP database protocol | /sql namespace bi_etl database etl_logs | Still direct DB coupling despite HTTP transport; metadata service alone owns repository |
| connector | extractor | shared filesystem | uploaded-files:/app/uploaded_files plus path in event | REMOVE inter-service sharing; ingestion-owner private file store |
| connector | detector/extractor | Kafka | connection_topic / schema_topic / aliases | REPLACE WITH HTTP if separate; in-process pipeline after consolidation |
| extractor | transformer | Kafka | extracted_rows_topic / raw_data | REPLACE WITH HTTP or owner-local pipeline |
| transformer | loader | Kafka | clean_rows_topic / load_rows_topic / transformed_data / load_requests | REPLACE WITH HTTP or owner-local pipeline |
| ETL stages | metadata | Kafka | metadata_topic / metadata_updates | REPLACE WITH HTTP batched metadata endpoint |
| ETL stages | error handling | Kafka | errors / quarantine / *_dlq | REMOVE cross-service broker; owner-local durable failed-job records and replay API |
| voice | unidentified event consumers | Kafka | report.voice.received; report.text.received; report.intent.generated; report.sql.generated; report.query.executed; report.visualization.ready | UNDECIDED; no in-repo consumer proved. Remove if redundant telemetry; HTTP if business consumer exists |
| AI process/worker | Redis | native owner-local queue/locks/cache | whisper:transcription:* and optional value-index keys | KEEP private to AI; not a cross-service business bus |
| ETL stages | shared persistence code | direct imports | etl-final/shared/models and shared/utils repositories | MOVE into domain owner; keep generic transport packages |

Kafka policy: REPLACE the five grouped inter-service ETL workflow paths (connection/schema, extracted rows, clean/load rows, metadata, error/DLQ). The two row topics and aliases are alternatives/branches, not necessarily independent consumers. Voice report.* events are UNDECIDED pending consumer discovery; no business consumer is proved. No Kafka usage is approved for retention merely because the payload is called analytics. Redis transcription coordination is KEEP within AI ownership; no Redis pub/sub cross-service business path was found.
