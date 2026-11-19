"""Prepare only the task-owned B database. Never restore or connect to A/production."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(
    r"D:\CLSEN_DeploymentPrep_20260914\development-v1.1.0-mvp-20261010\implementation-20261012\runtime"
)
CONTAINER = "clsen-data-web-b-v1-1-0-mysql"
VOLUME = "clsen-data-web-b-v1-1-0-mysql-data"
OWNER = "clsen-production-mvp-v1.1.0"
CONTROL = "clsen_control_b_v1_1_0"
ORDERS = "clsen_orders_b_v1_1_0"


def docker(*args: str, input: str | None = None) -> str:
    result = subprocess.run(
        ["docker", *args], input=input, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def main() -> None:
    if (
        subprocess.check_output(
            ["git", "-C", str(ROOT), "branch", "--show-current"], text=True
        ).strip()
        != "codex/develop-v1.1.0"
    ):
        raise RuntimeError("This preparation is restricted to the selected B branch")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    credentials_file = RUNTIME / "credentials.json"
    if credentials_file.exists():
        credentials = json.loads(credentials_file.read_text(encoding="utf-8"))
    else:
        credentials = {
            name: secrets.token_hex(24)
            for name in [
                "root",
                "control_migrator",
                "control_app",
                "orders_migrator",
                "orders_app",
                "service_token",
                "session_secret",
                "password",
            ]
        }
        credentials_file.write_text(json.dumps(credentials), encoding="utf-8")
        subprocess.run(
            [
                "icacls",
                str(credentials_file),
                "/inheritance:r",
                "/grant:r",
                f"{os.environ['USERNAME']}:(F)",
            ],
            capture_output=True,
            check=True,
        )
    root_secret = RUNTIME / "mysql-root-password"
    root_secret.write_text(credentials["root"], encoding="utf-8")
    subprocess.run(
        [
            "icacls",
            str(root_secret),
            "/inheritance:r",
            "/grant:r",
            f"{os.environ['USERNAME']}:(F)",
        ],
        capture_output=True,
        check=True,
    )
    probe = subprocess.run(
        ["docker", "inspect", CONTAINER], capture_output=True, text=True, check=False
    )
    if probe.returncode == 0:
        container = json.loads(probe.stdout)[0]
        if container["Config"]["Labels"].get("clsen.owner") != OWNER:
            raise RuntimeError("Container is not owned by this task")
        if not container["State"]["Running"]:
            docker("start", CONTAINER)
    else:
        volume = subprocess.run(
            ["docker", "volume", "inspect", VOLUME],
            capture_output=True,
            text=True,
            check=False,
        )
        if (
            volume.returncode == 0
            and json.loads(volume.stdout)[0].get("Labels", {}).get("clsen.owner")
            != OWNER
        ):
            raise RuntimeError("Volume is not owned by this task")
        if volume.returncode != 0:
            docker("volume", "create", "--label", f"clsen.owner={OWNER}", VOLUME)
        docker(
            "run",
            "-d",
            "--name",
            CONTAINER,
            "--label",
            f"clsen.owner={OWNER}",
            "-p",
            "127.0.0.1:23311:3306",
            "--mount",
            f"type=volume,source={VOLUME},target=/var/lib/mysql",
            "--mount",
            f"type=bind,source={root_secret},target=/run/secrets/root-password,readonly",
            "-e",
            "MYSQL_ROOT_PASSWORD_FILE=/run/secrets/root-password",
            "mysql:8.4.11",
            "--require-secure-transport=ON",
            "--transaction-isolation=READ-COMMITTED",
            "--innodb-buffer-pool-size=128M",
            "--max-connections=60",
        )
    for _ in range(60):
        result = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER,
                "sh",
                "-c",
                'MYSQL_PWD="$(cat /run/secrets/root-password)" mysql -uroot -N -e "SELECT 1"',
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Task MySQL did not become ready")
    docker("cp", f"{CONTAINER}:/var/lib/mysql/ca.pem", str(RUNTIME / "mysql-ca.pem"))
    sql = ["SET GLOBAL log_bin_trust_function_creators=1;"]
    for database, prefix in [(CONTROL, "control"), (ORDERS, "orders")]:
        sql.append(
            f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
        )
        for suffix in ["migrator", "app"]:
            user = f"b_{prefix}_{suffix}"
            sql.append(
                f"CREATE USER IF NOT EXISTS '{user}'@'%' IDENTIFIED BY '{credentials[prefix + '_' + suffix]}' REQUIRE SSL;"
            )
            privilege = (
                "ALL PRIVILEGES"
                if suffix == "migrator"
                else "SELECT,INSERT,UPDATE,DELETE"
            )
            sql.append(f"GRANT {privilege} ON `{database}`.* TO '{user}'@'%';")
    docker(
        "exec",
        "-i",
        CONTAINER,
        "sh",
        "-c",
        'MYSQL_PWD="$(cat /run/secrets/root-password)" mysql -uroot',
        input="\n".join(sql),
    )
    sys.path.insert(0, str(ROOT / "backend"))
    from alembic import command
    from alembic.config import Config
    from app.auth.passwords import hash_password
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL

    ca = str(RUNTIME / "mysql-ca.pem")

    def url(user: str, password: str) -> str:
        return URL.create(
            "mysql+pymysql",
            username=user,
            password=password,
            host="127.0.0.1",
            port=23311,
            database=CONTROL,
            query={"charset": "utf8mb4", "ssl_ca": ca, "ssl_check_hostname": "false"},
        ).render_as_string(hide_password=False)

    migration_url = url("b_control_migrator", credentials["control_migrator"])
    os.environ["APP_MIGRATION_DATABASE_URL"] = migration_url
    command.upgrade(Config(str(ROOT / "backend" / "alembic.ini")), "head")
    engine = create_engine(migration_url, hide_parameters=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE sites SET code='DEMO_LOCAL_ONLY',display_name='B独立生产演练 · 虚构数据' WHERE id=1"
            )
        )
        for role in ["admin", "data_manager", "viewer"]:
            username = f"production.demo.{role}"
            found = connection.scalar(
                text("SELECT id FROM users WHERE username_normalized=:username"),
                {"username": username},
            )
            if found is None:
                inserted = connection.execute(
                    text(
                        "INSERT INTO users(username_normalized,display_name,password_hash,status) VALUES(:username,:name,:password,'active')"
                    ),
                    {
                        "username": username,
                        "name": f"生产演练 {role}",
                        "password": hash_password(credentials["password"]),
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO user_roles(user_id,role_id,assigned_by) SELECT :user,id,:user FROM roles WHERE code=:role"
                    ),
                    {"user": inserted.lastrowid, "role": role},
                )
    engine.dispose()
    truststore = RUNTIME / "mysql-trust.p12"
    if not truststore.exists():
        subprocess.run(
            [
                r"D:\Program Files\Java\jdk-21.0.11\bin\keytool.exe",
                "-importcert",
                "-noprompt",
                "-alias",
                "task-mysql-ca",
                "-file",
                ca,
                "-keystore",
                str(truststore),
                "-storetype",
                "PKCS12",
                "-storepass",
                "changeit",
            ],
            capture_output=True,
            check=True,
        )
    environment = {
        "APP_DATABASE_URL": url("b_control_app", credentials["control_app"]),
        "APP_SESSION_SECRET": credentials["session_secret"],
        "APP_SESSION_COOKIE_SECURE": "false",
        "APP_ENVIRONMENT": "development",
        "APP_PRODUCT_ANALYTICS_SOURCE": "legacy_parser",
        "APP_PRODUCTION_SERVICE_URL": "http://127.0.0.1:23011",
        "APP_PRODUCTION_SERVICE_TOKEN": credentials["service_token"],
        "APP_PRODUCTION_DEMO_MODE": "true",
        "PRODUCTION_DATABASE_URL": f"jdbc:mysql://127.0.0.1:23311/{ORDERS}?sslMode=VERIFY_CA&trustCertificateKeyStoreUrl={truststore.as_uri()}&trustCertificateKeyStorePassword=changeit&connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true&characterEncoding=UTF-8",
        "PRODUCTION_DATABASE_USER": "b_orders_app",
        "PRODUCTION_DATABASE_PASSWORD": credentials["orders_app"],
        "PRODUCTION_MIGRATION_USER": "b_orders_migrator",
        "PRODUCTION_MIGRATION_PASSWORD": credentials["orders_migrator"],
        "PRODUCTION_SERVICE_TOKEN": credentials["service_token"],
        "PRODUCTION_AUTHORITY_MODE": "demo_fixed",
        "CATALOG_LIVE_API_URL": "http://127.0.0.1:23012",
        "VITE_PRODUCT_ANALYTICS_SOURCE": "legacy_parser",
        "VITE_PRODUCTION_ENABLED": "true",
    }
    (RUNTIME / "environment.json").write_text(json.dumps(environment), encoding="utf-8")
    subprocess.run(
        [
            "icacls",
            str(RUNTIME / "environment.json"),
            "/inheritance:r",
            "/grant:r",
            f"{os.environ['USERNAME']}:(F)",
        ],
        capture_output=True,
        check=True,
    )
    (RUNTIME / "accounts.txt").write_text(
        "仅B虚构演练账号；不适用于A／服务器\n"
        + "\n".join(
            f"production.demo.{role}" for role in ["admin", "data_manager", "viewer"]
        )
        + "\n临时密码："
        + credentials["password"]
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "icacls",
            str(RUNTIME / "accounts.txt"),
            "/inheritance:r",
            "/grant:r",
            f"{os.environ['USERNAME']}:(F)",
        ],
        capture_output=True,
        check=True,
    )
    print(
        "B control schema migrated and fictional accounts prepared; credentials are in the private task runtime."
    )


if __name__ == "__main__":
    main()
