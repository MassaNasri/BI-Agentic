# P1 Multi-Database Architecture

Date: 2026-10-07  
Mode: bounded, one-time snapshot ingestion. CDC is not part of P1.

## System flow

```text
Browser
  -> API gateway (JWT/public boundary)
  -> Query service (workspace ownership + dataset lifecycle)
  -> Connector service (capabilities/test/discover/queue)
  -> Kafka ingestion event (encrypted credential envelope)
  -> Extractor (registry connector + chunked reads)
  -> Transformer
  -> Loader
  -> ClickHouse tenant/dataset-qualified table
  -> Query service status/schema/preview
```

SQLite uses the same flow after an initial upload/preparation call. The uploaded file is stored below a workspace-specific root; downstream calls carry an opaque token rather than an arbitrary filesystem path.

## Component responsibilities

| Component | Responsibility |
|---|---|
| Frontend | Render capabilities, collect dynamic engine fields, prepare SQLite, test, discover, select tables, start snapshot, poll, and render schema/preview |
| API gateway | Route `/database/sources/*` and enforce the existing public authentication boundary |
| Query service | Enforce workspace ownership, proxy internal operations, create dataset metadata, expose lifecycle/schema/preview, avoid persisting credentials |
| Connector service | Validate configuration, expose registry capabilities, run test/discovery, encrypt credentials, and publish snapshot jobs |
| Shared connector registry | Canonical engine metadata, drivers, TLS rules, quoting, discovery, chunking, normalization, and safe errors |
| Kafka | Carry the existing ingestion event contract with database source details |
| Extractor | Decrypt the short-lived connector envelope, instantiate the same registry engine, read chunks, normalize rows, and publish batches |
| Transformer | Preserve the existing transformation contract |
| Loader | Create nullable source columns, add non-null ETL metadata, and insert ClickHouse batches |
| ClickHouse | Store materialized snapshot tables and serve preview/schema/query consumers |

## Public source API

The API gateway exposes the query-service routes below under the existing database prefix:

| Method | Route | Purpose |
|---|---|---|
| GET | `/database/sources/capabilities/` | Return authoritative registry-backed engines and fields |
| POST | `/database/sources/test/` | Test a server configuration or prepared SQLite token |
| POST | `/database/sources/discover/` | Return schemas, tables, columns, and primary keys |
| POST | `/database/sources/sqlite/prepare/` | Validate/store SQLite and return an opaque token |
| POST | `/database/sources/snapshot/` | Create the dataset lifecycle and queue selected tables |
| GET | `/database/` | Read current dataset status/metadata |
| GET | `/database/preview/` | Read ClickHouse preview after completion |
| DELETE | `/database/` | Delete dataset metadata/storage using the existing lifecycle |

Query service calls the corresponding internal connector routes at `/api/databases/*` with internal authentication.

## Registry contract

The registry resolves these canonical IDs:

| ID | Driver | Default port | Workflow |
|---|---|---:|---|
| `postgresql` | psycopg2 | 5432 | server |
| `mysql` | PyMySQL | 3306 | server |
| `mariadb` | PyMySQL-compatible protocol | 3306 | server |
| `mssql` | python-tds | 1433 | server |
| `oracle` | python-oracledb thin mode | 1521 | server |
| `sqlite` | Python sqlite3 | n/a | file upload |
| `clickhouse` | clickhouse-driver | 9000 | server |

Every connector supplies:

- `capabilities()`
- `validate_configuration()`
- `connect()` / `close()`
- `test_connection()`
- `list_schemas()` / `list_tables()` / `inspect_table()`
- `quote_identifier()` / `qualified_table()`
- `build_snapshot_query()` / chunk iteration

Drivers are imported lazily. Capability discovery remains available if an optional driver is absent; connection attempts then return `DRIVER_UNAVAILABLE` rather than crashing service startup.

## Capability-driven frontend

The UI does not maintain a second list of supported engines. It requests the registry capabilities, then uses each engine's workflow and field descriptors to render:

- Server connection fields and defaults.
- Password inputs with secret-clearing behavior.
- TLS controls.
- SQLite file selection/preparation.
- Connection success/failure state.
- Discovery and schema-qualified table selection.
- Snapshot start, polling, completion/failure, schema, and preview.

The existing file tab remains available, preserving CSV/XLS behavior.

## Snapshot event and table identity

The connector publishes a validated event containing source engine, non-secret configuration, encrypted password, selected tables, dataset/workspace scope, and snapshot mode. The extractor decrypts only at execution time. Persisted source metadata contains engine/table identity, never plaintext credentials.

Each selected source table maps to a ClickHouse name with explicit scope:

```text
w{workspace_id}_d{dataset_id}_{engine}_{schema}_{table}
```

Names are sanitized by the existing storage naming layer. This identity prevents two workspaces or datasets from targeting the same physical table.

## Discovery and extraction

Discovery returns schema and table inventories and can inspect an individual table's columns and primary key. Extraction:

1. Revalidates the destination and configuration.
2. Opens a driver connection.
3. Selects quoted identifiers only.
4. Uses a discovered primary key for deterministic keyset pagination when feasible; otherwise uses the connector's bounded offset pagination.
5. Emits bounded chunks rather than materializing the complete source table.
6. Normalizes every value before JSON/Kafka serialization.
7. Closes connections on success and failure.

The selected-table limit is 20 per snapshot request. Chunk size and timeouts are bounded configuration values.

## Value normalization

| Source value | Kafka-safe representation |
|---|---|
| null | JSON null |
| string/integer/float/boolean | Same primitive |
| exact decimal | String preserving scale |
| datetime/date/time | ISO 8601 string |
| UUID | Canonical string |
| bytes/binary | `base64:` plus Base64 payload |
| mapping/list/tuple/set | Recursively normalized JSON structure |
| unsupported driver object | Stable string fallback |

Unicode is passed through without ASCII coercion. Loader columns inferred from source values are nullable so a later null cannot invalidate an otherwise valid batch.

## Credential lifecycle

```text
Browser password field
  -> authenticated request
  -> internal authenticated connector call
  -> encrypted Kafka event field
  -> decrypt in extractor memory
  -> driver connection
  -> discard
```

Passwords are not included in dataset source metadata. Redaction walks nested mappings and sequences before event/log serialization. Safe connector errors expose a stable code and generic explanation, not the raw driver message.

## Network and TLS policy

Before a server connection, the connector resolves the destination and calls the shared destination policy. Loopback, link-local, private, or otherwise restricted ranges are rejected unless explicitly allowed by deployment CIDRs. This is performed in the shared base validation, so adding a new server connector cannot silently skip it.

TLS fields are engine specific. Certificate validation remains enabled unless an explicit trust option says otherwise. SQL Server uses `cafile` for python-tds TLS and host validation when trust is not disabled. Oracle uses thin-mode host/port/service-name arguments and `tcps` when requested; it does not embed credentials in a DSN string.

## Status semantics

The query service reports the existing dataset states. Completion is based on the materialized ClickHouse table. Because ingestion is asynchronous, database sources get a bounded empty-snapshot grace window (default 60 seconds): a not-yet-created/empty table is treated as in progress during the window, then as a valid zero-row completion if no rows arrive.

## Adding a future connector

1. Implement `BaseDatabaseConnector` in `shared/connectors`.
2. Define canonical ID, fields, driver, port, TLS behavior, quoting, discovery, and pagination.
3. Register it in the shared registry.
4. Add unit/contract cases for capabilities, validation, quoting, discovery metadata, paging, normalization, safe errors, TLS, and SSRF.
5. Add a live integration profile and edge-case seed table.
6. Do not add a frontend engine constant; the UI will render the new capability.
7. Keep `cdc: false` until a separate design provides durable offsets, replay semantics, and operational ownership.

## P2 seams

The registry, explicit snapshot mode, selected-table contract, source metadata, stable errors, and per-table scoped naming create clean extension points for scheduled refresh, richer multi-table dataset UX, additional connectors, and—only after separate design—CDC. P2 should retain the registry as the single capability source and must not bypass the destination or credential boundaries.
