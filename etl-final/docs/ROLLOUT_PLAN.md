> **SUPERSEDED RELEASE PLANNING — 2026-10-27.** This earlier plan remains technical/historical reference, not a January commitment or production certificate. BIAVORA_PRODUCTION_READINESS_AUDIT/43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md controls scope, dates and gates. The retained body must be revalidated before use; no new feature, Kubernetes requirement or cleanup is authorized by it.

# Rollout Plan (Staging → Production)

## Staging Deployment
1. Deploy new services to staging using `etl-infra/k8s/`.
2. Run smoke tests (see `migration/smoke_tests.py`).
3. Execute a 100k row load test.
4. Validate row counts and data integrity.

## Production Rollout (Controlled)
1. Enable parallel run for new pipeline consumers.
2. Monitor metrics, quarantine, and lineage.
3. Incrementally shift traffic or data sources to new pipeline.
4. If success criteria met, promote new pipeline to primary.

## Monitoring During Rollout
- Error rate and latency
- Kafka consumer lag
- ClickHouse load failures
- Quarantine rate changes
