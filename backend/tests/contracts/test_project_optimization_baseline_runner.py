from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

import tests.conftest as backend_conftest
from tests.conftest import _stage0_nodeid

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts/run-project-optimization-baseline.ps1"
CI_PROFILE_RUNNER = ROOT / "scripts/run-ci-profile.ps1"


def test_runner_requires_external_evidence_and_same_sha() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    for token in (
        "EvidenceRoot",
        "SourceSha",
        "git status --porcelain",
        "APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT",
        "APP_RELEASE_SOURCE_SHA",
    ):
        assert token in source
    for token in (
        "prepare-run",
        "run-identity.json",
        "APP_PROJECT_OPTIMIZATION_RUN_DIR",
        "APP_TEST_DATABASE_URL",
        "APP_TEST_RUNTIME_DATABASE_URL",
        "FileMode]::CreateNew",
        "previousEnvironment",
        "SetEnvironmentVariable",
    ):
        assert token in source
    assert source.index('if ($Mode -eq "Validate")') < source.index("prepare-run")


def test_runner_executes_every_frozen_quality_gate() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    for token in (
        "ubuntu-full",
        "windows-smoke",
        "frontend-full",
        "mysql-compatibility",
        "8.0",
        "8.4",
        "generate-api-client.ps1",
        "run-product-catalog-performance.ps1",
    ):
        assert token in source
    for token in (
        "finalize-run",
        "validate-run",
        "command-result-",
        "stdout_sha256",
        "profile_node_digest",
        "skip_count",
        "xfail_count",
        "flaky_count",
        "pnpm.cmd",
        "validate-pytest-outcomes",
        "explained_skip_count",
        "unexplained_skip_count",
        "pytest_outcome_evidence",
    ):
        assert token in source


def test_formal_stage0_identity_excludes_quick_diagnostic_node() -> None:
    source = CI_PROFILE_RUNNER.read_text(encoding="utf-8")
    assert '"project-optimization-baseline"' in source
    assert "--deselect" in source
    assert "test_heartbeat_long_task_quick_check" in source
    assert (
        "Get-NodeIds -Python $python -PytestArguments $releasePytestArguments" in source
    )


def test_openapi_gate_uses_external_python_without_worktree_venv(
    tmp_path: Path,
) -> None:
    runner_source = RUNNER.read_text(encoding="utf-8")
    generator = ROOT / "scripts/generate-api-client.ps1"
    generator_source = generator.read_text(encoding="utf-8")
    runtime_python = Path(sys.executable).resolve()
    wrapper_name = "external-python.cmd" if os.name == "nt" else "external-python"
    external_python = (tmp_path / wrapper_name).resolve()

    assert runtime_python.is_file()
    assert ROOT.resolve() not in external_python.parents
    if os.name == "nt":
        external_python.write_text(
            f'@echo off\n"{runtime_python}" %*\n',
            encoding="utf-8",
        )
    else:
        external_python.write_text(
            f'#!/bin/sh\nexec "{runtime_python}" "$@"\n',
            encoding="utf-8",
        )
        external_python.chmod(0o700)
    normalized_runner = " ".join(runner_source.replace("`", "").split())
    assert (
        "-File scripts/generate-api-client.ps1 -PythonExecutable "
        "$PythonExecutable -Check"
    ) in normalized_runner

    # Keep ordinary direct invocations compatible with the existing local-venv
    # fallback while proving the isolated runner does not depend on that fallback.
    assert 'Join-Path $repositoryRoot ".venv\\Scripts\\python.exe"' in generator_source

    environment = os.environ.copy()
    for name in (
        *backend_conftest._PRIVATE_CANARY_ENVIRONMENT_NAMES,
        "APP_DATABASE_URL",
        "APP_MIGRATION_DATABASE_URL",
        "APP_TEST_DATABASE_URL",
        "APP_TEST_RUNTIME_DATABASE_URL",
        "APP_TEST_BACKUP_DATABASE_URL",
    ):
        environment[name] = ""
    for name in (
        "PYTEST_ADDOPTS",
        "PLAYWRIGHT_BASELINE_RETRIES",
        "APP_BASELINE_MYSQL_VERSION",
        "APP_PRODUCT_ANALYTICS_SOURCE",
        "APP_PRODUCT_CATALOG_MYSQL80_SCALE_EVIDENCE",
        "APP_PRODUCT_CATALOG_MYSQL84_SCALE_EVIDENCE",
        "APP_PRODUCT_CATALOG_SCALE_EVIDENCE_PATH",
        "APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT",
        "APP_PROJECT_OPTIMIZATION_RUN_DIR",
        "APP_PROJECT_OPTIMIZATION_SYNTHETIC_ONLY",
        "APP_RELEASE_ID",
        "APP_RELEASE_SOURCE_SHA",
        "APP_TEST_RUN_ID",
        "APP_STAGE0_PYTEST_OUTCOME_DIRECTORY",
        "APP_STAGE0_PYTEST_OUTCOME_BINDING",
        "APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID",
        "APP_STAGE0_PYTEST_OUTCOME_SHARD",
        "APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST",
        "APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS",
    ):
        environment.pop(name, None)

    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(generator),
            "-PythonExecutable",
            str(external_python),
            "-Check",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr


def test_runner_isolates_private_canary_environment_and_restores_it() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    private_names = (
        "APP_PRODUCT_CATALOG_CANARY_DATABASE_URL",
        "APP_PRODUCT_CATALOG_PRIVATE_MANIFEST",
        "APP_PRODUCT_CATALOG_PRIVATE_CORPUS_ROOT",
        "APP_REQUIRE_PRODUCT_CATALOG_CANARY",
        "APP_PRODUCT_CATALOG_CANARY_EVIDENCE_PATH",
    )
    for name in private_names:
        assert name in source
    assert "Clear-PrivateCanaryEnvironment" in source
    assert "Restore-ManagedEnvironment" in source
    assert source.index("Clear-PrivateCanaryEnvironment") < source.index(
        "& $Command 1> $stdoutPath 2> $stderrPath"
    )


def test_pytest_outcome_nodeids_preserve_escaped_parameter_identities() -> None:
    expected = r"backend/tests/unit/example.py::test_value[\u2007\nC:\path]"
    assert _stage0_nodeid(r"tests/unit/example.py::test_value[\u2007\nC:\path]") == (
        expected
    )
    assert (
        _stage0_nodeid(r"backend\tests\unit\example.py::test_value[\u2007\nC:\path]")
        == expected
    )


def test_private_canary_environment_helpers_clear_children_and_restore() -> None:
    names = (
        "APP_PRODUCT_CATALOG_CANARY_DATABASE_URL",
        "APP_PRODUCT_CATALOG_PRIVATE_MANIFEST",
        "APP_PRODUCT_CATALOG_PRIVATE_CORPUS_ROOT",
        "APP_REQUIRE_PRODUCT_CATALOG_CANARY",
        "APP_PRODUCT_CATALOG_CANARY_EVIDENCE_PATH",
    )
    command = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $args[0], [ref]$tokens, [ref]$errors
)
foreach ($name in $args[1].Split(',')) {
    $function = $ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq $name
    }, $true) | Select-Object -First 1
    . ([scriptblock]::Create($function.Extent.Text))
}
$privateNames = $args[2].Split(',')
$script:privateCanaryEnvironmentNames = $privateNames
foreach ($name in $privateNames) {
    [Environment]::SetEnvironmentVariable($name, 'sentinel-private')
}
$snapshot = Get-ManagedEnvironmentSnapshot -Names $privateNames
Clear-PrivateCanaryEnvironment
$visible = & $args[3] -c (
    'import json,os,sys;' +
    'print(json.dumps({n:os.getenv(n) for n in sys.argv[1:]}))'
) @privateNames | ConvertFrom-Json -AsHashtable
Restore-ManagedEnvironment -Snapshot $snapshot
$restoredAfterSuccess = @(
    $privateNames | Where-Object {
        [Environment]::GetEnvironmentVariable($_) -cne 'sentinel-private'
    }
).Count -eq 0
try {
    Clear-PrivateCanaryEnvironment
    throw 'synthetic failure'
}
catch {}
finally {
    Restore-ManagedEnvironment -Snapshot $snapshot
}
$restoredAfterFailure = @(
    $privateNames | Where-Object {
        [Environment]::GetEnvironmentVariable($_) -cne 'sentinel-private'
    }
).Count -eq 0
foreach ($name in $privateNames) {
    [Environment]::SetEnvironmentVariable($name, $null)
}
@{
    visible = $visible
    restored_after_success = $restoredAfterSuccess
    restored_after_failure = $restoredAfterFailure
} | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-CommandWithArgs",
            command,
            str(RUNNER),
            ",".join(
                (
                    "Get-ManagedEnvironmentSnapshot",
                    "Clear-PrivateCanaryEnvironment",
                    "Restore-ManagedEnvironment",
                )
            ),
            ",".join(names),
            sys.executable,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert set(result["visible"]) == set(names)
    assert set(result["visible"].values()) == {None}
    assert result["restored_after_success"] is True
    assert result["restored_after_failure"] is True


def test_stage0_require_mysql_blocks_dotenv_private_values_and_rechecks_session(
    tmp_path: Path, monkeypatch: Any
) -> None:
    class PluginManager:
        reporter: Any = None

        def register(self, reporter: Any, name: str) -> None:
            assert name == "stage0-outcome-reporter"
            self.reporter = reporter

    class Config:
        pluginmanager = PluginManager()

        @staticmethod
        def getoption(name: str) -> bool:
            return name == "--require-mysql"

    outcome_directory = tmp_path / "outcomes"
    outcome_directory.mkdir()
    controls = {
        "APP_STAGE0_PYTEST_OUTCOME_DIRECTORY": str(outcome_directory),
        "APP_STAGE0_PYTEST_OUTCOME_BINDING": "a" * 64,
        "APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID": "stage0-backend-8-0",
        "APP_STAGE0_PYTEST_OUTCOME_SHARD": "scoped",
        "APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST": hashlib.sha256(
            b"\n"
        ).hexdigest(),
    }
    for name, value in controls.items():
        monkeypatch.setenv(name, value)
    for name in backend_conftest._PRIVATE_CANARY_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)

    def fake_load_dotenv(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        for name in backend_conftest._PRIVATE_CANARY_ENVIRONMENT_NAMES:
            os.environ.setdefault(name, "sentinel-from-dotenv")

    monkeypatch.setattr(backend_conftest, "load_dotenv", fake_load_dotenv)
    config = Config()
    backend_conftest.pytest_configure(cast(Any, config))

    assert all(
        os.getenv(name) is None
        for name in backend_conftest._PRIVATE_CANARY_ENVIRONMENT_NAMES
    )
    reporter = config.pluginmanager.reporter
    assert reporter is not None
    reporter.pytest_collection_finish(cast(Any, type("Session", (), {"items": []})()))
    monkeypatch.setenv(
        backend_conftest._PRIVATE_CANARY_ENVIRONMENT_NAMES[0],
        "sentinel-during-session",
    )
    reporter.pytest_sessionfinish(cast(Any, object()), 0)
    report = json.loads((outcome_directory / "scoped.json").read_text())
    assert report["private_environment_clear"] is False
    assert os.getenv(backend_conftest._PRIVATE_CANARY_ENVIRONMENT_NAMES[0]) is None


def test_ordinary_require_mysql_preserves_canonical_dotenv_behavior(
    monkeypatch: Any,
) -> None:
    class PluginManager:
        @staticmethod
        def register(reporter: Any, name: str) -> None:
            raise AssertionError((reporter, name))

    class Config:
        pluginmanager = PluginManager()

        @staticmethod
        def getoption(name: str) -> bool:
            return name == "--require-mysql"

    for name in (
        "APP_STAGE0_PYTEST_OUTCOME_DIRECTORY",
        "APP_STAGE0_PYTEST_OUTCOME_BINDING",
        "APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID",
        "APP_STAGE0_PYTEST_OUTCOME_SHARD",
        "APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST",
    ):
        monkeypatch.delenv(name, raising=False)
    loaded: list[tuple[Path, bool]] = []

    def fake_load_dotenv(path: Path, *, override: bool) -> None:
        loaded.append((path, override))
        monkeypatch.setenv(
            backend_conftest._PRIVATE_CANARY_ENVIRONMENT_NAMES[0],
            "ordinary-dotenv-value",
        )

    monkeypatch.setattr(backend_conftest, "load_dotenv", fake_load_dotenv)
    backend_conftest.pytest_configure(cast(Any, Config()))

    assert loaded == [(backend_conftest.REPOSITORY_ROOT / ".env", False)]
    assert (
        os.getenv(backend_conftest._PRIVATE_CANARY_ENVIRONMENT_NAMES[0])
        == "ordinary-dotenv-value"
    )


def test_stage0_reporter_children_keep_private_environment_clear(
    tmp_path: Path,
) -> None:
    private_names = backend_conftest._PRIVATE_CANARY_ENVIRONMENT_NAMES
    nodeid = (
        "backend/tests/contracts/test_project_optimization_baseline_runner.py::"
        "test_pytest_outcome_nodeids_preserve_escaped_parameter_identities"
    )
    expected_digest = hashlib.sha256(f"{nodeid}\n".encode()).hexdigest()
    cases = (
        ("ubuntu", "ubuntu-full", False),
        ("mysql", "mysql-compatibility-8-0", True),
        ("stage0", "stage0-backend-8-0", True),
    )
    for case_name, command_id, require_mysql in cases:
        report_directory = tmp_path / case_name
        report_directory.mkdir()
        environment = os.environ.copy()
        for name in private_names:
            environment.pop(name, None)
        environment.pop("PYTEST_ADDOPTS", None)
        for name in (
            "APP_DATABASE_URL",
            "APP_MIGRATION_DATABASE_URL",
            "APP_TEST_DATABASE_URL",
            "APP_TEST_RUNTIME_DATABASE_URL",
            "APP_TEST_BACKUP_DATABASE_URL",
        ):
            environment[name] = ""
        environment.update(
            {
                "APP_STAGE0_PYTEST_OUTCOME_DIRECTORY": str(report_directory),
                "APP_STAGE0_PYTEST_OUTCOME_BINDING": "a" * 64,
                "APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID": command_id,
                "APP_STAGE0_PYTEST_OUTCOME_SHARD": "pytest",
                "APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST": expected_digest,
                "APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS": json.dumps(
                    {"pytest": expected_digest}, separators=(",", ":")
                ),
            }
        )
        arguments = [
            sys.executable,
            "-m",
            "pytest",
            (
                "tests/contracts/test_project_optimization_baseline_runner.py::"
                "test_pytest_outcome_nodeids_preserve_escaped_parameter_identities"
            ),
            "-q",
        ]
        if require_mysql:
            arguments.append("--require-mysql")
        completed = subprocess.run(
            arguments,
            cwd=ROOT / "backend",
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert completed.returncode == 0, completed.stderr
        report = json.loads((report_directory / "pytest.json").read_text())
        assert report["private_environment_clear"] is True
        assert report["expected_node_digest"] == expected_digest
        assert report["collected_nodeids"] == [nodeid]
        assert report["session_exit_code"] == 0


def test_stale_reporter_and_pytest_addopts_cannot_contaminate_identity_collection(
    tmp_path: Path,
) -> None:
    control_names = (
        "APP_STAGE0_PYTEST_OUTCOME_DIRECTORY",
        "APP_STAGE0_PYTEST_OUTCOME_BINDING",
        "APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID",
        "APP_STAGE0_PYTEST_OUTCOME_SHARD",
        "APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST",
        "APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS",
    )
    clean_environment = os.environ.copy()
    for name in (*control_names, "PYTEST_ADDOPTS"):
        clean_environment.pop(name, None)
    canonical = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(ROOT / "scripts/run-ci-profile.ps1"),
            "-Profile",
            "ubuntu-full",
            "-PythonExecutable",
            sys.executable,
            "-Stage0IdentityOnly",
        ],
        cwd=ROOT,
        env=clean_environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert canonical.returncode == 0, canonical.stderr
    expected_identity = json.loads(canonical.stdout)

    stale_directory = tmp_path / "stale-reporter"
    stale_directory.mkdir()
    command = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $args[0], [ref]$tokens, [ref]$errors
)
foreach ($name in $args[1].Split(',')) {
    $function = $ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq $name
    }, $true) | Select-Object -First 1
    . ([scriptblock]::Create($function.Extent.Text))
}
$script:repositoryRoot = $args[2]
$script:PythonExecutable = $args[3]
$script:SourceSha = ('a' * 40)
$script:pwshCommand = 'pwsh'
$script:privateCanaryEnvironmentNames = @(
    'APP_PRODUCT_CATALOG_CANARY_DATABASE_URL',
    'APP_PRODUCT_CATALOG_PRIVATE_MANIFEST',
    'APP_PRODUCT_CATALOG_PRIVATE_CORPUS_ROOT',
    'APP_REQUIRE_PRODUCT_CATALOG_CANARY',
    'APP_PRODUCT_CATALOG_CANARY_EVIDENCE_PATH'
)
$script:stage0PytestOutcomeEnvironmentNames = $args[4].Split(',')
$managedNames = @(
    $script:stage0PytestOutcomeEnvironmentNames +
    $script:privateCanaryEnvironmentNames +
    @('PYTEST_ADDOPTS')
)
foreach ($name in $script:stage0PytestOutcomeEnvironmentNames) {
    [Environment]::SetEnvironmentVariable($name, 'stale-control')
}
$env:APP_STAGE0_PYTEST_OUTCOME_DIRECTORY = $args[5]
$env:APP_STAGE0_PYTEST_OUTCOME_BINDING = ('b' * 64)
$env:APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID = 'ubuntu-full'
$env:APP_STAGE0_PYTEST_OUTCOME_SHARD = 'pytest'
$env:APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST = ('c' * 64)
$env:APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS = '{"pytest":"' + ('c' * 64) + '"}'
$env:PYTEST_ADDOPTS = (
    '--deselect=tests/contracts/' +
    'test_project_optimization_baseline_runner.py::' +
    'test_runner_requires_external_evidence_and_same_sha'
)
foreach ($name in $script:privateCanaryEnvironmentNames) {
    [Environment]::SetEnvironmentVariable($name, 'stale-private')
}
$snapshot = Get-ManagedEnvironmentSnapshot -Names $managedNames
try {
    $identity = Get-Stage0PytestIdentity `
        -Name 'ubuntu-full' `
        -ExpectedProfile 'ubuntu-full' `
        -ExpectedShards @('pytest')
    $reportCount = @(Get-ChildItem -LiteralPath $args[5] -Force).Count
}
finally {
    Restore-ManagedEnvironment -Snapshot $snapshot
}
$restored = @(
    $managedNames | Where-Object {
        [Environment]::GetEnvironmentVariable($_) -cne $snapshot[$_]
    }
).Count -eq 0
@{
    identity = $identity
    stale_report_count = $reportCount
    restored = $restored
} | ConvertTo-Json -Depth 6 -Compress
"""
    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-CommandWithArgs",
            command,
            str(RUNNER),
            ",".join(
                (
                    "Get-ManagedEnvironmentSnapshot",
                    "Clear-PrivateCanaryEnvironment",
                    "Clear-Stage0PytestOutcomeEnvironment",
                    "Restore-ManagedEnvironment",
                    "Get-Stage0PytestIdentity",
                )
            ),
            str(ROOT),
            sys.executable,
            ",".join(control_names),
            str(stale_directory),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["identity"] == expected_identity
    assert result["stale_report_count"] == 0
    assert result["restored"] is True


def test_runner_binds_shard_identities_and_clears_ambient_controls() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    profile = (ROOT / "scripts/run-ci-profile.ps1").read_text(encoding="utf-8")
    matrix = (ROOT / "scripts/test-mysql-matrix.ps1").read_text(encoding="utf-8")
    validator = (ROOT / "tools/project_optimization_baseline.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "Clear-Stage0PytestOutcomeEnvironment",
        "APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST",
        "APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS",
        "PYTEST_ADDOPTS",
        "Get-Stage0PytestIdentity",
    ):
        assert token in source

    command = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $args[0], [ref]$tokens, [ref]$errors
)
if (@($errors).Count -ne 0) {
    throw 'The production runner did not parse.'
}
$assignments = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left.Extent.Text -ceq '$outcomeShards'
}, $true))
if ($assignments.Count -ne 1) {
    throw 'Expected exactly one production OutcomeShards assignment.'
}
$assignmentText = $assignments[0].Extent.Text
$cases = @(
    [pscustomobject]@{
        name = 'singleton'
        profile = @{ OutcomeShards = @('pytest') }
    },
    [pscustomobject]@{
        name = 'missing'
        profile = @{}
    },
    [pscustomobject]@{
        name = 'multiple'
        profile = @{ OutcomeShards = @('migration', 'scoped') }
    }
)
$results = foreach ($case in $cases) {
    $profile = $case.profile
    $outcomeShards = $null
    . ([scriptblock]::Create($assignmentText))
    [ordered]@{
        name = $case.name
        is_array = $outcomeShards -is [array]
        count = $outcomeShards.Count
        values = @($outcomeShards)
    }
}
@($results) | ConvertTo-Json -Depth 4 -Compress
"""
    completed = subprocess.run(
        ["pwsh", "-NoProfile", "-CommandWithArgs", command, str(RUNNER)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        {
            "name": "singleton",
            "is_array": True,
            "count": 1,
            "values": ["pytest"],
        },
        {"name": "missing", "is_array": True, "count": 0, "values": []},
        {
            "name": "multiple",
            "is_array": True,
            "count": 2,
            "values": ["migration", "scoped"],
        },
    ]

    assert "Stage0IdentityOnly" in profile
    assert "APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST" in profile
    assert "APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST" in matrix
    assert '"08-stage0-backend-8-0", "stage0-backend-8-0", True' in validator
    assert '"09-stage0-backend-8-4", "stage0-backend-8-4", True' in validator


def test_native_cleanup_removes_unexpected_files_without_masking_primary_failure(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    helper_names = (
        "Get-Sha256Bytes",
        "Protect-Output",
        "Write-ExclusiveJson",
        "Get-ManagedEnvironmentSnapshot",
        "Clear-PrivateCanaryEnvironment",
        "Clear-Stage0PytestOutcomeEnvironment",
        "Restore-ManagedEnvironment",
        "Write-TimingLine",
        "Get-PytestOutcomeBinding",
        "Get-ValidatedPytestOutcome",
        "Remove-OwnedDirectRegularChildren",
        "Invoke-NativeChecked",
    )
    command = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $args[0], [ref]$tokens, [ref]$errors
)
foreach ($name in $args[1].Split(',')) {
    $function = $ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq $name
    }, $true) | Select-Object -First 1
    . ([scriptblock]::Create($function.Extent.Text))
}
$script:PythonExecutable = $args[2]
$script:SourceSha = ('a' * 40)
$script:manifest = $args[3]
$script:platformId = 'win32'
$script:privateCanaryEnvironmentNames = @()
$script:stage0PytestOutcomeEnvironmentNames = @(
    'APP_STAGE0_PYTEST_OUTCOME_DIRECTORY',
    'APP_STAGE0_PYTEST_OUTCOME_BINDING',
    'APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID',
    'APP_STAGE0_PYTEST_OUTCOME_SHARD',
    'APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST',
    'APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS'
)

function Remove-LeakedCommandDirectory([string]$Root) {
    if ([string]::IsNullOrWhiteSpace($Root)) { return }
    $outcomes = Join-Path $Root 'pytest-outcomes'
    if (Test-Path -LiteralPath $outcomes -PathType Container) {
        foreach ($entry in @(Get-ChildItem -LiteralPath $outcomes -Force)) {
            if ($entry.PSIsContainer) {
                Remove-Item -LiteralPath $entry.FullName -Force
            }
            else {
                Remove-Item -LiteralPath $entry.FullName -Force
            }
        }
        Remove-Item -LiteralPath $outcomes -Force
    }
    foreach ($name in @('stdout', 'stderr', 'injected-directory')) {
        $path = Join-Path $Root $name
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }
    if (Test-Path -LiteralPath $Root -PathType Container) {
        Remove-Item -LiteralPath $Root -Force
    }
}

$nativeExtraRoot = $null
$nativeExtraMessage = $null
try {
    Invoke-NativeChecked `
        -Description 'native extra file' `
        -PytestOutcomeCommandId 'ubuntu-full' `
        -PytestOutcomeProfile 'ubuntu-full' `
        -PytestOutcomeShards @('pytest') `
        -ProfileNodeDigest ('a' * 64) `
        -PytestOutcomeShardDigests @{ pytest = ('a' * 64) } `
        -SuppressOutput {
        $script:nativeExtraRoot = $commandStreamDirectory
        [IO.File]::WriteAllText(
            (Join-Path $outcomeReportDirectory 'unexpected.txt'), 'unexpected'
        )
        & $script:PythonExecutable -c 'raise SystemExit(7)'
    }
}
catch { $nativeExtraMessage = $_.Exception.Message }
finally { Remove-LeakedCommandDirectory -Root $nativeExtraRoot }

$malformedExtraRoot = $null
$malformedExtraMessage = $null
try {
    Invoke-NativeChecked `
        -Description 'malformed extra file' `
        -PytestOutcomeCommandId 'ubuntu-full' `
        -PytestOutcomeProfile 'ubuntu-full' `
        -PytestOutcomeShards @('pytest') `
        -ProfileNodeDigest ('a' * 64) `
        -PytestOutcomeShardDigests @{ pytest = ('a' * 64) } `
        -SuppressOutput {
        $script:malformedExtraRoot = $commandStreamDirectory
        [IO.File]::WriteAllText(
            (Join-Path $outcomeReportDirectory 'pytest.json'), '{'
        )
        [IO.File]::WriteAllText(
            (Join-Path $outcomeReportDirectory 'unexpected.txt'), 'unexpected'
        )
        & $script:PythonExecutable -c 'raise SystemExit(0)'
    }
}
catch { $malformedExtraMessage = $_.Exception.Message }
finally { Remove-LeakedCommandDirectory -Root $malformedExtraRoot }

$nativeCleanupRoot = $null
$nativeCleanupMessage = $null
try {
    Invoke-NativeChecked -Description 'native cleanup precedence' -SuppressOutput {
        $script:nativeCleanupRoot = $commandStreamDirectory
        $null = New-Item -ItemType Directory -Path (
            Join-Path $commandStreamDirectory 'injected-directory'
        )
        & $script:PythonExecutable -c 'raise SystemExit(9)'
    }
}
catch { $nativeCleanupMessage = $_.Exception.Message }
finally {
    $nativeCleanupDirectoryPreserved = Test-Path -LiteralPath (
        Join-Path $nativeCleanupRoot 'injected-directory'
    ) -PathType Container
    Remove-LeakedCommandDirectory -Root $nativeCleanupRoot
}

$cleanupOnlyRoot = $null
$cleanupOnlyMessage = $null
try {
    Invoke-NativeChecked -Description 'cleanup only' -SuppressOutput {
        $script:cleanupOnlyRoot = $commandStreamDirectory
        $null = New-Item -ItemType Directory -Path (
            Join-Path $commandStreamDirectory 'injected-directory'
        )
        & $script:PythonExecutable -c 'raise SystemExit(0)'
    }
}
catch { $cleanupOnlyMessage = $_.Exception.Message }
finally {
    $cleanupOnlyDirectoryPreserved = Test-Path -LiteralPath (
        Join-Path $cleanupOnlyRoot 'injected-directory'
    ) -PathType Container
    Remove-LeakedCommandDirectory -Root $cleanupOnlyRoot
}

@{
    native_extra = $nativeExtraMessage
    malformed_extra = $malformedExtraMessage
    native_cleanup = $nativeCleanupMessage
    cleanup_only = $cleanupOnlyMessage
    native_cleanup_directory_preserved = $nativeCleanupDirectoryPreserved
    cleanup_only_directory_preserved = $cleanupOnlyDirectoryPreserved
} | ConvertTo-Json -Compress
"""
    monkeypatch.chdir(ROOT / "backend")
    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-CommandWithArgs",
            command,
            str(RUNNER),
            ",".join(helper_names),
            sys.executable,
            str(ROOT / "scripts/project-optimization-baseline-manifest.json"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "native_extra": "native extra file failed with exit code 7.",
        "malformed_extra": "malformed extra file pytest outcome evidence is invalid.",
        "native_cleanup": "native cleanup precedence failed with exit code 9.",
        "cleanup_only": "Command stream cleanup failed.",
        "native_cleanup_directory_preserved": True,
        "cleanup_only_directory_preserved": True,
    }


def test_runner_disallows_retry_based_success(tmp_path: Path) -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert 'PLAYWRIGHT_BASELINE_RETRIES = "0"' in source
    assert "Invoke-NativeChecked" in source
    assert "Retry" not in source
    assert "retry_count" in source
    assert 'if ($Mode -eq "Freeze")' in source
    assert "ApprovedBy" in source
    assert "ApprovalReference" in source
    assert "--budget-overrides" in source
    assert "AcceptProposedBudgets" in source
    assert "CompleteFreeze" in source
    assert "ApprovedRunId" in source
    assert "ApprovedToken" in source
    assert "--approved-token" in source
    assert "commandStagingDirectory" in source
    assert "Publish-CommandResults" in source
    assert "commandStreamDirectory" in source
    assert "UnixFileMode]::UserRead" in source
    assert "SetUnixFileMode" in source
    assert "GetUnixFileMode" in source
    assert "Approval token:" in source
    assert source.index(
        "Measured scenario table requiring explicit approval:"
    ) < source.index("if (-not $CompleteFreeze)")

    assert "Get-OutcomeCounts" not in source

    helper_names = ("Protect-Output",)
    command = """
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $args[0], [ref]$tokens, [ref]$errors
)
foreach ($name in $args[1].Split(',')) {
    $function = $ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq $name
    }, $true) | Select-Object -First 1
    . ([scriptblock]::Create($function.Extent.Text))
}
$secret = 'sentinel-password'
$env:APP_TEST_DATABASE_URL = 'mysql+pymysql://user:sentinel-password@host/db'
$safe = Protect-Output -Value (
    'password: sentinel-password --token=sentinel-token ' +
    '--api-key sentinel-api Authorization: Bearer sentinel-bearer ' +
    'X-API-Key: sentinel-header {"secret":"sentinel-json"} ' +
    'mysql://user:pass@host/db'
)
@{
    safe = $safe
} | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-CommandWithArgs",
            command,
            str(RUNNER),
            ",".join(helper_names),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert "sentinel" not in result["safe"]
    _assert_runner_preserves_separate_stdout_and_stderr_digests(tmp_path)


def _assert_runner_preserves_separate_stdout_and_stderr_digests(
    tmp_path: Path,
) -> None:
    helper_names = (
        "Get-Sha256Bytes",
        "Protect-Output",
        "Write-ExclusiveJson",
        "Get-ManagedEnvironmentSnapshot",
        "Clear-PrivateCanaryEnvironment",
        "Clear-Stage0PytestOutcomeEnvironment",
        "Restore-ManagedEnvironment",
        "Write-TimingLine",
        "Get-PytestOutcomeBinding",
        "Get-ValidatedPytestOutcome",
        "Remove-OwnedDirectRegularChildren",
        "Invoke-NativeChecked",
    )
    command = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $args[0], [ref]$tokens, [ref]$errors
)
foreach ($name in $args[1].Split(',')) {
    $function = $ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq $name
    }, $true) | Select-Object -First 1
    . ([scriptblock]::Create($function.Extent.Text))
}
$script:commandStagingDirectory = $args[2]
$script:commandSequence = 0
$script:nativeCommand = $args[3]
$script:PythonExecutable = $args[3]
$script:SourceSha = ('a' * 40)
$script:manifest = $args[4]
$script:platformId = 'win32'
$script:privateCanaryEnvironmentNames = @()
$script:stage0PytestOutcomeEnvironmentNames = @(
    'APP_STAGE0_PYTEST_OUTCOME_DIRECTORY',
    'APP_STAGE0_PYTEST_OUTCOME_BINDING',
    'APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID',
    'APP_STAGE0_PYTEST_OUTCOME_SHARD',
    'APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST',
    'APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS'
)
$script:invalidProfileCommandExecuted = $false
$invalidProfileMessage = $null
try {
    Invoke-NativeChecked `
        -Description 'invalid profile identity test' `
        -ProfileNodeDigest @(('a' * 64), ('b' * 64)) `
        -SuppressOutput {
        $script:invalidProfileCommandExecuted = $true
        & $script:nativeCommand -c 'raise SystemExit(0)'
    }
}
catch {
    $invalidProfileMessage = $_.Exception.Message
}
if ($invalidProfileCommandExecuted) {
    throw 'invalid profile identity executed its command'
}
if ($invalidProfileMessage -cne 'Command profile identity is invalid.') {
    throw "invalid profile identity did not fail fast: $invalidProfileMessage"
}
$script:permissionsChecked = $false
$emptyDigest = Get-Sha256Bytes -Value $null
Invoke-NativeChecked `
    -Description 'stream test' `
    -EvidenceKey 'stream-test' `
    -SuppressOutput {
    if (-not $IsWindows) {
        $ownerDirectoryMode = (
            [IO.UnixFileMode]::UserRead -bor
            [IO.UnixFileMode]::UserWrite -bor
            [IO.UnixFileMode]::UserExecute
        )
        $ownerFileMode = (
            [IO.UnixFileMode]::UserRead -bor
            [IO.UnixFileMode]::UserWrite
        )
        if (
            [IO.File]::GetUnixFileMode($commandStreamDirectory) -ne
                $ownerDirectoryMode -or
            [IO.File]::GetUnixFileMode($stdoutPath) -ne $ownerFileMode -or
            [IO.File]::GetUnixFileMode($stderrPath) -ne $ownerFileMode
        ) {
            throw 'command stream permissions are not owner-only'
        }
        $script:permissionsChecked = $true
    }
    & $script:nativeCommand -c (
        'import os;os.write(1,b"stdout");os.write(2,b"stderr")'
    )
}
Invoke-NativeChecked `
    -Description 'empty stderr test' `
    -EvidenceKey 'empty-stderr-test' `
    -SuppressOutput {
    & $script:nativeCommand -c 'import os;os.write(1,b"stdout")'
}
$nodeId = 'backend/tests/unit/example.py::test_stage0_identity'
$nodeDigest = Get-Sha256Bytes -Value (
    [Text.Encoding]::UTF8.GetBytes($nodeId + "`n")
)
foreach ($name in $script:stage0PytestOutcomeEnvironmentNames) {
    [Environment]::SetEnvironmentVariable($name, 'stale-control')
}
$env:PYTEST_ADDOPTS = '--deselect=stale-node'
Invoke-NativeChecked `
    -Description 'valid pytest outcome test' `
    -EvidenceKey 'valid-pytest-outcome-test' `
    -ProfileNodeDigest $nodeDigest `
    -PytestOutcomeCommandId 'ubuntu-full' `
    -PytestOutcomeProfile 'ubuntu-full' `
    -PytestOutcomeShards @('pytest') `
    -PytestOutcomeShardDigests @{ pytest = $nodeDigest } `
    -SuppressOutput {
    if (
        $env:APP_STAGE0_PYTEST_OUTCOME_DIRECTORY -ceq 'stale-control' -or
        $env:APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID -cne 'ubuntu-full' -or
        $env:APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS -notlike "*$nodeDigest*" -or
        $null -ne $env:APP_STAGE0_PYTEST_OUTCOME_SHARD -or
        $null -ne $env:APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST -or
        $null -ne $env:PYTEST_ADDOPTS
    ) {
        throw 'runner-owned pytest outcome environment was contaminated'
    }
    Write-ExclusiveJson `
        -Path (Join-Path $env:APP_STAGE0_PYTEST_OUTCOME_DIRECTORY 'pytest.json') `
        -Payload ([ordered]@{
            schema_version = 2
            binding_sha256 = $env:APP_STAGE0_PYTEST_OUTCOME_BINDING
            shard_id = 'pytest'
            expected_node_digest = $nodeDigest
            session_exit_code = 0
            private_environment_clear = $true
            collected_nodeids = @($nodeId)
            outcomes = @(
                @{
                    nodeid = $nodeId
                    status = 'passed'
                    reason = ''
                }
            )
        })
    & $script:nativeCommand -c 'raise SystemExit(0)'
}
if (
    @(
        $script:stage0PytestOutcomeEnvironmentNames | Where-Object {
            $null -ne [Environment]::GetEnvironmentVariable($_)
        }
    ).Count -ne 0 -or
    $null -ne $env:PYTEST_ADDOPTS
) {
    throw 'runner-owned pytest outcome environment was not cleared after command'
}
$failureMessage = $null
try {
    Invoke-NativeChecked `
        -Description 'failure cleanup test' `
        -EvidenceKey 'failure-precedence-test' `
        -PytestOutcomeCommandId 'ubuntu-full' `
        -PytestOutcomeProfile 'ubuntu-full' `
        -PytestOutcomeShards @('pytest') `
        -ProfileNodeDigest ('a' * 64) `
        -PytestOutcomeShardDigests @{ pytest = ('a' * 64) } `
        -SuppressOutput {
        & $script:nativeCommand -c (
            'import os;os.write(2,b"sentinel-failure");raise SystemExit(7)'
        )
    }
}
catch {
    $failureMessage = $_.Exception.Message
}
if ($failureMessage -cne 'failure cleanup test failed with exit code 7.') {
    throw "nonzero failure precedence was lost: $failureMessage"
}
if (-not $IsWindows -and -not $script:permissionsChecked) {
    throw 'POSIX permission contract was not executed'
}
$expectedEmptyDigest = (
    'e3b0c44298fc1c149afbf4c8996fb924' +
    '27ae41e4649b934ca495991b7852b855'
)
if ($emptyDigest -cne $expectedEmptyDigest) {
    throw 'empty stream digest is invalid'
}
"""
    stream_directories_before = set(
        Path(tempfile.gettempdir()).glob("project-optimization-command-*")
    )
    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-CommandWithArgs",
            command,
            str(RUNNER),
            ",".join(helper_names),
            str(tmp_path),
            sys.executable,
            str(ROOT / "scripts/project-optimization-baseline-manifest.json"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    assert (
        set(Path(tempfile.gettempdir()).glob("project-optimization-command-*"))
        == stream_directories_before
    )
    result = json.loads(
        (tmp_path / "command-result-01-stream-test.json").read_text(encoding="utf-8")
    )
    assert (
        result["stdout_sha256"]
        == hashlib.sha256(f"stdout{os.linesep}".encode()).hexdigest()
    )
    assert (
        result["stderr_sha256"]
        == hashlib.sha256(f"stderr{os.linesep}".encode()).hexdigest()
    )
    assert result["profile_node_digest"] is None
    empty_stderr = json.loads(
        (tmp_path / "command-result-02-empty-stderr-test.json").read_text(
            encoding="utf-8"
        )
    )
    assert empty_stderr["stderr_sha256"] == hashlib.sha256(b"").hexdigest()
    assert empty_stderr["profile_node_digest"] is None
    failed = json.loads(
        (tmp_path / "command-result-04-failure-precedence-test.json").read_text(
            encoding="utf-8"
        )
    )
    assert failed["exit_code"] == 7
    assert failed["pytest_outcome_evidence"]["status"] == "invalid"
    valid = json.loads(
        (tmp_path / "command-result-03-valid-pytest-outcome-test.json").read_text(
            encoding="utf-8"
        )
    )
    assert valid["pytest_outcome_evidence"]["status"] == "valid"
    assert valid["skip_count"] == 0
    assert (
        valid["profile_node_digest"]
        == valid["pytest_outcome_evidence"]["collected_node_digest"]
    )
