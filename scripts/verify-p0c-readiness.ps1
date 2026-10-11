param(
    [switch]$SkipOutages
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

function Invoke-Docker {
    param([string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & docker @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "Docker command failed: docker $($Arguments -join ' ')"
    }
    return ($output -join "`n")
}

function Invoke-Probe {
    param([string]$Url, [int]$TimeoutSeconds = 5)
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $raw = & curl.exe --silent --show-error --max-time $TimeoutSeconds --write-out "`nP0C_STATUS:%{http_code}" $Url 2>$null
    $curlExit = $LASTEXITCODE
    $timer.Stop()
    if ($curlExit -ne 0) { throw "HTTP transport failed for $Url (curl exit $curlExit)." }
    $text = $raw -join "`n"
    $match = [regex]::Match($text, '(?s)^(.*)\r?\nP0C_STATUS:(\d{3})$')
    if (-not $match.Success) { throw "HTTP probe output was malformed for $Url." }
    return [pscustomobject]@{
        Status = [int]$match.Groups[2].Value
        Body = $match.Groups[1].Value
        ElapsedSeconds = $timer.Elapsed.TotalSeconds
    }
}

function Wait-ProbeStatus {
    param([string]$Url, [int]$Expected, [int]$DeadlineSeconds = 90)
    $deadline = (Get-Date).AddSeconds($DeadlineSeconds)
    do {
        try {
            $probe = Invoke-Probe $Url
            if ($probe.Status -eq $Expected) { return $probe }
        }
        catch { }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "$Url did not return HTTP $Expected within $DeadlineSeconds seconds."
}

function Wait-ContainerHealthy {
    param([string]$Container, [int]$DeadlineSeconds = 180)
    $deadline = (Get-Date).AddSeconds($DeadlineSeconds)
    do {
        $state = (Invoke-Docker @("inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", $Container)).Trim()
        if ($state -in @("healthy", "running")) { return }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "$Container did not become healthy within $DeadlineSeconds seconds."
}

$httpServices = @(
    @{ Name = "api-gateway"; Base = "http://127.0.0.1:8000"; Prefix = "" },
    @{ Name = "auth-service"; Base = "http://127.0.0.1:8001"; Prefix = "" },
    @{ Name = "workspace-service"; Base = "http://127.0.0.1:8002"; Prefix = "" },
    @{ Name = "report-service"; Base = "http://127.0.0.1:8003"; Prefix = "" },
    @{ Name = "voice-service"; Base = "http://127.0.0.1:8004"; Prefix = "" },
    @{ Name = "ai-service"; Base = "http://127.0.0.1:8005"; Prefix = "" },
    @{ Name = "query-service"; Base = "http://127.0.0.1:8006"; Prefix = "" },
    @{ Name = "visualization-service"; Base = "http://127.0.0.1:8007"; Prefix = "" },
    @{ Name = "subscription-service"; Base = "http://127.0.0.1:8009"; Prefix = "" },
    @{ Name = "notification-service"; Base = "http://127.0.0.1:8010"; Prefix = "" },
    @{ Name = "etl-connector"; Base = "http://127.0.0.1:8101"; Prefix = "/api" },
    @{ Name = "etl-detector"; Base = "http://127.0.0.1:8102"; Prefix = "/api" },
    @{ Name = "etl-extractor"; Base = "http://127.0.0.1:8103"; Prefix = "/api" },
    @{ Name = "etl-transformer"; Base = "http://127.0.0.1:8104"; Prefix = "/api" },
    @{ Name = "etl-loader"; Base = "http://127.0.0.1:8105"; Prefix = "/api" },
    @{ Name = "etl-metadata"; Base = "http://127.0.0.1:8106"; Prefix = "/api" }
)

foreach ($service in $httpServices) {
    $healthUrl = $service.Base + $service.Prefix + "/health/"
    $readyUrl = $service.Base + $service.Prefix + "/ready/"
    $health = Wait-ProbeStatus $healthUrl 200
    $ready = Wait-ProbeStatus $readyUrl 200
    Write-Host "PASS $($service.Name): health=$($health.Status) ready=$($ready.Status)"
}

$workerHealth = (Invoke-Docker @("inspect", "--format", "{{.State.Health.Status}}", "notification-expiry-worker")).Trim()
if ($workerHealth -ne "healthy") { throw "Notification expiry worker health is $workerHealth." }
Write-Host "PASS notification-expiry-worker: heartbeat health=$workerHealth"

if ($SkipOutages) {
    Write-Host "P0-C health/readiness baseline passed; outage checks skipped by request."
    exit 0
}

$scenarios = @(
    @{ Name = "Redis"; Container = "redis"; Health = "http://127.0.0.1:8005/health/"; Ready = "http://127.0.0.1:8005/ready/" },
    @{ Name = "SurrealDB"; Container = "surrealdb"; Health = "http://127.0.0.1:8106/api/health/"; Ready = "http://127.0.0.1:8106/api/ready/" },
    @{ Name = "Metabase"; Container = "metabase"; Health = "http://127.0.0.1:8007/health/"; Ready = "http://127.0.0.1:8007/ready/" },
    @{ Name = "Query Service"; Container = "query-service"; Health = "http://127.0.0.1:8007/health/"; Ready = "http://127.0.0.1:8007/ready/" },
    @{ Name = "Workspace Service"; Container = "workspace-service"; Health = "http://127.0.0.1:8009/health/"; Ready = "http://127.0.0.1:8009/ready/" },
    @{ Name = "Kafka"; Container = "kafka"; Health = "http://127.0.0.1:8006/health/"; Ready = "http://127.0.0.1:8006/ready/" },
    @{ Name = "ClickHouse"; Container = "clickhouse"; Health = "http://127.0.0.1:8006/health/"; Ready = "http://127.0.0.1:8006/ready/" }
)

foreach ($scenario in $scenarios) {
    $stopped = $false
    try {
        Invoke-Docker @("compose", "stop", "--timeout", "20", $scenario.Container) | Out-Null
        $stopped = $true
        $failedReady = Wait-ProbeStatus $scenario.Ready 503 90
        $live = Wait-ProbeStatus $scenario.Health 200 30
        if ($failedReady.ElapsedSeconds -gt 8) {
            throw "$($scenario.Name) readiness response exceeded the bounded eight-second assertion."
        }
        $payload = $failedReady.Body | ConvertFrom-Json
        if ($payload.status -ne "not_ready" -or $payload.error.code -ne "service_not_ready") {
            throw "$($scenario.Name) did not return the standard readiness error envelope."
        }
        if ($failedReady.Body -match '(?i)password|secret|traceback|stack trace|\.env') {
            throw "$($scenario.Name) readiness response exposed sensitive diagnostic text."
        }
        Write-Host "PASS $($scenario.Name) outage: health=$($live.Status) ready=$($failedReady.Status) bounded=$([math]::Round($failedReady.ElapsedSeconds, 3))s"
    }
    finally {
        if ($stopped) {
            Invoke-Docker @("compose", "start", $scenario.Container) | Out-Null
            Wait-ContainerHealthy $scenario.Container
            Wait-ProbeStatus $scenario.Ready 200 180 | Out-Null
            Write-Host "PASS $($scenario.Name) recovery: ready=200"
        }
    }
}

Write-Host "P0-C health/readiness and seven live outage/recovery checks passed."
