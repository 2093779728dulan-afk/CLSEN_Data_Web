"""Quiesced B backup: both databases and source files, using the existing cipher."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, BinaryIO, cast
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from app.deployment.entrypoint import build_database_url
from app.deployment.production import database_pair, read_secret
from app.maintenance.backup import (
    decrypt_file,
    encrypt_file,
    load_keyring,
    verify_encrypted_file,
)


def fingerprint(connection: Connection, database: str) -> dict[str, dict[str, int]]:
    tables = connection.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema=:database AND table_type='BASE TABLE' "
            "ORDER BY table_name"
        ),
        {"database": database},
    ).scalars()
    result = {}
    for table in tables:
        if not table.replace("_", "").isalnum():
            raise ValueError("Unexpected table identifier")
        count = connection.execute(
            text(f"SELECT COUNT(*) FROM `{database}`.`{table}`")
        ).scalar_one()
        checksum = connection.execute(
            text(f"CHECKSUM TABLE `{database}`.`{table}` EXTENDED")
        ).one()[1]
        if checksum is None:
            raise ValueError("A table cannot be verified")
        result[table] = {"rows": count, "checksum": int(checksum)}
    return result


def connection_settings(role: str, database: str) -> tuple[str, str, str, str, str]:
    password = read_secret(
        "mysql_root_password" if role == "root" else "production_backup_password"
    )
    host = os.getenv("APP_DEPLOYMENT_MYSQL_HOST", "mysql")
    ca = os.getenv("APP_DEPLOYMENT_MYSQL_CA", "/run/secrets/mysql_ca_certificate")
    user = "root" if role == "root" else "clsen_production_backup"
    url = build_database_url(
        username=user, password=password, database=database, host=host, ssl_ca=ca
    )
    return user, password, host, ca, url


def option_file(path: Path, settings: tuple[str, str, str, str, str]) -> None:
    user, password, host, ca, _ = settings
    # Passwords are constrained by read_secret; quote the other MySQL options.
    values = {"user": user, "password": password, "host": host, "ssl-ca": ca}
    if any(any(c in value for c in '\r\n"\\') for value in values.values()):
        raise ValueError("Invalid MySQL option value")
    path.write_text(
        "[client]\n"
        + "\n".join(f'{key}="{value}"' for key, value in values.items())
        + "\nport=3306\nprotocol=TCP\nssl-mode=VERIFY_IDENTITY\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def mysql_command(
    arguments: list[str],
    *,
    output: BinaryIO | None = None,
    source: BinaryIO | None = None,
) -> None:
    result = subprocess.run(
        arguments,
        stdout=output or subprocess.DEVNULL,
        stdin=source,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        # Client diagnostics may include statements and credentials.
        raise RuntimeError("MySQL backup/restore command failed")


def backup(
    destination: Path, keyring_path: Path, roots: dict[str, Path], *, quiesced: bool
) -> dict[str, Any]:
    if not quiesced:
        raise ValueError("Stop and verify all B writers before backing up")
    catalog = os.getenv("APP_DEPLOYMENT_DATABASE", "clsen_data")
    production = os.getenv("PRODUCTION_DATABASE_NAME", "clsen_production")
    database_pair(catalog, production)
    destination.mkdir(parents=True, exist_ok=False)
    destination.chmod(0o700)
    keyring = load_keyring(keyring_path)
    settings = connection_settings("backup", catalog)
    engine = create_engine(settings[-1], hide_parameters=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".staging-", dir=destination
        ) as temporary:
            stage = Path(temporary)
            options = stage / "client.cnf"
            option_file(options, settings)
            manifest: dict[str, Any] = {
                "format": "clsen-production-backup-v1",
                "databases": {},
                "files": {},
            }
            archive = stage / "backup.tar"
            with engine.connect() as connection, tarfile.open(archive, "w") as bundle:
                for name, database in [
                    ("catalog", catalog),
                    ("production", production),
                ]:
                    before = fingerprint(connection, database)
                    dump = stage / (name + ".sql")
                    with dump.open("wb") as output:
                        mysql_command(
                            [
                                os.getenv("MYSQLDUMP_EXECUTABLE", "mysqldump"),
                                f"--defaults-extra-file={options}",
                                "--single-transaction",
                                "--routines",
                                "--triggers",
                                "--events",
                                "--hex-blob",
                                "--no-tablespaces",
                                "--set-gtid-purged=OFF",
                                "--skip-comments",
                                database,
                            ],
                            output=output,
                        )
                    if fingerprint(connection, database) != before:
                        raise RuntimeError(
                            "Database changed during the quiesced backup"
                        )
                    manifest["databases"][name] = {"source": database, "tables": before}
                    bundle.add(dump, arcname=name + ".sql", recursive=False)
                for name, root in roots.items():
                    if (
                        name not in {"raw", "production"}
                        or root.is_symlink()
                        or not root.is_dir()
                    ):
                        raise ValueError("Expected an explicit B storage directory")
                    for directory, dirs, files in os.walk(root):
                        if any(
                            (Path(directory) / child).is_symlink() for child in dirs
                        ):
                            raise ValueError(
                                "Source directories cannot contain symbolic links"
                            )
                        for filename in sorted(files):
                            source = Path(directory) / filename
                            if source.is_symlink() or not source.is_file():
                                raise ValueError("Source files must be regular files")
                            relative = name + "/" + source.relative_to(root).as_posix()
                            content = source.read_bytes()
                            manifest["files"][relative] = hashlib.sha256(
                                content
                            ).hexdigest()
                            # Archive the same bytes whose hash was recorded.
                            from io import BytesIO

                            info = tarfile.TarInfo(relative)
                            info.size = len(content)
                            info.mode = 0o600
                            bundle.addfile(info, BytesIO(content))
                manifest_path = stage / "manifest.json"
                manifest_path.write_text(
                    json.dumps(manifest, sort_keys=True), encoding="utf-8"
                )
                bundle.add(manifest_path, arcname="manifest.json", recursive=False)
            artifact = encrypt_file(
                archive,
                destination / "backup.enc",
                keyring=keyring,
                artifact_type="production-backup-v1",
            )
            verify_encrypted_file(
                destination / "backup.enc",
                keyring=keyring,
                expected_sha256=artifact.plaintext_sha256,
                expected_size=artifact.plaintext_size,
            )
            result = {"format": manifest["format"], "artifact": asdict(artifact)}
            (destination / "catalog.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
            return result
    finally:
        engine.dispose()


def unpack(directory: Path, keyring_path: Path, target: Path) -> dict[str, Any]:
    metadata = json.loads((directory / "catalog.json").read_text(encoding="utf-8"))
    keyring = load_keyring(keyring_path)
    artifact = metadata["artifact"]
    verify_encrypted_file(
        directory / "backup.enc",
        keyring=keyring,
        expected_sha256=artifact["plaintext_sha256"],
        expected_size=artifact["plaintext_size"],
    )
    target.mkdir(parents=True, exist_ok=False)
    archive = target / "backup.tar"
    decrypt_file(directory / "backup.enc", archive, keyring=keyring)
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or any(
            not member.isfile() for member in members
        ):
            raise ValueError("Backup contains duplicate or non-file entries")
        stream = bundle.extractfile("manifest.json")
        if stream is None:
            raise ValueError("Backup manifest is not a regular file")
        manifest = cast(dict[str, Any], json.load(stream))
        expected = {
            "manifest.json",
            "catalog.sql",
            "production.sql",
            *manifest["files"],
        }
        if manifest["format"] != "clsen-production-backup-v1" or set(names) != expected:
            raise ValueError("Backup file set is incomplete")
        bundle.extractall(target / "content", filter="data")
    for name, digest in manifest["files"].items():
        if (
            hashlib.sha256((target / "content" / name).read_bytes()).hexdigest()
            != digest
        ):
            raise ValueError("Source file checksum differs")
    return manifest


def restore_test(
    directory: Path,
    keyring_path: Path,
    temporary_root: Path,
) -> dict[str, Any]:
    catalog = os.getenv("APP_DEPLOYMENT_DATABASE", "")
    production = os.getenv("PRODUCTION_DATABASE_NAME", "")
    database_pair(catalog, production)
    if (
        not catalog.startswith("clsen_data_test_")
        or os.getenv("APP_DISPOSABLE_TEST_RUN") != "true"
    ):
        raise ValueError("Restore verification requires a task-owned disposable MySQL")
    run = uuid4().hex[:16]
    stage = temporary_root / run
    engine = None
    created = []
    try:
        manifest = unpack(directory, keyring_path, stage)
        settings = connection_settings("root", "mysql")
        options = stage / "client.cnf"
        option_file(options, settings)
        engine = create_engine(settings[-1], hide_parameters=True)
        with engine.connect() as connection:
            for kind in ["catalog", "production"]:
                database = (
                    "clsen_data_test_restore_"
                    if kind == "catalog"
                    else "clsen_production_test_restore_"
                ) + run
                if connection.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.schemata "
                        "WHERE schema_name=:name"
                    ),
                    {"name": database},
                ).scalar_one():
                    raise ValueError("Restore target already exists")
                connection.execute(
                    text(
                        f"CREATE DATABASE `{database}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                    )
                )
                created.append(database)
                connection.commit()
                with (stage / "content" / (kind + ".sql")).open("rb") as source:
                    mysql_command(
                        [
                            os.getenv("MYSQL_EXECUTABLE", "mysql"),
                            f"--defaults-extra-file={options}",
                            database,
                        ],
                        source=source,
                    )
                if (
                    fingerprint(connection, database)
                    != manifest["databases"][kind]["tables"]
                ):
                    raise ValueError("Restored database checksum differs")
            return {
                "status": "verified",
                "databases": len(created),
                "source_files": len(manifest["files"]),
            }
    finally:
        if engine is not None:
            try:
                with engine.connect() as connection:
                    for database in created:
                        connection.execute(text(f"DROP DATABASE `{database}`"))
            finally:
                engine.dispose()
        if stage.exists():
            if stage.is_symlink() or stage.resolve().parent != temporary_root.resolve():
                raise ValueError("Restore staging path escaped the temporary root")
            import shutil

            shutil.rmtree(stage)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["backup", "restore-test"])
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--keyring", required=True, type=Path)
    parser.add_argument(
        "--temporary-root", type=Path, default=Path("/var/lib/clsen/restore-tests")
    )
    parser.add_argument("--quiesced", action="store_true")
    args = parser.parse_args()
    try:
        result = (
            backup(
                args.directory,
                args.keyring,
                {
                    "raw": Path("/var/lib/clsen/raw"),
                    "production": Path("/var/lib/clsen/production"),
                },
                quiesced=args.quiesced,
            )
            if args.command == "backup"
            else restore_test(args.directory, args.keyring, args.temporary_root)
        )
    except Exception as error:
        detail = (
            str(error)
            if type(error) in {ValueError, RuntimeError}
            else type(error).__name__
        )
        raise SystemExit("B backup/restore failed: " + detail) from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
