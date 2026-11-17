# Foundation-D / D6-R2 release candidate and remote CI report

## Executive Status

**Foundation-D: LOCAL READY. G-D: BLOCKED pending exact-SHA remote CI. Production Readiness: NO-GO.** This is the release candidate review record. Report [63](63_FOUNDATION_D_D6_BROKER_RECOVERY_AND_LOCAL_CLOSURE_REPORT.md) is the authoritative local acceptance result. Report [62](62_FOUNDATION_D_FINAL_ACCEPTANCE_AND_RELEASE_REPORT.md) retains historical failures and is not reclassified.

## D6-R2 Scope

Review the accumulated first-party Foundation-A/B/C/D working tree, freeze the accepted D6-R1 candidate, stage exact release paths, run pre-commit checks, commit, push without rewriting history, and require the canonical nine-job remote workflow for the exact SHA. No Semantic Layer or deployment work is included.

## Entry Repository State

Branch `foundation-c-staging`, tracking `origin/foundation-c-staging` at `ca4547eb683bab21dbcbb8dab6cb1d18453632fa`. The index was empty. `git status --short --branch`, `git rev-parse HEAD`, `git diff --stat`, `git diff --cached --stat`, `git submodule status`, and `git ls-files --others --exclude-standard` were recorded before staging. There were 34 modified tracked paths, 102 untracked first-party release paths, one disposable SQLite database, and the pre-existing dirty TimesFM marker. The pinned TimesFM gitlink was `d720daa6786539c2566a44464fbda1019c0a82c0`.

## Release Inventory

Every path in the entry-state inventory below has exactly one disposition. The pattern rows are exhaustive for the listed changed paths; the raw entry listing is retained in the appendix for exact path verification.

| Disposition | Entry paths | Reason |
| --- | --- | --- |
| A: required implementation | `bi_platform_shared/cdc_*.py`; `etl-final/shared/cdc/**`; `etl-final/tests/test_cdc_*.py`; changed and new `services/query-service/database/**`, `integration/**`, `query_api/**`, `service_config/urls.py`, `tests/test_*.py` | CDC contracts, control and data planes, migrations, authorized Query, regression tests |
| B: required infrastructure | `.github/workflows/p0c-release-gate.yml`; `docker-compose.cdc-local.yml`; all added `scripts/*foundation_d*`, `scripts/scan_foundation_d6_first_party.py`, and `scripts/verify_foundation_d_migration.py` | Canonical workflow and reproducible acceptance/migration/security tooling |
| C: required canonical documentation | changed `BIAVORA_PRODUCTION_READINESS_AUDIT/{20,22,23,25,26,29,30,31,33,34,43,45}_*.md`; added reports `50` through `64`; `FOUNDATION_D_RESULTS.json`; `docs/remediation/FOUNDATION_D_CDC_RUNBOOK.md` | Current status, traceability, historical evidence and operator runbook |
| D: required prior Foundation-C dependency | `scripts/foundation_c4_owner_schemas.py`, `scripts/run_security_regression.py`, `scripts/verify_release_workflow.py` | Owner schema, isolated security matrix, and exact nine-job release contract needed by this candidate |
| E: external/local evidence | `services/query-service/query-foundation-a-test.sqlite3`; sibling validation JSON, scans, fixture env files; Docker state | Disposable/local evidence; never stage |
| F: unrelated user work | None identified among first-party changed paths | No unrelated release file staged |
| G: TimesFM | `services/ai-service/forecasting/timesfm` | Pre-existing dirty submodule; never enter, modify, or stage |

## Included First-Party Files

All A-D paths above are intended for the release commit. The exact staged path list and count are recorded in the appendix after staging. The prior Foundation-C three-script and workflow changes are dependencies of the release gate, not unrelated user edits.

## Excluded Local / Evidence Files

The disposable SQLite database and all external validation, fixture credentials, Docker volumes, scan archives, and secret-bearing JSON stay outside the index. The first-party scanner intentionally excludes TimesFM, local `.env` files and disposable database suffixes.

## Unrelated Work Preserved

No unrelated first-party path was identified. The excluded SQLite database and dirty TimesFM marker remain untouched. The working tree need not be clean after the commit.

## TimesFM Confirmation

The gitlink is pinned to `d720daa6786539c2566a44464fbda1019c0a82c0`; D6-R2 does not change it. A remote workflow may initialize that pinned commit for its own tests without changing the repository pointer.

## Dependency Closure Review

The new shared CDC contracts are included with Query and worker imports. Integration migrations 0005-0011 and Database migration 0007 are included in order. The local Compose fixture references the included CDC Dockerfile and existing service Dockerfiles. The release workflow references included static, security and migration scripts; its Foundation-D ETL and image build steps refer to included tests and Dockerfile. Historical reports may reference external disposable evidence by location, which is not a runtime dependency.

## Test-Only Hook Audit

`connect.configuration` rejects fixture gate tokens outside `APP_ENV=test` and rejects production transport. Its fixed snapshot SQL override is limited to the isolated `public.orders` generation-2 fixture and a server-derived scope. Reconciliation's advisory gate requires test mode, exact scope and fixture source. Worker crash injection executes only in test mode and cannot be selected from a public request. Worker execution refuses environments other than test/development. The local certificate issuer is limited to test or explicit development, and production cutover requires the real watermark certificate. Query CDC endpoints require `CDC_ENABLED=1`, reject production CDC transport, derive workspace/source authority on the server, and require an operator secret for reseed. `cutover_candidate(..., fault=...)` is an internal test parameter, not an HTTP parameter. No hook accepts arbitrary caller SQL or bypasses Query authority.

## Configuration Audit

`CDC_ENABLED` is opt-in. The isolated Compose file uses `APP_ENV=test`, loopback-bound host ports for PostgreSQL, ClickHouse and Query, private Connect REST, externally supplied fixture secrets, `wal_level=logical`, pinned infrastructure images, and `CONNECT_SCHEDULED_REBALANCE_MAX_DELAY_MS=10000`. Kafka transport in this fixture is plaintext and single broker; this setting is local recovery evidence, not production transport certification. Production CDC transport fails closed. CAP-14 must separately prove TLS, ACL, identities, managed secrets, hosted WAL and deployment operations.

## Secret Scan Before Staging

Pinned first-party gitleaks scan: **PASS**, 5,843 files scanned, zero findings, TimesFM excluded (`biavora-foundation-d6-r2-prestage-scan-elevated/summary.json`, outside the repository). Changed-file credential review found no committed fixture env file, private key, live DSN, or operator secret value. Test-only identifiers are synthetic. No secret values are printed in this report.

## Intentional Staging

**PASS.** Staged in four explicit groups: workflow/Compose (2), implementation (52), scripts including three prior Foundation-C dependencies (53), and documentation/results/runbook (30). The index contains 137 reviewed files. After each group, the cached stat and short status were inspected. `git add .` was not used. The disposable SQLite database and TimesFM remained unstaged.

## Full Staged Diff Review

**PASS for the frozen local candidate.** The complete staged patch was exported to external `biavora-foundation-d6-r2-staged.diff` for path-by-path review; high-risk production and workflow hunks were inspected directly. The Query public route and internal callback were checked for server-derived authority; source disable/retire/revoke now stops CDC intent. Dataset publication is Loader-only; the Query SQL guard blocks `_cdc_` technical columns. Integration migrations 0005-0011 and Dataset 0007 align with the model and owner schema. The worker has bounded 100-event batches, retained offset semantics (`auto_offset_reset='none'`), test-only crash hooks and explicit production refusal. The Connect rebalance value is 10,000 ms in the local fixture with no host REST port. The workflow retains all nine mandatory prerequisite jobs, six native security environments and the release aggregator. No staged `.env`, disposable DB, external fixture, generated secret report or TimesFM path appears. `git diff --cached --check` passed.

## Migration / Static Checks

Python/static compile passed 883 maintained files; the workflow verifier passed nine mandatory jobs and six security environments; `git diff --cached --check` passed. Both canonical and CDC fixture `docker compose config --quiet` passed. The eight-service model drift gate returned “No changes detected” for every service (with local database-history connection warnings for services whose default `host.docker.internal:5432` was unavailable). A fresh disposable PostgreSQL database passed Foundation-C and Foundation-D Integration 0005-0011 plus Query Dataset 0007 forward/reverse/reapply. A separate template0 disposable database passed owner-role CRUD, foreign-write denial and rollback. The staged-aware documentation checker reviewed 29 Markdown files and reported only the two historical report-50 table-width findings at lines 131-132; no new release-content error. The frontend files did not change after report 63's 19 tests, ESLint, production build and bundle verification pass. Pinned gitleaks scanned 5,844 first-party files after staging with zero findings and TimesFM excluded (`biavora-foundation-d6-r2-staged-scan/summary.json`, external).

## Frozen Candidate Manifest

**Implementation freeze declared after the pre-staging scan; no production/runtime code changed after report 63.** Branch `foundation-c-staging`; exact 137 staged paths are listed below. Worker image `sha256:d7218fa055614e73134fcf7c86bbe81d98916189934fbf3d957c342b2e54b0b3`. PostgreSQL `sha256:7e32e9833a6fb1c92c32552794cb6ed569d51b445a54907d35fc112ef39684db`; Debezium `sha256:4f807bd409b47268077e1142524f368db170560d5caceaee48a6a7a7fd288570`; Kafka `sha256:fbbb6fa11b258a88b83f54d4f0bddfcffbf2279f99d66a843486e3da7bdfbf41`; ClickHouse `sha256:0b2d7824347397b2ba6fcb216f0ae772568105f1f47e19f0d3247e24c79bc10a`. Report 63 accepted 1,803 passes, zero failures, 17 skips; fresh 5,000-row runs 53.594/45.719 s (<300); broker recovery 19.469/17.672 s and supplemental post-fix long outage 32.579 s (<120); two real watermark MATCH/cutovers. Both pre-staging and staged first-party gitleaks scans found zero secrets. Migration and owner checks passed; frontend's accepted pass remains valid.

## Commit Evidence

Pending reviewed commit.

## Post-Commit Tree State

Pending. Expected exclusions are the pre-existing TimesFM dirty marker and disposable SQLite database.

## Push Evidence

Pending normal push to `origin/foundation-c-staging`; no force push.

## Remote Workflow

Canonical `.github/workflows/p0c-release-gate.yml` (`P0-C release gate`) supports `pull_request` and `workflow_dispatch`. Existing open PR #1 has head `foundation-c-staging` and base `main`, so the normal push triggers the complete workflow. Run ID, URL, SHA, timing and conclusion pending.

## Remote Exact-SHA Verification

Pending comparison of accepted commit, remote branch head and workflow `head_sha`.

## Nine-Job CI Matrix

Required prerequisite jobs: `current-tree-secret-scan`, `static-and-compose`, `frontend`, `backend-and-ai`, `etl`, `security-regression` (six service environments), `migration-drift`, `docker-build`, `foundation-c-owner-boundary`. The always-running `release-gate` aggregator must also succeed. Remote per-job status, conclusion, duration and failures pending.

## Remote Security Results

Pending actual `current-tree-secret-scan`, all six `security-regression` matrix environments, and owner-boundary job; no skipped or continue-on-error substitutes accepted.

## CI Failure / Retry History

None yet. Any repository defect requires a new commit and affected local revalidation; an older SHA's workflow cannot close G-D.

## Final D1-D6 Acceptance Matrix

| Gate | Local status | Evidence | Remote SHA |
| --- | --- | --- | --- |
| D1 lifecycle, authorization, binding | READY | Report 51 | Pending |
| D2 capture and control | READY | Reports 52-53 | Pending |
| D3 envelope, replay, poison | READY | Report 54 | Pending |
| D4 current state and Query | READY | Report 55 | Pending |
| D5 generation, reseed, reconciliation, recovery | READY | Reports 56-61 | Pending |
| D6 local performance, recovery, security, regression | LOCAL READY | Reports 62-63, `FOUNDATION_D_RESULTS.json` | Pending |
| D6 remote canonical workflow | BLOCKED | Exact nine-job run pending | Pending |

## G-D Decision

**BLOCKED** until the exact accepted SHA passes the complete canonical remote workflow, including all nine mandatory prerequisites and the release aggregator.

## Foundation-D Decision

**LOCAL READY**, pending remote G-D closure.

## Production Readiness Status

**NO-GO.** Foundation-D local closure or future G-D GREEN cannot certify production deployment.

## Remaining CAP-14 Work

Hosted TLS verify-full, Kafka ACL/TLS, workload identities, managed secrets/KMS, Java/JDBC DNS and reconnect, hosted WAL/slot operations, staging, backup/restore, capacity, rollback and cutover certification remain independently required.

## Final Git / Repository State

Pending commit, push and remote exact-SHA verification. This report is an accurate pre-CI status record for the release candidate; post-CI evidence may be recorded outside the candidate SHA to avoid a self-referential status commit.

## Entry Path Appendix

The exact entry inventory and final staged path list follow after review.

| Entry path | Disposition |
| --- | --- |
| `.github/workflows/p0c-release-gate.yml` | B |
| `bi_platform_shared/cdc_contract.py` | A |
| `bi_platform_shared/cdc_reconciliation.py` | A |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/20_TECHNICAL_DEBT_AND_PROBLEM_REGISTER.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/22_TARGET_ARCHITECTURE.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/23_FEATURE_READINESS_MATRIX.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/25_14_WEEK_IMPLEMENTATION_ROADMAP.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/26_MASTER_REFACTOR_BUILD_DELETE_PLAN.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/29_CANONICAL_PRODUCT_SCOPE.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/30_CANONICAL_ARCHITECTURE_RULES.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/31_CANONICAL_SERVICE_OWNERSHIP_MAP.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/33_PRODUCTION_SECURITY_BASELINE.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/34_BIAVORA_MASTER_CONTEXT_FOR_FUTURE_PROMPTS.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/50_FOUNDATION_D_CDC_ARCHITECTURE_AND_IMPLEMENTATION_PLAN.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/50_FOUNDATION_D_POSTGRESQL_CDC_IMPLEMENTATION_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/51_FOUNDATION_D_CDC_DOMAIN_AND_LIFECYCLE_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/52_FOUNDATION_D_POSTGRES_CAPTURE_AND_CONNECT_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/53_FOUNDATION_D_D2_CAPTURE_CONTROL_CLOSURE_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/54_FOUNDATION_D_CHANGE_ENVELOPE_AND_PROCESSING_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/55_FOUNDATION_D_CLICKHOUSE_CURRENT_STATE_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/56_FOUNDATION_D_RECOVERY_RESEED_AND_RECONCILIATION_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/57_FOUNDATION_D_D5_RESEED_AND_CUTOVER_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/58_FOUNDATION_D_D5_WATERMARK_RECONCILIATION_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/59_FOUNDATION_D_D5_FINAL_OPERATIONAL_CLOSURE_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/60_FOUNDATION_D_D5_SNAPSHOT_AND_RECONCILIATION_CLOSURE_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/61_FOUNDATION_D_D5_RUNTIME_RECOVERY_AND_FINAL_CLOSURE_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/62_FOUNDATION_D_FINAL_ACCEPTANCE_AND_RELEASE_REPORT.md` | C |
| `BIAVORA_PRODUCTION_READINESS_AUDIT/63_FOUNDATION_D_D6_BROKER_RECOVERY_AND_LOCAL_CLOSURE_REPORT.md` | C |
| `docker-compose.cdc-local.yml` | B |
| `docs/remediation/FOUNDATION_D_CDC_RUNBOOK.md` | C |
| `etl-final/shared/cdc/__init__.py` | A |
| `etl-final/shared/cdc/clickhouse.py` | A |
| `etl-final/shared/cdc/connect.py` | A |
| `etl-final/shared/cdc/Dockerfile` | A |
| `etl-final/shared/cdc/health.py` | A |
| `etl-final/shared/cdc/postgres.py` | A |
| `etl-final/shared/cdc/reconciliation.py` | A |
| `etl-final/shared/cdc/requirements.txt` | A |
| `etl-final/shared/cdc/schema.py` | A |
| `etl-final/shared/cdc/worker.py` | A |
| `etl-final/tests/test_cdc_capture_preflight.py` | A |
| `etl-final/tests/test_cdc_clickhouse.py` | A |
| `etl-final/tests/test_cdc_contract.py` | A |
| `etl-final/tests/test_cdc_offsets.py` | A |
| `etl-final/tests/test_cdc_processing.py` | A |
| `etl-final/tests/test_cdc_reconciliation.py` | A |
| `FOUNDATION_D_RESULTS.json` | C |
| `scripts/bootstrap_foundation_d6_single.py` | B |
| `scripts/diagnose_foundation_d5_r4b_failed_stop.py` | B |
| `scripts/diagnose_foundation_d6_broker.py` | B |
| `scripts/foundation_c4_owner_schemas.py` | D |
| `scripts/foundation_d_kafka_probe.py` | B |
| `scripts/foundation_d4_kafka_probe.py` | B |
| `scripts/foundation_d4_store_probe.py` | B |
| `scripts/foundation_d6_event_audit.py` | B |
| `scripts/foundation_d6_r1_telemetry.py` | B |
| `scripts/foundation_d6_stage_probe.py` | B |
| `scripts/foundation_d6_wait_raw.py` | B |
| `scripts/run_foundation_d5_r4b_orphans.ps1` | B |
| `scripts/run_foundation_d5_r4b_reconciliation.ps1` | B |
| `scripts/run_foundation_d5_r4b_restart.ps1` | B |
| `scripts/run_security_regression.py` | D |
| `scripts/scan_foundation_d6_first_party.py` | B |
| `scripts/verify_foundation_d_cdc.py` | B |
| `scripts/verify_foundation_d_migration.py` | B |
| `scripts/verify_foundation_d1_concurrency.py` | B |
| `scripts/verify_foundation_d4.py` | B |
| `scripts/verify_foundation_d5.py` | B |
| `scripts/verify_foundation_d5_r1.py` | B |
| `scripts/verify_foundation_d5_r1_fence.py` | B |
| `scripts/verify_foundation_d5_r2.py` | B |
| `scripts/verify_foundation_d5_r3.py` | B |
| `scripts/verify_foundation_d5_r4a.py` | B |
| `scripts/verify_foundation_d5_r4a_benchmark.py` | B |
| `scripts/verify_foundation_d5_r4a_diagnose.py` | B |
| `scripts/verify_foundation_d5_r4a_mutation.py` | B |
| `scripts/verify_foundation_d5_r4a_remaining.py` | B |
| `scripts/verify_foundation_d5_r4a_schema.py` | B |
| `scripts/verify_foundation_d5_r4b.py` | B |
| `scripts/verify_foundation_d5_r4b_certificates.py` | B |
| `scripts/verify_foundation_d5_r4b_fence.py` | B |
| `scripts/verify_foundation_d5_r4b_kafka_secrets.py` | B |
| `scripts/verify_foundation_d5_r4b_loader_apply.py` | B |
| `scripts/verify_foundation_d5_r4b_mismatch.py` | B |
| `scripts/verify_foundation_d5_r4b_orphans.py` | B |
| `scripts/verify_foundation_d5_r4b_schema_placement.py` | B |
| `scripts/verify_foundation_d5_r4b_secret_scan.py` | B |
| `scripts/verify_foundation_d5_r4b_security.py` | B |
| `scripts/verify_foundation_d6_baseline.py` | B |
| `scripts/verify_foundation_d6_baseline_resume.py` | B |
| `scripts/verify_foundation_d6_broker_recovery.py` | B |
| `scripts/verify_foundation_d6_event_audit.py` | B |
| `scripts/verify_foundation_d6_r1_broker.py` | B |
| `scripts/verify_foundation_d6_r1_live_restarts.py` | B |
| `scripts/verify_foundation_d6_r1_pause_resume.py` | B |
| `scripts/verify_foundation_d6_r1_rotation.py` | B |
| `scripts/verify_foundation_d6_r1_security.py` | B |
| `scripts/verify_foundation_d6_reconciliation.py` | B |
| `scripts/verify_foundation_d6_state.py` | B |
| `scripts/verify_release_workflow.py` | D |
| `services/query-service/database/cdc.py` | A |
| `services/query-service/database/cdc_reconciliation.py` | A |
| `services/query-service/database/migrations/0007_database_cdc_generation.py` | A |
| `services/query-service/database/models.py` | A |
| `services/query-service/database/test_cdc_physical.py` | A |
| `services/query-service/database/test_cdc_query_guard.py` | A |
| `services/query-service/database/urls.py` | A |
| `services/query-service/database/views.py` | A |
| `services/query-service/integration/cdc.py` | A |
| `services/query-service/integration/cdc_lifecycle.py` | A |
| `services/query-service/integration/cdc_reseed.py` | A |
| `services/query-service/integration/credentials.py` | A |
| `services/query-service/integration/limits.py` | A |
| `services/query-service/integration/migrations/0005_cdcpipeline_cdcaudit_and_more.py` | A |
| `services/query-service/integration/migrations/0006_cdcaudit_dataset_id_cdcaudit_new_desired_state_and_more.py` | A |
| `services/query-service/integration/migrations/0007_cdc_generation.py` | A |
| `services/query-service/integration/migrations/0008_cdc_controller_lease.py` | A |
| `services/query-service/integration/migrations/0009_cdc_snapshot_signal.py` | A |
| `services/query-service/integration/migrations/0010_cdc_candidate_cutover.py` | A |
| `services/query-service/integration/migrations/0011_cdc_capture_and_reconciliation_attempt.py` | A |
| `services/query-service/integration/models.py` | A |
| `services/query-service/integration/service.py` | A |
| `services/query-service/integration/test_cdc.py` | A |
| `services/query-service/integration/test_public_boundary.py` | A |
| `services/query-service/integration/tests.py` | A |
| `services/query-service/integration/views.py` | A |
| `services/query-service/query_api/application/query_execution.py` | A |
| `services/query-service/query_api/services/clickhouse_executor.py` | A |
| `services/query-service/query_api/services/workspace_db_resolver.py` | A |
| `services/query-service/query-foundation-a-test.sqlite3` | E |
| `services/query-service/service_config/urls.py` | A |
| `services/query-service/tests/test_clickhouse_executor.py` | A |
| `services/query-service/tests/test_ingestion_callback_security.py` | A |
| `services/query-service/tests/test_query_execution_contract.py` | A |
| `services/query-service/tests/test_query_security_boundary.py` | A |
| `services/ai-service/forecasting/timesfm` (dirty submodule marker) | G |

## Frozen Staged Path Manifest

Exact reviewed index paths before commit (137):

```text
.github/workflows/p0c-release-gate.yml
BIAVORA_PRODUCTION_READINESS_AUDIT/20_TECHNICAL_DEBT_AND_PROBLEM_REGISTER.md
BIAVORA_PRODUCTION_READINESS_AUDIT/22_TARGET_ARCHITECTURE.md
BIAVORA_PRODUCTION_READINESS_AUDIT/23_FEATURE_READINESS_MATRIX.md
BIAVORA_PRODUCTION_READINESS_AUDIT/25_14_WEEK_IMPLEMENTATION_ROADMAP.md
BIAVORA_PRODUCTION_READINESS_AUDIT/26_MASTER_REFACTOR_BUILD_DELETE_PLAN.md
BIAVORA_PRODUCTION_READINESS_AUDIT/29_CANONICAL_PRODUCT_SCOPE.md
BIAVORA_PRODUCTION_READINESS_AUDIT/30_CANONICAL_ARCHITECTURE_RULES.md
BIAVORA_PRODUCTION_READINESS_AUDIT/31_CANONICAL_SERVICE_OWNERSHIP_MAP.md
BIAVORA_PRODUCTION_READINESS_AUDIT/33_PRODUCTION_SECURITY_BASELINE.md
BIAVORA_PRODUCTION_READINESS_AUDIT/34_BIAVORA_MASTER_CONTEXT_FOR_FUTURE_PROMPTS.md
BIAVORA_PRODUCTION_READINESS_AUDIT/43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md
BIAVORA_PRODUCTION_READINESS_AUDIT/45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md
BIAVORA_PRODUCTION_READINESS_AUDIT/50_FOUNDATION_D_CDC_ARCHITECTURE_AND_IMPLEMENTATION_PLAN.md
BIAVORA_PRODUCTION_READINESS_AUDIT/50_FOUNDATION_D_POSTGRESQL_CDC_IMPLEMENTATION_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/51_FOUNDATION_D_CDC_DOMAIN_AND_LIFECYCLE_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/52_FOUNDATION_D_POSTGRES_CAPTURE_AND_CONNECT_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/53_FOUNDATION_D_D2_CAPTURE_CONTROL_CLOSURE_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/54_FOUNDATION_D_CHANGE_ENVELOPE_AND_PROCESSING_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/55_FOUNDATION_D_CLICKHOUSE_CURRENT_STATE_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/56_FOUNDATION_D_RECOVERY_RESEED_AND_RECONCILIATION_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/57_FOUNDATION_D_D5_RESEED_AND_CUTOVER_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/58_FOUNDATION_D_D5_WATERMARK_RECONCILIATION_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/59_FOUNDATION_D_D5_FINAL_OPERATIONAL_CLOSURE_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/60_FOUNDATION_D_D5_SNAPSHOT_AND_RECONCILIATION_CLOSURE_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/61_FOUNDATION_D_D5_RUNTIME_RECOVERY_AND_FINAL_CLOSURE_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/62_FOUNDATION_D_FINAL_ACCEPTANCE_AND_RELEASE_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/63_FOUNDATION_D_D6_BROKER_RECOVERY_AND_LOCAL_CLOSURE_REPORT.md
BIAVORA_PRODUCTION_READINESS_AUDIT/64_FOUNDATION_D_GD_RELEASE_AND_REMOTE_CI_REPORT.md
FOUNDATION_D_RESULTS.json
bi_platform_shared/cdc_contract.py
bi_platform_shared/cdc_reconciliation.py
docker-compose.cdc-local.yml
docs/remediation/FOUNDATION_D_CDC_RUNBOOK.md
etl-final/shared/cdc/Dockerfile
etl-final/shared/cdc/__init__.py
etl-final/shared/cdc/clickhouse.py
etl-final/shared/cdc/connect.py
etl-final/shared/cdc/health.py
etl-final/shared/cdc/postgres.py
etl-final/shared/cdc/reconciliation.py
etl-final/shared/cdc/requirements.txt
etl-final/shared/cdc/schema.py
etl-final/shared/cdc/worker.py
etl-final/tests/test_cdc_capture_preflight.py
etl-final/tests/test_cdc_clickhouse.py
etl-final/tests/test_cdc_contract.py
etl-final/tests/test_cdc_offsets.py
etl-final/tests/test_cdc_processing.py
etl-final/tests/test_cdc_reconciliation.py
scripts/bootstrap_foundation_d6_single.py
scripts/diagnose_foundation_d5_r4b_failed_stop.py
scripts/diagnose_foundation_d6_broker.py
scripts/foundation_c4_owner_schemas.py
scripts/foundation_d4_kafka_probe.py
scripts/foundation_d4_store_probe.py
scripts/foundation_d6_event_audit.py
scripts/foundation_d6_r1_telemetry.py
scripts/foundation_d6_stage_probe.py
scripts/foundation_d6_wait_raw.py
scripts/foundation_d_kafka_probe.py
scripts/run_foundation_d5_r4b_orphans.ps1
scripts/run_foundation_d5_r4b_reconciliation.ps1
scripts/run_foundation_d5_r4b_restart.ps1
scripts/run_security_regression.py
scripts/scan_foundation_d6_first_party.py
scripts/verify_foundation_d1_concurrency.py
scripts/verify_foundation_d4.py
scripts/verify_foundation_d5.py
scripts/verify_foundation_d5_r1.py
scripts/verify_foundation_d5_r1_fence.py
scripts/verify_foundation_d5_r2.py
scripts/verify_foundation_d5_r3.py
scripts/verify_foundation_d5_r4a.py
scripts/verify_foundation_d5_r4a_benchmark.py
scripts/verify_foundation_d5_r4a_diagnose.py
scripts/verify_foundation_d5_r4a_mutation.py
scripts/verify_foundation_d5_r4a_remaining.py
scripts/verify_foundation_d5_r4a_schema.py
scripts/verify_foundation_d5_r4b.py
scripts/verify_foundation_d5_r4b_certificates.py
scripts/verify_foundation_d5_r4b_fence.py
scripts/verify_foundation_d5_r4b_kafka_secrets.py
scripts/verify_foundation_d5_r4b_loader_apply.py
scripts/verify_foundation_d5_r4b_mismatch.py
scripts/verify_foundation_d5_r4b_orphans.py
scripts/verify_foundation_d5_r4b_schema_placement.py
scripts/verify_foundation_d5_r4b_secret_scan.py
scripts/verify_foundation_d5_r4b_security.py
scripts/verify_foundation_d6_baseline.py
scripts/verify_foundation_d6_baseline_resume.py
scripts/verify_foundation_d6_broker_recovery.py
scripts/verify_foundation_d6_event_audit.py
scripts/verify_foundation_d6_r1_broker.py
scripts/verify_foundation_d6_r1_live_restarts.py
scripts/verify_foundation_d6_r1_pause_resume.py
scripts/verify_foundation_d6_r1_rotation.py
scripts/verify_foundation_d6_r1_security.py
scripts/verify_foundation_d6_reconciliation.py
scripts/verify_foundation_d6_state.py
scripts/verify_foundation_d_cdc.py
scripts/verify_foundation_d_migration.py
scripts/verify_release_workflow.py
services/query-service/database/cdc.py
services/query-service/database/cdc_reconciliation.py
services/query-service/database/migrations/0007_database_cdc_generation.py
services/query-service/database/models.py
services/query-service/database/test_cdc_physical.py
services/query-service/database/test_cdc_query_guard.py
services/query-service/database/urls.py
services/query-service/database/views.py
services/query-service/integration/cdc.py
services/query-service/integration/cdc_lifecycle.py
services/query-service/integration/cdc_reseed.py
services/query-service/integration/credentials.py
services/query-service/integration/limits.py
services/query-service/integration/migrations/0005_cdcpipeline_cdcaudit_and_more.py
services/query-service/integration/migrations/0006_cdcaudit_dataset_id_cdcaudit_new_desired_state_and_more.py
services/query-service/integration/migrations/0007_cdc_generation.py
services/query-service/integration/migrations/0008_cdc_controller_lease.py
services/query-service/integration/migrations/0009_cdc_snapshot_signal.py
services/query-service/integration/migrations/0010_cdc_candidate_cutover.py
services/query-service/integration/migrations/0011_cdc_capture_and_reconciliation_attempt.py
services/query-service/integration/models.py
services/query-service/integration/service.py
services/query-service/integration/test_cdc.py
services/query-service/integration/test_public_boundary.py
services/query-service/integration/tests.py
services/query-service/integration/views.py
services/query-service/query_api/application/query_execution.py
services/query-service/query_api/services/clickhouse_executor.py
services/query-service/query_api/services/workspace_db_resolver.py
services/query-service/service_config/urls.py
services/query-service/tests/test_clickhouse_executor.py
services/query-service/tests/test_ingestion_callback_security.py
services/query-service/tests/test_query_execution_contract.py
services/query-service/tests/test_query_security_boundary.py
```
