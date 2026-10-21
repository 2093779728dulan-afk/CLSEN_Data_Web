from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.catalog.category_service import (
    CatalogCategoryError,
    MySqlCatalogCategoryService,
)


def test_rename_preserves_identity_and_audits_old_code() -> None:
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "code": "SHIRT"
    }
    connection.scalar.return_value = None
    result = MySqlCatalogCategoryService(engine).update(
        site_id=1,
        category_id=7,
        actor_user_id=1,
        operation_token=uuid4(),
        code=" shirt_new ",
        display_name="Shirt",
        status="enabled",
        aliases=(),
    )
    assert result.category_id == 7
    assert result.code == "SHIRT_NEW"
    writes = [(str(c.args[0]), c.args[1]) for c in connection.execute.call_args_list]
    assert not any("UPDATE product_catalog_style_members" in sql for sql, _ in writes)
    audit = next(
        params for sql, params in writes if "INSERT INTO catalog_audit_events" in sql
    )
    assert '"previous_code":"SHIRT"' in audit["payload"]
    assert '"code":"SHIRT_NEW"' in audit["payload"]


def test_rename_rejects_other_category_alias_before_write() -> None:
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "code": "SHIRT"
    }
    connection.scalar.return_value = 1
    with pytest.raises(CatalogCategoryError, match="catalog_category_conflict"):
        MySqlCatalogCategoryService(engine).update(
            site_id=1,
            category_id=7,
            actor_user_id=1,
            operation_token=uuid4(),
            code="DRESS",
            display_name="Shirt",
            status="enabled",
            aliases=(),
        )
    assert not any(
        "UPDATE" in str(c.args[0]).split("WHERE")[0]
        for c in connection.execute.call_args_list
    )


@pytest.mark.parametrize(
    "parent_id,category_id,rows",
    [
        (7, 7, [{"id": 7, "parent_category_id": None, "status": "enabled"}]),
        (8, 7, [{"id": 8, "parent_category_id": 9, "status": "enabled"}]),
        (8, 7, [{"id": 8, "parent_category_id": None, "status": "disabled"}]),
        (
            8,
            7,
            [
                {"id": 8, "parent_category_id": None, "status": "enabled"},
                {"id": 9, "parent_category_id": 7, "status": "enabled"},
            ],
        ),
    ],
)
def test_hierarchy_rejects_cycles_third_level_disabled_parent_and_moving_root(
    parent_id: int, category_id: int, rows: list[dict[str, object]]
) -> None:
    from app.catalog.category_service import _check_parent

    connection = MagicMock()
    connection.execute.return_value.mappings.return_value.all.return_value = rows
    with pytest.raises(CatalogCategoryError):
        _check_parent(connection, 1, parent_id, category_id)
