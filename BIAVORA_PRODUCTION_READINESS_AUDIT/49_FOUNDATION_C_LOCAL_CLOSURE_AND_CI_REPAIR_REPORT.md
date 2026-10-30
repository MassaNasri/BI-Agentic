# 49 — Foundation-C local closure and CI repair

Decision date: **2026-10-27**. Branch: `foundation-c-staging`. Entry HEAD: `9ed2439512179b032736c6f1917521fb7c0dce71`. Public launch target: **10 January 2027**.

**Foundation-C Local Engineering: CLOSED**

**Foundation-C External Deployment Validation: DEFERRED_TO_PRODUCTION_READINESS**

**Production Readiness: NO-GO**

This is the owner's explicit phase-sequencing decision, supported by existing C6 local evidence and the CI repairs/validation recorded below. It is not an external certificate or a new execution of the entire historical C6 stack. Reports 36–42 and the prior scope reconciliation report 47 remain unchanged. The canonical roadmap/master/traceability now reflect this decision.

## Repository state and scope

Entry already contained the previous reconciliation: 34 modified tracked Markdown files, six new numbered Markdown documents (43–48), and `scripts/check_release_documentation.py`, all unstaged. The only unrelated dirty path was `services/ai-service/forecasting/timesfm` with its pre-existing untracked-content marker. These changes were preserved and current planning was updated in place as requested.

No production settings, service requirements, application behavior, CDC code, migration, cloud resource or staging deployment is changed by this repair. CI/test fixtures and documentation are the only new scope. No commit, push, staging, reset or cleanup of user work; TimesFM was not entered or modified. Disposable local test environments are outside the repository and do not use user databases or credentials.

## Previous remote CI and repaired verification

Previous remote run: **FAILED**, based on the owner's supplied errors:

1. Owner Boundary: `ImproperlyConfigured: Production DEBUG/ALLOWED_HOSTS configuration is unsafe.`
2. Security Regression: pip `ResolutionImpossible` from `kafka-python==2.0.2` versus `kafka-python==2.3.0`.

Fix: **implemented locally**.

New remote verification: **PENDING_PUSH_AND_RUN**.

No GitHub run URL/ID was supplied or independently fetched; these exact failures are owner-reported and corroborated by the workflow/settings/requirements. This uncommitted repair cannot have a verified future remote result. PRs, main pushes and workflow dispatch trigger the current workflow; after pushing this branch use the existing PR or manual dispatch as appropriate.

## Failure A — safe production owner fixture

The migration step switched `APP_ENV` to production and supplied database/secrets, but never supplied `ALLOWED_HOSTS`. Auth's settings read **`DEBUG`** through `_env_bool` and **`ALLOWED_HOSTS`** through `_csv_env`. DEBUG defaults false; ALLOWED_HOSTS defaults to an empty list. Production correctly rejects debug, empty hosts or a wildcard. Workspace, Subscription and Query use the same names and CSV format. This is a fixture defect, not a defect in the guard.

The workflow now explicitly supplies:

```yaml
APP_ENV: production
DEBUG: 'false'
ALLOWED_HOSTS: localhost,127.0.0.1
CORS_ALLOWED_ORIGINS: ''
DJANGO_CORS_ALLOWED_ORIGINS: ''
```

Only loopback names are needed: the runtime verifier starts WSGI on 127.0.0.1 and fetches `/ready/`. No browser-origin access is exercised, so CORS remains empty and no CSRF trust exception is needed. Existing internal tokens/generated secrets and explicit migration-role flags remain required. `DJANGO_ALLOWED_HOSTS` alone would not satisfy these services' real contract.

The C5 verifier also explicitly sets DEBUG false and empty CORS for its runtime children, so inherited development settings cannot break the proof. Production service settings and shared production validation are unchanged.

New tests initialize real Django for Auth/Workspace/Subscription/Query using safe production migration-mode fixtures, and reject DEBUG true, empty hosts and wildcard hosts for every service. Only dotenv file loading is mocked to prevent developer `.env` contamination; production validation itself is not mocked. No real credential or external endpoint is used.

## Failure B — service dependency isolation

Exact conflicting inputs in the old Security Regression install command:

| Manifest | Pin | Actual runtime boundary |
|---|---|---|
| `services/voice-service/requirements.txt:29` | `kafka-python==2.0.2` | Voice image installs its own requirements |
| `etl-final/shared/requirements.txt:1` | `kafka-python==2.3.0` | ETL shared dependency set |

The same 2.3.0 pin also appears in ETL Connector, Detector, Extractor, Transformer, Loader and Metadata manifests. The old job passed backend service manifests and ETL shared together to one pip command. The separate Voice and ETL Dockerfiles do not share that interpreter, so changing service versions would disguise a CI-induced conflict.

Security Regression is now a six-member matrix: **query, visualization, voice, auth, workspace, etl**. Each clean runner installs its own native service requirements. ETL installs shared plus Connector requirements because `test_security_controls.py` initializes Connector's Django app; shared alone does not provide that app's dependencies. Both ETL manifests use Kafka 2.3.0. No package is excluded and no service pin changes.

`scripts/run_security_regression.py` owns the exact install/test mapping and propagates subprocess failures. Separate local virtual environments invoke the same script. The matrix uses `fail-fast: false` so one failed service does not cancel the remaining security checks; this does not permit failure. The aggregate release gate still requires the whole matrix to succeed.

Original test coverage preserved:

| Suite | Commands retained |
|---|---|
| Query | Three credential/callback/configuration pytest files; Integration public-boundary Django suite with SQLite test settings |
| Visualization | Ownership/query-reference security pytest file |
| Voice | Workspace-authorization security pytest file |
| Auth | Invitation-signup security Django suite |
| Workspace | Invitation security Django suite |
| ETL | Shared security-controls pytest file with ETL PYTHONPATH |

## Release-gate strictness

All nine prerequisite jobs remain mandatory: Secret Scan, Static/Compose, Frontend, Backend/AI, ETL, Security Regression, Migration Drift, Docker Build and Foundation-C Owner Boundary. The final job still runs with `if: always()` and compares all nine results with `success`. No `continue-on-error`, ignored pip failure, removed security suite or new test skip was added.

`scripts/verify_release_workflow.py` parses YAML and checks the nine dependencies, strict aggregation, matrix coverage, native requirement mapping, retained test commands and exact safe production fixture. It runs in Static/Compose with a pinned CI-only PyYAML dependency. This is separate from the application/service requirements.

## Executed validation

All executed test suites finished successfully; **63 original Security Regression cases passed with no skips**, plus **16 new production-environment cases**. The new 16-case suite ran twice (existing interpreter and then fresh owner environment). No failure was suppressed.

Commands below use the indicated isolated environment's Python. Service-relative commands ran from their service directory; repository-level commands ran from the clean source mirror or actual repository as indicated.

| Command | Result | Scope / notes |
|---|---|---|
| `python scripts/verify_release_workflow.py` | PASS | YAML and required-job/matrix/fixture contract; no continue-on-error |
| `python scripts/p0c_static_check.py` | PASS | 804 maintained Python files compiled; no merge markers |
| `python scripts/run_security_regression.py query --install` | PASS | Unchanged Query native requirements; pip check clean |
| `python scripts/run_security_regression.py visualization --install` | PASS | Unchanged Visualization native requirements; pip check clean |
| `python scripts/run_security_regression.py voice --install` | PASS | Unchanged Voice native requirements; Kafka 2.0.2 confirmed; pip check clean |
| `python scripts/run_security_regression.py auth --install` | PASS | Unchanged Auth native requirements; pip check clean |
| `python scripts/run_security_regression.py workspace --install` | PASS | Unchanged Workspace native requirements; pip check clean |
| `python scripts/run_security_regression.py etl --install` | PASS | Unchanged ETL shared/Connector requirements; Kafka 2.3.0 confirmed; pip check clean |
| `python -m pip install -r services/auth-service/requirements.txt -r services/workspace-service/requirements.txt -r services/subscription-service/requirements.txt -r services/query-service/requirements.txt` | PASS | Separate owner-proof environment, matching owner job; pip check clean |
| `python -m pytest tests/test_clickhouse_credential_redaction.py tests/test_ingestion_callback_security.py tests/test_security_configuration.py -q` | PASS — 22 | Query native environment |
| `python manage.py test integration.test_public_boundary --settings=service_config.sqlite_test_settings --verbosity 1` | PASS — 3 | Query public contracts; real disposable SQLite test database |
| `python -m pytest visualization_api/tests/test_security_ownership_and_query_reference.py -q` | PASS — 8 | Visualization native environment |
| `python -m pytest voice_reports/tests_security_workspace_authorization.py -q` | PASS — 8 | Voice native environment |
| `python manage.py test users.tests_security_invitation --verbosity 1` | PASS — 2 | Auth native environment |
| `python manage.py test workspace.tests_security_invitation --verbosity 1` | PASS — 4 | Workspace native environment |
| `python -m pytest etl-final/shared/security/test_security_controls.py -q` | PASS — 16 | ETL native environment and ETL PYTHONPATH |
| `python -m pytest tests/test_owner_boundary_environment.py -q` | PASS — 16, twice | Actual repository: 34.23 s; fresh owner environment: 23.41 s; no database required |
| `python scripts/verify_foundation_c4_owner_roles.py` | PASS | Disposable PostgreSQL: owner CRUD, foreign mutation denial, identity sequence and rollback/data preservation |
| `python manage.py migrate --noinput --verbosity 0` | PASS for all four services | Auth, Workspace, Subscription, Query under production fixture/migration role; five Integration tables asserted |
| `python scripts/foundation_c4_owner_schemas.py apply` | PASS | Owned schemas/roles applied to fresh migrated database |
| `python scripts/verify_foundation_c5_service_roles.py` | PASS | Five real Django runtime roles, denied foreign writes, four WSGI readiness probes, Query/Integration cross-alias lifecycle |
| `python scripts/foundation_c4_owner_schemas.py rollback` | PASS | Owner migration rollback |
| `python -X utf8 scripts/check_release_documentation.py --write-inventory` | PASS | 41 changed/new Markdown files, 14 capability rows, stable issue IDs, local/deployment distinction, links/fences/tables; 175 reference files inventoried |
| `git --no-pager diff --check` | PASS | No whitespace errors |

The six security test groups were invoked through `scripts/run_security_regression.py <suite>`; that script emitted and executed the exact test commands above. No security suite was skipped or marked allowed to fail. Existing deprecation warnings from SimpleJWT/pkg_resources remain visible and do not fail these tests.

Setup diagnostics, resolved before acceptance: sandboxed environment setup stalled and was interrupted; initial local PostgreSQL initialization failed under the restricted token and with an empty password file; the old bundled pip rejected the local certificate chain. The disposable PostgreSQL cluster was then initialized with an explicit synthetic test password, and current pip bootstrapped the isolated environments using Windows certificate trust. **TLS verification was never disabled.** Final native installs and all listed tests passed. The local cluster bound only 127.0.0.1:55493 and was stopped after validation.

Not run: the entire Linux GitHub Actions workflow, Docker builds, frontend/AI/full ETL suites, external staging/TLS/KMS/identity/Kafka-drain certification and the full historical C6 E2E stack. These are not test skips added to CI: unmodified full-workflow checks remain mandatory remotely, while external deployment evidence remains CAP-14. Local test execution is not a remote GREEN claim. The local harness/logs remain in the workspace's `biavora-ci-repair-validation` directory, outside the Git repository.

Local execution uses Windows Python 3.12.3 and disposable PostgreSQL 18.3, matching the owner CI PostgreSQL major/version and CI Python minor. Linux runner/container builds remain remote verification; these local checks do not replace the full workflow. The service images' existing Python version differences and unbounded dependencies are unchanged wider CAP-14 work.

A clean first-party source mirror omits developer `.env`, runtime data, backups and TimesFM so local tests receive controlled CI-like inputs. The mirror runs unchanged test/source files plus this repair. Security configuration tests still examine the safe root configuration template and Compose, rather than inheriting developer secrets.

## Local closure, deferred evidence and debt semantics

Foundation-C local engineering covers service ownership, Integration/DataSource, versioned credential lifecycle, ConnectionTransport, DNS/SSRF/pinning, restricted PostgreSQL roles, Kafka v2 source path, public contracts, two-workspace isolation and the local E2E acceptance already recorded in C6. This run repairs and rechecks the CI paths without pretending that every historical integration drill was rerun.

BIA-008 remains **technically PARTIAL** because its original acceptance includes deployment evidence. Its implementation is **LOCAL ENGINEERING COMPLETE**; its external evidence is **DEFERRED_TO_PRODUCTION_READINESS**. BIA-005/014/018/030 local defect closures are retained. Kafka v1 remains TRANSITIONAL, default off with its bounded reader policy; real deployed drain is not inferred.

CAP-14 retains all of these mandatory items:

- Managed external secret store/KMS and deployed workload identities.
- Real identity/key rotation and workload-bound secret access.
- Controlled stable public egress and customer-like public PostgreSQL TLS verify-full.
- Customer allowlist proof and combined full public production-policy ETL.
- Deployed Kafka v1 backlog/retention/drain attestation.
- Deployment cutover and rollback proof.

Plan/operator/access checkpoint: **16 November**. Environment and combined probes start: **29 November**. Complete G-C-DEPLOY: **15 December**, before final RC and with time to repair failures. Repeat impacted proofs on the final candidate before public GO. None of these resources is provisioned in this run.

## Exact Foundation-D entry criteria

**Next implementation phase: Foundation-D — PostgreSQL CDC.**

Local implementation may begin after:

1. Foundation-C Local Engineering CLOSED.
2. The **required current release CI GREEN**.
3. No regression in Foundations A/B/C local security boundaries.

The second condition remains pending until the repaired commit is pushed and GitHub runs successfully. Local closure is not a claim that this remote condition already passed. External deployment validation is a production-certification prerequisite, not a local Foundation-D development prerequisite. Foundation-D has not been implemented here: no Debezium, WAL, Kafka Connect, CDC processor/loader, checkpoint or CDC-schema changes.

## Files changed in this repair

- [.github/workflows/p0c-release-gate.yml](../.github/workflows/p0c-release-gate.yml)
- [scripts/verify_foundation_c5_service_roles.py](../scripts/verify_foundation_c5_service_roles.py)
- [scripts/run_security_regression.py](../scripts/run_security_regression.py)
- [scripts/verify_release_workflow.py](../scripts/verify_release_workflow.py)
- [tests/test_owner_boundary_environment.py](../tests/test_owner_boundary_environment.py)
- [scripts/check_release_documentation.py](../scripts/check_release_documentation.py)

Canonical documentation updated in this repair:

- [20_TECHNICAL_DEBT_AND_PROBLEM_REGISTER.md](20_TECHNICAL_DEBT_AND_PROBLEM_REGISTER.md)
- [22_TARGET_ARCHITECTURE.md](22_TARGET_ARCHITECTURE.md)
- [23_FEATURE_READINESS_MATRIX.md](23_FEATURE_READINESS_MATRIX.md)
- [24_ARCHITECTURE_DECISION_RECORDS_NEEDED.md](24_ARCHITECTURE_DECISION_RECORDS_NEEDED.md)
- [25_14_WEEK_IMPLEMENTATION_ROADMAP.md](25_14_WEEK_IMPLEMENTATION_ROADMAP.md)
- [26_MASTER_REFACTOR_BUILD_DELETE_PLAN.md](26_MASTER_REFACTOR_BUILD_DELETE_PLAN.md)
- [29_CANONICAL_PRODUCT_SCOPE.md](29_CANONICAL_PRODUCT_SCOPE.md)
- [31_CANONICAL_SERVICE_OWNERSHIP_MAP.md](31_CANONICAL_SERVICE_OWNERSHIP_MAP.md)
- [33_PRODUCTION_SECURITY_BASELINE.md](33_PRODUCTION_SECURITY_BASELINE.md)
- [34_BIAVORA_MASTER_CONTEXT_FOR_FUTURE_PROMPTS.md](34_BIAVORA_MASTER_CONTEXT_FOR_FUTURE_PROMPTS.md)
- [43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md)
- [45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md](45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md)
- [48_DOCUMENTATION_INVENTORY_AND_SCOPE_REFERENCES.md](48_DOCUMENTATION_INVENTORY_AND_SCOPE_REFERENCES.md)
- [49_FOUNDATION_C_LOCAL_CLOSURE_AND_CI_REPAIR_REPORT.md](49_FOUNDATION_C_LOCAL_CLOSURE_AND_CI_REPAIR_REPORT.md)
- [README.md](README.md)
- [Root README](../README.md)

New files from this repair: `scripts/run_security_regression.py`, `scripts/verify_release_workflow.py`, `tests/test_owner_boundary_environment.py`, and report 49. The documentation checker and documents 43–48 were already untracked at entry.

Historical 36–42 and 47 remain unchanged. Earlier unrelated reconciliation files remain present and unstaged; the final parent diff therefore includes work predating this repair. The inventory/checker now treats 47 as historical, 49 as current, and validates documentation without incorrectly rejecting authorized CI/test edits.

## Final Git and handoff

Final branch and HEAD remain `foundation-c-staging` / `9ed2439512179b032736c6f1917521fb7c0dce71`. Staged diff: **empty**. Parent working tree: **36 modified tracked files, 11 untracked additions**, plus the unchanged pre-existing TimesFM ` ?` marker. The tracked diff is **630 insertions / 990 deletions** and includes the earlier documentation reconciliation; untracked additions are not included in that stat.

Final commands inspected: `git status --short`, `git --no-pager diff --check`, `git --no-pager diff --stat`, `git --no-pager diff --name-only`, `git --no-pager diff -- services/ai-service/forecasting/timesfm`, and the full workflow diff. The TimesFM parent diff is empty. Production settings and all service requirements have no diff. Historical Foundation reports 36–42 have no diff. Workflow inspection confirms all nine jobs remain mandatory, no test is disabled, no continue-on-error is introduced and dependency isolation is explicit.

**No stage, commit or push. TimesFM untouched.** The disposable local PostgreSQL test server was stopped after successful validation. No staging/cloud deployment or Foundation-D/CDC implementation occurred.

Next human action: **review → stage selected changes → commit → push → observe GitHub Actions**. No deployment provisioning is required before that review. Do not begin local Foundation-D until its current CI entry condition is actually GREEN.
