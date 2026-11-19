"""Task-owned fictional inventory review runtime; never targets the existing B schema."""

import hashlib
import json
import os
import secrets
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = Path(
    "D:/CLSEN_DeploymentPrep_20260914/development-v1.1.0-mvp-20261010/optimization-20261012/catalog-reference-20261012/inventory-reconciliation-20261013"
)
ORIGINAL = Path(
    "D:/CLSEN_DeploymentPrep_20260914/development-v1.1.0-mvp-20261010/implementation-20261012/runtime"
)
DATABASE = "clsen_data_test_inventory_review_20261013"
CONTAINER = "clsen-data-web-b-v1-1-0-mysql"


def private(path):
    subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            os.environ["USERNAME"] + ":(F)",
        ],
        capture_output=True,
        check=True,
    )


def main():
    action = sys.argv[1]
    TASK.mkdir(parents=True, exist_ok=True)
    config_path = TASK / "runtime.json"
    if action == "prepare":
        if config_path.exists():
            raise SystemExit(
                "Task already prepared; preserve its saved review history."
            )
        info = json.loads(subprocess.check_output(["docker", "inspect", CONTAINER]))[0]
        assert info["Config"]["Labels"]["clsen.owner"] == "clsen-production-mvp-v1.1.0"
        assert info["State"]["Running"]
        migrator, app, password = (secrets.token_urlsafe(24) for _ in range(3))
        sql = f"CREATE DATABASE IF NOT EXISTS `{DATABASE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci; CREATE USER IF NOT EXISTS 'inv_review_migrator'@'%' IDENTIFIED BY '{migrator}' REQUIRE SSL; CREATE USER IF NOT EXISTS 'inv_review_app'@'%' IDENTIFIED BY '{app}' REQUIRE SSL; ALTER USER 'inv_review_migrator'@'%' IDENTIFIED BY '{migrator}'; ALTER USER 'inv_review_app'@'%' IDENTIFIED BY '{app}'; GRANT ALL PRIVILEGES ON `{DATABASE}`.* TO 'inv_review_migrator'@'%'; GRANT SELECT,INSERT,UPDATE,DELETE ON `{DATABASE}`.* TO 'inv_review_app'@'%';"
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                CONTAINER,
                "sh",
                "-c",
                'MYSQL_PWD="$(cat /run/secrets/root-password)" mysql -uroot',
            ],
            input=sql,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise SystemExit(
                "Task schema provisioning failed; existing resources preserved."
            )
        sys.path.insert(0, str(ROOT / "backend"))
        from alembic import command
        from alembic.config import Config
        from app.auth.passwords import hash_password
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import URL

        def url(user, secret):
            return URL.create(
                "mysql+pymysql",
                username=user,
                password=secret,
                host="127.0.0.1",
                port=23311,
                database=DATABASE,
                query={
                    "charset": "utf8mb4",
                    "ssl_ca": str(ORIGINAL / "mysql-ca.pem"),
                    "ssl_check_hostname": "false",
                },
            ).render_as_string(hide_password=False)

        migration_url = url("inv_review_migrator", migrator)
        os.environ["APP_MIGRATION_DATABASE_URL"] = migration_url
        os.chdir(ROOT / "backend")
        root_command = [
            "docker",
            "exec",
            "-i",
            CONTAINER,
            "sh",
            "-c",
            'MYSQL_PWD="$(cat /run/secrets/root-password)" mysql -N -uroot',
        ]
        original_policy = subprocess.check_output(
            root_command,
            input="SELECT @@GLOBAL.log_bin_trust_function_creators;",
            text=True,
        ).strip()
        assert original_policy in ("0", "1")
        recovery = TASK / "migration-recovery.json"
        recovery.write_text(
            json.dumps(
                {
                    "migration_url": migration_url,
                    "original_trigger_policy": original_policy,
                }
            ),
            encoding="utf-8",
        )
        private(recovery)
        try:
            subprocess.run(
                root_command,
                input="SET GLOBAL log_bin_trust_function_creators=1;",
                text=True,
                check=True,
                capture_output=True,
            )
            command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        finally:
            subprocess.run(
                root_command,
                input="SET GLOBAL log_bin_trust_function_creators="
                + original_policy
                + ";",
                text=True,
                check=True,
                capture_output=True,
            )
        engine = create_engine(migration_url, hide_parameters=True)
        with engine.begin() as c:
            c.execute(
                text(
                    "UPDATE sites SET code='DEMO_LOCAL_ONLY', display_name='库存核对独立虚构数据' WHERE id=1"
                )
            )
            for role in ("admin", "data_manager", "viewer"):
                inserted = c.execute(
                    text(
                        "INSERT INTO users(username_normalized,display_name,password_hash,status) VALUES(:name,:name,:password,'active')"
                    ),
                    {
                        "name": "inventory.review." + role,
                        "password": hash_password(password),
                    },
                )
                c.execute(
                    text(
                        "INSERT INTO user_roles(user_id,role_id,assigned_by) SELECT :user,id,:user FROM roles WHERE code=:role"
                    ),
                    {"user": inserted.lastrowid, "role": role},
                )
        engine.dispose()
        inputs = TASK / "inputs"
        inputs.mkdir(exist_ok=True)
        content = "新款号   COLOR   XS   S   M   L   XL   XXL   3XL   合计   库位\nQA-1101   NAVY   7   4   4   3   0   /   /   18   新仓库\nQA-2206   sand   3   0   /   /   /   /   /   3   \nQA-2206   black   2   0   /   /   /   /   /   2   \n".encode()
        (inputs / "花都仓库1号-用户核对表-20261013.txt").write_bytes(content)
        (TASK / "inventory-source.json").write_text(
            json.dumps(
                {
                    "schema": "production-inventory-source-v1",
                    "consumer_site_id": "1",
                    "source_digest": hashlib.sha256(content).hexdigest(),
                    "source_format": "pasted_table",
                    "source_kind": "FICTIONAL",
                    "organized_on": "2026-10-10",
                    "stocktaken_on": None,
                }
            ),
            encoding="utf-8",
        )
        config = {
            "APP_DATABASE_URL": url("inv_review_app", app),
            "APP_SESSION_SECRET": secrets.token_urlsafe(48),
            "APP_ENVIRONMENT": "development",
            "APP_SESSION_COOKIE_SECURE": "false",
            "APP_CORS_ALLOWED_ORIGINS": "http://127.0.0.1:23020",
            "APP_PRODUCT_ANALYTICS_SOURCE": "p0_catalog",
            "APP_PRODUCTION_DEMO_MODE": "true",
            "APP_PRODUCTION_ORDER_DRAFT_ROOT": str(TASK),
            "APP_PRODUCTION_INVENTORY_REVIEW_WRITES_ENABLED": "true",
            "APP_PRODUCTION_SERVICE_URL": "http://127.0.0.1:23011",
            "APP_PRODUCTION_SERVICE_TOKEN": "inventory-review-isolated-no-java-authority",
            "MIGRATION_URL": migration_url,
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")
        private(config_path)
        accounts = TASK / "accounts.txt"
        accounts.write_text(
            "仅库存独立虚构体验，非原B/真实资料账号\ninventory.review.admin\ninventory.review.data_manager\ninventory.review.viewer\n临时密码："
            + password,
            encoding="utf-8",
        )
        private(accounts)
        print(
            "Task-owned fictional schema migrated to 0031; original B schema and source unchanged."
        )
        return
    config = json.loads(config_path.read_text(encoding="utf-8"))
    env = os.environ | {k: v for k, v in config.items() if k.startswith("APP_")}
    if action == "python":
        # Preserve the old schema as a read-only reference after consolidation.
        env["APP_PRODUCTION_INVENTORY_REVIEW_WRITES_ENABLED"] = "false"
        command = [
            str(Path("D:/CLSEN_Data_Web/.venv/Scripts/python.exe")),
            "-X",
            "utf8",
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "23022",
        ]
        cwd = ROOT / "backend"
    elif action == "frontend":
        class UnifiedEntry(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(307)
                self.send_header("Location", "http://127.0.0.1:23010" + self.path)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()

        print("Old inventory links redirect to the unified B entry on 23010.", flush=True)
        HTTPServer(("127.0.0.1", 23020), UnifiedEntry).serve_forever()
        return
    else:
        raise SystemExit("Expected prepare, python or frontend")
    raise SystemExit(subprocess.run(command, cwd=cwd, env=env, check=False).returncode)


if __name__ == "__main__":
    main()
