param(
    [bool]$Detached = $true
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$envFile = ".env"
$composeFile = "docker-compose.yml"

function Invoke-DockerChecked {
    param([string[]]$DockerArguments)

    & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed with exit code $LASTEXITCODE`: docker $($DockerArguments -join ' ')"
    }
}

if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Missing $envFile. Run 'Copy-Item .env.example .env', then configure every required value."
}

& (Join-Path $PSScriptRoot "verify-runtime-config.ps1") -EnvFile $envFile -ComposeFile $composeFile

Write-Host "Building microservice images..."
Invoke-DockerChecked -DockerArguments @("compose", "-f", $composeFile, "build")

& (Join-Path $PSScriptRoot "run-migrations.ps1") -ComposeFile $composeFile

$composeArgs = @("compose", "-f", $composeFile, "up")
if ($Detached) {
    $composeArgs += "-d"
}

Write-Host "Starting stack after successful serialized migrations..."
Invoke-DockerChecked -DockerArguments $composeArgs

Write-Host "Service status:"
Invoke-DockerChecked -DockerArguments @("compose", "-f", $composeFile, "ps")

Write-Host ""
Write-Host "Useful diagnostics:"
Write-Host "  docker compose ps"
Write-Host "  docker compose logs --tail=150"
