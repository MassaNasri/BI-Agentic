# Parallel Pipeline Run Strategy

## Approach
Run the old and new pipelines concurrently to compare outputs without disrupting production.

## Mechanics
- Use separate consumer groups for the new pipeline so it can read the same Kafka topics without interfering.
- Configure new services in a separate namespace or deployment set.
- Write new pipeline outputs into distinct target tables (e.g., `silver_*_v2`), or use a dedicated database.

## Comparison
- Run periodic reconciliation on row counts and sampled data.
- Compare quality metrics and quarantine rates.
- Validate lineage integrity for a sample set of rows.

## Duration
Maintain parallel run for at least one full retention window or minimum 7 days.

## Exit Criteria
- All success criteria met.
- No severe regressions in quality or throughput.
