"""Read-only, fail-closed bridge from a private Git source to public Actions CI.

Only explicitly publishable Git paths are enumerated. Public manifests are claims:
the private tree, the public tree and the actual jobs independently prove them.
No cross-repository write token, deployment access or installed package is needed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PRIVATE_REPOSITORY = "dulanjy/CLSEN_Data_Web"
PUBLIC_REPOSITORY = "2093779728dulan-afk/CLSEN_Data_Web"
SOURCE_ROOTS = (
    ".github",
    "backend",
    "frontend",
    "scripts",
    "docs",
    "ops",
    "tools",
    ".gitignore",
    ".gitattributes",
    ".dockerignore",
    ".env.example",
)
# Reviewed public-only adapters, not trusted merely because a manifest lists them.
ADAPTER_BLOBS = {
    ".github/workflows/public-ci.yml": "af6790d0a87ec988a0304c6a4a6a134cec347a6e",
    "scripts/prepare-public-ci.ps1": "af5eafbe62cd333eaa3cec498eb2733599a319d3",
    "backend/tests/contracts/test_public_ci_workflow.py": (
        "9b699444756794bcd5aaea24275eb7521a4898f9"
    ),
    "README.md": "97f10f2636661c8c73a45cd085acf733ec42f503",
}
_COMMON = (
    "Set up job",
    "Verify source and prepare reference contracts",
    "Complete job",
)
REQUIRED_JOBS = {
    "Ubuntu full / Python 3.14": (
        "ubuntu-24.04",
        (*_COMMON, "Run complete Ubuntu profile"),
    ),
    "Windows smoke / Python 3.14": (
        "windows-2025",
        (*_COMMON, "Run complete Windows profile"),
    ),
    "Frontend full / Node 24 / pnpm 11": (
        "ubuntu-24.04",
        (*_COMMON, "Run complete frontend profile"),
    ),
    "MySQL 8.4 compatibility / Python 3.14": (
        "ubuntu-24.04",
        (
            *_COMMON,
            "Run complete MySQL 8.4 profile",
            "Clean this job's disposable MySQL container",
        ),
    ),
    "public-required": (
        "ubuntu-24.04",
        ("Set up job", "Require every public profile", "Complete job"),
    ),
}
SHA = re.compile(r"[0-9a-f]{40}\Z")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    require(result.returncode == 0, "Private source Git lookup failed")
    return result.stdout.decode("utf-8").strip()


def safe_path(path: str) -> bool:
    # Same explicit publication selection as the existing one-way exporter.
    if path.split("/", 1)[0] not in SOURCE_ROOTS:
        return False
    if re.search(
        r"(^|/)(private|secrets|node_modules|data|mysql-data|\.venv)/",
        path,
        re.IGNORECASE,
    ) and not path.startswith("backend/app/catalog/data/ucd_15_1/"):
        return False
    if path != ".env.example" and re.search(r"(^|/)\.env(?:\.|$)", path, re.IGNORECASE):
        return False
    return not re.search(
        r"(?:^|/)(?:backup-keyring|credentials|id_rsa|id_ed25519)(?:\.|$)|\.(?:pem|pfx|p12|key)$",
        path,
        re.IGNORECASE,
    )


def source_files(root: Path, sha: str) -> tuple[str, dict[str, str]]:
    require(SHA.fullmatch(sha) is not None, "Expected a full private source SHA")
    tree = git(root, "rev-parse", f"{sha}^{{tree}}")
    # Never run a repository-wide recursive tree scan (in particular root data/).
    entries = git(root, "ls-tree", "-rz", sha, "--", *SOURCE_ROOTS)
    files: dict[str, str] = {}
    for entry in entries.split("\0"):
        if not entry:
            continue
        metadata, path = entry.split("\t", 1)
        mode, kind, blob = metadata.split()
        if safe_path(path):
            require(
                kind == "blob" and mode in {"100644", "100755"}, "Non-file source entry"
            )
            files[path] = blob
    require(bool(files), "Empty publication selection")
    return tree, files


def stored_path(path: str) -> str:
    if path.startswith(".github/workflows/"):
        return path.replace(
            ".github/workflows/", ".github/private-workflow-reference/", 1
        )
    return path


def validate_mapping(
    source_sha: str,
    source_tree: str,
    expected: dict[str, str],
    manifest: dict[str, Any],
    public_tree: dict[str, Any],
    *,
    root: Path | None = None,
    allow_merge_tree: bool = False,
) -> str:
    require(manifest.get("schema_version") == 1, "Unknown publication schema")
    require(
        manifest.get("source_repository") == PRIVATE_REPOSITORY,
        "Wrong private repository",
    )
    require(
        manifest.get("publication_repository") == PUBLIC_REPOSITORY,
        "Wrong public repository",
    )
    require(manifest.get("history_exported") is False, "Unexpected history export")
    tested_sha = str(manifest.get("source_sha", ""))
    require(SHA.fullmatch(tested_sha) is not None, "Malformed tested source SHA")
    require(manifest.get("source_tree") == source_tree, "Private source tree differs")
    if tested_sha != source_sha:
        require(allow_merge_tree and root is not None, "Private source SHA differs")
        assert root is not None
        require(
            git(root, "rev-parse", f"{tested_sha}^{{tree}}") == source_tree,
            "Tested ancestor tree differs",
        )
        require(
            tested_sha in git(root, "show", "-s", "--format=%P", source_sha).split(),
            "Tree reuse requires the tested source to be a direct merge parent",
        )
        require(
            len(git(root, "show", "-s", "--format=%P", source_sha).split()) == 2,
            "Tree reuse requires an unchanged two-parent merge",
        )
    files = manifest.get("files")
    require(isinstance(files, list), "Missing source file list")
    assert isinstance(files, list)
    recorded: dict[str, str] = {}
    for entry in files:
        path, blob = entry.get("path"), entry.get("git_blob")
        require(
            isinstance(path, str) and path not in recorded,
            "Duplicate or invalid source path",
        )
        recorded[path] = blob
    require(recorded == expected, "Source path set or canonical blobs differ")
    published = {stored_path(path): blob for path, blob in expected.items()}
    require(not (set(published) & set(ADAPTER_BLOBS)), "Source overlaps public adapter")
    published.update(ADAPTER_BLOBS)
    require(
        set(public_tree) == set(published) | {"public-ci-source.json"},
        "Unexpected or missing public files",
    )
    for path, entry in public_tree.items():
        require(
            entry.get("type") == "blob" and entry.get("mode") in {"100644", "100755"},
            "Unsafe public entry",
        )
        if path != "public-ci-source.json":
            require(
                entry.get("sha") == published[path],
                f"Public canonical blob differs: {path}",
            )
    return tested_sha


def validate_run(run: dict[str, Any], jobs: list[dict[str, Any]]) -> None:
    require(
        run.get("head_repository", {}).get("full_name") == PUBLIC_REPOSITORY,
        "Wrong run repository",
    )
    require(
        run.get("path") == ".github/workflows/public-ci.yml", "Wrong public workflow"
    )
    require(
        run.get("event") == "push" and run.get("head_branch") == "main",
        "Wrong run event or branch",
    )
    require(
        run.get("status") == "completed" and run.get("conclusion") == "success",
        "Public run is not successful",
    )
    require(
        SHA.fullmatch(str(run.get("head_sha", ""))) is not None, "Malformed public head"
    )
    require(isinstance(run.get("id"), int) and run["id"] > 0, "Invalid public run id")
    require(
        isinstance(run.get("run_attempt"), int) and run["run_attempt"] > 0,
        "Invalid run attempt",
    )
    require(
        len(jobs) == len(REQUIRED_JOBS)
        and {job.get("name") for job in jobs} == set(REQUIRED_JOBS),
        "Incomplete or duplicate public jobs",
    )
    for job in jobs:
        require(
            all(job.get(key) == run[key] for key in ("head_sha", "run_attempt")),
            "Job source/attempt differs",
        )
        require(job.get("run_id") == run["id"], "Job belongs to another run")
        require(
            job.get("status") == "completed" and job.get("conclusion") == "success",
            "Public job not successful",
        )
        label, required_steps = REQUIRED_JOBS[job["name"]]
        require(
            job.get("labels") == [label],
            "Public job is not on the approved hosted label",
        )
        steps = job.get("steps", [])
        require(
            not any(
                step.get("conclusion")
                in {"failure", "cancelled", "timed_out", "action_required"}
                for step in steps
            ),
            "Public job has a failed step",
        )
        for name in required_steps:
            matching = [step for step in steps if step.get("name") == name]
            require(
                len(matching) == 1
                and matching[0].get("status") == "completed"
                and matching[0].get("conclusion") == "success",
                f"Required public step not successful: {name}",
            )


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON object key")
        result[key] = value
    return result


class PublicApi:
    def __init__(self, use_gh: bool) -> None:
        self.use_gh = use_gh
        self.cache: dict[str, Any] = {}

    def get(self, path: str, *, immutable: bool = False) -> Any:
        if immutable and path in self.cache:
            return self.cache[path]
        endpoint = f"repos/{PUBLIC_REPOSITORY}/{path}"
        if self.use_gh:
            result = subprocess.run(
                ["gh", "api", endpoint], capture_output=True, check=False
            )
            require(result.returncode == 0, "Public GitHub API request failed (gh)")
            data = result.stdout
        else:
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            token = os.environ.get("GITHUB_TOKEN")
            require(bool(token), "Read-only GITHUB_TOKEN is required")
            headers["Authorization"] = f"Bearer {token}"
            request = urllib.request.Request(
                f"https://api.github.com/{endpoint}", headers=headers
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = response.read()
            except (OSError, urllib.error.URLError) as error:
                raise ValueError("Public GitHub API request failed") from error
        payload = json.loads(data, object_pairs_hook=strict_object)
        if immutable:
            self.cache[path] = payload
        return payload

    def publication(self, head: str) -> tuple[dict[str, Any], dict[str, Any]]:
        require(SHA.fullmatch(head) is not None, "Invalid public head")
        payload = self.get(f"git/trees/{head}?recursive=1", immutable=True)
        require(
            payload.get("truncated") is False, "Public Git tree response is truncated"
        )
        entries = [entry for entry in payload["tree"] if entry.get("type") != "tree"]
        tree = {entry["path"]: entry for entry in entries}
        require(len(tree) == len(entries), "Duplicate public Git paths")
        require("public-ci-source.json" in tree, "Missing public source manifest")
        blob_sha = tree["public-ci-source.json"]["sha"]
        blob = self.get(f"git/blobs/{blob_sha}", immutable=True)
        require(blob.get("encoding") == "base64", "Unexpected manifest encoding")
        content = base64.b64decode(blob["content"])
        digest = hashlib.sha1(
            b"blob " + str(len(content)).encode() + b"\0" + content
        ).hexdigest()
        require(digest == blob_sha, "Manifest Git blob integrity failed")
        manifest = json.loads(content, object_pairs_hook=strict_object)
        return manifest, tree


def find_evidence(
    api: PublicApi, root: Path, sha: str, event: str
) -> dict[str, Any] | None:
    source_tree, expected = source_files(root, sha)
    payload = api.get(
        "actions/workflows/public-ci.yml/runs?branch=main&event=push&per_page=100"
    )
    require(
        isinstance(payload.get("workflow_runs"), list), "Incomplete public run response"
    )
    for run in payload["workflow_runs"]:
        manifest, public_tree = api.publication(run["head_sha"])
        exact = manifest.get("source_sha") == sha
        equivalent = event == "push" and manifest.get("source_tree") == source_tree
        if not (exact or equivalent):
            continue
        tested_sha = validate_mapping(
            sha,
            source_tree,
            expected,
            manifest,
            public_tree,
            root=root,
            allow_merge_tree=event == "push",
        )
        if run.get("status") != "completed":
            return None
        jobs_payload = api.get(
            f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100"
        )
        jobs = jobs_payload.get("jobs", [])
        require(
            jobs_payload.get("total_count") == len(jobs),
            "Incomplete public job response",
        )
        validate_run(run, jobs)
        return {
            "private_source_sha": sha,
            "private_source_tree": source_tree,
            "tested_private_sha": tested_sha,
            "tree_equivalent_merge": tested_sha != sha,
            "public_head_sha": run["head_sha"],
            "public_run_id": run["id"],
            "public_run_attempt": run["run_attempt"],
            "public_run_url": f"https://github.com/{PUBLIC_REPOSITORY}/actions/runs/{run['id']}",
            "jobs": {job["name"]: job["id"] for job in jobs},
            "verified_files": len(expected),
        }
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--event", choices=("push", "pull_request"), required=True)
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument(
        "--gh",
        action="store_true",
        help="Use the existing logged-in gh for local verification",
    )
    args = parser.parse_args()
    require(0 <= args.wait_seconds <= 2400, "Invalid evidence wait budget")
    root = Path(__file__).resolve().parents[1]
    require(
        git(root, "rev-parse", "HEAD") == args.source_sha,
        "Checkout differs from requested private source",
    )
    deadline = time.monotonic() + args.wait_seconds
    api = PublicApi(args.gh)
    while True:
        evidence = find_evidence(api, root, args.source_sha, args.event)
        if evidence is not None:
            text = json.dumps(evidence, ensure_ascii=True, indent=2)
            print(text)
            summary = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary:
                with Path(summary).open("a", encoding="utf-8") as stream:
                    stream.write(
                        f"## Verified public CI evidence\n\n```json\n{text}\n```\n"
                    )
            return 0
        require(
            time.monotonic() < deadline,
            "No completed public CI evidence for this private source; "
            "gate remains closed",
        )
        print(
            "Waiting for the matching public source snapshot/CI (no run is dispatched)",
            flush=True,
        )
        time.sleep(min(30, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError) as failure:
        print(f"Public CI provenance rejected: {failure}", file=sys.stderr)
        sys.exit(1)
