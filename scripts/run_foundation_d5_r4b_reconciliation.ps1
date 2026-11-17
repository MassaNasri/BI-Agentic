param([string]$RunId = '20261110b', [switch]$Resume, [switch]$MatchOnly)

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

function Invoke-Probe([string]$Phase) {
    Invoke-DockerChecked @('run', '--rm', '--network', 'biavora_d5_r4b_default',
        '--env-file', $environment, '-e', 'CDC_FIXTURE_INTERNAL=1',
        '-e', 'CDC_CONNECT_URL=http://connect:8083', '-v', $mountScripts,
        '-v', $mountEvidence, '--entrypoint', 'python',
        'biavora-d5-r3-verifier:local', '/acceptance/verify_foundation_d5_r4b.py',
        '--env-file', '/evidence/fixture.env', '--case', 'recovery',
        '--phase', $Phase, '--run-id', $RunId)
}

Push-Location $repo
try {
    if ($MatchOnly) {
        Invoke-Probe 'refresh_match'
        Invoke-DockerChecked ($compose + @('restart', 'controller'))
        Invoke-Probe 'match_restart'
        $state = Get-Content (Join-Path $validation "d5-r4b-restart-$RunId.json") -Raw | ConvertFrom-Json
        $pipelineId = $state.candidate.pipeline_id
        $code = "from integration.cdc_reseed import cutover_candidate; cutover_candidate('$pipelineId')"
        Invoke-DockerChecked ($compose + @('exec', '-T', 'query', 'python', 'manage.py',
                                           'shell', '-c', $code))
        Invoke-Probe 'cutover_verify'
        return
    }
    if (-not $Resume) {
        Invoke-DockerChecked ($compose + @('stop', 'controller'))
        $controllerStopped = $true
        try {
            Invoke-Probe 'candidate'
        } finally {
            Invoke-DockerChecked ($compose + @('start', 'controller'))
            $controllerStopped = $false
        }
        Invoke-Probe 'candidate_post'
    }
    Invoke-DockerChecked ($compose + @('stop', 'loader'))
    $loaderStopped = $true
    try {
        Invoke-Probe 'watermark_request'
        Invoke-DockerChecked ($compose + @('stop', 'controller'))
        $controllerStopped = $true
        Invoke-DockerChecked ($compose + @('start', 'controller'))
        $controllerStopped = $false
        Invoke-Probe 'watermark_after_restart'
    } finally {
        if ($controllerStopped) { Invoke-DockerChecked ($compose + @('start', 'controller')) }
        Invoke-DockerChecked ($compose + @('start', 'loader'))
        $loaderStopped = $false
    }
    Invoke-Probe 'fresh_match'
    Invoke-DockerChecked ($compose + @('stop', 'controller'))
    $controllerStopped = $true
    try {
        Invoke-DockerChecked ($compose + @('start', 'controller'))
        $controllerStopped = $false
        Invoke-Probe 'match_restart'
        $state = Get-Content (Join-Path $validation "d5-r4b-restart-$RunId.json") -Raw | ConvertFrom-Json
        $pipelineId = $state.candidate.pipeline_id
        $code = "from integration.cdc_reseed import cutover_candidate; cutover_candidate('$pipelineId')"
        Invoke-DockerChecked ($compose + @('exec', '-T', 'query', 'python', 'manage.py',
                                           'shell', '-c', $code))
        Invoke-Probe 'cutover_verify'
    } finally {
        if ($controllerStopped) { Invoke-DockerChecked ($compose + @('start', 'controller')) }
    }
} finally {
    Pop-Location
}
