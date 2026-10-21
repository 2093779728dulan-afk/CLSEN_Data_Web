#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateSet("8.0", "8.4")]
    [ValidateNotNullOrEmpty()]
    [string[]]$Versions = @("8.4"),

    [Parameter()]
    [string]$MySql80EvidencePath = $env:APP_PRODUCT_CATALOG_MYSQL80_SCALE_EVIDENCE,

    [Parameter()]
    [string]$MySql84EvidencePath = $env:APP_PRODUCT_CATALOG_MYSQL84_SCALE_EVIDENCE,

    [Parameter()]
    [switch]$GenerateEvidence,

    [Parameter()]
    [string]$EvidenceDirectory,

    [Parameter()]
    [switch]$SetUserEnvironment,

    [Parameter(Mandatory)]
    [ValidatePattern("\A[0-9a-f]{40}\z")]
    [string]$SourceSha,

    [Parameter(Mandatory)]
    [string]$PythonExecutable,

    [Parameter()]
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$matrix = Join-Path $PSScriptRoot "test-mysql-matrix.ps1"
$previousRequire = [Environment]::GetEnvironmentVariable(
    "APP_REQUIRE_PRODUCT_CATALOG_PERFORMANCE"
)
$previousEvidence = [Environment]::GetEnvironmentVariable(
    "APP_PRODUCT_CATALOG_SCALE_EVIDENCE_PATH"
)
$previousGenerate = [Environment]::GetEnvironmentVariable(
    "APP_GENERATE_PRODUCT_CATALOG_SCALE_EVIDENCE"
)
$previousSourceSha = [Environment]::GetEnvironmentVariable("APP_RELEASE_SOURCE_SHA")

function Get-DerivedReleaseIdentity {
    $previousLocation = Get-Location
    try {
        Set-Location -LiteralPath (Join-Path $repositoryRoot "backend")
        $source = @"
import json
from tests.performance.product_catalog_scale_fixture import release_source_identity
print(json.dumps(release_source_identity("$SourceSha"), sort_keys=True))
"@
        $output = @(& $PythonExecutable -c $source 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "Release source identity could not be derived from a clean checkout."
        }
        return ($output -join "") | ConvertFrom-Json -AsHashtable
    }
    finally {
        Set-Location -LiteralPath $previousLocation
    }
}

$derivedIdentity = Get-DerivedReleaseIdentity

function Resolve-ScaleEvidence {
    param(
        [Parameter()][AllowEmptyString()][string]$Value,
        [Parameter(Mandatory)][ValidateSet("8.0", "8.4")][string]$Version
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "MySQL $Version analytics_scale_v1 evidence is required."
    }
    $resolved = [IO.Path]::GetFullPath($Value)
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "MySQL $Version analytics_scale_v1 evidence file is unavailable."
    }
    $payload = Get-Content -Raw -LiteralPath $resolved | ConvertFrom-Json -AsHashtable
    if (
        $payload.fixture -cne "analytics_scale_v1" -or
        $payload.mysql_version -cne $Version -or
        $payload.warmup_samples -ne 3 -or
        $payload.measured_samples -ne 20
    ) {
        throw "MySQL $Version analytics_scale_v1 evidence identity is invalid."
    }
    foreach ($field in @(
        "source_sha", "git_tree", "artifact_digest", "runner_digest"
    )) {
        if ($payload[$field] -cne $derivedIdentity[$field]) {
            throw "MySQL $Version analytics_scale_v1 evidence $field is invalid."
        }
    }
    return $resolved
}

try {
    if ($GenerateEvidence) {
        if ([string]::IsNullOrWhiteSpace($EvidenceDirectory)) {
            throw "EvidenceDirectory is required when GenerateEvidence is selected."
        }
        $resolvedDirectory = [IO.Path]::GetFullPath($EvidenceDirectory)
        New-Item -ItemType Directory -Path $resolvedDirectory -Force | Out-Null
        $evidenceByVersion = @{}
        foreach ($version in $Versions) {
            $suffix = $version.Replace('.', '')
            $evidenceByVersion[$version] = Join-Path $resolvedDirectory "analytics-scale-v1-mysql$suffix.json"
        }
        $env:APP_GENERATE_PRODUCT_CATALOG_SCALE_EVIDENCE = "1"
    }
    else {
        $evidenceByVersion = @{}
        foreach ($version in $Versions) {
            $value = if ($version -ceq "8.4") { $MySql84EvidencePath } else { $MySql80EvidencePath }
            $evidenceByVersion[$version] = Resolve-ScaleEvidence -Value $value -Version $version
        }
        Remove-Item Env:APP_GENERATE_PRODUCT_CATALOG_SCALE_EVIDENCE `
            -ErrorAction SilentlyContinue
    }
    if ($ValidateOnly) {
        if ($GenerateEvidence) {
            throw "ValidateOnly cannot generate performance evidence."
        }
        Write-Host "Performance evidence is bound to release source $SourceSha."
        return
    }
    $env:APP_RELEASE_SOURCE_SHA = $SourceSha
    $env:APP_REQUIRE_PRODUCT_CATALOG_PERFORMANCE = "1"
    foreach ($version in $Versions) {
        $env:APP_PRODUCT_CATALOG_SCALE_EVIDENCE_PATH = $evidenceByVersion[$version]
        & $matrix `
            -Versions @($version) `
            -PerformanceProfile `
            -Suites @("performance") `
            -PythonExecutable $PythonExecutable
        if ($LASTEXITCODE -ne 0) {
            throw "MySQL $version product catalog performance gate failed."
        }
        $evidenceByVersion[$version] = Resolve-ScaleEvidence `
            -Value $evidenceByVersion[$version] `
            -Version $version
    }
    if ($GenerateEvidence -and $SetUserEnvironment) {
        foreach ($version in $Versions) {
            $suffix = $version.Replace('.', '')
            [Environment]::SetEnvironmentVariable(
                "APP_PRODUCT_CATALOG_MYSQL${suffix}_SCALE_EVIDENCE",
                $evidenceByVersion[$version],
                "User"
            )
        }
        Write-Host "Saved selected scale evidence paths in the user environment."
    }
    Write-Host "Product catalog performance gates PASS for Oracle MySQL $($Versions -join '/')."
    foreach ($version in $Versions) {
        Write-Host "MySQL $version evidence: $($evidenceByVersion[$version])"
    }
}
finally {
    [Environment]::SetEnvironmentVariable(
        "APP_REQUIRE_PRODUCT_CATALOG_PERFORMANCE",
        $previousRequire
    )
    [Environment]::SetEnvironmentVariable(
        "APP_PRODUCT_CATALOG_SCALE_EVIDENCE_PATH",
        $previousEvidence
    )
    [Environment]::SetEnvironmentVariable(
        "APP_GENERATE_PRODUCT_CATALOG_SCALE_EVIDENCE",
        $previousGenerate
    )
    [Environment]::SetEnvironmentVariable(
        "APP_RELEASE_SOURCE_SHA",
        $previousSourceSha
    )
}
