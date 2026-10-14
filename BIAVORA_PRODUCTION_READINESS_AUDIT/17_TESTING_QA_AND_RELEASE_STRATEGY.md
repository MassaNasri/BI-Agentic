# 17 — Testing, QA and Release Strategy

> **v2 release rule:** The maintained test baseline is valuable but is not a production release gate by itself. Week-14 release additionally requires tenant-negative tests, provider/evaluation thresholds, CDC recovery/reconciliation, schema compatibility, payment/metering idempotency, upload abuse tests, dependency/image scanning, migration and rollback rehearsal, backup restore evidence, load/soak tests, alert drills, and signed deployment approval. AI evaluation begins Week 1 and expands with every feature.

## Executed baseline

The maintained command `scripts/test.ps1 -SkipFrontendInstall -SkipMigrations` was executed without changing source. Results:

- **PASS:** 1,464 Python/Node tests across 41 invocations.
- **PASS:** 17 additional Node subtests.
- **EXPECTED SKIP:** 17 integration tests whose external dependencies were unavailable.
- **PASS:** backend/ETL lint and compilation/static checks across 733 maintained Python files; no merge markers found.
- **PASS:** frontend 19-test suite and bundle policy.
- **PASS after environment escalation:** Vite production build. Initial run was blocked by sandbox access while scanning an ancestor directory; an approved external run passed. Main JavaScript chunk was 671.84 kB (194.57 kB gzip), with a >500 kB warning and stale browser-baseline-data warning.
- **PASS with limitation:** migration-drift commands for eight configured Django projects. Some emitted PostgreSQL connectivity warnings and relied on `--skip-checks`; unwired duplicate report models are outside installed-app coverage.
- **PASS:** `docker compose config --quiet`, aside from an environment warning reading the user's Docker client configuration.

Not run: live Compose end-to-end, paid/external model calls, payment provider flows, true database connectors, CDC, load/soak/chaos, browser E2E, backup restore and disaster recovery.

## Inventory and current quality

There are **140 tracked test files**: 103 under `etl-final`, 33 under services, three frontend test files, and one root-level test file. The suites are strongest around ETL connector contracts, security policy regressions, deterministic AI helpers and service units. Test quantity should not be mistaken for production coverage: external integration skips, heavy mocking, absent browser journeys and no persistent production-like environment leave the most important cross-service guarantees unproven.

Observed examples include 79 query tests, 63 visualization tests, 235 AI tests plus 12 subtests, and 20 voice tests plus five subtests. These are valuable regression assets and should be retained.

## Coverage gaps by layer

| Layer | Required additions |
|---|---|
| Unit | Authorization-policy edge cases, meter arithmetic, event upcasting, semantic formula validation, Arabic normalization |
| Contract | OpenAPI/event schema compatibility; provider/connector fixtures; webhook signatures; tool contracts |
| Integration | Real PostgreSQL/MySQL/MariaDB/ClickHouse/Kafka/Redis; object storage; source credential resolution; cross-tenant negative cases |
| E2E | Signup→workspace→source→snapshot→question→report→visualization; checkout/webhook; document/RAG; approval/action |
| Security | BOLA/IDOR matrix, same-DB table escape, SSRF/rebinding, SQL fuzzing, upload malware/polyglots, prompt/tool injection, dependency/container scan |
| Reliability | consumer crash/replay, duplicate/out-of-order event, poison/DLQ, provider timeout, partial service outage, webhook duplication |
| Performance | bounded query/result, concurrent AI jobs, large audio/documents, snapshot and CDC lag, gateway streaming/backpressure |
| Recovery | PostgreSQL/ClickHouse/object restore, semantic version rollback, Kafka offset recovery, tenant deletion proof |
| Frontend | component/accessibility/RTL tests, token expiry, error/loading states, responsive browser E2E |
| AI evaluation | versioned golden/adversarial/multilingual datasets and regression thresholds from report 08 |

## Test pyramid and environments

Keep fast deterministic unit tests on every change. Run contract and containerized component tests on pull requests for changed capabilities. Run a production-like multi-service acceptance environment before merge/release, with real brokers/datastores and synthetic secrets. Nightly suites should cover all connectors, model evaluations, security fuzzing and longer reliability scenarios. Weekly or release-candidate jobs should run load/soak, restore and controlled chaos.

Never depend on a developer workstation, `host.docker.internal`, Windows paths or an already-running local service. Seed each environment deterministically, allocate unique workspace/source IDs and clean by owned namespace. Marking a test integration does not justify silently skipping it at release time.

## Critical invariant suites

1. **Tenant isolation:** two workspaces share ClickHouse database but cannot discover/query each other's physical table through query, voice, reports, visualization, forecast, export or AI schema context.
2. **Usage correctness:** reserve→execute→commit/refund is atomic and idempotent under concurrent and retried calls.
3. **Ingestion correctness:** snapshot and CDC duplicate/reorder/crash/replay converge; deletes and schema changes are explicit; poison records quarantine and advance safely.
4. **Job recovery:** every stage survives worker death without double effects; cancellation and deadline propagation work.
5. **Trust:** every answer's SQL, semantic version, data freshness, source references and document citations resolve to the executed evidence.
6. **MCP approval:** no tool executes before a valid, unexpired, same-workspace approval; replay is idempotent and audited.

## Release pipeline

Recommended stages:

1. Format/lint/type/static compilation and generated-file drift.
2. Unit tests and deterministic AI fixtures.
3. Secret scanning (including history), SAST, dependency/license and IaC/container scans.
4. Contract/schema compatibility and migration expand/contract checks.
5. Containerized component/integration tests with required dependencies—no unexplained skips.
6. Browser E2E and multi-tenant security matrix.
7. AI evaluation regression with quality, safety, latency and cost budgets.
8. Build once; emit SBOM/provenance; sign immutable artifacts.
9. Staging migration/restore rehearsal, smoke and load/soak gate.
10. Progressive rollout with automated health/SLO checks and rollback.

Production deployment should promote the tested digest, not rebuild it.

## Exit criteria for public production

- Zero open BLOCKER/CRITICAL issues and explicit disposition of HIGH issues.
- No required integration or security suite skipped.
- Cross-tenant negative matrix passes on every externally reachable data path.
- CDC recovery/reconciliation and AI quality thresholds pass on versioned fixtures.
- Payment, quota and MCP tests prove signatures/approval/idempotency.
- Performance budgets and 24-hour staging soak meet measured SLOs without unbounded queues/memory.
- Restore and rollback exercises succeed with recorded RPO/RTO.
- Release evidence includes artifacts, migrations, SBOM, scan results, test/eval reports and operator runbooks.

