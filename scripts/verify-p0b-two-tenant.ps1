param()

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

function Read-DotEnv {
    param([string]$Path)
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            continue
        }
        $value = $Matches[2].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$Matches[1]] = $value
    }
    return $values
}

function Invoke-Docker {
    param([string[]]$Arguments)
    # Windows PowerShell can promote any native stderr line to an ErrorRecord
    # when ErrorActionPreference is Stop. Django dependency warnings are not a
    # command failure, so capture them and rely exclusively on the exit code.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & docker @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "Docker command failed without serializing command output."
    }
    return ($output -join "`n")
}

function Get-TaggedValue {
    param([string]$Output, [string]$Tag)
    $match = [regex]::Match($Output, [regex]::Escape($Tag) + '([^\r\n]+)')
    if (-not $match.Success) {
        throw "Expected verification tag was not returned: $Tag"
    }
    return $match.Groups[1].Value.Trim()
}

function Invoke-Http {
    param(
        [string]$Method,
        [string]$Url,
        [hashtable]$Headers = @{},
        [string]$JsonBody = ""
    )
    $parameters = @{
        Method = $Method
        Uri = $Url
        Headers = $Headers
        TimeoutSec = 30
        UseBasicParsing = $true
    }
    if ($JsonBody) {
        $parameters.Body = $JsonBody
        $parameters.ContentType = 'application/json'
    }
    try {
        $response = Invoke-WebRequest @parameters
        return [pscustomobject]@{ Status = [int]$response.StatusCode; Body = [string]$response.Content }
    }
    catch {
        $errorResponse = $_.Exception.Response
        if ($null -eq $errorResponse) {
            throw "HTTP request failed at transport level: $Method $Url"
        }
        $reader = New-Object System.IO.StreamReader($errorResponse.GetResponseStream())
        try {
            $body = $reader.ReadToEnd()
        }
        finally {
            $reader.Dispose()
        }
        return [pscustomobject]@{ Status = [int]$errorResponse.StatusCode; Body = $body }
    }
}

function Assert-Status {
    param([string]$Name, $Response, [int]$Expected)
    if ($Response.Status -ne $Expected) {
        throw "$Name expected HTTP $Expected but received $($Response.Status)."
    }
    Write-Host "PASS $Name (HTTP $Expected)"
}

$config = Read-DotEnv -Path '.env'
foreach ($required in @('SURREAL_USER', 'SURREAL_PASS', 'ETL_INTERNAL_API_KEY', 'INGESTION_CALLBACK_API_KEY')) {
    if (-not $config.ContainsKey($required) -or [string]::IsNullOrWhiteSpace($config[$required])) {
        throw "Required local verification configuration is missing: $required"
    }
}

$suffix = [Guid]::NewGuid().ToString('N').Substring(0, 12)
$emailA = "p0b-a-$suffix@example.invalid"
$emailB = "p0b-b-$suffix@example.invalid"
$workspaceNameA = "P0B Tenant A $suffix"
$workspaceNameB = "P0B Tenant B $suffix"
$password = "P0b!" + [Guid]::NewGuid().ToString('N')
$surrealRecord = "p0b_live_$suffix"
$metabaseObjectId = 2100000000 + (Get-Random -Minimum 1 -Maximum 999999)

$userA = $null
$userB = $null
$workspaceA = $null
$workspaceB = $null
$reportId = $null
$ownershipId = $null
$databaseId = $null
$jobId = $null

try {
    $authCode = @'
import os
from users.models import User
a = User.objects.create_user(email=os.environ['P0B_A_EMAIL'], password=os.environ['P0B_TEST_PASSWORD'], name='P0B Tenant A', role='manager', is_verified=True)
b = User.objects.create_user(email=os.environ['P0B_B_EMAIL'], password=os.environ['P0B_TEST_PASSWORD'], name='P0B Tenant B', role='manager', is_verified=True)
print(f'P0B_IDS:{a.id},{b.id}')
'@
    $authOutput = Invoke-Docker @(
        'exec',
        '-e', "P0B_A_EMAIL=$emailA",
        '-e', "P0B_B_EMAIL=$emailB",
        '-e', "P0B_TEST_PASSWORD=$password",
        'auth-service', 'python', 'manage.py', 'shell', '-c', $authCode
    )
    $userParts = (Get-TaggedValue $authOutput 'P0B_IDS:').Split(',')
    $userA = [int]$userParts[0]
    $userB = [int]$userParts[1]

    $workspaceCode = @'
import os
from workspace.models import Workspace
a = Workspace.objects.create(name=os.environ['P0B_WS_A_NAME'], owner=int(os.environ['P0B_USER_A']), owner_email=os.environ['P0B_A_EMAIL'], owner_name='P0B Tenant A')
b = Workspace.objects.create(name=os.environ['P0B_WS_B_NAME'], owner=int(os.environ['P0B_USER_B']), owner_email=os.environ['P0B_B_EMAIL'], owner_name='P0B Tenant B')
print(f'P0B_WORKSPACES:{a.id},{b.id}')
'@
    $workspaceOutput = Invoke-Docker @(
        'exec',
        '-e', "P0B_WS_A_NAME=$workspaceNameA",
        '-e', "P0B_WS_B_NAME=$workspaceNameB",
        '-e', "P0B_USER_A=$userA",
        '-e', "P0B_USER_B=$userB",
        '-e', "P0B_A_EMAIL=$emailA",
        '-e', "P0B_B_EMAIL=$emailB",
        'workspace-service', 'python', 'manage.py', 'shell', '-c', $workspaceCode
    )
    $workspaceParts = (Get-TaggedValue $workspaceOutput 'P0B_WORKSPACES:').Split(',')
    $workspaceA = [int]$workspaceParts[0]
    $workspaceB = [int]$workspaceParts[1]

    $loginA = Invoke-Http 'POST' 'http://127.0.0.1:8000/auth/login/' @{} (@{ email = $emailA; password = $password } | ConvertTo-Json -Compress)
    $loginB = Invoke-Http 'POST' 'http://127.0.0.1:8000/auth/login/' @{} (@{ email = $emailB; password = $password } | ConvertTo-Json -Compress)
    Assert-Status 'Tenant A real login' $loginA 200
    Assert-Status 'Tenant B real login' $loginB 200
    $tokenA = ($loginA.Body | ConvertFrom-Json).access
    $tokenB = ($loginB.Body | ConvertFrom-Json).access
    if (-not $tokenA -or -not $tokenB) { throw 'A login response omitted an access token.' }

    $voiceCode = @'
import os
from voice_reports.models import VoiceReport
r = VoiceReport.objects.create(workspace_id=os.environ['P0B_WORKSPACE_B'], created_by_id=os.environ['P0B_USER_B'], created_by_email=os.environ['P0B_B_EMAIL'], audio_file='', title='P0B disposable tenant B report')
print(f'P0B_REPORT:{r.id}')
'@
    $voiceOutput = Invoke-Docker @(
        'exec',
        '-e', "P0B_WORKSPACE_B=$workspaceB",
        '-e', "P0B_USER_B=$userB",
        '-e', "P0B_B_EMAIL=$emailB",
        'voice-service', 'python', 'manage.py', 'shell', '-c', $voiceCode
    )
    $reportId = [int](Get-TaggedValue $voiceOutput 'P0B_REPORT:')

    $foreignVoice = Invoke-Http 'GET' "http://127.0.0.1:8004/voice-reports/$reportId/" @{ Authorization = "Bearer $tokenA" }
    $ownVoice = Invoke-Http 'GET' "http://127.0.0.1:8004/voice-reports/$reportId/" @{ Authorization = "Bearer $tokenB" }
    Assert-Status 'Tenant A denied Tenant B Voice report' $foreignVoice 404
    Assert-Status 'Tenant B reads own Voice report' $ownVoice 200

    $visualizationCode = @'
import os
from visualization_api.models import VisualizationObjectOwnership
o = VisualizationObjectOwnership.objects.create(workspace_id=int(os.environ['P0B_WORKSPACE_B']), object_type='card', metabase_object_id=int(os.environ['P0B_METABASE_OBJECT']), creator_id=os.environ['P0B_USER_B'], source_context={'p0b_disposable': True})
print(f'P0B_OWNERSHIP:{o.id}')
'@
    $visualizationOutput = Invoke-Docker @(
        'exec',
        '-e', "P0B_WORKSPACE_B=$workspaceB",
        '-e', "P0B_USER_B=$userB",
        '-e', "P0B_METABASE_OBJECT=$metabaseObjectId",
        'visualization-service', 'python', 'manage.py', 'shell', '-c', $visualizationCode
    )
    $ownershipId = [int](Get-TaggedValue $visualizationOutput 'P0B_OWNERSHIP:')

    $foreignEmbed = Invoke-Http 'GET' "http://127.0.0.1:8007/visualization/question/$metabaseObjectId/embed-url/" @{ Authorization = "Bearer $tokenA" }
    $ownEmbed = Invoke-Http 'GET' "http://127.0.0.1:8007/visualization/question/$metabaseObjectId/embed-url/" @{ Authorization = "Bearer $tokenB" }
    Assert-Status 'Tenant A denied Tenant B visualization' $foreignEmbed 403
    Assert-Status 'Tenant B receives own visualization embed' $ownEmbed 200

    $queryCode = @'
import os
from database.models import Database
d = Database.objects.create(manager=int(os.environ['P0B_USER_B']), manager_email=os.environ['P0B_B_EMAIL'], manager_name='P0B Tenant B', workspace_id=int(os.environ['P0B_WORKSPACE_B']), filename='p0b-disposable.csv', file_size=0, file_path='p0b-disposable', etl_status='pending')
print(f'P0B_DATABASE:{d.id},{d.ingestion_job_id}')
'@
    $queryOutput = Invoke-Docker @(
        'exec',
        '-e', "P0B_USER_B=$userB",
        '-e', "P0B_B_EMAIL=$emailB",
        '-e', "P0B_WORKSPACE_B=$workspaceB",
        'query-service', 'python', 'manage.py', 'shell', '-c', $queryCode
    )
    $databaseParts = (Get-TaggedValue $queryOutput 'P0B_DATABASE:').Split(',')
    $databaseId = [int]$databaseParts[0]
    $jobId = $databaseParts[1]

    $callbackHeaders = @{
        'X-Internal-Service' = 'etl-loader'
        'X-Internal-API-Key' = $config['INGESTION_CALLBACK_API_KEY']
    }
    $foreignStatusBody = @{
        dataset_id = $databaseId
        workspace_id = $workspaceA
        expected_state = 'pending'
        etl_status = 'processing'
    } | ConvertTo-Json -Compress
    $ownStatusBody = @{
        dataset_id = $databaseId
        workspace_id = $workspaceB
        expected_state = 'pending'
        etl_status = 'processing'
    } | ConvertTo-Json -Compress
    $foreignStatus = Invoke-Http 'POST' "http://127.0.0.1:8006/internal/v1/ingestion/jobs/$jobId/dataset-status" $callbackHeaders $foreignStatusBody
    $ownStatus = Invoke-Http 'POST' "http://127.0.0.1:8006/internal/v1/ingestion/jobs/$jobId/dataset-status" $callbackHeaders $ownStatusBody
    Assert-Status 'Tenant A scope cannot mutate Tenant B ingestion state' $foreignStatus 404
    Assert-Status 'Tenant B scope mutates its own ingestion state' $ownStatus 200

    $surrealSql = "CREATE connection_logs:$surrealRecord CONTENT { workspace_id: $workspaceB, dataset_id: '$databaseId', ingestion_job_id: '$jobId', status: 'p0b_disposable' };"
    $surrealAuth = "$($config['SURREAL_USER']):$($config['SURREAL_PASS'])"
    $surrealCreate = & curl.exe -sS --fail --user $surrealAuth -H 'surreal-ns: bi_etl' -H 'surreal-db: etl_logs' -H 'Accept: application/json' --data $surrealSql 'http://127.0.0.1:8008/sql'
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create disposable scoped Surreal metadata.' }

    $metadataHeadersA = @{
        'X-Internal-Service' = 'query-service'
        'X-Internal-API-Key' = $config['ETL_INTERNAL_API_KEY']
        'X-Workspace-ID' = "$workspaceA"
        'X-Dataset-ID' = "$databaseId"
        'X-Ingestion-Job-ID' = "$jobId"
    }
    $metadataHeadersB = @{
        'X-Internal-Service' = 'query-service'
        'X-Internal-API-Key' = $config['ETL_INTERNAL_API_KEY']
        'X-Workspace-ID' = "$workspaceB"
        'X-Dataset-ID' = "$databaseId"
        'X-Ingestion-Job-ID' = "$jobId"
    }
    $foreignMetadata = Invoke-Http 'GET' 'http://127.0.0.1:8106/api/logs/connections/' $metadataHeadersA
    $ownMetadata = Invoke-Http 'GET' 'http://127.0.0.1:8106/api/logs/connections/' $metadataHeadersB
    Assert-Status 'Tenant A scoped ETL metadata request' $foreignMetadata 200
    Assert-Status 'Tenant B scoped ETL metadata request' $ownMetadata 200
    $foreignData = ($foreignMetadata.Body | ConvertFrom-Json).data
    $ownData = ($ownMetadata.Body | ConvertFrom-Json).data
    if (@($foreignData).Count -ne 0) { throw 'Tenant A received foreign ETL metadata.' }
    if (@($ownData).Count -lt 1) { throw 'Tenant B did not receive its own ETL metadata.' }
    Write-Host 'PASS Tenant A cannot access Tenant B ETL metadata'
    Write-Host 'PASS Tenant B reads its own ETL metadata'

    Write-Host 'P0B_LIVE_TWO_TENANT:PASS'
}
finally {
    if ($surrealRecord -and $config.ContainsKey('SURREAL_USER') -and $config.ContainsKey('SURREAL_PASS')) {
        $surrealAuth = "$($config['SURREAL_USER']):$($config['SURREAL_PASS'])"
        $deleteSql = "DELETE connection_logs:$surrealRecord;"
        & curl.exe -sS --user $surrealAuth -H 'surreal-ns: bi_etl' -H 'surreal-db: etl_logs' -H 'Accept: application/json' --data $deleteSql 'http://127.0.0.1:8008/sql' | Out-Null
    }
    $cleanup = "from visualization_api.models import VisualizationObjectOwnership; VisualizationObjectOwnership.objects.filter(source_context__p0b_disposable=True).delete()"
    Invoke-Docker @('exec', 'visualization-service', 'python', 'manage.py', 'shell', '-c', $cleanup) | Out-Null
    $cleanup = "from voice_reports.models import VoiceReport; VoiceReport.objects.filter(title='P0B disposable tenant B report', created_by_email='$emailB').delete()"
    Invoke-Docker @('exec', 'voice-service', 'python', 'manage.py', 'shell', '-c', $cleanup) | Out-Null
    $cleanup = "from database.models import Database; Database.objects.filter(filename='p0b-disposable.csv', manager_email='$emailB').delete()"
    Invoke-Docker @('exec', 'query-service', 'python', 'manage.py', 'shell', '-c', $cleanup) | Out-Null
    $cleanup = "from workspace.models import Workspace; Workspace.objects.filter(name__in=['$workspaceNameA','$workspaceNameB']).delete()"
    Invoke-Docker @('exec', 'workspace-service', 'python', 'manage.py', 'shell', '-c', $cleanup) | Out-Null
    $cleanup = "from users.models import User; User.objects.filter(email__in=['$emailA','$emailB']).delete()"
    Invoke-Docker @('exec', 'auth-service', 'python', 'manage.py', 'shell', '-c', $cleanup) | Out-Null
    $password = $null
    Write-Host 'P0B disposable two-tenant fixtures cleaned.'
}
