> **SUPERSEDED RELEASE PLANNING — 2026-10-27.** This earlier plan remains technical/historical reference, not a January commitment or production certificate. BIAVORA_PRODUCTION_READINESS_AUDIT/43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md controls scope, dates and gates. The retained body must be revalidated before use; no new feature, Kubernetes requirement or cleanup is authorized by it.

# Phase 7 Migration Checklist

This checklist is non-destructive and preserves existing data flows.

## Pre-Migration
- [ ] Freeze schema contract changes (tag rules + schema versions).
- [ ] Confirm ClickHouse backups and SurrealDB backups completed.
- [ ] Confirm Kafka retention is sufficient for parallel runs.
- [ ] Verify ClickHouse has capacity for duplicate (old + new) writes.
- [ ] Ensure `STATELESS_MODE=true` in production.
- [ ] Verify `deduplication_log`, `quarantine`, `quality_metrics` tables exist.
- [ ] Validate health endpoints for all services.
- [ ] Validate Prometheus metrics scraping.

## Parallel Run Preparation
- [ ] Ensure new pipeline topics are ready (same topics used, but parallelized by consumer groups).
- [ ] Configure new service deployments with distinct consumer group IDs if needed.
- [ ] Confirm extractor/transformer/loader batch sizes and backpressure settings.
- [ ] Enable lineage + correlation IDs for traceability.

## Migration Execution
- [ ] Run staging migration first (see `docs/ROLLOUT_PLAN.md`).
- [ ] Execute data migration scripts (see `migration/`).
- [ ] Reprocess migrated data through new pipeline.
- [ ] Validate row counts and sample checks.

## Validation
- [ ] Row count reconciliation (old vs new tables).
- [ ] Spot-check data quality for key sources.
- [ ] Verify quarantine volume is within expected bounds.
- [ ] Validate lineage query returns expected graph for sample rows.

## Cutover
- [ ] Promote new pipeline to primary.
- [ ] Keep old pipeline in read-only for a validation window.
- [ ] Start monitoring runbooks for regression.
