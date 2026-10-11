# P0-A modification ledger

This ledger records source/configuration files intentionally created or edited for P0-A. The repository was already extensively dirty; unrelated user work listed in `P0A_BASELINE.md` was preserved. No file was intentionally deleted, no history was rewritten, and no commit was created.

## Root configuration

| File | Action | Purpose |
| --- | --- | --- |
| `.env.example` | Modified | Document explicit profile, ETL identity/callback/encryption keys, and destination CIDRs |
| `docker-compose.yml` | Modified | Loopback publications, explicit profiles, and required ETL credentials |
| `etl-final/docker-compose.yml` | Modified | Loopback publications and explicit ETL security configuration |

## Service runtime settings

| File | Action | Purpose |
| --- | --- | --- |
| `services/api-gateway/service_config/settings.py` | Modified | Fail-closed profile/secret validation |
| `services/ai-service/backend/settings.py` | Modified | Fail-closed profile/secret validation |
| `services/auth-service/service_config/settings.py` | Modified | Fail-closed profile/secret validation |
| `services/notification-service/service_config/settings.py` | Modified | Fail-closed profile/secret validation |
| `services/query-service/service_config/settings.py` | Modified | Runtime validation plus callback/ETL keys |
| `services/report-service/service_config/settings.py` | Modified | Fail-closed profile/secret validation |
| `services/subscription-service/service_config/settings.py` | Modified | Fail-closed profile/secret validation |
| `services/visualization-service/service_config/settings.py` | Modified | Fail-closed profile/secret validation |
| `services/voice-service/service_config/settings.py` | Modified | Fail-closed profile/secret validation |
| `services/workspace-service/service_config/settings.py` | Modified | Fail-closed profile/secret validation |

## SEC-001 Voice authorization

| File | Action | Purpose |
| --- | --- | --- |
| `services/voice-service/voice_reports/infrastructure/workspace_client.py` | Modified | Strict authorization result model without hint fallback |
| `services/voice-service/voice_reports/infrastructure/auth_context.py` | Modified | Fail-closed result-to-HTTP guard |
| `services/voice-service/voice_reports/dashboard_builder_views.py` | Modified | Require verified workspace context |
| `services/voice-service/voice_reports/views.py` | Modified | Require verified workspace and Query-definition chart adapter |
| `services/voice-service/voice_reports/application/orchestration_service.py` | Modified | Require verified workspace in background orchestration |
| `services/voice-service/voice_reports/tests_security_workspace_authorization.py` | Created | Denial/outage/malformed/positive security tests |

## SEC-014 invitations

| File | Action | Purpose |
| --- | --- | --- |
| `services/auth-service/users/serializers.py` | Modified | Prohibit invitation-based mutation of an existing account |
| `services/auth-service/users/tests_security_invitation.py` | Created | Existing/new identity tests |
| `services/workspace-service/workspace/views.py` | Modified | Exact authenticated identity, expiry/replay checks, and row lock |
| `services/workspace-service/workspace/tests_security_invitation.py` | Created | Wrong/expired/replayed/matching acceptance tests |

## SEC-003, SEC-013, SEC-015 Query

| File | Action | Purpose |
| --- | --- | --- |
| `services/query-service/database/models.py` | Modified | Ingestion job and authorized-query models |
| `services/query-service/database/migrations/0003_database_ingestion_job_id.py` | Created | Safe nullable/backfill/final ingestion UUID migration |
| `services/query-service/database/migrations/0004_authorizedquerydefinition.py` | Created | Query-definition ownership migration |
| `services/query-service/database/internal_authentication.py` | Created | Ingestion service authentication |
| `services/query-service/database/views.py` | Modified | Scoped upload caller and versioned callback state machine |
| `services/query-service/database/urls.py` | Modified | Remove legacy status route |
| `services/query-service/database/utils.py` | Modified | Credential-safe HTTP auth and identifier validation/quoting |
| `services/query-service/service_config/urls.py` | Modified | Add versioned internal callback URL |
| `services/query-service/query_api/views.py` | Modified | Create/resolve authorized Query definitions and fail closed |
| `services/query-service/query_api/urls.py` | Modified | Query-definition endpoints |
| `services/query-service/tests/test_ingestion_callback_security.py` | Created | Service identity/binding/state tests |
| `services/query-service/tests/test_clickhouse_credential_redaction.py` | Created | URL/log/identifier regression tests |
| `services/query-service/tests/test_security_configuration.py` | Modified | Explicit-profile and production-placeholder assertions |

## SEC-002 and SEC-003 Visualization

| File | Action | Purpose |
| --- | --- | --- |
| `services/visualization-service/visualization_api/models.py` | Created | Application-owned Metabase object registry |
| `services/visualization-service/visualization_api/migrations/0001_visualizationobjectownership.py` | Created | Ownership registry migration |
| `services/visualization-service/visualization_api/services/query_authorization.py` | Created | Query-definition resolution with workspace equality |
| `services/visualization-service/visualization_api/services/jwt_embedding.py` | Modified | Five-minute embed-token maximum |
| `services/visualization-service/visualization_api/services/metabase_service.py` | Modified | Dashboard cleanup support |
| `services/visualization-service/visualization_api/views.py` | Modified | Ownership gates and query-reference-only chart creation |
| `services/visualization-service/visualization_api/tests/test_security_ownership_and_query_reference.py` | Created | Cross-tenant/raw-SQL/embed tests |

## SEC-005, SEC-006, SEC-007 ETL

| File | Action | Purpose |
| --- | --- | --- |
| `etl-final/shared/security/__init__.py` | Created | Shared security package |
| `etl-final/shared/security/internal_auth.py` | Created | Internal service identity and exact request scope |
| `etl-final/shared/security/destination_policy.py` | Created | DNS-resolved egress policy |
| `etl-final/shared/security/runtime_config.py` | Created | Explicit deployment profile/startup validation |
| `etl-final/shared/security/test_security_controls.py` | Created | ETL identity/scope/SSRF/config tests |
| `etl-final/shared/utils/credential_encryption.py` | Modified | Remove fallback encryption key |
| `etl-final/shared/utils/test_credential_encryption.py` | Modified | Supply explicit test-only singleton key |
| `etl-final/shared/utils/surreal_client.py` | Modified | Remove source-known metadata credentials and sanitize failures |
| `etl-final/connector-service/connector/connector/settings.py` | Modified | ETL runtime security validation |
| `etl-final/connector-service/connector/etl_engine/views.py` | Modified | Authenticate/scope ingestion APIs and propagate scope |
| `etl-final/connector-service/connector/etl_engine/utils.py` | Modified | Enforce destination policy and bounded DB timeouts |
| `etl-final/connector-service/connector/etl_engine/test_api_validation.py` | Modified | Exercise validation under the new internal contract |
| `etl-final/detector-service/detector/detector/settings.py` | Modified | ETL runtime security validation |
| `etl-final/detector-service/detector/core/views.py` | Modified | Authenticate/scope manual detector API |
| `etl-final/extractor-service/extractor/extractor/settings.py` | Modified | Runtime and encryption-key validation |
| `etl-final/extractor-service/extractor/engine/views.py` | Modified | Authenticate/scope APIs and pin validated destination IP |
| `etl-final/transformer-service/transformer/transformer/settings.py` | Modified | ETL runtime security validation |
| `etl-final/transformer-service/transformer/engine/views.py` | Modified | Authenticate/scope transformation/quarantine APIs |
| `etl-final/loader-service/loader/loader/settings.py` | Modified | ETL runtime security validation |
| `etl-final/loader-service/loader/engine/views.py` | Modified | Authenticate/scope loader API |
| `etl-final/loader-service/loader/engine/clickhouse_client.py` | Modified | Remove runtime password fallback |
| `etl-final/loader-service/loader/engine/kafka_listener.py` | Modified | Remove runtime password fallback |
| `etl-final/metadata-service/metadata/metadata/settings.py` | Modified | ETL runtime security validation |
| `etl-final/metadata-service/metadata/api/views.py` | Modified | Authenticate and scope metadata/lineage/quality reads |
| `etl-final/metadata-service/metadata/api/query_builder.py` | Modified | Allowlisted, tenant/dataset/job-scoped metadata queries |
| `etl-final/Test-File/verify_pipeline.py` | Modified | Require externally supplied validation credentials |
| `etl-final/Test-File/run_full_validation.py` | Modified | Remove source-known ClickHouse/Surreal validation credentials |
| `etl-final/Test-File/validate_pipeline.py` | Modified | Require external ClickHouse validation credentials |
| `etl-final/Test-File/test_full_pipeline.py` | Modified | Remove source-known ClickHouse validation credentials |

## Evidence documents

| File | Action | Purpose |
| --- | --- | --- |
| `docs/remediation/P0A_BASELINE.md` | Created/updated | Preserve starting identity, dirty state, constraints, and baseline tests |
| `docs/remediation/SECRET_ROTATION_CHECKLIST.md` | Created | Manual SEC-004 rotation plan without values |
| `docs/remediation/P0A_IMPLEMENTATION_REPORT.md` | Created | Issue-by-issue implementation and residual risk |
| `docs/remediation/P0A_SECURITY_TEST_MATRIX.md` | Created | Attack/failure expectations and final results |
| `docs/remediation/P0A_MODIFICATION_LEDGER.md` | Created | This complete P0-A ledger |

## Verification-only artifacts

A temporary migration runner and disposable SQLite databases were created solely under the remediation/temp locations to verify migration upgrades. The runner was deleted after execution and is not part of the source modification set. No application data was read, reset, or deleted.
