# Clean-state startup verification

Evidence: 2026-09-13, `startup_verification.json`, `migration_verification.json`, `container_migration_verification.json`, `migration_drift_detail.json`, and `final_storage_verification.json`.

**Local startup smoke: PASS. Migration execution: PASS. Migration/source parity: FAIL. Full functional acceptance: PARTIAL.**

| Check | Result | Scope |
| --- | --- | --- |
| Compose configuration | PASS | Existing root Compose parsed successfully. |
| Docker image builds | PASS | All 17 application/notification-worker images built from the current worktree after adding seven `.dockerignore` files. |
| Compose startup | PASS | `docker compose -f docker-compose.yml -f docs/audit/startup.override.yml up -d --no-build` completed. All 24 declared containers running; 23 report configured healthy, notification worker has no healthcheck. |
| Existing core migrations | PASS | Sequential commands for auth/workspace/subscription/notification/voice/query/visualization/report/AI; gateway checked in its actual container. No new migration generated. |
| Actual SQLite service migrations | PASS | AI and six ETL containers applied existing Django migrations. The first disposable AI compose-run check alone was insufficient, so migrations were repeated in the actual container. |
| Migration parity | FAIL | `makemigrations --check --dry-run` exits 1 for voice and notification. Details below. |
| HTTP probes | PASS | Fourteen probes: gateway, AI, query, subscription, notification, ETL connector/metadata health; anonymous-denial routes for auth/workspace/report/voice/visualization; frontend page; restored Metabase health. |
| Invalid login | PASS | Gateway `/auth/login/` returned 400. No signup or message sent. |
| Bootstrap admin login | PASS | Existing environment-defined bootstrap credentials returned tokens; an authorized gateway admin-users request returned 200. No token or credential serialized to reports. |
| PostgreSQL clean after requests | PASS | All 21 cleared business/session tables remain zero, including users and token tables. |
| Metabase H2 recovery copy | PASS, scoped | Offline H2 open/query succeeded; 484 cards, 16 dashboards, four collections, Sample Database/H2 and ClickHouse sources. Same original image starts the copy and `/api/health` returns 200. |
| Frontend build / serving | PASS | Production build completed; Vite serves HTTP 200 on 127.0.0.1:5173. Browser rendering and complete interactive user journey NOT VERIFIED. |
| Frontend lint | FAIL | ESLint configuration missing. |
| Selected tests | PARTIAL | 411 passed, 46 failed, plus 17 passing subtests; separate ETL collection errors. See TEST_EXECUTION.md. |

The initial report/voice/visualization probes addressed nonexistent route roots and returned 404. Inspection of active URL modules corrected them to `/voice-reports/reports/` and `/visualization/question/1/embed-url/`; each returns the expected anonymous 401. These initial 404s were probe errors, not evidence of missing implemented APIs. No application route was changed to make a test pass.

Voice drift proposes renaming `dashboard_p_workspa_0dd780_idx` and `report_page_page_id_8a980a_idx`, plus altering `VoiceReport.chart_type`. Notification proposes five `managed=False` record models in migration state. This does **not** prove five missing database tables; they already reference foreign owner tables. Review intentional state versus DDL, then commit migrations with regression and fresh-install tests. A zero `migrate` exit cannot close this gap.

The Metabase original remains stopped and unchanged. `phase0-metabase-restore` serves a disposable restored H2 copy at 127.0.0.1:3000, using the original image ID, the application network and `metabase` network alias. `MB_DISABLE_SCHEDULER=true`, anonymous tracking and update checks are disabled. This prevents stored dashboard subscriptions from being sent during the check. The original 37 backup entries remain separate and hash-verifiable. This temporary copy is not the target production Metabase installation; do not treat edits in it as changes to the preserved original.

Auth and both notification processes use `django.core.mail.backends.dummy.EmailBackend` via `startup.override.yml`. No SMTP messages or paid AI inference were requested. The frontend stays available at http://127.0.0.1:5173 and gateway at http://127.0.0.1:8000. Startup retained the existing Compose port bindings; loopback-only internal bindings remain a P0 task.

Remaining **NOT VERIFIED**: migration on a brand-new empty PostgreSQL application database; full upload/extract/transform/load/query/chart/report workflow; two-tenant live penetration/regression suite; real Metabase source query and tenant card ownership; external SMTP; paid model inference; load/soak tests; dependency outage readiness; full ClickHouse/broker/Redis recovery; long-term worker liveness. ETL web port health does not establish listener progress. Older legacy ETL containers and voice worker remain stopped.

Rerun only the read-only smoke with `./scripts/reset-dev.ps1 -Verify` while the local frontend, restored Metabase copy and root stack are running. It does not start containers or send email. The reset workflow and its drift guards are described in DATA_STORAGE_AND_WIPE_REPORT.md.
