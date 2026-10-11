# P0-C test and validation inventory

Inventory boundary: first-party automated tests plus first-party validation, startup, migration, reset, audit, shell, and PowerShell scripts. Source modules are not listed merely because they are Python/JavaScript. Glob rows are exhaustive for the stated directory; exceptions are named explicitly.

| Scope / exact selector | Files | Classification | Default gate | Reason / replacement contract |
|---|---:|---|---|---|
| `services/api-gateway/gateway/tests.py` | 1 | CANONICAL AUTOMATED | Yes | Two gateway readiness/auth-boundary tests added in P0-C. |
| `services/auth-service/users/tests_security_invitation.py` | 1 | CANONICAL AUTOMATED | Yes | Current P0-A invitation/authentication contract. |
| `services/workspace-service/workspace/tests_security_invitation.py` | 1 | CANONICAL AUTOMATED | Yes | Current P0-A membership/invitation contract. |
| `services/subscription-service/subscription/tests.py` | 1 | CANONICAL AUTOMATED | Yes | Three public-health, anonymous-denial, and valid authenticated-catalog tests. |
| `services/notification-service/notification/tests.py` | 1 | CANONICAL AUTOMATED | Yes | Four public-health, fail-closed key, denial, and valid internal-event tests. |
| `services/report-service/voice_reports/tests_sql_normalization.py` | 1 | CANONICAL AUTOMATED | Yes | Deterministic report SQL-boundary utility tests. |
| `services/voice-service/voice_reports/tests_*.py` | 4 | CANONICAL AUTOMATED | Yes | Current query, authorization, fallback, and AI-trace contracts. |
| `services/query-service/tests/test_*.py` | 13 | CANONICAL AUTOMATED | Yes | Current Query authorization, SQL, execution, metadata, shape, and ingestion contracts. |
| `services/visualization-service/visualization_api/tests/test_*.py` | 5 | CANONICAL AUTOMATED | Yes | Current visualization/query-reference/ownership contracts. |
| `services/ai-service/{tests,shared,intent_extraction,llm_app,reasoning_app,preprocessing_high,whisper_app}/test*.py` and `tests*.py` | 18 | CANONICAL AUTOMATED | Yes | Maintained deterministic AI behavior. Live provider calls are not permitted in the default gate. |
| `services/ai-service/forecasting/timesfm/**/tests/**` | 10 | EXTERNAL / VENDORED | No | Third-party TimesFM source and upstream tests; validated by its upstream package, not claimed as first-party. Product forecast adapter tests remain canonical. |
| `etl-final/shared/{models,utils,security}/test*.py` except the named diagnostics below | 35 | CANONICAL AUTOMATED | Yes | Shared ETL rules, schemas, identifiers, security, quality, idempotency, and broker adapters. Tests needing a live dependency must be marked integration and run in the integration stage, not silently skipped. |
| `etl-final/shared/models/test_import.py`, `test_import2.py` | 2 | OBSOLETE DIAGNOSTIC | No | Print/`exec` import experiments containing no assertions or test cases. Canonical package-import collection replaces them. |
| `etl-final/shared/models/test_file.txt` | 1 fixture | FIXTURE | No | UTF-16 rule-engine input fixture; not Python/doctest source. Explicit collection policy prevents accidental UTF-8 doctest parsing. |
| `etl-final/connector-service/connector/etl_engine/test*.py` and `tests.py` | 9 | CANONICAL AUTOMATED | Yes | Maintained Connector API, validation, scanner, rate-limit, and publish contracts. |
| `etl-final/connector-service/test_request_size_validation.py` | 1 | MANUAL VALIDATION | No | Standalone console validator; canonical request-size assertions live in `connector/etl_engine/test_request_size_limits*.py`. |
| `etl-final/connector-service/test_rate_limiting_standalone.py` | 1 | MANUAL VALIDATION | No | Standalone console/live-server validator; canonical automated contract lives in `connector/etl_engine/test_rate_limiting.py`. |
| `etl-final/connector-service/test_virus_scanning_demo.py` | 1 | DEMO / EXTERNAL-INTEGRATION | No | Demonstration requiring a scanner/live setup; canonical unit contract lives in `connector/etl_engine/test_virus_scanner.py`. |
| `etl-final/detector-service/detector/core/tests.py` | 1 | CANONICAL AUTOMATED | Yes | Four health, authentication, tenant-scope, and scope-publication tests. |
| `etl-final/extractor-service/extractor/engine/test*.py` and `tests.py` | 20 | CANONICAL AUTOMATED | Yes | Maintained extraction, checkpoint, pagination, lineage, and bronze-write contracts. |
| `etl-final/transformer-service/transformer/engine/test*.py` and `tests.py` | 7 | CANONICAL AUTOMATED | Yes | Maintained transformation, quarantine, schema, and rule contracts. |
| `etl-final/loader-service/loader/engine/test*.py` and `tests.py` | 3 | CANONICAL AUTOMATED | Yes | Maintained loading and silver-layer contracts. |
| `etl-final/metadata-service/metadata/api/tests.py` | 1 | CANONICAL AUTOMATED | Yes | Maintained scoped metadata API contract. |
| `etl-final/tests/test_p0_transform_loader_listeners.py` | 1 | CANONICAL AUTOMATED | Yes | P0 listener and service-identity regression contract. |
| `etl-final/Test-File/test_full_pipeline.py` | 1 | EXTERNAL-INTEGRATION | Dedicated E2E only | Live multi-service pipeline harness; superseded for release gating by the tagged P0-C disposable workflow while retained for operator use. |
| `etl-final/Test-File/test_quality_columns.py` | 1 | MANUAL VALIDATION | No | Operator/data-shape validator with external fixture assumptions. |
| `etl-final/Test-File/test_credential_encryption_integration.py` | 1 | EXTERNAL-INTEGRATION | Dedicated integration only | Exercises environment-backed credential encryption outside the offline unit boundary. |
| `etl-final/migration/test_migrate_bronze_to_new_tables.py` | 1 | MANUAL / DESTRUCTIVE MIGRATION | No | Data migration operator harness; not safe for an isolated unit run. Current schema/migration gates replace release-time execution. |
| `frontend/src/**/*.test.js` | 2 | CANONICAL AUTOMATED | Yes | Deterministic dashboard-grid and voice-error contracts. |
| `scripts/audit_*.py`, `scripts/finalize_phase0_audit.py`, `scripts/write_phase0_reports.py` | 9 | MANUAL / HISTORICAL AUDIT | No | Evidence-generation utilities for Phase 0; their generated audit artifacts are the record. |
| `scripts/reset_dev.py`, `scripts/reset-dev.ps1`, `scripts/reset_all_databases.sh`, `scripts/clear_*.sql` | 5 | MANUAL / DESTRUCTIVE | Never in CI | Exact reset procedures require explicit operator intent and are excluded from automated P0-C execution. |
| `scripts/run-migrations.ps1`, `scripts/run-migrations.sh` | 2 | CANONICAL OPERATIONAL | Migration gate | Serialized P0-B migration contract; first and second/no-work runs are mandatory. |
| `scripts/start-microservices.ps1`, `scripts/start_project.sh` | 2 | CANONICAL OPERATIONAL | Startup gate | Documented platform startup paths; PowerShell runs locally and POSIX is statically/syntax verified where native execution is unavailable. |
| `scripts/verify-p0b-two-tenant.ps1` | 1 | CANONICAL INTEGRATION | Yes | Live tenant-isolation regression gate. |
| `scripts/verify-runtime-config.ps1` | 1 | CANONICAL STATIC/SECURITY | Yes | P0-A runtime configuration assertions. |
| `scripts/repair-local-metabase-credentials.ps1` | 1 | MANUAL REPAIR | No | Explicit local repair operation, never an automatic release test. |
| ETL service `start.sh` files and `etl-infra/kafka/init.sh` | 7 | CANONICAL OPERATIONAL | Shell syntax + image/runtime gate | Runtime entrypoints, not unit tests. |
| TimesFM example/finetune shell scripts | 2 | EXTERNAL / VENDORED | No | Upstream examples requiring heavyweight model/dependency environments. |

## Canonical execution policy

The default offline gate comprises all rows marked **CANONICAL AUTOMATED**, frontend tests/lint/build, static correctness, migration drift, P0-A security, and deterministic health/readiness tests. Each Django project runs in its own process so `DJANGO_SETTINGS_MODULE`, application registries, and same-named modules cannot bleed across services. The ETL root is added once as an import root by the runner; individual test directories are not appended ad hoc.

## Final canonical automated suites

The counts below are the final runner results. Pytest/Django subtests are reported using each runner's own test count; the five Voice `subTest` cases are evidence but are not added again to the machine total.

| Component | Runner | Path / selector | Test count | Dependencies | Canonical? | CI? |
|---|---|---|---:|---|---|---|
| Shared HTTP | pytest | `tests/test_health_readiness.py` | 6 | Mocked dependency checks | Yes | Yes |
| API Gateway | Django test | `gateway` | 2 | Test settings | Yes | Yes |
| Query | pytest | `services/query-service/tests` | 60 | Mocked HTTP/ClickHouse unit boundaries | Yes | Yes |
| Visualization | pytest | `visualization_api/tests` | 63 | Mocked Query/Metabase unit boundaries | Yes | Yes |
| Voice | pytest | four `voice_reports/tests_*.py` selectors | 20 | Mocked owner services | Yes | Yes |
| Report | pytest | `voice_reports/tests_sql_normalization.py` | 5 | None | Yes | Yes |
| Auth | Django test | `users.tests_security_invitation` | 2 | Isolated test database | Yes | Yes |
| Workspace | Django test | `workspace.tests_security_invitation` | 4 | Isolated test database | Yes | Yes |
| Subscription | Django test | `subscription.tests` | 3 | In-memory SQLite | Yes | Yes |
| Notification | Django test | `notification.tests` | 4 | In-memory SQLite; local-memory email | Yes | Yes |
| AI deterministic | pytest | explicit 18-file selector in `scripts/test.*` | 230 | Provider boundaries mocked | Yes | Yes |
| ETL shared models/security | pytest | `shared/models`, `shared/security` | 330 | Offline/test secrets | Yes | Yes |
| ETL shared utilities | pytest | per-file maintained selector | 296 passed, 10 skipped | Live-only cases explicitly skipped | Yes | Yes |
| ETL Connector | Django test | `connector/etl_engine` | 131 | Mocked broker/scanner/DB contracts | Yes | Yes |
| ETL Extractor | pytest | `extractor/engine` | 218 passed, 5 skipped | Optional live integrations skipped | Yes | Yes |
| ETL Transformer | pytest | `transformer/engine` | 11 passed, 1 skipped | Optional live integration skipped | Yes | Yes |
| ETL Loader | pytest | `loader/engine` | 8 passed, 1 skipped | Optional live integration skipped | Yes | Yes |
| ETL listener contracts | pytest | `etl-final/tests/test_p0_transform_loader_listeners.py` | 6 | Adapter mocks | Yes | Yes |
| ETL Detector | Django test | `core.tests` | 4 | Adapter mocks | Yes | Yes |
| ETL Metadata | Django test | `api.tests` | 4 | Surreal adapter mocked | Yes | Yes |
| Frontend | Node test | `npm test` | 9 | Lockfile install | Yes | Yes |

Totals: **169 backend**, **230 AI**, **1,008 ETL**, and **9 frontend** tests passed; **17 ETL tests skipped with explicit live-integration reasons**. Machine total: **1,416 passed, 0 failed, 17 skipped, 0 collection errors**.

Manual, destructive, demo, external-integration, and vendored tests remain visible here rather than disappearing through broad ignore patterns. Their replacement or dedicated gate is named in the table. A failing canonical test cannot be relabeled “legacy” to make CI green.
