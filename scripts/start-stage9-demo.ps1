[CmdletBinding()]
param(
    [string]$Username = "stage9-admin",

    [ValidateSet("admin", "data_manager", "viewer")]
    [string]$Role = "admin"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$environmentFile = Join-Path $repositoryRoot ".env"
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$demoStorageRoot = Join-Path $repositoryRoot "data\raw\stage6-demo"

if (-not (Test-Path -LiteralPath $environmentFile -PathType Leaf)) {
    throw "Environment file was not found at '$environmentFile'."
}
if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "Virtual-environment Python was not found at '$pythonExecutable'."
}
if (-not (Test-Path -LiteralPath $demoStorageRoot -PathType Container)) {
    throw (
        "Stage 6 demo storage was not found at '$demoStorageRoot'. " +
        "Run scripts/stage6-demo.ps1 first to create the isolated sample data."
    )
}

& $pythonExecutable -m app.demo.stage9_access `
    --environment-file $environmentFile `
    --username $Username `
    --role $Role
if ($LASTEXITCODE -ne 0) {
    throw "The isolated Stage 9 demo account was not created."
}

# Load only into this PowerShell process. Values are neither echoed nor written
# back to .env. The app uses the low-privilege test runtime account, never the
# formal application or migration URL.
Get-Content -LiteralPath $environmentFile | ForEach-Object {
    if ($_ -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        Set-Item -Path "Env:$($matches[1])" -Value $matches[2]
    }
}
$env:APP_DATABASE_URL = $env:APP_TEST_RUNTIME_DATABASE_URL
$env:APP_STORAGE_ROOT = $demoStorageRoot.Replace('\', '/')

Push-Location -LiteralPath (Join-Path $repositoryRoot "backend")
try {
    & $pythonExecutable -m app.schema_preflight `
        --database-environment APP_DATABASE_URL `
        --component api
    if ($LASTEXITCODE -ne 0) {
        throw "The isolated Stage 9 database failed schema preflight."
    }
}
finally {
    Pop-Location
}

Write-Host "Starting Stage 9 API against the isolated test database only."
Push-Location -LiteralPath $repositoryRoot
try {
    & $pythonExecutable -m uvicorn app.main:app `
        --app-dir (Join-Path $repositoryRoot "backend") `
        --host 127.0.0.1 `
        --port 8000 `
        --reload `
        --reload-dir (Join-Path $repositoryRoot "backend")
}
finally {
    Pop-Location
}
