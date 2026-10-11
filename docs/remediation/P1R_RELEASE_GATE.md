# P1-R Release Gate

Date: 2026-10-11  
Final decision: **GREEN**

## Mandatory gates

| Gate | Result | Evidence |
|---|---|---|
| CSV regression | PASS | User manual PASS; 24/24 focused automated tests |
| PostgreSQL live/full E2E | PASS | 2,512 rows; 4 tables; empty + 2,500-row chunked table |
| MySQL live/full E2E | PASS | 2,512 rows; 4 tables; exact counts/uniqueness |
| MariaDB live/full E2E | PASS | Independent MariaDB 11.8 run; 2,512 rows |
| SQLite live/full E2E | PASS | Public upload; 2,503 rows; confinement failures |
| ClickHouse-source live/full E2E | PASS | Separate source/destination; 2,512 rows |
| Multi-table browsing | PASS | Opaque selector, table-aware schema/preview, frontend switcher |
| Empty-table completion | PASS | Schema-only event creates successful zero-row destination |
| Core regressions | PASS | All required suites green |
| Static/build gates | PASS | ESLint, production build, Django checks, migration drift, Compose render |
| Security gate | PASS | SSRF, auth, workspace, encryption/redaction, TLS contracts, readonly sources |
| Runtime gate | PASS | 8/8 required services healthy; scoped logs clean |
| Cleanup | PASS | Zero records/tables/temp files/source containers |

## Optional enterprise engines

SQL Server and Oracle are accepted as optional enterprise connectors for this release under the supplied rule:

- Implementation, registry identity, drivers, frontend options, configuration validation, quoting/pagination, normalized errors, TLS contracts, and optional Compose rendering pass.
- Their live runtimes are `BLOCKED_EXTERNAL`, not PASS. Neither image was cached. Permission to download/start the SQL Server image was requested and declined; no unauthorized Oracle pull was then attempted.
- No implementation defect was observed in either connector and no live result was fabricated.

## Exact regression results

| Command-level suite | Result |
|---|---|
| Shared connector/security/redaction/Kafka schema | 111 passed |
| Focused TLS/SSRF/error/auth | 16 passed, 26 deselected |
| Query service full | 79 passed, 3 warnings |
| Connector Django full | 134 passed |
| Extractor full | 220 passed, 5 skipped, 22 warnings |
| Transformer full | 12 passed, 1 skipped, 113 warnings |
| Loader full | 14 passed, 1 skipped, 1 warning |
| ETL listener contracts | 7 passed, 9 warnings |
| CSV focused | 24 passed |
| Frontend | 19 passed, 0 failed |

Warnings are deprecation/advisory items and did not hide failures. The frontend build transformed 1,929 modules and emitted only stale browser-data and bundle-size advisories.

## Freeze decision

P1 snapshot ingestion may now be frozen for the supported core matrix. The public contracts, connector registry, PK discovery, table identity, credentials-in-transit design, Kafka/ETL flow, multi-table browsing, zero-row behavior, and cleanup boundary are stable enough to begin P2 architecture.

This decision does not claim that CDC exists. SQL Server and Oracle should receive live certification when their optional images/environment are authorized, but that external gap does not reopen a known P1 correctness defect.

## Remaining limitations

- Snapshot is one-time/on-demand only; no CDC, offset, replay, persistent connection, or scheduler exists.
- SQL Server and Oracle are not live-certified in this environment.
- Local disposable containers used explicit plaintext development connections; enterprise TLS paths are contract-tested, not full-PKI live-tested.
- Existing deprecation warnings (`datetime.utcnow`, Pydantic protected namespaces) and frontend bundle/browser-data advisories remain non-blocking maintenance items.
- CSV empty-input acceptance was not separately rerun and remains `NOT_RUN` in the detailed matrix.

`P2_READY` is **true** under the defined rule. The next phase is P2 Persistent Database Connections + CDC; it was not implemented here.
