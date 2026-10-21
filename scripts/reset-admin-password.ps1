#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Username
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backendDirectory = Join-Path $repositoryRoot "backend"
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$environmentFile = Join-Path $repositoryRoot ".env"

if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "Virtual-environment Python was not found at '$pythonExecutable'."
}
if (-not (Test-Path -LiteralPath $environmentFile -PathType Leaf)) {
    throw "Environment file was not found at '$environmentFile'."
}

Push-Location -LiteralPath $backendDirectory
try {
    & $pythonExecutable -m app.cli reset-admin-password `
        "--username=$Username" `
        "--environment-file=$environmentFile"
    if ($LASTEXITCODE -ne 0) {
        throw "Administrator password reset failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
