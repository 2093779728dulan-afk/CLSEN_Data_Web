#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('\A[0-9a-f]{32}\z')]
    [string]$RunId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$runtimeRoot = [IO.Path]::GetFullPath(
    (Join-Path $temporaryRoot "clsen-catalog-live-$RunId")
)
if (
    -not $runtimeRoot.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -or
    (Split-Path -Leaf $runtimeRoot) -cne "clsen-catalog-live-$RunId" -or
    $runtimeRoot -ceq $temporaryRoot
) {
    throw "The experience runtime root is outside the operating-system temporary directory."
}
$manifestPath = Join-Path $runtimeRoot "run-manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "No active catalog experience manifest exists for this run ID."
}
$manifest = Get-Content -Raw -LiteralPath $manifestPath |
    ConvertFrom-Json -AsHashtable
$expectedDatabase = "clsen_data_test_$($RunId.Substring(0, 16))"
if (
    $manifest.run_id -cne $RunId -or
    $manifest.database_name -cne $expectedDatabase -or
    [IO.Path]::GetFullPath([string]$manifest.runtime_root) -cne $runtimeRoot -or
    $manifest.state -cne "experience_running"
) {
    throw "The catalog experience manifest failed ownership validation."
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($null -eq $dockerCommand) {
    throw "Docker is required to verify the experience database owner."
}
$containerId = [string]$manifest.details.container_id
$actualContainerId = @(
    & $dockerCommand.Source inspect --format '{{.Id}}' $containerId 2>&1
)
$actualContainerLabel = @(
    & $dockerCommand.Source inspect `
        --format '{{ index .Config.Labels "clsen.catalog-live.run" }}' `
        $containerId 2>&1
)
if (
    $LASTEXITCODE -ne 0 -or
    ($actualContainerId -join "").Trim() -cne $containerId -or
    ($actualContainerLabel -join "").Trim() -cne $RunId
) {
    throw "The catalog experience database container failed ownership validation."
}

foreach ($record in @($manifest.details.processes)) {
    $process = Get-Process -Id ([int]$record.pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        throw "A runner-owned experience process is no longer running."
    }
    if ($process.StartTime.ToUniversalTime().Ticks -ne [long]$record.start_ticks) {
        throw "A runner-owned experience PID was reused."
    }
}

$stopMarker = [IO.Path]::GetFullPath([string]$manifest.details.experience.stop_marker)
$expectedStopMarker = Join-Path $runtimeRoot "experience-stop.json"
if ($stopMarker -cne $expectedStopMarker -or (Test-Path -LiteralPath $stopMarker)) {
    throw "The catalog experience stop target failed ownership validation."
}
$request = [ordered]@{
    run_id = $RunId
    action = "stop"
    requested_at = [DateTimeOffset]::UtcNow.ToString("O")
}
[IO.File]::WriteAllText(
    $stopMarker,
    ($request | ConvertTo-Json -Compress),
    [Text.UTF8Encoding]::new($false)
)
Write-Host "Catalog experience stop requested for run $RunId."
