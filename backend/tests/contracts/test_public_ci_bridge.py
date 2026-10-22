from __future__ import annotations

import copy
import importlib.util
import io
import json
import subprocess
import urllib.error
from email.message import Message
from itertools import product
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_public_ci.py"


def bridge() -> Any:
    spec = importlib.util.spec_from_file_location("public_ci_bridge", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_payload(module: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    files = {"backend/example.py": "a" * 40, ".env.example": "b" * 40}
    manifest = {
        "schema_version": 1,
        "source_repository": module.PRIVATE_REPOSITORY,
        "publication_repository": module.PUBLIC_REPOSITORY,
        "source_sha": "1" * 40,
        "source_tree": "2" * 40,
        "history_exported": False,
        "files": [{"path": path, "git_blob": sha} for path, sha in files.items()],
    }
    tree = {
        path: {"type": "blob", "mode": "100644", "sha": sha}
        for path, sha in (files | module.ADAPTER_BLOBS).items()
    }
    tree["public-ci-source.json"] = {"type": "blob", "mode": "100644", "sha": "c" * 40}
    return manifest, tree


def test_mapping_accepts_only_complete_independently_derived_source() -> None:
    module = bridge()
    manifest, tree = fixture_payload(module)
    expected = {item["path"]: item["git_blob"] for item in manifest["files"]}
    assert module.validate_mapping("1" * 40, "2" * 40, expected, manifest, tree) == (
        "1" * 40
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "extra",
        "changed",
        "workflow",
        "injection",
        "repository",
        "tree",
        "history",
        "symlink",
        "source",
    ],
)
def test_mapping_rejects_untrusted_or_incomplete_publication(change: str) -> None:
    module = bridge()
    manifest, tree = fixture_payload(module)
    expected = {item["path"]: item["git_blob"] for item in manifest["files"]}
    if change == "missing":
        manifest["files"].pop()
    elif change == "duplicate":
        manifest["files"].append(manifest["files"][0])
    elif change == "extra":
        manifest["files"].append({"path": "other.py", "git_blob": "d" * 40})
    elif change == "changed":
        tree["backend/example.py"]["sha"] = "d" * 40
    elif change == "workflow":
        tree[".github/workflows/public-ci.yml"]["sha"] = "d" * 40
    elif change == "injection":
        tree[".github/workflows/other.yml"] = copy.deepcopy(tree[".env.example"])
    elif change == "repository":
        manifest["source_repository"] = "other/repo"
    elif change == "tree":
        manifest["source_tree"] = "d" * 40
    elif change == "history":
        manifest["history_exported"] = True
    elif change == "symlink":
        tree["backend/example.py"]["mode"] = "120000"
    elif change == "source":
        manifest["source_sha"] = "d" * 40
    with pytest.raises(ValueError):
        module.validate_mapping("1" * 40, "2" * 40, expected, manifest, tree)


def run_payload(module: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run = {
        "id": 42,
        "run_attempt": 1,
        "head_sha": "3" * 40,
        "head_repository": {"full_name": module.PUBLIC_REPOSITORY},
        "path": ".github/workflows/public-ci.yml",
        "event": "push",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
    }
    jobs: list[dict[str, Any]] = []
    for name, (label, required_steps) in module.REQUIRED_JOBS.items():
        jobs.append(
            {
                "id": len(jobs) + 1,
                "name": name,
                "run_id": 42,
                "run_attempt": 1,
                "head_sha": "3" * 40,
                "status": "completed",
                "conclusion": "success",
                "labels": [label],
                "steps": [
                    {"name": step, "status": "completed", "conclusion": "success"}
                    for step in required_steps
                ],
            }
        )
    return run, jobs


def test_all_full_profiles_and_cleanup_are_required() -> None:
    module = bridge()
    run, jobs = run_payload(module)
    module.validate_run(run, jobs)
    assert len(jobs) == 16
    assert {
        f"Frontend {gate} shard {shard}/4 / Node 24 / pnpm 11"
        for gate in ("a11y", "visual")
        for shard in range(1, 5)
    } <= {job["name"] for job in jobs}


def test_profile_contracts_describe_the_exact_pinned_executable_public_workflow() -> (
    None
):
    module = bridge()
    blob = subprocess.check_output(
        ["git", "hash-object", "scripts/public-ci-workflow.yml"], cwd=ROOT, text=True
    ).strip()
    assert blob == module.ADAPTER_BLOBS[".github/workflows/public-ci.yml"]
    workflow = yaml.load(
        (ROOT / "scripts/public-ci-workflow.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    expanded = {}
    for job in workflow["jobs"].values():
        matrix = job.get("strategy", {}).get("matrix", {})
        for values in product(*matrix.values()):
            name = job["name"]
            for key, value in zip(matrix, values, strict=True):
                name = name.replace("${{ matrix." + key + " }}", value)
            expanded[name] = job
    assert set(expanded) == set(module.REQUIRED_JOBS)
    for name, (label, steps) in module.REQUIRED_JOBS.items():
        job = expanded[name]
        assert job["runs-on"] == label
        names = {step.get("name") for step in job["steps"]}
        assert set(steps) - {"Set up job", "Complete job"} <= names


@pytest.mark.parametrize(
    "change",
    [
        "cleanup",
        "profile",
        "summary",
        "missing",
        "duplicate",
        "hosted",
        "attempt",
        "sha",
        "event",
        "pending",
        "repository",
        "workflow",
    ],
)
def test_job_or_run_mismatch_cannot_turn_into_green(change: str) -> None:
    module = bridge()
    run, jobs = run_payload(module)
    mysql = next(job for job in jobs if job["name"].startswith("MySQL"))
    if change == "cleanup":
        next(step for step in mysql["steps"] if "Clean this job" in step["name"])[
            "conclusion"
        ] = "failure"
    elif change == "profile":
        mysql["steps"] = [
            step for step in mysql["steps"] if "profile" not in step["name"]
        ]
    elif change == "summary":
        jobs[-1]["conclusion"] = "skipped"
    elif change == "missing":
        jobs.pop()
    elif change == "duplicate":
        jobs.append(jobs[0])
    elif change == "hosted":
        mysql["labels"].append("self-hosted")
    elif change == "attempt":
        mysql["run_attempt"] = 2
    elif change == "sha":
        mysql["head_sha"] = "4" * 40
    elif change == "event":
        run["event"] = "pull_request"
    elif change == "pending":
        mysql["status"] = "in_progress"
    elif change == "repository":
        run["head_repository"]["full_name"] = "other/repo"
    elif change == "workflow":
        run["path"] = ".github/workflows/other.yml"
    with pytest.raises(ValueError):
        module.validate_run(run, jobs)


def test_private_workflow_only_checks_public_evidence_and_keeps_stable_gates() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/compatibility.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["jobs"]) == {
        "public-evidence",
        "pr-required",
        "master-required",
    }
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    execution = workflow["jobs"]["public-evidence"]
    assert execution["runs-on"] == ["self-hosted", "Linux", "X64", "clsen-rag-ov"]
    assert execution["timeout-minutes"] == "145"
    source = json.dumps(execution)
    assert "verify_public_ci.py" in source
    assert "github.event.pull_request.head.sha || github.sha" in source
    assert "pip install" not in source and "run-ci-profile.ps1" not in source
    assert "secrets.GITHUB_TOKEN" in source
    assert "--wait-seconds 8400" in source
    for name in ("pr-required", "master-required"):
        assert workflow["jobs"][name]["needs"] == ["public-evidence"]


def test_source_selection_is_whitelisted_and_never_enumerates_root_data(
    tmp_path: Path,
) -> None:
    module = bridge()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend/example.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("CHANGE_ME\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "backend", ".env.example"], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "synthetic source",
        ],
        check=True,
    )
    sha = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    tree, files = module.source_files(tmp_path, sha)
    assert len(tree) == 40 and set(files) == {"backend/example.py", ".env.example"}
    for path in (
        "backend/.env",
        "ops/secrets/key.txt",
        "frontend/node_modules/a",
        "backend/private/a",
    ):
        assert not module.safe_path(path)
    assert "data" not in module.SOURCE_ROOTS


def test_merge_reuse_requires_identical_full_tree_and_direct_tested_parent(
    tmp_path: Path,
) -> None:
    module = bridge()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    def command(*args: str, input_text: str = "") -> str:
        return subprocess.check_output(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                *args,
            ],
            input=input_text,
            text=True,
        ).strip()

    tree = command("mktree", input_text="")
    base = command("commit-tree", tree, "-m", "base")
    tested = command("commit-tree", tree, "-p", base, "-m", "tested")
    merged = command("commit-tree", tree, "-p", base, "-p", tested, "-m", "merge")
    manifest, public_tree = fixture_payload(module)
    expected = {item["path"]: item["git_blob"] for item in manifest["files"]}
    manifest.update(source_sha=tested, source_tree=tree)
    assert (
        module.validate_mapping(
            merged,
            tree,
            expected,
            manifest,
            public_tree,
            root=tmp_path,
            allow_merge_tree=True,
        )
        == tested
    )
    with pytest.raises(ValueError):
        module.validate_mapping(merged, tree, expected, manifest, public_tree)
    with pytest.raises(ValueError):
        module.validate_mapping(
            merged,
            "d" * 40,
            expected,
            manifest,
            public_tree,
            root=tmp_path,
            allow_merge_tree=True,
        )
    unrelated = command("commit-tree", tree, "-m", "unrelated")
    manifest["source_sha"] = unrelated
    with pytest.raises(ValueError):
        module.validate_mapping(
            merged,
            tree,
            expected,
            manifest,
            public_tree,
            root=tmp_path,
            allow_merge_tree=True,
        )


@pytest.mark.parametrize("change", ["none", "pending", "failed", "incomplete-jobs"])
def test_read_only_api_flow_never_dispatches_or_mixes_results(
    tmp_path: Path, change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = bridge()
    manifest, tree = fixture_payload(module)
    expected = {item["path"]: item["git_blob"] for item in manifest["files"]}
    run, jobs = run_payload(module)
    monkeypatch.setattr(module, "source_files", lambda *_: ("2" * 40, expected))
    if change == "pending":
        run["status"] = "in_progress"
    if change == "failed":
        run["conclusion"] = "failure"

    class ReadOnlyApi:
        def get(self, path: str) -> dict[str, Any]:
            if path.startswith("actions/workflows/"):
                return {"workflow_runs": [run]}
            assert path == "actions/runs/42/attempts/1/jobs?per_page=100"
            return {
                "total_count": len(jobs) + (change == "incomplete-jobs"),
                "jobs": jobs,
            }

        def publication(self, head: str) -> tuple[dict[str, Any], dict[str, Any]]:
            assert head == "3" * 40
            return manifest, tree

    if change in {"failed", "incomplete-jobs"}:
        with pytest.raises(ValueError):
            module.find_evidence(ReadOnlyApi(), tmp_path, "1" * 40, "pull_request")
    else:
        evidence = module.find_evidence(
            ReadOnlyApi(), tmp_path, "1" * 40, "pull_request"
        )
        if change == "pending":
            assert evidence is None
        else:
            assert evidence["public_run_id"] == 42
            assert evidence["verified_files"] == 2


@pytest.mark.parametrize("failure", ["http503", "timeout", "rate-limit"])
def test_api_retries_only_temporary_get_failures(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = bridge()
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-token")
    calls: list[object] = []
    sleeps: list[int] = []
    headers = Message()
    headers["X-RateLimit-Remaining"] = "0"

    def open_request(request: object, *, timeout: int) -> io.BytesIO:
        calls.append(request)
        assert timeout == 30
        if len(calls) == 1:
            if failure == "timeout":
                raise urllib.error.URLError(TimeoutError("private transport detail"))
            raise urllib.error.HTTPError(
                "https://example.invalid",
                403 if failure == "rate-limit" else 503,
                "private response detail",
                headers,
                None,
            )
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(module.urllib.request, "urlopen", open_request)
    monkeypatch.setattr(module.time, "sleep", sleeps.append)
    assert module.PublicApi(False).get("actions/runs") == {"ok": True}
    assert len(calls) == 2
    assert sleeps == [5]


@pytest.mark.parametrize("status", [401, 403, 404, 503])
def test_api_failure_is_bounded_diagnostic_and_does_not_expose_response(
    status: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = bridge()
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-token")
    calls: list[object] = []
    sleeps: list[int] = []

    def open_request(request: object, *, timeout: int) -> io.BytesIO:
        calls.append(request)
        raise urllib.error.HTTPError(
            "https://example.invalid/private",
            status,
            "private response detail",
            Message(),
            None,
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", open_request)
    monkeypatch.setattr(module.time, "sleep", sleeps.append)
    with pytest.raises(ValueError, match=f"HTTP {status}") as error:
        module.PublicApi(False).get("actions/runs")
    assert len(calls) == (3 if status == 503 else 1)
    assert sleeps == ([5, 10] if status == 503 else [])
    output = str(error.value) + capsys.readouterr().out
    assert "private" not in output and "synthetic-token" not in output


def test_api_does_not_retry_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    module = bridge()
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-token")
    calls: list[object] = []

    def open_request(request: object, *, timeout: int) -> io.BytesIO:
        calls.append(request)
        return io.BytesIO(b'{"ok":true,"ok":false}')

    monkeypatch.setattr(module.urllib.request, "urlopen", open_request)
    with pytest.raises(ValueError, match="Duplicate JSON object key"):
        module.PublicApi(False).get("actions/runs")
    assert len(calls) == 1
