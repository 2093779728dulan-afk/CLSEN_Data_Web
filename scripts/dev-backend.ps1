[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backendDirectory = Join-Path $repositoryRoot "backend"
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$environmentFile = Join-Path $repositoryRoot ".env"

if (-not (Test-Path -LiteralPath (Join-Path $backendDirectory "pyproject.toml") -PathType Leaf)) {
    throw "Backend project not found at '$backendDirectory'. The repository checkout may be incomplete."
}

if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "Virtual-environment Python not found at '$pythonExecutable'. Create it with 'python -m venv .venv' and install backend/requirements.lock before starting the backend."
}

& $pythonExecutable -c "import uvicorn"
if ($LASTEXITCODE -ne 0) {
    throw "uvicorn is not installed in '$pythonExecutable'. Install backend/requirements.lock and the backend package before starting the backend."
}

$preflightArguments = @(
    "-m", "app.schema_preflight",
    "--database-environment", "APP_DATABASE_URL",
    "--component", "api"
)
if (Test-Path -LiteralPath $environmentFile -PathType Leaf) {
    $preflightArguments += @("--environment-file", $environmentFile)
}
Push-Location -LiteralPath $backendDirectory
try {
    & $pythonExecutable @preflightArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Backend schema preflight failed. Uvicorn was not started."
    }
}
finally {
    Pop-Location
}

$uvicornArguments = @(
    "-m", "uvicorn",
    "app.main:app",
    "--app-dir", $backendDirectory,
    "--host", "127.0.0.1",
    "--port", "8000",
    "--reload",
    "--reload-dir", $backendDirectory
)
if (Test-Path -LiteralPath $environmentFile -PathType Leaf) {
    $uvicornArguments += @("--env-file", $environmentFile)
}

Push-Location -LiteralPath $repositoryRoot
try {
    & $pythonExecutable @uvicornArguments
    if ($LASTEXITCODE -ne 0) {
        throw "The backend development server exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
