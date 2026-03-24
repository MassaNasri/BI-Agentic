#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env.microservices"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}"
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required but not installed."
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required but not installed."
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

echo "Resetting PostgreSQL data on ${DB_HOST}:${DB_PORT}/${DB_NAME}..."
PGPASSWORD="${DB_PASSWORD}" psql \
  -v ON_ERROR_STOP=1 \
  -h "${DB_HOST}" \
  -p "${DB_PORT}" \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  -f "${SCRIPT_DIR}/clear_postgres.sql"

echo "Collecting ClickHouse tables in ${CLICKHOUSE_DATABASE}..."
TABLE_LIST_QUERY="$(sed "s/{{CLICKHOUSE_DATABASE}}/${CLICKHOUSE_DATABASE}/g" "${SCRIPT_DIR}/clear_clickhouse.sql")"
CLICKHOUSE_TABLES="$(
  curl -sS --fail \
    -u "${CLICKHOUSE_USER}:${CLICKHOUSE_PASSWORD}" \
    "http://${CLICKHOUSE_HOST}:${CLICKHOUSE_PORT}/?database=${CLICKHOUSE_DATABASE}" \
    --data-binary "${TABLE_LIST_QUERY}"
)"

if [[ -z "${CLICKHOUSE_TABLES//[[:space:]]/}" ]]; then
  echo "No ClickHouse tables to truncate in ${CLICKHOUSE_DATABASE}."
else
  while IFS= read -r table_name; do
    [[ -z "${table_name}" ]] && continue
    truncate_sql="TRUNCATE TABLE \`${CLICKHOUSE_DATABASE}\`.\`${table_name}\`;"
    curl -sS --fail \
      -u "${CLICKHOUSE_USER}:${CLICKHOUSE_PASSWORD}" \
      "http://${CLICKHOUSE_HOST}:${CLICKHOUSE_PORT}/?database=${CLICKHOUSE_DATABASE}" \
      --data-binary "${truncate_sql}" >/dev/null
    echo "Truncated ClickHouse table: ${CLICKHOUSE_DATABASE}.${table_name}"
  done <<< "${CLICKHOUSE_TABLES}"
fi

echo "All databases cleared successfully."
