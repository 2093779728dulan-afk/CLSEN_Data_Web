"""Verify source CSV files against an existing golden manifest."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_golden_manifest import ManifestError, add_canary_scope, build_manifest


def _file_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ManifestError("Manifest field 'files' must be a list")

    result: dict[str, dict[str, Any]] = {}
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ManifestError("Every manifest file entry must contain a string path")
        path = entry["path"]
        if path in result:
            raise ManifestError(f"Manifest contains a duplicate path: {path}")
        result[path] = entry
    return result


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ManifestError(f"Manifest does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise ManifestError(f"Manifest is not valid JSON: {path}: {error}") from error
    if not isinstance(manifest, dict):
        raise ManifestError("Manifest root must be a JSON object")
    return manifest


def verify_manifest(source_root: Path | str, manifest_path: Path | str) -> list[str]:
    """Return privacy-safe mismatch descriptions; an empty list means success."""

    expected = _load_manifest(Path(manifest_path).resolve())
    actual = build_manifest(source_root)
    mismatches: list[str] = []

    if "approved_scope" in expected:
        try:
            scope = expected["approved_scope"]
            add_canary_scope(
                actual,
                Path(source_root),
                site_id=scope["site_id"],
                start=date.fromisoformat(scope["report_dates"][0]),
                end=date.fromisoformat(scope["report_dates"][-1]),
            )
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise ManifestError("Approved canary scope is invalid") from error
        for field_name in ("approved_scope", "canary_expected"):
            if expected.get(field_name) != actual.get(field_name):
                mismatches.append(f"manifest field changed: {field_name}")

    for field_name in ("schema_version", "tool_version", "summary"):
        if expected.get(field_name) != actual.get(field_name):
            mismatches.append(f"manifest field changed: {field_name}")

    expected_files = _file_map(expected)
    actual_files = _file_map(actual)
    for missing_path in sorted(expected_files.keys() - actual_files.keys()):
        mismatches.append(f"missing file: {missing_path}")
    for added_path in sorted(actual_files.keys() - expected_files.keys()):
        mismatches.append(f"unexpected file: {added_path}")

    for common_path in sorted(expected_files.keys() & actual_files.keys()):
        expected_entry = expected_files[common_path]
        actual_entry = actual_files[common_path]
        for field_name in sorted(set(expected_entry) | set(actual_entry)):
            if expected_entry.get(field_name) != actual_entry.get(field_name):
                mismatches.append(f"{common_path}: {field_name} changed")

    return mismatches


def _create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify Amazon report CSV files against a golden manifest."
    )
    parser.add_argument(
        "--source", required=True, type=Path, help="Root directory of CSV files"
    )
    parser.add_argument(
        "--manifest", required=True, type=Path, help="Manifest JSON path"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _create_argument_parser().parse_args(argv)
    try:
        mismatches = verify_manifest(args.source, args.manifest)
    except (ManifestError, OSError) as error:
        print(f"golden manifest verification failed: {error}", file=sys.stderr)
        return 2

    if mismatches:
        print(
            f"golden manifest mismatch: {len(mismatches)} difference(s)",
            file=sys.stderr,
        )
        for mismatch in mismatches:
            print(f"- {mismatch}", file=sys.stderr)
        return 1

    print("golden manifest verified: source files match the approved baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
