# Foundation-C Part 1 — Service Ownership and Integration/Data Source

> Date: 2026-10-19  
> Status: **PARTIAL**. C1/C2 code and focused migration/contract verification are complete; physical owner grants, C3, C4, and the live application path remain open. Foundation-C is **not GREEN**.

## 1. Executive Summary

Integration is now a distinct Django logical domain co-deployed with Query. A workspace-owned `DataSource` has a UUID identity, non-secret connection metadata, selected tables, and active/disabled/retired lifecycle. Query retains the legacy `Database` table as the **dataset/materialization** record and links it to the source. A source can produce multiple datasets; a new snapshot or CSV/XLSX upload no longer destroys the preceding dataset. Existing source routes and the Connector/Kafka/Extractor/Transformer/Loader data plane remain intact. The browser can select an existing source, import another dataset, select older datasets, and delete one dataset without retiring its source.

This slice does not close BIA-005, BIA-008, or BIA-014. Source secret references, transport policy, staged cutover, owner database roles, and a full live application gate are outstanding. The local Compose application was stopped; no new end-to-end ingestion claim is made.

## 2. Baseline / Git State

- Repository: `BI-Voice-Agent`; branch `main`; entry HEAD `9298d2f25425f880cb56ccdeb2036e65f83f1bcb`.
- Entry `git status --short`: only `? services/ai-service/forecasting/timesfm`; unstaged/staged diffs empty. Submodule at `d720daa6786539c2566a44464fbda1019c0a82c0` (v1.2.6-146-gd720daa), dirty before this work and untouched.
- No reset, clean, staging, commit, push, or history rewrite. Ignored local `.env` and backup artifacts were left untouched.

## 3. Documents Read

Read master context `34` first, then canonical `29`–`33`, register `20`, roadmap `25`, map `26`, Foundation-A `36`, Foundation-B `37`, five `docs/audit` architecture/ownership/communication documents, and the P1 multi-database architecture, audit, implementation report, test matrix, and results JSON. The P1 matrix distinguishes live PostgreSQL/MySQL/SQLite/ClickHouse from contract-only MariaDB/MSSQL/Oracle. Older `SERVICE_COMMUNICATION_MATRIX.md` and `MICROSERVICES_RESTRUCTURING_PLAN.md` propose removing Kafka and splitting per-service databases; newer approved v2 canonical documents `30`/`31` explicitly retain Kafka for the data/event plane and require logical ownership before physical separation. The v2 decision governs this implementation.

## 4. Canonical Issue Mapping

| Issue / MAP | Canonical finding and entry status | C1/C2 change | Closure still needed |
|---|---|---|---|
| BIA-005 / MAP-020 | Critical shared PostgreSQL role/schema ownership; open | Integration owner and Query dataset owner separated in code | Owner schemas/roles, denied cross-owner writes, reversible deployment migration and C4 proof |
| BIA-008 / MAP-021, MAP-040 | Unsafe source/credential lifecycle; open | Persistent multi-source aggregate, separate UUID, retirement and non-destructive additive ingestion | C3 versioned opaque secret refs, rotation, DirectTransport; stage/test/load/cutover/rollback; C4 |
| BIA-014 / MAP-021 | One source per manager and destructive replacement; open | Unique manager constraint removed; existing datasets retained; source can link many datasets | Replacement/cutover semantics and live verification |
| BIA-030 / MAP-042 | Public physical identifiers; open | Removed ClickHouse database/table fields from dataset serializer and deletion response | Audit remaining public routes and compatibility in later API review |
| BIA-018 | Destination DNS rebinding window; open | Existing P1 validation unchanged | C3 direct transport revalidation/security gate |
| MAP-001, MAP-005 | Registry and regression assets to keep | Registry untouched; CI now runs Integration owner tests | Continue in C3/C4 |

BIA-001/002/010 and BIA-003/006/011 remain closed from Foundations A/B; their status is not reopened by this report. BIA-009 durable jobs, BIA-017 metadata scope, and BIA-021 AI schema tools are adjacent work, not claimed closed here.

## 5. Current Ownership Matrix

“Current” describes the entry code; “now” describes this part. Public APIs route through Gateway. The old ETL `source_id` means an extraction/dataset identifier and is not the new Integration UUID.

| Object / responsibility | Entry owner / persistence / readers-writers | Public / internal / Kafka / credential access | Problem and canonical owner now |
|---|---|---|---|
| External source definition | Query `Database` in shared PostgreSQL; Query writes, frontend reads | `/database/sources/*`; no persistent source ID | Conflated with dataset. Integration `DataSource` is now the only definition writer. |
| Source credential | Browser request → Query proxy → Connector; encrypted event → Extractor memory | No public serializer; Connector encrypts, Extractor decrypts | `TRANSITIONAL_C3_DEBT`: Integration owns policy, but no managed secret reference yet. |
| Connection metadata | Request config, only engine/table copied into Query dataset | Query → Connector HTTP; no raw credential in new source JSON | Integration persists an allowlisted non-secret subset. |
| Connection test | Query public proxy; Connector registry/driver execution | HTTP control plane; no Kafka | Integration authorizes a supplied source UUID before the Connector call. |
| Schema discovery | Query public proxy; Connector registry/driver | HTTP control plane; no Kafka | Integration authorizes source scope; Connector remains execution owner. |
| Table selection | P1 `Database.source_tables` mixed source selection and destination/status | Snapshot HTTP, then Kafka selected tables | Integration owns selected logical tables; Query retains per-dataset imported table/status projection. |
| Snapshot request | Query creates dataset; Connector publishes `connection_topic` | HTTP command → Kafka event; Connector sees transient credentials | Integration source is checked, Query dataset created, separate UUID sent as `integration_source_id`. |
| Dataset record | Query `manager_databases`; Query writes/reads | `/database/`, `/database/datasets/` | Query remains dataset and binding owner; `source_id` FK is optional for files. |
| Ingestion job/status | Query dataset `ingestion_job_id`/`etl_status`; ETL metadata projection | Kafka stages/status callback → Query | Query still has P1 job/status contract; durable BIA-009 job work remains. |
| ClickHouse binding | Query `Database.clickhouse_database`, `clickhouse_table_name`, imported destinations | Query internal resolver; no physical field in new public dataset JSON | Query owns exact authorized dataset/table binding. |
| Extraction | Extractor + shared Connector registry | Kafka consumer/producer; decrypted transient source password | Data Platform. |
| Transformation | Transformer | Kafka consumer/producer; no source credential | Data Platform. |
| Loading | Loader / ClickHouse | Kafka consumer; ClickHouse write credential | Data Platform. |
| Schema/metadata result | Connector discovery; ETL metadata/SurrealDB projection; Query schema view | HTTP result and Kafka progress | Connector/metadata execute; Query exposes authorized dataset schema. |
| Analytical query | Query resolver/guard/executor | Query HTTP; read-only ClickHouse policy | Query remains sole product authority. |
| Source deletion | No separate object; old dataset delete removed warehouse data | Former `/database/` only | Integration DELETE now retires source and preserves linked datasets. |
| Dataset deletion | Query `Database` and direct ClickHouse cleanup | `/database/?dataset_id=...` | Query deletes exactly the selected dataset; direct warehouse cleanup is remaining ownership debt. |

## 6. Current Source/Dataset Architecture

Before this part, one `Database` row per manager represented file upload, source engine/table list, ingestion status, and physical ClickHouse binding. Snapshot startup called `cleanup_database` and deleted that row **before** a new Connector dispatch. P1 multi-table loads already produced distinct warehouse tables, but one dataset ID grouped them. Connector capabilities were already authoritative, and credential encryption existed only for the transient Kafka handoff.

## 7. Problems Confirmed

The manager uniqueness constraint, destructive snapshot/file replacement, source/dataset conflation, public physical binding fields, and ETL `source_id` overload were confirmed in runtime code. Shared PostgreSQL credentials and Notification unmanaged foreign-domain reads remain as BIA-005 evidence. Query still performs direct ClickHouse deletion for a dataset. AI's broad schema reader remains BIA-021; no AI source credential path was added.

## 8. Problems No Longer Present

The existing Foundations A/B already removed Voice analytical fallback, bounded Query execution, contained payment simulation, and closed public upload/secret containment. This part adds a stable source UUID, many datasets per manager/source, non-destructive snapshot/file creation, source retirement separate from dataset deletion, and public dataset JSON without physical ClickHouse identifiers. These are code/test observations, not a new live production claim.

## 9. Canonical Ownership Decisions

Workspace remains organization/membership/role authority; Integration owns source definition/lifecycle/table selection; Query owns dataset binding and analytical execution; Connector tests/discovers/queues authorized requests; Extractor/Transformer/Loader execute ingestion; metadata worker projects ingestion status. AI, Voice, Report, and Visualization are not source or credential owners. The new `integration` Django app is in the Query deployment; there is no new physical service, database instance, port, or topic.

## 10. Control Plane vs Data/Event Plane

Gateway → Query/Integration source CRUD, test/discover, snapshot submit, dataset list/read/delete are `CONTROL_PLANE` HTTP. Query → Connector internal authenticated commands are `CONTROL_PLANE`. Connector → Kafka extraction, Extractor → Transformer → Loader, and metadata/status events are `DATA_PLANE`/`EVENT_PLANE`. ETL `source_id=str(dataset_id)` is `LEGACY_COMPATIBILITY`; the new `integration_source_id` UUID is additive. Notification's foreign ORM reads and Query's direct ClickHouse DROP remain `INVALID_CROSS_DOMAIN`/ownership debt. The old audit's proposed wholesale Kafka removal was superseded by canonical v2.

## 11. Integration/Data Source Domain Placement

`services/query-service/integration/` holds the DataSource model, non-secret metadata policy, workspace scope, application service, source views, and migration. Query's `database` app retains the legacy table name as a dataset adapter. Integration and Query still share the current PostgreSQL role/schema physically; critical owner grants are deferred under BIA-005. No second source table or independent authority was introduced.

## 12. Data Source vs Dataset Semantics

Source = persistent workspace-owned connection definition/selected logical tables, identified by UUID. Dataset = an import/materialization with a numeric ID, ETL status/job, and exact ClickHouse destinations. One source can produce multiple datasets; one snapshot dataset can contain up to 20 selected tables. CSV/XLSX is a file ingestion artifact with `source_id=NULL`, not a database connection. SQLite prepare is a private temporary token; a SQLite snapshot gets a source record, but the token is not persisted and a new upload is needed to reuse it. Integration owns connection metadata; Query owns destination binding and ingestion status.

## 13. Data Source Model / Aggregate

`DataSource` stores UUID, workspace, creator, name, engine, allowlisted non-secret connection metadata, logical selected tables, state, timestamps, and a nullable legacy-dataset marker for idempotent backfill. It stores no password, ciphertext, source file path/token, or physical warehouse binding. The Connector registry remains the capability truth; this model does not assert CDC capability or certify an engine. `Database.source` is a nullable protected FK; existing dataset IDs remain unchanged.

## 14. Lifecycle

Source states are `active`, `disabled`, `retired`; retirement is a soft delete and preserves datasets. Supplied source IDs must be active for test/discover/snapshot. Dataset states remain the existing `pending`, `processing`, `completed`, `failed` P1 contract. New uploads/snapshots create new datasets; old data is not removed at submission. This is additive import, not full staged replacement/cutover/rollback; that acceptance item remains open.

## 15. Public API Boundary

Manager and JWT workspace scope gate `GET/POST /database/sources/` and `GET/PATCH/DELETE /database/sources/{uuid}/`. Existing capability/test/discovery/SQLite/snapshot routes remain. `source_id` is optional for legacy snapshot clients and required to reuse a particular source. `GET /database/datasets/` lists only authenticated workspace datasets. Existing `/database/` status/preview/schema/delete accept an optional dataset ID and default to the latest for compatibility. Dataset serializers expose logical source/dataset IDs and table selectors, omitting ClickHouse database/table names. Source mutation never accepts a password or arbitrary metadata key.

## 16. Internal ETL Contract Boundary

Query validates source ownership and engine/metadata match before dispatch. Connector still validates source destination, engine configuration, TLS, discovered table selection, and internal service identity. Snapshot HTTP now carries `integration_source_id`; Connector validates it as a UUID and adds it to the existing event. The legacy event `source_id` retains its P1 dataset-scoped meaning so Extractor/idempotency/metadata consumers do not break. No new topic or Kafka replacement was added.

## 17. Credential Ownership and C3 Transitional Debt

Integration is the logical source credential owner. Current implementation still accepts a browser-supplied password at test/discovery/snapshot time, proxies it through Query to authenticated Connector, encrypts it for the Kafka event, decrypts it in Extractor memory, and discards it. This is **TRANSITIONAL_C3_DEBT**. It lacks opaque versioned secret refs, managed storage, rotation/audit, and the direct secure transport abstraction. Public Integration and Dataset serializers exclude passwords; connection metadata is strictly allowlisted for explicit CRUD. C3 must replace the transient password handoff without turning Query analytical code into a secret manager.

## 18. Cross-Domain Persistence Changes

Query's snapshot view now calls Integration application operations for source creation, lookup, and table selection; it writes only Query's dataset row itself. No service was granted a new foreign ORM writer. The physical shared PostgreSQL role, Notification unmanaged reads, and Query direct ClickHouse dataset cleanup remain. New code does not claim BIA-005 closure.

## 19. Migrations / Backfill

`integration.0001` creates source records; `database.0006` removes manager uniqueness, adds the protected nullable source FK, and links existing workspace-owned `source_kind=database` rows. It preserves legacy dataset IDs/workspace/manager/status/destinations, copies only logical table names/schema, and skips rows with unknown workspace rather than inventing one. `legacy_dataset_id` makes reverse/reapply idempotent. A disposable PostgreSQL container ran forward → reverse → reapply and verified one stable source UUID and preserved dataset. The exact container was stopped. Local application PostgreSQL was unavailable, so these migrations were not applied to the shared live database. `makemigrations --check --dry-run` found no drift (its history check warned that the stopped external PostgreSQL host was unreachable).

## 20. Frontend Compatibility

The existing capability-driven connector form and CSV/XLSX upload remain. The management page now keeps import controls visible with an existing dataset, offers existing active sources, sends an optional source UUID/name, lists workspace datasets, scopes preview/status/delete to the selected dataset, and describes source retirement separately from dataset deletion. Password clearing after snapshot remains. No styling redesign or CDC/transport UI was added.

## 21. Security / Workspace Isolation

Integration CRUD derives workspace from the authenticated principal and allows managers only. Foreign source get/update/delete, test/discovery, and snapshot fail before Connector dispatch. Snapshot rejects mismatched source engine/non-secret metadata and disabled/retired IDs. Connector's existing internal auth, destination policy, TLS validation, and password encryption remain. Source and dataset response tests assert no credential/physical binding fields. This part did not fix the known DNS rebinding window (BIA-018), which remains for C3.

## 22. P1 Multi-Database Regression

- Shared Connector/security tests: **44 passed**; PostgreSQL, MySQL, MariaDB, SQLite, ClickHouse, MSSQL and Oracle registry/contract coverage retained.
- Connector Django app: **143 tests OK**, including additive UUID event and malformed UUID rejection.
- Extractor database strategy/pagination: **35 passed**.
- Query suite: **114 passed**. Integration ownership/migration tests: **5 passed**.
- No engine was live re-tested in this part. Prior P1 evidence has PostgreSQL/MySQL/SQLite/ClickHouse live passes; MariaDB/MSSQL/Oracle are contract-only in this environment. No CDC claim.

## 23. Foundation-A Regression

Query's 114 tests cover logical dataset binding, exact table allowlist, resource limits, workspace concurrency/cancellation, and fail-closed paths. Voice's focused suite passed **27 tests plus 5 subtests**. No Query authority, SQL guard, Voice fallback, or ClickHouse execution policy was changed. The complete prior live resource/cancel drill was not repeated.

## 24. Foundation-B Regression

Shared secret/upload/audio tests passed **28**. Voice's upload/query boundary suite passed as above. Payment, subscription, ClamAV, and private storage code was not modified. A source-directory Gitleaks scan passed for changed Query, frontend, Connector, workflow, and script paths. The full local-tree Gitleaks scan returned 38 findings only in pre-existing ignored local `.env`, integration `.env`, and backup database artifacts; none is from changed source. Those files were not altered or deleted. Foundation-B's prior live evidence remains the baseline; it was not replayed here.

## 25. Runtime Verification

Docker Compose configuration passed. Docker daemon was accessible but `docker ps` showed no running BIAVORA application containers; the configured external PostgreSQL host did not respond to local Query tests. The focused authenticated Gateway → source → Connector → Kafka → ClickHouse → Query flow, source persistence across service restart, and live deletion/isolation were **BLOCKED_ENVIRONMENT / NOT RUN**. A new disposable PostgreSQL container was used solely for migration verification, then stopped; it is not an application E2E pass.

## 26. Files Changed

Created: Integration app/model/service/scope/views/migration/tests, `database.0006`, migration verification script, and this report. Modified: Query model/serializer/views/URLs/settings/tests, Connector view/test, frontend endpoints/management page, and CI release gate. Execution-state documents `20` and `34` are updated below. No files deleted; TimesFM preserved.

## 27. Remaining C3 Work

Versioned opaque credential references and managed secret lifecycle/rotation/audit; `ConnectionTransport`, direct secure Internet transport with DNS/IP revalidation, TLS/egress policy and runtime proof; staged source replacement/cutover/rollback. Private network and agent transport are future modes. Existing transient encrypted event credentials must be retired under a tested migration.

## 28. Remaining C4 Work

Run live authenticated two-workspace source CRUD/discovery/snapshot/preview/delete and service restart, verify real source/dataset persistence and no credential leakage, exercise all applicable source engines honestly, apply owner schemas/roles with denied cross-owner writes, run full security/release/regression gate, and reconcile final issue closure. This report does not close Foundation-C.

## 29. Known Limitations

The Integration app still shares Query's physical PostgreSQL role/schema. Query still directly drops ClickHouse tables on dataset delete. Source state is a definition lifecycle, while ETL status is dataset-specific; durable jobs are separate BIA-009 work. Explicit source CRUD stores only non-secret metadata; repeat connection operations still require credential input until C3. SQLite tokens cannot be reused after staging cleanup. Full local-tree Gitleaks is blocked by ignored local artifacts; changed source scanned clean. The application stack was not running, so live C1/C2 acceptance is pending. `DataSource` is not a production transport/credential implementation.

## 30. Final Part-1 Status

**PARTIAL.** The C1/C2 logical boundary, data model, API, compatibility path, non-destructive import behavior, migration, and focused tests are implemented. BIA-005, BIA-008, BIA-014, BIA-018, and BIA-030 remain open/partial to their full canonical closure criteria. Foundation-A and Foundation-B code regressions tested here are green, while their prior live gates were not rerun. Foundation-C remains **PARTIAL** pending C3 and C4. CDC was not started; no commit or push was made.
