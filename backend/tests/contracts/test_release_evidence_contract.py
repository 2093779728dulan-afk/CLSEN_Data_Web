from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
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
