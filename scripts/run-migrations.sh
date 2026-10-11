#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${1:-${PROJECT_ROOT}/docker-compose.yml}"

# The shared PostgreSQL layout is retained for P0-B. Running the owning services
# one at a time prevents concurrent web/worker startup from racing migrations.
migration_services=(
  auth-service
  workspace-service
  subscription-service
  notification-service
  voice-service
  query-service
  visualization-service
  report-service
)

cd "${PROJECT_ROOT}"
for service in "${migration_services[@]}"; do
  echo "Applying reviewed migrations for ${service}..."
  docker compose -f "${COMPOSE_FILE}" run --rm --no-deps \
    "${service}" python manage.py migrate --noinput
done

echo "All serialized PostgreSQL migration jobs completed."
