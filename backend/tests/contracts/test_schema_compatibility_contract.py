from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPOSITORY_ROOT / "scripts/schema-compatibility-entrypoints.json"
EXPECTED_IDENTITIES = {
    "dev-api",
    "direct-api",
    "container-api",
    "demo-api",
    "live-api",
    "dev-worker",
    "direct-worker",
    "container-worker",
    "live-worker",
}


def _manifest() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(MANIFEST.read_text(encoding="utf-8")))


def test_manifest_has_exact_stage0_identity_coverage_and_resolvable_tokens() -> None:
    manifest = _manifest()
    assert set(manifest) == {"schema_version", "entries"}
    assert manifest["schema_version"] == 1
    entries = manifest["entries"]
    assert len(entries) == 9
    assert {entry["id"] for entry in entries} == EXPECTED_IDENTITIES
    assert len({entry["id"] for entry in entries}) == len(entries)
    for entry in entries:
        assert set(entry) == {
            "id",
            "kind",
            "source_path",
            "pre_process_guard",
            "in_process_defense",
            "failure_boundary",
        }
        assert entry["kind"] in {"api", "worker"}
        path = Path(entry["source_path"])
        assert not path.is_absolute() and ".." not in path.parts
        source_path = REPOSITORY_ROOT / path
        assert source_path.is_file()
        source = source_path.read_text(encoding="utf-8")
        guard = entry["pre_process_guard"]
        if guard is not None:
            assert guard in source
        assert entry["in_process_defense"] in source
        assert isinstance(entry["failure_boundary"], str)
        assert entry["failure_boundary"].strip()


def test_runtime_guard_has_no_bypass_or_automatic_migration_path() -> None:
    runtime_paths = (
        "backend/app/main.py",
        "backend/app/schema_preflight.py",
        "backend/app/worker/cli.py",
    )
    source = "\n".join(
        (REPOSITORY_ROOT / path).read_text(encoding="utf-8") for path in runtime_paths
    )
    for forbidden in (
        "skip_schema_check",
        "schema_check_bypass",
        "allow_schema_mismatch",
        "command.upgrade",
        "alembic.command",
        "BACKUP_READER_SCHEMA_REVISIONS",
    ):
        assert forbidden not in source


def test_guard_query_is_one_unbounded_read_and_events_are_closed() -> None:
    guard = (
        REPOSITORY_ROOT / "backend/app/maintenance/schema_compatibility.py"
    ).read_text(encoding="utf-8")
    preflight = (REPOSITORY_ROOT / "backend/app/schema_preflight.py").read_text(
        encoding="utf-8"
    )

    assert guard.count('"SELECT version_num FROM alembic_version"') == 1
    assert "LIMIT 1" not in guard
    for forbidden in ("INSERT INTO", "UPDATE alembic", "DELETE FROM", "CREATE TABLE"):
        assert forbidden not in guard
    assert "safe_url" in preflight
    assert "hide_password=False" not in preflight


def test_compose_default_runtime_cannot_schedule_migrate() -> None:
    compose = yaml.safe_load(
        (REPOSITORY_ROOT / "ops/docker-compose.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    assert services["migrate"]["profiles"] == ["operations"]
    for role in ("backend", "worker"):
        assert "migrate" not in services[role]["depends_on"]


def test_supported_script_guards_precede_process_boundaries() -> None:
    sources = {
        path: (REPOSITORY_ROOT / path).read_text(encoding="utf-8")
        for path in (
            "scripts/dev-backend.ps1",
            "scripts/run-worker.ps1",
            "scripts/start-stage9-demo.ps1",
        )
    }
    assert sources["scripts/dev-backend.ps1"].index("app.schema_preflight") < sources[
        "scripts/dev-backend.ps1"
    ].index("@uvicornArguments")
    assert sources["scripts/run-worker.ps1"].index("@preflightArguments") < sources[
        "scripts/run-worker.ps1"
    ].index("CLSEN worker ready.")
    assert sources["scripts/start-stage9-demo.ps1"].index(
        "app.schema_preflight"
    ) < sources["scripts/start-stage9-demo.ps1"].index("-m uvicorn")
