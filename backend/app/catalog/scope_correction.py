# ruff: noqa: E501
"""Offline administrator repair of a mistaken initial source confirmation.

No runtime write grant or HTTP mutation endpoint. Apply requires the maintenance
identity and explicit quiescence acknowledgement; database table locks serialize
against every writer, including a process started during maintenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.catalog.canonical_json import canonical_json_bytes


class CorrectionRejected(ValueError):
    pass


@dataclass(frozen=True)
class Correction:
    site_id: int
    scope_id: int
    actor_username: str
    expected_revision: int
    expected_old_key: str
    new_key: str
    new_display_name: str
    reason: str
    evidence_url: str
    operation_token: str

    def validate(self) -> None:
        if any(
            type(v) is not int or v < 1
            for v in (self.site_id, self.scope_id, self.expected_revision)
        ):
            raise CorrectionRejected("invalid_identity_or_revision")
        for value, limit in (
            (self.actor_username, 255),
            (self.expected_old_key, 255),
            (self.new_key, 255),
            (self.new_display_name, 128),
            (self.reason, 1000),
            (self.evidence_url, 1000),
        ):
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
                or len(value) > limit
                or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)
            ):
                raise CorrectionRejected("invalid_input")
        if (
            UUID(self.operation_token).version != 4
            or self.new_key == self.expected_old_key
        ):
            raise CorrectionRejected("invalid_correction")
        if not self.evidence_url.startswith("https://"):
            raise CorrectionRejected("https_evidence_required")

    def digest(self) -> bytes:
        return hashlib.sha256(canonical_json_bytes(asdict(self))).digest()


def _key(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def execute(
    engine: Engine, command: Correction, *, apply: bool = False, quiesced: bool = False
) -> dict[str, Any]:
    command.validate()
    if apply and not quiesced:
        raise CorrectionRejected("stop_lan_writers_before_apply")
    raw = engine.raw_connection()
    cur = raw.cursor()
    locked = False
    try:
        # LOCK TABLES implicitly commits: use a fresh dedicated connection only.
        cur.execute("SET SESSION lock_wait_timeout=10")
        cur.execute("SET SESSION innodb_lock_wait_timeout=10")
        cur.execute("SET autocommit=0")
        if apply:
            cur.execute(
                "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'"
            )
            tables = [row[0] for row in cur.fetchall()]
            if not tables or any(not re.fullmatch(r"[A-Za-z0-9_]+", t) for t in tables):
                raise CorrectionRejected("unexpected_schema")
            cur.execute(
                "LOCK TABLES " + ", ".join(f"`{t}` WRITE" for t in sorted(tables))
            )
            locked = True
        else:
            cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
        cur.execute("SELECT version_num FROM alembic_version")
        if cur.fetchall() not in ((("0029",),), (("0030",),)):
            raise CorrectionRejected("requires_schema_0029_or_0030")
        cur.execute(
            "SELECT users.id FROM users JOIN user_roles ON user_roles.user_id=users.id JOIN roles ON roles.id=user_roles.role_id WHERE users.username_normalized=%s AND users.status='active' AND roles.code='admin'",
            (command.actor_username,),
        )
        actors = cur.fetchall()
        if len(actors) != 1:
            raise CorrectionRejected("active_administrator_required")
        actor = actors[0][0]
        cur.execute("SELECT id FROM sites WHERE status='active'")
        if cur.fetchall() != ((command.site_id,),):
            raise CorrectionRejected("single_active_site_required")
        cur.execute(
            "SELECT operation_digest,evidence FROM report_source_scope_corrections WHERE operation_token=%s",
            (UUID(command.operation_token).bytes,),
        )
        prior = cur.fetchone()
        if prior:
            if bytes(prior[0]) != command.digest():
                raise CorrectionRejected("operation_token_conflict")
            return {
                "status": "replayed",
                "evidence": json.loads(prior[1])
                if isinstance(prior[1], str)
                else prior[1],
            }
        cur.execute(
            "SELECT seller_account_scope_key,seller_account_display_name,marketplace_scope_code FROM report_source_scopes WHERE id=%s AND site_id=%s",
            (command.scope_id, command.site_id),
        )
        scope = cur.fetchone()
        if (
            not scope
            or bytes(scope[0]) != _key(command.expected_old_key)
            or scope[2] != "amazon_us"
        ):
            raise CorrectionRejected("source_identity_changed")
        cur.execute(
            "SELECT COUNT(*) FROM report_source_scope_corrections WHERE report_source_scope_id=%s",
            (command.scope_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise CorrectionRejected("count_unavailable")
        if row[0]:
            raise CorrectionRejected("already_corrected_requires_separate_review")
        cur.execute(
            "SELECT site_config_versions.id,version_number,source_timezone,reporting_timezone,currency_code FROM site_config_versions JOIN site_current_configs ON site_current_configs.current_config_version_id=site_config_versions.id AND site_current_configs.site_id=site_config_versions.site_id WHERE site_current_configs.site_id=%s",
            (command.site_id,),
        )
        config = cur.fetchone()
        if not config or config[1] != command.expected_revision:
            raise CorrectionRejected("site_revision_changed")
        blockers = (
            "publication_snapshots",
            "return_dedup_staging_jobs",
            "return_dedup_group_revisions",
            "return_dedup_snapshots",
            "product_catalog_versions",
            "product_catalog_mappings",
            "product_catalog_exclusions",
            "catalog_exports",
            "catalog_imports",
            "catalog_jobs",
            "catalog_draft_identity_reservations",
        )
        for table in blockers:
            cur.execute(
                f"SELECT COUNT(*) FROM `{table}` WHERE site_id=%s", (command.site_id,)
            )
            count = cur.fetchone()
            if count is None:
                raise CorrectionRejected("count_unavailable")
            if count[0]:
                raise CorrectionRejected("downstream_evidence_exists:" + table)
        cur.execute(
            "SELECT current_snapshot_id,dedup_publication_revision FROM return_dedup_publications WHERE site_id=%s AND report_source_scope_id=%s",
            (command.site_id, command.scope_id),
        )
        if any(r[0] is not None or r[1] != 0 for r in cur.fetchall()):
            raise CorrectionRejected("dedup_pointer_not_empty")
        preserved = {}
        for table in ("report_dataset_scope_assignments", "report_source_keys"):
            cur.execute(
                f"SELECT * FROM `{table}` WHERE site_id=%s AND report_source_scope_id=%s ORDER BY id",
                (command.site_id, command.scope_id),
            )
            rows = cur.fetchall()
            preserved[table] = {
                "count": len(rows),
                "sha256": hashlib.sha256(repr(rows).encode()).hexdigest(),
            }
        evidence = {
            "site_id": command.site_id,
            "scope_id": command.scope_id,
            "old_display_name": scope[1],
            "old_key_sha256": bytes(scope[0]).hex(),
            "new_display_name": command.new_display_name,
            "new_key_sha256": _key(command.new_key).hex(),
            "actor_user_id": actor,
            "reason": command.reason,
            "evidence_url": command.evidence_url,
            "old_config_id": config[0],
            "old_revision": config[1],
            "new_revision": config[1] + 1,
            "preserved": preserved,
        }
        if not apply:
            return {"status": "preview", "evidence": evidence}
        now = datetime.now(UTC).replace(tzinfo=None)
        cur.execute(
            "INSERT INTO site_config_versions(site_id,version_number,source_timezone,reporting_timezone,currency_code,effective_at,change_reason,created_by_user_id,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                command.site_id,
                config[1] + 1,
                config[2],
                config[3],
                config[4],
                now,
                command.reason,
                actor,
                now,
            ),
        )
        new_config = cur.lastrowid
        evidence["new_config_id"] = new_config
        payload = canonical_json_bytes(evidence).decode("utf-8")
        cur.execute(
            "INSERT INTO report_source_scope_corrections(report_source_scope_id,site_id,operation_token,operation_digest,seller_account_scope_key,seller_account_display_name,actor_user_id,evidence,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                command.scope_id,
                command.site_id,
                UUID(command.operation_token).bytes,
                command.digest(),
                _key(command.new_key),
                command.new_display_name,
                actor,
                payload,
                now,
            ),
        )
        cur.execute(
            "UPDATE site_current_configs SET current_config_version_id=%s,updated_by_user_id=%s,updated_at=%s WHERE site_id=%s AND current_config_version_id=%s",
            (new_config, actor, now, command.site_id, config[0]),
        )
        if cur.rowcount != 1:
            raise CorrectionRejected("site_revision_changed")
        cur.execute(
            "INSERT INTO catalog_audit_events(site_id,actor_user_id,event_kind,resource_kind,resource_id,operation_token,safe_payload_json,event_digest,created_at) VALUES(%s,%s,'catalog.source_scope_corrected','report_source_scope',%s,%s,%s,%s,%s)",
            (
                command.site_id,
                actor,
                command.scope_id,
                UUID(command.operation_token).bytes,
                payload,
                hashlib.sha256(payload.encode()).digest(),
                now,
            ),
        )
        # Verify retained identities before committing, under the same table locks.
        for table, expected in preserved.items():
            cur.execute(
                f"SELECT * FROM `{table}` WHERE site_id=%s AND report_source_scope_id=%s ORDER BY id",
                (command.site_id, command.scope_id),
            )
            rows = cur.fetchall()
            if expected != {
                "count": len(rows),
                "sha256": hashlib.sha256(repr(rows).encode()).hexdigest(),
            }:
                raise CorrectionRejected("retained_identity_changed")
        raw.commit()
        return {"status": "applied", "evidence": evidence}
    finally:
        raw.rollback()
        if locked:
            cur.execute("UNLOCK TABLES")
        cur.close()
        raw.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--writers-stopped", action="store_true")
    args = parser.parse_args()
    from app.deployment.entrypoint import _configure_process_environment

    _configure_process_environment(accounts=frozenset({"migrator"}))
    engine = sa.create_engine(
        os.environ["APP_MIGRATION_DATABASE_URL"], hide_parameters=True
    )
    try:
        result = execute(
            engine,
            Correction(**json.loads(args.command.read_text(encoding="utf-8-sig"))),
            apply=args.apply,
            quiesced=args.writers_stopped,
        )
        print(json.dumps(result, ensure_ascii=False))
    except CorrectionRejected as error:
        print(json.dumps({"status": "rejected", "reason": str(error)}))
        raise SystemExit(1) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
