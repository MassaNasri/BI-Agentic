param(
    [switch]$SkipFrontendInstall,
    [switch]$SkipFrontend,
    [switch]$SkipMigrations
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$EtlRoot = Join-Path $RepoRoot "etl-final"
$env:APP_ENV = "test"
$env:DJANGO_EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
$env:EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
$env:OPENROUTER_API_KEY = ""
$env:CREDENTIAL_SECRET_KEY = "biavora-p0c-test-only-credential-key"
$env:PYTHONHASHSEED = "0"
$env:PYTHONPATH = $RepoRoot.Path

function Invoke-Checked {
    param([string]$Name, [string]$WorkingDirectory, [string]$Command, [string[]]$Arguments)
    Write-Host "`n=== $Name ==="
    Push-Location $WorkingDirectory
    try {
        & $Command @Arguments
        if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
    }
    finally { Pop-Location }
}

Invoke-Checked "Python/static" $RepoRoot "python" @("scripts/p0c_static_check.py")
Invoke-Checked "Shared readiness/request IDs" $RepoRoot "python" @("-m", "pytest", "tests/test_health_readiness.py", "-q")
Invoke-Checked "API Gateway health/auth boundary" (Join-Path $RepoRoot "services/api-gateway") "python" @("manage.py", "test", "gateway", "--verbosity", "1")

Invoke-Checked "Query" (Join-Path $RepoRoot "services/query-service") "python" @("-m", "pytest", "tests", "-q")
Invoke-Checked "Visualization" (Join-Path $RepoRoot "services/visualization-service") "python" @("-m", "pytest", "visualization_api/tests", "-q")
Invoke-Checked "Voice" (Join-Path $RepoRoot "services/voice-service") "python" @("-m", "pytest", "voice_reports/tests_ai_trace_service.py", "voice_reports/tests_query_execute_metabase_fallback.py", "voice_reports/tests_query_service_contract.py", "voice_reports/tests_security_workspace_authorization.py", "-q")
Invoke-Checked "Report" (Join-Path $RepoRoot "services/report-service") "python" @("-m", "pytest", "voice_reports/tests_sql_normalization.py", "-q")
Invoke-Checked "Auth security" (Join-Path $RepoRoot "services/auth-service") "python" @("manage.py", "test", "users.tests_security_invitation", "--verbosity", "1")
Invoke-Checked "Workspace security" (Join-Path $RepoRoot "services/workspace-service") "python" @("manage.py", "test", "workspace.tests_security_invitation", "--verbosity", "1")
Invoke-Checked "Subscription smoke/security" (Join-Path $RepoRoot "services/subscription-service") "python" @("manage.py", "test", "subscription.tests", "--verbosity", "1")
Invoke-Checked "Notification smoke/security" (Join-Path $RepoRoot "services/notification-service") "python" @("manage.py", "test", "notification.tests", "--verbosity", "1")

$aiTests = @(
    "intent_extraction/tests.py", "llm_app/tests.py", "preprocessing_high/tests_llm_client.py",
    "preprocessing_high/tests_recovery.py", "reasoning_app/tests.py", "shared/tests_sql_review.py",
    "tests/test_bi_generalized_semantics_pipeline.py", "tests/test_bi_hardening.py",
    "tests/test_bi_semantic_layer.py", "tests/test_bi_semantic_reasoning_integration.py",
    "tests/test_bi_temporal_semantics.py", "tests/test_forecasting_pipeline.py",
    "tests/test_pipeline_integration.py", "tests/test_preprocessing_high_recovery.py",
    "tests/test_preprocessing_low_semantic_guard.py", "tests/test_tiered_resolution.py",
    "tests/test_value_index.py", "whisper_app/tests.py", "-q"
)
Invoke-Checked "AI deterministic" (Join-Path $RepoRoot "services/ai-service") "python" (@("-m", "pytest") + $aiTests)

$env:PYTHONPATH = $EtlRoot
Invoke-Checked "ETL shared models" $RepoRoot "python" @("-m", "pytest", "etl-final/shared/models", "etl-final/shared/security", "-q")
$sharedUtils = Get-ChildItem (Join-Path $EtlRoot "shared/utils") -Filter "test_*.py" | Where-Object { $_.Name -notin @("test_bronze_indexes.py", "test_kafka_validation_integration.py") }
foreach ($testFile in $sharedUtils) {
    Invoke-Checked "ETL shared/$($testFile.Name)" $RepoRoot "python" @("-m", "pytest", $testFile.FullName, "-q")
}
Invoke-Checked "ETL connector" (Join-Path $EtlRoot "connector-service/connector") "python" @("manage.py", "test", "--verbosity", "1")
Invoke-Checked "ETL extractor" $RepoRoot "python" @("-m", "pytest", "etl-final/extractor-service/extractor/engine", "-q")
Invoke-Checked "ETL transformer" $RepoRoot "python" @("-m", "pytest", "etl-final/transformer-service/transformer/engine", "-q")
Invoke-Checked "ETL loader" $RepoRoot "python" @("-m", "pytest", "etl-final/loader-service/loader/engine", "-q")
Invoke-Checked "ETL listener contracts" $RepoRoot "python" @("-m", "pytest", "etl-final/tests/test_p0_transform_loader_listeners.py", "-q")
Invoke-Checked "ETL detector Django" (Join-Path $EtlRoot "detector-service/detector") "python" @("manage.py", "test", "--verbosity", "1")
Invoke-Checked "ETL metadata Django" (Join-Path $EtlRoot "metadata-service/metadata") "python" @("manage.py", "test", "--verbosity", "1")

if (-not $SkipMigrations) { & (Join-Path $PSScriptRoot "check-migration-drift.ps1") }

if (-not $SkipFrontend) {
    $frontend = Join-Path $RepoRoot "frontend"
    if (-not $SkipFrontendInstall) { Invoke-Checked "Frontend clean install" $frontend "npm.cmd" @("ci", "--no-audit", "--no-fund") }
    Invoke-Checked "Frontend tests" $frontend "npm.cmd" @("test")
    Invoke-Checked "Frontend lint" $frontend "npm.cmd" @("run", "lint")
    Invoke-Checked "Frontend build" $frontend "npm.cmd" @("run", "build")
    Invoke-Checked "Frontend bundle policy" $RepoRoot "python" @("scripts/verify_frontend_bundle.py")
}

Write-Host "`nP0-C canonical offline test gate passed."
