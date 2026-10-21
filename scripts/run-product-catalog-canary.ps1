#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter()]
    [switch]$RequirePrivateCorpus,

    [Parameter()]
    [switch]$RequireCurrentDatabase,

    [Parameter()]
    [string]$PrivateManifestPath = $env:APP_PRODUCT_CATALOG_PRIVATE_MANIFEST,

    [Parameter()]
    [string]$PrivateCorpusRoot = $env:APP_PRODUCT_CATALOG_PRIVATE_CORPUS_ROOT,

    [Parameter()]
    [string]$PythonExecutable,

    [Parameter()]
    [switch]$ReleaseMode,

    [Parameter()]
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$python = if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    Join-Path $repositoryRoot ".venv\Scripts\python.exe"
} else {
    [IO.Path]::GetFullPath($PythonExecutable)
}
$backend = Join-Path $repositoryRoot "backend"
$manifest = if ([string]::IsNullOrWhiteSpace($PrivateManifestPath)) {
    Join-Path $repositoryRoot "data\golden\golden-manifest.json"
} else {
    [IO.Path]::GetFullPath($PrivateManifestPath)
}
$privateRoot = if ([string]::IsNullOrWhiteSpace($PrivateCorpusRoot)) {
    Join-Path $repositoryRoot "表格"
} else {
    [IO.Path]::GetFullPath($PrivateCorpusRoot)
}
$runId = [guid]::NewGuid().ToString("N")
$evidencePath = Join-Path ([IO.Path]::GetTempPath()) "clsen-product-canary-$runId.json"
$managed = @(
    "APP_REQUIRE_PRIVATE_CSV_REGRESSION",
    "APP_REQUIRE_PRODUCT_CATALOG_CANARY",
    "APP_PRODUCT_CATALOG_CANARY_EVIDENCE_PATH",
    "APP_PRODUCT_CATALOG_PRIVATE_MANIFEST",
    "APP_PRODUCT_CATALOG_PRIVATE_CORPUS_ROOT"
)
$previous = @{}
foreach ($name in $managed) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name)
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python runtime is unavailable."
}
if ($RequirePrivateCorpus -or $RequireCurrentDatabase) {
    if (
        -not (Test-Path -LiteralPath $manifest -PathType Leaf) -or
        -not (Test-Path -LiteralPath $privateRoot -PathType Container)
    ) {
        throw "The required private CSV corpus and approved manifest are unavailable."
    }
    if ($ReleaseMode) {
        $repositoryPrefix = $repositoryRoot.TrimEnd(
            [IO.Path]::DirectorySeparatorChar
        ) + [IO.Path]::DirectorySeparatorChar
        foreach ($path in @($manifest, $privateRoot)) {
            $resolved = [IO.Path]::GetFullPath($path)
            if ($resolved.StartsWith(
                    $repositoryPrefix,
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                throw "Release private canary inputs must remain outside the repository."
            }
            $item = Get-Item -LiteralPath $resolved -Force
            if ($item.Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) {
                throw "Release private canary inputs must not be reparse points."
            }
        }
    }
    $payload = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 |
        ConvertFrom-Json -AsHashtable -Depth 100
    $reparseEntries = @(
        Get-ChildItem -LiteralPath $privateRoot -Force -Recurse |
            Where-Object {
                $_.Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)
            }
    )
    if ($reparseEntries.Count) {
        throw "Release private canary corpus must not contain reparse points."
    }
    $entries = @($payload.files)
    if ($entries.Count -eq 0) {
        throw "Private canary manifest contains no files."
    }
    $expectedFiles = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($entry in $entries) {
        $relativePath = [string]$entry.path
        if ([IO.Path]::IsPathRooted($relativePath) -or $relativePath.Contains("..")) {
            throw "Private canary manifest contains an unsafe path."
        }
        $path = [IO.Path]::GetFullPath((Join-Path $privateRoot $relativePath))
        $rootPrefix = $privateRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) +
            [IO.Path]::DirectorySeparatorChar
        if (-not $path.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Private canary manifest path escaped the corpus or is missing."
        }
        if (-not $expectedFiles.Add($path)) {
            throw "Private canary manifest contains a duplicate path."
        }
        $digest = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($digest -cne [string]$entry.sha256) {
            throw "Private canary file digest mismatch."
        }
    }
    $actualFiles = @(
        Get-ChildItem -LiteralPath $privateRoot -File -Recurse -Filter "*.csv" |
            ForEach-Object { $_.FullName }
    )
    if ($actualFiles.Count -ne $expectedFiles.Count -or
        @($actualFiles | Where-Object { -not $expectedFiles.Contains($_) }).Count) {
        throw "Private canary corpus has missing or extra CSV files."
    }
}
if (
    $RequireCurrentDatabase -and
    [string]::IsNullOrWhiteSpace($env:APP_PRODUCT_CATALOG_CANARY_DATABASE_URL)
) {
    throw "APP_PRODUCT_CATALOG_CANARY_DATABASE_URL is required and must be SELECT-only."
}
if (-not $RequirePrivateCorpus -and -not $RequireCurrentDatabase) {
    throw "Select at least one required canary input; an empty canary is forbidden."
}
if ($ValidateOnly) {
    Write-Host "Product catalog canary inputs validated without execution."
    return
}

try {
    # The database oracle and its approved scope are part of the same manifest,
    # including when only the read-only database node is selected.
    $env:APP_PRODUCT_CATALOG_PRIVATE_MANIFEST = $manifest
    $env:APP_PRODUCT_CATALOG_PRIVATE_CORPUS_ROOT = $privateRoot
    if ($RequirePrivateCorpus) {
        $env:APP_REQUIRE_PRIVATE_CSV_REGRESSION = "1"
    }
    $env:APP_REQUIRE_PRODUCT_CATALOG_CANARY = "1"
    $env:APP_PRODUCT_CATALOG_CANARY_EVIDENCE_PATH = $evidencePath
    $tests = [Collections.Generic.List[string]]::new()
    if ($RequirePrivateCorpus) {
        $tests.Add("tests/integration/test_real_csv_regression.py")
        $tests.Add(
            "tests/integration/test_product_catalog_canary.py::" +
            "test_private_representatives_preserve_shape_quoting_and_identity_semantics"
        )
    }
    if ($RequireCurrentDatabase) {
        $tests.Add(
            "tests/integration/test_product_catalog_canary.py::" +
            "test_current_database_read_only_snapshot_matches_approved_counts"
        )
    }
    Push-Location -LiteralPath $backend
    try {
        & $python -m pytest @tests -q
        if ($LASTEXITCODE -ne 0) { throw "Product catalog canary failed." }
    }
    finally { Pop-Location }
    if ($RequireCurrentDatabase) {
        if (-not (Test-Path -LiteralPath $evidencePath -PathType Leaf)) {
            throw "Current database canary did not produce allowlisted evidence."
        }
        $evidence = Get-Content -Raw -LiteralPath $evidencePath |
            ConvertFrom-Json -AsHashtable
        $allowed = @(
            "artifact_digest", "candidate_style_count", "consistent_as_of",
            "distinct_seller_sku_count", "normalization_version", "query_digest",
            "report_membership_counts", "safe_output", "strict_seller_sku_count",
            "anomaly_count"
        )
        if (Compare-Object ([string[]]$evidence.Keys | Sort-Object) ($allowed | Sort-Object)) {
            throw "Current database canary evidence exceeded its output allowlist."
        }
        Write-Host "Current database canary evidence: $evidencePath"
    }
    Write-Host "Product catalog private/read-only canary PASS."
}
finally {
    foreach ($name in $managed) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name])
    }
}
