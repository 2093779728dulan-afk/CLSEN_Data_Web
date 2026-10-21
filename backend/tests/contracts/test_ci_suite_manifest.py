from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
COMPATIBILITY = REPOSITORY_ROOT / ".github" / "workflows" / "compatibility.yml"
RELEASE = REPOSITORY_ROOT / ".github" / "workflows" / "release-gates.yml"
MANIFEST = REPOSITORY_ROOT / "scripts" / "ci-suite-manifest.json"
PROFILE_RUNNER = REPOSITORY_ROOT / "scripts" / "run-ci-profile.ps1"


def _load_workflow(path: Path) -> dict[str, Any]:
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(workflow, dict)
    assert "on" in workflow
    assert True not in workflow
    return workflow


def _job_source(job: dict[str, Any]) -> str:
    return json.dumps(job, sort_keys=True)


def test_compatibility_events_and_concurrency_are_usage_bounded() -> None:
    workflow = _load_workflow(COMPATIBILITY)
    events = workflow["on"]
    assert events["push"]["branches"] == ["master"]
    assert "pull_request" in events

    concurrency = workflow["concurrency"]
    group = concurrency["group"]
    cancel = concurrency["cancel-in-progress"]
    assert "application-compatibility-pr-" in group
    assert "github.event.pull_request.number" in group
    assert "application-compatibility-master-" in group
    assert "github.sha" in group
    assert "github.event_name == 'pull_request'" in cancel


def test_compatibility_has_stable_fail_closed_required_jobs() -> None:
    jobs = _load_workflow(COMPATIBILITY)["jobs"]
    expected_execution = {
        "backend-ubuntu",
        "backend-windows",
        "frontend",
        "mysql-84",
    }
    assert expected_execution <= set(jobs)
    assert "mysql-80" not in jobs
    assert "if" not in jobs["mysql-84"]
    assert set(jobs["pr-required"]["needs"]) == expected_execution
    assert set(jobs["master-required"]["needs"]) == expected_execution
    assert jobs["pr-required"]["if"] == (
        "always() && github.event_name == 'pull_request'"
    )
    assert jobs["master-required"]["if"] == "always() && github.event_name == 'push'"
    for name in ("pr-required", "master-required"):
        job = jobs[name]
        assert job["name"] == name
        assert "toJson(needs)" in _job_source(job)
        assert "success" in _job_source(job)
        assert "exit 1" in _job_source(job)
        script = job["steps"][0]["run"]
        for results in (
            {"backend-ubuntu": "success", "backend-windows": "success"},
            {"backend-ubuntu": "failure", "backend-windows": "skipped"},
            {"backend-ubuntu": "success", "backend-windows": "cancelled"},
            {"mysql-84": "failure"},
            {"mysql-84": "skipped"},
            {"mysql-84": "cancelled"},
        ):
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                env={
                    **os.environ,
                    "NEEDS_JSON": json.dumps(
                        {key: {"result": value} for key, value in results.items()}
                    ),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            failures = {
                key: value for key, value in results.items() if value != "success"
            }
            assert completed.returncode == (1 if failures else 0)
            for key, result in failures.items():
                assert f"Required job failed: {key} ({result})" in completed.stderr
    for name in ("mysql-84",):
        job = jobs[name]
        execution = next(step for step in job["steps"] if step.get("id") == "mysql")
        cleanup = job["steps"][-1]
        assert int(job["timeout-minutes"]) > int(execution["timeout-minutes"])
        assert cleanup["if"] == "always()"
        assert cleanup["run"] == "./scripts/cleanup-ci-mysql.ps1"
        assert "steps.mysql.outputs.mysql_run_id" in _job_source(cleanup)
        assert "-MySqlVersion 8.4" in execution["run"]


def test_compatibility_jobs_only_select_canonical_profiles() -> None:
    workflow = _load_workflow(COMPATIBILITY)
    jobs = workflow["jobs"]
    expected_profiles = {
        "backend-ubuntu": "ubuntu-full",
        "backend-windows": "windows-smoke",
        "frontend": "frontend-full",
        "mysql-84": "mysql-compatibility",
    }
    for job_name, profile in expected_profiles.items():
        source = _job_source(jobs[job_name])
        assert "scripts/run-ci-profile.ps1" in source
        assert f"-Profile {profile}" in source
    whole_source = COMPATIBILITY.read_text(encoding="utf-8")
    assert 'tests -m "not mysql"' not in whole_source
    assert "tests/integration/test_" not in whole_source


def test_release_workflow_splits_trusted_provenance_from_private_gate() -> None:
    workflow = _load_workflow(RELEASE)
    dispatch = workflow["on"]["workflow_dispatch"]
    source_input = dispatch["inputs"]["source_sha"]
    assert source_input["required"] == "true"

    concurrency = workflow["concurrency"]
    assert "product-catalog-release-" in concurrency["group"]
    assert "inputs.source_sha" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == "false"

    jobs = workflow["jobs"]
    assert set(jobs) == {"provenance", "release-gates"}
    provenance = jobs["provenance"]
    gate = jobs["release-gates"]
    assert provenance["runs-on"] == ["self-hosted", "Linux", "X64", "clsen-rag-ov"]
    assert "environment" not in provenance
    assert provenance["permissions"] == {"actions": "read", "contents": "read"}
    assert gate["permissions"] == {"contents": "read"}
    assert gate["environment"] == "clsen-release-gates"
    assert gate["needs"] == "provenance"

    provenance_source = _job_source(provenance)
    assert "verify-release-source.ps1" in provenance_source
    assert "git/ref/heads/master" in provenance_source
    assert "-DispatchRef" in provenance_source
    assert "github.workflow_sha" in provenance_source
    assert "github.ref" in provenance_source
    assert "fetch-depth" in provenance_source
    gate_source = _job_source(gate)
    assert "needs.provenance.outputs.source_sha" in gate_source
    assert "run-ci-profile.ps1" in gate_source
    assert "APP_PLAN_BASELINE_ROOT" not in gate_source


def test_enabled_workflow_jobs_do_not_select_github_hosted_runners() -> None:
    windows = _load_workflow(COMPATIBILITY)["jobs"]["backend-windows"]
    assert "if" not in windows
    assert windows["runs-on"] == ["self-hosted", "Windows", "X64", "clsen-windows-ci"]
    assert "actions/setup-python" not in _job_source(windows)
    runtime = next(
        step for step in windows["steps"] if step.get("id") == "setup-python"
    )
    assert "RUNNER_TOOL_CACHE" in runtime["run"]
    assert "Python/3.14.8/x64" in runtime["run"]
    assert "python-path=" in runtime["run"]
    assert "throw" in runtime["run"]
    release = _load_workflow(RELEASE)["jobs"]["release-gates"]
    assert "clsen-release" in release["runs-on"]
    assert "clsen-windows-ci" not in release["runs-on"]
    for workflow_path in (COMPATIBILITY, RELEASE):
        jobs = _load_workflow(workflow_path)["jobs"]
        for job_name, job in jobs.items():
            runs_on = job["runs-on"]
            if isinstance(runs_on, str):
                assert not runs_on.endswith("-latest"), job_name
            else:
                assert "self-hosted" in runs_on, job_name


def test_release_secrets_are_step_scoped_and_profiles_are_release_only() -> None:
    gate = _load_workflow(RELEASE)["jobs"]["release-gates"]
    assert "env" not in gate
    suites = {
        "workspace-boundary",
        "performance",
        "canary",
        "restore",
        "live",
        "deployment",
        "generated-contract",
    }
    sources = [_job_source(step) for step in gate["steps"]]
    for suite in suites:
        matching = [source for source in sources if f"-ReleaseSuite {suite}" in source]
        assert matching, suite
        assert all("-Profile release-only" in source for source in matching)
    whole_source = "\n".join(sources)
    assert 'tests -m \\"not mysql\\"' not in whole_source
    assert "test-mysql-matrix.ps1" not in whole_source
    live = next(source for source in sources if "-ReleaseSuite live" in source)
    assert "APP_PRODUCT_ANALYTICS_SOURCE" in live
    assert "VITE_PRODUCT_ANALYTICS_SOURCE" in live
    assert live.count("p0_catalog") >= 2


def test_release_deployment_secrets_are_ephemeral_after_clean_checkout() -> None:
    gate = _load_workflow(RELEASE)["jobs"]["release-gates"]
    checkout = next(
        step
        for step in gate["steps"]
        if step.get("name") == "Check out verified source"
    )
    assert checkout["with"]["clean"] == "true"

    deployment = next(
        step
        for step in gate["steps"]
        if step.get("name") == "Run deployment verification"
    )
    source = _job_source(deployment)
    assert "bootstrap-secrets.ps1" in source
    assert "try" in source
    assert "finally" in source
    assert "Remove-Item" in source
    assert "-LiteralPath" in source
    assert "-ReleaseSuite deployment" in source

    profile_source = PROFILE_RUNNER.read_text(encoding="utf-8")
    validation = re.search(
        r'if \(\$ValidateOnly\).*?"deployment" \{(?P<body>.*?)\n\s*\}',
        profile_source,
        re.DOTALL,
    )
    assert validation is not None
    assert "ops/secrets" not in validation.group("body")
    assert "bootstrap-secrets.ps1" in validation.group("body")


def test_manifest_has_strict_top_level_and_canonical_profiles() -> None:
    assert MANIFEST.is_file()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert set(manifest) == {
        "schema_version",
        "profiles",
        "mysql_suites",
        "mysql_exclusions",
        "windows_smoke",
        "release_suites",
    }
    assert manifest["schema_version"] == 1
    assert manifest["profiles"]["mysql-compatibility"]["versions"] == ["8.4"]
    assert set(manifest["profiles"]) == {
        "ubuntu-full",
        "windows-smoke",
        "frontend-full",
        "mysql-compatibility",
        "release-only",
    }
    assert manifest["profiles"]["mysql-compatibility"]["suites"] == [
        "mysql-migrations",
        "mysql-legacy",
        "mysql-p0",
        "mysql-schema-startup",
        "mysql-worker-observability",
    ]
    assert manifest["mysql_suites"]["mysql-schema-startup"] == [
        "backend/tests/integration/test_schema_compatibility.py",
        "backend/tests/integration/test_schema_startup_processes.py",
    ]
    assert manifest["mysql_suites"]["mysql-worker-observability"] == [
        "backend/tests/integration/test_worker_observability.py",
        "backend/tests/integration/test_worker_observability_api.py",
    ]
    assert set(manifest["release_suites"]) == {
        "workspace-boundary",
        "performance",
        "canary",
        "restore",
        "live",
        "deployment",
        "generated-contract",
        "project-optimization-baseline",
    }
    baseline_runner_paths = [
        "scripts/project-optimization-baseline-manifest.json",
        "tools/project_optimization_baseline.py",
        "backend/tests/performance/project_optimization_baseline.py",
        "backend/tests/performance/test_project_optimization_baseline.py",
        "frontend/playwright.baseline.config.ts",
        "frontend/playwright.config.ts",
        "frontend/tests/e2e/project-optimization-baseline.spec.ts",
        "frontend/scripts/project-optimization-bundle-baseline.mjs",
        "scripts/run-project-optimization-baseline.ps1",
    ]
    assert (
        manifest["release_suites"]["project-optimization-baseline"]["runner_paths"]
        == baseline_runner_paths
    )
    assert manifest["release_suites"]["performance"]["runner_paths"] == [
        "backend/tests/performance/product_catalog_scale_fixture.py",
        "backend/tests/performance/test_product_catalog_performance.py",
        "scripts/run-product-catalog-performance.ps1",
        "scripts/run-ci-profile.ps1",
    ]
    for raw_path in baseline_runner_paths:
        assert (REPOSITORY_ROOT / raw_path).is_file(), raw_path


def test_project_optimization_baseline_resolves_as_one_mysql_release_path() -> None:
    module = REPOSITORY_ROOT / "scripts" / "CiSuiteManifest.psm1"
    script = (
        f"Import-Module '{module}' -Force; "
        "$manifest = Import-CiSuiteManifest -RepositoryRoot '"
        f"{REPOSITORY_ROOT}'; "
        "$paths = @(Get-MySqlSuitePaths -Suites project-optimization-baseline "
        "-Manifest $manifest); ConvertTo-Json -InputObject $paths -Compress"
    )
    completed = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        "backend/tests/performance/test_project_optimization_baseline.py"
    ]


def test_manifest_paths_are_safe_existing_and_unique() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    paths: list[str] = []
    for suite in manifest["mysql_suites"].values():
        paths.extend(suite)
    paths.extend(manifest["windows_smoke"]["paths"])
    for suite in manifest["release_suites"].values():
        paths.extend(suite.get("pytest_paths", []))
    assert len(paths) == len(set(paths))
    for raw_path in paths:
        path = Path(raw_path)
        assert not path.is_absolute()
        assert ".." not in path.parts
        assert (REPOSITORY_ROOT / path).exists(), raw_path


def test_every_mysql_marked_module_is_classified_exactly_once() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    classified: list[str] = []
    for suite in manifest["mysql_suites"].values():
        classified.extend(suite)
    classified.extend(manifest["mysql_exclusions"])
    for suite in manifest["release_suites"].values():
        classified.extend(suite.get("pytest_paths", []))

    marked = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in (REPOSITORY_ROOT / "backend" / "tests").rglob("*.py")
        if re.search(
            r"pytestmark\s*=\s*pytest\.mark\.mysql|@pytest\.mark\.mysql",
            path.read_text(encoding="utf-8"),
        )
    }
    for path in marked:
        assert classified.count(path) == 1, path


def test_product_catalog_scale_fixture_nodes_are_frozen_in_ubuntu_profile() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fixture = REPOSITORY_ROOT / manifest["profiles"]["ubuntu-full"]["baseline_fixture"]
    prefix = "backend/tests/unit/test_product_catalog_scale_fixture.py::"
    actual = {
        line
        for line in fixture.read_text(encoding="utf-8").splitlines()
        if line.startswith(prefix)
    }
    expected = {
        prefix + "test_loopback_login_failure_has_safe_status_category_and_code"
        "[401-invalid_credentials-login_http_401]",
        prefix + "test_loopback_login_failure_has_safe_status_category_and_code"
        "[403-csrf_invalid-login_http_403]",
        prefix + "test_loopback_login_failure_has_safe_status_category_and_code"
        "[429-login_rate_limited-login_http_429]",
        prefix + "test_loopback_login_failure_has_safe_status_category_and_code"
        "[500-internal_server_error-login_http_5xx]",
        prefix + "test_loopback_login_failure_uses_safe_fallback_for_unknown_status",
        prefix
        + "test_loopback_login_failure_does_not_retain_unknown_or_malformed_payload"
        "[payload0]",
        prefix
        + "test_loopback_login_failure_does_not_retain_unknown_or_malformed_payload"
        "[payload1]",
        prefix
        + "test_loopback_login_failure_does_not_retain_unknown_or_malformed_payload"
        "[payload2]",
        prefix
        + "test_loopback_login_failure_does_not_retain_unknown_or_malformed_payload"
        "[payload3]",
        prefix
        + "test_loopback_login_failure_does_not_retain_unknown_or_malformed_payload"
        "[payload4]",
        prefix + "test_loopback_login_failure_does_not_retain_body_headers_or_cookies",
        prefix + "test_loopback_login_failure_contains_json_exception",
        prefix + "test_loopback_login_failure_contains_mapping_exception[contains]",
        prefix + "test_loopback_login_failure_contains_mapping_exception[get]",
        prefix + "test_loopback_login_failure_contains_mapping_exception[index]",
        prefix + "test_loopback_login_failure_contains_mapping_exception[iteration]",
        prefix + "test_loopback_login_failure_does_not_catch_control_flow[failure0]",
        prefix + "test_loopback_login_failure_does_not_catch_control_flow[failure1]",
        prefix + "test_loopback_login_failure_does_not_catch_control_flow[failure2]",
        prefix + "test_loopback_login_success_is_unchanged",
    }
    assert actual == expected


def test_windows_smoke_path_boundary_is_exact() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["windows_smoke"]["paths"] == [
        "backend/tests/contracts",
        "backend/tests/unit/catalog/test_ooxml.py",
        "backend/tests/unit/catalog/test_normalization.py",
        "backend/tests/unit/imports/test_storage.py",
        "backend/tests/unit/auth/test_product_catalog_live_harness.py",
        "backend/tests/unit/deployment/test_entrypoint.py",
        "backend/tests/unit/maintenance/test_schema_compatibility.py",
        "backend/tests/unit/maintenance/test_worker_status.py",
        "backend/tests/unit/test_logging.py",
        "backend/tests/unit/test_main_schema_compatibility.py",
        "backend/tests/unit/test_openapi_contract.py",
        "backend/tests/unit/test_schema_preflight.py",
        "backend/tests/unit/worker/test_cli.py",
        "backend/tests/unit/worker/test_heartbeat.py",
        "backend/tests/unit/worker/test_observability.py",
        "backend/tests/unit/worker/test_runner.py",
    ]
    fixture = (
        REPOSITORY_ROOT / manifest["profiles"]["windows-smoke"]["baseline_fixture"]
    )
    nodes = [
        line
        for line in fixture.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    original_nodes = [
        node
        for node in nodes
        if "/test_project_optimization_baseline_runner.py::" not in node
    ]
    assert len(original_nodes) == 360
    assert len(set(original_nodes)) == 360
    assert len({node.casefold() for node in original_nodes}) == 359
    assert len(nodes) == 373
    assert len(set(nodes)) == 373
    assert len({node.casefold() for node in nodes}) == 372
    runner = PROFILE_RUNNER.read_text(encoding="utf-8")
    assert "[StringComparer]::Ordinal" in runner
    assert "Sort-Object -Unique" not in runner


def test_profile_runner_is_fail_closed() -> None:
    assert PROFILE_RUNNER.is_file()
    source = PROFILE_RUNNER.read_text(encoding="utf-8")
    assert "ValidateSet" in source
    assert "ubuntu-full" in source
    assert "windows-smoke" in source
    assert "frontend-full" in source
    assert "mysql-compatibility" in source
    assert "release-only" in source
    assert "ValidateOnly" in source
    assert "ListOnly" in source
    assert "Python 3.14" in source
    assert '$env:PLAYWRIGHT_CUTOVER_RUN = "1"' in source
    assert '$env:VITE_PRODUCT_ANALYTICS_SOURCE = "p0_catalog"' in source
    assert "[Net.Sockets.TcpListener]::new" in source
    assert "$previousPlaywrightPort" in source
    assert "$previousCutoverRun" in source
    assert "$previousPlaywrightSource" in source
    matrix_runner = (REPOSITORY_ROOT / "scripts" / "test-mysql-matrix.ps1").read_text(
        encoding="utf-8"
    )
    assert 'tests -m "not mysql"' not in matrix_runner
    assert '"mysql-worker-observability"' in matrix_runner
    module = (REPOSITORY_ROOT / "scripts" / "CiSuiteManifest.psm1").read_text(
        encoding="utf-8"
    )
    assert "System.Text.Json.JsonDocument" in module
    assert "Duplicate JSON object key" in module
