"""Run B's Java contracts and Linux image against an owned, disposable TLS MySQL."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]


def cleanup(output: Path) -> None:
    path = output / "resources.json"
    if not path.exists():
        return
    resources = json.loads(path.read_text(encoding="utf-8"))
    task = resources["task"]
    if not re.fullmatch(r"clsen-b-ci-[0-9a-f]{12}", task):
        raise RuntimeError("Invalid Java CI task identity")
    for identifier in [
        *reversed(list(resources["containers"].values())),
        resources["network"],
    ]:
        if not identifier:
            continue
        kind = "network" if identifier == resources["network"] else "container"
        found = subprocess.run(
            ["docker", kind, "inspect", identifier], capture_output=True, check=False
        )
        if found.returncode:
            # A missing task ID is already clean. A daemon outage is not.
            subprocess.run(["docker", "info"], check=True, capture_output=True)
            continue
        info = json.loads(found.stdout)[0]
        labels = info["Labels"] if kind == "network" else info["Config"]["Labels"]
        if info["Id"] != identifier or labels.get("clsen.task") != task:
            raise RuntimeError("Java CI cleanup ownership mismatch")
        args = (
            ["docker", "network", "rm", identifier]
            if kind == "network"
            else [
                "docker",
                "rm",
                "--force",
                "--volumes",
                identifier,
            ]
        )
        subprocess.run(args, check=True, capture_output=True)


def certificates(directory: Path) -> None:
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "CLSEN disposable CI CA")]
    )
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mysql")]))
        .issuer_name(name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("mysql"),
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    (directory / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (directory / "server.pem").write_bytes(
        server.public_bytes(serialization.Encoding.PEM)
    )
    (directory / "server-key.pem").write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def run(output: Path, *, offline: bool) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private"
    private.mkdir(mode=0o700)
    if os.name == "nt":
        subprocess.run(
            [
                "icacls",
                str(private),
                "/inheritance:r",
                "/grant:r",
                os.environ["USERNAME"] + ":(OI)(CI)(F)",
            ],
            check=True,
            capture_output=True,
        )
    passwords = {
        role: secrets.token_hex(32) for role in ["root", "app", "migrator", "service"]
    }
    for role, value in passwords.items():
        filename = (
            "mysql_root_password"
            if role == "root"
            else (
                "production_service_token"
                if role == "service"
                else "production_" + role + "_password"
            )
        )
        (private / filename).write_text(value, encoding="utf-8")
    certificates(private)
    (private / "client.cnf").write_text(
        '[client]\nuser=root\npassword="' + passwords["root"] + '"\n'
        "host=127.0.0.1\nprotocol=TCP\nssl-mode=VERIFY_IDENTITY\n"
        "ssl-ca=/run/secrets/ca.pem\n",
        encoding="utf-8",
    )
    for file in private.iterdir():
        # The host directory is owner-only. Each container receives only its
        # required files; bind-mounted secrets must be readable by UID 10001.
        file.chmod(0o444)
    task = "clsen-b-ci-" + secrets.token_hex(6)
    mysql = task + "-mysql"
    java = task + "-java"
    migration = task + "-migration"
    suffix = "ci_" + task.rsplit("-", 1)[-1]
    catalog = "clsen_data_test_" + suffix
    production = "clsen_production_test_" + suffix
    image = task + ":java"
    containers: dict[str, str] = {}
    network_id = ""
    result: dict[str, object] = {
        "task": task,
        "tests": "all production Java tests",
        "status": "incomplete",
    }

    def save_resources() -> None:
        (output / "resources.json").write_text(
            json.dumps(
                {
                    "task": task,
                    "containers": containers,
                    "network": network_id,
                }
            ),
            encoding="utf-8",
        )

    def command(
        arguments: list[str],
        *,
        input: bytes | None = None,
        env: dict[str, str] | None = None,
        log: str | None = None,
    ) -> str:
        process = subprocess.run(
            arguments, cwd=ROOT, input=input, env=env, capture_output=True, check=False
        )
        stdout = process.stdout.decode("utf-8", errors="replace")
        diagnostic = stdout + process.stderr.decode("utf-8", errors="replace")
        for password in passwords.values():
            diagnostic = diagnostic.replace(password, "<redacted>")
        if log:
            (output / log).write_text(diagnostic, encoding="utf-8")
        if process.returncode:
            raise RuntimeError(
                "B CI command failed: " + arguments[0] + ("; see " + log if log else "")
            )
        return stdout.strip()

    def inspect_owned(name: str) -> dict:
        info = json.loads(command(["docker", "inspect", name]))[0]
        if (
            info["Id"] != containers[name]
            or info["Config"]["Labels"].get("clsen.task") != task
        ):
            raise RuntimeError("Task container identity changed")
        return info

    def sql(statement: str) -> str:
        inspect_owned(mysql)
        return command(
            [
                "docker",
                "exec",
                "-i",
                mysql,
                "mysql",
                "--defaults-extra-file=/run/secrets/client.cnf",
                "-N",
                "-B",
            ],
            input=statement.encode("utf-8"),
        )

    try:
        network_id = command(
            ["docker", "network", "create", "--label", "clsen.task=" + task, task]
        )
        save_resources()
        startup = (
            "mkdir -p /tmp/ci-tls; cp /run/secrets/ca.pem /run/secrets/server.pem "
            "/run/secrets/server-key.pem /tmp/ci-tls/; chown -R 999:999 /tmp/ci-tls; "
            "chmod 600 /tmp/ci-tls/server-key.pem; exec docker-entrypoint.sh mysqld "
            "--require-secure-transport=ON --tls-version=TLSv1.2,TLSv1.3 "
            "--ssl-ca=/tmp/ci-tls/ca.pem --ssl-cert=/tmp/ci-tls/server.pem "
            "--ssl-key=/tmp/ci-tls/server-key.pem --log-bin-trust-function-creators=ON"
        )
        containers[mysql] = command(
            [
                "docker",
                "run",
                "-d",
                "--pull=never",
                "--name",
                mysql,
                "--label",
                "clsen.task=" + task,
                "--network",
                task,
                "--network-alias",
                "mysql",
                "--publish",
                "127.0.0.1::3306",
                "--mount",
                f"type=bind,source={private},target=/run/secrets,readonly",
                "--env",
                "MYSQL_ROOT_PASSWORD_FILE=/run/secrets/mysql_root_password",
                "--entrypoint",
                "sh",
                "mysql:8.4.11",
                "-ec",
                startup,
            ]
        )
        save_resources()
        for attempt in range(60):
            try:
                if sql("SELECT 1;") == "1":
                    break
            except RuntimeError:
                if attempt == 59:
                    command(["docker", "logs", mysql], log="mysql-startup.log")
                    raise
            time.sleep(1)
        port = inspect_owned(mysql)["NetworkSettings"]["Ports"]["3306/tcp"][0][
            "HostPort"
        ]
        statements = [
            f"CREATE DATABASE {name} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
            for name in [
                "clsen_fba_contract",
                "clsen_orders_b_v1_1_0_test",
                "clsen_p2_contract_test_3",
                "clsen_p4_transport_contract",
                catalog,
                production,
            ]
        ]
        for role, grants in [
            ("app", "SELECT,INSERT,UPDATE,DELETE"),
            (
                "migrator",
                "SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,DROP,INDEX,REFERENCES,TRIGGER",
            ),
        ]:
            user = "clsen_production_" + role
            statements.append(
                f"CREATE USER '{user}'@'%' IDENTIFIED BY '{passwords[role]}' REQUIRE SSL;"
            )
            for database in [
                "clsen_fba_contract",
                "clsen_orders_b_v1_1_0_test",
                "clsen_p2_contract_test_3",
                "clsen_p4_transport_contract",
                production,
            ]:
                statements.append(f"GRANT {grants} ON {database}.* TO '{user}'@'%';")
        statements.append(f"GRANT SELECT ON {catalog}.* TO 'clsen_production_app'@'%';")
        sql("\n".join(statements))
        keytool = shutil.which("keytool") or str(
            Path(os.environ["JAVA_HOME"]) / "bin/keytool.exe"
        )
        truststore = private / "mysql-ca.p12"
        command(
            [
                keytool,
                "-importcert",
                "-noprompt",
                "-alias",
                "ci-ca",
                "-file",
                str(private / "ca.pem"),
                "-keystore",
                str(truststore),
                "-storetype",
                "PKCS12",
                "-storepass",
                "changeit",
            ],
            log="truststore.log",
        )
        jdbc = (
            f"jdbc:mysql://127.0.0.1:{port}/clsen_fba_contract?sslMode=VERIFY_IDENTITY"
            f"&trustCertificateKeyStoreUrl={truststore.as_uri()}"
            "&trustCertificateKeyStoreType=PKCS12&trustCertificateKeyStorePassword=changeit"
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("FBA_TEST_", "PRODUCTION_", "P2_TEST_", "P4_TEST_"))
        }
        env.update(
            FBA_TEST_JDBC_URL=jdbc,
            FBA_TEST_MIGRATION_USER="clsen_production_migrator",
            FBA_TEST_MIGRATION_PASSWORD=passwords["migrator"],
            FBA_TEST_RUNTIME_USER="clsen_production_app",
            FBA_TEST_RUNTIME_PASSWORD=passwords["app"],
        )
        for prefix, schema in [
            ("P2_TEST", "clsen_p2_contract_test_3"),
            ("P4_TEST", "clsen_p4_transport_contract"),
        ]:
            env.update(
                {
                    prefix + "_JDBC_URL": jdbc.replace(
                        "/clsen_fba_contract?", "/" + schema + "?"
                    ),
                    prefix + "_MIGRATION_USER": "clsen_production_migrator",
                    prefix + "_MIGRATION_PASSWORD": passwords["migrator"],
                    prefix + "_RUNTIME_USER": "clsen_production_app",
                    prefix + "_RUNTIME_PASSWORD": passwords["app"],
                }
            )
        env.update(
            PRODUCTION_DATABASE_URL=jdbc.replace(
                "/clsen_fba_contract?", "/clsen_orders_b_v1_1_0_test?"
            )
            + "&connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true",
            PRODUCTION_DATABASE_USER="clsen_production_app",
            PRODUCTION_DATABASE_PASSWORD=passwords["app"],
            PRODUCTION_MIGRATION_USER="clsen_production_migrator",
            PRODUCTION_MIGRATION_PASSWORD=passwords["migrator"],
            PRODUCTION_SERVICE_TOKEN=passwords["service"],
            PRODUCTION_AUTHORITY_MODE="demo_fixed",
        )
        maven = shutil.which("mvn") or shutil.which("mvn.cmd")
        if not maven:
            raise RuntimeError("Use the existing Maven/JDK21 runtime")
        command(
            [
                maven,
                *(["-o"] if offline else []),
                "--batch-mode",
                "-f",
                str(ROOT / "backend-java/pom.xml"),
                "verify",
            ],
            env=env,
            log="java-contracts.log",
        )
        context = output / "build-context"
        for source in [
            "backend-java/Dockerfile",
            "ops/production-entrypoint.sh",
            "backend-java/target/dataweb-production-1.1.0-SNAPSHOT.jar",
        ]:
            target = context / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / source, target)
        command(
            [
                "docker",
                "build",
                "--pull=false",
                "--label",
                "clsen.task=" + task,
                "-t",
                image,
                "-f",
                str(context / "backend-java/Dockerfile"),
                str(context),
            ],
            log="image-build.log",
        )
        common = [
            "--network",
            task,
            "--label",
            "clsen.task=" + task,
            "--read-only",
            "--tmpfs",
            "/tmp:size=128m,mode=1777",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
        ]

        def java_mounts(migrate: bool) -> list[str]:
            files = (
                {
                    "mysql_ca_certificate": "ca.pem",
                    "production_migrator_password": "production_migrator_password",
                }
                if migrate
                else {
                    "mysql_ca_certificate": "ca.pem",
                    "production_app_password": "production_app_password",
                    "production_service_token": "production_service_token",
                }
            )
            return [
                part
                for name, filename in files.items()
                for part in [
                    "--mount",
                    f"type=bind,source={private / filename},target=/run/secrets/{name},readonly",
                ]
            ]

        containers[migration] = command(
            [
                "docker",
                "create",
                "--name",
                migration,
                *common,
                *java_mounts(True),
                "--env",
                "PRODUCTION_DATABASE_NAME=" + production,
                image,
                "--migrate",
            ]
        )
        save_resources()
        command(
            ["docker", "start", "--attach", containers[migration]],
            log="image-migration.log",
        )
        containers[java] = command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                java,
                *common,
                *java_mounts(False),
                "--env",
                "PRODUCTION_DATABASE_NAME=" + production,
                "--env",
                "PRODUCTION_CATALOG_SCHEMA=" + catalog,
                "--env",
                "PRODUCTION_CATALOG_ALLOWED_SKUS=approved_catalog",
                "--env",
                "PRODUCTION_AUTHORITY_MODE=catalog_transactional",
                "--env",
                "PRODUCTION_WRITES_ENABLED=false",
                "--env",
                "PRODUCTION_ORDER_SHIPMENT_WRITES_ENABLED=true",
                image,
            ]
        )
        save_resources()
        for attempt in range(45):
            inspect_owned(java)
            check = subprocess.run(
                ["docker", "exec", java, "/app/entrypoint.sh", "--healthcheck"],
                capture_output=True,
                check=False,
            )
            if check.returncode == 0:
                break
            if attempt == 44:
                command(["docker", "logs", java], log="java-startup.log")
                raise RuntimeError("Linux Java readiness failed")
            time.sleep(1)
        command(["docker", "logs", java], log="java-startup.log")
        result.update(
            status="passed",
            tls="VERIFY_IDENTITY",
            java_migration=21,
            image_id=json.loads(command(["docker", "image", "inspect", image]))[0][
                "Id"
            ],
        )
    except Exception:
        result["status"] = "failed"
        raise
    finally:
        cleanup(output)
        result["resources_cleaned"] = True
        (output / "result.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--cleanup-only", action="store_true")
    options = parser.parse_args()
    if options.cleanup_only:
        cleanup(options.output.resolve())
        print("Owned Java CI containers and network are clean")
    else:
        print(json.dumps(run(options.output.resolve(), offline=options.offline)))
