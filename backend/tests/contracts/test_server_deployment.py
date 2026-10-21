from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_compose_keeps_mysql_and_application_services_internal() -> None:
    compose = _read("ops/docker-compose.yml")

    assert "mysql:8.4.11" in compose
    assert "--require-secure-transport=ON" in compose
    assert "--tls-version=TLSv1.2,TLSv1.3" in compose
    assert "${BIND_ADDRESS:-127.0.0.1}:${HTTPS_PORT:-8443}:8443" in compose
    assert compose.count("ports:") == 1
    for service in ("mysql", "backend", "worker", "frontend"):
        assert f"  {service}:\n" in compose
    assert "internal: true" in compose


def test_compose_uses_secrets_healthchecks_and_process_hardening() -> None:
    compose = _read("ops/docker-compose.yml")

    for secret in (
        "mysql_root_password",
        "mysql_app_password",
        "mysql_migrator_password",
        "mysql_backup_password",
        "session_secret",
        "tls_certificate",
        "tls_private_key",
    ):
        assert f"{secret}:" in compose
    assert "healthcheck:" in compose
    assert (
        "APP_PRODUCT_ANALYTICS_SOURCE: "
        "${APP_PRODUCT_ANALYTICS_SOURCE:?APP_PRODUCT_ANALYTICS_SOURCE is required}"
        in compose
    )
    assert (
        "VITE_PRODUCT_ANALYTICS_SOURCE: "
        "${VITE_PRODUCT_ANALYTICS_SOURCE:?VITE_PRODUCT_ANALYTICS_SOURCE is required}"
        in compose
    )
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose
    assert "read_only: true" in compose
    assert "CHANGE_ME" not in compose
    init_users = _read("ops/mysql/init-users.sh")
    assert "CREATE USER IF NOT EXISTS 'clsen_schema_unreadable'@'%'" in init_users
    assert "schema-unreadable:" in init_users
    example = _read(".env.example")
    assert "APP_PRODUCT_ANALYTICS_SOURCE=p0_catalog" in example
    assert "VITE_PRODUCT_ANALYTICS_SOURCE=p0_catalog" in example
    assert "APP_PRODUCT_ANALYTICS_SOURCE=legacy_parser" not in example
    assert "VITE_PRODUCT_ANALYTICS_SOURCE=legacy_parser" not in example


def test_compose_migration_is_explicit_with_direct_runtime_dependencies() -> None:
    compose = yaml.safe_load(_read("ops/docker-compose.yml"))
    services = compose["services"]

    assert services["migrate"]["profiles"] == ["operations"]
    for role in ("backend", "worker"):
        dependencies = services[role]["depends_on"]
        assert "migrate" not in dependencies
        assert dependencies == {
            "mysql": {"condition": "service_healthy"},
            "storage-init": {"condition": "service_completed_successfully"},
        }


def test_verifier_records_explicit_operations_migration_before_runtime_start() -> None:
    verifier = _read("ops/verify-deployment.ps1")
    explicit_migration = "Invoke-Compose --profile operations run --rm migrate"
    runtime_start = "Invoke-Compose up --detach"

    assert explicit_migration in verifier
    assert verifier.index(explicit_migration) < verifier.index(runtime_start)
    assert "--profile verification run --rm migrate" not in verifier


@pytest.mark.parametrize("skip_roundtrip", [False, True])
def test_historical_nodes_run_once_before_current_head(
    tmp_path: Path, skip_roundtrip: bool
) -> None:
    ops = tmp_path / "ops"
    (ops / "secrets").mkdir(parents=True)
    (ops / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    verifier = ops / "verify-deployment.ps1"
    verifier.write_text(_read("ops/verify-deployment.ps1"), encoding="utf-8")
    manifest_path = "backend/tests/fixtures/ci/mysql-historical-nodeids.txt"
    manifest = tmp_path / manifest_path
    manifest.parent.mkdir(parents=True)
    manifest.write_text(_read(manifest_path), encoding="utf-8")
    harness = tmp_path / "schedule.ps1"
    harness.write_text(
        r"""
param([string]$Verifier, [int]$SkipRoundtrip)
$ErrorActionPreference = "Stop"
$global:deploymentSchedule = [Collections.Generic.List[object]]::new()
function docker {
    param([Parameter(ValueFromRemainingArguments)][string[]]$CommandArguments)
    $global:LASTEXITCODE = 0
    $command = $CommandArguments -join " "
    if ($CommandArguments[0] -eq "inspect") { return "healthy" }
    if ($command -match ' ps -q \S+$') { return "owned-test-container" }
    if ($command -match ' port nginx 8443$') { return "127.0.0.1:49152" }
    if (
        $CommandArguments -contains "reset-test-database" -or
        $CommandArguments -contains "pytest"
    ) {
        $global:deploymentSchedule.Add(@($CommandArguments))
    }
    if ($CommandArguments -contains "tests/integration/test_published_analytics.py") {
        throw "schedule-probe-complete"
    }
}
function Invoke-WebRequest {
    param([string]$Uri, [switch]$SkipCertificateCheck)
    return @{
        StatusCode = 200
        Headers = @{
            "Strict-Transport-Security" = "present"
            "Content-Security-Policy" = "present"
            "X-Content-Type-Options" = "present"
        }
    }
}
try {
    & $Verifier -DisposableTestRun -SkipBuild `
        -SkipMigrationRoundtrip:([bool]$SkipRoundtrip)
}
catch { $failure = $_.Exception.Message }
@{
    error = $failure
    commands = @($global:deploymentSchedule.ToArray())
} | ConvertTo-Json -Depth 5 -Compress
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(harness),
            str(verifier),
            str(int(skip_roundtrip)),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=30,
    )
    evidence = json.loads(result.stdout)
    assert evidence["error"] == "schedule-probe-complete"
    commands = evidence["commands"]
    assert commands[0][-2:] == ["reset-test-database", "--empty"]
    assert commands[2][-1] == "reset-test-database"
    historical = commands[1]
    assert historical[-3:] == ["--require-mysql", "-q", "-x"]
    nodes = historical[historical.index("pytest") + 1 : -3]
    historical_files = {
        "tests/integration/test_stage_five_schema.py",
        "tests/integration/test_stage_six_schema.py",
        "tests/integration/test_admin_operation_permissions.py",
    }
    if not skip_roundtrip:
        historical_files.add("tests/integration/test_migrations.py")
    expected = [
        line
        for line in _read(manifest_path).splitlines()
        if line.split("::", 1)[0] in historical_files
    ]
    assert nodes == expected
    assert len(nodes) == len(set(nodes))
    for command in commands[3:]:
        assert "pytest" in command
        targets = {arg for arg in command if arg.startswith("tests/")}
        exclusions = {
            arg.removeprefix("--deselect=")
            for arg in command
            if arg.startswith("--deselect=")
        }
        # Every relocated node is excluded from its later file invocation.
        assert {
            node for node in nodes if node.split("::", 1)[0] in targets
        } <= exclusions
        assert exclusions <= set(nodes)
        assert "tests/integration/test_migrations.py" not in targets
    assert 'raise RuntimeError("Initialization evidence must be retained")' in _read(
        "backend/alembic/versions/0030_return_initialization.py"
    )


def test_backend_image_is_python_314_and_installs_hashed_lock() -> None:
    dockerfile = _read("backend/Dockerfile")

    assert "python:3.14.7-slim-trixie" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "requirements.lock" in dockerfile
    assert "mysql-community-client" in dockerfile
    assert "USER app" in dockerfile


def test_frontend_image_uses_locked_node_build_and_unprivileged_runtime() -> None:
    dockerfile = _read("frontend/Dockerfile")

    assert "node:24-alpine" in dockerfile
    assert "pnpm install --frozen-lockfile" in dockerfile
    assert "ARG VITE_PRODUCT_ANALYTICS_SOURCE" in dockerfile
    assert (
        "ENV VITE_PRODUCT_ANALYTICS_SOURCE=${VITE_PRODUCT_ANALYTICS_SOURCE}"
        in dockerfile
    )
    assert "nginxinc/nginx-unprivileged" in dockerfile


def test_edge_nginx_enforces_https_and_security_headers() -> None:
    nginx = _read("ops/nginx/default.conf")

    assert "listen 8443 ssl" in nginx
    assert "ssl_protocols TLSv1.2 TLSv1.3" in nginx
    assert "Strict-Transport-Security" in nginx
    assert "Content-Security-Policy" in nginx
    assert "X-Content-Type-Options" in nginx
    assert "client_max_body_size 100m" in nginx
    assert "proxy_pass http://backend:8000" in nginx
    assert "proxy_pass http://frontend:8080" in nginx


def test_load_verification_isolated_to_container_test_database() -> None:
    compose = _read("ops/docker-compose.yml")
    verification_nginx = _read("ops/nginx/verification.conf")
    bootstrap = _read("ops/bootstrap-secrets.ps1")

    assert "verification-backend:" in compose
    assert "APP_DEPLOYMENT_DATABASE: clsen_data_test_container" in compose
    assert "verification-nginx:" in compose
    assert "proxy_pass http://verification-backend:8000" in verification_nginx
    assert "DNS:verification-nginx" in bootstrap
    assert "RotateEdgeCertificate" in bootstrap
    assert "reset-test-database" in _read("backend/app/deployment/entrypoint.py")


def test_server_secrets_are_ignored() -> None:
    gitignore = _read(".gitignore")

    assert "/ops/secrets/" in gitignore


def test_deployment_runbook_and_verifier_preserve_named_volumes() -> None:
    runbook = _read("ops/DEPLOYMENT.md")
    verifier = _read("ops/verify-deployment.ps1")

    assert "docker compose --env-file .\\.env -f .\\ops\\docker-compose.yml" in runbook
    assert "docker compose -f .\\ops\\docker-compose.yml config" not in runbook
    assert "docker compose down -v" in runbook
    assert "reset-test-database" in verifier
    assert "test_server_deployment_load.py" in verifier
    assert "restore-verifier" in verifier
    assert "down -v" not in verifier


def test_release_verifier_has_an_owned_disposable_database_mode() -> None:
    verifier = _read("ops/verify-deployment.ps1")
    mysql_initializer = _read("ops/mysql/init-users.sh")
    workflow = _read(".github/workflows/release-gates.yml")
    profile_runner = _read("scripts/run-ci-profile.ps1")

    assert "[switch]$DisposableTestRun" in verifier
    assert (
        '$disposableDatabase = "clsen_data_test_$($runIdentifier.Substring(0, 16))"'
        in verifier
    )
    assert "APP_DEPLOYMENT_TEST_DATABASE: $disposableDatabase" in verifier
    assert "APP_TEST_DATABASE_SCOPE: disposable-compose" in verifier
    assert "APP_TEST_COMPOSE_PROJECT: $composeProjectName" in verifier
    assert "deployment_database=${MYSQL_DATABASE:-clsen_data}" in mysql_initializer
    assert "clsen_data|clsen_data_test_?*" in mysql_initializer
    assert "*[!a-z0-9_]*" in mysql_initializer
    assert "test_database=$deployment_database" in mysql_initializer
    assert "--project-name" in verifier
    assert "clsen-deployment-verify-" in verifier
    assert "@disposableCleanupProfiles" in verifier
    assert '"verification"' in verifier
    assert '"maintenance"' in verifier
    assert '"load-test"' in verifier
    assert "down --volumes --remove-orphans" in verifier
    assert "-ReleaseSuite deployment" in workflow
    assert '"ops/verify-deployment.ps1"' in profile_runner
    assert "-DisposableTestRun" in profile_runner


def test_verifier_does_not_use_powershell_common_parameter_abbreviations() -> None:
    verifier = _read("ops/verify-deployment.ps1")

    assert "Invoke-Compose up -d" not in verifier
    assert "Invoke-Compose --profile load-test up -d" not in verifier
    assert "\n        -e APP_DEPLOYMENT_" not in verifier
    assert "Invoke-Compose up --detach" in verifier
    assert "--env APP_DEPLOYMENT_HTTPS_BASE_URL=" in verifier
    assert '$env:APP_PRODUCT_ANALYTICS_SOURCE = "p0_catalog"' in verifier
    assert '$env:VITE_PRODUCT_ANALYTICS_SOURCE = "p0_catalog"' in verifier


def test_verifier_uses_dictionary_compatible_header_lookup() -> None:
    verifier = _read("ops/verify-deployment.ps1")

    assert ".Headers.ContainsKey($header)" in verifier
    assert ".Headers.Contains($header)" not in verifier


@pytest.mark.parametrize(
    ("binding", "expected_error", "expected_uri"),
    [
        (
            "127.0.0.1:19443",
            "startup-probe-complete",
            "https://localhost:19443/api/health/ready",
        ),
        ("0.0.0.0:19443", "Disposable HTTPS loopback binding is unavailable.", None),
        ("", "Disposable HTTPS loopback binding is unavailable.", None),
        ("127.0.0.1:0", "Disposable HTTPS port is invalid.", None),
    ],
)
def test_disposable_verifier_probes_its_own_port_and_restores_environment(
    tmp_path: Path, binding: str, expected_error: str, expected_uri: str | None
) -> None:
    ops = tmp_path / "ops"
    (ops / "secrets").mkdir(parents=True)
    (ops / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    verifier = ops / "verify-deployment.ps1"
    verifier.write_text(_read("ops/verify-deployment.ps1"), encoding="utf-8")
    harness = tmp_path / "probe.ps1"
    harness.write_text(
        r"""
param([string]$Verifier, [string]$Binding)
$ErrorActionPreference = "Stop"
$env:BIND_ADDRESS = "0.0.0.0"
$env:HTTPS_PORT = "8443"
$global:deploymentProbe = @{
    uri = $null
    cleaned = $false
    bindings = [Collections.Generic.List[string]]::new()
    returnedBinding = $Binding
}
function docker {
    param([Parameter(ValueFromRemainingArguments)][string[]]$CommandArguments)
    $global:LASTEXITCODE = 0
    $global:deploymentProbe.bindings.Add("$env:BIND_ADDRESS/$env:HTTPS_PORT")
    $command = $CommandArguments -join " "
    if ($command -match ' down --volumes --remove-orphans$') {
        $global:deploymentProbe.cleaned = $true
        return
    }
    if ($null -ne $global:deploymentProbe.uri) { throw "startup-probe-complete" }
    if ($CommandArguments[0] -eq "inspect") { return "healthy" }
    if ($command -match ' ps -q \S+$') { return "owned-test-container" }
    if (
        $command -match ' port nginx 8443$' -and
        $global:deploymentProbe.returnedBinding
    ) {
        return $global:deploymentProbe.returnedBinding
    }
}
function Invoke-WebRequest {
    param([string]$Uri, [switch]$SkipCertificateCheck)
    $global:deploymentProbe.uri = $Uri
    return @{
        StatusCode = 200
        Headers = @{
            "Strict-Transport-Security" = "present"
            "Content-Security-Policy" = "present"
            "X-Content-Type-Options" = "present"
        }
    }
}
try { & $Verifier -DisposableTestRun -SkipBuild }
catch { $failure = $_.Exception.Message }
@{
    error = $failure
    uri = $global:deploymentProbe.uri
    cleaned = $global:deploymentProbe.cleaned
    bindings = @($global:deploymentProbe.bindings)
    restored = "$env:BIND_ADDRESS/$env:HTTPS_PORT"
} | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(harness), str(verifier), binding],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=30,
    )
    evidence = json.loads(result.stdout)
    assert evidence["error"] == expected_error
    assert evidence["uri"] == expected_uri
    assert evidence["cleaned"] is True
    assert set(evidence["bindings"]) == {"127.0.0.1/0"}
    assert evidence["restored"] == "0.0.0.0/8443"


def test_release_workflow_calls_the_same_canonical_runners_and_fails_closed() -> None:
    workflow = _read(".github/workflows/release-gates.yml")
    profile_runner = _read("scripts/run-ci-profile.ps1")

    assert "workflow_dispatch:" in workflow
    assert "APP_PRODUCT_CATALOG_CANARY_DATABASE_URL" in workflow
    assert "secrets.APP_PRODUCT_CATALOG_MYSQL80_SCALE_EVIDENCE" not in workflow
    assert "APP_PRODUCT_CATALOG_MYSQL84_SCALE_EVIDENCE" in workflow
    assert "scripts/run-ci-profile.ps1" in workflow
    assert "test-mysql-matrix.ps1" not in workflow
    for runner in (
        "run-product-catalog-performance.ps1",
        "run-product-catalog-canary.ps1",
        "run-product-catalog-backup-restore.ps1",
        "run-product-catalog-live-e2e.ps1",
        "verify-deployment.ps1",
    ):
        assert runner in profile_runner
    assert "-RequirePrivateCorpus" in profile_runner
    assert "-RequireCurrentDatabase" in profile_runner
    assert "-ReleaseMode" in profile_runner
    assert "-Profile release-only" in workflow
    assert "continue-on-error" not in workflow


def test_product_catalog_rollout_documents_release_only_boundaries() -> None:
    rollout = _read("docs/operations/product-catalog-rollout.md")

    assert "legacy-before" in rollout
    assert "legacy-rollback" in rollout
    assert "SELECT-only" in rollout
    assert "不授权生产迁移或流量切换" in rollout
    assert "downgrade Alembic" in rollout
