# Operations Training Notes

## Monitoring

Key endpoints:
- `/health/` on most services (HTTP ports 8001–8006)
- `/metrics/` on most services (HTTP)
- Listener metrics ports: 9101–9103

Key metrics:
- `ROWS_PROCESSED`
- `ERRORS_TOTAL`
- `PROCESS_LATENCY`

## Scaling

- Scale via Kubernetes manifests (`etl-infra/k8s/`).
- Set `KAFKA_CONSUMER_PARALLELISM` per service for parallel consumption.
- HPAs are defined for core services.

## Failure Handling

- Loader has circuit breaker and retry/backoff.
- Quarantine captures invalid rows; never drop silently.

## Common Operations

- Validate Kafka connectivity.
- Validate ClickHouse availability.
- Inspect SurrealDB for logs and lineage.
- Use metadata service endpoints for lineage and quality trends.
