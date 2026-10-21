#Requires -Version 7.0

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [Parameter()]
    [ValidateSet("8.0", "8.4")]
    [string[]]$Versions = @("8.4"),

    [Parameter(Mandatory)]
    [ValidateSet(
        "mysql-migrations", "mysql-legacy", "mysql-p0", "performance", "restore",
        "project-optimization-baseline", "mysql-schema-startup",
        "mysql-worker-observability"
    )]
    [string[]]$Suites,

    [Parameter()]
    [string[]]$DevelopmentTests = @(),

    [Parameter(Mandatory)]
    [string]$PythonExecutable,

    [Parameter()]
    [switch]$PerformanceProfile,

    # Diagnostic-only single-node timing. This never produces release evidence.
    [Parameter()]
    [switch]$Diagnostic,

    # B-batch independent quick check. This is diagnostic-only and never formal evidence.
    [Parameter()]
    [switch]$QuickDiagnostic,

    [Parameter()]
    [ValidatePattern("\A[0-9a-f]{40}\z")]
    [string]$SourceSha,

    [Parameter()]
    [string]$DiagnosticEvidenceRoot,

    [Parameter()]
    [ValidateSet(
        "tests/performance/test_project_optimization_baseline.py::test_heartbeat_candidate_baselines",
        "tests/performance/test_project_optimization_baseline.py::test_heartbeat_long_task_quick_check"
    )]
    [string]$DiagnosticNode
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$developmentMode = $DevelopmentTests.Count -gt 0
$quickDiagnosticMode = $QuickDiagnostic.IsPresent
$diagnosticMode = $Diagnostic.IsPresent -or $quickDiagnosticMode
$diagnosticTestTarget = $null
$quickDiagnosticNode = "tests/performance/test_project_optimization_baseline.py::test_heartbeat_long_task_quick_check"
$diagnosticRunDirectory = $null
$diagnosticMetadataPath = $null
$diagnosticIdentity = $null
if ($diagnosticMode) {
    if ($Diagnostic.IsPresent -and $QuickDiagnostic.IsPresent) {
        throw "Diagnostic timing cannot combine full and quick diagnostic modes."
    }
    if ($developmentMode -or $PerformanceProfile) {
        throw "Diagnostic timing cannot combine with DevelopmentTests or PerformanceProfile."
    }
    if ($Versions.Count -ne 1) {
        throw "Diagnostic timing requires exactly one MySQL version."
    }
    if ($Suites.Count -ne 1 -or $Suites[0] -cne "project-optimization-baseline") {
        throw "Diagnostic timing requires the project-optimization-baseline suite only."
    }
    if ([string]::IsNullOrWhiteSpace($SourceSha)) {
        throw "Diagnostic timing requires an explicit clean checkout SourceSha."
    }
    if ([string]::IsNullOrWhiteSpace($DiagnosticEvidenceRoot)) {
        throw "Diagnostic timing requires an external DiagnosticEvidenceRoot."
    }
    if ([string]::IsNullOrWhiteSpace($DiagnosticNode)) {
        throw "Diagnostic timing requires an explicit DiagnosticNode."
    }
    foreach ($name in @(
            "APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT",
            "APP_PROJECT_OPTIMIZATION_RUN_DIR",
            "APP_RELEASE_SOURCE_SHA",
            "APP_BASELINE_MYSQL_VERSION",
            "APP_PROJECT_OPTIMIZATION_QUICK_CHECK",
            "APP_STAGE0_PYTEST_OUTCOME_DIRECTORY",
            "APP_STAGE0_PYTEST_OUTCOME_BINDING"
        )) {
        if (-not [string]::IsNullOrWhiteSpace(
                [Environment]::GetEnvironmentVariable(
                    $name,
                    [EnvironmentVariableTarget]::Process
                )
            )) {
            throw "Diagnostic timing requires process variable '$name' to be unset before preflight."
        }
    }
}
elseif (
    -not [string]::IsNullOrWhiteSpace($SourceSha) -or
    -not [string]::IsNullOrWhiteSpace($DiagnosticEvidenceRoot) -or
    -not [string]::IsNullOrWhiteSpace($DiagnosticNode)
) {
    throw "SourceSha, DiagnosticEvidenceRoot, and DiagnosticNode require -Diagnostic or -QuickDiagnostic."
}

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backendDirectory = Join-Path $repositoryRoot "backend"
$historicalNodeFixture = Join-Path $repositoryRoot "backend/tests/fixtures/ci/mysql-historical-nodeids.txt"
$historicalNodes = @(
    Get-Content -LiteralPath $historicalNodeFixture -Encoding UTF8 |
        Where-Object { $_ -and -not $_.StartsWith("#") }
)
$privilegeManifestPath = Join-Path $PSScriptRoot "database-privileges.json"
Import-Module (Join-Path $PSScriptRoot "DatabaseContract.psm1") -Force
$runIdentifier = [guid]::NewGuid().ToString("N")
$testDatabaseName = "clsen_data_test_$($runIdentifier.Substring(0, 16))"
$forbiddenDatabaseName = "clsen_data"
$migrationUser = "clsen_migrator"
$runtimeUser = "clsen_app"
$backupUser = "clsen_backup"
$schemaUnreadableUser = "clsen_schema_unreadable"
$accountHost = "%"

$databasePrivileges = Import-StrictDatabasePrivilegeManifest `
    -LiteralPath $privilegeManifestPath

if ([string]::Equals(
        $testDatabaseName,
        $forbiddenDatabaseName,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Refusing to run the compatibility matrix against production database '$forbiddenDatabaseName'."
}
if ($testDatabaseName -notmatch '\Aclsen_data_test(?:_[a-z0-9_]+)?\z') {
    throw "The matrix database must be a disposable clsen_data_test* database."
}
if (-not (Test-Path -LiteralPath $backendDirectory -PathType Container)) {
    throw "Backend project not found at '$backendDirectory'. The checkout may be incomplete."
}

$pythonExecutable = if (Test-Path -LiteralPath $PythonExecutable -PathType Leaf) {
    (Resolve-Path -LiteralPath $PythonExecutable).Path
} else {
    throw "Python runtime not found at '$PythonExecutable'."
}

Import-Module (Join-Path $PSScriptRoot "CiSuiteManifest.psm1") -Force
$manifest = Import-CiSuiteManifest -RepositoryRoot $repositoryRoot
$repositoryPaths = @(Get-MySqlSuitePaths -Suites $Suites -Manifest $manifest)
$selectedRepositoryPaths = $repositoryPaths
if ($DevelopmentTests.Count -gt 0) {
    foreach ($developmentTest in $DevelopmentTests) {
        if ($repositoryPaths -cnotcontains $developmentTest) {
            throw (
                "Development test '$developmentTest' is not allowlisted by " +
                "the selected MySQL suites."
            )
        }
    }
    $selectedRepositoryPaths = @($DevelopmentTests)
}
$PytestPaths = @(
    $selectedRepositoryPaths | ForEach-Object {
        if (-not ([string]$_).StartsWith("backend/", [StringComparison]::Ordinal)) {
            throw "MySQL suite path '$_' is not backend-relative."
        }
        ([string]$_).Substring("backend/".Length)
    }
)
if ($PytestPaths.Count -eq 0) {
    throw "At least one allowlisted MySQL suite is required."
}

$pythonVersionOutput = @(& $pythonExecutable -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to run the virtual-environment Python at '$pythonExecutable'."
}
$pythonVersion = ($pythonVersionOutput -join "").Trim()
if ($pythonVersion -ne "3.14") {
    throw "The MySQL matrix requires Python 3.14; '$pythonExecutable' reports Python $pythonVersion."
}

$dependencyCheckOutput = @(
    & $pythonExecutable -c "import alembic, app, pymysql, pytest, sqlalchemy" 2>&1
)
if ($LASTEXITCODE -ne 0) {
    throw "The Python 3.14 test runtime is incomplete. Install backend/requirements.lock with --require-hashes and install backend editable with --no-deps."
}
foreach ($pytestPath in $PytestPaths) {
    if (
        [string]::IsNullOrWhiteSpace($pytestPath) -or
        $pytestPath -cnotmatch '\Atests/[A-Za-z0-9_./-]+\.py\z' -or
        $pytestPath.Contains("..")
    ) {
        throw "Pytest paths must be explicit backend-relative tests/*.py paths."
    }
    $resolvedPytestPath = [IO.Path]::GetFullPath(
        (Join-Path $backendDirectory $pytestPath)
    )
    if (
        -not $resolvedPytestPath.StartsWith(
            [IO.Path]::GetFullPath($backendDirectory + [IO.Path]::DirectorySeparatorChar),
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not (Test-Path -LiteralPath $resolvedPytestPath -PathType Leaf)
    ) {
        throw "Pytest path '$pytestPath' is outside the backend or does not exist."
    }
}
$expectedSchemaRevision = Get-DatabaseSchemaRevision `
    -PythonExecutable $pythonExecutable `
    -BackendDirectory $backendDirectory

$canonicalIdentityProbe = @'
import json
from tests.performance.project_optimization_baseline import _release_identity
identity = _release_identity()
if not identity:
    raise RuntimeError("canonical release identity was empty")
print(json.dumps(identity, sort_keys=True))
'@

function Resolve-DiagnosticEvidenceRoot {
    param([Parameter(Mandatory)][string]$Value)
    if (-not [IO.Path]::IsPathFullyQualified($Value) -or -not (Test-Path -LiteralPath $Value -PathType Container)) {
        throw "DiagnosticEvidenceRoot must be an existing external directory."
    }
    $resolvedFull = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Value).Path)
    $repositoryExact = [IO.Path]::GetFullPath($repositoryRoot).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $repositoryPrefix = $repositoryExact + [IO.Path]::DirectorySeparatorChar
    $item = Get-Item -LiteralPath $resolvedFull -Force
    if ([String]::Equals($resolvedFull, $repositoryExact, [StringComparison]::OrdinalIgnoreCase) -or
        $resolvedFull.StartsWith($repositoryPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "DiagnosticEvidenceRoot must be a real directory outside the repository."
    }
    if ((Split-Path -Leaf $resolvedFull) -notmatch '(?i)diagnostic') {
        throw "DiagnosticEvidenceRoot leaf must identify a diagnostic evidence directory."
    }
    if (@(Get-ChildItem -LiteralPath $resolvedFull -Force).Count -ne 0) {
        throw "DiagnosticEvidenceRoot must be empty."
    }
    return $resolvedFull
}

function Invoke-CanonicalDiagnosticIdentity {
    param([Parameter(Mandatory)][string]$ExpectedSourceSha)
    $previousSourceSha = [Environment]::GetEnvironmentVariable("APP_RELEASE_SOURCE_SHA", [EnvironmentVariableTarget]::Process)
    try {
        [Environment]::SetEnvironmentVariable("APP_RELEASE_SOURCE_SHA", $ExpectedSourceSha, [EnvironmentVariableTarget]::Process)
        Push-Location -LiteralPath $backendDirectory
        try {
            $output = @(& $pythonExecutable -c $canonicalIdentityProbe 2>&1)
            if ($LASTEXITCODE -ne 0) {
                throw "Canonical release identity preflight failed: $(($output | Select-Object -Last 1) -join '')"
            }
        }
        finally { Pop-Location }
    }
    finally {
        [Environment]::SetEnvironmentVariable("APP_RELEASE_SOURCE_SHA", $previousSourceSha, [EnvironmentVariableTarget]::Process)
    }
    try { $identity = ($output -join "") | ConvertFrom-Json }
    catch { throw "Canonical release identity preflight returned invalid JSON." }
    foreach ($name in @("source_sha", "git_tree", "fixture_id", "runner_digest", "host_environment_digest")) {
        if ([string]::IsNullOrWhiteSpace([string]$identity.$name)) {
            throw "Canonical release identity is missing '$name'."
        }
    }
    if ([string]$identity.source_sha -cne $ExpectedSourceSha) {
        throw "Canonical release identity source SHA does not match the requested SourceSha."
    }
    if ([string]$identity.git_tree -notmatch '\A[0-9a-f]{40}\z') {
        throw "Canonical release identity tree is invalid."
    }
    foreach ($name in @("runner_digest", "host_environment_digest")) {
        if ([string]$identity.$name -notmatch '\A[0-9a-f]{64}\z') {
            throw "Canonical release identity '$name' is invalid."
        }
    }
    return $identity
}

function Write-DiagnosticJson {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][Collections.IDictionary]$Payload)
    [IO.File]::WriteAllText($Path, (($Payload | ConvertTo-Json -Depth 8) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
}

function Update-DiagnosticMigrationHead {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$MigrationHead)
    $payload = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json -AsHashtable
    $payload["database_migration_head"] = $MigrationHead
    $payload["database_migration_head_status"] = "verified_by_revision_check"
    Write-DiagnosticJson -Path $Path -Payload $payload
}

if ($diagnosticMode) {
    $expectedDiagnosticNode = if ($quickDiagnosticMode) {
        $quickDiagnosticNode
    } else {
        "tests/performance/test_project_optimization_baseline.py::test_heartbeat_candidate_baselines"
    }
    if ($DiagnosticNode -cne $expectedDiagnosticNode) {
        throw "DiagnosticNode is not an approved single baseline test node."
    }
    if ($PytestPaths.Count -ne 1 -or $PytestPaths[0] -cne "tests/performance/test_project_optimization_baseline.py") {
        throw "DiagnosticNode is not backed by the canonical project baseline suite."
    }
    $resolvedDiagnosticRoot = Resolve-DiagnosticEvidenceRoot -Value $DiagnosticEvidenceRoot
    $diagnosticIdentity = Invoke-CanonicalDiagnosticIdentity -ExpectedSourceSha $SourceSha
    $diagnosticTestTarget = $DiagnosticNode
    $executorHash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $diagnosticRunId = "stage0-$([guid]::NewGuid().ToString('N').Substring(0, 12))"
    $diagnosticRunDirectory = Join-Path $resolvedDiagnosticRoot $diagnosticRunId
    New-Item -ItemType Directory -Path $diagnosticRunDirectory -ErrorAction Stop | Out-Null
    Write-DiagnosticJson -Path (Join-Path $diagnosticRunDirectory "run-identity.json") -Payload ([ordered]@{
        run_id = $diagnosticRunId
        source_sha = $SourceSha
        status = "prepared"
    })
    $diagnosticMetadataPath = Join-Path $resolvedDiagnosticRoot "diagnostic-identity.json"
    $diagnosticModeName = if ($quickDiagnosticMode) { "diagnostic-quick" } else { "diagnostic" }
    $samplingProtocol = if ($quickDiagnosticMode) {
        [ordered]@{
            mode = "quick-heartbeat-long-task"
            independent_checks_per_version = 3
            heartbeat_seconds = 10
            stale_seconds = 30
            long_task_seconds = 35
            long_task_wait_seconds = 105
            p50_p95_distribution = $false
        }
    } else {
        [ordered]@{
            warmups_per_round = 3
            measured_samples_per_round = 20
            rounds = 3
            heartbeat_long_task_operations = 69
            heartbeat_long_task_wait_seconds = 2415
            heartbeat_long_task_minimum_minutes = 40.25
        }
    }
    Write-DiagnosticJson -Path $diagnosticMetadataPath -Payload ([ordered]@{
        schema_version = 1
        mode = $diagnosticModeName
        formal_evidence = $false
        finalize_run = $false
        executor_script_sha256 = $executorHash
        source_sha = [string]$diagnosticIdentity.source_sha
        git_tree = [string]$diagnosticIdentity.git_tree
        fixture_id = [string]$diagnosticIdentity.fixture_id
        runner_digest = [string]$diagnosticIdentity.runner_digest
        host_environment_digest = [string]$diagnosticIdentity.host_environment_digest
        selected_node = $DiagnosticNode
        expected_migration_head = $expectedSchemaRevision
        database_migration_head = $null
        database_migration_head_status = "not_recorded"
        sampling_protocol = $samplingProtocol
        run_directory = $diagnosticRunDirectory
    })
}

$dockerCommand = Get-Command -Name docker -ErrorAction SilentlyContinue
if ($null -eq $dockerCommand) {
    throw "Docker CLI was not found on PATH. Install Docker Desktop (or another Docker runtime) before running the MySQL matrix."
}
$dockerVersionOutput = @(& $dockerCommand.Source version --format "{{.Server.Version}}" 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "Docker CLI is installed, but the Docker daemon is unavailable. Start the container runtime and retry."
}

function ConvertTo-MySqlStringLiteral {
    param(
        [Parameter(Mandatory)]
        [string]$Value
    )

    return $Value.Replace("\", "\\").Replace("'", "''")
}

function ConvertTo-MySqlIdentifier {
    param(
        [Parameter(Mandatory)]
        [string]$Value
    )

    if ($Value -notmatch '\A[A-Za-z0-9_]+\z') {
        throw "Unsafe MySQL identifier was rejected."
    }
    return "{0}{1}{0}" -f [char]96, $Value
}

function New-DatabaseUrl {
    param(
        [Parameter(Mandatory)]
        [string]$User,

        [Parameter(Mandatory)]
        [string]$Password,

        [Parameter(Mandatory)]
        [int]$Port,

        [Parameter(Mandatory)]
        [string]$CaCertificatePath
    )

    $encodedUser = [Uri]::EscapeDataString($User)
    $encodedPassword = [Uri]::EscapeDataString($Password)
    $encodedCaCertificatePath = [Uri]::EscapeDataString($CaCertificatePath)
    return "mysql+pymysql://${encodedUser}:${encodedPassword}@127.0.0.1:${Port}/${testDatabaseName}?charset=utf8mb4&ssl_ca=${encodedCaCertificatePath}&ssl_check_hostname=false"
}

function Invoke-ContainerSql {
    param(
        [Parameter(Mandatory)]
        [string]$ContainerName,

        [Parameter(Mandatory)]
        [string]$Sql,

        [Parameter(Mandatory)]
        [string]$Operation
    )

    $sqlOutput = @(
        $Sql | & $dockerCommand.Source exec --interactive $ContainerName mysql --user=root --batch 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "MySQL failed while attempting to $Operation in the isolated matrix container. No credentials were written to the command line or log."
    }
}

function Set-Stage0PytestShard {
    param([Parameter(Mandatory)][string]$Shard)
    if ([string]::IsNullOrWhiteSpace(
            $env:APP_STAGE0_PYTEST_OUTCOME_DIRECTORY
        )) {
        return
    }
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

function Write-MatrixTiming {
    param(
        [Parameter(Mandatory)][string]$Version,
        [Parameter(Mandatory)][string]$Phase,
        [Parameter(Mandatory)][string]$Status,
        [AllowNull()][double]$ElapsedSeconds = $null
    )
    $elapsed = if ($null -eq $ElapsedSeconds) { "unavailable" } else {
        $ElapsedSeconds.ToString("F3", [Globalization.CultureInfo]::InvariantCulture)
    }
    Write-Host (
        "TIMING mysql_version={0} phase={1} status={2} elapsed_seconds={3}" -f
        $Version, $Phase, $Status, $elapsed
    )
}

$managedEnvironmentVariables = @(
    "APP_DATABASE_URL",
    "APP_MIGRATION_DATABASE_URL",
    "APP_TEST_DATABASE_URL",
    "APP_TEST_RUNTIME_DATABASE_URL",
    "APP_TEST_BACKUP_DATABASE_URL",
    "APP_TEST_SCHEMA_UNREADABLE_DATABASE_URL",
    "APP_TEST_RUN_ID",
    "APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT",
    "APP_PROJECT_OPTIMIZATION_RUN_DIR",
    "APP_RELEASE_SOURCE_SHA",
    "APP_BASELINE_MYSQL_VERSION",
    "APP_PROJECT_OPTIMIZATION_QUICK_CHECK",
    "APP_STAGE0_PYTEST_OUTCOME_SHARD",
    "APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST"
)
$previousEnvironment = @{}
foreach ($name in $managedEnvironmentVariables) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable(
        $name,
        [EnvironmentVariableTarget]::Process
    )
}
if ($diagnosticMode) {
    [Environment]::SetEnvironmentVariable(
        "APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT",
        (Split-Path -Parent $diagnosticRunDirectory),
        [EnvironmentVariableTarget]::Process
    )
    [Environment]::SetEnvironmentVariable(
        "APP_PROJECT_OPTIMIZATION_RUN_DIR",
        $diagnosticRunDirectory,
        [EnvironmentVariableTarget]::Process
    )
    [Environment]::SetEnvironmentVariable(
        "APP_RELEASE_SOURCE_SHA",
        $SourceSha,
        [EnvironmentVariableTarget]::Process
    )
    [Environment]::SetEnvironmentVariable(
        "APP_PROJECT_OPTIMIZATION_QUICK_CHECK",
        $(if ($quickDiagnosticMode) { "1" } else { $null }),
        [EnvironmentVariableTarget]::Process
    )
}

$databaseIdentifier = ConvertTo-MySqlIdentifier -Value $testDatabaseName
$migrationAccount = "'$migrationUser'@'$accountHost'"
$runtimeAccount = "'$runtimeUser'@'$accountHost'"
$backupAccount = "'$backupUser'@'$accountHost'"
$temporaryRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$temporaryDirectory = [System.IO.Path]::GetFullPath(
    (Join-Path $temporaryRoot "clsen-mysql-matrix-$runIdentifier")
)
$temporaryDirectoryCreated = $false
if (
    -not $temporaryDirectory.StartsWith(
        $temporaryRoot,
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    (Split-Path -Leaf $temporaryDirectory) -cne "clsen-mysql-matrix-$runIdentifier"
) {
    throw "Temporary CA directory resolved outside the operating-system temporary root."
}
$tlsCheckSource = @'
import os

from sqlalchemy import create_engine, make_url

for variable_name in (
    "APP_TEST_DATABASE_URL",
    "APP_TEST_RUNTIME_DATABASE_URL",
    "APP_TEST_BACKUP_DATABASE_URL",
    "APP_TEST_SCHEMA_UNREADABLE_DATABASE_URL",
):
    value = os.environ[variable_name]
    url = make_url(value)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        _, connect_options = engine.dialect.create_connect_args(url)
        ssl_options = connect_options.get("ssl")
        if (
            not isinstance(ssl_options, dict)
            or ssl_options.get("ca") != url.query.get("ssl_ca")
            or ssl_options.get("check_hostname") is not False
        ):
            raise RuntimeError(
                f"{variable_name} does not preserve CA verification options"
            )
        with engine.connect() as connection:
            status = connection.exec_driver_sql(
                "SHOW SESSION STATUS LIKE 'Ssl_cipher'"
            ).one()
            if not str(status[1]).strip():
                raise RuntimeError(f"{variable_name} did not negotiate TLS")
    finally:
        engine.dispose()
'@
$schemaRevisionCheckSource = @'
import os

from sqlalchemy import create_engine

from app.maintenance.schema_revision import CURRENT_SCHEMA_REVISION

engine = create_engine(os.environ["APP_TEST_DATABASE_URL"], pool_pre_ping=True)
try:
    with engine.connect() as connection:
        actual = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
finally:
    engine.dispose()
if actual != CURRENT_SCHEMA_REVISION:
    raise RuntimeError(
        f"database revision {actual!r} does not match "
        f"{CURRENT_SCHEMA_REVISION!r}"
    )
'@

try {
    New-Item -ItemType Directory -Path $temporaryDirectory -ErrorAction Stop |
        Out-Null
    $temporaryDirectoryCreated = $true

    foreach ($version in $Versions) {
        if ($diagnosticMode) {
            [Environment]::SetEnvironmentVariable(
                "APP_BASELINE_MYSQL_VERSION",
                $version,
                [EnvironmentVariableTarget]::Process
            )
        }
        $containerName = "clsen-mysql-matrix-$PID-$($runIdentifier.Substring(0, 12))-$($version.Replace('.', '-'))"
        if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_OUTPUT)) {
            "mysql_container=$containerName" | Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
            "mysql_run_id=$runIdentifier" | Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
        }
        $containerStarted = $false
        $migrationPassword = [guid]::NewGuid().ToString("N")
        $runtimePassword = [guid]::NewGuid().ToString("N")
        $backupPassword = [guid]::NewGuid().ToString("N")
        $schemaUnreadablePassword = [guid]::NewGuid().ToString("N")
        $startupClock = [Diagnostics.Stopwatch]::StartNew()
        $startupStatus = "failed"
        $migrationClock = $null
        $migrationStatus = "not_started"
        $testClock = $null
        $testStatus = "not_started"

        try {
            if (-not $PSCmdlet.ShouldProcess(
                    "isolated container $containerName",
                    "run MySQL $version compatibility tests and remove the container"
                )) {
                continue
            }

            $imageName = "mysql:$version"
            $resourceArguments = if ($PerformanceProfile) {
                @("--cpus", "4", "--memory", "8g")
            }
            else {
                @()
            }
            $serverArguments = @(
                "--character-set-server=utf8mb4",
                "--collation-server=utf8mb4_0900_ai_ci",
                "--default-time-zone=+00:00"
            )
            if ($PerformanceProfile) {
                $serverArguments += @(
                    "--innodb-buffer-pool-size=2147483648",
                    "--innodb-redo-log-capacity=2147483648",
                    "--innodb-flush-log-at-trx-commit=2",
                    "--sync-binlog=0"
                )
            }
            $dockerRunOutput = @(
                & $dockerCommand.Source run --detach --rm `
                    --name $containerName `
                    --label "clsen.mysql-matrix.run=$runIdentifier" `
                    --publish "127.0.0.1::3306" `
                    --env "MYSQL_ALLOW_EMPTY_PASSWORD=yes" `
                    @resourceArguments `
                    $imageName `
                    @serverArguments 2>&1
            )
            if ($LASTEXITCODE -ne 0) {
                throw "Docker could not start the isolated $imageName container. Verify that the image can be pulled and the Docker daemon has sufficient resources."
            }
            $containerStarted = $true

            $mysqlReady = $false
            for ($attempt = 1; $attempt -le 30; $attempt++) {
                $healthOutput = @(
                    & $dockerCommand.Source exec $containerName `
                        mysqladmin ping `
                        --protocol=TCP `
                        --host=127.0.0.1 `
                        --port=3306 `
                        --user=root `
                        --silent 2>&1
                )
                if ($LASTEXITCODE -eq 0) {
                    $mysqlReady = $true
                    break
                }
                Start-Sleep -Seconds 2
            }
            if (-not $mysqlReady) {
                throw "MySQL $version did not become ready within 60 seconds in the isolated container."
            }

            $caCertificatePath = Join-Path `
                $temporaryDirectory `
                "mysql-$($version.Replace('.', '-'))-ca.pem"
            $copyOutput = @(
                & $dockerCommand.Source cp `
                    "${containerName}:/var/lib/mysql/ca.pem" `
                    $caCertificatePath 2>&1
            )
            if (
                $LASTEXITCODE -ne 0 -or
                -not (Test-Path -LiteralPath $caCertificatePath -PathType Leaf) -or
                (Get-Item -LiteralPath $caCertificatePath).Length -lt 1
            ) {
                throw "MySQL $version did not provide the CA certificate required for verified TLS connections."
            }

            $portOutput = @(
                & $dockerCommand.Source port $containerName "3306/tcp" 2>&1
            )
            if ($LASTEXITCODE -ne 0) {
                throw "Docker did not report the host port for the isolated MySQL $version container."
            }
            $portMatch = [regex]::Match(
                ($portOutput -join "`n"),
                '(?m):(?<port>[0-9]{1,5})\s*$'
            )
            $hostPort = 0
            if (
                -not $portMatch.Success -or
                -not [int]::TryParse($portMatch.Groups["port"].Value, [ref]$hostPort) -or
                $hostPort -lt 1 -or
                $hostPort -gt 65535
            ) {
                throw "Docker returned an invalid host port for the isolated MySQL $version container."
            }
            $startupStatus = "passed"
            $startupClock.Stop()
            Write-MatrixTiming -Version $version -Phase "database-startup" -Status $startupStatus -ElapsedSeconds $startupClock.Elapsed.TotalSeconds

            $migrationPasswordSql = ConvertTo-MySqlStringLiteral -Value $migrationPassword
            $runtimePasswordSql = ConvertTo-MySqlStringLiteral -Value $runtimePassword
            $backupPasswordSql = ConvertTo-MySqlStringLiteral -Value $backupPassword
            $schemaUnreadablePasswordSql = ConvertTo-MySqlStringLiteral -Value $schemaUnreadablePassword
            $backupSchemaPrivilegeList = (
                [string[]]$databasePrivileges["backup"]["schema"]
            ) -join ", "
            $bootstrapSql = @"
SET GLOBAL log_bin_trust_function_creators = ON;
CREATE DATABASE IF NOT EXISTS $databaseIdentifier CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS $migrationAccount IDENTIFIED WITH caching_sha2_password BY '$migrationPasswordSql' REQUIRE SSL;
CREATE USER IF NOT EXISTS $runtimeAccount IDENTIFIED WITH caching_sha2_password BY '$runtimePasswordSql' REQUIRE SSL;
CREATE USER IF NOT EXISTS $backupAccount IDENTIFIED WITH caching_sha2_password BY '$backupPasswordSql' REQUIRE SSL;
CREATE USER IF NOT EXISTS '$schemaUnreadableUser'@'$accountHost' IDENTIFIED WITH caching_sha2_password BY '$schemaUnreadablePasswordSql' REQUIRE SSL;
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES, TRIGGER, LOCK TABLES
    ON $databaseIdentifier.* TO $migrationAccount;
GRANT SELECT ON $databaseIdentifier.* TO $runtimeAccount;
GRANT $backupSchemaPrivilegeList ON $databaseIdentifier.* TO $backupAccount;
GRANT SELECT ON $databaseIdentifier.* TO '$schemaUnreadableUser'@'$accountHost';
"@
            Invoke-ContainerSql `
                -ContainerName $containerName `
                -Sql $bootstrapSql `
                -Operation "create the disposable database and isolated accounts"

            $migrationUrl = New-DatabaseUrl `
                -User $migrationUser `
                -Password $migrationPassword `
                -Port $hostPort `
                -CaCertificatePath $caCertificatePath
            $runtimeUrl = New-DatabaseUrl `
                -User $runtimeUser `
                -Password $runtimePassword `
                -Port $hostPort `
                -CaCertificatePath $caCertificatePath
            $backupUrl = New-DatabaseUrl `
                -User $backupUser `
                -Password $backupPassword `
                -Port $hostPort `
                -CaCertificatePath $caCertificatePath
            $schemaUnreadableUrl = New-DatabaseUrl `
                -User $schemaUnreadableUser `
                -Password $schemaUnreadablePassword `
                -Port $hostPort `
                -CaCertificatePath $caCertificatePath
            [Environment]::SetEnvironmentVariable("APP_DATABASE_URL", $runtimeUrl)
            [Environment]::SetEnvironmentVariable(
                "APP_MIGRATION_DATABASE_URL",
                $migrationUrl
            )
            [Environment]::SetEnvironmentVariable("APP_TEST_DATABASE_URL", $migrationUrl)
            [Environment]::SetEnvironmentVariable(
                "APP_TEST_RUNTIME_DATABASE_URL",
                $runtimeUrl
            )
            [Environment]::SetEnvironmentVariable(
                "APP_TEST_BACKUP_DATABASE_URL",
                $backupUrl
            )
            [Environment]::SetEnvironmentVariable(
                "APP_TEST_SCHEMA_UNREADABLE_DATABASE_URL",
                $schemaUnreadableUrl
            )
            [Environment]::SetEnvironmentVariable("APP_TEST_RUN_ID", $runIdentifier)

            $tlsReady = $false
            for ($tlsAttempt = 1; $tlsAttempt -le 15; $tlsAttempt++) {
                $tlsCheckOutput = @(& $pythonExecutable -c $tlsCheckSource 2>&1)
                if ($LASTEXITCODE -eq 0) {
                    $tlsReady = $true
                    break
                }
                Start-Sleep -Seconds 2
            }
            if (-not $tlsReady) {
                throw "Verified TLS checks failed for one or more MySQL $version matrix accounts."
            }
            Invoke-ContainerSql `
                -ContainerName $containerName `
                -Sql "SET GLOBAL log_bin_trust_function_creators = ON;" `
                -Operation "configure trigger creation on the final MySQL server"

            Push-Location -LiteralPath $backendDirectory
            $migrationClock = [Diagnostics.Stopwatch]::StartNew()
            $migrationStatus = "failed"
            try {
                $selectedHistoricalNodes = @(
                    $historicalNodes | Where-Object {
                        $PytestPaths -ccontains ($_ -split "::", 2)[0]
                    }
                )
                if ($selectedHistoricalNodes.Count -gt 0) {
                    Set-Stage0PytestShard -Shard "migration"
                    & $pythonExecutable -u -m pytest `
                        @selectedHistoricalNodes --require-mysql -x -vv --durations=20
                    if ($LASTEXITCODE -ne 0) {
                        throw "MySQL $version migration tests failed with exit code $LASTEXITCODE."
                    }
                }
                & $pythonExecutable -m alembic -c alembic.ini upgrade head
                if ($LASTEXITCODE -ne 0) {
                    throw "MySQL $version scoped schema upgrade failed with exit code $LASTEXITCODE."
                }
                $migrationStatus = "passed"
            }
            finally {
                Pop-Location
                $migrationClock.Stop()
                Write-MatrixTiming -Version $version -Phase "migration" -Status $migrationStatus -ElapsedSeconds $migrationClock.Elapsed.TotalSeconds
            }

            Push-Location -LiteralPath $backendDirectory
            try {
                $revisionCheckOutput = @(
                    & $pythonExecutable -c $schemaRevisionCheckSource 2>&1
                )
                if ($LASTEXITCODE -ne 0) {
                    throw (
                        "MySQL $version did not converge to shared schema " +
                        "revision '$expectedSchemaRevision'."
                    )
                }
            }
            finally {
                Pop-Location
            }
            if ($diagnosticMode) {
                Update-DiagnosticMigrationHead -Path $diagnosticMetadataPath -MigrationHead $expectedSchemaRevision
                Write-Host ("DIAGNOSTIC migration verified: expected_head={0}; database_migration_head={0}" -f $expectedSchemaRevision)
            }

            $runtimePrivileges = $databasePrivileges["runtime"]
            $insertTables = [string[]](
                $runtimePrivileges["insert_only"] +
                $runtimePrivileges["mutable_insert"]
            )
            $updateTables = [string[]]$runtimePrivileges["update"]
            $columnUpdates = $runtimePrivileges["update_columns"]
            $deleteTables = [string[]]$runtimePrivileges["delete"]
            $runtimeGrantStatements = [Collections.Generic.List[string]]::new()
            foreach ($table in $insertTables) {
                $tableIdentifier = ConvertTo-MySqlIdentifier -Value $table
                $runtimeGrantStatements.Add(
                    "GRANT INSERT ON $databaseIdentifier.$tableIdentifier TO $runtimeAccount;"
                )
            }
            foreach ($table in $updateTables) {
                $tableIdentifier = ConvertTo-MySqlIdentifier -Value $table
                $runtimeGrantStatements.Add(
                    "GRANT UPDATE ON $databaseIdentifier.$tableIdentifier TO $runtimeAccount;"
                )
            }
            foreach ($table in $columnUpdates.Keys) {
                $tableIdentifier = ConvertTo-MySqlIdentifier -Value $table
                $columnIdentifiers = @(
                    foreach ($column in [string[]]$columnUpdates[$table]) {
                        ConvertTo-MySqlIdentifier -Value $column
                    }
                )
                $runtimeGrantStatements.Add(
                    "GRANT UPDATE ($($columnIdentifiers -join ', ')) ON $databaseIdentifier.$tableIdentifier TO $runtimeAccount;"
                )
            }
            foreach ($table in $deleteTables) {
                $tableIdentifier = ConvertTo-MySqlIdentifier -Value $table
                $runtimeGrantStatements.Add(
                    "GRANT DELETE ON $databaseIdentifier.$tableIdentifier TO $runtimeAccount;"
                )
            }
            Invoke-ContainerSql `
                -ContainerName $containerName `
                -Sql ($runtimeGrantStatements -join "`n") `
                -Operation "apply least-privilege runtime grants"

            $backupPrivileges = $databasePrivileges["backup"]
            $backupGrantStatements = [Collections.Generic.List[string]]::new()
            foreach ($table in [string[]]$backupPrivileges["insert"]) {
                $tableIdentifier = ConvertTo-MySqlIdentifier -Value $table
                $backupGrantStatements.Add(
                    "GRANT INSERT ON $databaseIdentifier.$tableIdentifier TO $backupAccount;"
                )
            }
            foreach ($table in [string[]]$backupPrivileges["update"]) {
                $tableIdentifier = ConvertTo-MySqlIdentifier -Value $table
                $backupGrantStatements.Add(
                    "GRANT UPDATE ON $databaseIdentifier.$tableIdentifier TO $backupAccount;"
                )
            }
            Invoke-ContainerSql `
                -ContainerName $containerName `
                -Sql ($backupGrantStatements -join "`n") `
                -Operation "apply least-privilege backup audit grants"
            Invoke-ContainerSql `
                -ContainerName $containerName `
                -Sql "REVOKE SELECT ON $databaseIdentifier.* FROM '$schemaUnreadableUser'@'$accountHost'; GRANT SELECT ON $databaseIdentifier.sites TO '$schemaUnreadableUser'@'$accountHost';" `
                -Operation "restrict the schema-unreadable probe account"

            $remainingPaths = @(
                $PytestPaths | Where-Object {
                    ($_ -split "::", 2)[0] -cne "tests/integration/test_migrations.py"
                }
            )
            if ($remainingPaths.Count -gt 0) {
                $testClock = [Diagnostics.Stopwatch]::StartNew()
                $testStatus = "failed"
                Push-Location -LiteralPath $backendDirectory
                try {
                    Set-Stage0PytestShard -Shard "scoped"
                    [string[]]$testTargets = if ($diagnosticMode) { @($diagnosticTestTarget) } else { @($remainingPaths) }
                    [string[]]$formalSelectionArguments = @(
                        $selectedHistoricalNodes |
                            Where-Object { ($_ -split "::", 2)[0] -cne "tests/integration/test_migrations.py" } |
                            ForEach-Object { "--deselect=$_" }
                    )
                    if (-not $diagnosticMode -and $remainingPaths -ccontains "tests/performance/test_project_optimization_baseline.py") {
                        $formalSelectionArguments += @("--deselect", $quickDiagnosticNode)
                    }
                    & $pythonExecutable -u -m pytest @testTargets --require-mysql -x -vv --durations=20 @formalSelectionArguments
                    if ($LASTEXITCODE -ne 0) {
                        throw "MySQL $version scoped tests failed with exit code $LASTEXITCODE."
                    }
                    $testStatus = "passed"
                }
                finally {
                    Pop-Location
                    $testClock.Stop()
                    Write-MatrixTiming -Version $version -Phase "tests" -Status $testStatus -ElapsedSeconds $testClock.Elapsed.TotalSeconds
                }
            }
            else {
                $testStatus = "not_applicable"
                Write-MatrixTiming -Version $version -Phase "tests" -Status $testStatus
            }

            if ($diagnosticMode) {
                Write-Host "Diagnostic timing completed; no formal release evidence was finalized."
            }
            else {
                Write-Host "MySQL $version compatibility tests passed."
            }
        }
        finally {
            if ($startupClock.IsRunning) {
                $startupClock.Stop()
                Write-MatrixTiming -Version $version -Phase "database-startup" -Status $startupStatus -ElapsedSeconds $startupClock.Elapsed.TotalSeconds
            }
            if ($null -eq $migrationClock) {
                Write-MatrixTiming -Version $version -Phase "migration" -Status "not_started"
            }
            if ($null -eq $testClock -and $testStatus -eq "not_started") {
                Write-MatrixTiming -Version $version -Phase "tests" -Status "not_started"
            }
            $cleanupClock = [Diagnostics.Stopwatch]::StartNew()
            $cleanupStatus = "failed"
            $migrationPassword = $null
            $runtimePassword = $null
            $backupPassword = $null
            $schemaUnreadablePassword = $null

            if ($containerStarted) {
                $labelOutput = @(
                    & $dockerCommand.Source inspect `
                        --format '{{ index .Config.Labels "clsen.mysql-matrix.run" }}' `
                        $containerName 2>&1
                )
                $labelExitCode = $LASTEXITCODE
                $containerLabel = ($labelOutput -join "").Trim()
                if ($labelExitCode -eq 0 -and $containerLabel -ceq $runIdentifier) {
                    $removeOutput = @(
                        & $dockerCommand.Source rm --force $containerName 2>&1
                    )
                    if ($LASTEXITCODE -ne 0) {
                        Write-Warning "Could not remove isolated matrix container '$containerName'; remove it manually after verifying its label."
                    }
                }
                else {
                    Write-Warning "Refused to remove container '$containerName' because its ownership label did not match this matrix run."
                }
            }
            $cleanupStatus = "passed"
            $cleanupClock.Stop()
            Write-MatrixTiming -Version $version -Phase "cleanup" -Status $cleanupStatus -ElapsedSeconds $cleanupClock.Elapsed.TotalSeconds
        }
    }
}
finally {
    foreach ($name in $managedEnvironmentVariables) {
        [Environment]::SetEnvironmentVariable(
            $name,
            $previousEnvironment[$name],
            [EnvironmentVariableTarget]::Process
        )
    }

    if ($temporaryDirectoryCreated -and (Test-Path -LiteralPath $temporaryDirectory)) {
        $resolvedTemporaryDirectory = [System.IO.Path]::GetFullPath(
            $temporaryDirectory
        )
        if (
            $resolvedTemporaryDirectory.StartsWith(
                $temporaryRoot,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            (Split-Path -Leaf $resolvedTemporaryDirectory) -ceq
                "clsen-mysql-matrix-$runIdentifier"
        ) {
            Remove-Item `
                -LiteralPath $resolvedTemporaryDirectory `
                -Recurse `
                -Force
        }
        else {
            Write-Warning "Refused to remove unexpected temporary CA path '$resolvedTemporaryDirectory'."
        }
    }
}
