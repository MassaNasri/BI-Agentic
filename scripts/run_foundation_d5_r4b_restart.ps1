param([string]$RunId = '20261110a', [switch]$Resume)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$validation = (Resolve-Path (Join-Path $repo '..\biavora-foundation-d-r4b-validation')).Path
$environment = Join-Path $validation 'fixture.env'
$compose = @('compose', '--project-name', 'biavora_d5_r4b', '--env-file', $environment,
             '-f', (Join-Path $repo 'docker-compose.cdc-local.yml'))
$mountScripts = "${PSScriptRoot}:/acceptance:ro"
$mountEvidence = "${validation}:/evidence"

function Invoke-DockerChecked([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed with exit code $LASTEXITCODE" }
}

function Invoke-Probe([string]$Phase, [string]$Component) {
    $arguments = @('run', '--rm', '--network', 'biavora_d5_r4b_default',
                   '--env-file', $environment, '-e', 'CDC_FIXTURE_INTERNAL=1',
                   '-e', 'CDC_CONNECT_URL=http://connect:8083',
                   '-v', $mountScripts, '-v', $mountEvidence,
                   '--entrypoint', 'python', 'biavora-d5-r3-verifier:local',
                   '/acceptance/verify_foundation_d5_r4b.py',
                   '--env-file', '/evidence/fixture.env', '--case', 'restart',
                   '--phase', $Phase, '--component', $Component, '--run-id', $RunId)
    Invoke-DockerChecked $arguments
}

Push-Location $repo
try {
    if (-not $Resume) { Invoke-Probe 'setup' 'normalizer' }
    foreach ($component in @('normalizer', 'transformer', 'loader', 'query', 'connect', 'controller')) {
        if ($Resume) {
            $state = Get-Content (Join-Path $validation "d5-r4b-restart-$RunId.json") -Raw | ConvertFrom-Json
            if ($state.components.$component.result -eq 'PASS') { continue }
        }
        Write-Output "R4B_RESTART_BEGIN $component"
        Invoke-Probe 'pre' $component
        Invoke-DockerChecked ($compose + @('stop', $component))
        $needsRestore = $true
        try {
            if ($component -in @('normalizer', 'transformer', 'loader')) {
                Invoke-Probe 'inject' $component
            }
            Invoke-DockerChecked ($compose + @('start', $component))
            $needsRestore = $false
            Invoke-Probe 'post' $component
            Write-Output "R4B_RESTART_PASS $component"
        } finally {
            if ($needsRestore) { Invoke-DockerChecked ($compose + @('start', $component)) }
        }
    }
} finally {
    Pop-Location
}
