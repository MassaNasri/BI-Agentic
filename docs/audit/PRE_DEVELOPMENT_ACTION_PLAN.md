# Pre-development action plan

The audit, backups, targeted reset, builds, tests and planning are complete in their recorded scopes. Overall Phase 0 acceptance is **PARTIAL** and production is **NOT READY**. Resolve the gates below before feature work. Do not silently turn an unverified result into a waiver. Each issue in `issues.json` includes evidence, risk, solution, migration impact, complexity and priority.

## Top 10 blockers

1. **Retained exposed credentials (SEC-004):** current local secrets still match historical tracked values; secret removal from the worktree did not revoke them.
2. **Fail-open workspace authorization (SEC-001):** a denied workspace lookup retains the caller's workspace hint and subsequent report/page queries use it.
3. **Mutable unowned dataset bindings (SEC-015):** dataset status updates lack owner/job authorization and accept physical ClickHouse identifiers.
4. **Unscoped Metabase objects (SEC-002):** embed signing and card/dashboard mutation lack tenant ownership checks.
5. **Alternate raw SQL execution (SEC-003):** visualization accepts SQL that bypasses the query service AST/tenant boundary.
6. **Public, unscoped ETL and unsafe connectors (SEC-005/006/007/008/009):** unauthenticated ingress combines with SSRF, fallback encryption and exposed internal ports.
7. **Existing-account invitation mutation (SEC-014):** invitation signup can replace an existing account's password/role without account authentication.
8. **Metadata durability and recovery (OPS-001/002/006):** Surreal memory mode, Metabase writable-layer H2 and nonpersistent media threaten data loss.
9. **Shared database and non-HTTP business boundaries (ARC-001–007):** the required target is not met; moving tables alone will not remove foreign access or distributed transaction failures.
10. **Unreliable release evidence (OPS-005/008/009/016):** TCP-only health, model/migration drift, failing tests, collection/lint errors and unsupported dependencies prevent a dependable release gate.

## The exact first 10 tasks to execute next

| # | Task / owner | Concrete work | Acceptance evidence |
| --- | --- | --- | --- |
| 1 | Rotate exposed credentials — security/platform | Inventory historical credential names without values; revoke external provider key; rotate admin, internal API, embedding, JWT and affected DB/BI credentials; distribute only to required services and invalidate old sessions. Coordinate history remediation separately. | Old credentials rejected, new service calls succeed, secret scan returns no new leaks; a rotation record names each key and date without its value. |
| 2 | Close voice workspace fail-open — voice/workspace | Change `voice_reports/infrastructure/workspace_client.py` and auth context to distinguish validated membership, denied membership and unavailable owner. Reject unverified hints before every report/page/history lookup. | Two tenants cannot read/edit/delete each other's objects; 403/404 never becomes permission; timeout yields bounded 503; authorized manager/member flows pass. |
| 3 | Protect dataset callbacks and identifiers — query/ingestion | Restrict `database/views.py` DatabaseStatusView to a scoped ingestion job; bind tenant/dataset/job immutably; allow only legal status transitions; remove caller physical names; quote and validate identifiers in preview/delete utilities. | Foreign dataset mutation and poisoned binding tests fail closed; legitimate callback is idempotent; tenant query/preview/delete all use one authoritative mapping. |
| 4 | Authorize visualization objects — visualization/report | Add an ownership registry for card/dashboard IDs; backfill only provable mappings; quarantine unknown legacy objects; check both objects before attachment and before signing embeds. | Two-tenant embed/attach/read tests pass; unmapped objects cannot be embedded; preserved Metabase metadata remains recoverable. |
| 5 | Remove visualization SQL bypass — query/visualization/voice | Introduce authorized query-definition/result IDs; run every execution through query AST, dataset scope and limits; migrate callers away from arbitrary SQL payloads. | Multi-statement/system/function/foreign-table bypasses rejected on every path; valid chart creation still succeeds; compatibility route cannot bypass validation. |
| 6 | Isolate and authenticate ETL — platform/ingestion | Require verified service identity plus tenant/dataset/job at upload, connection, logs and lineage endpoints; bind development diagnostic ports to loopback; isolate internal networks; use destination allowlists and explicit timeouts; fail startup without a real credential encryption key and safe settings. | Anonymous ETL calls rejected; cross-tenant files/logs denied; localhost/link-local SSRF blocked; approved connector works; missing secrets fail startup. |
| 7 | Fix existing-user invitation acceptance — auth/workspace | Separate new-account signup from authenticated existing-account invitation acceptance; remove password/role replacement from existing-user signup. Use the dedicated recovery flow for password resets. | Invitation possession alone cannot change an existing identity; expiry/replay/mismatched-email tests pass; legitimate invited users can join once. |
| 8 | Make metadata and uploads durable — platform/metadata/BI | Pin the current versions; migrate Surreal to a mounted persistent engine with a restart/read test; migrate a verified H2 copy to dedicated Metabase PostgreSQL; persist owner media; keep originals and create off-host backup/restore runbooks. | Metabase cards/dashboard/source counts match, source read works with restricted grant, metadata/media survives replacement, isolated restore succeeds. Record unrecoverable prior Surreal memory state. |
| 9 | Reconcile migration state — voice/notification/platform | Run `makemigrations --check --dry-run`, review every detected change, commit only intended migrations, and test each owner on a fresh disposable DB and upgrade clone. Separate migrations from web/worker startup. | No unexplained drift; empty-install and upgrade migrations pass; service images retain needed persistence; rollback limits documented. |
| 10 | Establish the green baseline and readiness gate — all service owners | Repair ETL test imports/encoding/mocks, AI SQL/chart contracts and frontend ESLint config; add CI builds/unit/contract/two-tenant tests; implement readiness and worker heartbeats; run one disposable mail-disabled upload→query→report workflow and remove its data. | All intended suites collect and pass, lint/build green, outage health returns 503, critical regressions are CI gates, startup and after-test cleanup are reproducible. |

Tasks 2–7 use source-level regression tests before behavior changes. Task 1 may invalidate sessions and needs coordinated secret deployment. Task 8 must use copies and preserve original metadata. Existing user work must remain intact throughout. Do not use this list as authorization to rewrite Git history, publish a deployment, or send third-party notifications.

## P0 — Must fix before new development

Execute tasks 1–10 and the P0 entries in `issues.json`. Retire unsafe reset usage; keep reviewed manifest and backup guards. Address known port and log exposure, maintain explicit development environment markers, verify after-state and resolve current startup failures. Restrict development access while critical fixes are pending. No new feature branch should expand the vulnerable execution paths.

## P1 — Fix during architecture restructuring

Follow R1–R7 and the database/communication matrices: assign report persistence to report-service and voice jobs to voice-service; split logical databases and credentials; replace notification foreign ORM with narrow owner HTTP APIs; give query exclusive serving-warehouse ownership; replace AI warehouse reads with schema/value/result APIs; consolidate ETL into an ingestion owner with private staging and HTTP metadata/publication contracts. Remove Kafka business paths and shared cross-service files after equivalence/replay validation. Adopt versioned internal HTTP, scoped identity, idempotency and compensating workflow state. Replace shared business repositories with owner modules; keep only transport/DTO utilities shared. Update current architecture docs from the resulting implementation.

## P2 — Must fix before production

Complete R8–R13: supported locked dependencies and image digests, production servers/non-root images, TLS/network policies, secret isolation/JWKS, refresh handling/CSP, API version/error schemas, bounded retries/circuit breakers, distributed throttling, telemetry and redaction, worker supervision, performance/retention/load gates, restore drills, deployment provenance and rollback exercises. Do not defer critical security fixes into these infrastructure phases. `OPS-008` is a release blocker even though its supported-framework upgrade belongs after immediate P0 regression coverage.

## P3 — Post-MVP improvements

Prioritize from measured use: selective HA and replicas, query tuning, model cost/quality evaluation, fine-grained cost attribution, automated retention and capacity alerts, compatibility-route removal and documentation automation. No critical/high finding is accepted as post-MVP work by default.

## Sprint-ready decomposition and rollback

`MICROSERVICES_RESTRUCTURING_PLAN.md` contains R0–R13, with goal, reason, services/files, database/API impact, dependencies, detailed tasks, acceptance, tests and rollback for each. Use one owner/database boundary per cutover; retain readable migration mappings and old read-only stores until reconciliation passes. Avoid dual writes without a defined authority and repair path. Import `issues.json` into issue tracking only when explicitly requested; this audit sent no messages and created no external tickets.
