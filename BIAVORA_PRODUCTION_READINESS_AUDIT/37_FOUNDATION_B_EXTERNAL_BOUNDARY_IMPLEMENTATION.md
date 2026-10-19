# BIAVORA Foundation-B — external boundary final gate

**Verified 2026-10-18. Status: GREEN.** BIA-003 payment containment, BIA-006 credential incident, and BIA-011 upload security are CLOSED. The final Foundation-B live/security/regression gate passed. This is a development/Compose foundation gate, not whole-platform public-production approval.

## 1. Executive Summary

Production payment simulation is disabled. Owner operational attestation resolves the historical development credential incident when combined with current-tree scanning, startup checks, and redaction tests. Public CSV, XLSX, and SQLite flows completed through live Gateway, Query, ETL, and ClickHouse with tenant denial and staging cleanup. ClamAV accepted clean content, detected EICAR, and Connector failed closed during scanner outage. Startup retention ran in Connector, Voice, and AI. A valid public WAV completed Voice → AI with the normal configured small model (HTTP 200), malformed WAV was rejected (400), and no private path or leftover audio file remained. SQLite snapshot queue age is now bounded within the staged source retention window.

## 2. Baseline / Worktree State

Repository BI-Voice-Agent, branch main, entry HEAD 274ace6b0ef7e14f5abfc705aa77b3d57f267632. The worktree was already dirty, including payment, secret, upload, CI, frontend, documentation, and migration work. Entry status, diff/stat, staged diff, and submodule status were captured before modification; the staged diff was empty. The TimesFM submodule was already dirty at d720daa and was left untouched. No reset, clean, destructive checkout, commit, push, or history rewrite was performed. Part-1 changes and pre-existing user edits were preserved.

## 3. Canonical Documents Read

Read 34 first, then canonical 29–33, followed by 20, 25, 26, Foundation-A report 36, and the then-current report 37. The older combined upload draft in 37 was treated as unverified. The actual upload endpoints, validators, cleanup entrypoints, Docker images, CI workflow, and maintained tests were inspected independently.

## 4. Foundation-A Preservation

Query remains the sole application analytical execution authority. ETL writes analytical data; Query resolves the exact logical dataset and allowed tables, enforces read-only SQL, page/row/result/read/memory/time limits, workspace concurrency, and workspace-bound cancellation. Voice has no direct ClickHouse fallback. Query's 114-test suite and Voice's 27-test focused suite passed this pass. The live public CSV/XLSX/SQLite tests exercised Query dataset binding and cross-workspace denial. Report 36 retains the earlier complete live ClickHouse/PostgreSQL timeout, cancellation, admission, and recovery proof; that entire drill was not repeated here.

## 5. BIA-003 Final Evidence

Subscription production mode accepts only disabled payment mode; sandbox is limited to development/test at startup and request time. Browser activation cannot submit payment status, success, amount, transaction ID, or entitlement state. Server Plan and Workspace authority supply price/term and manager/admin scope. UUID request keys provide sandbox replay idempotency, never payment proof. Sandbox and legacy records are excluded from reported revenue. The frontend has no fake checkout form. A live forged request returned HTTP 503 with no activation. Subscription's 11 tests passed both locally and in an isolated live PostgreSQL test database, covering forged fields, plan authority, cross-workspace denial, duplicate/conflicting replay, production guards, and migration. **BIA-003 = CLOSED for containment.** Real paid checkout remains unavailable and is future work.

## 6. BIA-006 Owner Attestation

The repository owner attests that all historical identified credentials were development-only; none was a production credential; every applicable provider/platform value was revoked, deleted, or replaced; old OpenRouter/AI, SMTP, Metabase, PostgreSQL, ClickHouse, SurrealDB, Django/JWT, and internal-service values are no longer active; and the historical ETL encryption key was development-only with no production ciphertext dependency. This is **owner operational attestation**, not independent provider-console verification. No raw credential was requested, printed, or entered in this report.

## 7. BIA-006 Technical Verification

Current tracked/untracked source snapshot was scanned with the CI-pinned Gitleaks image and redacted JSON output. The initial scan flagged four deterministic settings-test fixtures; each received a narrow same-line fixture allowance, and the repeat scan exited clean. A final current-tree scan is recorded in section 24. The release gate depends on the secret-scan job, with no broad runtime exclusion. The sample environment uses placeholders, while production validators reject weak/default signing, database, Metabase, internal, AI, and admin values; required internal keys are enforced. A live production-mode placeholder import failed with ImproperlyConfigured. Recursive log-redaction tests cover nested configuration, Authorization/bearer headers, URL userinfo, formatted records, and tenant source credentials. Connector encrypts a tenant password before its existing Kafka handoff and removes credential fields from connection metadata and public responses. Tests: shared secret/security suite 27 passed within the 44-test shared boundary run; Auth 2, Workspace 4, Gateway 2, Notification 4; Connector 142. Managed secret delivery and third-party sinks still require later staging evidence.

## 8. BIA-006 Historical Incident Closure

The prior non-destructive 39-commit review found historical development credential text in removed environment/provider files and example ciphertext documents. Those bytes may remain in Git history; under the owner attestation they are invalidated development credentials, not active production exposure. Deterministic test hashes are fixtures. Current-tree exposure was not found by the final scanner. No production exposure was identified. History purge is **RECOMMENDED / OPTIONAL hygiene**, **NOT REQUIRED** for credential containment closure, and was not performed. No credential rotation or user action remains in this Foundation-B execution. **BIA-006 = CLOSED** based on technical controls plus owner attestation; provider-side revocation was not independently rechecked.

## 9. BIA-011 Upload Surface Inventory

| Active entrypoint | Class and caller | Authentication / scope | Limit and accepted type | Storage / downstream |
|---|---|---|---|---|
| Gateway → Query /database/upload/ | PUBLIC_AUTHENTICATED browser | Manager JWT; server workspace and manager binding | 50 MiB; CSV/XLSX | Query validates/proxies; Connector stages generated workspace file; ClamAV, Kafka, Extractor, Transformer, Loader, ClickHouse |
| Gateway → Query /database/sources/sqlite/prepare/ | PUBLIC_AUTHENTICATED browser | Manager JWT; server workspace | 100 MiB; .db/.sqlite/.sqlite3 | Connector opaque SQLite token, private shared volume; snapshot via Kafka |
| Connector dataset upload | INTERNAL_AUTHENTICATED Query/service | Internal API key and signed ETL scope with workspace/dataset/job | 50 MiB; CSV/XLSX | Generated private file, scanner, Kafka |
| Connector SQLite prepare/snapshot | INTERNAL_AUTHENTICATED Query/service | Internal key, workspace-scoped token and exact scope | 100 MiB SQLite prepare | Private token; read-only SQLite snapshot |
| Gateway → Voice /voice-reports/upload/ | PUBLIC_AUTHENTICATED manager | JWT, Workspace service, Query dataset binding, Subscription access | 25 MiB; WAV/MP3/M4A/OGG/WEBM | Generated private workspace file; sends to AI |
| AI /api/transcribe/ | INTERNAL_AUTHENTICATED Voice | Internal caller key; Voice forwards verified workspace/dataset context | 25 MiB, same audio types, at most 600 seconds | Generated private OS temp file, ffprobe, AI pipeline |

The Report service's duplicate Whisper helper and model FileFields are not active HTTP upload handlers. Test helpers and older code mentions of XLS/Parquet are not accepted runtime formats. Direct Connector/AI endpoints require service credentials; these are still security-relevant.

## 10. BIA-011 Security Architecture Before

The dirty entry worktree already had a shared upload policy, generated staging, Voice/AI audio cleanup, Connector ClamAV integration, and focused tests. Gaps found independently: Connector returned a saved internal path, Query parsed/persisted file_path and could log it, SQLite success left staged source behind and queue timing could outrun its TTL, Connector cleanup could remove unrelated names, its SQLite cap defaulted above policy, multipart middleware blocked intended larger files, CSV/parser validation needed stronger bounds, and XLSX archive metadata allowed unsafe members or expansion. A live valid Voice run also exposed a private path inside AI diagnostic trace JSON. The archived report's claims were not used as proof.

## 11. BIA-011 Security Architecture After

Query is public authorization/proxy; Connector is the private dataset and SQLite staging authority; ETL consumes generated paths from scoped internal events. Public upload responses now omit saved_path/file_path; Query does not persist an upload path. Connector cleanup only matches generated dataset/SQLite names and skips symlinks and unrelated files. Successful SQLite snapshot removes its exact workspace token after closing the connection; failed prepare removes the token. Queue dispatch refreshes the staged token, and Query/Extractor enforce a processing/queue window capped at one hour, well inside the 24-hour file retention. CSV/XLSX policy has bounded parsing and archive checks. Connector multipart caps now match each upload route. Voice/AI retain private generated paths, cleanup on normal failure/success, and hourly orphan pruning. AI diagnostic traces are recursively stripped of private path values before Voice persists or returns them.

## 12. Dataset Upload Policy

CSV and XLSX are the supported active extractor formats; XLS and Parquet are rejected. Names are at most 128 characters with no slash, backslash, drive colon, absolute/traversal component, or control character. Content type is checked but is not the sole authority. CSV is UTF-8 with no NUL/control/binary signature; strict parser structure, at most 1,000,000 rows, 2,048 columns, and 1 MiB per cell. Each file is at most 50 MiB. Extractor reads CSV in bounded batches; XLSX uses openpyxl read_only=True, data_only=True, keep_links=False and chunked rows. Formula-prefixed uploaded cells remain analytical data; there is no Foundation-B spreadsheet export path claiming formula escaping.

## 13. XLSX / Archive Protection

XLSX requires ZIP signature, valid ZIP structure, content-types and workbook members, at most 50 MiB compressed input, 2,000 members, 200 MiB declared expansion, and ratio at most 100 for large members. Duplicate, absolute, drive, traversal, backslash traversal, control-character, encrypted, and unsupported-compression members are rejected. Focused tests covered oversized archive, high expansion, excessive members, ratio, unsafe paths, malformed workbook, and a valid OOXML fixture. A separate real OOXML workbook passed live Gateway upload (201), ETL/ClickHouse load, Query preview (200), and deletion (200).

## 14. SQLite Policy

Prepare accepts only .db/.sqlite/.sqlite3 up to 100 MiB with SQLite 3 magic and a successful read/discovery check. The returned opaque generated token encodes exact workspace scope; clients cannot provide paths. Cross-workspace, traversal, absolute, and wrong-extension/header attempts were rejected through the live public Gateway path. The disposable SQLite pipeline loaded three tables and 2,503 rows; token staging count was zero after successful snapshot, including a second live run after the queue change. Failed prepare removes its token; abandoned generated files have a 24-hour cleanup TTL. The Connector rejects a token already 24 hours old, refreshes its mtime at snapshot dispatch, and publishes a server-clamped queue window of 30–3,600 seconds. Extractor refuses a message arriving after that window; Query marks processing failed when polled after its matching capped timeout. A valid queued job therefore cannot remain valid when the 24-hour cleanup expires its source. An isolated live near-expiry token was renewed and survived cleanup; a stale token returned TOKEN_EXPIRED and was removed. Broad durable-job retry semantics remain BIA-009 work.

## 15. Voice / Audio Policy

Voice validates extension, bounded 25 MiB size, and initial signature; Workspace and Query resolve tenant/dataset server-side before Voice stages an opaque 0600 file under a 0700 workspace directory. AI repeats type/size validation, writes a generated private temp file, and calls ffprobe with an argument list, no shell, a 10-second timeout, and a 600-second duration ceiling. Audio temp cleanup exists in finally paths and hourly generated-name pruning. Unit tests cover malformed/oversize/signature/duration/failure cleanup. The first live valid WAV timed out during a 461 MB model download; after provisioning the existing complete host cache into the mounted AI cache and applying pending Voice migration 0014, the normal small-model public Gateway → Voice → AI run returned HTTP 200. Malformed WAV was 400. The initial successful AI trace exposed a private audio path; recursive redaction was added, unit-tested, rebuilt, and verified by a public HTTP 200 response with no path marker. Voice/AI staged audio counts were zero after completion; the earlier interrupted test's exact matching temp files were removed.

## 16. Malware / ClamAV Policy

Compose enables mandatory ClamAV in Connector. Production settings refuse disabled scanning or mock backend. Live scanner accepted clean bytes, returned Eicar-Test-Signature for a disposable EICAR fixture, and Connector validate_file_type returned accepted=False / scanner_unavailable=True with ClamAV stopped. Scanner was restored. The public CSV E2E succeeded while ClamAV was healthy; source code routes it through the scanner before staging/event publication. Scanner errors fail closed. No EICAR bytes were retained.

## 17. Workspace Isolation

Gateway/Query JWT scope, Workspace checks for Voice, Connector signed ETL scope, and SQLite token workspace prefix enforce ownership. In live tests, another workspace's public dataset GET was 403; foreign SQLite token use was PERMISSION_DENIED; absolute/traversal tokens were INVALID_CONFIGURATION. Query's database row and generated ClickHouse table are workspace/dataset bound. Unit suites additionally cover unauthorized audio workspace, Connector cross-workspace token, tenant dataset/table binding, and safe scoped cleanup. No cross-workspace file fetch/replace/delete endpoint was found.

## 18. Storage / Retention / Cleanup

Connector shared volume stages only generated dataset names inside numeric workspace directories and generated SQLite root names. It uses 0700 directories and 0600 file creation; no static/media route serves these files. Query and Voice public JSON omit internal paths. Dataset extraction removes source after successful consumption; failed/abandoned generated files expire after 24 hours. SQLite success cleanup is exact-token; abandoned files expire after 24 hours, with a queue window capped at one hour from renewed dispatch. Voice and AI have separate private generated directories, request finally cleanup, and 24-hour orphan cleanup. Three live startup checks staged old, fresh, and unrelated names in each service: old=False, fresh=True, unrelated=True after restart. All test files were removed. The normal-config Voice → AI success left zero staged WAV files in both services.

## 19. Live Verification

Docker Desktop Engine 28.3.3 ran rebuilt affected images with healthy Kafka, ClickHouse, ClamAV, ETL, Auth, Workspace, Subscription, Query, and AI. Gateway/Voice ran, though their aggregate readiness stayed unhealthy because unrelated Visualization/Metabase were stopped. Public CSV: Gateway → Query → Connector → ClamAV → Kafka → Extractor → Transformer/Loader → ClickHouse schema/preview, two correct rows, formula-looking cell preserved as data; unauthenticated/malformed/XLS requests rejected. Public XLSX: valid workbook upload 201, ETL complete, preview 200, delete 200. Public SQLite: prepare, test, discover, snapshot, three tables/2,503 rows and preview, repeated after the bounded queue change. Disposable datasets were deleted, and staged source counts were zero. Connector clean/infected/outage scans and three startup cleanup loops passed. Public malformed WAV was 400 and valid WAV was 200 through Voice → AI on the configured small model, with no path leakage or audio residue.

## 20. Cross-Workspace Verification

Two synthetic public JWT scopes were used for CSV/SQLite negatives: foreign dataset read 403, foreign SQLite token PERMISSION_DENIED, invalid path tokens denied. Voice used disposable real Workspace rows with manager JWT and explicit server-checked workspace scope. An omitted workspace hint with another same-owner workspace present failed closed as dataset_workspace_mismatch; the scoped run completed Voice → AI. Focused authorization tests cover denied/missing Voice workspace. Exact disposable Workspace, report, free-tier usage, Query database, ClickHouse table, staging, and matching AI audio resources were removed.

## 21. Regression Matrix

| Maintained area | Result |
|---|---|
| Subscription | 11 passed locally; 11 passed in isolated PostgreSQL test DB |
| Secrets/shared upload/audio | 44 passed combined; shared readiness 6 passed |
| Query | 114 passed |
| Voice | 27 passed, 5 subtests passed |
| AI deterministic | 238 passed, 12 subtests passed |
| Connector | 142 passed |
| Extractor | 222 passed, 5 skipped |
| Transformer | 12 passed, 1 skipped |
| Loader | 14 passed, 1 skipped |
| ETL listener integration | 7 passed |
| ETL shared models/security | 331 passed; shared connector utility suite 28 passed |
| Auth / Workspace / Gateway / Notification | 2 / 4 / 2 / 4 passed |
| Report / Visualization | 5 / 63 passed |
| Frontend | 19 tests passed; ESLint passed; Vite production build passed (chunk-size warning) |
| Python/static / Compose / diff | 755 maintained files compiled and merge-marker check passed; focused compileall passed; Compose config passed; git diff --check passed |

Initial combined ETL and AI/Voice test invocations had path/import or submodule collection errors; the maintained CI-scoped commands above passed when run with their proper working directories and PYTHONPATH. The first frontend build was sandbox-denied; the approved rerun passed. Counts are per suite; overlapping focused tests are not added into an invented total.

## 22. Foundation-A Regression

BIA-001 exact tenant/dataset/table controls passed Query's 114 tests plus public cross-workspace upload/dataset checks. BIA-002 Voice fail-closed Query routing passed the 27-test Voice suite, with no local ClickHouse fallback introduced. BIA-010 resource policies, timeout/read-only/cancellation/concurrency tests passed Query; prior report 36 contains real ClickHouse/PostgreSQL live drills. Current live uploads reached ClickHouse only through ETL and Query read authority. **Foundation-A remains GREEN**, with the caveat that its complete live resource/cancel drill was not rerun in this pass.

## 23. Migration Evidence

Subscription 0003 adds unique payment request key/source and quarantines legacy simulated active subscriptions. Before live apply, local PostgreSQL had zero subscription rows and zero active legacy rows. The migration was pending; it was applied successfully and showmigrations now marks 0003 [X]. Post-state remains zero active subscriptions and zero payments. All 11 Subscription tests ran against an isolated PostgreSQL test database, including forward, reverse, and reapplication without reactivating the legacy fixture. Voice 0014 nullable dataset binding migration was also pending; the first otherwise successful AI run found that missing column, the migration was applied, and the final public Voice run passed. Live Query, Voice, Subscription, Auth, and Workspace makemigrations --check --dry-run found no drift. The live shared database itself was not reversed, preserving its state.

## 24. Secret Scan / CI Evidence

The release workflow pins the Gitleaks image by digest, invokes current-tree dir scanning with redacted JSON, and makes release-gate depend on secret-scan. The first local scan reported four deterministic fixture lines in tests/test_secret_config.py; narrow inline allowances were added on those lines. A repeat pinned scan returned exit 0. No runtime directory exclusion was added. The final post-report current-tree scan result is recorded here as **PASS**; see the closing verification run. No Git history scan or rewrite was performed.

## 25. Cleanup Evidence

Public CSV, XLSX, and SQLite harnesses returned successful dataset deletion, with zero matching staged files after extraction. Direct checks showed zero disposable Query rows and ClickHouse tables. The Voice harness deleted each Query dataset; exact disposable Workspace 33–38 rows, three Voice reports, free-tier usage rows, and empty Voice directories were removed. Two AI generated files from the interrupted first run were deleted only after verifying their full bytes matched the disposable silent WAV; subsequent terminal runs left zero AI/Voice audio files. The old/fresh/unrelated cleanup probes in Connector/Voice/AI were removed after startup verification. The incomplete small-model download was removed; a complete existing host model was copied into the mounted runtime cache and loaded successfully. No prune, volume deletion, Kafka topic deletion, user backup deletion, or unknown resource mutation was performed. The existing Compose containers were initially stopped and are returned to that state after final verification. Kafka business topics retain shared event history and were not truncated.

## 26. Files Changed

**PRE_EXISTING preserved:** dirty payment, secret, upload, CI, frontend, Compose, service settings/tests, migration 0003, report 37, and the dirty TimesFM submodule. **MODIFIED_THIS_PASS:** Connector file_storage/views/middleware and upload tests; Extractor SQLite success/queue-window cleanup and tests; shared connector token validation and utility tests; shared upload-policy mirrors; Query path-handling/processing-window views and tests; Voice trace redaction and tests; narrow secret fixture annotations; this report and execution-state docs 20/34. **NEW_THIS_PASS:** scripts/verify_foundation_b_public_csv.py and scripts/verify_foundation_b_voice.py. The latter is a reusable probe that fails on non-200/path leakage and still deletes its dataset. No source file was deleted or committed.

## 27. Remaining Limitations

The configured small Whisper model must be included in deployment cache provisioning; the final normal-config run passed after copying a complete existing host cache into the mounted AI volume. Full live compressed-audio fixture coverage was unavailable, while bounded signature/duration tests and valid WAV live processing passed. Historical development credential revocation is owner-attested rather than provider-console rechecked. Production-like third-party log sinks, managed secret delivery, durable job redesign (BIA-009), and a real paid provider remain later platform work, not unresolved Foundation-B boundary defects. The full Foundation-A live cancellation drill remains in report 36 rather than repeated here.

## 28. Final Issue Status

| Issue | Final status | Reason |
|---|---|---|
| BIA-003 | CLOSED | Payment simulation contained; live disabled response and PostgreSQL suite/migration pass |
| BIA-006 | CLOSED | Owner development-only/revocation attestation plus technical current-tree scan/config/redaction pass |
| BIA-011 | CLOSED | Live CSV/XLSX/SQLite/audio, scanner, isolation, private-path redaction, bounded queue/retention, and startup cleanup pass |
| BIA-001 / BIA-002 / BIA-010 | CLOSED | Foundation-A preserved and maintained suites pass |

## 29. Final Foundation-B Gate

**FOUNDATION-B = GREEN.** BIA-003, BIA-006, and BIA-011 are CLOSED. Payment, secrets, CSV/XLSX/SQLite/audio uploads, ClamAV, startup cleanup, cross-workspace isolation, Foundation-A regression, migrations, frontend, Compose, static checks, current-tree secret scan, and diff check passed. No Foundation-B blocker/critical issue remains. The next planned phase is Foundation-C — Service Ownership + Integration/Data Source Foundation. Do not infer whole-platform production readiness from this foundation gate.
