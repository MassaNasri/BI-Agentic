# P0-C test results

Final status: **PASS**. The canonical baseline has **1,416 passed, 0 failed, 17 skipped, and 0 collection errors**.

| Scope | Passed | Failed | Skipped | Collection errors |
|---|---:|---:|---:|---:|
| Backend services and shared HTTP | 169 | 0 | 0 | 0 |
| Deterministic AI | 230 | 0 | 0 | 0 |
| ETL | 1,008 | 0 | 17 | 0 |
| Frontend Node tests | 9 | 0 | 0 | 0 |
| **Total** | **1,416** | **0** | **17** | **0** |

## Backend detail

| Suite | Result |
|---|---|
| Shared readiness/request IDs | 6 passed |
| API Gateway | 2 passed |
| Query | 60 passed |
| Visualization | 63 passed |
| Voice | 20 passed, plus five successful `subTest` cases not double-counted |
| Report | 5 passed |
| Auth | 2 passed |
| Workspace | 4 passed |
| Subscription | 3 passed |
| Notification | 4 passed |

## ETL detail

| Suite | Result |
|---|---|
| Shared models/security | 330 passed |
| Shared utilities | 296 passed, 10 skipped |
| Connector | 131 passed |
| Extractor | 218 passed, 5 skipped |
| Transformer | 11 passed, 1 skipped |
| Loader | 8 passed, 1 skipped |
| Transform/loader listener contracts | 6 passed |
| Detector | 4 passed |
| Metadata | 4 passed |

All 17 skips are explicit optional/live-integration cases. They are not collection failures and are separately retained in the inventory. Destructive database migration tools, live scanner demos, external model runs, TimesFM upstream tests, and historical audit scripts are not default automated tests.

## Other required gates

- `npm ci --no-audit --no-fund`: PASS from the lockfile.
- `npm test`: 9 passed.
- `npm run lint`: PASS with zero warnings (`--max-warnings 0`).
- `npm run build`: PASS; 1,928 modules transformed. One non-fatal bundle-size advisory remains.
- Frontend bundle policy: PASS; no localhost API, Docker-only service host, database endpoint, development secret, or debug route in the production output.
- Python/static: PASS; 720 maintained Python files compiled and no merge markers found.
- P0-A: original 55/55 passed; the current selector is a 57-test superset and also passes.
- P0-B live tenant isolation: PASS.

## Isolation and repeat evidence

The major canonical suites ran twice. The first repeat exposed shell leakage of `CREDENTIAL_SECRET_KEY`; the runner now owns the value and the independent Extractor rerun passed. A later complete Python/ETL pass was green. Frontend tests/lint passed on repeat, and the production build passed unchanged outside the Windows filesystem sandbox. No unexplained flake remains and no arbitrary sleep was added.

Canonical commands are `powershell -File scripts/test.ps1` and `bash scripts/test.sh` from the repository root. They set `APP_ENV=test`, safe test-only secrets, local-memory email, deterministic import roots, and non-zero failure behavior.
