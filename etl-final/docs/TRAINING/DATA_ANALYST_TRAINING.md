# Data Analyst Training Notes

## Understanding Quality Metrics

Quality metrics are stored in ClickHouse:
- `quality_metrics` (batch-level metrics)
- `quality_anomalies` (outlier detection)

Use metadata service endpoint:
- `GET /quality/trends/` for daily aggregates

## Quarantine Workflow

1. Review quarantined rows:
   - `GET /quarantine/?limit=...&offset=...`
2. Prepare updated rules or schema contract.
3. Reprocess quarantined rows:
   - `POST /quarantine/reprocess/` with `ids` and optional `rules_path` / `schema_contract`

## Lineage

Lineage is queryable via:
- `GET /lineage/{row_id}/`

Use lineage to trace data issues back to sources or to verify transformation rule application.
