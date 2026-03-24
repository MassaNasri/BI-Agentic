#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "Building microservice images..."
docker compose -f "${PROJECT_ROOT}/docker-compose.yml" build

echo "Starting microservices and infrastructure..."
docker compose -f "${PROJECT_ROOT}/docker-compose.yml" up -d

echo
echo "External services (not managed by docker-compose):"
echo "  PostgreSQL: localhost:5432"
echo "  Metabase:   http://127.0.0.1:3000"
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
