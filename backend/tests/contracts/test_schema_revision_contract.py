from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from app.maintenance.schema_revision import (
    BACKUP_READER_SCHEMA_REVISIONS,
    CURRENT_SCHEMA_REVISION,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
SCHEMA_REVISION_MODULE = BACKEND_ROOT / "app" / "maintenance" / "schema_revision.py"
WORKTREE_TEXT_CHECKER = REPOSITORY_ROOT / "scripts" / "check-worktree-text.ps1"
BASELINE_CHECKER = REPOSITORY_ROOT / "scripts" / "check-plan-worktree-baseline.ps1"


def _literal_assignment(module: ast.Module, name: str) -> object:
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            return ast.literal_eval(statement.value)
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
        ):
            if statement.value is None:
                raise AssertionError(f"schema revision assignment {name} has no value")
            return ast.literal_eval(statement.value)
    raise AssertionError(f"schema revision module does not define {name}")


def _run_powershell(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(script), *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_schema_revision_has_one_literal_runtime_source() -> None:
    module = ast.parse(SCHEMA_REVISION_MODULE.read_text(encoding="utf-8"))

    assert _literal_assignment(module, "CURRENT_SCHEMA_REVISION") == "0030"
    assert _literal_assignment(module, "BACKUP_READER_SCHEMA_REVISIONS") == (
        "0020",
        "0021",
        "0022",
        "0023",
        "0024",
        "0025",
        "0026",
        "0027",
        "0028",
        "0029",
        "0030",
    )


def test_current_revision_matches_the_only_alembic_head() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "alembic.ini",
            "heads",
        ],
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.stdout.strip() == "0030 (head)"


def test_backup_writer_and_restore_reader_have_distinct_revision_policies() -> None:
    backup_source = (REPOSITORY_ROOT / "backend/app/maintenance/backup.py").read_text(
        encoding="utf-8"
    )
    restore_source = (REPOSITORY_ROOT / "backend/app/maintenance/restore.py").read_text(
        encoding="utf-8"
    )

    assert CURRENT_SCHEMA_REVISION == "0030"
    assert BACKUP_READER_SCHEMA_REVISIONS == (
        "0020",
        "0021",
        "0022",
        "0023",
        "0024",
        "0025",
        "0026",
        "0027",
        "0028",
        "0029",
        "0030",
    )
    assert "schema_revision != CURRENT_SCHEMA_REVISION" in backup_source
    assert "schema_revision not in BACKUP_READER_SCHEMA_REVISIONS" in restore_source
    assert "0019" not in BACKUP_READER_SCHEMA_REVISIONS
    assert "0022" in BACKUP_READER_SCHEMA_REVISIONS
    assert "0023" in BACKUP_READER_SCHEMA_REVISIONS
    assert "0024" in BACKUP_READER_SCHEMA_REVISIONS
    assert "0025" in BACKUP_READER_SCHEMA_REVISIONS
    assert "0026" in BACKUP_READER_SCHEMA_REVISIONS


def test_cli_preflight_requires_the_shared_current_revision() -> None:
    source = (REPOSITORY_ROOT / "backend/app/cli.py").read_text(encoding="utf-8")

    assert "revision != CURRENT_SCHEMA_REVISION" in source
    assert "expected " in source
    assert "CURRENT_SCHEMA_REVISION!r" in source


@pytest.mark.parametrize(
    ("relative_path", "required_import"),
    (
        ("backend/app/cli.py", "CURRENT_SCHEMA_REVISION"),
        ("backend/app/maintenance/backup.py", "CURRENT_SCHEMA_REVISION"),
        ("backend/app/maintenance/restore.py", "BACKUP_READER_SCHEMA_REVISIONS"),
    ),
)
def test_python_revision_consumers_import_the_shared_source(
    relative_path: str,
    required_import: str,
) -> None:
    source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")

    assert "from app.maintenance.schema_revision import" in source
    assert required_import in source


@pytest.mark.parametrize(
    ("relative_path", "required_runtime_marker"),
    (
        (
            "scripts/init-database.ps1",
            "$actualSchemaRevision.Trim() -cne $expectedSchemaRevision",
        ),
        (
            "scripts/sync-test-runtime-grants.ps1",
            "$actualSchemaRevision.Trim() -cne $expectedSchemaRevision",
        ),
        (
            "scripts/test-mysql-matrix.ps1",
            "if actual != CURRENT_SCHEMA_REVISION:",
        ),
    ),
)
def test_powershell_revision_consumers_resolve_the_python_source(
    relative_path: str,
    required_runtime_marker: str,
) -> None:
    source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
    contract = (REPOSITORY_ROOT / "scripts/DatabaseContract.psm1").read_text(
        encoding="utf-8"
    )

    assert "DatabaseContract.psm1" in source
    assert "Get-DatabaseSchemaRevision" in source
    assert "app.maintenance.schema_revision" in contract
    assert '"0021"' not in source
    assert required_runtime_marker in source


def test_compatibility_workflow_checks_the_shared_revision_contract() -> None:
    source = (REPOSITORY_ROOT / ".github/workflows/compatibility.yml").read_text(
        encoding="utf-8"
    )
    profile = (REPOSITORY_ROOT / "scripts/run-ci-profile.ps1").read_text(
        encoding="utf-8"
    )
    ci_manifest = json.loads(
        (REPOSITORY_ROOT / "scripts/ci-suite-manifest.json").read_text(encoding="utf-8")
    )
    baseline = (
        REPOSITORY_ROOT / "backend/tests/fixtures/ci/offline-backend-nodeids.txt"
    ).read_text(encoding="utf-8")

    assert "-Profile ubuntu-full" in source
    ubuntu = ci_manifest["profiles"]["ubuntu-full"]
    assert ubuntu["pytest_paths"] == ["backend/tests"]
    assert ubuntu["pytest_marker"] == "not mysql"
    assert ubuntu["pytest_ignores"] == [
        "backend/tests/performance/test_project_optimization_baseline.py",
        "backend/tests/integration/test_product_catalog_canary.py",
        "backend/tests/integration/test_real_csv_regression.py",
    ]
    for selector_field in ("pytest_paths", "pytest_marker", "pytest_ignores"):
        assert f"profileDefinition.{selector_field}" in profile
    assert "test_schema_revision_contract.py::" in baseline


def test_worktree_text_checker_rejects_an_unsorted_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('["backend/pyproject.toml","backend/app/main.py"]\n')

    completed = _run_powershell(
        WORKTREE_TEXT_CHECKER,
        "-PathManifest",
        str(manifest),
        "-BaselineRoot",
        str(tmp_path / "private-baseline"),
    )

    assert completed.returncode != 0
    assert "ordinal-sorted" in (completed.stdout + completed.stderr)


def test_baseline_checker_rejects_a_repository_internal_baseline() -> None:
    completed = _run_powershell(
        BASELINE_CHECKER,
        "-PathManifest",
        str(
            REPOSITORY_ROOT / "docs/superpowers/plans/"
            "2026-08-20-product-style-variant-analytics-foundation-"
            "file-manifest.json"
        ),
        "-BaselineRoot",
        str(REPOSITORY_ROOT / ".forged-plan-baseline"),
    )

    assert completed.returncode != 0
    assert "outside the repository" in (completed.stdout + completed.stderr)


def test_baseline_checker_has_closed_scope_and_integrity_guards() -> None:
    source = BASELINE_CHECKER.read_text(encoding="utf-8")

    for marker in (
        "APP_PLAN_BASELINE_ROOT",
        "manifest_sha256",
        "repository_sha256",
        "git-status-z.bin",
        "path-ownership.json",
        "unregistered path",
        "original user content",
        "strict UTF-8",
        "task1-replacements.json",
        "original_line_sha256",
        "current_file_sha256",
        "task1_semantic_replacement",
    ):
        assert marker in source
