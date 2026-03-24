-- List user tables for truncation in target ClickHouse database.
-- Placeholder {{CLICKHOUSE_DATABASE}} is replaced by reset_all_databases.sh.

SELECT
    name
FROM system.tables
WHERE database = '{{CLICKHOUSE_DATABASE}}'
  AND is_temporary = 0
  AND engine NOT IN ('View', 'MaterializedView', 'LiveView', 'WindowView')
ORDER BY name
FORMAT TSV;
