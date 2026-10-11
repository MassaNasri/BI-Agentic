#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
export APP_ENV=test
export DJANGO_EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend
export PYTHONPATH="${PROJECT_ROOT}"

projects=(
  services/auth-service
  services/workspace-service
  services/subscription-service
  services/notification-service
  services/voice-service
  services/query-service
  services/visualization-service
  services/report-service
)

for project in "${projects[@]}"; do
  echo "Checking migration drift: ${project}"
  (cd "${PROJECT_ROOT}/${project}" && python manage.py makemigrations --check --dry-run --skip-checks)
done

echo "Migration drift gate passed for all eight P0-B configurations."
