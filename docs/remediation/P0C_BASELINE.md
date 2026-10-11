# P0-C starting baseline

Captured before any P0-C implementation change on 2026-09-30 (Asia/Damascus).

## Source state

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD | `1ca062ca330655fc68b5f363e9d6d0b4fad19a6c` |
| Upstream state | `origin/main`, local branch ahead by 1 |
| Dirty paths | 323 |
| Modified entries | 196 |
| Deleted entries | 16 |
| Untracked entries | 110 |
| Added entries | 0 |
| Renamed entries | 0 |

The worktree was already substantially dirty from the audit, P0-A, P0-B, and pre-existing user work. P0-C will not reset, clean, stash, commit, delete backups, delete volumes, remove the preserved Metabase H2 artifact, prune images, or claim these pre-existing changes as P0-C work. `docs/remediation/P0B_GIT_STATUS_AFTER.txt` is the immediate prior-phase boundary.

## Runtime baseline

`docker compose ps -a`, `docker compose images`, and `docker compose config --services` were captured before P0-C edits.

| Class | Count | Baseline |
|---|---:|---|
| Current Compose service definitions | 27 | 26 long-running definitions plus one one-shot initializer |
| Current long-running containers | 26 | All running |
| Long-running containers with a configured healthy result | 25 | All 25 reported `healthy` |
| Long-running containers without a probe | 1 | `notification-expiry-worker` was running but had no healthcheck |
| Successful one-shot containers | 1 | `surrealdb-volume-init` exited 0 |
| Historical orphan containers | 1 | `voice-service-worker`, exited 137 about four months earlier |

The historical Voice worker is not a current Compose service, does not auto-start, cannot process live work, and is excluded from current service health counts. Classification: **HISTORICAL ORPHAN — NON-ACTIVE**.

Current application services included the gateway, Auth, Workspace, Subscription, Notification, Report, Voice, Query, Visualization, AI, six ETL services, and the Notification expiry worker. Infrastructure included PostgreSQL-backed Metabase, ClickHouse, Redis, Kafka, ZooKeeper, SurrealDB, ClamAV, Kafka UI, and the Surreal volume initializer. P0-B persistence choices were active: Surreal RocksDB, Metabase PostgreSQL, named Voice media storage, and explicit broker volumes.

Application image ages were mixed: P0-B rebuilt the gateway, Query, Notification, Visualization, Voice, and all ETL images recently, while several other application images were approximately two weeks old. Therefore cached runtime success is not accepted as the P0-C Docker build gate.

## Test discovery baseline

- Repository scan found 132 Python test-shaped files (`test*.py`, `tests.py`, or `tests_*.py`) outside `node_modules` and `__pycache__`.
- This raw count includes maintained service tests, ETL integration/manual scripts that look like tests, and vendored TimesFM tests. P0-C inventory and collection decide the canonical boundary; filename alone does not.
- Frontend contains two Node test files: `dashboardGridLayout.test.js` and `voiceWorkflowError.test.js`.
- Frontend has two narrow scripts (`test:grid`, `test:voice-errors`) and no canonical `npm test` entry.
- No root canonical test runner (`scripts/test.ps1` or `scripts/test.sh`) existed.
- No repository-wide pytest configuration was found. Individual Django projects set their own `DJANGO_SETTINGS_MODULE`; historical ETL runs required ad-hoc `PYTHONPATH` manipulation.
- The Phase 0 audit recorded 411 selected passes, 46 failures, 17 passing subtests, and separate collection failures. P0-B subsequently proved the 55-test P0-A security gate, the live two-tenant gate, and selected Query/Visualization/Voice/ETL suites, but did not establish an all-maintained-suite baseline.

## Frontend tooling baseline

`frontend/package-lock.json` exists and defines a reproducible `npm ci` install. `package.json` defines Vite build and an ESLint command, but no ESLint configuration file existed. ESLint therefore could not be a valid green gate at baseline. The lock resolves ESLint 8.57.1 and Vite 5.x-era tooling; dependency support status is assessed separately rather than mass-upgraded in P0-C.

## CI and static-gate baseline

- `.github` did not exist; there was no first-party GitHub Actions release gate.
- No repository-wide Python correctness command existed.
- Ruff configuration exists only inside the vendored/embedded TimesFM subtree and is not a repository policy.
- Existing P0-B migration scripts provide the serialized migration path but were not wired to CI.
- Compose configuration was operational from P0-B, but P0-C still must validate it and rebuild every maintained application image.

## Baseline interpretation

This file records facts, not a pass claim. P0-C begins from a live P0-B stack with strong security/migration/persistence evidence but without a canonical all-suite runner, green lint gate, explicit readiness contract, worker liveness signal, disposable full BI workflow, or release CI. The P0-A and P0-B contracts remain binding while those gaps are addressed.
