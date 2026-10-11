# P0-C CI report

Workflow: `.github/workflows/p0c-release-gate.yml`. Local structural validation: **PASS**. The YAML parses into eight jobs, the release job requires all seven upstream jobs, and no required command uses `continue-on-error` or `|| true`.

| Job | Enforced gates |
|---|---|
| `static-and-compose` | Python syntax/merge markers, POSIX script syntax, Compose config |
| `frontend` | Node 22, lockfile `npm ci`, tests, zero-warning ESLint, production build, bundle leakage policy |
| `backend-and-ai` | Shared HTTP and all maintained Django/backend/AI selectors, including Subscription and Notification |
| `etl` | Maintained shared, Connector, Extractor, Transformer, Loader, listener, Detector, and Metadata selectors |
| `security-regression` | Actual Query, Visualization, Voice, Auth, Workspace, and ETL security test execution |
| `migration-drift` | `makemigrations --check --dry-run` for all eight P0-B configurations |
| `docker-build` | Compose build of all maintained application images without publishing |
| `release-gate` | Fails unless every required upstream job reports `success` |

The backend job emits JUnit XML artifacts for shared, Query, Visualization, Voice, Report, and AI suites. Django/ETL jobs retain clear native runner output. Required failures propagate non-zero exit status.

Security properties:

- Test-only non-production credential material only; no production secret is required or printed.
- `APP_ENV=test`, in-memory email, and empty OpenRouter key are explicit.
- No paid inference, outbound email, shared destructive reset, image push, deployment, or production data access.
- Workflow permissions are read-only (`contents: read`).
- Node 22 replaces the EOL Node 20 CI runtime.

Local evidence includes successful equivalent test commands, Compose validation, 17 application-image builds, migration drift, frontend build/bundle scan, and YAML parsing. A hosted GitHub Actions run was not triggered from this local task; this does not weaken the gate definition, and the first pushed run remains normal repository operational evidence.
