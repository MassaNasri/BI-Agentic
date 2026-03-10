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
