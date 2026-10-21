#Requires -Version 7.0

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [Parameter()]
    [ValidateSet("8.0", "8.4")]
    [string[]]$Versions = @("8.0", "8.4"),

    [Parameter(Mandatory)]
    [ValidateSet("mysql-migrations", "mysql-legacy", "mysql-p0")]
    [string[]]$Suites,

    [Parameter(Mandatory)]
    [string]$PythonExecutable
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$managedInputs = @(
    "APP_TEST_DATABASE_URL",
    "APP_TEST_RUNTIME_DATABASE_URL",
    "APP_TEST_BACKUP_DATABASE_URL",
    "APP_TEST_RUN_ID"
)
foreach ($name in $managedInputs) {
    if (-not [string]::IsNullOrWhiteSpace(
            [Environment]::GetEnvironmentVariable(
                $name,
                [EnvironmentVariableTarget]::Process
            )
        )) {
        throw (
            "$name must not be supplied externally; the product-catalog " +
            "runner creates and owns every database identity."
        )
    }
}

$matrix = Join-Path $PSScriptRoot "test-mysql-matrix.ps1"
if (-not (Test-Path -LiteralPath $matrix -PathType Leaf)) {
    throw "The canonical MySQL matrix runner is missing."
}

if ($PSCmdlet.ShouldProcess(
        "runner-owned random Oracle MySQL containers",
        "run scoped product-catalog tests"
    )) {
    & $matrix `
        -Versions $Versions `
        -Suites $Suites `
        -PythonExecutable $PythonExecutable `
        -Confirm:$false
}
