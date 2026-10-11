# P1-R Acceptance Audit

Date: 2026-10-11  
Scope: one-time/on-demand snapshot ingestion only. CDC, scheduling, offsets, and persistent source connections were not implemented.

## Starting state

The run started on `main`, tracking `origin/main`, one commit ahead:

```text
## main...origin/main [ahead 1]
```

The worktree already contained extensive user-owned modified, deleted, and untracked files across services, ETL, frontend, documentation, and generated Python caches. Representative pre-existing entries included `.gitignore`, `README.md`, most service settings/routes, ETL tests, frontend pages, deleted historical reports, and untracked remediation documents. No reset, checkout, clean, or unrelated revert was performed. All work was applied around that state.

## Evidence available at entry

The prior P1 reports recorded connector/registry implementation, live PostgreSQL/MySQL/SQLite/ClickHouse checks, one public SQLite E2E, 18 shared tests, 67 query tests, 218 extractor tests with 5 skips, 8 loader tests with 1 skip, 134 connector tests, 19 frontend tests, and 24 focused CSV tests. They also recorded three gaps: no MariaDB live run, no SQL Server/Oracle live run, and first-table-only dataset browsing after a multi-table snapshot.

The repository and current runtime were treated as authoritative; earlier reports were context only.

## Runtime topology exercised

```text
Authenticated public API
  -> API gateway
  -> Query service
  -> Connector service
  -> Kafka load_requests
  -> Extractor
  -> Kafka raw_data
  -> Transformer
  -> Kafka transformed/load rows
  -> Loader
  -> BIAVORA ClickHouse
  -> Query dataset status / imported tables / schema / preview
```

Required final runtime services were `api-gateway`, `query-service`, `etl-connector`, `etl-extractor`, `etl-transformer`, `etl-loader`, `kafka`, and destination `clickhouse`. All eight were healthy at the final gate.

Disposable sources were created from `etl-final/tests/integration/docker-compose.p1-optional.yml`: PostgreSQL 18.3, MySQL 8.4, MariaDB 11.8, and a logically separate ClickHouse source. SQL Server and Oracle profiles also render reproducibly but their images were not cached.

## Environment and network controls

- `host.docker.internal` resolved inside the connector/extractor acceptance runtime to `192.168.65.254` through the Compose host-gateway mapping.
- Local `.env` uses only `192.168.65.254/32` in `ETL_APPROVED_DESTINATION_CIDRS`; production defaults were not broadened.
- `.env.example` explains that the address must be resolved inside the connector/extractor and documents exact `/32` use.
- During ClickHouse source acceptance, Docker Desktop's published-port hairpin became intermittent. The disposable source was attached to the application network and its current `172.19.0.15/32` was added temporarily. After the successful run, that allowance was removed and the services were recreated with only the host-gateway `/32`.
- No RFC1918-wide rule and no `0.0.0.0/0` rule was used.
- Test credentials remained in ignored local configuration and were never written to a report.

## Gaps found and corrected

1. Multi-table jobs loaded all tables but schema/preview exposed only the first. A table-aware `source_tables` lifecycle, opaque selectors, per-table schema/preview, aggregate completion, all-table cleanup, frontend selector, authorization, and compatibility fallback were implemented.
2. Empty tables lacked a deterministic end-to-end signal. Extractor schema-only messages now propagate through transformer and loader so the physical zero-row table is created and can complete without pretending rows exist.
3. PostgreSQL SELECT-only users could not always see PK constraints through `information_schema`; a `pg_catalog` fallback was added.
4. MariaDB SELECT-only PK discovery received a `COLUMN_KEY='PRI'` fallback. MySQL constraint joins were tightened by table name.
5. ClickHouse keyset pagination used named parameters but the extractor coerced them to tuples. Mapping parameters are now preserved and ClickHouse supplies `%(last_pk)s` correctly.
6. Kafka validation rejected legitimate schema-only empty-table events. It now accepts zero rows only with `schema_only=true` and a non-empty column schema.
7. Driver errors and destination policy failures were normalized for DNS, refusal, auth, database, permission, and TLS cases without returning raw diagnostics.
8. A legacy single-table status test exposed that mocked `source_tables` values and singular status wording were no longer compatible. The normalization helper now ignores non-list metadata and preserves singular legacy text.

## Live acceptance summary

- CSV: user-provided manual acceptance retained; focused automated regression 24/24.
- PostgreSQL: public full E2E PASS, 2,512 aggregate rows across 8/0/2,500/4-row tables.
- MySQL: public full E2E PASS, same deterministic counts.
- MariaDB: independent public full E2E PASS, same deterministic counts.
- SQLite: public upload full E2E PASS, 2,503 aggregate rows across 3/0/2,500-row tables plus rejection tests.
- ClickHouse external source: public full E2E PASS, 2,512 aggregate rows across 8/0/2,500/4-row tables.
- SQL Server: implementation, driver, registry, tests, and profile PASS; live BLOCKED_EXTERNAL because the image was not cached and the requested download/start was declined.
- Oracle: implementation, driver, registry, tests, and profile PASS; live BLOCKED_EXTERNAL for the same reason.

## Cleanup and final state

Public harnesses deleted their datasets. A final audit found ten orphan destination/staging tables from earlier failed/retried P1-R attempts in dedicated workspace `99101`; their exact names were enumerated before deletion. Final checks returned:

```text
P1-R query-service records (workspaces 99101, 99992): 0
P1-R destination ClickHouse tables: 0
P1-R temporary SQLite files: 0
Disposable p1r-* containers: 0
```

The disposable source containers and isolated integration network were removed. Reproducible Compose, seed, and harness definitions remain in source control.

## Audit conclusion

The known P1 browsing limitation is resolved, all mandatory core engines completed a real public gateway-to-ClickHouse flow, regressions and security gates pass, and final runtime health/log checks pass. SQL Server and Oracle remain explicitly optional live-runtime gaps, not implementation failures. The release interpretation is GREEN under the supplied optional-enterprise-connector rule.
