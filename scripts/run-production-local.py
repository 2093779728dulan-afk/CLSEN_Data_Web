"""Start the isolated B demo with private task-owned configuration."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(
    r"D:\CLSEN_DeploymentPrep_20260914\development-v1.1.0-mvp-20261010\implementation-20261012\runtime"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["migrate", "java", "python", "frontend"])
    args = parser.parse_args()
    configuration = json.loads(
        (RUNTIME / "environment.json").read_text(encoding="utf-8")
    )
    prefix = (
        "PRODUCTION_"
        if args.service in {"java", "migrate"}
        else "APP_"
        if args.service == "python"
        else "VITE_"
    )
    env = os.environ | {
        key: value
        for key, value in configuration.items()
        if key.startswith(prefix)
        or (args.service == "frontend" and key == "CATALOG_LIVE_API_URL")
    }
    if args.service in {"java", "migrate"}:
        command = [
            r"D:\Program Files\Java\jdk-21.0.11\bin\java.exe",
            "-jar",
            str(ROOT / "backend-java/target/dataweb-production-1.1.0-SNAPSHOT.jar"),
        ]
        if args.service == "migrate":
            command.append("--migrate")
        else:
            env.pop("PRODUCTION_MIGRATION_PASSWORD", None)
            env.pop("PRODUCTION_MIGRATION_USER", None)
        cwd = ROOT / "backend-java"
    elif args.service == "python":
        env["APP_CORS_ALLOWED_ORIGINS"] = "http://127.0.0.1:23010"
        env["APP_PRODUCTION_INVENTORY_REVIEW_WRITES_ENABLED"] = (
            configuration.get("APP_PRODUCTION_INVENTORY_REVIEW_WRITES_ENABLED", "false")
            if configuration.get("APP_PRODUCTION_INVENTORY_SOURCE_ROOT")
            else "false"
        )
        command = [
            r"D:\CLSEN_Data_Web\.venv\Scripts\python.exe",
            "-X",
            "utf8",
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "23012",
        ]
        cwd = ROOT / "backend"
    else:
        command = [
            "node",
            "node_modules/vite/bin/vite.js",
            "--host",
            "127.0.0.1",
            "--port",
            "23010",
            "--strictPort",
        ]
        cwd = ROOT / "frontend"
    result = subprocess.run(command, cwd=cwd, env=env, check=False)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
