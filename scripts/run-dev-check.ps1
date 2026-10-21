#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet("Backend", "Frontend")]
    [string]$Kind,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string[]]$Targets,

    [string]$PythonExecutable = "D:\CLSEN_Data_Web\.venv\Scripts\python.exe",
    [switch]$ListOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
foreach ($entry in Get-ChildItem Env:) {
    if (($entry.Name -like "APP_STAGE0_PYTEST_*" -or $entry.Name -in @(
        "APP_PROJECT_OPTIMIZATION_RUN_DIR", "APP_RELEASE_SOURCE_SHA"
    )) -and -not [string]::IsNullOrWhiteSpace($entry.Value)) {
        throw "Development checks cannot run inside release evidence collection."
    }
}
if (-not [string]::IsNullOrWhiteSpace($env:PYTEST_ADDOPTS)) {
    throw "Clear PYTEST_ADDOPTS before a targeted development run."
}

foreach ($target in $Targets) {
    $file = ($target -split "::", 2)[0]
    $pattern = if ($Kind -eq "Backend") {
        '\Abackend/tests/(unit|contracts)/[A-Za-z0-9_/-]+\.py(?:::[A-Za-z0-9_][^\r\n]*)?\z'
    }
    else {
        '\Afrontend/src/[A-Za-z0-9_/-]+\.test\.tsx?\z'
    }
    if ($target -cnotmatch $pattern -or
        -not (Test-Path -LiteralPath (Join-Path $repositoryRoot $file) -PathType Leaf)) {
        throw "An existing explicit $Kind test file or backend node is required: $target"
    }
}
$Targets = @($Targets | Select-Object -Unique)
$workingDirectory = $repositoryRoot
if ($Kind -eq "Backend") {
    $executable = $PythonExecutable
    $arguments = @("-m", "pytest") + $Targets + @(
        "-q", "-x", "-m", "not mysql", "-p", "no:cacheprovider"
    )
}
else {
    $executable = "pnpm"
    $workingDirectory = Join-Path $repositoryRoot "frontend"
    $arguments = @("exec", "vitest", "run") + @($Targets | ForEach-Object {
        $_.Substring("frontend/".Length)
    }) + @("--bail=1")
}
if ($ListOnly) {
    [ordered]@{
        mode = "development"
        executable = $executable
        arguments = $arguments
        working_directory = $workingDirectory
        release_evidence = $false
    } | ConvertTo-Json -Depth 4
    return
}

$clock = [Diagnostics.Stopwatch]::StartNew()
if ($Kind -eq "Backend") {
    # A unique, initially absent base avoids deleting another test run's files.
    $testTemp = Join-Path $repositoryRoot (".tmp/dev-check-" + [guid]::NewGuid().ToString("N"))
    $arguments += @("--basetemp", $testTemp)
}
Push-Location -LiteralPath $workingDirectory
try {
    & $executable @arguments
    if ($LASTEXITCODE -ne 0) { throw "Targeted $Kind check failed (exit $LASTEXITCODE)." }
    Write-Host ("Targeted {0} check passed in {1:N1}s; release validation remains separate." -f
        $Kind, $clock.Elapsed.TotalSeconds)
}
finally { Pop-Location }
