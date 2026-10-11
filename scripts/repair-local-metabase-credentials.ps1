param(
    [Parameter(Mandatory = $true)]
    [string]$TargetEnv,

    [Parameter(Mandatory = $true)]
    [string]$Username
)

$ErrorActionPreference = "Stop"

$resolvedEnv = (Resolve-Path -LiteralPath $TargetEnv).Path
$lines = [System.Collections.Generic.List[string]]::new()
$lines.AddRange([string[]][System.IO.File]::ReadAllLines($resolvedEnv))

$randomBytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($randomBytes)
$password = [Convert]::ToBase64String($randomBytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")

function Set-EnvValue {
    param(
        [System.Collections.Generic.List[string]]$Content,
        [string]$Name,
        [string]$Value
    )

    $prefix = "$Name="
    for ($index = 0; $index -lt $Content.Count; $index++) {
        if ($Content[$index].StartsWith($prefix, [System.StringComparison]::Ordinal)) {
            $Content[$index] = "$prefix$Value"
            return
        }
    }
    $Content.Add("$prefix$Value")
}

Set-EnvValue -Content $lines -Name "METABASE_USERNAME" -Value $Username
Set-EnvValue -Content $lines -Name "METABASE_PASSWORD" -Value $password

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($resolvedEnv, (($lines -join [Environment]::NewLine) + [Environment]::NewLine), $utf8NoBom)

function Get-Fingerprint {
    param([string]$Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $hash = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Value))
    return [BitConverter]::ToString($hash).Replace("-", "").Substring(0, 12).ToLowerInvariant()
}

Write-Output "metabase_username_fingerprint=$(Get-Fingerprint $Username)"
Write-Output "metabase_password_fingerprint=$(Get-Fingerprint $password)"
Write-Output "metabase_password_length=$($password.Length)"
