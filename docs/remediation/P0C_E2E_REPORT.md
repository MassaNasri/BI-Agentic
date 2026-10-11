# P0-C disposable BI workflow report

Result: **PASS**. Cleanup: **PASS**. The workflow uses `scripts/verify_p0c_e2e.py`, a tiny synthetic non-sensitive CSV, deterministic chart selection, no paid inference, and no outbound email.

## Executed path

1. Created and authenticated disposable tenant A and tenant B identities through Auth.
2. Created an isolated tenant A workspace.
3. Uploaded a tagged synthetic sales CSV through Query into the real Kafka ETL path.
4. Verified ClickHouse ingestion: 12 rows and 13 resulting columns.
5. Retrieved the dataset preview through Query.
6. Polled unified Surreal metadata by exact workspace/dataset/ingestion-job scope.
7. Proved tenant B could not read tenant A metadata.
8. Created real Query-owned definitions and executed three authorized ClickHouse queries.
9. Verified deterministic equivalents of Revenue by month, Revenue by category, and Top products by revenue.
10. Passed returned shapes through Visualization and received compatible line/bar/bar selections.
11. Created Metabase cards and a dashboard, then obtained a tenant-owned embed path.
12. Exercised forecast eligibility without invoking an external model.
13. Saved and retrieved the report through the supported report path.
14. Proved tenant B could not retrieve tenant A's result.

The SQL was not mocked: it passed the real Query authorization, SQL guard, normalization, ClickHouse execution, and result-shape layers. Only optional model selection was made deterministic.

## Cleanup proof

All artifacts use the reserved `p0c_sales_` tag/prefix. Cleanup removed the disposable users, workspaces, tokens/sessions, dataset and ingestion records, ClickHouse table, Metabase cards/dashboard, visualization ownership, report state, uploads, and unified/legacy Surreal metadata. The dedicated `scripts/cleanup_p0c_test_artifacts.py` applies exact-prefix allowlisting and supports dry-run/proof modes; it never broad-deletes application data.

Before the final run, stale tagged rows from failed development attempts were removed only from the five scoped metadata tables: 10 connection, 5 schema, 5 extraction, 4 cleaning, and 4 loading rows. The post-cleanup proof returned zero tagged rows. Final signals were `P0C_E2E:PASS` and `P0C_E2E_CLEANUP:PASS`.
