# Troubleshooting Guide

This guide lists common issues observed in the implemented system and their mitigations.

## 1. Kafka Consumer Lag Growing

Symptoms:
- Increasing lag on `extracted_rows_topic` or `clean_rows_topic`

Checks:
- Verify `KAFKA_CONSUMER_PARALLELISM` is set appropriately.
- Confirm cooperative rebalancing is enabled (`KAFKA_REBALANCE_STRATEGY=cooperative`).
- Check CPU usage on transformer/loader services.

Actions:
- Scale the consumer services horizontally.
- Increase `TRANSFORMER_BATCH_SIZE` or `LOADER_BATCH_SIZE`.

## 2. Loader Errors / ClickHouse Failures

Symptoms:
- Loader logs show repeated insert failures
- Circuit breaker opens

Checks:
- ClickHouse availability and credentials
- Disk space and I/O pressure
- Validate schema drift (new columns)

Actions:
- Verify ClickHouse is reachable and healthy.
- Temporarily reduce batch sizes.
- Check `LOADER_RETRIES`, `LOADER_BACKOFF_BASE`, `LOADER_MAX_BACKOFF`.

## 3. Quarantine Spike

Symptoms:
- Many rows appear in quarantine

Checks:
- Inspect schema contracts and rules configuration.
- Validate input data types for recent sources.

Actions:
- Use `GET /quarantine/` to inspect samples.
- Reprocess with updated rules via `POST /quarantine/reprocess/`.

## 4. Missing Quality Trends

Symptoms:
- `GET /quality/trends/` returns empty

Checks:
- ClickHouse table `quality_metrics` exists and has rows.
- Transformer listener is running and persisting metrics.

Actions:
- Ensure transformer service has ClickHouse access.
- Confirm ingestion is active and batches are being processed.

## 5. Unexpected Duplicates

Symptoms:
- Duplicate rows in ClickHouse tables

Checks:
- Verify idempotency checks are enabled in extractor/transformer.
- Confirm deduplication_log table exists.

Actions:
- Inspect `deduplication_log` entries.
- Validate `_dedup_key` generation in extractor/transformer.

## 6. API Endpoint Returns 404

Symptoms:
- API request fails with 404

Checks:
- Confirm service base URL and port.
- Confirm endpoint is supported (see `docs/API_OPENAPI.yaml`).

Actions:
- Route to correct service port.
- Ensure the service is running.

## 7. Metrics Endpoint Unavailable

Symptoms:
- `/metrics/` returns 404 or connection refused

Checks:
- Verify service exposes `/metrics/` in Django URLs.
- For listeners, verify metrics server ports (9101–9103).

Actions:
- Validate `*_METRICS_PORT` settings.
- Restart service with correct env configuration.
