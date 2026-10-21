from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.mysql

CATALOG_TABLES = frozenset(
    {
        "report_source_scopes",
        "report_dataset_scope_assignments",
        "report_source_keys",
        "report_publication_revisions",
        "publication_snapshots",
        "publication_snapshot_members",
        "return_dedup_group_revisions",
        "return_dedup_group_members",
        "return_dedup_snapshots",
        "return_dedup_snapshot_groups",
        "return_dedup_publications",
        "return_dedup_staging_jobs",
        "return_dedup_staging_members",
        "fact_snapshot_tuples",
        "product_styles",
        "product_style_revisions",
        "product_skus",
        "product_sku_revisions",
        "product_identity_key_reservations",
        "product_catalog_versions",
        "product_catalog_style_members",
        "product_catalog_sku_members",
        "product_catalog_mappings",
        "product_catalog_exclusions",
        "product_catalog_publications",
        "product_catalog_publication_events",
        "catalog_source_refs",
        "catalog_source_evidence",
        "catalog_exports",
        "catalog_export_payloads",
        "catalog_imports",
        "catalog_parse_attempts",
        "catalog_import_rows",
        "catalog_import_issues",
        "catalog_validation_runs",
        "catalog_approval_projections",
        "catalog_command_claims",
        "catalog_command_effects",
        "catalog_audit_events",
        "catalog_jobs",
    }
)

IMMUTABLE_TABLES = CATALOG_TABLES - {
    "return_dedup_publications",
    "return_dedup_staging_jobs",
    "report_publication_revisions",
    "product_styles",
    "product_skus",
    "product_catalog_publications",
    "catalog_exports",
    "catalog_imports",
    "catalog_jobs",
}

TRANSITION_TABLES = {
    "publication_snapshots",
    "catalog_parse_attempts",
    "catalog_command_claims",
}

REQUIRED_COMPOSITE_REFERENCE_KEYS = frozenset(
    {
        ("publication_snapshots", ("id", "site_id")),
        (
            "return_dedup_snapshots",
            ("id", "site_id", "report_source_scope_id"),
        ),
        ("fact_snapshot_tuples", ("id", "site_id")),
    }
)


def _catalog_tables(connection: sa.Connection) -> frozenset[str]:
    return frozenset(
        str(value)
        for value in connection.scalars(
            sa.text(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name IN :table_names
                """
            ).bindparams(sa.bindparam("table_names", expanding=True)),
            {"table_names": tuple(CATALOG_TABLES)},
        )
    )


def test_catalog_schema_has_complete_tables_triggers_and_binary_keys(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    with mysql_engine.connect() as connection:
        assert _catalog_tables(connection) == CATALOG_TABLES
        comments = dict(
            connection.execute(
                sa.text(
                    """
                    SELECT table_name, table_comment
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name IN :table_names
                    """
                ).bindparams(sa.bindparam("table_names", expanding=True)),
                {"table_names": tuple(CATALOG_TABLES)},
            )
            .tuples()
            .all()
        )
        assert all(
            str(comments[table]).startswith("clsen-0022:")
            and len(str(comments[table])) == len("clsen-0022:") + 64
            for table in CATALOG_TABLES
        )
        triggers = frozenset(
            (str(table_name), str(operation).upper())
            for table_name, operation in connection.execute(
                sa.text(
                    """
                    SELECT event_object_table, event_manipulation
                    FROM information_schema.triggers
                    WHERE trigger_schema = DATABASE()
                      AND event_object_table IN :table_names
                    """
                ).bindparams(sa.bindparam("table_names", expanding=True)),
                {"table_names": tuple(CATALOG_TABLES)},
            )
            .tuples()
            .all()
        )
        expected_triggers = frozenset(
            (table, operation)
            for table in IMMUTABLE_TABLES | TRANSITION_TABLES
            for operation in ("UPDATE", "DELETE")
        ) | {("return_dedup_staging_jobs", "UPDATE")}
        assert triggers == expected_triggers
        staging_update_trigger_names = frozenset(
            str(trigger_name)
            for trigger_name in connection.scalars(
                sa.text(
                    """
                    SELECT trigger_name
                    FROM information_schema.triggers
                    WHERE trigger_schema = DATABASE()
                      AND event_object_table = 'return_dedup_staging_jobs'
                      AND event_manipulation = 'UPDATE'
                    """
                )
            )
        )
        assert staging_update_trigger_names == {"return_initialization_identity_guard"}
        trigger_name, table_name, operation, timing, initialization_guard = (
            connection.execute(
                sa.text(
                    """
                    SELECT trigger_name, event_object_table, event_manipulation,
                           action_timing, action_statement
                    FROM information_schema.triggers
                    WHERE trigger_schema = DATABASE()
                      AND trigger_name = 'return_initialization_identity_guard'
                    """
                )
            ).one()
        )
        assert (
            str(trigger_name),
            str(table_name),
            str(operation).upper(),
            str(timing).upper(),
        ) == (
            "return_initialization_identity_guard",
            "return_dedup_staging_jobs",
            "UPDATE",
            "BEFORE",
        )
        normalized_initialization_guard = "".join(
            str(initialization_guard).casefold().split()
        )
        assert "old.initialization_revision<=>new.initialization_revision" in (
            normalized_initialization_guard
        )
        assert "initializationidentityisimmutable" in normalized_initialization_guard
        binary_columns = dict(
            connection.execute(
                sa.text(
                    """
                    SELECT CONCAT(table_name, '.', column_name), column_type
                    FROM information_schema.columns
                    WHERE table_schema = DATABASE()
                      AND (column_name LIKE '%_sha256'
                           OR column_name LIKE '%_digest'
                           OR column_name LIKE '%_key_bytes')
                      AND table_name IN :table_names
                    """
                ).bindparams(sa.bindparam("table_names", expanding=True)),
                {"table_names": tuple(CATALOG_TABLES)},
            )
            .tuples()
            .all()
        )
        assert binary_columns
        assert all(
            str(column_type).casefold().startswith(("binary(", "varbinary("))
            for column_type in binary_columns.values()
        )
        unique_index_columns: dict[tuple[str, str], list[str]] = {}
        for table_name, index_name, column_name in connection.execute(
            sa.text(
                """
                SELECT table_name, index_name, column_name
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                  AND non_unique = 0
                  AND table_name IN :table_names
                ORDER BY table_name, index_name, seq_in_index
                """
            ).bindparams(sa.bindparam("table_names", expanding=True)),
            {
                "table_names": tuple(
                    table_name
                    for table_name, _columns in REQUIRED_COMPOSITE_REFERENCE_KEYS
                )
            },
        ).tuples():
            unique_index_columns.setdefault(
                (str(table_name), str(index_name)), []
            ).append(str(column_name))
        assert (
            frozenset(
                (table_name, tuple(columns))
                for (table_name, _index_name), columns in unique_index_columns.items()
            )
            >= REQUIRED_COMPOSITE_REFERENCE_KEYS
        )
        analytics_index = tuple(
            str(value)
            for value in connection.scalars(
                sa.text(
                    """
                    SELECT column_name FROM information_schema.statistics
                    WHERE table_schema = DATABASE()
                      AND table_name = 'version_rows'
                      AND index_name = 'ix_version_rows_analytics_active'
                    ORDER BY seq_in_index
                    """
                )
            )
        )
        assert analytics_index == ("version_id", "row_state", "id")


def test_catalog_partial_migration_recreates_only_the_missing_suffix(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "0028")
    command.downgrade(alembic_config, "0022")
    try:
        with mysql_engine.begin() as connection:
            connection.execute(sa.text("DROP TABLE catalog_jobs"))
            connection.execute(
                sa.text("UPDATE alembic_version SET version_num = '0021'")
            )

        command.upgrade(alembic_config, "0022")

        with mysql_engine.connect() as connection:
            assert _catalog_tables(connection) == CATALOG_TABLES
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0022"
            )
    finally:
        command.upgrade(alembic_config, "0028")


def test_catalog_partial_migration_rejects_a_mutated_sealed_table(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "0028")
    command.downgrade(alembic_config, "0022")
    try:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "CREATE INDEX ix_catalog_jobs_unexpected "
                    "ON catalog_jobs (updated_at)"
                )
            )
            connection.execute(
                sa.text("UPDATE alembic_version SET version_num = '0021'")
            )

        with pytest.raises(
            RuntimeError,
            match="incompatible pre-existing 0022 catalog schema",
        ):
            command.upgrade(alembic_config, "0022")
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text("DROP INDEX ix_catalog_jobs_unexpected ON catalog_jobs")
            )
        command.upgrade(alembic_config, "0028")
