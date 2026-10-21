from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.mysql


def test_batch_review_repository_schema_exposes_site_and_lease_guards(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    inspector = sa.inspect(mysql_engine)

    assert {
        "batch_review_runs",
        "batch_review_items",
        "batch_review_commands",
    } <= set(inspector.get_table_names())
    item_columns = {
        column["name"] for column in inspector.get_columns("batch_review_items")
    }
    assert {"site_id", "lease_token", "lease_expires_at", "lease_fence"} <= item_columns
    foreign_keys = {
        constraint["name"]: constraint
        for constraint in inspector.get_foreign_keys("batch_review_items")
    }
    assert foreign_keys["fk_batch_review_items_run"]["options"]["ondelete"] == "CASCADE"
    assert (
        foreign_keys["fk_batch_review_items_batch"]["options"]["ondelete"] == "RESTRICT"
    )
