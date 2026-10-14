# Service communication audit

## Verdict

HTTP is appropriate for short control-plane queries and commands; Kafka is appropriate for row movement, domain facts, and CDC. BIAVORA's problem is not “HTTP versus events” but that one interactive request crosses too many synchronous boundaries, while emitted domain events are non-transactional and unused.

## HTTP dependency map

| Caller | Callee | Purpose | Timeout/retry behavior | Assessment |
|---|---|---|---|---|
| Browser | Gateway | All product APIs | Browser/Axios has no global timeout | Gateway buffering hides progress and cancellation |
| Gateway | Every service | Static reverse proxy | One integer timeout, default 360s; no retry/streaming/circuit | Latency and memory amplifier; 502 only |
| Report | Voice | Every report read/edit/page/widget route | connect 5/read 90; only widget GET retries once | Pure redundant hop |
| Voice | Workspace | Workspace/dataset context | Mixed raw clients | Necessary control lookup but cache/snapshot could reduce coupling |
| Voice | Subscription | Check and immediately consume quota | Synchronous, fail closed | Correct to fail closed, wrong charging lifecycle |
| Voice | AI | Whole voice/text pipeline | connect 10/read 300, one retry | Expensive non-idempotent request can duplicate work |
| Voice | Query | Execute and authorize SQL | 120s; local CH fallback on transport exception | **Unsafe fail-open** |
| Voice | Visualization | Question/dashboard/embed operations | 60–120s per call | Multi-step non-atomic saga inside request |
| Visualization | Query | Redeem short-lived query definition | Synchronous | Good anti-corruption/security direction |
| Visualization | Metabase | Question/dashboard/embed | Multiple calls/recovery attempts | Needs idempotency and durable workflow |
| Voice/workspace/subscription | Notification | Send event/email | Best effort, ignored failures | Acceptable only if durable event/outbox replaces direct call |
| Query | Connector | Test/discover/snapshot; includes source credential | Internal key, long source operations | Must become Integration control plane with secret reference |
| Metadata | Query | Failure callback | Internal key | Useful, but success/status model is incomplete |

## Critical synchronous chains

The worst chain is:

```text
client -> gateway -> voice -> AI/Dagster/Ollama/OpenRouter/Redis/ClickHouse schema
       -> voice -> query -> ClickHouse
       -> voice -> AI/TimesFM (optional)
       -> voice -> query-definition -> visualization -> query -> Metabase
       -> voice -> visualization dashboard/add/embed -> notification
```

Consequences:

- 360-second gateway occupancy and full response buffering;
- timeout layering without a single deadline budget;
- repeated authentication, serialization, and large JSON copies;
- ambiguous client retry after partial commit;
- report can be executed and persisted while visualization fails;
- quota is already consumed before AI success;
- Metabase objects can exist without matching final report state;
- retrying AI or dashboard calls can duplicate expensive work/objects;
- a readiness failure in an optional dependency can remove unrelated capabilities.

The correct target is a short command that creates a durable `analysis_job`, followed by worker steps with state transitions and an idempotency key. Status can be polled initially; SSE may be added later. Do not use Kafka for user queries requiring immediate authorization/response; use it for facts and background steps.

## Gateway findings

`gateway/views.py` forwards almost every incoming header, reads `request.body`, buffers the upstream response, and returns it wholesale. It cannot stream uploads, downloads, SSE, or WebSockets, and holds memory proportional to payloads. The size check relies on `Content-Length`; it is not a robust edge limit. The rate limiter stores timestamp deques by remote IP and path in one process, has no trusted-proxy logic, diverges across replicas, and never bounds the key map. Authentication only checks header presence; downstream verification is intentional but permits pointless traffic and inconsistent edge policy.

Use a production reverse proxy/API gateway for TLS, trusted client IP, distributed rate limits, body/stream limits, cancellation, access logs, and route timeouts. Keep application gateway logic only if it adds real policy.

## Kafka map

Canonical ETL topics are `load_requests`, `raw_data`, `transformed_data`, `metadata_updates`, `errors`, and `quarantine`. Legacy aliases remain enabled by default (`connection_topic`, `extracted_rows_topic`, `clean_rows_topic`, `metadata_topic`), while `load_rows_topic` remains a distinct legacy path. Producers request `acks=all`, idempotence, gzip, and max in-flight 1. Consumers use manual commit and rewind after processing failure.

Good foundations:

- scoped metadata contracts and schema validation;
- manual success-only offset commits;
- producer acknowledgement and bounded connect retry;
- explicit DLQ/quarantine paths;
- trace/correlation propagation helpers.

Risks:

1. Invalid messages `continue` before commit/DLQ, leaving a poison record to recur after restart/rebalance.
2. Every client may call topic initialization; application workers should not own broker control-plane provisioning.
3. No broker schema registry or compatibility policy; custom validation and legacy aliases allow drift.
4. Credentials, source rows, and DLQ rows can live in Kafka retention. Encryption uses one static derived key without key ID/version/rotation.
5. No transaction spans source read → event → CH write → metadata callback. At-least-once behavior is partially mitigated by dedupe but not an exactly-once guarantee.
6. `report.*` events are fire-and-forget after database writes, have no outbox, and no repository consumers were found.
7. Single broker, replication effectively one, ZooKeeper, plaintext listener, and no ACL/SASL/TLS constitute a development topology.

## Control/data/event plane rules

| Interaction | Recommended mechanism | Reason |
|---|---|---|
| Login, membership check, plan catalog, source test/discovery | REST with short deadline | Immediate command/query response |
| Submit analysis/report build | REST command → durable job | User needs ID immediately, work is long-running |
| Job progress/completion | State store + poll/SSE; optional event fanout | Durable truth plus UX updates |
| Snapshot/CDC records | Kafka, versioned envelopes | High-volume replayable data plane |
| Source/semantic model/report lifecycle facts | Transactional outbox → Kafka | Reliable cross-domain projection updates |
| Query execution | Query-service synchronous API or worker tool | Needs authoritative authorization and bounded result |
| Email/alerts | Domain event/outbox → notification consumer | Caller must not wait for SMTP |
| Payment | Provider hosted flow + webhook | Provider event is payment truth |
| MCP action | Approved command to isolated Tool Gateway | Idempotency/audit/policy required |

## Retry, circuit, timeout, and bulkhead policy

- Propagate an absolute request deadline, not independent maximums.
- Retry only idempotent reads or commands with an idempotency key; use exponential backoff and jitter.
- Never retry SQL writes/actions implicitly. Analytical SELECT may retry once only on classified transient connection failure and under the same dataset policy.
- Remove the voice local query fallback. A security owner outage must fail closed.
- Use separate worker pools/concurrency limits for Whisper, LLM, forecast, ingestion, Metabase, and external actions.
- Circuit breakers must be observable and shared enough to be meaningful; the existing process-local helper is insufficient across replicas.
- Readiness should include only dependencies required for that process's essential capability. Expose dependency degradation separately.

## Contract strategy

Define versioned REST/OpenAPI and event schemas in one contract package, with producer/consumer compatibility tests. Contracts must include request ID, workspace ID, actor, idempotency key, schema version, timestamp, and data classification where applicable. Credentials and raw PII must be explicitly prohibited from logs/events except in an encrypted, short-retention secret-delivery channel.
