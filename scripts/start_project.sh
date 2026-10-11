#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Copy .env.example to .env and fill required values." >&2
  exit 1
fi

echo "Validating Docker Compose configuration with the automatically loaded .env..."
docker compose -f "${PROJECT_ROOT}/docker-compose.yml" config --quiet

echo "Building microservice images..."
docker compose -f "${PROJECT_ROOT}/docker-compose.yml" build

echo "Applying reviewed migrations serially..."
"${SCRIPT_DIR}/run-migrations.sh" "${PROJECT_ROOT}/docker-compose.yml"

echo "Starting microservices and infrastructure after migrations..."
docker compose -f "${PROJECT_ROOT}/docker-compose.yml" up -d

echo "Service status:"
docker compose -f "${PROJECT_ROOT}/docker-compose.yml" ps

echo
echo "External services:"
echo "  PostgreSQL: localhost:5432"
echo "  Metabase:   http://127.0.0.1:3000 (managed by docker-compose)"
echo
echo "Microservice URLs:"
echo "  API Gateway:            http://localhost:8000"
echo "  Auth Service:           http://localhost:8001"
echo "  Workspace Service:      http://localhost:8002"
echo "  Report Service:         http://localhost:8003"
echo "  Voice Service:          http://localhost:8004"
echo "  AI Service:             http://localhost:8005"
echo "  Query Service:          http://localhost:8006"
echo "  Visualization Service:  http://localhost:8007"
echo
echo "Infrastructure URLs:"
echo "  ClickHouse HTTP:        http://localhost:8123"
echo "  Kafka Broker:           localhost:9092"
echo "  Zookeeper:              localhost:2181"
echo
echo "Diagnostics:"
echo "  docker compose ps"
echo "  docker compose logs --tail=150"
