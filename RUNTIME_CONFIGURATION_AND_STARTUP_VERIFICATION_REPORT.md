# Runtime Configuration and Startup Verification Report

Date: 2026-07-06

## 1. Executive Summary

The Docker Compose runtime configuration was audited, repaired, rebuilt, and verified with `.env.microservices` as the intended source of truth.

Final startup status: **Passed with external/manual limitations**.

- `docker compose --env-file .env.microservices config --quiet` passes.
- `docker compose --env-file .env.microservices up --build -d` is the standard startup command.
- A full recreate was also run once with `--force-recreate` to prove the rotated local credentials are picked up by containers.
- All 24 Compose services are running.
- Docker health-gated services are healthy.
- `voice_reports.0012_add_visualization_spec` is applied.
- Required pytest target passed: `75 passed, 3 warnings`.
- No Docker volumes, databases, uploaded files, migrations, or unrelated repository changes were deleted.
- No Git commit was created.

Remaining limitations are documented in section 19. The main runtime blocker is that Metabase is unavailable from the local stack, so health endpoints that include Metabase return `503` even though their containers are running and healthy.

## 2. Initial Failure Analysis

The immediate failure was:

```text
error while interpolating services.etl-transformer.environment.SURREAL_USER:
required variable SURREAL_USER is missing a value:
SURREAL_USER must be set
```

This occurred during Compose interpolation, before containers started. Service-level `env_file` entries do not satisfy `${VAR:?message}` expressions while Compose parses `docker-compose.yml`. The command must explicitly load `.env.microservices`:

```powershell
docker compose --env-file .env.microservices config --quiet
docker compose --env-file .env.microservices up --build -d
```

Baseline checks also showed a dirty worktree and `.env.microservices` is still tracked by Git even though it appears in `.gitignore`.

## 3. Root Cause of SURREAL_USER Failure

Root cause: `SURREAL_USER` and `SURREAL_PASS` were required Compose interpolation variables used by both the `surrealdb` command and ETL services, but they were not available to Compose parsing unless `.env.microservices` was loaded with `--env-file`.

Fixes applied:

- Ensured `.env.microservices` contains `SURREAL_USER=********` and `SURREAL_PASS=********`.
- Ensured `docker-compose.yml` consistently uses `SURREAL_USER` and `SURREAL_PASS`.
- Ensured `etl-final/docker-compose.yml` also uses the same required variable names.
- Added startup/verification scripts that require `.env.microservices` and run Compose with `--env-file`.
- Documented the standard startup command in `README.md`.

## 4. Environment Variable Inventory

Required Compose interpolation variables:

| Variable | Classification | Status |
| --- | --- | --- |
| `CLICKHOUSE_USER` | Local infrastructure credential | Present |
| `CLICKHOUSE_PASSWORD` | Local infrastructure secret | Present, rotated locally |
| `SURREAL_USER` | Local infrastructure credential | Present |
| `SURREAL_PASS` | Local infrastructure secret | Present, generated locally |

Optional Compose interpolation variables with defaults:

`AI_SERVICE_URL`, `AUTH_SERVICE_URL`, `CLICKHOUSE_DATABASE`, `ETL_SERVICE_URL`, `GATEWAY_RATE_LIMIT_REQUESTS`, `GATEWAY_RATE_LIMIT_WINDOW_SECONDS`, `GATEWAY_UPSTREAM_TIMEOUT_SECONDS`, `METADATA_SERVICE_URL`, `NOTIFICATION_EXPIRY_CHECK_INTERVAL_SECONDS`, `NOTIFICATION_SERVICE_URL`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `QUERY_SERVICE_URL`, `REPORT_SERVICE_URL`, `SMALL_WHISPER_CONNECT_TIMEOUT_SECONDS`, `SMALL_WHISPER_HEALTH_TIMEOUT_SECONDS`, `SMALL_WHISPER_MAX_RETRIES`, `SMALL_WHISPER_TIMEOUT_SECONDS`, `SUBSCRIPTION_SERVICE_URL`, `TRANSCRIPTION_REDIS_URL`, `VISUALIZATION_SERVICE_URL`, `VOICE_SERVICE_URL`, `WHISPER_CACHE_DIR`, `WHISPER_MODEL_NAME`, `WHISPER_TASK`, `WORKSPACE_SERVICE_URL`.

Container runtime variables in `.env.microservices`, grouped by purpose:

- Django/PostgreSQL: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DJANGO_SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`.
- Admin/email: `ADMIN_EMAIL`, `ADMIN_NAME`, `ADMIN_PASSWORD`, `DEFAULT_FROM_EMAIL`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`.
- Internal service auth: `INTERNAL_SERVICE_TOKEN`, `AI_SERVICE_INTERNAL_API_KEY`, `AI_SERVICE_REQUIRE_INTERNAL_AUTH`, `NOTIFICATION_SERVICE_API_KEY`.
- Service URLs: `AUTH_SERVICE_URL`, `WORKSPACE_SERVICE_URL`, `REPORT_SERVICE_URL`, `VOICE_SERVICE_URL`, `AI_SERVICE_URL`, `QUERY_SERVICE_URL`, `VISUALIZATION_SERVICE_URL`, `SUBSCRIPTION_SERVICE_URL`, `NOTIFICATION_SERVICE_URL`, `SMALL_WHISPER_URL`, `FRONTEND_URL`.
- ClickHouse: `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_DATABASE`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`.
- SurrealDB: `SURREAL_USER`, `SURREAL_PASS`.
- Metabase: `METABASE_URL`, `METABASE_EMBED_URL`, `METABASE_USERNAME`, `METABASE_PASSWORD`, `METABASE_SECRET_KEY`, `METABASE_DATABASE_ID`, `METABASE_AUTH_TYPE`.
- LLM/Ollama/OpenRouter: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `SQL_REVIEW_OLLAMA_URL`, `SQL_REVIEW_OLLAMA_MODEL`, `INTENT_CLASSIFIER_OLLAMA_URL`, `INTENT_CLASSIFIER_OLLAMA_MODEL`, `TEXT_PREPROCESS_OLLAMA_URL`, `TEXT_PREPROCESS_MODEL`, `PREPROCESS_HIGH_OLLAMA_URL`, `PREPROCESS_HIGH_OLLAMA_MODEL`, `INTENT_EXTRACTION_OLLAMA_URL`, `INTENT_EXTRACTION_OLLAMA_MODEL`.
- Voice/Whisper/TimesFM: `WHISPER_MODEL_NAME`, `WHISPER_CACHE_DIR`, `WHISPER_TASK`, `TRANSCRIPTION_REDIS_URL`, `TIMESFM_*`.
- Subscription/reset limits: `FREE_TIER_VOICE_REQUEST_LIMIT`, `PASSWORD_RESET_CODE_EXPIRY_MINUTES`, `PASSWORD_RESET_MAX_ATTEMPTS`, `SUBSCRIPTION_EXPIRY_WARNING_DAYS`, `NOTIFICATION_EXPIRY_CHECK_INTERVAL_SECONDS`.

Deprecated or not used by the active Compose file:

`SURREALDB_USER`, `SURREALDB_PASS`, `SURREALDB_ROOT_USER`, `SURREALDB_ROOT_PASSWORD`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `REDIS_PASSWORD`, `METABASE_DB_USER`, `METABASE_DB_PASS`, `METABASE_DB_DBNAME`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`.

## 5. Compose Interpolation Variables vs Container Runtime Variables

Compose interpolation happens before containers exist. Variables in this form must be loaded by the Compose CLI:

```yaml
${SURREAL_USER:?SURREAL_USER must be set}
```

Service `env_file` entries are container runtime inputs. They are passed into containers after the Compose file has already been parsed.

Therefore the supported flow is:

```powershell
docker compose --env-file .env.microservices config --quiet
docker compose --env-file .env.microservices up --build -d
```

The repository now includes helper scripts that enforce this distinction and mask secret output.

## 6. `.env.microservices` Validation Results

Status: **Passed with one external manual item**.

- Required Compose variables are present and non-empty.
- Required Compose variables are not placeholder/sample values.
- Removed sample local credentials were replaced or rotated without printing values.
- `EMAIL_HOST_PASSWORD` remains empty. This is an external SMTP credential and does not block startup.
- `.env.microservices` is listed in `.gitignore`, but it is still tracked by Git and must be manually untracked after secret rotation.

Validation command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-runtime-config.ps1
```

Result:

```text
Runtime configuration validation completed without printing secret values.
```

## 7. Variables Added, Corrected, or Deprecated

Added or corrected in `.env.microservices`:

- `SURREAL_USER=********`
- `SURREAL_PASS=********`
- `INTERNAL_SERVICE_TOKEN=********`
- `DB_PASSWORD=********`
- `CLICKHOUSE_PASSWORD=********`
- `DJANGO_SECRET_KEY=********`

Corrected in examples/docs:

- `.env.microservices.example` now uses explicit `CHANGE_ME_*` placeholders for secret-like values.
- `README.md` now documents `--env-file .env.microservices`.
- Startup helper scripts now validate required variables and mask values.

Corrected in Compose:

- Root `docker-compose.yml` uses root build context for `query-service` so `bi_platform_shared` is available in the image.
- `etl-final/docker-compose.yml` no longer embeds hardcoded ETL/Surreal sample credentials.
- `report-service` now exposes its existing health proxy at `/voice-reports/health/`.

Deprecated or not active:

- `SURREALDB_*` variants are not used by the current Compose files.
- `POSTGRES_*` variants are not used by the current Django services; the current settings use `DB_*`.

## 8. Secret-Safety and Rotation Notes

No secret values are included in this report.

Local placeholders/sample credentials rotated or generated:

- `DB_PASSWORD`
- `CLICKHOUSE_PASSWORD`
- `DJANGO_SECRET_KEY`
- `SURREAL_PASS`
- `INTERNAL_SERVICE_TOKEN`

External provider credentials preserved or left as manual setup:

- `OPENROUTER_API_KEY`
- `EMAIL_HOST_PASSWORD`
- Metabase credentials: `METABASE_USERNAME`, `METABASE_PASSWORD`, `METABASE_SECRET_KEY`

Manual rotation candidates because `.env.microservices` is tracked and history may contain secret material:

`DB_PASSWORD`, `DJANGO_SECRET_KEY`, `ADMIN_PASSWORD`, `CLICKHOUSE_PASSWORD`, `SURREAL_PASS`, `METABASE_PASSWORD`, `METABASE_SECRET_KEY`, `INTERNAL_SERVICE_TOKEN`, `NOTIFICATION_SERVICE_API_KEY`, `AI_SERVICE_INTERNAL_API_KEY`, `OPENROUTER_API_KEY`, `EMAIL_HOST_PASSWORD`.

Required manual Git hygiene:

```powershell
git rm --cached .env.microservices
```

This was **not** run because it changes index tracking and was not explicitly requested as a Git operation.

## 9. Docker Compose Validation Results

Passed:

```powershell
docker compose --env-file .env.microservices config --quiet
docker compose --env-file .env.microservices config
docker compose --env-file .env.microservices config --services
```

Rendered config verification:

- No unresolved `${...}` interpolation remained.
- 24 services were rendered.
- Root Compose config passed.
- `etl-final/docker-compose.yml` config passed; Compose warned that its `version` field is obsolete.

Non-blocking warning observed in sandboxed validation:

```text
WARNING: Error loading config file: open C:\Users\massa\.docker\config.json: Access is denied.
```

This warning did not block config rendering or startup.

## 10. Startup Commands Used

Primary safe startup command:

```powershell
docker compose --env-file .env.microservices up --build -d
```

One-time recreate after local credential rotation:

```powershell
docker compose --env-file .env.microservices up --build -d --force-recreate
```

Targeted rebuilds were also used during repair:

```powershell
docker compose --env-file .env.microservices up --build -d report-service
```

No destructive Docker commands were run. Specifically, no `down -v`, `volume rm`, `system prune`, `container prune`, or image prune commands were run.

## 11. Service Status Table

Final `docker compose --env-file .env.microservices ps` result:

| Service | Container status | Docker health | Port(s) | Notes |
| --- | --- | --- | --- | --- |
| `api-gateway` | Up | No healthcheck | `8000` | `/health/` returns 200 |
| `auth-service` | Up | Healthy | `8001` | TCP healthcheck healthy |
| `workspace-service` | Up | Healthy | `8002` | TCP healthcheck healthy |
| `report-service` | Up | Healthy | `8003` | Container healthy; app health depends on Metabase |
| `voice-service` | Up | Healthy | `8004` | Container healthy; app health depends on Metabase |
| `ai-service` | Up | Healthy | `8005` | `/health/` returns 200 |
| `query-service` | Up | Healthy | `8006` | Query and database health return 200 |
| `visualization-service` | Up | Healthy | `8007` | Container healthy; app health depends on Metabase |
| `subscription-service` | Up | Healthy | host `8009` to container `8008` | `/subscription/health/` returns 200 |
| `notification-service` | Up | Healthy | `8010` | `/notification/health/` returns 200 |
| `notification-expiry-worker` | Up | No healthcheck | internal `8010` | Worker running |
| `redis` | Up | Healthy | `6379` | `PING` returns `PONG` |
| `clickhouse` | Up | No healthcheck | `8123`, `9000` | `SELECT 1` passed |
| `surrealdb` | Up | No healthcheck | host `8008` to container `8000` | `/health`, `/status`, `/version` passed |
| `kafka` | Up | No healthcheck | `9092` | Topic listing passed |
| `zookeeper` | Up | No healthcheck | `2181` | Running |
| `clamav` | Up | Healthy | `3310` | Healthy after startup |
| `etl-connector` | Up | No healthcheck | `8101` | Running |
| `etl-detector` | Up | No healthcheck | `8102` | Running |
| `etl-extractor` | Up | No healthcheck | `8103` | Running |
| `etl-transformer` | Up | No healthcheck | `8104` | Kafka and SurrealDB smoke passed |
| `etl-loader` | Up | No healthcheck | `8105` | ClickHouse/Kafka logs verified |
| `etl-metadata` | Up | No healthcheck | `8106` | Running |
| `kafka-ui` | Up | No healthcheck | `8081` | Auth disabled warning in logs |

## 12. Health Check Results

HTTP health endpoints:

| Check | URL | Result | Status |
| --- | --- | --- | --- |
| API Gateway | `http://127.0.0.1:8000/health/` | Passed | 200 |
| AI Service | `http://127.0.0.1:8005/health/` | Passed | 200 |
| Query Service | `http://127.0.0.1:8006/query/health/` | Passed | 200 |
| Query Database | `http://127.0.0.1:8006/database/health/` | Passed | 200 |
| Report Service | `http://127.0.0.1:8003/voice-reports/health/` | Failed external dependency | 503 |
| Voice Service | `http://127.0.0.1:8004/voice-reports/health/` | Failed external dependency | 503 |
| Visualization Service | `http://127.0.0.1:8007/visualization/health/` | Failed external dependency | 503 |
| Subscription Service | `http://127.0.0.1:8009/subscription/health/` | Passed | 200 |
| Notification Service | `http://127.0.0.1:8010/notification/health/` | Passed | 200 |

The 503s are caused by Metabase being unavailable:

- Voice/report health showed `small_whisper=true`, `clickhouse=true`, `metabase=false`.
- Visualization health returned `metabase_unavailable`.

Docker health checks:

- Healthy: `auth-service`, `workspace-service`, `report-service`, `voice-service`, `ai-service`, `query-service`, `visualization-service`, `subscription-service`, `notification-service`, `redis`, `clamav`.
- No Docker healthcheck defined: `api-gateway`, `notification-expiry-worker`, `clickhouse`, `surrealdb`, `kafka`, `zookeeper`, ETL services, `kafka-ui`.

## 13. Internal Connectivity Results

| Connectivity check | Method | Result |
| --- | --- | --- |
| Django services to PostgreSQL | Services started, healthchecks passed, migrations ran | Passed |
| Query/ETL to ClickHouse | `SELECT 1` via `clickhouse-client` with env credentials | Passed |
| Redis | `redis-cli ping` | Passed |
| Kafka/Zookeeper | `kafka-topics --list`; ETL logs show topic verification and consumer joins | Passed |
| ETL transformer to SurrealDB | `SurrealClient().query("RETURN true;")` from `etl-transformer` | Passed |
| SurrealDB HTTP | `/health`, `/status`, `/version` | Passed |
| AI service to Ollama | `GET http://host.docker.internal:11434/api/tags` from `ai-service` | Passed, 200 |
| Voice to AI/ClickHouse | Voice health body showed Whisper and ClickHouse true | Passed |
| Voice/Report/Visualization to Metabase | Health endpoints | Failed, Metabase unavailable |
| ClamAV | Docker healthcheck | Passed |

## 14. Django Migration Results

Before repair:

```text
voice_reports.0012_add_visualization_spec: not applied
```

Command run:

```powershell
docker compose --env-file .env.microservices exec -T voice-service python manage.py migrate voice_reports
```

Result:

```text
Applying voice_reports.0012_add_visualization_spec... OK
```

Final verification:

```text
[X] 0012_add_visualization_spec
```

Log warning to address separately:

- `notification-expiry-worker` reported model changes in app `notification` that are not reflected in a migration. This did not block startup, but it should be reviewed before release.

## 15. Security Runtime Verification

Runtime settings were checked inside these Django containers:

`api-gateway`, `auth-service`, `workspace-service`, `report-service`, `voice-service`, `ai-service`, `query-service`, `visualization-service`, `subscription-service`, `notification-service`.

Results:

- `DEBUG=False` in all checked Django services.
- `ALLOWED_HOSTS` did not contain `*` in all checked Django services.
- `CORS_ALLOW_ALL_ORIGINS=False` for services using CORS settings.
- `CORS_ALLOW_CREDENTIALS=True` where configured.
- `CORS_ALLOWED_ORIGINS_COUNT=2` for the services using the shared CORS configuration.
- AI service does not define `CORS_ALLOW_CREDENTIALS` and reported no configured CORS origins.

Repository secret-safety:

- No active secret values were added to `docker-compose.yml`.
- `.env.microservices.example` uses placeholders only.
- `.env.microservices` is still tracked by Git and must be untracked manually after rotating real/local secrets.
- Kafka UI logs reported unrestricted auth. Treat `kafka-ui` as local-only until authentication is configured.

## 16. Smoke Test Results

Passed:

- API gateway returned 200.
- AI service returned 200.
- Query service returned 200.
- Query database health returned 200.
- Subscription service returned 200.
- Notification service returned 200.
- ClickHouse `SELECT 1` returned `1`.
- Redis returned `PONG`.
- Kafka topic listing succeeded.
- SurrealDB authenticated ETL query returned OK.
- Ollama reachability from AI service returned 200.
- SQL guard imported and accepted a safe `SELECT 1`.
- `voice_reports.0012_add_visualization_spec` is applied.
- `python -m py_compile` passed for changed Python modules.
- Required pytest target passed: `75 passed, 3 warnings`.

Failed or blocked:

- Report, voice, and visualization app health endpoints return 503 because Metabase is unavailable.
- Full end-to-end BI flow was not run because local test data and a healthy Metabase dependency were not available.

## 17. Files Modified

Files changed for this task:

- `.env.microservices`
- `.env.microservices.example`
- `docker-compose.yml`
- `etl-final/docker-compose.yml`
- `scripts/start_project.sh`
- `scripts/verify-runtime-config.ps1`
- `scripts/start-microservices.ps1`
- `README.md`
- `services/query-service/Dockerfile`
- `services/query-service/query_api/services/__init__.py`
- `services/report-service/voice_reports/report_urls.py`
- `RUNTIME_CONFIGURATION_AND_STARTUP_VERIFICATION_REPORT.md`

Notes:

- `query-service` now builds from the repository root and copies `bi_platform_shared`.
- `query_api.services.__init__` now exports the workspace ClickHouse resolution symbols required by imports.
- `report-service` now exposes its existing health proxy route.
- Existing unrelated dirty worktree changes were not reverted.

## 18. Exact Commands Run

Baseline and inspection:

```powershell
git status --short
git diff --stat
git diff --name-only
docker compose version
docker compose config --services
docker compose --env-file .env.microservices config --quiet
docker compose --env-file .env.microservices config --services
```

Configuration validation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-runtime-config.ps1
docker compose --env-file .env.microservices config
docker compose --env-file .env.microservices -f etl-final/docker-compose.yml config --quiet
```

Startup and rebuild:

```powershell
docker compose --env-file .env.microservices up --build -d
docker compose --env-file .env.microservices up --build -d report-service
docker compose --env-file .env.microservices up --build -d --force-recreate
docker compose --env-file .env.microservices ps
docker compose --env-file .env.microservices logs --tail=150
```

Credential repair commands were run with in-memory/generated values and masked output. Secret values are intentionally not reproduced here. The important operations were:

```powershell
docker compose --env-file .env.microservices exec -T -e NEW_DB_PASSWORD=******** auth-service python -c "<rotate PostgreSQL role password>"
docker compose --env-file .env.microservices up --build -d --force-recreate
```

Runtime checks:

```powershell
curl.exe -sS -i http://127.0.0.1:8004/voice-reports/health/
curl.exe -sS -i http://127.0.0.1:8007/visualization/health/
curl.exe -sS -i http://127.0.0.1:8003/voice-reports/health/
docker exec clickhouse sh -lc 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query=SELECT\ 1'
docker exec redis redis-cli ping
docker exec kafka kafka-topics --bootstrap-server localhost:9092 --list
docker compose --env-file .env.microservices exec -T etl-transformer python -c "..."
docker compose --env-file .env.microservices exec -T ai-service python -c "..."
docker inspect -f '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' ...
```

Migrations and tests:

```powershell
docker compose --env-file .env.microservices exec -T voice-service python manage.py showmigrations voice_reports
docker compose --env-file .env.microservices exec -T voice-service python manage.py migrate voice_reports
docker compose --env-file .env.microservices exec -T voice-service python manage.py showmigrations voice_reports
python -m pytest services/query-service/tests services/visualization-service/visualization_api/tests -q
python -m py_compile services/query-service/query_api/services/__init__.py services/report-service/voice_reports/report_urls.py
python -c "from query_api.services.sql_guard import SQLGuard; ..."
```

## 19. Failures, Blockers, and Manual Actions Required

| Item | Status | Required action |
| --- | --- | --- |
| Metabase unavailable | Manual Action Required | Start/configure Metabase and verify `METABASE_*` values without exposing secrets. |
| `.env.microservices` tracked by Git | Manual Action Required | Rotate secrets, then untrack with `git rm --cached .env.microservices`. |
| External SMTP password empty | Manual Action Required | Set `EMAIL_HOST_PASSWORD=********` if email delivery is required. |
| Kafka UI auth disabled | Manual Action Required | Configure Kafka UI authentication or keep it local-only and unexposed. |
| SurrealDB running in memory mode | Manual Action Required | Current command uses `memory`; switch to file/RocksDB storage if persistence is required. |
| `notification` app model changes without migration | Manual Action Required | Review and create/apply a proper migration if those model changes are intended. |
| Orphan `voice-service-worker` container warning | Manual Action Required | Review whether it is obsolete; cleanup would require explicit approval. |
| Full BI end-to-end flow | Blocked | Needs healthy Metabase and realistic local test data. |
| Docker config access warning | Non-blocking | Docker read access to `C:\Users\massa\.docker\config.json` was denied in sandboxed commands but did not block startup. |

## 20. Recommended Standard Startup Command

Validate first:

```powershell
docker compose --env-file .env.microservices config --quiet
```

Start the stack:

```powershell
docker compose --env-file .env.microservices up --build -d
```

Check status:

```powershell
docker compose --env-file .env.microservices ps
```

Optional helper:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-microservices.ps1 -Detached
```
