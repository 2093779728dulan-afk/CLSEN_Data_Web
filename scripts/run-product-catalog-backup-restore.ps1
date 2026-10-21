#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateSet("8.0", "8.4")]
    [ValidateNotNullOrEmpty()]
    [string[]]$Versions = @("8.4"),

    [Parameter(Mandatory)]
    [string]$PythonExecutable,

    [Parameter()]
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$matrix = Join-Path $PSScriptRoot "test-mysql-matrix.ps1"
$previous = [Environment]::GetEnvironmentVariable(
    "APP_REQUIRE_PRODUCT_CATALOG_BACKUP_RESTORE"
)

foreach ($command in @("mysql", "mysqldump", "docker")) {
    if ($null -eq (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command is required by the canonical encrypted restore runner."
    }
}
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "Python 3.14 runtime is required by the restore gate."
}
if ($ValidateOnly) {
    Write-Host "Encrypted restore prerequisites validated without execution."
    return
}

try {
    $env:APP_REQUIRE_PRODUCT_CATALOG_BACKUP_RESTORE = "1"
    & $matrix `
        -Versions $Versions `
        -Suites @("restore") `
        -PythonExecutable $PythonExecutable
    if ($LASTEXITCODE -ne 0) {
        throw "Product catalog encrypted backup/restore gate failed."
    }
    Write-Host "Product catalog encrypted restore PASS on MySQL $($Versions -join '/')."
}
finally {
    [Environment]::SetEnvironmentVariable(
        "APP_REQUIRE_PRODUCT_CATALOG_BACKUP_RESTORE",
        $previous
    )
}
