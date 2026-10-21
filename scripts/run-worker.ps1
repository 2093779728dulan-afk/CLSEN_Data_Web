#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter()]
    [switch]$UseTestDatabase,

    [Parameter()]
    [switch]$Drain,

    [Parameter()]
    [ValidateRange(1, 60)]
    [int]$PollSeconds = 2
)

$ErrorActionPreference = "Stop"
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$backendDirectory = Join-Path $repositoryRoot "backend"
$environmentFile = Join-Path $repositoryRoot ".env"
if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "Project Python was not found at '$pythonExecutable'."
}

$databaseEnvironment = if ($UseTestDatabase) {
    "APP_TEST_RUNTIME_DATABASE_URL"
}
else {
    "APP_DATABASE_URL"
}
$arguments = @(
    "-m", "app.worker.cli",
    "--database-environment", $databaseEnvironment,
    "--poll-seconds", $PollSeconds
)
if ($Drain) {
    $arguments += "--drain"
}
$preflightArguments = @(
    "-m", "app.schema_preflight",
    "--database-environment", $databaseEnvironment,
    "--component", "worker"
)
if (Test-Path -LiteralPath $environmentFile -PathType Leaf) {
    $preflightArguments += @("--environment-file", $environmentFile)
}
Push-Location -LiteralPath $backendDirectory
try {
    Write-Host "Starting CLSEN worker..."
    & $pythonExecutable @preflightArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Worker schema preflight failed. The worker was not started."
    }
    Write-Host "CLSEN worker ready."
    & $pythonExecutable @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Outbox worker failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
