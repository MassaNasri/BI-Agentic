# P1 Multi-Database Audit

Date: 2026-10-07  
Scope: one-time database snapshots only; change-data capture (CDC) is explicitly out of scope.

## Executive finding

The pre-P1 product presented a broader database story than it could execute. The UI and validation layers named multiple engines, but the runtime extraction path was effectively limited to PostgreSQL and MySQL. MariaDB was collapsed into MySQL, SQL Server, Oracle, and SQLite had no complete execution path, ClickHouse was not available as an external source, and there was no shared capabilities contract tying the frontend to executable backend support.

P1 closes that gap with one connector registry used by connection testing, discovery, and extraction; a public source API through the API gateway and query service; a database workflow in the existing management UI; and the existing Kafka/transform/load path into ClickHouse. The implementation supports PostgreSQL, MySQL, MariaDB, SQL Server, Oracle, SQLite, and ClickHouse as snapshot sources. Live verification was completed for PostgreSQL, MySQL, SQLite, and ClickHouse. SQL Server, Oracle, and a MariaDB-specific server were not started locally and are not represented as live passes.

## Original architecture and data flow

The existing file path was:

1. Frontend uploads CSV/XLS-family input through the API gateway.
2. Query/connector services validate the request and publish an extraction event.
3. Extractor reads source data and writes Kafka batches.
4. Transformer processes those batches.
5. Loader writes ClickHouse tables.
6. Query service exposes dataset status, schema, preview, and deletion.

The partial database path had separate conditionals, incomplete normalization, and no authoritative engine capability description. Database credentials and engine details could take different shapes between API validation, the event envelope, and extraction.

## Root causes

| Area | Pre-P1 problem | Effect |
|---|---|---|
| Capability truth | Engine names were duplicated in UI and validators | Advertised support could diverge from executable support |
| Connector construction | Per-engine logic was conditional and incomplete | SQL Server, Oracle, SQLite, and ClickHouse could not traverse a common workflow |
| MariaDB identity | MariaDB normalized to MySQL | The product could not report or reason about MariaDB independently |
| Discovery | No uniform schema/table/column/PK contract | UI could not offer safe, engine-neutral selection |
| Public API | No complete source lifecycle through gateway/query service | Users could not test, discover, start, and observe a snapshot consistently |
| SQLite | No managed upload/token workflow | Accepting client filesystem paths would have created a path traversal boundary |
| Value transport | Driver-native values were not normalized centrally | Decimal, temporal, UUID, binary, JSON, null, and Unicode behavior varied |
| Secret lifecycle | Event and log redaction was shallow | Nested connector secrets could leak or persist incorrectly |
| Tenant scope | Some legacy lookups were not workspace-qualified | Cross-workspace collision and disclosure risk |

## Pre-P1 versus implemented support

| Engine | Pre-P1 executable snapshot | P1 implementation | Live verification in this environment |
|---|---:|---:|---:|
| PostgreSQL | Partial | Yes | Pass |
| MySQL | Partial | Yes | Pass |
| MariaDB | Aliased to MySQL | Yes, distinct capability/connector | Not run |
| SQL Server | No complete path | Yes | Not run |
| Oracle | No complete path | Yes, thin driver | Not run |
| SQLite | No managed database workflow | Yes, opaque uploaded-file token | Pass |
| ClickHouse external source | No | Yes | Pass |

## Reused architecture

P1 deliberately retained these proven components:

- The API gateway as the public boundary.
- Query service ownership of user-visible dataset metadata and status.
- Connector service publication into the existing Kafka ingestion path.
- Extractor, transformer, loader, and ClickHouse as the data plane.
- Existing credential encryption, augmented with recursive redaction.
- Existing destination policy/SSRF protection, now invoked by every server connector.
- Existing CSV/XLS ingestion behavior and user-visible schema/preview endpoints.

## New shared connector contract

`etl-final/shared/connectors` now owns:

- Canonical engine identity and capability fields.
- Configuration validation and stable safe error mapping.
- Connection test, schema/table discovery, column introspection, and primary-key discovery.
- Dialect-specific identifier quoting and chunked snapshot queries.
- TLS options and lazy driver loading.
- Deterministic snapshot value normalization.
- Registry lookup used by both connector and extractor services.

The registry is the source of truth for the frontend capability response. It reports snapshot support and `cdc: false` for every engine.

## Data correctness findings

The snapshot transport now preserves the meaningful source value without relying on JSON's lossy defaults:

- `NULL` remains null.
- `Decimal` becomes an exact decimal string.
- Date, time, and datetime values use ISO 8601 strings.
- UUID becomes its canonical string.
- Binary becomes a `base64:`-prefixed string.
- Nested JSON is normalized recursively.
- Unicode remains Unicode end to end.

Loader source columns are nullable; ETL metadata columns remain non-null. A live SQLite path exposed the old nullable-column mismatch and the P1 implementation corrected it.

## Security audit

| Control | Result |
|---|---|
| Public authentication | Source endpoints require the existing authenticated gateway/query path |
| Internal authentication | Query-to-connector calls use the existing internal authentication headers |
| Tenant isolation | Dataset operations and source records are workspace-scoped; colliding cross-workspace ownership returns 409 rather than leaking data |
| SSRF policy | Every server-based connector validates the resolved host/port against the destination policy before connecting |
| Credential storage | Passwords are encrypted for the Kafka handoff and are not stored in the dataset record |
| Log/event redaction | Nested mappings and sequences are recursively redacted for password/token/secret-like keys |
| SQLite paths | Clients receive an opaque token; the resolved path is confined to the configured workspace directory and opened read-only |
| SQLite validation | Extension, size, and SQLite header are validated before preparation |
| TLS | Engine-specific TLS fields are exposed; SQL Server CA validation and Oracle TCPS service-name construction are covered by contract tests |
| Error disclosure | Driver exceptions are mapped to stable codes/messages without DSNs, credentials, or tracebacks |
| Identifier safety | Schema, table, and column identifiers use connector-specific quoting rather than string acceptance |

## Dependency audit

The runtime images pin the new drivers:

- `kafka-python==2.3.0`
- `python-tds==1.17.1`
- `oracledb==3.4.2`

PostgreSQL, PyMySQL, and ClickHouse drivers remain in the service requirements. `hypothesis==6.151.9` is test-only in the connector service's `requirements-test.txt`; it is not installed in the clean production image.

## Residual risks and constraints

- CDC and continuous synchronization are not implemented by design.
- SQL Server, Oracle, and MariaDB-specific live runtimes were not exercised in this workstation run. SQL Server and Oracle optional Compose profiles are supplied for follow-up validation.
- A multi-table request loads each selected table into its own tenant/dataset-qualified ClickHouse table, while the single dataset record's current schema/preview contract points to the first selected table.
- Private/internal database targets must be explicitly allowed by deployment destination-policy configuration; P1 does not weaken SSRF policy for convenience.
- Customer CA certificates and Oracle network material must be supplied as deployment mounts where required.
- A truly empty snapshot uses a bounded 60-second default grace period so the asynchronous status check does not mistake an in-flight first batch for a completed zero-row dataset.

## Audit conclusion

The executable product surface and the advertised product surface now agree for snapshot ingestion. The mandatory minimum live matrix passed, the complete public SQLite path passed through Kafka and ClickHouse, legacy CSV tests passed, all core containers are healthy, and recent core-service logs are clean. Subject to the explicitly stated optional-engine runtime gaps, P1 is complete and ready to serve as the base for P2 work.
