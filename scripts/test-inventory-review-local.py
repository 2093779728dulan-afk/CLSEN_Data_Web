"""Run the target MySQL contracts with the existing four-account test boundary."""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
TASK = Path(
    "D:/CLSEN_DeploymentPrep_20260914/development-v1.1.0-mvp-20261010/optimization-20261012/catalog-reference-20261012/inventory-reconciliation-20261013"
)
sys.path.insert(0, str(ROOT / "backend"))
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.auth.passwords import hash_password
from app.db.engine import configure_mysql_connection
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

path = TASK / "test-runtime.json"
if not path.exists():
    runtime = json.loads((TASK / "runtime.json").read_text())
    run_id = uuid4().hex
    database = "clsen_data_test_" + run_id[:16]
    root_command = [
        "docker",
        "exec",
        "-i",
        "clsen-data-web-b-v1-1-0-mysql",
        "sh",
        "-c",
        'MYSQL_PWD="$(cat /run/secrets/root-password)" mysql -N -uroot',
    ]
    base = make_url(runtime["APP_DATABASE_URL"])
    credentials = {
        suffix: secrets.token_urlsafe(24)
        for suffix in ("migrator", "app", "backup", "unreadable")
    }
    config = {"APP_TEST_RUN_ID": run_id, "APP_INVENTORY_REVIEW_TASK_TESTS": "true"}
    sql = [
        f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
    ]
    for suffix, variable in [
        ("migrator", "APP_TEST_DATABASE_URL"),
        ("app", "APP_TEST_RUNTIME_DATABASE_URL"),
        ("backup", "APP_TEST_BACKUP_DATABASE_URL"),
        ("unreadable", "APP_TEST_SCHEMA_UNREADABLE_DATABASE_URL"),
    ]:
        username = "inv_" + run_id[:8] + "_" + suffix
        sql.append(
            f"CREATE USER '{username}'@'%' IDENTIFIED BY '{credentials[suffix]}' REQUIRE SSL;"
        )
        privilege = {
            "migrator": "SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,DROP,INDEX,REFERENCES,TRIGGER",
            "app": "SELECT,INSERT,UPDATE,DELETE",
            "backup": "SELECT,SHOW VIEW",
        }.get(suffix)
        if privilege:
            sql.append(f"GRANT {privilege} ON `{database}`.* TO '{username}'@'%';")
        config[variable] = base.set(
            username=username, password=credentials[suffix], database=database
        ).render_as_string(hide_password=False)
    subprocess.run(
        root_command, input="\n".join(sql), text=True, capture_output=True, check=True
    )
    path.write_text(json.dumps(config), encoding="utf-8")
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
    old = subprocess.check_output(
        root_command,
        input="SELECT @@GLOBAL.log_bin_trust_function_creators;",
        text=True,
    ).strip()
    assert old in ("0", "1")
    try:
        subprocess.run(
            root_command,
            input="SET GLOBAL log_bin_trust_function_creators=1;",
            text=True,
            capture_output=True,
            check=True,
        )
        os.environ["APP_MIGRATION_DATABASE_URL"] = config["APP_TEST_DATABASE_URL"]
        os.chdir(ROOT / "backend")
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
    finally:
        subprocess.run(
            root_command,
            input="SET GLOBAL log_bin_trust_function_creators=" + old + ";",
            text=True,
            capture_output=True,
            check=True,
        )
    engine = create_engine(config["APP_TEST_DATABASE_URL"], hide_parameters=True)
    sa.event.listen(engine, "connect", configure_mysql_connection)
    with engine.begin() as c:
        c.execute(text("UPDATE sites SET code='DEMO_LOCAL_ONLY' WHERE id=1"))
        inserted = c.execute(
            text(
                "INSERT INTO users(username_normalized,display_name,password_hash,status) VALUES('inventory.review.admin','虚构合同测试管理员',:password,'active')"
            ),
            {"password": hash_password(secrets.token_urlsafe(24))},
        )
        c.execute(
            text(
                "INSERT INTO user_roles(user_id,role_id,assigned_by) SELECT :user,id,:user FROM roles WHERE code='admin'"
            ),
            {"user": inserted.lastrowid},
        )
    engine.dispose()
config = json.loads(path.read_text())
os.environ.update(config)
os.environ["APP_INVENTORY_REVIEW_HTTP_BASE_URL"] = "http://127.0.0.1:23012"
os.chdir(ROOT / "backend")
raise SystemExit(
    pytest.main(
        [
            "tests/integration/test_inventory_review_task.py",
            "--require-mysql",
            "-x",
            "-q",
        ]
    )
)
