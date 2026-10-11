param(
    [string]$EnvFile = ".env",
    [string]$ComposeFile = "docker-compose.yml"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

function Invoke-DockerChecked {
    param([string[]]$DockerArguments)

    & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed with exit code $LASTEXITCODE`: docker $($DockerArguments -join ' ')"
    }
}

function Read-DotEnvKeys {
    param([string]$Path)
    $values = @{}
    $lineNo = 0
    foreach ($line in Get-Content -LiteralPath $Path) {
        $lineNo++
        if ($line -match '^\s*#' -or $line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            continue
        }
        $key = $Matches[1]
        $value = $Matches[2].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = [pscustomobject]@{
            Line = $lineNo
            Empty = ($value.Length -eq 0)
            Placeholder = ($value -match '^(?i:CHANGE_ME|CHANGE_ME_.*|YOUR_SECRET_HERE|your_password|example|placeholder|replace-with-.+|replace_with_.+|changeme|change-me.*|todo|<secret>|undefined|null|none|StrongPassword123|etl_pass123|root)$')
        }
    }
    return $values
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing $EnvFile. Copy .env.example to .env and fill required values."
}

$envValues = Read-DotEnvKeys -Path $EnvFile
$composeText = Get-Content -LiteralPath $ComposeFile -Raw
$required = [regex]::Matches($composeText, '\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?])[^}]*)?\}') |
    ForEach-Object {
        $name = $_.Groups[1].Value
        $op = $_.Groups[2].Value
        if ($op -eq ':?' -or $op -eq '?' -or [string]::IsNullOrEmpty($op)) { $name }
    } |
    Sort-Object -Unique

$problems = @()
foreach ($name in $required) {
    if (-not $envValues.ContainsKey($name)) {
        $problems += "$name is missing"
        continue
    }
    if ($envValues[$name].Empty) {
        $problems += "$name is empty"
    }
    if ($envValues[$name].Placeholder) {
        $problems += "$name still has a placeholder value"
    }
}

if ($problems.Count -gt 0) {
    Write-Host "Runtime configuration validation failed:" -ForegroundColor Red
    $problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    throw "Runtime configuration contains missing, empty, or placeholder values."
}

Write-Host "Required Compose interpolation variables are present and non-empty:" -ForegroundColor Green
$required | ForEach-Object { Write-Host "  - $_=********" }

Write-Host "Running Docker Compose config validation..."
Invoke-DockerChecked -DockerArguments @("compose", "-f", $ComposeFile, "config", "--quiet")

Write-Host "Services:"
Invoke-DockerChecked -DockerArguments @("compose", "-f", $ComposeFile, "config", "--services")

Write-Host "Runtime configuration validation completed without printing secret values." -ForegroundColor Green
