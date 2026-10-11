# P0-A baseline

Captured before P0-A source changes on 2026-09-29 (Asia/Damascus).

## Repository identity

- Repository: `BI-Voice-Agent`
- Branch: `main`
- HEAD: `1ca062ca330655fc68b5f363e9d6d0b4fad19a6c`
- HEAD timestamp: 2026-05-08 18:19:31 +0300
- HEAD subject: `add bi_shared`

## Preservation state

The worktree was already extensively dirty. The starting `git status --short` was captured in the tool transcript before this file was created. It included tracked modifications/deletions across root configuration, frontend, shared libraries, AI, gateway, auth, query, report, visualization, voice, workspace, and ETL, plus many untracked audit, hardening, service, and UI files. These are treated as user work and will not be reset, checked out, cleaned, or overwritten wholesale.

The complete earlier Phase 0 status snapshot is stored in `docs/audit/inventory.json` under `git_status_before`; the later Phase 0 snapshot is in `docs/audit/git_status_after.txt`. P0-A's final modification ledger will distinguish files added or intentionally edited by this phase from this baseline.

Notable pre-existing target-file modifications include:

- `docker-compose.yml` and `etl-final/docker-compose.yml`
- Voice views/models/settings and untracked dashboard/security-related modules
- Query database views/utilities, execution, SQL guard, settings, requirements, and untracked tests
- Visualization views/settings/Metabase services and tests
- Auth settings/permissions and workspace serializers/views/URLs
- API gateway routing/settings
- AI and shared-contract changes

The nested TimesFM checkout already contained an untracked `run.py` dated April 2026; it remains outside P0-A scope.

## P0-A constraints

- No data wipe or backup deletion.
- No database-per-service split.
- No Kafka removal or ETL consolidation.
- No Metabase or SurrealDB migration.
- No Django major upgrade or API gateway rewrite.
- No Git history rewrite, hard reset, checkout-over, clean, or commit.
- External credentials are not considered rotated by repository changes.

## Baseline verification plan

Run the existing relevant auth, voice, workspace, query, visualization, ETL connector/metadata, and gateway tests before applying security changes. Record pre-existing failures separately from new security test results and regressions.

## Baseline results

The isolated, relevant pre-change suites completed with **158 passed and 0 failed**:

| Scope | Passed | Failed | Notes |
| --- | ---: | ---: | --- |
| Query Service existing tests | 32 | 0 | Three Pydantic warnings |
| Visualization Service existing tests | 54 | 0 | Three Pydantic warnings |
| Voice Service contract/trace tests | 12 | 0 | Five additional subtests passed |
| ETL input-validation and credential-encryption tests | 60 | 0 | Required ETL and shared-utils `PYTHONPATH` entries |

The first ETL invocation produced two collection errors because the shared-utils path was absent. The corrected invocation passed all 60 tests; those initial collection errors are harness configuration, not product failures. Auth, Workspace, Metadata, and Gateway had no dedicated first-party baseline suite for these paths, consistent with the Phase 0 audit.
