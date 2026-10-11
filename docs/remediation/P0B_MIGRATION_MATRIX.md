# P0-B migration matrix

Verified on 2026-09-30 against both a new empty PostgreSQL 18.3 database and an isolated restore of `backups/phase0-20260913T141937Z/bi_voice_agent.dump`. The restore container, databases, and volume were disposable and have been removed. The source dump and active database were not altered during the first-run safety test.

| Service | Existing latest at P0-B start | Final latest | Drift | Fresh DB | Upgrade clone | Smoke | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Auth | `users.0003` | `users.0003` | None | PASS | PASS | Live anonymous denial PASS | PASS |
| Workspace | `workspace.0006` | `workspace.0006` | None | PASS | PASS | Live anonymous denial PASS | PASS |
| Subscription | `subscription.0002` | `subscription.0002` | None | PASS | PASS | Live dependency health PASS | PASS |
| Notification | `notification.0001` | `notification.0002` | Reconciled as state-only unmanaged foreign models | PASS | PASS | Live dependency health PASS | PASS |
| Voice | `voice_reports.0012` | `voice_reports.0013` | Reconciled model state to existing physical indexes/column | PASS | PASS | 20 tests plus 5 subtests and live denial PASS | PASS |
| Query | `database.0004` | `database.0004` | None after safe `0003` repair | PASS | PASS | 50 tests and live dependency health PASS | PASS |
| Visualization | `visualization_api.0001` | `visualization_api.0001` | None | PASS | PASS | 62 tests and live denial PASS | PASS |
| Report | Framework migrations only; no active domain ORM app | Unchanged | None | PASS | PASS | Live denial PASS | PASS |

## Intentional migration repairs

- `services/query-service/database/migrations/0003_database_ingestion_job_id.py` now adds the UUID nullable and without a default, backfills each row with its own UUID, and only then makes the field unique, required, and defaulted. PostgreSQL had evaluated the prior statement default once, causing a duplicate-key failure on a real multi-row restored clone.
- `services/query-service/database/migrations/0001_initial.py` represents the cross-service manager identifier as the scalar `PositiveBigIntegerField` used by the current model. It no longer installs an unintended dependency on an Auth model owned by another service.
- `services/workspace-service/workspace/migrations/0001_initial.py` and `0002_alter_workspacemember_unique_together_and_more.py` represent external user/owner identifiers as scalars. A fresh shared-database install no longer depends on a nonexistent `auth_user` table.
- `services/voice-service/voice_reports/migrations/0013_reconcile_chart_type_state.py` uses `SeparateDatabaseAndState`. It records the current chart choices while leaving the already-correct column and indexes unchanged.
- `services/notification-service/notification/migrations/0002_unmanaged_foreign_model_state.py` records five foreign-owned models as `managed=False`. It creates, alters, or deletes no foreign table.

## Clone integrity evidence

Before and after migration, the restored clone retained these counts: 5 users, 3 workspaces, 2 database-manager rows, 331 voice reports, 6 dashboard pages, 334 page assignments, and 223 notification dispatch rows. Query and Visualization P0-A tables were absent before upgrade and created by their reviewed migrations.

After upgrade:

- both dataset rows had non-null, distinct ingestion UUIDs;
- required uniqueness was enforced with zero duplicate violations;
- Voice rows with overlength chart values: zero;
- expected Voice index names matched the physical database;
- no foreign-owned Notification tables were created;
- a second full serialized migration run was a no-op for all eight configurations.

`makemigrations --check --dry-run --skip-checks` returned “No changes detected” for all eight in-scope Django configurations. Migration startup was removed from API Gateway and Query web commands and from the Notification expiry worker; `scripts/run-migrations.ps1` and `scripts/run-migrations.sh` are now the single serialized migration path.
