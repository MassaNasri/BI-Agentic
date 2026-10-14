# Repository inventory

## Baseline

- Working repository: `C:\Users\massa\Desktop\senior 1\BI-Voice-Agent`
- Branch/revision: `main`, `0b9ee0b`
- Pre-existing status: `? services/ai-service/forecasting/timesfm` (dirty submodule content). It was not modified.
- Latest work is P1-R snapshot/multi-database remediation. CDC is explicitly out of scope in those artifacts.

## File counts

Counts use `rg --files -uuu` for the physical tree and `git ls-files` for tracked classification. Dependency, build, database, cache, and submodule contents are counted but not represented as first-party source.

| Class | Count | Notes |
|---|---:|---|
| Physical files present | 21,373 | Includes `frontend/node_modules`, `dist`, caches, database data, and TimesFM working tree |
| Git-tracked paths | 5,639 | Includes a very large ClickHouse data snapshot |
| Tracked source/config files | 884 | Code/config extensions plus Dockerfiles |
| Python | 734 | Includes tests and scripts |
| JavaScript/JSX/TypeScript | 64 | Mostly React JSX; no meaningful TypeScript application layer |
| HTML/CSS/SCSS | 2 | JSX/Tailwind carries most UI markup/styling |
| Shell/PowerShell/batch | 28 | Startup, test, migration, and operations scripts |
| YAML/YML | 28 | Compose, CI, ETL/K8s/monitoring definitions |
| Dockerfiles | 16 | One per first-party application service |
| Django migrations | 31 | Eight PostgreSQL service configurations plus sparse SQLite apps |
| Test files | 140 | 103 ETL, 33 services, 3 frontend, 1 shared-root |
| Documentation files | 119 | Markdown and related tracked documents |
| Mechanically generated artifacts (narrow extension/path rule) | 1,544 | Understates the committed ClickHouse snapshot because many files have SQL/metadata extensions |
| Dataset/fixture/sample-related paths | 6 | Does not count database engine data as a dataset |
| Model/cache-related tracked paths | 2 | TimesFM itself is a submodule; no weights are tracked in the parent |

### Material repository-hygiene findings

- `etl-final/etl-infra/clickhouse/data/`: **4,531 tracked paths**. These are engine runtime artifacts, not maintainable source.
- `etl-final/etl-infra/surreal_data/`: 22 tracked paths.
- Compiled Python: 18 tracked `.pyc` files.
- Historical material: 36 `docs/audit`, 41 `docs/remediation`, 35 `etl-final/Test-File` paths, plus a root backup artifact.
- `frontend/node_modules` and `frontend/dist` are present locally but not tracked. The build output is correctly excluded.
- No parent-repository model weights were found. TimesFM is a Git submodule and was already dirty.

## First-party size by meaningful area

The following line counts exclude dependency/build/cache/database-data directories and the TimesFM submodule; they include tests and configuration where relevant.

| Area | Files | Approx. lines | Purpose |
|---|---:|---:|---|
| `etl-final` | 349 | 52,894 | Connectors, Kafka pipeline, schema/quality/lineage utilities, ETL apps, tests |
| `services/ai-service` | 124 | 27,737 | Whisper, intent/semantic pipeline, SQL compiler/review, Dagster assets, forecast API |
| `frontend` | 67 | 12,592 | React/Vite product UI |
| `services/voice-service` | 57 | 11,545 | Interactive workflow, report owner, dashboards, AI/query/viz orchestration |
| `services/query-service` | 52 | 5,176 | Dataset metadata, ingestion facade, SQL authorization/execution |
| `services/visualization-service` | 28 | 4,717 | Query-definition validation, chart selection, Metabase ownership |
| `bi_platform_shared` | 25 | 3,333 | HTTP, health, SQL, contracts, semantic priority utilities |
| `services/report-service` | 29 | 3,083 | Thin runtime proxy plus unwired duplicate legacy implementation |
| `services/auth-service` | 28 | 3,014 | Users, JWT, password reset, admin APIs |
| `scripts` | 33 | 2,813 | Test/start/migration/audit legacy utilities |
| `services/workspace-service` | 29 | 2,230 | Workspaces, members, invitations |
| `services/notification-service` | 23 | 1,353 | Email dispatch log, domain projections, expiry warnings |
| `services/subscription-service` | 20 | 1,106 | Plans, simulated payments, voice quota |
| `services/api-gateway` | 13 | 395 | Static routing, presence auth, proxy, in-process rate limit |

## Runtime applications and entrypoints

The root Compose file resolves to **27 services**:

- Ten business HTTP services: gateway, auth, workspace, report, voice, AI, query, visualization, subscription, notification.
- Six ETL applications: connector, detector, extractor, transformer, loader, metadata.
- One additional notification expiry worker process using the notification image.
- Ten infrastructure services: ClickHouse, Redis, SurrealDB init, SurrealDB, ZooKeeper, Kafka, Kafka UI, Metabase PostgreSQL, Metabase, ClamAV.

Every business/ETL HTTP service is Django. There is no FastAPI or Flask runtime. ETL listeners are launched alongside Django development servers by `start.sh`. AI defines Dagster assets/jobs but executes jobs synchronously via `execute_in_process`; there is no Dagster daemon or durable run worker.

## Directory purpose map

| Directory | Actual purpose / status |
|---|---|
| `.github/workflows` | One P0-C-named release gate covering static, selected unit/security tests, migration drift, Compose and image build |
| `bi_platform_shared` | Cross-service contracts, HTTP helper, health/readiness, SQL guard/normalization, IDs, and small semantic rules |
| `services/api-gateway` | Buffered reverse proxy with path routing and local rate-limit/auth-presence middleware |
| `services/auth-service` | Identity/JWT/password-reset source of truth |
| `services/workspace-service` | Workspace/member/invitation source of truth; stores identity IDs/snapshots |
| `services/query-service` | Current dataset/source metadata owner and authoritative SQL HTTP boundary |
| `services/voice-service` | Current report/dashboard owner and interactive workflow orchestrator |
| `services/report-service` | Runtime report proxy only; duplicate models/services are not installed/wired |
| `services/visualization-service` | Metabase objects and visualization ownership |
| `services/subscription-service` | Plan and coarse voice-use limits; checkout is simulated |
| `services/notification-service` | Synchronous email/event handling and periodic expiry warnings |
| `services/ai-service` | Stateless-claimed AI worker with local SQLite/Django metadata, Whisper, Dagster-in-process, LLM rules, and forecast endpoints |
| `etl-final/shared` | Connector adapters, event validators, security, Kafka, schema, quality, lineage, idempotency, ClickHouse helpers |
| `etl-final/*-service` | Six Django API/listener processes implementing the snapshot pipeline |
| `etl-final/etl-infra` | Development infrastructure configs **and accidentally tracked database runtime state** |
| `etl-final/monitoring` | Grafana/alert configuration not instantiated by root Compose |
| `etl-final/Test-File` | Legacy implementation reports, guides, validators, and test artifacts; not one canonical test tree |
| `frontend/src` | Routes, Zustand auth/theme, Axios client, database/report/dashboard/subscription/admin pages |
| `docs/audit` | Older audit evidence; useful history, not current authority |
| `docs/remediation` | Phase remediation evidence through P1-R; generally accurate about snapshot-only scope |
| `scripts` | Canonical checks plus older audit/report generators and operations helpers |
| `tests` | Root shared readiness/request-ID tests |

## Documentation versus reality

The root README says eight services and claims PostgreSQL/Metabase are external and excluded. Compose currently has ten business services plus notification worker, includes Metabase and its PostgreSQL database, and also includes Redis. README calls report-service an ordinary service but does not explain that it proxies voice-service. Remediation documents correctly state that CDC, persistent connections, scheduling, offsets, and replay are absent. Executable Compose and source take precedence.

## Inventory caveat

“Files scanned” means all paths were enumerated and classified; it does not mean third-party dependencies, compiled bytes, engine data, model code, or every repeated test fixture received manual line-by-line review. Every first-party runtime entrypoint and security/ownership-critical flow was traced, and key implementation files were deep-read.
