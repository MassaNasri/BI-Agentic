param(
    [string]$ComposeFile = "docker-compose.yml"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

# The shared PostgreSQL layout is retained for P0-B. Running the owning services
# one at a time prevents concurrent web/worker startup from racing migrations.
$migrationServices = @(
    "auth-service",
    "workspace-service",
    "subscription-service",
    "notification-service",
    "voice-service",
    "query-service",
    "visualization-service",
    "report-service"
)

foreach ($service in $migrationServices) {
    Write-Host "Applying reviewed migrations for $service..."
    & docker compose -f $ComposeFile run --rm --no-deps $service python manage.py migrate --noinput
    if ($LASTEXITCODE -ne 0) {
        throw "Migration failed for $service with exit code $LASTEXITCODE. Service startup is blocked."
    }
}

Write-Host "All serialized PostgreSQL migration jobs completed."
