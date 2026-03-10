# Rollback Procedures

All rollback steps are designed to be non-destructive.

## Triggers for Rollback
- Sustained increase in error rate > baseline.
- Row count mismatch > agreed threshold.
- ClickHouse load failures with circuit breaker open.
- Unexpected data quality degradation.

## Rollback Steps (Safe)
1. Disable new pipeline consumers (scale deployments to 0).
2. Re-enable old pipeline consumers.
3. Stop new schema/rules deployment.
4. Preserve migrated data; do not drop any tables.
5. Record rollback decision and reason.

## Data Safety Guarantees
- No destructive table operations are required for rollback.
- All migration writes are additive.
- Data reconciliation scripts are read-only.

## Post-Rollback Actions
- Capture metrics and logs to diagnose regression.
- Compare lineage/quality metrics for a sample batch.
- Prepare patch and re-run staging validation.
