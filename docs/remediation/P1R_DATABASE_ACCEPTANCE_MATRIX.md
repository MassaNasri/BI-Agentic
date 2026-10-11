# P1-R Database Acceptance Matrix

Date: 2026-10-11  
Vocabulary is strict: `PASS`, `FAIL`, `NOT_RUN`, `NOT_APPLICABLE`, `BLOCKED_EXTERNAL`. Contract-only evidence never creates a live PASS.

| Acceptance dimension | CSV | PostgreSQL | MySQL | MariaDB | SQLite | ClickHouse source | SQL Server | Oracle |
|---|---|---|---|---|---|---|---|---|
| Implementation exists | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Driver available | NOT_APPLICABLE | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Runtime service available | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Public capability advertised | NOT_APPLICABLE | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Frontend option available | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Configuration validation | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Test connection | NOT_APPLICABLE | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Schema discovery | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Table discovery | NOT_APPLICABLE | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Column discovery | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Primary-key discovery | NOT_APPLICABLE | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Identifier quoting | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Chunked extraction | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Null preservation | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Decimal preservation | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Date/time handling | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Timezone handling | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| JSON handling where supported | PASS | PASS | PASS | PASS | NOT_APPLICABLE | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Unicode | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Empty table | NOT_RUN | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Multi-table snapshot | NOT_APPLICABLE | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| ClickHouse row integrity | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Dataset completion | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Schema API | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Preview API | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Authentication failure | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Network failure | NOT_APPLICABLE | PASS | PASS | PASS | NOT_APPLICABLE | PASS | PASS | PASS |
| Invalid database | NOT_APPLICABLE | PASS | PASS | PASS | NOT_APPLICABLE | PASS | PASS | PASS |
| Blocked destination / SSRF | NOT_APPLICABLE | PASS | PASS | PASS | NOT_APPLICABLE | PASS | PASS | PASS |
| TLS behavior | NOT_APPLICABLE | PASS | PASS | PASS | NOT_APPLICABLE | PASS | PASS | PASS |
| Secret redaction | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Cleanup | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Full public E2E | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |
| Final status | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED_EXTERNAL | BLOCKED_EXTERNAL |

## Evidence interpretation

- PostgreSQL, MySQL, MariaDB, SQLite, and ClickHouse source were each run through the authenticated public API gateway and real Kafka/ETL/destination path. Their live table counts and representative value evidence are in `P1R_E2E_RESULTS.md`.
- The type rows combine real deterministic source fixtures with connector normalization/quoting/TLS contract tests. No SQL Server or Oracle type row is marked live PASS; their live-dependent cells remain `BLOCKED_EXTERNAL`.
- The CSV full-path claim uses the already user-confirmed manual acceptance plus the current 24-test file extraction regression and the unchanged, previously verified public file pipeline. No new manual claim was invented.
- SQLite rejection behavior covers extension, header, cross-workspace token, traversal-shaped token, and absolute-path-shaped token. Size validation is covered by connector tests.
- `NOT_RUN` for CSV empty input is intentionally visible; it is not required to establish the requested dirty/stress CSV regression and was not converted to PASS.

## Live row matrix

| Engine | Imported tables | Aggregate destination rows | Large-table uniqueness | Public E2E |
|---|---:|---:|---:|---|
| PostgreSQL | 4 | 2,512 | 2,500 / 2,500 | PASS |
| MySQL | 4 | 2,512 | 2,500 / 2,500 | PASS |
| MariaDB | 4 | 2,512 | 2,500 / 2,500 | PASS |
| SQLite | 3 | 2,503 | 2,500 / 2,500 | PASS |
| ClickHouse source | 4 | 2,512 | 2,500 / 2,500 | PASS |
| SQL Server | 0 | 0 | NOT_RUN | BLOCKED_EXTERNAL |
| Oracle | 0 | 0 | NOT_RUN | BLOCKED_EXTERNAL |
