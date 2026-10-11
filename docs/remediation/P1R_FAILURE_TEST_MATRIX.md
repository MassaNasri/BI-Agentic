# P1-R Failure Acceptance Matrix

Date: 2026-10-11

`PASS (live)` means the public endpoint hit a real source. `PASS (contract)` means automated normalization/redaction coverage passed but no live server claim is made. SQL Server and Oracle live cells remain blocked.

| Engine | Wrong password | Invalid DB | Wrong port | Blocked host | TLS failure | Permission failure | Safe public error | Secret redaction |
|---|---|---|---|---|---|---|---|---|
| PostgreSQL | PASS (live): `AUTHENTICATION_FAILED` | PASS (live): `DATABASE_NOT_FOUND` | PASS (live safe error; post-fix refusal contract) | PASS (live): `DESTINATION_NOT_ALLOWED` | PASS (contract) | PASS: SELECT-only source | PASS | PASS |
| MySQL | PASS (live): `AUTHENTICATION_FAILED` | PASS (live): `PERMISSION_DENIED` | PASS (live): `CONNECTION_REFUSED` | PASS (live): `DESTINATION_NOT_ALLOWED` | PASS (contract) | PASS (live): SELECT-only source | PASS | PASS |
| MariaDB | PASS (live): `AUTHENTICATION_FAILED` | PASS (live): `PERMISSION_DENIED` | PASS (live): `CONNECTION_REFUSED` | PASS (live): `DESTINATION_NOT_ALLOWED` | PASS (contract) | PASS (live): SELECT-only source | PASS | PASS |
| SQLite | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PASS (live): cross-workspace `PERMISSION_DENIED` | PASS (live) | PASS |
| ClickHouse source | PASS (live): `AUTHENTICATION_FAILED` | PASS (live): `DATABASE_NOT_FOUND` | PASS (live): `CONNECTION_REFUSED` | PASS (live): `DESTINATION_NOT_ALLOWED` | PASS (contract) | PASS (live): readonly source | PASS | PASS |
| SQL Server | PASS (contract) | PASS (contract) | PASS (contract) | PASS (contract) | PASS (contract) | BLOCKED_EXTERNAL | PASS (contract) | PASS |
| Oracle | PASS (contract) | PASS (contract) | PASS (contract) | PASS (contract) | PASS (contract) | BLOCKED_EXTERNAL | PASS (contract) | PASS |

## Normalized error gate

The automated connector/security suites exercise safe handling of:

- `INVALID_CONFIGURATION`
- `DNS_RESOLUTION_FAILED`
- `DESTINATION_NOT_ALLOWED`
- `CONNECTION_TIMEOUT`
- `CONNECTION_REFUSED`
- `AUTHENTICATION_FAILED`
- `TLS_ERROR`
- `DATABASE_NOT_FOUND`
- `SCHEMA_NOT_FOUND`
- `TABLE_NOT_FOUND`
- `PERMISSION_DENIED`
- `DRIVER_UNAVAILABLE`
- `EXTRACTION_FAILED`

The shared connector/security/redaction command passed 111 tests. A focused TLS/SSRF/error/auth gate passed 16 tests with 26 deselected. Public failure payloads were also checked for credential reflection, traceback text, raw password DSNs, and private-key text.

## SQLite file-boundary failures

| Case | Result |
|---|---|
| Valid `.sqlite3` upload/header | PASS |
| Unsupported/fake extension | PASS: rejected |
| Invalid SQLite header | PASS: rejected |
| Token from another workspace | PASS: `PERMISSION_DENIED` |
| Traversal-shaped token | PASS: `INVALID_CONFIGURATION` |
| Absolute-path-shaped token | PASS: `INVALID_CONFIGURATION` |
| Maximum-size enforcement | PASS (automated connector tests) |
| Opaque token not reflected in failure | PASS |

## Observed safe behavior

- Source credentials were encrypted before Kafka publication and decrypted only by the extractor boundary.
- Logs identify connector/workspace/dataset/job/table/chunk context without logging connection secrets.
- The final acceptance-window scan found no exact test-secret value in any required service log.
- The final five-minute scan found no `ERROR`, `CRITICAL`, `Traceback`, `Unhandled`, `ImportError`, `panic`, or `fatal` token in the eight required services.
