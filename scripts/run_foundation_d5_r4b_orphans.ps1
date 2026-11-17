param([string]$RunId = '20261110a', [switch]$ResumeFailed, [switch]$SkipFailed,
      [switch]$ResumePending)

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

function Invoke-Probe([string]$Case, [string]$Phase) {
    Invoke-DockerChecked @('run', '--rm', '--network', 'biavora_d5_r4b_default',
        '--env-file', $environment, '-e', 'CDC_FIXTURE_INTERNAL=1',
        '-e', 'CDC_CONNECT_URL=http://connect:8083', '-v', $mountScripts,
        '-v', $mountEvidence, '--entrypoint', 'python',
        'biavora-d5-r3-verifier:local', '/acceptance/verify_foundation_d5_r4b_orphans.py',
        '--env-file', '/evidence/fixture.env', '--case', $Case,
        '--phase', $Phase, '--run-id', $RunId)
}

Push-Location $repo
try {
    if (-not $ResumeFailed) {
        Invoke-Probe 'missing' 'setup'
        Invoke-DockerChecked ($compose + @('stop', 'controller'))
        try {
            Invoke-Probe 'missing' 'boundary'
        } finally {
            Invoke-DockerChecked ($compose + @('start', 'controller'))
        }
        Invoke-Probe 'missing' 'repair'

        Invoke-Probe 'failed' 'setup'
        Invoke-Probe 'failed' 'candidate'
    }
    if (-not $SkipFailed) {
        Invoke-Probe 'failed' 'abort'
        Invoke-Probe 'failed' 'verify'
    }

    if (-not $ResumePending) {
        Invoke-Probe 'pending' 'setup'
        Invoke-Probe 'pending' 'candidate'
    }
    $state = Get-Content (Join-Path $validation "d5-r4b-orphan-pending-$RunId.json") -Raw | ConvertFrom-Json
    $pipelineId = $state.candidate.pipeline_id
    $code = "from integration.cdc_reseed import cutover_candidate; cutover_candidate('$pipelineId', fault='after_query')"
    $savedErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker @compose 'exec' '-T' 'query' 'python' 'manage.py' 'shell' '-c' $code *> $null
    } finally {
        $ErrorActionPreference = $savedErrorAction
    }
    if ($LASTEXITCODE -eq 0) { throw 'Expected after_query cutover interruption was absent' }
    Invoke-Probe 'pending' 'bound'
    Invoke-DockerChecked ($compose + @('restart', 'controller'))
    Invoke-Probe 'pending' 'recover'

    Invoke-Probe 'binding' 'setup'
    Invoke-DockerChecked ($compose + @('stop', 'controller'))
    try {
        Invoke-Probe 'binding' 'corrupt'
        Invoke-Probe 'binding' 'verify'
    } finally {
        Invoke-DockerChecked ($compose + @('start', 'controller'))
    }
} finally {
    Pop-Location
}
