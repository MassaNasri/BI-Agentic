# Developer Training Notes

## Architecture Overview

Key components:
- Connector: validates uploads and DB credentials.
- Extractor: batches rows, writes bronze, emits to Kafka.
- Transformer: deterministic rules, schema validation, quarantine.
- Loader: transactional-like ClickHouse load, retries, circuit breaker.
- Metadata: lineage and quality metrics query API.

## Design Principles

- Stateless services (enable `STATELESS_MODE` in production)
- Batch-first streaming for throughput
- Deterministic transformations
- Idempotency at every stage

## Code Locations

- Extraction strategies: `extractor-service/extractor/engine/*_extraction_strategy.py`
- Rules engine: `shared/models/rules_engine.py`
- YAML rules parser: `shared/models/rule_yaml_parser.py`
- Schema contracts: `shared/models/schema_contract.py`
- Transformer service: `transformer-service/transformer/engine/transformer_service.py`
- Loader logic: `loader-service/loader/engine/loader_logic.py`

## Local Development

- Use Docker Compose for Kafka and ClickHouse.
- Use `TRANSFORMER_RULES_PATH` to point to a local YAML rules file.
- Keep schema contracts versioned; include `schema_id` + `version`.

## Testing

Phase 5 tests are under `tests/phase5/`:
- load tests: `load_test_100k_rows.py`, `load_test_10m_rows.py`
- perf regression: `performance_regression_test.py`
- chaos and scale (K8s): `chaos_test_k8s.py`, `scalability_test_k8s.py`

## Do/Don’t

Do:
- Add new rules via YAML
- Keep transformations deterministic
- Keep hot paths free of excessive logging

Don’t:
- Introduce stateful globals
- Log PII or secrets
