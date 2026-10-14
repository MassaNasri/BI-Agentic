# 19 — Dead Code and Deletion Candidates

## Method and caution

Candidates were checked against imports, installed Django apps, URL routing, Compose entrypoints, scripts, CI and tests where practical. This is a deletion plan, not authorization to delete. Ambiguous or potentially evidentiary material is marked `INVESTIGATE` or `ARCHIVE`; `DELETE_SAFE` is used only where runtime evidence is strong. No file was deleted.

## Candidate register

| Candidate | Location/evidence | Class | Action/gate |
|---|---|---|---|
| Report service duplicate domain/application implementation | `services/report-service/voice_reports/models.py`, `services.py`, `urls.py`; app absent from `INSTALLED_APPS`; runtime uses `report_urls.py` proxy to voice | DELETE_AFTER_MIGRATION | First decide report ownership and migrate any required behavior/tests; then remove duplicate unwired app |
| Broken alternate voice orchestration | `services/voice-service/voice_reports/application/orchestration_service.py` imports missing `domain.statuses` and missing infrastructure clients; not the active views path | INVESTIGATE | Confirm no external importer, preserve useful design intent in ADR, then delete or rebuild only under chosen job architecture |
| Legacy report proxy hop | `services/report-service/report_urls.py` and proxy views forward to voice | MERGE | Move report ownership to the selected service; remove proxy deployment after client/gateway cutover |
| Duplicate report ORM models/migrations across voice/report | both service trees define report concepts while only voice owns active state | MERGE | Select one owner; data migration and contract deprecation required |
| Unconsumed report Kafka events | voice emits `report.*`; repository contains no matching business consumer | INVESTIGATE | Add an owned consumer only if notification/audit requirement is real; otherwise remove emission after telemetry confirms no external consumer |
| Legacy ETL topic aliases/metadata shape | ETL compatibility constants and `process_load_status` omit current scope fields | DELETE_AFTER_MIGRATION | Inventory deployed producers/consumers, publish deprecation metrics, migrate and retire legacy contract |
| Committed ClickHouse engine data | `etl-final/etl-infra/clickhouse/data/` contains 4,531 tracked paths | GENERATED_IGNORE | Verify no intentional fixture, archive any required seed metadata, remove from Git in a separately approved change and ignore runtime volumes |
| Committed SurrealDB data | 22 tracked data paths | GENERATED_IGNORE | Same provenance/backup check; move runtime state out of source control |
| Compiled Python artifacts | 18 tracked `.pyc` paths | DELETE_SAFE | No runtime/CI reference and reproducible from source; remove in approved cleanup and strengthen ignore rule |
| ETL local test files | 35 paths under `etl-final/Test-File` | INVESTIGATE | Classify fixtures versus outputs; keep minimal deterministic fixtures, remove generated/output data |
| Historical audit documents | about 36 audit/report docs outside the new audit directory | ARCHIVE | Retain as dated evidence if required, but mark superseded and move to a deliberate archive/index later |
| Historical remediation documents | about 41 remediation docs | ARCHIVE | Consolidate decisions/status; do not let stale claims act as architecture truth |
| Duplicate HTTP client/auth/readiness utilities | repeated service-local client and health patterns | MERGE | Standardize only stable cross-cutting transport/telemetry primitives; keep business authorization local |
| Placeholder MCP plan flag | `Plan.has_mcp_access` without tool runtime | KEEP | It is product metadata, not an implementation; rename/document semantics during billing migration if retained |

## Keep

- Multi-engine connector registry/adapters and P1-R snapshot/security regression suites.
- Shared SQL parsing/guard library, after tightening table authorization.
- Deterministic AI compiler/planner components and their tests.
- TimesFM submodule and its current local working state. Its modifications pre-existed this audit and were deliberately untouched.
- Migration histories for installed applications. Old migrations are not dead merely because later migrations supersede their schema.
- Prior audit/remediation reports until an explicit records-retention decision is made.

## Additional investigation queue

Static heuristics alone are insufficient for individual unused functions/imports because Django discovery, settings strings and test patch paths create dynamic references. Before a cleanup change, run Python import analysis, frontend dependency analysis, coverage from the full integration suite and a route/topic inventory. Require all of these for `DELETE_SAFE`: no import, entrypoint, route, installed app, Compose/CI/script/doc requirement, migration dependency, test fixture, serialized path or externally published contract.

Potentially stale dependencies should be checked with language-specific dependency analyzers, then removed one at a time with lock/build/tests. Do not remove LangChain merely because no RAG exists until all dynamic imports are resolved; conversely, a dependency name is not proof that a capability exists.

## Deletion sequence

1. Record SHA/path provenance and establish the target ownership ADRs.
2. Add telemetry for legacy routes/topics and observe a defined deprecation window.
3. Migrate data/contracts and update clients in a backward-compatible release.
4. Remove deployment/routing references, then code and dependencies.
5. Run the full release gate and scan packaged images for remnants.
6. Remove generated artifacts/history only under an explicit retention and secret-rotation plan.

The audit identifies **14 candidate groups**: one `DELETE_SAFE`, two `GENERATED_IGNORE`, three `MERGE`, three `DELETE_AFTER_MIGRATION`, three `INVESTIGATE`, two `ARCHIVE`, plus explicit keep decisions. Counts are groups, not raw files.

