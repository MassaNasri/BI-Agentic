param(
    [ValidateSet('development')][string]$Environment = 'development',
    [switch]$DryRun,
    [switch]$Apply,
    [switch]$Backup,
    [switch]$Verify
)
$ErrorActionPreference = 'Stop'
if ($Apply -and $DryRun) { throw 'Choose -Apply or -DryRun, not both.' }
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($Verify) {
    if ($Apply -or $Backup -or $DryRun) { throw '-Verify is a separate read-only startup validation mode.' }
    & python -X utf8 (Join-Path $PSScriptRoot 'audit_verify_startup.py')
    if ($LASTEXITCODE -ne 0) { throw 'Startup validation has failures. Read docs/audit/startup_verification.json.' }
    exit 0
}
Write-Host 'DEV ONLY: explicit local datastore allowlists, verified backups, no volume deletion.'
if ($Backup) {
    & python -X utf8 (Join-Path $PSScriptRoot 'audit_backup.py')
    if ($LASTEXITCODE -ne 0) { throw 'Backup failed. No reset performed.' }
    Write-Host 'Offline backup complete. Start only datastores, run audit_storage_detail.py, then run -DryRun.'
    exit 0
}
$resetArgs = @('-X','utf8',(Join-Path $PSScriptRoot 'reset_dev.py'),'--environment',$Environment)
if ($Apply) { $resetArgs += '--apply' }
& python @resetArgs
if ($LASTEXITCODE -ne 0) { throw 'Reset preflight or execution failed. Inspect docs/audit/reset_execution.json; do not assume a clean state.' }
