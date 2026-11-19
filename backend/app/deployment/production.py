"""Explicit B database preparation; runtime services never receive these credentials."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text

from app.deployment.entrypoint import build_database_url

CATALOG_TABLES = (
    "product_catalog_publications",
    "product_catalog_sku_members",
    "product_sku_revisions",
    "product_catalog_style_members",
    "product_style_revisions",
    "production_inventory_reviews",
    "production_inventory_review_revisions",
)


def database_pair(catalog: str, production: str) -> None:
    import re

    if (catalog, production) == ("clsen_data", "clsen_production"):
        return
    match = re.fullmatch(r"clsen_production_test_([a-z0-9_]{1,32})", production)
    if not match or catalog != "clsen_data_test_" + match[1]:
        raise ValueError(
            "B requires an explicitly paired catalog and production database"
        )


def read_secret(name: str) -> str:
    value = (
        (Path(os.getenv("DEPLOYMENT_SECRETS_DIR", "/run/secrets")) / name)
        .read_text()
        .strip()
    )
    if len(value) < 32 or not all(
        c.isascii() and (c.isalnum() or c in "_-") for c in value
    ):
        raise ValueError("Invalid deployment secret file: " + name)
    return value


def prepare() -> None:
    catalog = os.getenv("APP_DEPLOYMENT_DATABASE", "clsen_data")
    production = os.getenv("PRODUCTION_DATABASE_NAME", "clsen_production")
    database_pair(catalog, production)
    engine = create_engine(
        build_database_url(
            username="root",
            password=read_secret("mysql_root_password"),
            database=catalog,
            host=os.getenv("APP_DEPLOYMENT_MYSQL_HOST", "mysql"),
            ssl_ca=os.getenv(
                "APP_DEPLOYMENT_MYSQL_CA", "/run/secrets/mysql_ca_certificate"
            ),
        ),
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{production}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
            )
            for role, privileges in [
                ("app", "SELECT,INSERT,UPDATE,DELETE"),
                (
                    "migrator",
                    "SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,DROP,INDEX,REFERENCES,TRIGGER",
                ),
                ("backup", "SELECT,SHOW VIEW,TRIGGER,EVENT"),
            ]:
                user = "clsen_production_" + role
                password = read_secret("production_" + role + "_password")
                connection.execute(
                    text(
                        f"CREATE USER IF NOT EXISTS '{user}'@'%' "
                        "IDENTIFIED BY :password REQUIRE SSL"
                    ),
                    {"password": password},
                )
                connection.execute(
                    text(
                        f"ALTER USER '{user}'@'%' IDENTIFIED BY :password REQUIRE SSL"
                    ),
                    {"password": password},
                )
                connection.execute(
                    text(f"REVOKE ALL PRIVILEGES, GRANT OPTION FROM '{user}'@'%'")
                )
                connection.execute(
                    text(f"GRANT {privileges} ON `{production}`.* TO '{user}'@'%'")
                )
            for table in CATALOG_TABLES:
                connection.execute(
                    text(
                        f"GRANT SELECT ON `{catalog}`.`{table}` "
                        "TO 'clsen_production_app'@'%'"
                    )
                )
            connection.execute(
                text(
                    f"GRANT SELECT,SHOW VIEW,TRIGGER,EVENT ON `{catalog}`.* "
                    "TO 'clsen_production_backup'@'%'"
                )
            )
            connection.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    prepare()
