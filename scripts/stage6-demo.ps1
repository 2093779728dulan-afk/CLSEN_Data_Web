[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$PrimaryDate,

    [Parameter(Mandatory)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$IsolationDate,

    [string]$EnvironmentFile,

    [string]$StorageRoot
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backendDirectory = Join-Path $repositoryRoot "backend"
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"

function Resolve-Stage6DemoPath {
    param(
        [Parameter(Mandatory)]
        [string]$Value
    )

    if ([IO.Path]::IsPathRooted($Value)) {
        return [IO.Path]::GetFullPath($Value)
    }
    return [IO.Path]::GetFullPath((Join-Path $repositoryRoot $Value))
}

if ([string]::IsNullOrWhiteSpace($EnvironmentFile)) {
    $resolvedEnvironmentFile = Join-Path $repositoryRoot ".env"
}
else {
    $resolvedEnvironmentFile = Resolve-Stage6DemoPath -Value $EnvironmentFile
}
if ([string]::IsNullOrWhiteSpace($StorageRoot)) {
    $resolvedStorageRoot = Join-Path $repositoryRoot "data\raw\stage6-demo"
}
else {
    $resolvedStorageRoot = Resolve-Stage6DemoPath -Value $StorageRoot
}

if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw (
        "Virtual-environment Python was not found at '$pythonExecutable'. " +
        "Create .venv and install backend/requirements.lock first."
    )
}
if (-not (Test-Path -LiteralPath $resolvedEnvironmentFile -PathType Leaf)) {
    throw "Environment file was not found at '$resolvedEnvironmentFile'."
}
if (-not (Test-Path -LiteralPath $backendDirectory -PathType Container)) {
    throw "Backend directory was not found at '$backendDirectory'."
}

$storageVolumeRoot = [IO.Path]::GetPathRoot($resolvedStorageRoot)
if ($resolvedStorageRoot -eq $storageVolumeRoot) {
    throw "Stage 6 demo storage must not be a filesystem root."
}

$operation = (
    "run retained stage 6 synthetic workflow for primary date $PrimaryDate " +
    "and isolation date $IsolationDate"
)
if (-not $PSCmdlet.ShouldProcess("the APP_TEST_* local database", $operation)) {
    return
}

Write-Host (
    "Boundary: this runs backend services only. Stage 7 API and stage 8 UI " +
    "have not been started."
)
Write-Host (
    "The demo keeps its date-scoped records and performs no migration, " +
    "database reset, or whole-database cleanup."
)

$arguments = @(
    "-m", "app.demo.stage6",
    "--primary-date", $PrimaryDate,
    "--isolation-date", $IsolationDate,
    "--environment-file", $resolvedEnvironmentFile,
    "--storage-root", $resolvedStorageRoot
)

Push-Location -LiteralPath $backendDirectory
try {
    & $pythonExecutable @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Stage 6 demo exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
