#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ETL_ROOT="${PROJECT_ROOT}/etl-final"
export APP_ENV=test
export DJANGO_EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend
export EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend
export OPENROUTER_API_KEY=""
export CREDENTIAL_SECRET_KEY="biavora-p0c-test-only-credential-key"
export PYTHONHASHSEED=0
export PYTHONPATH="${PROJECT_ROOT}"

run_pytest() {
  local name="$1" workdir="$2"; shift 2
  echo; echo "=== ${name} ==="
  (cd "${workdir}" && python -m pytest "$@" -q)
}

cd "${PROJECT_ROOT}"
python scripts/p0c_static_check.py
run_pytest "Shared readiness/request IDs" "${PROJECT_ROOT}" tests/test_health_readiness.py
(cd "${PROJECT_ROOT}/services/api-gateway" && python manage.py test gateway --verbosity 1)
run_pytest "Query" "${PROJECT_ROOT}/services/query-service" tests
run_pytest "Visualization" "${PROJECT_ROOT}/services/visualization-service" visualization_api/tests
run_pytest "Voice" "${PROJECT_ROOT}/services/voice-service" voice_reports/tests_ai_trace_service.py voice_reports/tests_query_execute_metabase_fallback.py voice_reports/tests_query_service_contract.py voice_reports/tests_security_workspace_authorization.py
run_pytest "Report" "${PROJECT_ROOT}/services/report-service" voice_reports/tests_sql_normalization.py
(cd "${PROJECT_ROOT}/services/auth-service" && python manage.py test users.tests_security_invitation --verbosity 1)
(cd "${PROJECT_ROOT}/services/workspace-service" && python manage.py test workspace.tests_security_invitation --verbosity 1)
(cd "${PROJECT_ROOT}/services/subscription-service" && python manage.py test subscription.tests --verbosity 1)
(cd "${PROJECT_ROOT}/services/notification-service" && python manage.py test notification.tests --verbosity 1)

run_pytest "AI deterministic" "${PROJECT_ROOT}/services/ai-service" \
  intent_extraction/tests.py llm_app/tests.py preprocessing_high/tests_llm_client.py preprocessing_high/tests_recovery.py \
  reasoning_app/tests.py shared/tests_sql_review.py tests/test_bi_generalized_semantics_pipeline.py tests/test_bi_hardening.py \
  tests/test_bi_semantic_layer.py tests/test_bi_semantic_reasoning_integration.py tests/test_bi_temporal_semantics.py \
  tests/test_forecasting_pipeline.py tests/test_pipeline_integration.py tests/test_preprocessing_high_recovery.py \
  tests/test_preprocessing_low_semantic_guard.py tests/test_tiered_resolution.py tests/test_value_index.py whisper_app/tests.py

export PYTHONPATH="${ETL_ROOT}"
run_pytest "ETL shared models" "${PROJECT_ROOT}" etl-final/shared/models etl-final/shared/security
for test_file in "${ETL_ROOT}"/shared/utils/test_*.py; do
  case "$(basename "${test_file}")" in test_bronze_indexes.py|test_kafka_validation_integration.py) continue;; esac
  run_pytest "ETL shared/$(basename "${test_file}")" "${PROJECT_ROOT}" "${test_file}"
done
(cd "${ETL_ROOT}/connector-service/connector" && python manage.py test --verbosity 1)
run_pytest "ETL extractor" "${PROJECT_ROOT}" etl-final/extractor-service/extractor/engine
run_pytest "ETL transformer" "${PROJECT_ROOT}" etl-final/transformer-service/transformer/engine
run_pytest "ETL loader" "${PROJECT_ROOT}" etl-final/loader-service/loader/engine
run_pytest "ETL listeners" "${PROJECT_ROOT}" etl-final/tests/test_p0_transform_loader_listeners.py
(cd "${ETL_ROOT}/detector-service/detector" && python manage.py test --verbosity 1)
(cd "${ETL_ROOT}/metadata-service/metadata" && python manage.py test --verbosity 1)

"${SCRIPT_DIR}/check-migration-drift.sh"
(cd "${PROJECT_ROOT}/frontend" && npm ci --no-audit --no-fund && npm test && npm run lint && npm run build)
python scripts/verify_frontend_bundle.py
echo; echo "P0-C canonical offline test gate passed."
