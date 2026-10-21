from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.auth.passwords import hash_password, verify_password
from app.db.settings import DatabaseSettings
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from tests.integration.historical_schema_support import (
    create_historical_schema_engine,
)

pytestmark = pytest.mark.mysql


@pytest.fixture(name="mysql_engine")
def _historical_schema_engine(historical_mysql_engine: Engine) -> Engine:
    return historical_mysql_engine


@pytest.fixture()
def admin_runtime_engine(
    mysql_settings: DatabaseSettings,
    request: pytest.FixtureRequest,
) -> Iterator[Engine]:
    value = os.getenv("APP_TEST_RUNTIME_DATABASE_URL")
    if value is None or not value.strip():
        if request.config.getoption("--require-mysql"):
            raise pytest.UsageError(
                "APP_TEST_RUNTIME_DATABASE_URL is required by --require-mysql"
            )
        pytest.skip("APP_TEST_RUNTIME_DATABASE_URL is not configured")
    runtime_settings = DatabaseSettings.from_url(
        value,
        pool_size=1,
        max_overflow=0,
    )
    migration_location = (
        (mysql_settings.url.host or "").casefold(),
        mysql_settings.url.port or 3306,
        mysql_settings.url.database,
    )
    runtime_location = (
        (runtime_settings.url.host or "").casefold(),
        runtime_settings.url.port or 3306,
        runtime_settings.url.database,
    )
    if runtime_location != migration_location:
        pytest.fail(
            "APP_TEST_RUNTIME_DATABASE_URL must target the same database as "
            "APP_TEST_DATABASE_URL",
            pytrace=False,
        )
    if runtime_settings.url.username == mysql_settings.url.username:
        pytest.fail(
            "the runtime and migration test URLs must use different accounts",
            pytrace=False,
        )
    engine = create_historical_schema_engine(runtime_settings)
    try:
        yield engine
    finally:
        engine.dispose()


def _assert_runtime_command_denied(
    engine: Engine,
    *,
    statement: str,
    operation_token: bytes,
) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with pytest.raises(DBAPIError) as captured:
                connection.execute(
                    sa.text(statement),
                    {"operation_token": operation_token},
                )
            original = captured.value.orig
            assert original is not None
            assert int(original.args[0]) in {1142, 1143}
        finally:
            transaction.rollback()


def test_admin_operation_migration_roundtrips_empty_ledgers(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "0028")
    with mysql_engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
            == "0028"
        )
        assert (
            connection.scalar(sa.text("SELECT COUNT(*) FROM admin_operation_tokens"))
            == 0
        )
        assert (
            connection.scalar(sa.text("SELECT COUNT(*) FROM admin_operation_results"))
            == 0
        )

    try:
        command.downgrade(alembic_config, "0010")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0010"
            )
            tables = set(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = DATABASE()
                          AND table_name IN (
                              'admin_operation_tokens',
                              'admin_operation_results'
                          )
                        """
                    )
                )
            )
            assert tables == set()

        command.upgrade(alembic_config, "0011")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0011"
            )
            triggers = set(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT trigger_name
                        FROM information_schema.triggers
                        WHERE trigger_schema = DATABASE()
                          AND event_object_table IN (
                              'admin_operation_tokens',
                              'admin_operation_results'
                          )
                        """
                    )
                )
            )
            assert triggers == {
                "trg_admin_operation_tokens_no_update",
                "trg_admin_operation_tokens_no_delete",
                "trg_admin_operation_results_no_update",
                "trg_admin_operation_results_no_delete",
            }
    finally:
        command.upgrade(alembic_config, "0028")


def test_runtime_can_append_but_cannot_mutate_admin_operation_ledgers(
    alembic_config: Config,
    mysql_engine: Engine,
    admin_runtime_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    username = f"admin-operation-permission-{uuid4().hex}"
    operation_token = uuid4().bytes
    operation_digest = uuid4().bytes + uuid4().bytes
    with mysql_engine.begin() as connection:
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO users (
                    username_normalized, display_name, password_hash, status,
                    created_at, updated_at
                ) VALUES (
                    :username, 'Admin Operation Permission', :password_hash,
                    'active', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                )
                """
            ),
            {
                "username": username,
                "password_hash": hash_password("permission test password"),
            },
        )
        assert inserted.lastrowid is not None
        actor_user_id = int(inserted.lastrowid)

    try:
        with admin_runtime_engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO admin_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, secret_verifier, registered_at
                    ) VALUES (
                        :operation_token, 'create_site_config_version',
                        :operation_digest, :actor_user_id, NULL,
                        UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "operation_token": operation_token,
                    "operation_digest": operation_digest,
                    "actor_user_id": actor_user_id,
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO admin_operation_results (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, response_schema_version,
                        response_status_code, response_payload, completed_at
                    ) VALUES (
                        :operation_token, 'create_site_config_version',
                        :operation_digest, :actor_user_id, 1, 201, '{}',
                        UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "operation_token": operation_token,
                    "operation_digest": operation_digest,
                    "actor_user_id": actor_user_id,
                },
            )
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT response_status_code "
                        "FROM admin_operation_results "
                        "WHERE operation_token = :operation_token"
                    ),
                    {"operation_token": operation_token},
                )
                == 201
            )

        for table_name in (
            "admin_operation_tokens",
            "admin_operation_results",
        ):
            _assert_runtime_command_denied(
                admin_runtime_engine,
                statement=(
                    f"UPDATE {table_name} SET operation_kind = operation_kind "
                    "WHERE operation_token = :operation_token"
                ),
                operation_token=operation_token,
            )
            _assert_runtime_command_denied(
                admin_runtime_engine,
                statement=(
                    f"DELETE FROM {table_name} WHERE operation_token = :operation_token"
                ),
                operation_token=operation_token,
            )
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "DELETE FROM admin_operation_results "
                    "WHERE operation_token = :operation_token"
                ),
                {"operation_token": operation_token},
            )
            connection.execute(
                sa.text(
                    "DELETE FROM admin_operation_tokens "
                    "WHERE operation_token = :operation_token"
                ),
                {"operation_token": operation_token},
            )
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :actor_user_id"),
                {"actor_user_id": actor_user_id},
            )


def test_runtime_can_store_only_the_fixed_admin_operation_secret_marker(
    alembic_config: Config,
    mysql_engine: Engine,
    admin_runtime_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    username = f"admin-operation-marker-{uuid4().hex}"
    valid_tokens = [uuid4().bytes for _ in range(4)]
    with mysql_engine.begin() as connection:
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO users (
                    username_normalized, display_name, password_hash, status,
                    created_at, updated_at
                ) VALUES (
                    :username, 'Admin Operation Marker', :password_hash,
                    'active', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                )
                """
            ),
            {
                "username": username,
                "password_hash": hash_password("marker constraint password"),
            },
        )
        assert inserted.lastrowid is not None
        actor_user_id = int(inserted.lastrowid)

    valid_cases = (
        ("create_user", "$secret-not-stored$v1$"),
        ("update_user", None),
        ("update_user", "$secret-not-stored$v1$"),
        ("create_site_config_version", None),
    )
    invalid_cases = (
        ("create_user", None),
        ("create_user", "$argon2id$secret-material"),
        ("update_user", "$hmac-sha256$v2$secret-material"),
        ("create_site_config_version", "$secret-not-stored$v1$"),
    )
    try:
        with admin_runtime_engine.begin() as connection:
            for operation_token, (operation_kind, secret_verifier) in zip(
                valid_tokens, valid_cases, strict=True
            ):
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO admin_operation_tokens (
                            operation_token, operation_kind, operation_digest,
                            actor_user_id, secret_verifier, registered_at
                        ) VALUES (
                            :operation_token, :operation_kind, :operation_digest,
                            :actor_user_id, :secret_verifier, UTC_TIMESTAMP(6)
                        )
                        """
                    ),
                    {
                        "operation_token": operation_token,
                        "operation_kind": operation_kind,
                        "operation_digest": uuid4().bytes + uuid4().bytes,
                        "actor_user_id": actor_user_id,
                        "secret_verifier": secret_verifier,
                    },
                )

        for operation_kind, secret_verifier in invalid_cases:
            with admin_runtime_engine.connect() as connection:
                transaction = connection.begin()
                try:
                    with pytest.raises(DBAPIError) as captured:
                        connection.execute(
                            sa.text(
                                """
                                INSERT INTO admin_operation_tokens (
                                    operation_token, operation_kind,
                                    operation_digest, actor_user_id,
                                    secret_verifier, registered_at
                                ) VALUES (
                                    :operation_token, :operation_kind,
                                    :operation_digest, :actor_user_id,
                                    :secret_verifier, UTC_TIMESTAMP(6)
                                )
                                """
                            ),
                            {
                                "operation_token": uuid4().bytes,
                                "operation_kind": operation_kind,
                                "operation_digest": uuid4().bytes + uuid4().bytes,
                                "actor_user_id": actor_user_id,
                                "secret_verifier": secret_verifier,
                            },
                        )
                    original = captured.value.orig
                    assert original is not None
                    assert int(original.args[0]) == 3819
                finally:
                    transaction.rollback()
    finally:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "DELETE FROM admin_operation_tokens "
                    "WHERE actor_user_id = :actor_user_id"
                ),
                {"actor_user_id": actor_user_id},
            )
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :actor_user_id"),
                {"actor_user_id": actor_user_id},
            )


def test_stage_twelve_scrubs_legacy_verifiers_and_preserves_write_guards(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.downgrade(alembic_config, "0011")
    username = f"legacy-admin-operation-{uuid4().hex}"
    password = "legacy operation password"
    legacy_password_hash = hash_password(password)
    operation_token = uuid4().bytes
    actor_user_id: int | None = None
    try:
        with mysql_engine.begin() as connection:
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status,
                        created_at, updated_at
                    ) VALUES (
                        :username, 'Legacy Admin Operation', :password_hash,
                        'active', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {"username": username, "password_hash": legacy_password_hash},
            )
            assert inserted.lastrowid is not None
            actor_user_id = int(inserted.lastrowid)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO admin_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, secret_verifier, registered_at
                    ) VALUES (
                        :operation_token, 'create_user', :operation_digest,
                        :actor_user_id, :secret_verifier, UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "operation_token": operation_token,
                    "operation_digest": uuid4().bytes + uuid4().bytes,
                    "actor_user_id": actor_user_id,
                    "secret_verifier": legacy_password_hash,
                },
            )

        command.upgrade(alembic_config, "0012")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0012"
            )
            scrubbed, stored_user_hash = connection.execute(
                sa.text(
                    """
                    SELECT tokens.secret_verifier, users.password_hash
                    FROM admin_operation_tokens AS tokens
                    INNER JOIN users ON users.id = tokens.actor_user_id
                    WHERE tokens.operation_token = :operation_token
                    """
                ),
                {"operation_token": operation_token},
            ).one()
            triggers = set(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT trigger_name
                        FROM information_schema.triggers
                        WHERE trigger_schema = DATABASE()
                          AND event_object_table IN (
                              'admin_operation_tokens',
                              'admin_operation_results'
                          )
                        """
                    )
                )
            )
        assert scrubbed == "$legacy-untrusted$v1$"
        assert isinstance(stored_user_hash, str)
        assert verify_password(stored_user_hash, password)
        assert triggers == {
            "trg_admin_operation_tokens_no_update",
            "trg_admin_operation_tokens_no_delete",
            "trg_admin_operation_results_no_update",
            "trg_admin_operation_results_no_delete",
        }

        command.downgrade(alembic_config, "0011")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT secret_verifier FROM admin_operation_tokens "
                        "WHERE operation_token = :operation_token"
                    ),
                    {"operation_token": operation_token},
                )
                == "$legacy-untrusted$v1$"
            )
    finally:
        command.upgrade(alembic_config, "0028")
        if actor_user_id is not None:
            with mysql_engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "DELETE FROM admin_operation_tokens "
                        "WHERE operation_token = :operation_token"
                    ),
                    {"operation_token": operation_token},
                )
                connection.execute(
                    sa.text("DELETE FROM users WHERE id = :actor_user_id"),
                    {"actor_user_id": actor_user_id},
                )


def test_stage_fourteen_replaces_all_secret_material_with_a_fixed_marker(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.downgrade(alembic_config, "0013")
    username = f"secret-marker-admin-operation-{uuid4().hex}"
    actor_user_id: int | None = None
    operation_tokens = [uuid4().bytes for _ in range(4)]
    legacy_values = [
        hash_password("legacy password material"),
        f"$hmac-sha256$v1${'a' * 64}",
        f"$hmac-sha256$v2${'b' * 64}",
        "malformed verifier material",
    ]
    try:
        with mysql_engine.begin() as connection:
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status,
                        created_at, updated_at
                    ) VALUES (
                        :username, 'Secret Marker Admin Operation', :password_hash,
                        'active', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {"username": username, "password_hash": hash_password("temporary")},
            )
            assert inserted.lastrowid is not None
            actor_user_id = int(inserted.lastrowid)
            for operation_token, legacy_value in zip(
                operation_tokens, legacy_values, strict=True
            ):
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO admin_operation_tokens (
                            operation_token, operation_kind, operation_digest,
                            actor_user_id, secret_verifier, registered_at
                        ) VALUES (
                            :operation_token, 'create_user', :operation_digest,
                            :actor_user_id, :secret_verifier, UTC_TIMESTAMP(6)
                        )
                        """
                    ),
                    {
                        "operation_token": operation_token,
                        "operation_digest": uuid4().bytes + uuid4().bytes,
                        "actor_user_id": actor_user_id,
                        "secret_verifier": legacy_value,
                    },
                )

        command.upgrade(alembic_config, "0014")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0014"
            )
            markers = list(
                connection.scalars(
                    sa.text(
                        "SELECT secret_verifier FROM admin_operation_tokens "
                        "WHERE actor_user_id = :actor_user_id ORDER BY operation_token"
                    ),
                    {"actor_user_id": actor_user_id},
                )
            )
        assert markers == ["$secret-not-stored$v1$"] * len(legacy_values)

        command.downgrade(alembic_config, "0013")
        with mysql_engine.connect() as connection:
            markers_after_downgrade = list(
                connection.scalars(
                    sa.text(
                        "SELECT secret_verifier FROM admin_operation_tokens "
                        "WHERE actor_user_id = :actor_user_id ORDER BY operation_token"
                    ),
                    {"actor_user_id": actor_user_id},
                )
            )
        assert markers_after_downgrade == markers
    finally:
        command.upgrade(alembic_config, "0028")
        if actor_user_id is not None:
            with mysql_engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "DELETE FROM admin_operation_tokens "
                        "WHERE actor_user_id = :actor_user_id"
                    ),
                    {"actor_user_id": actor_user_id},
                )
                connection.execute(
                    sa.text("DELETE FROM users WHERE id = :actor_user_id"),
                    {"actor_user_id": actor_user_id},
                )


def test_stage_fifteen_enforces_the_marker_domain_and_roundtrips_schema(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.downgrade(alembic_config, "0014")
    username = f"marker-domain-admin-operation-{uuid4().hex}"
    actor_user_id: int | None = None
    operation_tokens = [uuid4().bytes for _ in range(3)]
    legacy_cases = (
        ("create_user", hash_password("legacy secret material")),
        ("update_user", f"$hmac-sha256$v2${'a' * 64}"),
        ("update_user", None),
    )
    try:
        with mysql_engine.begin() as connection:
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status,
                        created_at, updated_at
                    ) VALUES (
                        :username, 'Marker Domain Admin Operation',
                        :password_hash, 'active',
                        UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "username": username,
                    "password_hash": hash_password("temporary"),
                },
            )
            assert inserted.lastrowid is not None
            actor_user_id = int(inserted.lastrowid)
            for operation_token, (operation_kind, secret_verifier) in zip(
                operation_tokens, legacy_cases, strict=True
            ):
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO admin_operation_tokens (
                            operation_token, operation_kind, operation_digest,
                            actor_user_id, secret_verifier, registered_at
                        ) VALUES (
                            :operation_token, :operation_kind, :operation_digest,
                            :actor_user_id, :secret_verifier, UTC_TIMESTAMP(6)
                        )
                        """
                    ),
                    {
                        "operation_token": operation_token,
                        "operation_kind": operation_kind,
                        "operation_digest": uuid4().bytes + uuid4().bytes,
                        "actor_user_id": actor_user_id,
                        "secret_verifier": secret_verifier,
                    },
                )

        command.upgrade(alembic_config, "0015")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0015"
            )
            stored_values = [
                connection.scalar(
                    sa.text(
                        "SELECT secret_verifier FROM admin_operation_tokens "
                        "WHERE operation_token = :operation_token"
                    ),
                    {"operation_token": operation_token},
                )
                for operation_token in operation_tokens
            ]
            enforced_checks = set(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT constraint_name
                        FROM information_schema.table_constraints
                        WHERE constraint_schema = DATABASE()
                          AND table_name = 'admin_operation_tokens'
                          AND constraint_type = 'CHECK'
                          AND enforced = 'YES'
                        """
                    )
                )
            )
            triggers = set(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT trigger_name
                        FROM information_schema.triggers
                        WHERE trigger_schema = DATABASE()
                          AND event_object_table IN (
                              'admin_operation_tokens',
                              'admin_operation_results'
                          )
                        """
                    )
                )
            )
        assert stored_values == [
            "$secret-not-stored$v1$",
            "$secret-not-stored$v1$",
            None,
        ]
        assert {
            "ck_admin_operation_tokens_secret",
            "ck_admin_operation_tokens_secret_marker",
        }.issubset(enforced_checks)
        assert triggers == {
            "trg_admin_operation_tokens_no_update",
            "trg_admin_operation_tokens_no_delete",
            "trg_admin_operation_results_no_update",
            "trg_admin_operation_results_no_delete",
        }

        with mysql_engine.connect() as connection:
            transaction = connection.begin()
            try:
                with pytest.raises(DBAPIError) as captured:
                    connection.execute(
                        sa.text(
                            """
                            INSERT INTO admin_operation_tokens (
                                operation_token, operation_kind,
                                operation_digest, actor_user_id,
                                secret_verifier, registered_at
                            ) VALUES (
                                :operation_token, 'update_user',
                                :operation_digest, :actor_user_id,
                                '$argon2id$secret-material', UTC_TIMESTAMP(6)
                            )
                            """
                        ),
                        {
                            "operation_token": uuid4().bytes,
                            "operation_digest": uuid4().bytes + uuid4().bytes,
                            "actor_user_id": actor_user_id,
                        },
                    )
                original = captured.value.orig
                assert original is not None
                assert int(original.args[0]) == 3819
            finally:
                transaction.rollback()

        command.downgrade(alembic_config, "0014")
        with mysql_engine.connect() as connection:
            remaining_checks = set(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT constraint_name
                        FROM information_schema.table_constraints
                        WHERE constraint_schema = DATABASE()
                          AND table_name = 'admin_operation_tokens'
                          AND constraint_type = 'CHECK'
                        """
                    )
                )
            )
            triggers_after_downgrade = set(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT trigger_name
                        FROM information_schema.triggers
                        WHERE trigger_schema = DATABASE()
                          AND event_object_table IN (
                              'admin_operation_tokens',
                              'admin_operation_results'
                          )
                        """
                    )
                )
            )
            markers_after_downgrade = [
                connection.scalar(
                    sa.text(
                        "SELECT secret_verifier FROM admin_operation_tokens "
                        "WHERE operation_token = :operation_token"
                    ),
                    {"operation_token": operation_token},
                )
                for operation_token in operation_tokens
            ]
        assert "ck_admin_operation_tokens_secret" in remaining_checks
        assert "ck_admin_operation_tokens_secret_marker" not in remaining_checks
        assert triggers_after_downgrade == triggers
        assert markers_after_downgrade == stored_values
    finally:
        command.upgrade(alembic_config, "0028")
        if actor_user_id is not None:
            with mysql_engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "DELETE FROM admin_operation_tokens "
                        "WHERE actor_user_id = :actor_user_id"
                    ),
                    {"actor_user_id": actor_user_id},
                )
                connection.execute(
                    sa.text("DELETE FROM users WHERE id = :actor_user_id"),
                    {"actor_user_id": actor_user_id},
                )


def test_stage_fifteen_recovers_only_matching_partial_constraint_ddl(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    constraint_name = "ck_admin_operation_tokens_secret_marker"
    command.downgrade(alembic_config, "0014")
    try:
        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "ALTER TABLE admin_operation_tokens "
                    f"ADD CONSTRAINT {constraint_name} "
                    "CHECK (secret_verifier IS NULL OR "
                    "secret_verifier = '$secret-not-stored$v1$')"
                )
            )
        command.upgrade(alembic_config, "0015")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0015"
            )
            assert (
                connection.scalar(
                    sa.text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.table_constraints
                        WHERE constraint_schema = DATABASE()
                          AND table_name = 'admin_operation_tokens'
                          AND constraint_name = :constraint_name
                          AND constraint_type = 'CHECK'
                          AND enforced = 'YES'
                        """
                    ),
                    {"constraint_name": constraint_name},
                )
                == 1
            )

        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text(
                    f"ALTER TABLE admin_operation_tokens DROP CHECK {constraint_name}"
                )
            )
        command.downgrade(alembic_config, "0014")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0014"
            )

        with mysql_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "ALTER TABLE admin_operation_tokens "
                    f"ADD CONSTRAINT {constraint_name} "
                    "CHECK (secret_verifier IS NULL OR secret_verifier <> '')"
                )
            )
        with pytest.raises(RuntimeError, match="incompatible"):
            command.upgrade(alembic_config, "0015")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0014"
            )
    finally:
        command.downgrade(alembic_config, "0014")
        with mysql_engine.begin() as connection:
            if int(
                connection.scalar(
                    sa.text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.table_constraints
                        WHERE constraint_schema = DATABASE()
                          AND table_name = 'admin_operation_tokens'
                          AND constraint_name = :constraint_name
                        """
                    ),
                    {"constraint_name": constraint_name},
                )
                or 0
            ):
                connection.execute(
                    sa.text(
                        "ALTER TABLE admin_operation_tokens "
                        f"DROP CHECK {constraint_name}"
                    )
                )
        command.upgrade(alembic_config, "0028")


def test_stage_thirteen_scrubs_public_key_v1_tags_and_preserves_write_guards(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.downgrade(alembic_config, "0012")
    username = f"public-v1-admin-operation-{uuid4().hex}"
    operation_token = uuid4().bytes
    actor_user_id: int | None = None
    try:
        with mysql_engine.begin() as connection:
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status,
                        created_at, updated_at
                    ) VALUES (
                        :username, 'Public V1 Admin Operation', :password_hash,
                        'active', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {"username": username, "password_hash": hash_password("temporary")},
            )
            assert inserted.lastrowid is not None
            actor_user_id = int(inserted.lastrowid)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO admin_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, secret_verifier, registered_at
                    ) VALUES (
                        :operation_token, 'create_user', :operation_digest,
                        :actor_user_id, :secret_verifier, UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "operation_token": operation_token,
                    "operation_digest": uuid4().bytes + uuid4().bytes,
                    "actor_user_id": actor_user_id,
                    "secret_verifier": f"$hmac-sha256$v1${'a' * 64}",
                },
            )

        command.upgrade(alembic_config, "0013")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0013"
            )
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT secret_verifier FROM admin_operation_tokens "
                        "WHERE operation_token = :operation_token"
                    ),
                    {"operation_token": operation_token},
                )
                == "$legacy-untrusted$v1$"
            )
            triggers = set(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT trigger_name
                        FROM information_schema.triggers
                        WHERE trigger_schema = DATABASE()
                          AND event_object_table IN (
                              'admin_operation_tokens',
                              'admin_operation_results'
                          )
                        """
                    )
                )
            )
        assert triggers == {
            "trg_admin_operation_tokens_no_update",
            "trg_admin_operation_tokens_no_delete",
            "trg_admin_operation_results_no_update",
            "trg_admin_operation_results_no_delete",
        }

        command.downgrade(alembic_config, "0012")
        with mysql_engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT secret_verifier FROM admin_operation_tokens "
                        "WHERE operation_token = :operation_token"
                    ),
                    {"operation_token": operation_token},
                )
                == "$legacy-untrusted$v1$"
            )
    finally:
        command.upgrade(alembic_config, "0028")
        if actor_user_id is not None:
            with mysql_engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "DELETE FROM admin_operation_tokens "
                        "WHERE operation_token = :operation_token"
                    ),
                    {"operation_token": operation_token},
                )
                connection.execute(
                    sa.text("DELETE FROM users WHERE id = :actor_user_id"),
                    {"actor_user_id": actor_user_id},
                )
