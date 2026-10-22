from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from tests.performance import product_catalog_scale_fixture as scale
from tests.performance.product_catalog_scale_fixture import (
    validate_release_evidence_identity,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VERIFIER = REPOSITORY_ROOT / "scripts" / "verify-release-source.ps1"
SHA = "1" * 40


def _identity() -> dict[str, str]:
    return {
        "source_sha": SHA,
        "git_tree": "2" * 40,
        "artifact_digest": "3" * 64,
        "runner_digest": "4" * 64,
    }


def test_release_evidence_requires_all_source_identity_fields() -> None:
    expected = _identity()
    for field in expected:
        evidence = expected.copy()
        evidence.pop(field)
        with pytest.raises(ValueError, match=field):
            validate_release_evidence_identity(evidence, expected)


def test_release_evidence_rejects_every_identity_mismatch() -> None:
    expected = _identity()
    for field, value in expected.items():
        evidence = expected.copy()
        evidence[field] = ("0" if value[0] != "0" else "f") + value[1:]
        with pytest.raises(ValueError, match=field):
            validate_release_evidence_identity(evidence, expected)


def _run_verifier(
    tmp_path: Path, payload: dict[str, object], **overrides: str
) -> subprocess.CompletedProcess[str]:
    payload_path = tmp_path / "runs.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    values = {
        "DispatchRef": "refs/heads/master",
        "WorkflowSha": SHA,
        "SourceSha": SHA,
        "MasterSha": SHA,
        "Repository": "owner/repository",
        "RunsJsonPath": str(payload_path),
    }
    values.update(overrides)
    command = ["pwsh", "-NoProfile", "-File", str(VERIFIER)]
    for name, value in values.items():
        command.extend((f"-{name}", value))
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _valid_run_payload() -> dict[str, object]:
    return {
        "workflow_runs": [
            {
                "id": 7,
                "head_sha": SHA,
                "event": "push",
                "head_branch": "master",
                "status": "completed",
                "conclusion": "success",
                "jobs": [
                    {
                        "name": "master-required",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            }
        ]
    }


def test_release_source_verifier_accepts_one_exact_success(tmp_path: Path) -> None:
    completed = _run_verifier(tmp_path, _valid_run_payload())
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == SHA


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event", "pull_request"),
        ("head_branch", "feature"),
        ("head_sha", "2" * 40),
        ("status", "in_progress"),
        ("conclusion", "failure"),
    ],
)
def test_release_source_verifier_rejects_wrong_run_identity(
    tmp_path: Path, field: str, value: str
) -> None:
    payload = _valid_run_payload()
    payload["workflow_runs"][0][field] = value  # type: ignore[index]
    completed = _run_verifier(tmp_path, payload)
    assert completed.returncode != 0


def test_release_source_verifier_rejects_wrong_dispatch_or_sha(tmp_path: Path) -> None:
    payload = _valid_run_payload()
    assert (
        _run_verifier(tmp_path, payload, DispatchRef="refs/heads/feature").returncode
        != 0
    )
    assert _run_verifier(tmp_path, payload, MasterSha="2" * 40).returncode != 0
    assert _run_verifier(tmp_path, payload, WorkflowSha="2" * 40).returncode != 0


def test_release_source_verifier_rejects_missing_gate_and_ambiguity(
    tmp_path: Path,
) -> None:
    missing_gate = _valid_run_payload()
    missing_gate["workflow_runs"][0]["jobs"] = []  # type: ignore[index]
    assert _run_verifier(tmp_path, missing_gate).returncode != 0

    ambiguous = _valid_run_payload()
    runs = ambiguous["workflow_runs"]
    assert isinstance(runs, list)
    runs.append(dict(runs[0]))
    assert _run_verifier(tmp_path, ambiguous).returncode != 0


@pytest.fixture
def release_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "ci-suite-manifest.json").write_text(
        json.dumps(
            {
                "release_suites": {
                    "performance": {"runner_paths": ["scripts/runner.ps1"]}
                }
            }
        ),
        encoding="utf-8",
    )
    (scripts / "runner.ps1").write_text("# fixture runner\n", encoding="utf-8")
    nested = tmp_path / "opaque-subtree"
    nested.mkdir()
    (nested / "fixture.txt").write_text("synthetic content\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "--", "scripts", "opaque-subtree")
    _git(
        tmp_path,
        "-c",
        "user.name=Release boundary test",
        "-c",
        "user.email=release-boundary@example.invalid",
        "commit",
        "-qm",
        "Synthetic release fixture",
    )
    monkeypatch.setattr(scale, "REPOSITORY_ROOT", tmp_path)
    return tmp_path


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_identity_never_scans_untracked_paths_or_recurses_git_trees(
    release_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = _git(release_checkout, "rev-parse", "HEAD")
    original = subprocess.run

    def bounded_run(
        command: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
        if command[0:2] == ("git", "status"):
            assert command == ("git", "status", "--short", "--untracked-files=no")
        assert command[0:2] != ("git", "ls-tree"), "Do not enumerate Git subtrees"
        return original(command, **kwargs)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr(subprocess, "run", bounded_run)
    identity = scale.release_source_identity(head)
    assert identity["source_sha"] == head


def test_artifact_digest_binds_the_complete_root_tree_without_listing_children(
    release_checkout: Path,
) -> None:
    head = _git(release_checkout, "rev-parse", "HEAD")
    identity = scale.release_source_identity(head)
    root_object = subprocess.run(
        ["git", "cat-file", "tree", identity["git_tree"]],
        cwd=release_checkout,
        check=True,
        capture_output=True,
    ).stdout
    assert identity["artifact_digest"] == hashlib.sha256(root_object).hexdigest()


def test_untracked_file_is_not_inspected_as_release_source(
    release_checkout: Path,
) -> None:
    head = _git(release_checkout, "rev-parse", "HEAD")
    before = scale.release_source_identity(head)
    (release_checkout / "untracked-fixture.txt").write_text(
        "not a release input\n", encoding="utf-8"
    )
    assert scale.release_source_identity(head) == before


def test_nested_tracked_change_changes_artifact_identity(
    release_checkout: Path,
) -> None:
    head = _git(release_checkout, "rev-parse", "HEAD")
    before = scale.release_source_identity(head)
    (release_checkout / "opaque-subtree/fixture.txt").write_text(
        "changed synthetic content\n", encoding="utf-8"
    )
    _git(release_checkout, "add", "--", "opaque-subtree/fixture.txt")
    _git(
        release_checkout,
        "-c",
        "user.name=Release boundary test",
        "-c",
        "user.email=release-boundary@example.invalid",
        "commit",
        "-qm",
        "Change nested fixture",
    )
    after = scale.release_source_identity(_git(release_checkout, "rev-parse", "HEAD"))
    assert before["git_tree"] != after["git_tree"]
    assert before["artifact_digest"] != after["artifact_digest"]
    assert before["runner_digest"] == after["runner_digest"]


@pytest.mark.parametrize("staged", [False, True])
def test_tracked_changes_still_block_release_identity(
    release_checkout: Path, staged: bool
) -> None:
    head = _git(release_checkout, "rev-parse", "HEAD")
    (release_checkout / "scripts/runner.ps1").write_text(
        "# changed fixture runner\n", encoding="utf-8"
    )
    if staged:
        _git(release_checkout, "add", "--", "scripts/runner.ps1")
    with pytest.raises(ValueError, match="tracked changes"):
        scale.release_source_identity(head)


def test_source_sha_must_still_equal_checkout_head(release_checkout: Path) -> None:
    with pytest.raises(ValueError, match="does not match checkout HEAD"):
        scale.release_source_identity("0" * 40)


def test_workspace_preflight_excludes_untracked_paths() -> None:
    profile = (REPOSITORY_ROOT / "scripts/run-ci-profile.ps1").read_text(
        encoding="utf-8"
    )
    assert "git status --short --untracked-files=no" in profile
    assert "git status --porcelain" not in profile
