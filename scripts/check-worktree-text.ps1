#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$PathManifest,

    [Parameter()]
    [string]$BaselineRoot = $env:APP_PLAN_BASELINE_ROOT,

    [Parameter()]
    [string[]]$Extensions = @(
        ".py", ".ts", ".tsx", ".css", ".md", ".json", ".toml",
        ".ps1", ".in", ".lock", ".yml", ".yaml", ".txt"
    )
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = [IO.Path]::GetFullPath(
    ((git rev-parse --show-toplevel) -join "").Trim()
)
$manifest = @(Get-Content -Raw -LiteralPath $PathManifest | ConvertFrom-Json)
$ordinal = [string[]]$manifest.Clone()
[Array]::Sort($ordinal, [StringComparer]::Ordinal)
if (($manifest -join "`n") -cne ($ordinal -join "`n")) {
    throw "Path manifest must be ordinal-sorted."
}
$baselineChecker = Join-Path $PSScriptRoot "check-plan-worktree-baseline.ps1"
& $baselineChecker -PathManifest $PathManifest -BaselineRoot $BaselineRoot | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Plan baseline validation failed." }

$allowedExtensions = [Collections.Generic.HashSet[string]]::new(
    [string[]]$Extensions,
    [StringComparer]::OrdinalIgnoreCase
)
$strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
$checked = 0
foreach ($relativePath in $manifest) {
    if (-not $allowedExtensions.Contains([IO.Path]::GetExtension($relativePath))) {
        continue
    }
    $resolved = [IO.Path]::GetFullPath((Join-Path $repositoryRoot $relativePath))
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { continue }
    $bytes = [IO.File]::ReadAllBytes($resolved)
    try {
        $text = $strictUtf8.GetString($bytes)
    }
    catch {
        throw "Text file is not strict UTF-8: $relativePath"
    }
    if ($text.Contains([char]0) -or $text.Contains([char]0xFFFD)) {
        throw "Text file contains text damage: $relativePath"
    }
    $checked++
}

Write-Output "Worktree text PASS: $checked strict UTF-8 files checked."
