# Optional SQL Server and Oracle P1 integration profile

The main P1 verification does not claim live SQL Server or Oracle coverage.
These services are optional because their images are large and SQL Server also
requires explicit EULA acceptance. The connector driver construction, quoting,
pagination, TLS behavior, and Oracle service-name/TCPS behavior are covered by
unit/contract tests regardless.

Use test-only passwords and, for reproducibility beyond the versioned default
tags, set `P1_MSSQL_IMAGE` and `P1_ORACLE_IMAGE` to registry digests.

```powershell
$env:P1_MSSQL_SA_PASSWORD = '<strong test-only password>'
$env:P1_ORACLE_PASSWORD = '<strong test-only password>'
$env:P1_ORACLE_APP_PASSWORD = '<strong test-only password>'

docker compose -f docker-compose.p1-optional.yml --profile p1-mssql up -d p1-mssql
docker compose -f docker-compose.p1-optional.yml --profile p1-oracle up -d p1-oracle
```

Use `ETL_APPROVED_DESTINATION_CIDRS` to allow only the Compose test-network CIDR,
seed the edge-case table described in `P1_MULTI_DATABASE_TEST_MATRIX.md`, and
exercise the connector endpoints. Never broaden the destination policy merely
to make these tests pass.
