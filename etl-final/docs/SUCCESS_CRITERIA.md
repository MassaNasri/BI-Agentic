# Phase 7 Success Criteria

## Data Integrity
- Row count match within agreed threshold (default: 0.1%).
- No unexpected duplicates (deduplication_log stable).
- No missing batches (metadata and lineage coverage).

## Quality
- Quality score distributions within baseline tolerance.
- Quarantine rate within expected range.

## Performance
- Throughput meets or exceeds baseline.
- Latency within p95 targets.

## Operational Stability
- No sustained error spikes.
- Circuit breaker rarely triggered.
- Health endpoints consistently green.
