from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.live import product_catalog_live_harness
from tests.live.product_catalog_live_harness import (
    DatabaseIdentity,
    ProcessIdentity,
    RunManifest,
    assert_database_identity,
    assert_empty_seed_target,
    assert_live_playwright_config,
    assert_owned_cleanup_path,
    assert_process_identity,
    validate_database_urls,
    validate_run_id,
)

RUN_ID = "0123456789abcdef0123456789abcdef"
DATABASE = f"clsen_data_test_{RUN_ID[:16]}"


def _url(*, user: str, host: str = "127.0.0.1", database: str = DATABASE) -> str:
    return (
        f"mysql+pymysql://{user}:secret@{host}:33060/{database}"
        "?charset=utf8mb4&ssl_ca=C%3A%5Ctemp%5Cca.pem&ssl_check_hostname=false"
    )


def test_run_id_and_database_urls_fail_closed() -> None:
    assert validate_run_id(RUN_ID) == RUN_ID
    with pytest.raises(ValueError, match="run ID"):
        validate_run_id("../not-owned")
    with pytest.raises(ValueError, match="loopback"):
        validate_database_urls(
            _url(user="migration", host="db.example.test"),
            _url(user="runtime", host="db.example.test"),
            run_id=RUN_ID,
        )
    with pytest.raises(ValueError, match="clsen_data_test"):
        validate_database_urls(
            _url(user="migration", database="clsen_data"),
            _url(user="runtime", database="clsen_data"),
            run_id=RUN_ID,
        )
    with pytest.raises(ValueError, match="separate"):
        validate_database_urls(
            _url(user="shared"),
            _url(user="shared"),
            run_id=RUN_ID,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"database": "ordinary"}, "schema"),
        ({"version": "10.11.6-MariaDB"}, "Oracle MySQL"),
        ({"version_comment": "MariaDB Server"}, "Oracle MySQL"),
        ({"character_set": "latin1"}, "utf8mb4"),
        ({"tls_cipher": ""}, "TLS"),
    ],
)
def test_database_identity_rejects_wrong_server_or_schema(
    overrides: dict[str, str], message: str
) -> None:
    values = {
        "database": DATABASE,
        "version": "8.0.43",
        "version_comment": "MySQL Community Server - GPL",
        "character_set": "utf8mb4",
        "current_user": "migration@%",
        "tls_cipher": "TLS_AES_256_GCM_SHA384",
    }
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        assert_database_identity(
            DatabaseIdentity(**values),
            expected_database=DATABASE,
            expected_user="migration",
        )


def test_seed_target_must_be_empty_and_seed_is_one_shot(tmp_path: Path) -> None:
    assert_empty_seed_target({"users": 0, "facts": 0, "catalog": 0})
    with pytest.raises(ValueError, match="ordinary"):
        assert_empty_seed_target({"users": 1, "facts": 0, "catalog": 0})
    manifest = RunManifest.create(
        run_id=RUN_ID,
        database_name=DATABASE,
        runtime_root=tmp_path / f"clsen-catalog-live-{RUN_ID}",
        storage_root=tmp_path / f"clsen-catalog-live-{RUN_ID}" / "storage",
    )
    manifest.require_state("created")
    with pytest.raises(ValueError, match="state"):
        manifest.require_state("seeded")


def test_cleanup_paths_and_manifest_run_id_cannot_be_forged(tmp_path: Path) -> None:
    runtime_root = tmp_path / f"clsen-catalog-live-{RUN_ID}"
    owned = runtime_root / "storage"
    assert (
        assert_owned_cleanup_path(owned, runtime_root=runtime_root, run_id=RUN_ID)
        == owned.resolve()
    )
    with pytest.raises(ValueError, match="outside"):
        assert_owned_cleanup_path(
            tmp_path / "someone-else", runtime_root=runtime_root, run_id=RUN_ID
        )
    with pytest.raises(ValueError, match="run ID"):
        RunManifest.from_dict(
            {
                "run_id": "fedcba9876543210fedcba9876543210",
                "database_name": DATABASE,
                "runtime_root": str(runtime_root),
                "storage_root": str(owned),
                "state": "created",
            },
            expected_run_id=RUN_ID,
        )


def test_process_identity_rejects_pid_reuse_or_command_change() -> None:
    expected = ProcessIdentity(
        pid=4321,
        started_at=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
        command_sha256="a" * 64,
    )
    assert_process_identity(expected, expected)
    with pytest.raises(ValueError, match="start time"):
        assert_process_identity(
            expected,
            ProcessIdentity(
                pid=4321,
                started_at=expected.started_at + timedelta(seconds=1),
                command_sha256=expected.command_sha256,
            ),
        )
    with pytest.raises(ValueError, match="command"):
        assert_process_identity(
            expected,
            ProcessIdentity(
                pid=4321,
                started_at=expected.started_at,
                command_sha256="b" * 64,
            ),
        )


def test_live_config_cannot_start_or_reuse_servers() -> None:
    assert_live_playwright_config(
        "export default defineConfig({ testDir: './tests/e2e/live' });"
    )
    for unsafe in ("webServer: {}", "reuseExistingServer: true"):
        with pytest.raises(ValueError, match="server"):
            assert_live_playwright_config(f"export default defineConfig({{{unsafe}}});")


def test_seed_cli_enables_catalog_experience_only_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root = tmp_path / f"clsen-catalog-live-{RUN_ID}"
    runtime_root.mkdir()
    manifest_path = runtime_root / "manifest.json"
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_catalog_live_harness,
        "seed",
        lambda **kwargs: calls.append(kwargs),
    )
    base_arguments = [
        "--run-id",
        RUN_ID,
        "--manifest",
        str(manifest_path),
        "seed",
    ]

    assert product_catalog_live_harness.main(base_arguments) == 0
    assert (
        product_catalog_live_harness.main(
            [*base_arguments, "--include-catalog-experience"]
        )
        == 0
    )

    assert [call["include_catalog_experience"] for call in calls] == [False, True]
