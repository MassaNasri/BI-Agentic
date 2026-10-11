# Test execution — 2026-09-13

Host Python 3.12.3; source services build Python 3.10/3.11 images, so host test success is not container parity. Commands use python -X utf8 -B -m pytest <paths> -q -p no:cacheprovider --tb=short. ETL selected suites required PYTHONPATH=<repo>/etl-final; selected shared tests additionally require <repo>/etl-final/shared/utils. Initial import failures remain documented; path fixes do not fix the kafka shadowing defect.

| Service | Scope | Passed | Failed | Skipped | Notes |
| --- | --- | --- | --- | --- | --- |
| query | services/query-service/tests | 32 | 0 | 0 | 3 warnings; isolated host pytest |
| visualization | visualization_api/tests | 54 | 0 | 0 | 3 warnings |
| AI | services/ai-service/tests | 106 | 10 | 0 | 12 subtests passed; semantic SQL/chart/forecast mismatches |
| voice | 3 voice_reports/tests_*.py contract/trace files | 12 | 0 | 0 | 5 subtests passed |
| report | tests_sql_normalization.py | 5 | 0 | 0 | isolated unit tests |
| frontend | 2 node test files | 9 | 0 | 0 | node --test |
| ETL shared selected | schema_contract/rules_engine/ch_identifiers/input_validator/credential_encryption | 136 | 3 | 0 | PYTHONPATH includes ETL and shared/utils; rule warnings versus errors mismatch |
| ETL loader selected | engine/test_etl_remediation_loader.py | 7 | 1 | 0 | identifier trailing underscore mismatch |
| ETL extractor selected | remediation, SQL injection, pagination contract | 12 | 19 | 0 | 19 failures use non-iterable Mock cursor.description; not evidence of 19 real SQL injection bugs |
| ETL connector selected | file validator and Kafka publish reliability | 38 | 13 | 0 | Mock uploaded_file.chunks not iterable |
| ETL shared full | shared/models shared/utils | NOT RUN | 6 collection errors | NOT VERIFIED | encoding/import errors and kafka package shadowing |
| ETL transformer selected | cleaning/rules/remediation | NOT RUN | 1 collection error | NOT VERIFIED | after correcting PYTHONPATH; local kafka module shadows dependency |
| auth/workspace/subscription/notification/gateway | no dedicated first-party test files inventoried | NOT VERIFIED | NOT VERIFIED | NOT VERIFIED | requires isolated service/contract/security suite |
| ETL detector/metadata | placeholder tests.py present | NOT VERIFIED | NOT VERIFIED | NOT VERIFIED | no comprehensive suite executed |

Executed non-overlapping selected tests: 411 passed, 46 failed, plus 17 passing subtests. Collection failures are separate, not skipped tests. No result claims full coverage. Frontend npm run build passed after retry outside sandbox; bundle JS 661.70 kB / 191.89 kB gzip. npm run lint failed: ESLint configuration absent. docker compose config --quiet passed. Static AST parse found no syntax errors in first-party scanned Python files.

Failing groups: AI daily trend/distribution SQL and forecast/chart selection; ETL rules error/warning contract; loader identifier contract; extractor cursor mocks; connector upload chunk mocks. Reconcile intended contracts rather than blindly changing expectations. Full ETL collection additionally encounters UTF-16 test_file.txt, top-level imports and shared/kafka shadowing kafka-python.

The workspace-client security reproduction returned caller hint 999999 after a mocked HTTP 403; no live tenant record was accessed. Existing SQL guard tests cover AST statements, table functions, system tables and workspace DB binding and passed. Their pass does not secure visualization paths that bypass that guard.

Required next tests: two-tenant CRUD/embeds/files/AI/query history; revoked membership; JWT expiry/reuse/admin denial; new-install migration graph per owner; dependency outage readiness; restore drills; full disposable upload→ETL→query→report workflow with mail disabled and no paid model calls.
