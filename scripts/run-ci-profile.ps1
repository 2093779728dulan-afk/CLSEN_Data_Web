#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet(
        "ubuntu-full", "windows-smoke", "frontend-full",
        "mysql-compatibility", "release-only"
    )]
    [string]$Profile,

    [Parameter()]
    [ValidateSet("checks", "browser", "build", "a11y", "visual")]
    [string]$FrontendStage,

    [Parameter()]
    [ValidateRange(1, 4)]
    [int]$StorybookShard,

    [Parameter()]
    [ValidateSet("8.0", "8.4")]
    [string]$MySqlVersion,

    [Parameter()]
    [ValidateSet(
        "workspace-boundary", "performance", "canary", "restore", "live",
        "deployment", "generated-contract", "project-optimization-baseline"
    )]
    [string]$ReleaseSuite,

    [Parameter()]
    [ValidatePattern("\A[0-9a-f]{40}\z")]
    [string]$SourceSha,

    [Parameter()]
    [string]$PythonExecutable,

    [Parameter()]
    [switch]$ListOnly,

    [Parameter()]
    [switch]$Stage0IdentityOnly,

    [Parameter()]
    [switch]$ValidateOnly,

    [Parameter()]
    [string]$EvidenceRoot = $env:APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backendDirectory = Join-Path $repositoryRoot "backend"
$formalQuickDiagnosticNode = "tests/performance/test_project_optimization_baseline.py::test_heartbeat_long_task_quick_check"
Import-Module (Join-Path $PSScriptRoot "CiSuiteManifest.psm1") -Force
$manifest = Import-CiSuiteManifest -RepositoryRoot $repositoryRoot
$profileDefinition = Get-CiProfile -Name $Profile -Manifest $manifest

function Resolve-ValidatedPython {
    param([AllowEmptyString()] [string]$Requested)

    $candidate = $Requested
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $candidate = if ($IsWindows) {
            Join-Path $repositoryRoot ".venv\Scripts\python.exe"
        } else {
            Join-Path $repositoryRoot ".venv/bin/python"
        }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            Push-Location -LiteralPath $repositoryRoot
            try {
                $commonDirectory = (@(git rev-parse --git-common-dir 2>&1) -join "").Trim()
                if ($LASTEXITCODE -eq 0) {
                    $commonPath = if ([IO.Path]::IsPathFullyQualified($commonDirectory)) {
                        [IO.Path]::GetFullPath($commonDirectory)
                    }
                    else {
                        [IO.Path]::GetFullPath(
                            (Join-Path $repositoryRoot $commonDirectory)
                        )
                    }
                    $commonRoot = Split-Path -Parent (
                        $commonPath
                    )
                    $candidate = if ($IsWindows) {
                        Join-Path $commonRoot ".venv\Scripts\python.exe"
                    }
                    else {
                        Join-Path $commonRoot ".venv/bin/python"
                    }
                }
            }
            finally {
                Pop-Location
            }
        }
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Python runtime not found at '$candidate'."
    }
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    $probe = @(
        & $resolved -c (
            "import sys; import alembic, app, pymysql, pytest, sqlalchemy, yaml; " +
            "print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        ) 2>&1
    )
    if ($LASTEXITCODE -ne 0 -or ($probe -join "").Trim() -cne "3.14") {
        throw "Python 3.14 with the locked CI dependencies is required."
    }
    return $resolved
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory)] [string]$Description,
        [Parameter(Mandatory)] [scriptblock]$Command
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Invoke-PytestChecked {
    param(
        [Parameter(Mandatory)] [string]$Description,
        [Parameter(Mandatory)] [string]$Shard,
        [Parameter(Mandatory)] [scriptblock]$Command
    )
    $previousShard = $env:APP_STAGE0_PYTEST_OUTCOME_SHARD
    $previousExpectedDigest = $env:APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST
    try {
        if (-not [string]::IsNullOrWhiteSpace(
                $env:APP_STAGE0_PYTEST_OUTCOME_DIRECTORY
            )) {
            if (
                [string]::IsNullOrWhiteSpace($env:APP_STAGE0_PYTEST_OUTCOME_BINDING) -or
                [string]::IsNullOrWhiteSpace($env:APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID) -or
                [string]::IsNullOrWhiteSpace(
                    $env:APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS
                )
            ) {
                throw "Stage 0 pytest outcome configuration is incomplete."
            }
            try {
                $shardDigests = (
                    $env:APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS |
                        ConvertFrom-Json -AsHashtable
                )
            }
            catch {
                throw "Stage 0 pytest outcome shard identity is invalid."
            }
            if (
                $shardDigests -isnot [Collections.IDictionary] -or
                -not $shardDigests.Contains($Shard) -or
                $shardDigests[$Shard] -isnot [string] -or
                $shardDigests[$Shard] -cnotmatch '\A[0-9a-f]{64}\z'
            ) {
                throw "Stage 0 pytest outcome shard identity is invalid."
            }
            $env:APP_STAGE0_PYTEST_OUTCOME_SHARD = $Shard
            $env:APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST = `
                $shardDigests[$Shard]
        }
        Invoke-NativeChecked -Description $Description -Command $Command
    }
    finally {
        $env:APP_STAGE0_PYTEST_OUTCOME_SHARD = $previousShard
        $env:APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST = `
            $previousExpectedDigest
    }
}

function Get-OrdinalUniqueStrings {
    param([Parameter(Mandatory)] [AllowEmptyCollection()] [string[]]$Values)
    $set = [Collections.Generic.SortedSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($value in $Values) {
        $null = $set.Add($value)
    }
    return @($set)
}

function New-OrdinalStringSet {
    param([Parameter(Mandatory)] [AllowEmptyCollection()] [string[]]$Values)
    $set = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($value in $Values) {
        $null = $set.Add($value)
    }
    return ,$set
}

function Resolve-PnpmCommand {
    $names = if ($IsWindows) { @("pnpm.cmd", "pnpm") } else { @("pnpm") }
    foreach ($name in $names) {
        $command = Get-Command `
            -Name $name `
            -CommandType Application `
            -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $command) {
            return $command.Source
        }
    }
    throw "pnpm is required by the frontend profile."
}

function Get-NodeIds {
    param(
        [Parameter(Mandatory)] [string]$Python,
        [Parameter(Mandatory)] [string[]]$PytestArguments
    )
    Push-Location -LiteralPath $backendDirectory
    try {
        $output = @(& $Python -m pytest @PytestArguments --collect-only -q 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "Pytest collection failed."
        }
    }
    finally {
        Pop-Location
    }
    return @(
        Get-OrdinalUniqueStrings -Values @(
            $output |
            ForEach-Object { [string]$_ } |
            Where-Object { $_ -match '^tests/.+::' } |
            ForEach-Object { "backend/$_" }
        )
    )
}

function Get-BaselineNodes {
    param([Parameter(Mandatory)] [string]$RelativePath)
    $path = Join-Path $repositoryRoot $RelativePath
    return @(
        Get-OrdinalUniqueStrings -Values @(
            Get-Content -LiteralPath $path -Encoding UTF8 |
                Where-Object { $_ -and -not $_.StartsWith("#") }
        )
    )
}

function Get-NodeDigest {
    param([Parameter(Mandatory)] [string[]]$Nodes)
    $canonical = ((Get-OrdinalUniqueStrings -Values $Nodes) -join "`n") + "`n"
    $bytes = [Text.Encoding]::UTF8.GetBytes($canonical)
    return [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($bytes)
    ).ToLowerInvariant()
}

function Assert-BaselineNodes {
    param(
        [Parameter(Mandatory)] [string[]]$Actual,
        [Parameter(Mandatory)] [string[]]$Baseline,
        [switch]$Exact,
        [string[]]$AddedAllowlist = @()
    )
    $actualSet = New-OrdinalStringSet -Values $Actual
    $baselineSet = New-OrdinalStringSet -Values $Baseline
    $missing = @($Baseline | Where-Object { -not $actualSet.Contains($_) })
    if ($missing.Count -gt 0) {
        throw "Profile collection lost $($missing.Count) approved baseline nodes."
    }
    $added = @($Actual | Where-Object { -not $baselineSet.Contains($_) })
    if ($Exact -and $added.Count -gt 0) {
        throw "Profile collection added $($added.Count) nodes to an exact baseline."
    }
    foreach ($node in $added) {
        if (-not ($AddedAllowlist | Where-Object {
                    $node -ceq $_ -or $node -clike $_
                })) {
            throw "Unapproved node '$node' was added to the profile."
        }
    }
}

function Write-ProfileSummary {
    param(
        [string]$Suite,
        [string[]]$Nodes = @(),
        [string]$BaselineComparison = "not-applicable"
    )
    $summary = [ordered]@{
        profile = $Profile
        suite = $Suite
        mysql_version = $MySqlVersion
        node_count = $Nodes.Count
        node_digest = if ($Nodes.Count) { Get-NodeDigest $Nodes } else { $null }
        baseline_comparison = $BaselineComparison
    }
    Write-Output ($summary | ConvertTo-Json -Compress)
}

function Write-Stage0Identity {
    param(
        [Parameter(Mandatory)][string]$IdentityProfile,
        [Parameter(Mandatory)][Collections.IDictionary]$ShardNodes
    )
    $allNodes = [Collections.Generic.List[string]]::new()
    $shardDigests = [ordered]@{}
    $shardCounts = [ordered]@{}
    foreach ($shard in @($ShardNodes.Keys | Sort-Object)) {
        $nodes = @(Get-OrdinalUniqueStrings -Values @($ShardNodes[$shard]))
        if ($nodes.Count -eq 0) {
            throw "Stage 0 shard '$shard' collected no node identities."
        }
        $shardDigests[[string]$shard] = Get-NodeDigest -Nodes $nodes
        $shardCounts[[string]$shard] = $nodes.Count
        foreach ($node in $nodes) {
            $allNodes.Add($node)
        }
    }
    $uniqueNodes = @(Get-OrdinalUniqueStrings -Values $allNodes.ToArray())
    if ($uniqueNodes.Count -ne $allNodes.Count) {
        throw "Stage 0 shard identities overlap."
    }
    $identity = [ordered]@{
        schema_version = 1
        profile = $IdentityProfile
        profile_node_count = $uniqueNodes.Count
        profile_node_digest = Get-NodeDigest -Nodes $uniqueNodes
        shard_node_counts = $shardCounts
        shard_node_digests = $shardDigests
    }
    Write-Output ($identity | ConvertTo-Json -Depth 4 -Compress)
}

if ($Profile -ne "mysql-compatibility" -and $MySqlVersion) {
    throw "MySqlVersion is accepted only by mysql-compatibility."
}
if ($Profile -ne "frontend-full" -and ($FrontendStage -or $StorybookShard)) {
    throw "FrontendStage and StorybookShard are frontend-full parameters."
}
if ($FrontendStage -in @("a11y", "visual")) {
    if (-not $StorybookShard) { throw "A StorybookShard from 1 to 4 is required." }
} elseif ($StorybookShard) {
    throw "StorybookShard is accepted only by the a11y and visual stages."
}
if ($Stage0IdentityOnly -and ($ListOnly -or $ValidateOnly)) {
    throw "Stage0IdentityOnly cannot be combined with ListOnly or ValidateOnly."
}
if ($Stage0IdentityOnly -and $Profile -eq "frontend-full") {
    throw "Stage0IdentityOnly is available only for pytest-bearing profiles."
}
if ($Profile -ne "release-only" -and ($ReleaseSuite -or $SourceSha -or $ValidateOnly)) {
    throw "ReleaseSuite, SourceSha, and ValidateOnly are release-only parameters."
}
if ($Profile -eq "mysql-compatibility" -and -not $MySqlVersion) {
    throw "MySqlVersion is required by mysql-compatibility."
}
if ($Profile -eq "release-only") {
    if (-not $ReleaseSuite -or -not $SourceSha) {
        throw "ReleaseSuite and a verified 40-character SourceSha are required."
    }
    $null = Get-ReleaseSuite -Name $ReleaseSuite -Manifest $manifest
}

$python = if ($Profile -eq "frontend-full") {
    if ($PythonExecutable) {
        throw "frontend-full does not accept PythonExecutable."
    }
    $null
} else {
    Resolve-ValidatedPython -Requested $PythonExecutable
}

if ($Profile -eq "ubuntu-full") {
    $repositoryArguments = @(
        @($profileDefinition.pytest_paths)
        "-m"
        [string]$profileDefinition.pytest_marker
        @($profileDefinition.pytest_ignores | ForEach-Object { "--ignore=$_" })
    )
    $arguments = @(
        @($profileDefinition.pytest_paths | ForEach-Object {
                ([string]$_).Substring("backend/".Length)
            })
        "-m"
        [string]$profileDefinition.pytest_marker
        @($profileDefinition.pytest_ignores | ForEach-Object {
                "--ignore=$(([string]$_).Substring('backend/'.Length))"
            })
    )
    if ($Stage0IdentityOnly) {
        $nodes = Get-NodeIds -Python $python -PytestArguments $arguments
        Write-Stage0Identity `
            -IdentityProfile "ubuntu-full" `
            -ShardNodes ([ordered]@{ pytest = $nodes })
        exit 0
    }
    if ($ListOnly) {
        $nodes = Get-NodeIds -Python $python -PytestArguments $arguments
        $baseline = Get-BaselineNodes $profileDefinition.baseline_fixture
        Assert-BaselineNodes -Actual $nodes -Baseline $baseline -AddedAllowlist @(
            "backend/tests/contracts/test_ci_suite_manifest.py::*",
            "backend/tests/contracts/test_release_evidence_contract.py::*",
            "backend/tests/unit/imports/test_storage.py::test_validate_rejects_noncanonical_storage_keys[sha256/aa/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]"
        )
        Write-ProfileSummary -Suite "offline-backend" -Nodes $nodes `
            -BaselineComparison "baseline-preserved"
        exit 0
    }
    Push-Location -LiteralPath $repositoryRoot
    try {
        Invoke-NativeChecked "Ruff lint" {
            & $python -m ruff check --config backend/pyproject.toml backend/app backend/tests
        }
        Invoke-NativeChecked "Ruff format check" {
            & $python -m ruff format --check --config backend/pyproject.toml backend/app backend/tests
        }
        Invoke-NativeChecked "mypy" {
            & $python -m mypy --config-file backend/pyproject.toml backend/app backend/tests
        }
        Invoke-PytestChecked "offline backend tests" -Shard "pytest" {
            & $python -m pytest @repositoryArguments
        }
    }
    finally { Pop-Location }
    exit 0
}

if ($Profile -eq "windows-smoke") {
    $paths = @(
        $manifest.windows_smoke.paths |
            ForEach-Object { ([string]$_).Substring("backend/".Length) }
    )
    $arguments = @($paths + @("-m", "not mysql"))
    if ($Stage0IdentityOnly) {
        $nodes = Get-NodeIds -Python $python -PytestArguments $arguments
        Write-Stage0Identity `
            -IdentityProfile "windows-smoke" `
            -ShardNodes ([ordered]@{ pytest = $nodes })
        exit 0
    }
    if ($ListOnly) {
        $nodes = Get-NodeIds -Python $python -PytestArguments $arguments
        $baseline = Get-BaselineNodes $profileDefinition.baseline_fixture
        Assert-BaselineNodes -Actual $nodes -Baseline $baseline `
            -AddedAllowlist @($manifest.windows_smoke.contract_node_allowlist)
        Write-ProfileSummary -Suite "windows-cross-platform" -Nodes $nodes `
            -BaselineComparison "baseline-preserved"
        exit 0
    }
    Push-Location -LiteralPath $backendDirectory
    try {
        Invoke-PytestChecked "Windows smoke tests" -Shard "pytest" {
            & $python -m pytest @arguments
        }
    }
    finally { Pop-Location }
    exit 0
}

if ($Profile -eq "frontend-full") {
    if ($ListOnly) {
        $commands = @($profileDefinition.commands)
        if ($FrontendStage) {
            $commands = @(switch ($FrontendStage) {
                "checks" { $commands[0..3] }
                "browser" { $commands[4] }
                "build" { $commands[5]; $commands[8..9] }
                "a11y" { "$($commands[6]) --shard=$StorybookShard/4 --fully-parallel --workers=1 --reporter=line" }
                "visual" { "$($commands[7]) --shard=$StorybookShard/4 --fully-parallel --workers=1 --reporter=line" }
            })
        }
        Write-Output (ConvertTo-Json -InputObject $commands -Compress)
        exit 0
    }
    Push-Location -LiteralPath (Join-Path $repositoryRoot "frontend")
    try {
        $pnpm = Resolve-PnpmCommand
        if (-not $FrontendStage -or $FrontendStage -eq "checks") {
            Invoke-NativeChecked "frontend lint" { & $pnpm lint }
            Invoke-NativeChecked "frontend typecheck" { & $pnpm typecheck }
            Invoke-NativeChecked "frontend design-system token policy" { & $pnpm test:tokens }
            Invoke-NativeChecked "frontend unit tests" { & $pnpm test --run }
        }
        if (-not $FrontendStage -or $FrontendStage -eq "browser") {
            $previousPlaywrightPort = $env:PLAYWRIGHT_PORT
            $previousCutoverRun = $env:PLAYWRIGHT_CUTOVER_RUN
            $previousPlaywrightSource = $env:VITE_PRODUCT_ANALYTICS_SOURCE
            $portListener = [Net.Sockets.TcpListener]::new(
                [Net.IPAddress]::Loopback,
                0
            )
            try {
                $portListener.Start()
                $env:PLAYWRIGHT_PORT = [string](
                    ([Net.IPEndPoint]$portListener.LocalEndpoint).Port
                )
            }
            finally { $portListener.Stop() }
            try {
                $env:PLAYWRIGHT_CUTOVER_RUN = "1"
                $env:VITE_PRODUCT_ANALYTICS_SOURCE = "p0_catalog"
                Invoke-NativeChecked "frontend browser tests" {
                    & $pnpm exec playwright test
                }
            }
            finally {
                $env:PLAYWRIGHT_PORT = $previousPlaywrightPort
                $env:PLAYWRIGHT_CUTOVER_RUN = $previousCutoverRun
                $env:VITE_PRODUCT_ANALYTICS_SOURCE = $previousPlaywrightSource
            }
        }
        if (-not $FrontendStage -or $FrontendStage -eq "build") {
            Invoke-NativeChecked "frontend Storybook static build" { & $pnpm storybook:build }
        }
        if (-not $FrontendStage -or $FrontendStage -eq "a11y") {
            Invoke-NativeChecked "frontend Storybook accessibility gate" {
                if ($FrontendStage) {
                    & $pnpm test:a11y "--shard=$StorybookShard/4" --fully-parallel --workers=1 --reporter=line
                } else { & $pnpm test:a11y }
            }
        }
        if (-not $FrontendStage -or $FrontendStage -eq "visual") {
            Invoke-NativeChecked "frontend Storybook visual gate" {
                if ($FrontendStage) {
                    & $pnpm test:visual "--shard=$StorybookShard/4" --fully-parallel --workers=1 --reporter=line
                } else { & $pnpm test:visual }
            }
        }
        if (-not $FrontendStage -or $FrontendStage -eq "build") {
            foreach ($source in @("legacy_parser", "p0_catalog")) {
                $previous = $env:VITE_PRODUCT_ANALYTICS_SOURCE
                try {
                    $env:VITE_PRODUCT_ANALYTICS_SOURCE = $source
                    Invoke-NativeChecked "frontend $source production build" { & $pnpm build }
                }
                finally { $env:VITE_PRODUCT_ANALYTICS_SOURCE = $previous }
            }
        }
    }
    finally { Pop-Location }
    exit 0
}

if ($Profile -eq "mysql-compatibility") {
    $suites = @($profileDefinition.suites)
    $repositoryPaths = @(Get-MySqlSuitePaths -Suites $suites -Manifest $manifest)
    $paths = @($repositoryPaths | ForEach-Object { $_.Substring("backend/".Length) })
    if ($Stage0IdentityOnly) {
        $historicalNodeFixture = Join-Path $repositoryRoot "backend/tests/fixtures/ci/mysql-historical-nodeids.txt"
        $historicalNodes = @(
            Get-Content -LiteralPath $historicalNodeFixture -Encoding UTF8 |
                Where-Object { $_ -and -not $_.StartsWith("#") }
        )
        $migrationNodes = Get-NodeIds `
            -Python $python `
            -PytestArguments $historicalNodes
        $scopedPaths = @($paths | Where-Object { $_ -cne "tests/integration/test_migrations.py" })
        $scopedArguments = @($scopedPaths) + @(
            $historicalNodes |
                Where-Object { ($_ -split "::", 2)[0] -cne "tests/integration/test_migrations.py" } |
                ForEach-Object { "--deselect=$_" }
        )
        $scopedNodes = Get-NodeIds `
            -Python $python `
            -PytestArguments $scopedArguments
        Write-Stage0Identity `
            -IdentityProfile "mysql-compatibility" `
            -ShardNodes ([ordered]@{
                migration = $migrationNodes
                scoped = $scopedNodes
            })
        exit 0
    }
    if ($ListOnly) {
        $nodes = Get-NodeIds -Python $python -PytestArguments $paths
        $baseline = Get-BaselineNodes $profileDefinition.baseline_fixture
        Assert-BaselineNodes -Actual $nodes -Baseline $baseline -Exact
        Write-ProfileSummary -Suite ($suites -join ",") -Nodes $nodes `
            -BaselineComparison "exact"
        exit 0
    }
    & (Join-Path $PSScriptRoot "test-mysql-matrix.ps1") `
        -Versions @($MySqlVersion) `
        -Suites $suites `
        -PythonExecutable $python `
        -Confirm:$false
    if ($LASTEXITCODE -ne 0) { throw "MySQL compatibility profile failed." }
    exit 0
}

$releaseDefinition = Get-ReleaseSuite -Name $ReleaseSuite -Manifest $manifest
if ($Stage0IdentityOnly) {
    $releasePaths = @(
        $releaseDefinition.pytest_paths |
            ForEach-Object { ([string]$_).Substring("backend/".Length) }
    )
    $releasePytestArguments = @($releasePaths)
    if ($ReleaseSuite -ceq "project-optimization-baseline") {
        $releasePytestArguments += @(
            "--deselect",
            $formalQuickDiagnosticNode
        )
    }
    $nodes = Get-NodeIds -Python $python -PytestArguments $releasePytestArguments
    Write-Stage0Identity `
        -IdentityProfile $ReleaseSuite `
        -ShardNodes ([ordered]@{ scoped = $nodes })
    exit 0
}
if ($ListOnly) {
    $releasePaths = @($releaseDefinition.pytest_paths)
    Write-ProfileSummary -Suite $ReleaseSuite -Nodes $releasePaths
    exit 0
}

$requiredFiles = @{
    "workspace-boundary" = @("scripts/check-worktree-text.ps1")
    "performance" = @("scripts/run-product-catalog-performance.ps1")
    "canary" = @("scripts/run-product-catalog-canary.ps1")
    "restore" = @("scripts/run-product-catalog-backup-restore.ps1")
    "live" = @("scripts/run-product-catalog-live-e2e.ps1")
    "deployment" = @(
        "ops/bootstrap-secrets.ps1",
        "ops/verify-deployment.ps1"
    )
    "generated-contract" = @("scripts/generate-api-client.ps1")
    "project-optimization-baseline" = @(
        "scripts/project-optimization-baseline-manifest.json",
        "tools/project_optimization_baseline.py",
        "backend/tests/performance/project_optimization_baseline.py",
        "backend/tests/performance/test_project_optimization_baseline.py",
        "frontend/playwright.baseline.config.ts",
        "frontend/playwright.config.ts",
        "frontend/tests/e2e/project-optimization-baseline.spec.ts",
        "frontend/scripts/project-optimization-bundle-baseline.mjs",
        "scripts/run-project-optimization-baseline.ps1"
    )
}
foreach ($relativePath in $requiredFiles[$ReleaseSuite]) {
    if (-not (Test-Path -LiteralPath (Join-Path $repositoryRoot $relativePath) -PathType Leaf)) {
        throw "Release suite dependency '$relativePath' is missing."
    }
}
if ($ValidateOnly) {
    switch ($ReleaseSuite) {
        "performance" {
            & (Join-Path $PSScriptRoot "run-product-catalog-performance.ps1") `
                -SourceSha $SourceSha `
                -PythonExecutable $python `
                -ValidateOnly
        }
        "canary" {
            & (Join-Path $PSScriptRoot "run-product-catalog-canary.ps1") `
                -RequirePrivateCorpus `
                -RequireCurrentDatabase `
                -PrivateManifestPath $env:APP_PRODUCT_CATALOG_PRIVATE_MANIFEST `
                -PrivateCorpusRoot $env:APP_PRODUCT_CATALOG_PRIVATE_CORPUS_ROOT `
                -PythonExecutable $python `
                -ReleaseMode `
                -ValidateOnly
        }
        "restore" {
            & (Join-Path $PSScriptRoot "run-product-catalog-backup-restore.ps1") `
                -PythonExecutable $python `
                -ValidateOnly
        }
        "live" {
            & (Join-Path $PSScriptRoot "run-product-catalog-live-e2e.ps1") `
                -Milestone All `
                -ValidateOnly
        }
        "workspace-boundary" {
            Push-Location $repositoryRoot
            try {
                if ((git rev-parse HEAD) -cne $SourceSha) {
                    throw "Workspace HEAD differs from the release source."
                }
                if (git status --porcelain) {
                    throw "Release workspace is not clean."
                }
            }
            finally { Pop-Location }
        }
        "deployment" {
            foreach ($path in @(
                    "ops/docker-compose.yml",
                    "ops/bootstrap-secrets.ps1"
                )) {
                if (-not (Test-Path -LiteralPath (Join-Path $repositoryRoot $path))) {
                    throw "Deployment prerequisite '$path' is missing."
                }
            }
            if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
                throw "Docker is required by deployment verification."
            }
        }
        "generated-contract" {
            if (-not (Test-Path -LiteralPath (
                        Join-Path $repositoryRoot "frontend/src/api/generated.ts"
                    ) -PathType Leaf)) {
                throw "Generated API client is missing."
            }
        }
        "project-optimization-baseline" {
            $temporaryEvidenceRoot = $null
            try {
                $validationEvidenceRoot = $EvidenceRoot
                if ([string]::IsNullOrWhiteSpace($validationEvidenceRoot)) {
                    $temporaryEvidenceRoot = Join-Path `
                        ([IO.Path]::GetTempPath()) `
                        "clsen-stage0-validate-$PID-$([guid]::NewGuid().ToString('N'))"
                    New-Item `
                        -ItemType Directory `
                        -Path $temporaryEvidenceRoot `
                        -ErrorAction Stop | Out-Null
                    $validationEvidenceRoot = $temporaryEvidenceRoot
                }
                & (Join-Path $PSScriptRoot "run-project-optimization-baseline.ps1") `
                    -SourceSha $SourceSha `
                    -PythonExecutable $python `
                    -EvidenceRoot $validationEvidenceRoot `
                    -Mode Validate
            }
            finally {
                if (
                    $null -ne $temporaryEvidenceRoot -and
                    (Test-Path -LiteralPath $temporaryEvidenceRoot -PathType Container) -and
                    (Split-Path -Leaf $temporaryEvidenceRoot) -cmatch
                        '\Aclsen-stage0-validate-[0-9]+-[0-9a-f]{32}\z'
                ) {
                    Remove-Item -LiteralPath $temporaryEvidenceRoot
                }
            }
        }
        default {
            Write-Output "Validated release-only suite '$ReleaseSuite' for $SourceSha."
        }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Release-only suite '$ReleaseSuite' validation failed."
    }
    exit 0
}

switch ($ReleaseSuite) {
    "workspace-boundary" {
        Push-Location $repositoryRoot
        try {
            Invoke-NativeChecked "source SHA check" { git merge-base --is-ancestor $SourceSha HEAD }
            Invoke-NativeChecked "worktree check" { git diff --exit-code }
            Invoke-NativeChecked "index check" { git diff --cached --exit-code }
        }
        finally { Pop-Location }
    }
    "performance" {
        & (Join-Path $PSScriptRoot "run-product-catalog-performance.ps1") `
            -SourceSha $SourceSha `
            -PythonExecutable $python
    }
    "canary" {
        & (Join-Path $PSScriptRoot "run-product-catalog-canary.ps1") `
            -RequirePrivateCorpus `
            -RequireCurrentDatabase `
            -PrivateManifestPath $env:APP_PRODUCT_CATALOG_PRIVATE_MANIFEST `
            -PrivateCorpusRoot $env:APP_PRODUCT_CATALOG_PRIVATE_CORPUS_ROOT `
            -PythonExecutable $python `
            -ReleaseMode
    }
    "restore" {
        & (Join-Path $PSScriptRoot "run-product-catalog-backup-restore.ps1") `
            -PythonExecutable $python
    }
    "live" {
        & (Join-Path $PSScriptRoot "run-product-catalog-live-e2e.ps1") -Milestone All
    }
    "deployment" {
        & (Join-Path $repositoryRoot "ops/verify-deployment.ps1") -DisposableTestRun
    }
    "generated-contract" {
        & (Join-Path $PSScriptRoot "generate-api-client.ps1") -Check
    }
    "project-optimization-baseline" {
        if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
            throw "EvidenceRoot is required for baseline collection."
        }
        & (Join-Path $PSScriptRoot "run-project-optimization-baseline.ps1") `
            -SourceSha $SourceSha `
            -PythonExecutable $python `
            -EvidenceRoot $EvidenceRoot `
            -Mode Collect
    }
}
if ($LASTEXITCODE -ne 0) {
    throw "Release-only suite '$ReleaseSuite' failed."
}
