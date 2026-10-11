# P0-A security test matrix

Final security result: **55 passed, 0 failed**. The counts exclude the 158 pre-existing relevant tests.

| Issue | Attack/Failure Scenario | Expected | Actual | Status |
| --- | --- | --- | --- | --- |
| SEC-001 | Workspace dependency returns 401/403 | Requested workspace never becomes trusted | Denied result has no workspace context and raises 403 | PASS |
| SEC-001 | Workspace dependency returns 404 | Resource rejected | Explicit `NOT_FOUND`, no hint fallback | PASS |
| SEC-001 | Timeout/network failure | Bounded fail-closed response | Explicit dependency failure maps to 503 | PASS |
| SEC-001 | Malformed or mismatched 200 response | Deny | `INVALID_RESPONSE`; no trusted context | PASS |
| SEC-001 | Valid membership response | Continue only with verified workspace | Matching dependency workspace accepted | PASS |
| SEC-002 | Tenant A embeds foreign/unmapped card | 403 | 403 | PASS |
| SEC-002 | Tenant A embeds foreign/unmapped dashboard | 403 | 403 | PASS |
| SEC-002 | Foreign card/local dashboard or local card/foreign dashboard | 403 | Both ownership records required | PASS |
| SEC-002 | Same-tenant card/dashboard attachment | Success | 200 | PASS |
| SEC-002 | Oversized embed lifetime | Reject | Values over 300 seconds raise validation error | PASS |
| SEC-003 | Public Visualization request supplies raw SQL | Reject | 400; query-definition reference required | PASS |
| SEC-003 | Query definition resolves to another workspace | Reject | 403 | PASS |
| SEC-003 | DDL, DML, multiple statements, system tables, table functions, foreign database | Reject | Existing AST policy suite passed | PASS |
| SEC-005 | Anonymous/wrong ETL service credential | Reject | Authentication failure | PASS |
| SEC-005 | Missing tenant/dataset/job scope | Reject | Scope validation error | PASS |
| SEC-005 | Wrong tenant, dataset, or job metadata | No result | Exact-scope matcher rejects each mismatch | PASS |
| SEC-006 | Loopback, IPv6 loopback, link-local metadata, private IP | Reject after DNS resolution | All blocked | PASS |
| SEC-006 | Public resolved destination | Allow | Accepted | PASS |
| SEC-006 | Administrator-approved private CIDR | Allow only exact allowlist | Accepted only with configured CIDR | PASS |
| SEC-007 | Missing credential-encryption key | Fail closed | Configuration exception; no fallback key | PASS |
| SEC-008 | Missing/invalid deployment profile or production placeholder | Startup failure | Runtime validators and source assertions passed | PASS |
| SEC-009 | Published development ports | Loopback-only | Compose scan finds no unqualified host publication | PASS |
| SEC-013 | ClickHouse password in URL/query parameters | Absent | HTTP Basic auth used; URL contains no password | PASS |
| SEC-013 | Exception contains credential text | Redact | Credential absent from result and logs | PASS |
| SEC-014 | Existing account plus invitation | Cannot reset password/role | Serializer rejects recovery path before mutation | PASS |
| SEC-014 | Wrong/anonymous actor accepts existing-user invitation | Reject | 401 | PASS |
| SEC-014 | Expired or replayed invitation | Reject | 400 | PASS |
| SEC-014 | Authenticated matching actor accepts once | Success | Membership activated and invitation consumed | PASS |
| SEC-014 | New invited identity registers | Success with invitation identity | New user created; no existing identity mutation | PASS |
| SEC-015 | Frontend bearer token calls ingestion callback | Reject | Service authentication required | PASS |
| SEC-015 | Wrong dataset/job/workspace tuple | 404 | Exact three-part lookup returns 404 | PASS |
| SEC-015 | Unknown physical/ownership field | Reject | 400 allowlist violation | PASS |
| SEC-015 | Illegal terminal transition | Reject | 409 | PASS |
| SEC-015 | Repeated identical callback | Idempotent success | 200; no save | PASS |
| SEC-015 | Malicious ClickHouse identifier | Reject before SQL construction | Identifier tests passed | PASS |

## Final commands and results

| Scope | Result |
| --- | --- |
| Query `pytest tests -q` | 50 passed; 32 existing + 18 new |
| Visualization `pytest visualization_api/tests -q` | 62 passed; 54 existing + 8 new |
| Voice selected contract/security files | 20 passed plus 5 subtests; 12 existing + 8 new |
| Auth invitation security | 2 passed |
| Workspace invitation security | 4 passed |
| ETL new security controls | 15 passed |
| ETL existing input/credential suites | 60 passed |
| ETL connector compatibility/security selection | Included in separate 46-pass run with the 15 new ETL tests |
| Python compileall | Passed |
| Query and Visualization `makemigrations --check --dry-run` | No changes detected |
| Disposable migration upgrades | Query 0002 to 0004 passed; Visualization zero to 0001 passed |
| `docker compose config --quiet` with non-secret test placeholders | Passed; Docker config-file access warnings only |

## Result classification

- **PRE-EXISTING FAILURES:** 0 in the 158-test relevant baseline. Broader Phase 0 AI/ETL failures and full-suite collection defects remain documented in `docs/audit/TEST_EXECUTION.md` and were not attributed to P0-A.
- **NEW FAILURES:** 0 final. One new embed-lifetime test initially called the wrong method name; it was corrected and the complete Visualization suite then passed 62/62.
- **FIXED FAILURES:** The audit's reproducible Voice 403 hint fallback is fixed and covered by the new denial tests.
- **NEW SECURITY TESTS PASSED:** 55.
- **NEW REGRESSIONS INTRODUCED:** 0 in the relevant suites.
