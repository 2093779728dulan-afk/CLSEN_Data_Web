"""Task-owned fictional production catalog runtime; preserves existing B databases."""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = Path(
    "D:/CLSEN_DeploymentPrep_20260914/development-v1.1.0-mvp-20261010/optimization-20261012/catalog-reference-20261012/production-candidates-20261015"
)
ORIGINAL = Path(
    "D:/CLSEN_DeploymentPrep_20260914/development-v1.1.0-mvp-20261010/implementation-20261012/runtime"
)
DATABASE = "clsen_data_test_production_catalog_20261015"
CONTAINER = "clsen-data-web-b-v1-1-0-mysql"
PYTHON = "D:/CLSEN_Data_Web/.venv/Scripts/python.exe"


def private(path):
    subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            os.environ["USERNAME"] + ":(F)",
        ],
        check=True,
        capture_output=True,
    )


def root_sql(sql):
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            CONTAINER,
            "sh",
            "-c",
            'MYSQL_PWD="$(cat /run/secrets/root-password)" mysql -N -uroot',
        ],
        input=sql,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            "Task MySQL command failed; private inputs were not printed."
        )
    return result.stdout.strip()


def owner():
    info = json.loads(subprocess.check_output(["docker", "inspect", CONTAINER]))[0]
    assert info["Config"]["Labels"]["clsen.owner"] == "clsen-production-mvp-v1.1.0"
    assert info["State"]["Running"]
    assert info["HostConfig"]["PortBindings"]["3306/tcp"][0]["HostIp"] == "127.0.0.1"
    assert info["HostConfig"]["PortBindings"]["3306/tcp"][0]["HostPort"] == "23311"


def migrate(configuration):
    owner()
    previous = root_sql("SELECT @@GLOBAL.log_bin_trust_function_creators;")
    assert previous in ("0", "1")
    environment = os.environ | {
        "APP_MIGRATION_DATABASE_URL": configuration["MIGRATION_URL"]
    }
    try:
        root_sql("SET GLOBAL log_bin_trust_function_creators=1;")
        result = subprocess.run(
            [PYTHON, "-X", "utf8", "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        (TASK / "migration.log").write_text(
            result.stdout + result.stderr, encoding="utf-8"
        )
        if result.returncode:
            raise RuntimeError(
                "Task migration failed; see task migration.log. Existing schemas were not targeted."
            )
    finally:
        root_sql("SET GLOBAL log_bin_trust_function_creators=" + previous + ";")


def main():
    action = sys.argv[1]
    TASK.mkdir(exist_ok=True)
    config_path = TASK / "runtime.json"
    sys.path.insert(0, str(ROOT / "backend"))
    if action == "prepare":
        assert not config_path.exists(), (
            "Task exists; preserve its users, sources and catalog history."
        )
        owner()
        assert (
            root_sql(
                "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name='"
                + DATABASE
                + "';"
            )
            == "0"
        )
        assert (
            root_sql("SELECT COUNT(*) FROM mysql.user WHERE user LIKE 'pcat15_%';")
            == "0"
        )
        from sqlalchemy.engine import URL

        credentials = {
            role: secrets.token_urlsafe(24)
            for role in ("migrator", "app", "backup", "unreadable")
        }

        def url(role):
            return URL.create(
                "mysql+pymysql",
                username="pcat15_" + role,
                password=credentials[role],
                host="127.0.0.1",
                port=23311,
                database=DATABASE,
                query={
                    "charset": "utf8mb4",
                    "ssl_ca": str(ORIGINAL / "mysql-ca.pem"),
                    "ssl_check_hostname": "false",
                },
            ).render_as_string(hide_password=False)

        sql = (
            "CREATE DATABASE `"
            + DATABASE
            + "` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
        )
        for role, password in credentials.items():
            sql += f"CREATE USER 'pcat15_{role}'@'%' IDENTIFIED BY '{password}' REQUIRE SSL;"
        for role, permissions in (
            ("migrator", "ALL PRIVILEGES"),
            ("app", "SELECT,INSERT,UPDATE,DELETE"),
            ("backup", "SELECT,SHOW VIEW,TRIGGER"),
        ):
            sql += f"GRANT {permissions} ON `{DATABASE}`.* TO 'pcat15_{role}'@'%';"
        # Save credentials before provisioning so a partial setup is recoverable.
        password = secrets.token_urlsafe(24)
        configuration = {
            "APP_DATABASE_URL": url("app"),
            "MIGRATION_URL": url("migrator"),
            "BACKUP_URL": url("backup"),
            "UNREADABLE_URL": url("unreadable"),
            "APP_ENVIRONMENT": "development",
            "APP_SESSION_SECRET": secrets.token_urlsafe(48),
            "APP_SESSION_COOKIE_SECURE": "false",
            "APP_CORS_ALLOWED_ORIGINS": "http://127.0.0.1:23030",
            "APP_PRODUCT_ANALYTICS_SOURCE": "p0_catalog",
            "APP_CATALOG_PRODUCTION_SOURCES_ENABLED": "true",
            "APP_PRODUCTION_DEMO_MODE": "false",
            "APP_PRODUCTION_SERVICE_URL": "",
            "APP_PRODUCTION_SERVICE_TOKEN": "",
            "APP_STORAGE_ROOT": str(TASK / "storage"),
            "APP_STORAGE_MAX_UPLOAD_BYTES": "1000000",
            "APP_STORAGE_LEASE_TTL_SECONDS": "120",
            "APP_STORAGE_LEASE_RENEW_INTERVAL_SECONDS": "30",
            "APP_STORAGE_ORPHAN_AGE_SECONDS": "86400",
            "ACCOUNT_PASSWORD": password,
        }
        config_path.write_text(json.dumps(configuration), encoding="utf-8")
        private(config_path)
        root_sql(sql)
        migrate(configuration)
        import sqlalchemy as sa
        from app.auth.passwords import hash_password
        from app.db.engine import configure_mysql_connection

        engine = sa.create_engine(configuration["MIGRATION_URL"], hide_parameters=True)
        sa.event.listen(engine, "connect", configure_mysql_connection)
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE sites SET code='QA_PRODUCTION_CATALOG',display_name='生产商品主档独立虚构体验' WHERE id=1"
                )
            )
            for role in ("admin", "data_manager", "viewer"):
                username = "catalog.production." + role
                inserted = connection.execute(
                    sa.text(
                        "INSERT INTO users(username_normalized,display_name,password_hash,status) VALUES(:name,:name,:hash,'active')"
                    ),
                    {"name": username, "hash": hash_password(password)},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO user_roles(user_id,role_id,assigned_by) SELECT :user,id,:user FROM roles WHERE code=:role"
                    ),
                    {"user": inserted.lastrowid, "role": role},
                )
        engine.dispose()
        accounts = TASK / "accounts.txt"
        accounts.write_text(
            "仅生产商品候选独立虚构体验\ncatalog.production.admin\ncatalog.production.data_manager\ncatalog.production.viewer\n密码："
            + password,
            encoding="utf-8",
        )
        private(accounts)
        (TASK / "sample.csv").write_text(
            "款号,颜色,尺码\nQA-FACTORY-01,Olive,M\nQA-FACTORY-01,Olive,L\n",
            encoding="utf-8-sig",
        )
        print(
            "Independent fictional catalog schema and accounts prepared; original B/A unchanged."
        )
        return
    configuration = json.loads(config_path.read_bytes())
    if action == "migrate":
        migrate(configuration)
        return
    environment = os.environ | {
        key: value for key, value in configuration.items() if key.startswith("APP_")
    }
    if action == "python":
        command = [
            PYTHON,
            "-X",
            "utf8",
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "23032",
        ]
        cwd = ROOT / "backend"
    elif action == "frontend":
        environment |= {
            "CATALOG_LIVE_API_URL": "http://127.0.0.1:23032",
            "VITE_PRODUCT_ANALYTICS_SOURCE": "p0_catalog",
            "VITE_PRODUCTION_ENABLED": "true",
            "VITE_PRODUCTION_CATALOG_ENABLED": "true",
        }
        command = [
            "node",
            str(ROOT / "frontend/node_modules/vite/bin/vite.js"),
            "--host",
            "127.0.0.1",
            "--port",
            "23030",
            "--strictPort",
        ]
        cwd = ROOT / "frontend"
    else:
        raise SystemExit("Expected prepare, migrate, python or frontend.")
    raise SystemExit(
        subprocess.run(command, cwd=cwd, env=environment, check=False).returncode
    )


if __name__ == "__main__":
    main()
