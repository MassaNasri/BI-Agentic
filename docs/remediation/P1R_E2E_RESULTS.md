# P1-R Full E2E Results

Date: 2026-10-11

Every database result marked PASS below entered through the authenticated public API gateway and traversed Query -> Connector -> Kafka -> Extractor -> Transformer -> Loader -> destination ClickHouse. Direct connector checks were diagnostic only and were not used to claim full E2E.

## CSV / existing file workflow

- Source environment: existing file workflow and established dirty/stress CSV assets.
- Manual acceptance: PASS, as supplied by the user.
- Automated regression: PASS, 24/24 in `test_csv_extraction_strategy.py`.
- Assertions: quoted/custom-delimiter data, chunk boundaries, header/no-header behavior, only-header and empty-file behavior, deterministic batch IDs, schema validation, bounded reading, complete multi-batch coverage, and existing CSV/Excel frontend acceptance.
- Public path: unchanged file workflow; previous full public pipeline evidence remains valid and the current connector/extractor/frontend regressions passed.
- Cleanup: PASS; no P1-R CSV artifact was created by this run.

## PostgreSQL

- Source: disposable PostgreSQL 18.3, database `p1r_source`, read-only `biavora_reader`, schemas `company_data` and `analytics_demo`.
- Public path: PASS.
- Connection/discovery: `CONNECTION_OK`; four selected tables, columns, and PKs discovered. SELECT-only PK discovery passed through the new `pg_catalog` fallback.
- Destination/dataset: `completed`, aggregate 2,512 rows.

| Source table | Source rows | Destination rows | PK |
|---|---:|---:|---|
| `company_data.customers` | 8 | 8 | `id` |
| `company_data.empty_table` | 0 | 0 | `id` |
| `company_data.large_events` | 2,500 | 2,500 | `id` |
| `analytics_demo.Sales Data` | 4 | 4 | quoted `Order ID` |

- Integrity: 2,500 rows and 2,500 unique IDs in `large_events`; Unicode included Arabic, Japanese, accented Latin, and emoji; deterministic schema/preview table identities passed.
- Failure checks: blocked host `DESTINATION_NOT_ALLOWED`; invalid database `DATABASE_NOT_FOUND`; wrong password `AUTHENTICATION_FAILED`; wrong port returned a safe connection error before the refined refusal mapping, whose post-fix contract test passes.
- Cleanup: PASS.

## MySQL

- Source: disposable MySQL 8.4, database `p1r_source`, SELECT-only `biavora_reader`.
- Public path: PASS.
- Connection/discovery: `CONNECTION_OK`; four tables with independent PK/column inspection.
- Destination/dataset: `completed`, aggregate 2,512 rows.

| Source table | Source rows | Destination rows |
|---|---:|---:|
| `customers` | 8 | 8 |
| `empty_table` | 0 | 0 |
| `large_events` | 2,500 | 2,500 |
| `Sales Data` | 4 | 4 |

- Integrity: 2,500 unique large-event IDs; Arabic/Japanese/accented/emoji text retained; table-aware schema and preview passed.
- Failure checks: wrong password `AUTHENTICATION_FAILED`; invalid database `PERMISSION_DENIED` under the read-only grant model; wrong port `CONNECTION_REFUSED`; blocked host `DESTINATION_NOT_ALLOWED`.
- Cleanup: PASS.

## MariaDB

- Source: disposable MariaDB 11.8, database `p1r_source`, SELECT-only `biavora_reader`.
- Public path: PASS, independently of MySQL.
- Connection/discovery: `CONNECTION_OK`; MariaDB PK fallback, columns, and four tables passed.
- Destination/dataset: `completed`, aggregate 2,512 rows: `customers=8`, `empty_table=0`, `large_events=2500`, `Sales Data=4`.
- Integrity: 2,500 unique large-event IDs; Unicode retained; schema/preview and multi-table identity passed.
- Failure checks: wrong password `AUTHENTICATION_FAILED`; invalid database `PERMISSION_DENIED`; wrong port `CONNECTION_REFUSED`; blocked host `DESTINATION_NOT_ALLOWED`.
- Cleanup: PASS.

## SQLite

- Source: runtime-created valid SQLite 3 file uploaded through `/database/sources/sqlite/prepare/` under an opaque workspace token.
- Public path: PASS.
- Connection/discovery: `CONNECTION_OK`; three tables, columns, and PKs discovered; source was opened read-only.
- Destination/dataset: `completed`, aggregate 2,503 rows.

| Source table | Source rows | Destination rows | PK |
|---|---:|---:|---|
| `Sales Data` | 3 | 3 | `Order ID` |
| `empty_table` | 0 | 0 | `id` |
| `large_events` | 2,500 | 2,500 | `id` |

- Integrity: 2,500 unique large-event IDs; 2 representative nulls; `Damascus – مرحبا`, `Zoë`, and `東京 😊` matched in preview; table-aware schema/preview passed.
- Rejections: bad extension and invalid header rejected safely; cross-workspace token returned `PERMISSION_DENIED`; traversal and absolute-path-shaped tokens returned `INVALID_CONFIGURATION`.
- Cleanup: public dataset deletion passed; the exact remaining acceptance-token file was enumerated and removed; final workspace file count was zero.

## ClickHouse external source

- Source: disposable logically separate ClickHouse instance/database `p1r_source`, read-only `biavora_reader`; destination remained BIAVORA's `clickhouse` service.
- Public path: PASS.
- Connection/discovery: `CONNECTION_OK`; four tables, columns, and PKs discovered.
- Destination/dataset: `completed`, aggregate 2,512 rows.

| Source table | Source rows | Destination rows |
|---|---:|---:|
| `customers` | 8 | 8 |
| `empty_table` | 0 | 0 |
| `large_events` | 2,500 | 2,500 |
| `Sales Data` | 4 | 4 |

- Integrity: 2,500 unique large-event IDs; Unicode set exactly included `Damascus – مرحبا`, `東京`, `Zoë`, and `Renée 😊`; table-aware schema/preview passed.
- Failure checks: wrong password `AUTHENTICATION_FAILED`; invalid database `DATABASE_NOT_FOUND`; wrong port `CONNECTION_REFUSED`; blocked host `DESTINATION_NOT_ALLOWED`.
- Runtime note: the first attempt exposed intermittent Docker Desktop host-port hairpin failure. The test was rerun using the disposable source on the application network plus a temporary exact `/32`; no policy was disabled. The allowance was removed afterward.
- Cleanup: PASS.

## SQL Server

- Source environment: reproducible `p1-mssql` profile using Microsoft SQL Server 2022 Developer and deterministic seed procedure.
- Driver/contract/profile: PASS (`python-tds` imports; registry, configuration, quoting, pagination, TLS, errors, and Compose render pass).
- Live/full E2E: `BLOCKED_EXTERNAL` / `BLOCKED_EXTERNAL`.
- Rows verified: 0.
- Exact blocker: the image was not cached; permission to download/start the optional image was requested and declined. No live claim is made.
- Cleanup: no container or data was created.

## Oracle

- Source environment: reproducible `p1-oracle` profile using Oracle Free thin-mode configuration and deterministic seed scripts.
- Driver/contract/profile: PASS (`oracledb` imports; service-name/TCPS configuration, quoting, pagination, errors, and Compose render pass).
- Live/full E2E: `BLOCKED_EXTERNAL` / `BLOCKED_EXTERNAL`.
- Rows verified: 0.
- Exact blocker: the image was not cached; after the SQL Server image pull/start was declined, no unauthorized Oracle download was attempted. No live claim is made.
- Cleanup: no container or data was created.

## Final cleanup proof

```text
query-service P1-R records: 0
destination ClickHouse P1-R tables: 0
temporary SQLite acceptance files: 0
disposable p1r-* containers: 0
```
