import json
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKUP_SCRIPT = REPOSITORY_ROOT / "scripts" / "backup.ps1"
RESTORE_SCRIPT = REPOSITORY_ROOT / "scripts" / "restore-verify.ps1"
WORKER_SCRIPT = REPOSITORY_ROOT / "scripts" / "run-worker.ps1"
DEV_BACKEND_SCRIPT = REPOSITORY_ROOT / "scripts" / "dev-backend.ps1"
STAGE9_DEMO_SCRIPT = REPOSITORY_ROOT / "scripts" / "start-stage9-demo.ps1"
CATALOG_LIVE_SCRIPT = REPOSITORY_ROOT / "scripts" / "run-product-catalog-live-e2e.ps1"
CATALOG_EXPERIENCE_STOP_SCRIPT = (
    REPOSITORY_ROOT / "scripts" / "stop-product-catalog-experience.ps1"
)
BACKUP_MODULE = REPOSITORY_ROOT / "backend" / "app" / "maintenance" / "backup.py"
RESTORE_MODULE = REPOSITORY_ROOT / "backend" / "app" / "maintenance" / "restore.py"
PERFORMANCE_RUNNER = REPOSITORY_ROOT / "scripts" / "run-product-catalog-performance.ps1"
CANARY_RUNNER = REPOSITORY_ROOT / "scripts" / "run-product-catalog-canary.ps1"
CATALOG_RESTORE_RUNNER = (
    REPOSITORY_ROOT / "scripts" / "run-product-catalog-backup-restore.ps1"
)
CI_SUITE_MANIFEST = REPOSITORY_ROOT / "scripts" / "ci-suite-manifest.json"


@pytest.mark.parametrize(
    ("scenario", "closed", "records", "job_created"),
    [
        ("phase-rollover", 2, 0, False),
        ("start-changed", 0, 1, True),
        ("command-changed", 0, 1, True),
        ("close-failed", 0, 1, True),
        ("idle", 0, 1, False),
    ],
)
def test_catalog_live_job_cleanup_keeps_only_active_phase_identities(
    tmp_path: Path,
    scenario: str,
    closed: int,
    records: int,
    job_created: bool,
) -> None:
    probe = tmp_path / "probe-live-cleanup.ps1"
    probe.write_text(
        r"""
param([string]$LiveScriptPath, [string]$Scenario)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $LiveScriptPath, [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count) { throw 'Live script parsing failed' }
foreach ($name in @('Get-TextSha256', 'Register-ProcessIdentity',
                    'Assert-OwnedProcessIdentity', 'Stop-LiveJob')) {
    $definitions = @($ast.FindAll({ param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq $name
    }, $true))
    if ($definitions.Count -ne 1) { throw "Missing function $name" }
    . ([scriptblock]::Create($definitions[0].Extent.Text))
}
# All OS process lookups and Job closure are fakes: never inspect or kill a host PID.
class CatalogLiveJob {
    static [int]$Closed = 0
    static [bool]$FailClose = $false
    static [void] Close() {
        if ([CatalogLiveJob]::FailClose) { throw 'simulated close failure' }
        [CatalogLiveJob]::Closed++
    }
}
$processRecords = [Collections.Generic.List[object]]::new()
$script:jobCreated = $true
$script:started = [DateTime]::Parse('2026-10-22T00:00:00Z').ToUniversalTime()
$script:command = 'legacy-before-fixture'
function Get-Process {
    param([int]$Id, [string]$ErrorAction)
    return [pscustomobject]@{ StartTime = $script:started }
}
function Get-ProcessCommandLine {
    param([int]$ProcessId)
    return $script:command
}
Register-ProcessIdentity -ProcessId 101 -Role 'legacy-before' `
    -RequiredCommandFragment 'fixture'
if ($Scenario -eq 'phase-rollover') {
    Stop-LiveJob
    # The OS may reuse a closed phase's PID for the next phase or an unrelated process.
    $script:started = $script:started.AddSeconds(10)
    $script:command = 'p0-fixture'
    $script:jobCreated = $true
    Register-ProcessIdentity -ProcessId 101 -Role 'p0' `
        -RequiredCommandFragment 'fixture'
    if ($processRecords.Count -ne 1 -or $processRecords[0].role -cne 'p0') {
        throw 'Closed phase process identity leaked into the next phase'
    }
    Stop-LiveJob
} elseif ($Scenario -eq 'idle') {
    $script:jobCreated = $false
    Stop-LiveJob
} else {
    if ($Scenario -eq 'start-changed') {
        $script:started = $script:started.AddSeconds(1)
    }
    if ($Scenario -eq 'command-changed') { $script:command = 'different-fixture' }
    if ($Scenario -eq 'close-failed') { [CatalogLiveJob]::FailClose = $true }
    $rejected = $false
    try { Stop-LiveJob } catch {
        $expected = if ($Scenario -eq 'close-failed') { 'simulated close failure' }
                    else { 'Refusing ambiguous cleanup' }
        if (-not $_.ToString().Contains($expected)) { throw }
        $rejected = $true
    }
    if (-not $rejected) { throw 'Unsafe or unsuccessful closure was accepted' }
}
@{ closed = [CatalogLiveJob]::Closed; records = $processRecords.Count
   job_created = $script:jobCreated } | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(probe),
            "-LiveScriptPath",
            str(CATALOG_LIVE_SCRIPT),
            "-Scenario",
            scenario,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "closed": closed,
        "records": records,
        "job_created": job_created,
    }


@pytest.fixture
def performance_runner(tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    source = PERFORMANCE_RUNNER.read_text(encoding="utf-8")
    # Stub only source identity, retaining evidence checks and version selection.
    marker = "$derivedIdentity = Get-DerivedReleaseIdentity"
    assert source.count(marker) == 1
    source = source.replace(
        marker,
        "$derivedIdentity = @{ source_sha = ('a' * 40); git_tree = ('b' * 40); "
        "artifact_digest = ('c' * 64); runner_digest = ('d' * 64) }",
    )
    runner = scripts / PERFORMANCE_RUNNER.name
    runner.write_text(source, encoding="utf-8")
    (scripts / "test-mysql-matrix.ps1").write_text(
        "param($Versions, [switch]$PerformanceProfile, $Suites, $PythonExecutable)\n"
        "$payload = @{fixture='analytics_scale_v1'; mysql_version=$Versions[0]; "
        "warmup_samples=3; measured_samples=20; "
        "source_sha=('a'*40); git_tree=('b'*40); "
        "artifact_digest=('c'*64); runner_digest=('d'*64)}\n"
        "$payload | ConvertTo-Json | Set-Content -LiteralPath "
        "$env:APP_PRODUCT_CATALOG_SCALE_EVIDENCE_PATH\n"
        "$global:LASTEXITCODE = 0\n",
        encoding="utf-8",
    )
    return runner


def test_performance_generates_and_validates_only_mysql84_by_default(
    performance_runner: Path,
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    command = [
        "pwsh",
        "-NoProfile",
        "-File",
        str(performance_runner),
        "-SourceSha",
        "a" * 40,
        "-PythonExecutable",
        sys.executable,
    ]
    generated = subprocess.run(
        [*command, "-GenerateEvidence", "-EvidenceDirectory", str(evidence)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert generated.returncode == 0, generated.stderr
    assert {path.name for path in evidence.iterdir()} == {
        "analytics-scale-v1-mysql84.json"
    }
    validated = subprocess.run(
        [
            *command,
            "-MySql84EvidencePath",
            str(evidence / "analytics-scale-v1-mysql84.json"),
            "-ValidateOnly",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert validated.returncode == 0, validated.stderr
    assert "PASS for Oracle MySQL 8.4." in generated.stdout
    assert "MySQL 8.0 evidence:" not in generated.stdout


@pytest.mark.parametrize(
    "field,value",
    [
        ("mysql_version", "8.0"),
        ("source_sha", "e" * 40),
        ("git_tree", "e" * 40),
        ("fixture", "wrong_fixture"),
        ("missing_file", ""),
        ("artifact_digest", "e" * 64),
        ("runner_digest", "e" * 64),
        ("measured_samples", 1),
        ("warmup_samples", 0),
    ],
)
def test_mysql84_performance_still_rejects_invalid_evidence(
    performance_runner: Path,
    tmp_path: Path,
    field: str,
    value: str | int,
) -> None:
    payload = {
        "fixture": "analytics_scale_v1",
        "mysql_version": "8.4",
        "warmup_samples": 3,
        "measured_samples": 20,
        "source_sha": "a" * 40,
        "git_tree": "b" * 40,
        "artifact_digest": "c" * 64,
        "runner_digest": "d" * 64,
    }
    payload[field] = value
    evidence = tmp_path / "invalid-evidence.json"
    if field != "missing_file":
        evidence.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(performance_runner),
            "-SourceSha",
            "a" * 40,
            "-PythonExecutable",
            sys.executable,
            "-MySql84EvidencePath",
            str(evidence),
            "-ValidateOnly",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert "evidence" in result.stderr
    assert ("unavailable" if field == "missing_file" else "invalid") in result.stderr


def test_restore_passes_only_mysql84_to_the_matrix_by_default(tmp_path: Path) -> None:
    runner = tmp_path / CATALOG_RESTORE_RUNNER.name
    runner.write_text(
        CATALOG_RESTORE_RUNNER.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "test-mysql-matrix.ps1").write_text(
        "param($Versions, $Suites, $PythonExecutable)\n"
        "if (($Versions -join ',') -cne '8.4' -or "
        "($Suites -join ',') -cne 'restore') "
        "{ throw 'Unexpected matrix invocation' }\n"
        "Write-Host 'MOCK_MATRIX_84_ONLY'\n$global:LASTEXITCODE = 0\n",
        encoding="utf-8",
    )
    script = (
        "function mysql {}; function mysqldump {}; function docker {}; "
        f"& '{runner}' -PythonExecutable '{sys.executable}'"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "MOCK_MATRIX_84_ONLY" in result.stdout
    assert "PASS on MySQL 8.4." in result.stdout


def test_backup_script_keeps_keyring_outside_repository_and_protects_acl() -> None:
    source = BACKUP_SCRIPT.read_text(encoding="utf-8")

    assert "#Requires -Version 7.0" in source
    assert "LOCALAPPDATA" in source
    assert "backup-keyring.json" in source
    assert "must remain outside the repository" in source
    assert "Set-PrivatePathAcl" in source
    assert "FileSystemAclExtensions]::SetAccessControl" in source
    assert "Set-Acl" not in source
    assert "APP_TEST_BACKUP_DATABASE_URL" in source
    assert "[string]$StorageRoot" in source
    assert 'SetEnvironmentVariable(\n                "APP_STORAGE_ROOT"' in source
    assert "app.maintenance.cli" in source
    assert "--password" not in source


def test_backup_module_uses_required_consistent_dump_and_chunked_aes_gcm() -> None:
    source = BACKUP_MODULE.read_text(encoding="utf-8")

    for option in (
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
        "--events",
        "--hex-blob",
        "--default-character-set=utf8mb4",
        "--no-tablespaces",
    ):
        assert option in source
    assert "AESGCM" in source
    assert "secrets.token_bytes(8)" in source
    assert "--defaults-extra-file" in source
    assert "APP_MIGRATION_DATABASE_URL" not in source
    assert "status = 'sealed'" in source
    assert "status = 'succeeded'" in source


def test_restore_script_uses_temporary_option_file_and_default_retention() -> None:
    source = RESTORE_SCRIPT.read_text(encoding="utf-8")

    assert "#Requires -Version 7.0" in source
    assert "Get-Credential" in source
    assert "--administrator-option-file" in source
    assert "Set-PrivatePathAcl" in source
    assert "FileSystemAclExtensions]::SetAccessControl" in source
    assert "Set-Acl" not in source
    assert "clsen-restore-credential-" in source
    assert "Remove-Item" in source
    assert "[switch]$Cleanup" in source
    assert "DROP DATABASE" not in source.upper()


def test_restore_module_generates_and_rechecks_random_isolated_targets() -> None:
    source = RESTORE_MODULE.read_text(encoding="utf-8")

    assert 'database_name = f"clsen_restore_{verification_uuid.hex}"' in source
    assert "_RESTORE_DATABASE_PATTERN.fullmatch" in source
    assert "resolved_target.parent != resolved_root" in source
    assert "DROP DATABASE" in source
    assert "clsen_data`" not in source
    assert "verify_encrypted_file" in source
    assert "restore_verified_at = UTC_TIMESTAMP(6)" in source


def test_worker_script_has_explicit_test_database_and_drain_modes() -> None:
    source = WORKER_SCRIPT.read_text(encoding="utf-8")

    assert "#Requires -Version 7.0" in source
    assert "APP_TEST_RUNTIME_DATABASE_URL" in source
    assert "APP_DATABASE_URL" in source
    assert "--drain" in source
    assert "app.worker.cli" in source


def test_supported_local_launchers_preflight_before_ready_or_uvicorn() -> None:
    worker = WORKER_SCRIPT.read_text(encoding="utf-8")
    backend = DEV_BACKEND_SCRIPT.read_text(encoding="utf-8")
    demo = STAGE9_DEMO_SCRIPT.read_text(encoding="utf-8")

    assert "app.schema_preflight" in worker
    assert worker.index("& $pythonExecutable @preflightArguments") < worker.index(
        'Write-Host "CLSEN worker ready."'
    )
    assert worker.index('Write-Host "CLSEN worker ready."') < worker.index(
        "& $pythonExecutable @arguments"
    )
    assert backend.index("app.schema_preflight") < backend.index(
        "& $pythonExecutable @uvicornArguments"
    )
    assert demo.index("app.schema_preflight") < demo.index("-m uvicorn")


def test_live_runner_preflights_each_api_and_worker_process_launch(
    tmp_path: Path,
) -> None:
    source = CATALOG_LIVE_SCRIPT.read_text(encoding="utf-8")
    assert (
        '$databaseName = "clsen_data_test_$($runIdentifier.Substring(0, 16))"' in source
    )
    assert '$databaseName = "clsen_data_test_$runIdentifier"' not in source
    assert "[switch]$Experience" in source
    assert "experience-credentials.json" in source
    assert "Catalog experience READY." in source
    assert "Experience monitor detected" in source
    assert "Write-Host $managerPassword" not in source
    assert "$experienceUsername = if ($ExperienceOnly)" in source
    assert "$experiencePassword = if ($ExperienceOnly)" in source
    experience_seed = (
        'if ($ExperienceOnly) { $seedArguments += "--include-catalog-experience" }'
    )
    assert experience_seed in source
    assert "username = $experienceUsername" in source
    assert "password = $experiencePassword" in source
    assert (
        "$success -and $cleanupErrors.Count -eq 0 -and -not $ExperienceOnly" in source
    )
    assert 'Write-Host "Catalog experience stopped."' in source
    api_preflight = (
        'Invoke-SchemaPreflight -DatabaseEnvironment "APP_DATABASE_URL" '
        '-Component "api"'
    )
    worker_preflight = (
        "Invoke-SchemaPreflight -DatabaseEnvironment "
        '"APP_TEST_RUNTIME_DATABASE_URL" -Component "worker"'
    )

    assert source.count(api_preflight) == 2
    assert source.count(worker_preflight) == 2
    api_launches = [
        position
        for position in range(len(source))
        if source.startswith("$apiProcessId = [CatalogLiveJob]::Launch(", position)
    ]
    worker_launches = [
        position
        for position in range(len(source))
        if source.startswith("$workerProcessId = [CatalogLiveJob]::Launch(", position)
    ]
    api_preflights = [
        position
        for position in range(len(source))
        if source.startswith(api_preflight, position)
    ]
    worker_preflights = [
        position
        for position in range(len(source))
        if source.startswith(worker_preflight, position)
    ]
    assert len(api_launches) == len(api_preflights) == 2
    assert len(worker_launches) == len(worker_preflights) == 2
    assert all(
        guard < launch
        for guard, launch in zip(api_preflights, api_launches, strict=True)
    )
    assert all(
        guard < launch
        for guard, launch in zip(worker_preflights, worker_launches, strict=True)
    )
    probe = tmp_path / "probe-schema-preflight.ps1"
    probe.write_text(
        r"""
param([string]$LiveScriptPath)
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $LiveScriptPath, [ref]$tokens, [ref]$parseErrors
)
$definition = $ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Invoke-SchemaPreflight'
}, $true) | Select-Object -First 1
. ([scriptblock]::Create($definition.Extent.Text))
$backendDirectory = $PSScriptRoot
$pythonExecutable = 'Invoke-FakePreflight'
$script:preflightExit = 0
function Invoke-FakePreflight {
    '{"event":"schema_compatibility","status":"fixture"}'
    $global:LASTEXITCODE = $script:preflightExit
}
$output = @(Invoke-SchemaPreflight -DatabaseEnvironment fixture -Component api)
if ($output.Count -ne 0) { throw 'Schema logs contaminated the phase return value' }
$script:preflightExit = 1
$rejected = $false
try { Invoke-SchemaPreflight -DatabaseEnvironment fixture -Component api } catch {
    if ($_.ToString() -notlike '*schema preflight failed*') { throw }
    $rejected = $true
}
if (-not $rejected) { throw 'Failed schema preflight was accepted' }
Write-Output 'SCHEMA_PREFLIGHT_OUTPUT_PASS'
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(probe),
            "-LiveScriptPath",
            str(CATALOG_LIVE_SCRIPT),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "SCHEMA_PREFLIGHT_OUTPUT_PASS" in completed.stdout


def test_catalog_experience_stop_script_only_signals_an_owned_run() -> None:
    source = CATALOG_EXPERIENCE_STOP_SCRIPT.read_text(encoding="utf-8")

    assert "[ValidatePattern('\\A[0-9a-f]{32}\\z')]" in source
    assert '"clsen-catalog-live-$RunId"' in source
    assert '"clsen_data_test_$($RunId.Substring(0, 16))"' in source
    assert 'manifest.state -cne "experience_running"' in source
    assert "clsen.catalog-live.run" in source
    assert "start_ticks" in source
    assert 'action = "stop"' in source
    assert "Remove-Item" not in source
    assert "dockerCommand.Source rm" not in source


def test_product_catalog_release_runners_fail_closed_and_use_canonical_suites() -> None:
    performance = PERFORMANCE_RUNNER.read_text(encoding="utf-8")
    canary = CANARY_RUNNER.read_text(encoding="utf-8")
    restore = CATALOG_RESTORE_RUNNER.read_text(encoding="utf-8")
    manifest = json.loads(CI_SUITE_MANIFEST.read_text(encoding="utf-8"))

    assert '[string[]]$Versions = @("8.4")' in performance
    assert "foreach ($version in $Versions)" in performance
    assert '"8.0" = Resolve-ScaleEvidence' not in performance
    assert "analytics_scale_v1 evidence is required" in performance
    assert "-PerformanceProfile" in performance
    assert '-Suites @("performance")' in performance
    assert manifest["release_suites"]["performance"]["pytest_paths"] == [
        "backend/tests/performance/test_product_catalog_performance.py"
    ]
    assert "RequirePrivateCorpus" in canary
    assert "RequireCurrentDatabase" in canary
    assert "SELECT-only" in canary
    assert "ALLOWED_EVIDENCE_KEYS" not in canary
    assert "test_real_csv_regression.py" in canary
    assert "test_product_catalog_canary.py" in canary
    assert '[string[]]$Versions = @("8.4")' in restore
    assert "-Versions $Versions" in restore
    matrix = (REPOSITORY_ROOT / "scripts/test-mysql-matrix.ps1").read_text(
        encoding="utf-8"
    )
    assert '[string[]]$Versions = @("8.4")' in matrix
    assert '[ValidateSet("8.0", "8.4")]' in matrix
    assert '-Suites @("restore")' in restore
    assert "test_product_catalog_permissions.py" not in restore
    assert manifest["release_suites"]["restore"]["pytest_paths"] == [
        "backend/tests/integration/test_product_catalog_backup_restore.py"
    ]
