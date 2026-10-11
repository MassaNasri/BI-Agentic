# P1-R Security Report

Date: 2026-10-11  
Decision: PASS for the P1 snapshot boundary.

## SSRF and destination policy

All server connectors resolve destination addresses before opening a driver connection. Loopback, link-local, multicast, unspecified, and private destinations remain denied unless an exact approved CIDR includes the resolved address. Public live failure tests returned `DESTINATION_NOT_ALLOWED` for `127.0.0.1`.

Development acceptance did not disable policy. Compose maps `host.docker.internal` through `host-gateway`; connector/extractor resolved it to `192.168.65.254`, and local `.env` contains only `192.168.65.254/32`. `.env.example` documents runtime resolution and narrow `/32` use while preserving an empty secure default. A temporary `172.19.0.15/32` used for the isolated ClickHouse source was removed immediately after acceptance.

## Source privileges

Live sources used read-only accounts:

- PostgreSQL: `CONNECT` on database, `USAGE` on selected schemas, `SELECT` on source tables. PK discovery falls back to readable `pg_catalog` metadata and requires no DDL rights.
- MySQL/MariaDB: `SELECT` on the test database; MariaDB PK fallback reads `information_schema.columns`.
- SQLite: URI read-only mode against a workspace-confined opaque file.
- ClickHouse: `SELECT` on the source database with `readonly=1`.

Recommended optional-engine minimums remain:

- SQL Server: login/connect plus `SELECT` and metadata visibility on selected schemas/tables; no source DDL/DML role.
- Oracle: `CREATE SESSION` plus explicit `SELECT` grants on selected owner tables; no DBA role.

Connector/extractor logs showed discovery and reads only. No source `CREATE`, `UPDATE`, or `DELETE` was required.

## Credentials and Kafka transport

- Public configuration accepts secrets only for the immediate operation.
- Password/private-key fields are cleared from frontend state after snapshot start and are not persisted in local/session storage.
- Query encrypts the source credential envelope before Kafka publication.
- Extractor decrypts only at the source-connection boundary.
- Recursive redaction tests cover nested event/log structures.
- Public error envelopes never include raw driver tracebacks, passwords, DSNs, certificates, or private keys.
- Final exact-value scans found no local acceptance secret in required-service logs.

## SQLite confinement

- Allowed extensions are `.db`, `.sqlite`, and `.sqlite3`.
- Maximum size is checked before persistence.
- The 16-byte SQLite 3 header is required.
- Storage names are server-generated `sqlite_<workspace>_<uuid>.db` tokens.
- Resolution enforces the configured root and token workspace.
- Traversal-shaped and absolute-path-shaped values were rejected with `INVALID_CONFIGURATION`.
- A token minted for another workspace was rejected with `PERMISSION_DENIED`.
- The final acceptance token file was explicitly removed and the workspace file count verified as zero.

## TLS

Capabilities expose engine-specific TLS modes. Connector contracts verify mapping of CA/certificate options to PostgreSQL, MySQL/MariaDB, SQL Server, Oracle, and ClickHouse drivers. Hostname verification is not disabled globally. Invalid/incompatible TLS input is normalized to `TLS_ERROR` or `INVALID_CONFIGURATION`, and certificate/private-key contents are redacted. Local disposable containers intentionally used explicit plaintext development mode; no claim of an enterprise-PKI live run is made.

## Workspace and service authentication

- Public database endpoints require an authenticated manager JWT with workspace scope.
- Internal Query-to-Connector calls require internal-service authentication and workspace headers.
- Dataset lookup is manager/workspace scoped.
- Imported table resolution occurs only after dataset authorization and only through an allowlisted opaque ID.
- A live SQLite token from workspace `99992` was denied to workspace `99993`.
- Physical destination table names include workspace and dataset IDs and are not serialized publicly.

## Errors, observability, and logs

Safe logs include connector, workspace, dataset, job, schema/table, chunk/row count, result, and normalized code. The final five-minute scan across all eight required services found no `ERROR`, `CRITICAL`, `Traceback`, `Unhandled`, `ImportError`, `panic`, or `fatal` match. Earlier deliberate negative tests and the diagnosed Docker host-hairpin failures remain documented as acceptance evidence, not ignored.

## Automated evidence

- Shared connector/security/redaction/schema suite: 111 passed.
- Focused TLS/SSRF/error/auth gate: 16 passed, 26 deselected.
- Query full suite, including workspace/table authorization: 79 passed.
- Connector full suite: 134 passed.
- SQLite live file-boundary and cross-workspace failures: PASS.
- Public failure cases for PostgreSQL, MySQL, MariaDB, and ClickHouse: PASS.
