#Requires -Version 7.0
[CmdletBinding()]
param([string]$SecretDirectory = (Join-Path $PSScriptRoot 'secrets'))
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($SecretDirectory)
$allowed = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
if (-not $root.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase) -or
    -not (Test-Path -LiteralPath $root -PathType Container) -or
    ((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Use the existing private secret directory inside this checkout ops folder.'
}
foreach ($name in @('production_app_password', 'production_migrator_password', 'production_backup_password', 'production_service_token')) {
    $path = Join-Path $root $name
    if (Test-Path -LiteralPath $path) {
        $item = Get-Item -LiteralPath $path
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            [IO.File]::ReadAllText($path).Trim() -notmatch '^[A-Za-z0-9_-]{32,}$') {
            throw 'An existing B secret file is invalid; it was not replaced.'
        }
        continue
    }
    $value = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
    $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($value)
        $stream.Write($bytes, 0, $bytes.Length)
    } finally { $stream.Dispose() }
    # The directory was created by bootstrap-secrets.ps1 with owner-only inheritance.
    if ($IsWindows) { & icacls $path /inheritance:r /grant:r "$($env:USERNAME):(F)" | Out-Null; if ($LASTEXITCODE) { throw 'Could not protect B secret' } }
    else { & chmod 600 -- $path; if ($LASTEXITCODE) { throw 'Could not protect B secret' } }
}
Write-Host 'B secret files prepared; existing credentials were preserved.'
