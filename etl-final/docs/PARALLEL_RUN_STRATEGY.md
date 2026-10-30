> **SUPERSEDED RELEASE PLANNING — 2026-10-27.** This earlier plan remains technical/historical reference, not a January commitment or production certificate. BIAVORA_PRODUCTION_READINESS_AUDIT/43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md controls scope, dates and gates. The retained body must be revalidated before use; no new feature, Kubernetes requirement or cleanup is authorized by it.

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
