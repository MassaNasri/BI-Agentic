# P0-B verification results

Verification date: 2026-09-30. Environment: local Windows/Docker Desktop, PostgreSQL/restore tools 18.3. Secret values and tenant content are intentionally excluded.

## Migration checks

Commands:

```powershell
.\scripts\run-migrations.ps1
docker compose run --rm --no-deps <service> python manage.py makemigrations --check --dry-run --skip-checks
```

Services checked: Auth, Workspace, Subscription, Notification, Voice, Query, Visualization, Report.

Result: **PASS**. First live serialized run applied Notification `0002`, Voice `0013`, Query `0003`/`0004`, and Visualization `0001` where required. The next complete run reported `No migrations to apply` for every service. All eight drift checks returned `No changes detected`.

## Fresh install

Method: started a disposable PostgreSQL 18.3 container on an isolated named volume, created `p0b_fresh`, and ran each service’s `python manage.py migrate --noinput` sequentially with database environment pointed only at that container.

Result: **PASS**, eight of eight configurations. No `--fake`, global authentication weakening, or source-database mutation was used.

## Upgrade clone

Source and isolation:

```powershell
Get-FileHash -Algorithm SHA256 backups\phase0-20260913T141937Z\bi_voice_agent.dump
pg_restore --list backups\phase0-20260913T141937Z\bi_voice_agent.dump
# Restore target was p0b_clone in the isolated p0b-postgres-harness only.
```

Result: **PASS**. Source dump SHA-256 `89458c319fffd1c87e1713380491d1d168c503f0cbef7efdc5464153ea4fee1b`. Counts before/after: users 5, workspaces 3, manager databases 2, voice reports 331, dashboard pages 6, assignments 334, notification logs 223. Two dataset ingestion UUIDs were non-null and distinct; duplicate count zero. Expected new Query/Visualization tables and Voice indexes existed. Second upgrade was a no-op.

The first Query clone attempt failed safely on the disposable clone with a duplicate UUID constraint: PostgreSQL evaluated the old statement default once for the multi-row update. This was **FIXED BY P0-B** with nullable add → per-row backfill → constraint/default alteration, after which the clone passed.

## SurrealDB restart/recreate and recovery

Active configuration:

```text
surrealdb/surrealdb@sha256:849c9ad548415ddf06b80d834929ddc43fb9c482d2ef9b51113641a8e47fad63
rocksdb:///data/biavora/database
volume: surreal_data -> /data
```

Behavior performed: create a harmless tagged record → restart/read → remove/recreate active container → read exact record → native export → import into a new isolated volume/container → read exact record → remove tagged record and isolated resources.

Result: **PASS**. Active export: 451 bytes, SHA-256 `23D95B620D8610C65B467FE4F41908030A75EB98D82753D2128FD5791102145F`. Duplicate second import correctly refused an existing record rather than silently overwriting it. Historical pre-P0-B memory state remains unrecoverable and is not included in this pass.

## Metabase H2 to PostgreSQL and recreation

Source version: Metabase v0.58.8.5, build `23da6ce`; target uses the exact same image digest. The original H2 file stayed offline and hash-equal to the Phase 0 manifest. Migration ran from a separate writable working copy because Metabase must update its H2 migration lock; the initial read-only-copy attempt was an **ENVIRONMENT/HARNESS FAILURE**, not a source mutation or application defect.

Counts:

| Object | H2 before | PostgreSQL after | Recreated app | Encrypted restore |
| --- | ---: | ---: | ---: | ---: |
| Cards | 484 | 484 | 484 | 484 |
| Dashboards | 16 | 16 | 16 | 16 |
| Collections | 4 | 4 | 4 | 4 |
| Users | 2 | 2 | 2 | 2 |
| Data sources | 2 | 2 | 2 | 2 |

Result: **PASS**. The active Metabase container uses dedicated PostgreSQL and survived recreation. The encrypted dump restored to an isolated database; exact-version app startup, login, source 2 health, and ClickHouse `SELECT 1` all passed. The exact version does not expose the newer `enable-encryption` command; starting it with `MB_ENCRYPTION_SECRET_KEY` performed the version-supported encryption path, and stored source details were no longer plaintext JSON objects.

## Media persistence

Voice: write tagged file → compute SHA-256 → replace container/read → tar backup → restore into isolated volume/read → remove tag.

Result: **PASS**. Marker SHA matched before/after/restore. Archive: 10,240 bytes, SHA-256 `B64BC98C4E6E4121F06DB33B604F409524AB82893DAAE1C55C205862FBF38ADA`.

ETL upload handoff:

```powershell
docker compose up -d --force-recreate etl-connector
```

Result: **PASS**. Marker SHA-256 `0f51180463cc96192aea9b87e8cf2192f859b0bb452f898b72f7c98e15ceb4d6` matched after Connector recreation and the marker was removed.

## Security regression

Final commands/results:

```text
services/query-service> python -m pytest tests -q -p no:cacheprovider --tb=short
50 passed

services/visualization-service> python -m pytest visualization_api/tests -q -p no:cacheprovider --tb=short
62 passed

services/voice-service> PYTHONPATH=<repo> python -m pytest voice_reports/tests_ai_trace_service.py voice_reports/tests_query_execute_metabase_fallback.py voice_reports/tests_query_service_contract.py voice_reports/tests_security_workspace_authorization.py -q -p no:cacheprovider --tb=short
20 passed, 5 subtests passed

services/auth-service> python manage.py test users.tests_security_invitation
2 passed

services/workspace-service> python manage.py test workspace.tests_security_invitation
4 passed

repo> PYTHONPATH=etl-final python -m pytest etl-final/shared/security/test_security_controls.py -q -p no:cacheprovider --tb=short
15 passed

repo> PYTHONPATH=etl-final;etl-final/shared/utils python -m pytest test_input_validator.py test_credential_encryption.py test_ch_identifiers.py
71 passed

connector-service> python manage.py test connector.etl_engine.test_api_validation
17 passed
```

P0-A classification: **55 new security tests passed, 0 failed; 158 existing relevant tests passed, 0 failed; 0 new regressions.** The 158 count uses the P0-A-defined existing subsets (32 Query + 54 Visualization + 12 Voice + 60 ETL input/credential). The broader 71-test ETL selection includes 11 additional identifier cases.

Harness classifications:

- Direct Auth/Workspace `pytest` without Django setup: **ENVIRONMENT/HARNESS FAILURE**; `manage.py test` passed 2/2 and 4/4.
- Query suite inside the runtime image: **ENVIRONMENT/HARNESS FAILURE** because a test assumes two source-tree parent directories and `/app/tests` has only one; the source-tree run passed 50/50.
- First Voice source-tree run without repository `PYTHONPATH`: **ENVIRONMENT/HARNESS FAILURE**; corrected run passed 20/20 plus 5 subtests.
- Broad legacy ETL selection: 35 failures/66 passes from known stale auth/path contracts; not used to overwrite the scoped P0-A baseline. Security 15/15, relevant utils 71/71, and Connector validation 17/17 passed.

## Live two-tenant integration

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-p0b-two-tenant.ps1
```

Final result: **PASS**.

```text
Tenant A real login: 200
Tenant B real login: 200
Tenant A -> Tenant B Voice report: 404
Tenant B -> own Voice report: 200
Tenant A -> Tenant B visualization: 403
Tenant B -> own visualization embed: 200
Tenant A scope -> Tenant B ingestion mutation: 404
Tenant B exact scope -> own ingestion mutation: 200
Tenant A -> Tenant B ETL metadata: no record
Tenant B -> own ETL metadata: exact record returned
```

The final cleanup left users 0, workspaces/members 0, voice reports 0, manager databases 0, visualization ownership 0, tagged Surreal metadata 0, and outstanding/blacklisted test JWT rows 0.

Issues discovered during the live run:

- Voice converted a scoped `Http404` to 500. **FIXED BY P0-B** with a non-disclosing 404 branch.
- Running ETL images were stale relative to P0-A source. **ENVIRONMENT/DEPLOYMENT DRIFT**, fixed by rebuilding all six images.
- Current Surreal client prepended two `USE` statements, so the serializer consumed the namespace result instead of the query. **FIXED BY P0-B** by using request context headers and a single query result.

## Runtime behavior

Final HTTP probe result: **14/14 PASS**—Gateway, AI, Query, Subscription, Notification, Connector, Metadata, and Metabase health; anonymous denials for Auth, Workspace, Report, Voice, and Visualization; invalid Gateway login rejection.

Current topology: 26 long-running services running (25 configured healthy plus the intentional Notification expiry worker without a probe), and one `surrealdb-volume-init` one-shot exited 0. A stopped four-month-old `voice-service-worker` is an orphan from a historical Compose definition and was preserved, not counted as a current service.

## Cleanup and preservation

Removed only these disposable verification resources after evidence capture:

- containers: `p0b-postgres-harness`, `p0b-metabase-restore`, `p0b-surreal-compose-restore`;
- volumes: `p0b-postgres-harness-data`, `p0b-surreal-compose-restore-data`, `p0b-voice-media-restore`;
- exact tagged data/markers and 8 orphaned JWT rows created by live verification.

Original H2, Phase 0/P0-B backups, anonymous broker source volumes, the historical Voice worker, and all 534 unknown volumes remain preserved.
