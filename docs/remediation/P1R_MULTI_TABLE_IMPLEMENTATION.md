# P1-R Multi-Table Dataset Browsing

## Previous limitation

A database snapshot could select and load several source tables, but `Database.clickhouse_table_name`, schema, preview, completion, and deletion behavior were effectively anchored to the first table. Users could not browse the other successfully loaded tables, and cleanup could leave non-primary physical tables behind.

## Selected architecture

One logical dataset now owns an ordered list of imported child-table metadata. This preserves the current Dataset abstraction while making every imported table independently addressable:

```text
Dataset
  -> source_tables[]
       -> opaque id
       -> source schema/name
       -> processing/completed status
       -> row/column counts
       -> columns schema
       -> internal destination table (server-side only)
```

`source_tables` is a JSON field introduced by migration `database.0005_database_source_metadata`; `source_kind` and `source_engine` distinguish file and database sources. Physical ClickHouse names remain workspace/dataset qualified and are never accepted from a client.

## Table identity and authorization

- The public selector is the first 20 hex characters of SHA-256 over the source schema/name identity. It is stable for the dataset response but reveals no destination name.
- Query resolution first selects the authenticated manager's dataset inside the JWT workspace, then matches the requested selector only against that dataset's allowlisted `source_tables`.
- Unknown selectors return a safe not-found response; duplicate schema/name selections are rejected.
- The serializer exposes source identity, status, counts, and schema only. It explicitly omits `destination_table`.
- Destination names are generated from workspace ID, dataset ID, database/service identity, schema, and table, then sanitized for ClickHouse. Arbitrary physical table injection is not possible through schema/preview parameters.

## API behavior

- Dataset detail includes a public `source_tables` list.
- `GET /database/schema/?table=<opaque-id>` returns the selected imported table's schema and table identity.
- `GET /database/preview/?table=<opaque-id>` returns that table's preview, row total, and table identity.
- `table_id` remains accepted as an alias.
- Omitting `table` retains backward-compatible first-table behavior.
- Completion checks every imported destination table, records each table's count/schema/status, and publishes the dataset aggregate row count.
- Deletion iterates every server-side allowlisted destination and drops each one.

## Empty tables

Extractor publishes a schema-only event for a selected existing table with zero rows. Kafka validation permits this only when `schema_only=true`, row count is zero, and columns are present. Transformer preserves the event and loader creates the zero-row physical table. The dataset can therefore complete with `rows=0` instead of failing or waiting indefinitely for a row that cannot exist.

## Frontend behavior

The Database Management page retains separate File and Database workflows. For completed database datasets, `ImportedTableSelector` renders the imported table list, keeps the chosen opaque ID in component state, and reloads schema/preview when the user switches tables. Poll completion selects the first table by default. File/CSV behavior remains unchanged.

## Backward compatibility

- Legacy single-table rows with an empty `source_tables` list synthesize a `default` table using `clickhouse_table_name`.
- Existing clients can omit the table parameter and receive the first imported table.
- Legacy status text remains singular for one table.
- Serializer and view tests cover non-list legacy metadata and first-table fallback.
- CSV/file datasets continue to use the established schema/preview path.

## Verification

- Query-service full suite: 79 passed.
- Frontend suite: 19 passed.
- Live PostgreSQL, MySQL, MariaDB, SQLite, and ClickHouse-source E2Es each selected multiple tables and asserted:
  - all expected tables appear;
  - per-table row counts match source;
  - each schema/preview response returns the requested opaque table ID;
  - empty-table preview reports zero rows;
  - aggregate dataset counts equal the sum of child tables;
  - 2,500-row tables contain 2,500 unique IDs.
- Workspace isolation passed both automated tests and live SQLite cross-workspace token denial.
- Cleanup was verified at zero remaining P1-R destination tables.
