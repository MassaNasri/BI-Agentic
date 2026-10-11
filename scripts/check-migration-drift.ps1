$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$env:APP_ENV = "test"
$env:DJANGO_EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
$env:PYTHONPATH = $RepoRoot.Path

$projects = @(
    "services/auth-service",
    "services/workspace-service",
    "services/subscription-service",
    "services/notification-service",
    "services/voice-service",
    "services/query-service",
    "services/visualization-service",
    "services/report-service"
)

foreach ($project in $projects) {
    Push-Location (Join-Path $RepoRoot $project)
    try {
        Write-Host "Checking migration drift: $project"
        & python manage.py makemigrations --check --dry-run --skip-checks
        if ($LASTEXITCODE -ne 0) { throw "Migration drift detected in $project" }
    }
    finally { Pop-Location }
}

Write-Host "Migration drift gate passed for all eight P0-B configurations."
