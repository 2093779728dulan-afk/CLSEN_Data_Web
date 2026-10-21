Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-ExactKeys {
    param(
        [Parameter(Mandatory)] [System.Collections.IDictionary] $Value,
        [Parameter(Mandatory)] [string[]] $Expected,
        [Parameter(Mandatory)] [string] $Context
    )

    $actual = @($Value.Keys | ForEach-Object { [string]$_ } | Sort-Object)
    $wanted = @($Expected | Sort-Object)
    if (($actual -join "`n") -cne ($wanted -join "`n")) {
        throw "$Context has unknown or missing keys."
    }
}

function Assert-RepositoryPath {
    param(
        [Parameter(Mandatory)] [string] $RepositoryRoot,
        [Parameter(Mandatory)] [string] $RelativePath
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath) -or
        [System.IO.Path]::IsPathRooted($RelativePath) -or
        ($RelativePath -split '[\\/]' | Where-Object { $_ -eq '..' })) {
        throw "Unsafe CI suite path '$RelativePath'."
    }
    $root = [System.IO.Path]::GetFullPath($RepositoryRoot)
    $resolved = [System.IO.Path]::GetFullPath((Join-Path $root $RelativePath))
    $prefix = $root.TrimEnd([System.IO.Path]::DirectorySeparatorChar) +
        [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $resolved)) {
        throw "CI suite path '$RelativePath' is missing or outside the repository."
    }
}

function Assert-CiNoDuplicateJsonObjectKeys {
    param(
        [Parameter(Mandatory)] [System.Text.Json.JsonElement]$Element,
        [Parameter(Mandatory)] [string]$Path
    )
    if ($Element.ValueKind -eq [System.Text.Json.JsonValueKind]::Object) {
        $seen = [Collections.Generic.HashSet[string]]::new(
            [StringComparer]::Ordinal
        )
        foreach ($property in $Element.EnumerateObject()) {
            if (-not $seen.Add($property.Name)) {
                throw "Duplicate JSON object key '$($property.Name)' at '$Path'."
            }
            Assert-CiNoDuplicateJsonObjectKeys `
                -Element $property.Value `
                -Path "$Path.$($property.Name)"
        }
    }
    elseif ($Element.ValueKind -eq [System.Text.Json.JsonValueKind]::Array) {
        $index = 0
        foreach ($item in $Element.EnumerateArray()) {
            Assert-CiNoDuplicateJsonObjectKeys $item "${Path}[$index]"
            $index++
        }
    }
}

function Import-CiSuiteManifest {
    [CmdletBinding()]
    param(
        [string] $Path = (Join-Path $PSScriptRoot "ci-suite-manifest.json"),
        [string] $RepositoryRoot = (Split-Path $PSScriptRoot -Parent)
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "CI suite manifest not found at '$Path'."
    }
    $document = $null
    try {
        $json = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        $document = [System.Text.Json.JsonDocument]::Parse($json)
        Assert-CiNoDuplicateJsonObjectKeys $document.RootElement '$'
        $manifest = $json |
            ConvertFrom-Json -AsHashtable -Depth 100 -ErrorAction Stop
    }
    catch {
        throw "CI suite manifest is not strict JSON: $($_.Exception.Message)"
    }
    finally {
        if ($null -ne $document) { $document.Dispose() }
    }
    if ($manifest -isnot [System.Collections.IDictionary]) {
        throw "CI suite manifest root must be an object."
    }
    Assert-ExactKeys $manifest @(
        "schema_version", "profiles", "mysql_suites", "mysql_exclusions",
        "windows_smoke", "release_suites"
    ) "CI suite manifest"
    if ($manifest.schema_version -ne 1) {
        throw "Unsupported CI suite manifest version."
    }
    Assert-ExactKeys $manifest.profiles @(
        "ubuntu-full", "windows-smoke", "frontend-full",
        "mysql-compatibility", "release-only"
    ) "profiles"
    Assert-ExactKeys $manifest.mysql_suites @(
        "mysql-migrations", "mysql-legacy", "mysql-p0", "mysql-schema-startup",
        "mysql-worker-observability"
    ) "mysql_suites"
    Assert-ExactKeys $manifest.release_suites @(
        "workspace-boundary", "performance", "canary", "restore", "live",
        "deployment", "generated-contract", "project-optimization-baseline"
    ) "release_suites"
    Assert-ExactKeys $manifest.profiles["ubuntu-full"] @(
        "pytest_paths", "pytest_marker", "pytest_ignores", "baseline_fixture"
    ) "ubuntu-full"
    Assert-ExactKeys $manifest.profiles["windows-smoke"] @(
        "baseline_fixture"
    ) "windows-smoke"
    Assert-ExactKeys $manifest.profiles["frontend-full"] @("commands") `
        "frontend-full"
    Assert-ExactKeys $manifest.profiles["mysql-compatibility"] @(
        "versions", "suites", "baseline_fixture"
    ) "mysql-compatibility"
    Assert-ExactKeys $manifest.profiles["release-only"] @("suites") `
        "release-only"
    Assert-ExactKeys $manifest.windows_smoke @(
        "paths", "pytest_marker", "contract_node_allowlist"
    ) "windows_smoke"
    foreach ($suiteName in $manifest.release_suites.Keys) {
        $expectedKeys = if ($suiteName -in @("performance", "project-optimization-baseline")) {
            @("pytest_paths", "runner_paths")
        } else {
            @("pytest_paths")
        }
        Assert-ExactKeys $manifest.release_suites[$suiteName] $expectedKeys `
            "release suite '$suiteName'"
    }

    $compatibility = @($manifest.profiles["mysql-compatibility"].suites)
    if (($compatibility -join "|") -cne
        "mysql-migrations|mysql-legacy|mysql-p0|mysql-schema-startup|" +
        "mysql-worker-observability") {
        throw "mysql-compatibility suite order is immutable."
    }
    $versions = @($manifest.profiles["mysql-compatibility"].versions)
    if (($versions -join "|") -cne "8.4") {
        throw "Oracle MySQL 8.4 is the required compatibility version."
    }

    $allPaths = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($suiteName in $manifest.mysql_suites.Keys) {
        $suitePaths = @($manifest.mysql_suites[$suiteName])
        if ($suitePaths.Count -eq 0) {
            throw "MySQL suite '$suiteName' must not be empty."
        }
        foreach ($relativePath in $suitePaths) {
            Assert-RepositoryPath $RepositoryRoot ([string]$relativePath)
            if (-not $allPaths.Add([string]$relativePath)) {
                throw "Duplicate CI suite path '$relativePath'."
            }
        }
    }
    foreach ($relativePath in @($manifest.windows_smoke.paths)) {
        Assert-RepositoryPath $RepositoryRoot ([string]$relativePath)
        if (-not $allPaths.Add([string]$relativePath)) {
            throw "Duplicate CI suite path '$relativePath'."
        }
    }
    foreach ($suiteName in $manifest.release_suites.Keys) {
        foreach ($relativePath in @($manifest.release_suites[$suiteName].pytest_paths)) {
            Assert-RepositoryPath $RepositoryRoot ([string]$relativePath)
            if (-not $allPaths.Add([string]$relativePath)) {
                throw "Duplicate CI suite path '$relativePath'."
            }
        }
    }
    $identityPaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($identitySuite in @("performance", "project-optimization-baseline")) {
        foreach ($relativePath in @($manifest.release_suites[$identitySuite].runner_paths)) {
            Assert-RepositoryPath $RepositoryRoot ([string]$relativePath)
            if (-not $identityPaths.Add("$identitySuite`:$relativePath")) {
                throw "Duplicate $identitySuite runner identity path '$relativePath'."
            }
        }
    }
    if ($identityPaths.Count -eq 0) {
        throw "Performance runner identity paths must not be empty."
    }
    foreach ($entry in $manifest.mysql_exclusions.GetEnumerator()) {
        Assert-RepositoryPath $RepositoryRoot ([string]$entry.Key)
        if ([string]::IsNullOrWhiteSpace([string]$entry.Value)) {
            throw "MySQL exclusion '$($entry.Key)' requires a reason."
        }
    }
    return $manifest
}

function Get-CiProfile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Name,
        [System.Collections.IDictionary] $Manifest = (Import-CiSuiteManifest)
    )
    if (-not $Manifest.profiles.Contains($Name)) {
        throw "Unknown CI profile '$Name'."
    }
    return $Manifest.profiles[$Name]
}

function Get-MySqlSuitePaths {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string[]] $Suites,
        [System.Collections.IDictionary] $Manifest = (Import-CiSuiteManifest)
    )
    $paths = [System.Collections.Generic.List[string]]::new()
    foreach ($suite in $Suites) {
        if ($Manifest.mysql_suites.Contains($suite)) {
            $suitePaths = @($Manifest.mysql_suites[$suite])
        }
        elseif ($suite -in @("performance", "restore", "project-optimization-baseline")) {
            $suitePaths = @($Manifest.release_suites[$suite].pytest_paths)
        }
        else {
            throw "Unknown MySQL-backed suite '$suite'."
        }
        if ($suitePaths.Count -eq 0) {
            throw "MySQL-backed suite '$suite' must not be empty."
        }
        foreach ($path in $suitePaths) {
            $paths.Add([string]$path)
        }
    }
    return @($paths)
}

function Get-ReleaseSuite {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Name,
        [System.Collections.IDictionary] $Manifest = (Import-CiSuiteManifest)
    )
    if (-not $Manifest.release_suites.Contains($Name)) {
        throw "Unknown release suite '$Name'."
    }
    return $Manifest.release_suites[$Name]
}

Export-ModuleMember -Function Import-CiSuiteManifest, Get-CiProfile,
    Get-MySqlSuitePaths, Get-ReleaseSuite
