# P1 Multi-Database Implementation Report

Date: 2026-10-07  
Final status: GREEN for the defined P1 snapshot scope.

## Delivered outcome

BIAVORA now exposes a coherent, registry-backed snapshot workflow for PostgreSQL, MySQL, MariaDB, SQL Server, Oracle, SQLite, and ClickHouse. A user can select Database in the existing management page, render fields from backend capabilities, prepare SQLite or enter server details, test the connection, discover source structure, choose schema-qualified tables, start a snapshot, observe status, and access schema/preview through the existing dataset experience.

The implementation reuses the Kafka ETL pipeline rather than establishing a parallel loader. The verified public SQLite E2E moved real edge-case rows from an uploaded database through the API gateway, query service, connector, Kafka, extractor, transformer, loader, and ClickHouse, then returned the completed schema and preview.

## Major code changes

### Shared connector layer

Added `etl-final/shared/connectors/__init__.py` and `core.py` with:

- `ConnectorRegistry` and `BaseDatabaseConnector`.
- PostgreSQL, MySQL, MariaDB, SQL Server, Oracle, SQLite, and ClickHouse implementations.
- Capabilities and dynamic field definitions.
- Configuration validation and SSRF destination checks.
- Engine-specific TLS, discovery, quoting, and pagination.
- Safe error codes.
- Snapshot value/row normalization.
- Opaque, confined, read-only SQLite resolution.

Database type normalization now keeps MariaDB distinct and recognizes ClickHouse. Shared tests cover the registry and secret redaction.

### Connector service

Added internal authenticated endpoints for capabilities, test, discovery, SQLite preparation, and snapshot queueing. SQLite storage validates the extension, configured size limit, file header, token format, workspace ownership, and resolved containment. Snapshot queueing accepts at most 20 selected tables, encrypts the password for the Kafka event, and returns only safe errors.

The legacy upload/connect routes remain in place for compatibility.

### Kafka contract and secret safety

The message validator and schema validator accept canonical engines, nested source configuration, selected schema/table objects, and legacy-compatible shapes. Producer sanitization now recursively redacts sensitive keys inside nested mappings and sequences.

`kafka-python` is pinned to `2.3.0`; this corrects the incompatible unpinned runtime version observed during image verification.

### Extractor and loader

The extractor resolves the registry engine, decrypts the credential envelope in memory, discovers a primary key, reads bounded chunks, normalizes values, and emits workspace/dataset-qualified table sources. Persisted/logged metadata is sanitized.

The loader creates nullable source columns while retaining non-null ETL metadata columns. This is required for faithful database snapshots where any source column can contain null even if the first inferred batch does not.

### Query service and public API

The query service now owns the public source lifecycle and proxies connector operations through internal authentication. It validates manager/workspace scope, creates the dataset before publishing a numeric dataset ID, stores only non-secret engine/table metadata, predicts the scoped storage table, and exposes existing status/schema/preview/delete operations.

The `Database` model gained:

- `source_kind`
- `source_engine`
- `source_tables`

Migration `database.0005_database_source_metadata` was applied successfully. Dataset lookups were tightened to the current workspace. Cross-workspace uniqueness collisions produce a non-disclosing conflict response.

Asynchronous empty snapshots use a bounded `DATABASE_EMPTY_SNAPSHOT_GRACE_SECONDS` setting (60 seconds by default), avoiding a false zero-row completion while the first Kafka batch is still in flight.

### Frontend

`DatabaseManagement.jsx` now provides File and Database tabs. The database workflow is driven by the capabilities response and includes:

- Engine selection.
- Dynamic server/TLS fields.
- SQLite upload/preparation.
- Test success and safe failure states.
- Schema/table discovery and schema-qualified selection.
- Snapshot start and polling.
- Completed/failed states plus schema/preview integration.
- Secret clearing after use.

`databaseSourceState.js` isolates state transitions and validation. Its tests cover capability rendering, server versus SQLite workflows, defaults, connection outcomes, discovery/snapshot transitions, polling completion/failure, secrets, schema-qualified selection, and CSV/XLS regression helpers.

### Integration assets and dependencies

Added:

- Internal SQLite snapshot smoke script.
- Public SQLite snapshot E2E script.
- Optional SQL Server/Oracle Compose profiles and usage instructions.
- Connector test-only requirements.
- Environment documentation for allowed destination CIDRs and SQLite size.

Pinned new runtime drivers:

- `python-tds==1.17.1`
- `oracledb==3.4.2`
- `kafka-python==2.3.0`

## Public contract summary

All source operations are available through `/database/sources/` at the API gateway/query boundary. Internal connector routes live below `/api/databases/`. Capability data, rather than UI constants, determines supported engines and fields. Every capability reports snapshot extraction and `cdc: false`.

## Security changes

- Preserved and centralized destination/SSRF enforcement for every server engine.
- Enforced public and internal authentication boundaries.
- Workspace-qualified dataset access and physical table naming.
- Encrypted passwords in transit through Kafka; no plaintext credential persistence.
- Recursive event/log secret redaction.
- Opaque SQLite references with path confinement and read-only connections.
- TLS controls and CA/hostname validation where the driver supports them.
- Safe error envelopes that do not reflect raw driver exceptions.
- Dialect-safe identifier quoting.

## Verification summary

| Area | Result |
|---|---|
| Shared connector/redaction tests | 18 passed |
| Query full suite | 67 passed, 3 warnings |
| Extractor full suite | 218 passed, 5 skipped, 20 warnings |
| Loader full suite | 8 passed, 1 skipped, 1 warning |
| Connector full app suite | 134 tests, OK |
| Frontend tests | 19 passed, 0 failed |
| CSV focused regression | 24 passed; subset of extractor suite |
| Frontend lint | Pass |
| Frontend production build | Pass, 1,929 modules |
| Live PostgreSQL/MySQL/SQLite/ClickHouse | Pass |
| Public gateway-to-ClickHouse E2E | Pass |
| Final required-container health | 8/8 healthy |
| Final recent error scan | No matches |

See `P1_MULTI_DATABASE_TEST_MATRIX.md` for the non-inflated per-engine matrix and exact evidence.

## Compatibility and cleanup

Existing CSV ingestion passed its focused 24-test regression set. The original file workflow and legacy connector routes remain. Live verification artifacts were cleaned: disposable PostgreSQL/MySQL containers were removed, test SQLite files were deleted, and verification found no remaining P1 E2E ClickHouse tables or query-service records.

The repository had extensive unrelated pre-existing modifications. P1 work did not reset or overwrite those changes.

## Remaining limitations

- No CDC or continuous replication.
- No live MariaDB-specific, SQL Server, or Oracle run in this environment; SQL Server and Oracle have optional profiles.
- A multi-table job writes every table but the current single-dataset schema/preview UI targets the first table.
- Deployment must mount organization CA/wallet material where needed.
- Empty sources can remain in progress for the configured grace window.
- The frontend production bundle exceeds Vite's advisory 500 kB threshold and Browserslist data is stale; neither warning prevented a valid build.

## P2 readiness

P1 establishes the needed seams for P2: one capability registry, explicit source metadata, stable public/internal contracts, selected-table jobs, safe normalized chunks, tenant-qualified storage, and reproducible live-test assets. Recommended P2 priorities are scheduled snapshots, per-table dataset browsing for multi-table imports, live CI profiles for MariaDB/SQL Server/Oracle, observability per source table, and bundle code splitting. CDC should remain a separate architecture decision with explicit offset, replay, and credential-rotation semantics.
