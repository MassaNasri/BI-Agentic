# P1 Multi-Database Test Matrix

Date: 2026-10-07  
Result vocabulary: `PASS` means executed successfully in this run; `NOT RUN` means no live claim is made. Unit/contract coverage is separate from a live server integration or complete application E2E.

## Engine coverage

| Engine | Unit/contract | Live connection + discovery + chunked read | Full gateway-to-ClickHouse E2E | Runtime driver/image | Notes |
|---|---|---|---|---|---|
| PostgreSQL | PASS | PASS | NOT RUN | PASS | Disposable live server; PK discovery, two chunks, exact decimal, null |
| MySQL | PASS | PASS | NOT RUN | PASS | MySQL 8.4; information-schema case handling, PK, exact decimal/date/null |
| MariaDB | PASS | NOT RUN | NOT RUN | NOT RUN | Distinct registry identity; MySQL-protocol connector contract covered |
| SQL Server | PASS | NOT RUN | NOT RUN | NOT RUN | python-tds construction, quoting/paging, CA TLS and host validation covered; optional profile supplied |
| Oracle | PASS | NOT RUN | NOT RUN | NOT RUN | oracledb thin service-name/TCPS construction, quoting/paging covered; optional profile supplied |
| SQLite | PASS | PASS | PASS | PASS | Opaque upload token; full public application flow; null and Unicode verified |
| ClickHouse external source | PASS | PASS | NOT RUN | PASS | Live external-source connection/discovery/chunked read; 3 rows, null and Unicode |

## Automated suite results

| Suite | Exact result | Scope |
|---|---|---|
| Shared connector + recursive redaction | 18 passed | Registry, all engine contracts, type normalization, TLS, safe errors, redaction |
| Query service full suite | 67 passed, 3 warnings | Public source API, auth/scope, dataset lifecycle, legacy query behavior |
| Extractor full suite | 218 passed, 5 skipped, 20 warnings | Database and file extraction, Kafka listener, validation, idempotency/checkpoints |
| Loader full suite | 8 passed, 1 skipped, 1 warning | Nullable source columns, ClickHouse load behavior, existing loader coverage |
| Connector Django app full suite | 134 tests, OK | Upload regression, database endpoints, validation, limits, Kafka publication |
| Frontend | 19 tests passed, 0 failed | Capabilities, workflow states, polling, secrets, selection, file regression helpers |
| CSV regression subset | 24 passed | Existing CSV extraction behavior; included within the extractor coverage and not additive |

There is deliberately no aggregate pass total because the 24-test CSV command is a focused subset of the extractor suite. Per-command exact counts above avoid double counting.

## Static/build checks

| Check | Result |
|---|---|
| Frontend ESLint | PASS |
| Frontend production build | PASS: 1,929 modules transformed |
| Query Django system check | PASS |
| Connector Django system check | PASS |
| Query migration drift check | PASS: no changes detected |
| Query migration `database.0005_database_source_metadata` | PASS: applied |
| Optional Compose profile config (`p1-mssql`) | PASS |
| Optional Compose profile config (`p1-oracle`) | PASS |

The frontend build emitted advisory stale-Browserslist-data and bundle-size warnings; it produced the distribution successfully. The main JavaScript artifact was 670.11 kB (194.12 kB gzip).

## Live integration evidence

### PostgreSQL

- Disposable PostgreSQL service started and accepted the registry connection.
- Connection result: `CONNECTION_OK`.
- Schema/table/column and primary-key discovery passed.
- Two rows were read with `chunk_size=1`.
- Decimal value remained `"12.3400"`; null remained null.
- Disposable service was stopped and removed after the check.

### MySQL

- Disposable MySQL 8.4 service started and accepted the registry connection.
- Connection result: `CONNECTION_OK`.
- Table, five columns, and primary key were discovered.
- Two rows were read with `chunk_size=1`.
- Decimal scale, ISO date, and null were preserved.
- Disposable service was stopped and removed after the check.

### SQLite internal pipeline

- SQLite file passed extension, maximum-size, and header checks.
- Prepared path was represented by an opaque workspace token.
- Connector discovery and snapshot queueing passed.
- Extractor emitted 3 rows; transformer and loader completed.
- ClickHouse contained 3 rows, 2 null values, and Unicode values including `Damascus – مرحبا`, `Zoë`, and `東京`.
- Test file and ClickHouse table were removed after verification.

### ClickHouse external source

- Connection result: `CONNECTION_OK`.
- Source table and 11 columns were discovered.
- Chunked read returned 3 rows and preserved 2 nulls and Unicode.
- Source test table was removed afterward.

### Full public application path

The authenticated test used the public API gateway, not an internal shortcut:

```text
API gateway -> query service -> connector -> Kafka -> extractor
-> transformer -> loader -> ClickHouse -> query status/schema/preview
```

Observed result:

```json
{
  "connector_count": 7,
  "dataset_status": "completed",
  "discovered_table": "Sales Data",
  "preview_nulls": 2,
  "preview_rows": 3,
  "public_gateway": true,
  "schema_columns": 11,
  "test_connection": "CONNECTION_OK",
  "unicode_values": ["Damascus – مرحبا", "Zoë", "東京"]
}
```

The dataset was deleted through the public lifecycle. Follow-up checks found zero P1 E2E ClickHouse tables and zero P1 E2E query-service records.

## Docker/runtime verification

Final `docker compose ps` reported all required services healthy:

- `api-gateway`
- `etl-connector`
- `etl-extractor`
- `etl-transformer`
- `etl-loader`
- `query-service`
- `kafka`
- `clickhouse`

A final three-minute log scan across those services for `ERROR|CRITICAL|Traceback|Unhandled|ImportError` returned no matches. Final production images contain `kafka-python 2.3.0`, `python-tds 1.17.1`, and `oracledb 3.4.2`; test-only Hypothesis was removed by rebuilding/recreating the clean connector image.

## Optional-engine procedure

`etl-final/tests/integration/docker-compose.p1-optional.yml` provides separately gated SQL Server and Oracle services. Instructions are in `README_P1_OPTIONAL.md`. Their configuration renders successfully, but their images were not started and no live result is claimed. A MariaDB-specific live profile remains a P2/test-infrastructure follow-up.

## Release interpretation

The required minimum live integration matrix—PostgreSQL, MySQL, SQLite, and ClickHouse—passed. At least one complete application path passed with real row movement. Unit/contract coverage exists for all seven engines. Optional engine live gaps remain visible and do not invalidate the P1 snapshot implementation claim.
