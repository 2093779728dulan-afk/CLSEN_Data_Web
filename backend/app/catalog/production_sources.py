# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
"""Production identity evidence projected into the existing catalog draft workflow."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import Field, field_validator
from sqlalchemy.engine import Connection, Engine

from app.catalog.canonical_json import CanonicalValue, canonical_json_bytes
from app.catalog.commands import semantic_command_digest
from app.catalog.errors import CatalogNormalizationError
from app.catalog.fact_tuples import NORMALIZATION_MANIFEST_ID
from app.catalog.import_repository import (
    CatalogPublicationRevisionConflict,
    MySqlCatalogImportRepository,
    _insert_projection,
)
from app.catalog.import_service import DraftProjection, DraftRow, validate_draft_rows
from app.catalog.inventory import (
    CatalogIdentityInventory,
    load_catalog_identity_inventory,
)
from app.catalog.listing_registration import prefill_source_code
from app.catalog.models import StrictCatalogModel
from app.catalog.normalization import catalog_identity_key_v1
from app.catalog.production_code_evidence import ProductionCodeEvidenceInvalid
from app.catalog.source_formatting import FORMAT_REASON, format_identity_field


class ProductionSourceRow(StrictCatalogModel):
    style_code: str = Field(min_length=1, max_length=128)
    color: str = Field(min_length=1, max_length=128)
    size: str = Field(min_length=1, max_length=128)
    formal_sku: str | None = Field(default=None, min_length=1, max_length=128)
    selected_sku_id: int | None = Field(default=None, gt=0)
    source_location: str | None = Field(
        default=None, max_length=256, exclude_if=lambda v: v is None
    )

    @field_validator("style_code", "color", "size")
    @classmethod
    def explicit_text(cls, value: str) -> str:
        if not value.strip() or value.strip() == "/":
            raise ValueError("An explicit product specification is required.")
        try:
            catalog_identity_key_v1(value)
        except CatalogNormalizationError as error:
            raise ValueError("The product specification text is invalid.") from error
        return value

    @field_validator("formal_sku")
    @classmethod
    def explicit_formal_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip() or any(
            ord(char) < 32 or ord(char) == 127 for char in value
        ):
            raise ValueError(
                "A formal code must be explicit text without control characters."
            )
        try:
            catalog_identity_key_v1(value)
        except CatalogNormalizationError as error:
            raise ValueError("The formal code is invalid.") from error
        return value


class ProductionSource(StrictCatalogModel):
    source_name: str = Field(min_length=1, max_length=128)
    report_source_scope_id: int | None = Field(default=None, gt=0)
    channel_evidence: str | None = Field(default=None, min_length=1, max_length=1000)
    rows: list[ProductionSourceRow] = Field(min_length=1, max_length=1000)

    def evidence(self) -> dict[str, CanonicalValue]:
        body = cast(dict[str, CanonicalValue], self.model_dump(mode="json"))
        return body | {"digest": hashlib.sha256(canonical_json_bytes(body)).hexdigest()}


class ProductionSourceInputError(ValueError):
    code = "production_source_invalid"

    def __init__(self, issues: list[str]) -> None:
        self.public_message = "表格检查未通过，请修改后重新检查：\n" + "\n".join(
            issues[:20]
        )
        if len(issues) > 20:
            self.public_message += f"\n另有{len(issues) - 20}处问题，请修正后再次检查。"
        super().__init__(self.code)


def source_text_problem(value: str) -> str | None:
    if "\ufffd" in value:
        return "文字出现乱码，请从原表另存为UTF-8编码或XLSX后重新上传。"
    if not value.strip() or value.strip() == "/":
        return "不能为空或用斜杠代替，请填写明确值。"
    if len(value) > 128:
        return "最多128个字符，请核对是否粘贴了其他内容。"
    if any(unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} for c in value):
        return "含换行、制表符或不可见字符，请删除后重新填写。"
    if (
        value != value.strip()
        or "  " in value
        or any(c.isspace() and c != " " for c in value)
    ):
        return "含首尾空格、连续空格或特殊空格，请使用规范文字及单个半角空格。"
    if any(0xFF01 <= ord(c) <= 0xFF5E for c in value):
        return "含全角字母、数字或符号，请核对并改用半角字符。"
    try:
        catalog_identity_key_v1(value)
    except CatalogNormalizationError:
        return "含不支持的字符，请核对原始文字。"
    return None


def prepare_production_source(
    source: ProductionSource,
    inventory: CatalogIdentityInventory,
    locations: list[str] | None = None,
) -> tuple[ProductionSource, list[dict[str, CanonicalValue]]]:
    """Keep original evidence separate from the server-generated draft values."""
    prepared: list[ProductionSourceRow] = []
    adjustments: list[dict[str, CanonicalValue]] = []
    issues: list[str] = []
    for index, row in enumerate(source.rows):
        place = (
            locations[index]
            if locations is not None
            else row.source_location or f"资料第{index + 1}条"
        )
        style, problem = format_identity_field(
            row.style_code, "style", (str(s["style_code"]) for s in inventory.styles)
        )
        if problem:
            issues.append(f"{place}，A列（款号）：{problem}")
        scoped = [
            s
            for s in inventory.skus
            if catalog_identity_key_v1(str(s["style_code"])).utf8
            == catalog_identity_key_v1(style).utf8
        ]
        values = {"style_code": style}
        for field, kind, label, column, catalog_field in (
            ("color", "color", "颜色", "B", "standard_color"),
            ("size", "size", "尺码", "C", "standard_size"),
        ):
            value, problem = format_identity_field(
                getattr(row, field), kind, (str(s[catalog_field]) for s in scoped)
            )
            values[field] = value
            if problem:
                issues.append(f"{place}，{column}列（{label}）：{problem}")
        for field, value in values.items():
            before = getattr(row, field)
            if before != value:
                adjustments.append(
                    {
                        "source_row": index + 1,
                        "location": place,
                        "field": field,
                        "before": before,
                        "after": value,
                        "reason": (
                            "标准尺码统一为3XL；原始尺码及正式编码保留。"
                            if field == "size" and value == "3XL"
                            else FORMAT_REASON
                        ),
                    }
                )
        prepared.append(row.model_copy(update=values))
    if issues:
        raise ProductionSourceInputError(issues)
    return source.model_copy(update={"rows": prepared}), adjustments


def validate_production_source(
    source: ProductionSource,
    inventory: CatalogIdentityInventory,
    locations: list[str] | None = None,
) -> None:
    """Check new submissions; do not rewrite historical evidence or infer aliases."""
    issues: list[str] = []
    value: str | None
    spelling: dict[tuple[bytes, str, bytes], str] = {}
    codes: dict[bytes, tuple[bytes, ...]] = {}
    variants: dict[tuple[bytes, ...], dict[str, object]] = {}
    for style in inventory.styles:
        value = str(style["style_code"])
        spelling[(b"", "款号", catalog_identity_key_v1(value).utf8)] = value
    for sku in inventory.skus:
        identity = tuple(
            catalog_identity_key_v1(str(sku[f])).utf8
            for f in ("style_code", "standard_color", "standard_size")
        )
        variants[identity] = dict(sku)
        for field, label in (("standard_color", "颜色"), ("standard_size", "尺码")):
            value = str(sku[field])
            spelling[(identity[0], label, catalog_identity_key_v1(value).utf8)] = value
        if sku.get("internal_display_sku"):
            codes[catalog_identity_key_v1(str(sku["internal_display_sku"])).utf8] = (
                identity
            )
    seen: dict[tuple[bytes, ...], tuple[int, str | None]] = {}
    for index, row in enumerate(source.rows):
        place = locations[index] if locations is not None else f"资料第{index + 1}条"
        identity = tuple(
            catalog_identity_key_v1(v).utf8
            for v in (row.style_code, row.color, row.size)
        )
        for col, (label, value) in enumerate(
            zip(
                ("款号", "颜色", "尺码", "正式SKU"),
                (row.style_code, row.color, row.size, row.formal_sku),
                strict=True,
            )
        ):
            if value is None:
                continue
            prefix = f"{place}，{chr(65 + col)}列（{label}）："
            problem = source_text_problem(value)
            if problem:
                issues.append(prefix + problem)
                continue
            if col < 3:
                key = (b"" if col == 0 else identity[0], label, identity[col])
                standard = spelling.get(key)
                if standard is not None and standard != value:
                    issues.append(
                        prefix + f"写法不一致，请使用“{standard}”；系统不会自动改写。"
                    )
                else:
                    spelling[key] = value
        if identity in seen:
            previous, code = seen[identity]
            if code != row.formal_sku:
                issues.append(
                    f"{place}，D列（正式SKU）："
                    f"与资料第{previous + 1}条的相同规格编码不一致，"
                    "请核对后保留一致的编码。"
                )
        else:
            seen[identity] = (index, row.formal_sku)
        if row.formal_sku:
            code_key = catalog_identity_key_v1(row.formal_sku).utf8
            if code_key in codes and codes[code_key] != identity:
                issues.append(
                    f"{place}，D列（正式SKU）：该编码已属于其他款号、颜色或尺码，请核对商品身份。"
                )
            codes[code_key] = identity
            existing = variants.get(identity)
            if (
                existing
                and existing.get("code_status") == "confirmed"
                and existing.get("internal_display_sku") != row.formal_sku
            ):
                issues.append(
                    f"{place}，D列（正式SKU）：与主档正式编码不一致，请核对后使用“{existing['internal_display_sku']}”；编码变更请走主档更正流程。"
                )
    if issues:
        raise ProductionSourceInputError(issues)


def _row(section: str, key: str, payload: dict[str, CanonicalValue]) -> DraftRow:
    payload = {**payload, "row_key": key}
    return DraftRow(
        section,
        key,
        "user_created",
        "included",
        payload,
        hashlib.sha256(canonical_json_bytes(payload)).digest(),
    )


def _key(prefix: str, *values: str) -> str:
    return prefix + hashlib.sha256(canonical_json_bytes(list(values))).hexdigest()[:40]


def production_sku_choices(rows: tuple[DraftRow, ...]) -> dict[str, dict[str, object]]:
    """Only offer recorded evidence or the approved value; never generate codes."""
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        if row.section != "skus":
            continue
        options: list[dict[str, str]] = []
        for field in ("source_formal_sku", "approved_formal_sku"):
            value = row.payload.get(field)
            if (
                isinstance(value, str)
                and value
                and all(item["value"] != value for item in options)
            ):
                options.append({"value": value, "label": value})
        result[row.row_key] = {
            "options": options,
            "message": (
                "从来源或已批准编码选择。尚无正式编码时请明确选择待补并说明依据。"
            ),
        }
    owners: dict[bytes, set[str]] = {}
    for row in rows:
        if row.section == "skus":
            for field in (
                "internal_display_sku",
                "source_formal_sku",
                "approved_formal_sku",
            ):
                value = row.payload.get(field)
                if isinstance(value, str) and value:
                    owners.setdefault(catalog_identity_key_v1(value).utf8, set()).add(
                        row.row_key
                    )
    for choice in result.values():
        options = cast(list[dict[str, str]], choice["options"])
        if any(
            len(owners[catalog_identity_key_v1(option["value"]).utf8]) > 1
            for option in options
        ):
            choice["options"] = []
            choice["message"] = "来源编码与其他规格冲突, 请先核对归属。"
    return result


def project_production_source(
    source: ProductionSource | None, inventory: CatalogIdentityInventory
) -> tuple[DraftProjection, list[dict[str, CanonicalValue]]]:
    rows: dict[str, DraftRow] = {}
    style_keys: dict[bytes, str] = {}
    variants: dict[tuple[bytes, ...], str] = {}
    for style in inventory.styles:
        normalized = catalog_identity_key_v1(str(style["style_code"])).utf8
        key = "style-" + str(style["style_id"])
        style_keys[normalized] = key
        rows[key] = _row(
            "styles",
            key,
            {
                "system_style_id": str(style["style_id"]),
                "style_code": str(style["style_code"]),
                "standard_name": str(style["standard_name"]),
                "status": str(style["status"]),
                "category_action": "keep",
                "category_code": None,
            },
        )
    for sku in inventory.skus:
        existing_style_key = style_keys[
            catalog_identity_key_v1(str(sku["style_code"])).utf8
        ]
        key = "sku-" + str(sku["sku_id"])
        identity = tuple(
            catalog_identity_key_v1(str(sku[field])).utf8
            for field in ("style_code", "standard_color", "standard_size")
        )
        variants[identity] = key
        rows[key] = _row(
            "skus",
            key,
            {
                "system_sku_id": str(sku["sku_id"]),
                "style_row_key": existing_style_key,
                "source_style_code": str(sku["style_code"]),
                "internal_display_sku": cast(str | None, sku["internal_display_sku"]),
                "approved_formal_sku": cast(str | None, sku["internal_display_sku"]),
                "code_status": str(sku.get("code_status", "legacy")),
                "code_evidence": cast(str | None, sku.get("code_evidence")),
                "standard_color": str(sku["standard_color"]),
                "standard_size": str(sku["standard_size"]),
                "status": str(sku["status"]),
            },
        )
    observations: list[dict[str, CanonicalValue]] = []
    seen: set[tuple[bytes, ...]] = set()
    for index, record in enumerate(source.rows if source else [], 1):
        assert source is not None
        identity = tuple(
            catalog_identity_key_v1(value).utf8
            for value in (record.style_code, record.color, record.size)
        )
        if identity in seen:
            observations.append(
                {
                    "source_row": index,
                    "style_code": record.style_code,
                    "color": record.color,
                    "size": record.size,
                    "action": "DUPLICATE_SOURCE_ROW",
                }
            )
            continue
        seen.add(identity)
        existing_style = identity[0] in style_keys
        style_key = style_keys.get(identity[0])
        if style_key is None:
            style_key = _key("new-style-", identity[0].decode())
            style_keys[identity[0]] = style_key
            rows[style_key] = _row(
                "styles",
                style_key,
                {
                    "system_style_id": None,
                    "style_code": record.style_code,
                    "standard_name": None,
                    "status": "enabled",
                    "category_action": "keep",
                    "category_code": None,
                },
            )
        sku_key = variants.get(identity)
        if sku_key is None:
            sku_key = _key("new-sku-", *(part.decode() for part in identity))
            variants[identity] = sku_key
            rows[sku_key] = _row(
                "skus",
                sku_key,
                {
                    "system_sku_id": None,
                    "style_row_key": style_key,
                    "source_style_code": record.style_code,
                    "internal_display_sku": None,
                    "approved_formal_sku": None,
                    "standard_color": record.color,
                    "standard_size": record.size,
                    "source_color_preview": json.dumps(
                        [record.color], ensure_ascii=False
                    ),
                    "source_size_preview": json.dumps(
                        [record.size], ensure_ascii=False
                    ),
                    "status": "enabled",
                },
            )
            action = (
                "ADD_SPECIFICATION"
                if existing_style and rows[style_key].payload.get("system_style_id")
                else "REVIEW_NEW_PRODUCT"
            )
        else:
            action = (
                "REUSE_EXISTING"
                if rows[sku_key].payload.get("system_sku_id")
                else "REVIEW_NEW_PRODUCT"
            )
            if action == "REUSE_EXISTING" and (
                rows[sku_key].payload["status"] != "enabled"
                or rows[style_key].payload["status"] != "enabled"
            ):
                action = "REVIEW_DISABLED"
        sku_payload = dict(rows[sku_key].payload)
        if record.selected_sku_id is not None and str(
            record.selected_sku_id
        ) != sku_payload.get("system_sku_id"):
            raise ProductionCodeEvidenceInvalid(
                "Selected SKU does not match this site's approved specification."
            )
        if record.formal_sku is not None:
            catalog_identity_key_v1(record.formal_sku)
            sku_payload["source_formal_sku"] = record.formal_sku
            sku_payload["source_code_evidence"] = source.source_name
        if (
            source.report_source_scope_id is not None
            and source.channel_evidence
            and record.formal_sku
        ):
            sku_payload = prefill_source_code(
                sku_payload, record.formal_sku, source.source_name
            )
        rows[sku_key] = _row("skus", sku_key, sku_payload)
        if source.report_source_scope_id is not None and record.formal_sku is not None:
            if not source.channel_evidence or not source.channel_evidence.strip():
                raise ProductionCodeEvidenceInvalid("Channel evidence is required.")
            raw_sha = (
                "sha256:"
                + hashlib.sha256(record.formal_sku.encode("utf-8")).hexdigest()
            )
            mapping_key = "production-mapping-" + raw_sha[7:47]
            if (
                mapping_key in rows
                and rows[mapping_key].payload.get("source_target_sku_row_key")
                != sku_key
            ):
                raise ProductionCodeEvidenceInvalid(
                    "Seller SKU refers to multiple product specifications."
                )
            rows[mapping_key] = _row(
                "mappings",
                mapping_key,
                {
                    "seller_sku_preview": record.formal_sku,
                    "seller_sku_sha256": raw_sha,
                    "seller_account": str(source.report_source_scope_id),
                    "marketplace": "amazon_us",
                    "identity_decision": "mapped",
                    "target_sku_row_key": sku_key,
                    "source_target_sku_row_key": sku_key,
                },
            )
        observations.append(
            {
                "source_row": index,
                "style_code": record.style_code,
                "color": record.color,
                "size": record.size,
                "style_row_key": style_key,
                "sku_row_key": sku_key,
                "action": action,
                "sku_id": sku_payload.get("system_sku_id"),
                "formal_sku": sku_payload.get("internal_display_sku"),
                "code_status": sku_payload.get("code_status", "unreviewed"),
            }
        )
    return validate_draft_rows(tuple(rows.values())), observations


def validate_source_scope(
    connection: Connection, site_id: int, source: ProductionSource
) -> None:
    if source.report_source_scope_id is None:
        return
    if not source.channel_evidence or not source.channel_evidence.strip():
        raise ProductionCodeEvidenceInvalid("Channel evidence is required.")
    valid = connection.scalar(
        sa.text(
            "SELECT id FROM report_source_scopes WHERE id=:id AND site_id=:site AND"
            " marketplace_scope_code='amazon_us'"
        ),
        {"id": source.report_source_scope_id, "site": site_id},
    )
    if valid is None:
        raise ProductionCodeEvidenceInvalid(
            "Source scope is not available for this site."
        )


def _publication(
    connection: Connection, site_id: int, *, lock: bool
) -> tuple[int | None, int]:
    if lock:
        connection.execute(
            sa.text(
                "INSERT IGNORE INTO product_catalog_publications(site_id,curr"
                "ent_catalog_version_id,catalog_publication_revision) VALUES("
                ":site,NULL,0)"
            ),
            {"site": site_id},
        )
    pointer = (
        connection.execute(
            sa.text(
                (
                    "SELECT current_catalog_version_id,catalog_publication_revisi"
                    "on FROM product_catalog_publications WHERE site_id=:site"
                )
                + (" FOR UPDATE" if lock else "")
            ),
            {"site": site_id},
        )
        .mappings()
        .one_or_none()
    )
    return (
        (None, 0)
        if pointer is None
        else (
            pointer["current_catalog_version_id"],
            int(pointer["catalog_publication_revision"]),
        )
    )


def source_preview(
    engine: Engine,
    site_id: int,
    source: ProductionSource,
    *,
    locations: list[str] | None = None,
) -> dict[str, object]:
    with (
        engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection,
        connection.begin(),
    ):
        base, revision = _publication(connection, site_id, lock=False)
        validate_source_scope(connection, site_id, source)
        inventory = load_catalog_identity_inventory(
            connection, site_id=site_id, catalog_version_id=base
        )
        prepared, adjustments = prepare_production_source(source, inventory, locations)
        validate_production_source(prepared, inventory, locations)
        projection, observations = project_production_source(prepared, inventory)
    return {
        "source": source.evidence(),
        "format_adjustments": adjustments,
        "catalog_publication_revision": revision,
        "observations": observations,
        "counts": dict(Counter(str(item["action"]) for item in observations)),
        "blocking_fields": len(projection.issues),
    }


def production_evidence(
    connection: Connection, *, import_id: int, site_id: int
) -> dict[str, object] | None:
    payload = connection.scalar(
        sa.text(
            "SELECT p.evidence_payload_json FROM catalog_imports i JOIN catal"
            "og_export_payloads p ON p.export_id=i.export_id AND p.site_id=i."
            "site_id WHERE i.id=:id AND i.site_id=:site AND i.source_kind='pr"
            "oduction'"
        ),
        {"id": import_id, "site": site_id},
    )
    if payload is None:
        return None
    value = json.loads(payload) if isinstance(payload, str) else payload
    return cast(dict[str, object], value["production_source"])


def _create_export(
    connection: Connection,
    *,
    site_id: int,
    actor_id: int,
    token: UUID,
    source: ProductionSource | dict[str, CanonicalValue],
    base: int | None,
    revision: int,
    observations: list[dict[str, CanonicalValue]],
) -> int:
    source_payload = dict(source) if isinstance(source, dict) else source.evidence()
    source_payload.update(
        {
            "observations": cast(list[CanonicalValue], observations),
            "recorded_at": datetime.now(UTC).isoformat(),
        }
    )
    payload: dict[str, CanonicalValue] = {"production_source": source_payload}
    digest = hashlib.sha256(canonical_json_bytes(payload)).digest()
    export = connection.execute(
        sa.text(
            "INSERT INTO catalog_exports(site_id,operation_token,fact_sna"
            "pshot_tuple_id,base_catalog_version_id,catalog_publication_r"
            "evision,workbook_schema_version,normalization_manifest_id,ex"
            "port_status,workbook_status,capacity_violations,created_by_u"
            "ser_id)\n        VALUES(:site,:token,NULL,:base,:revision,'pr"
            "oduct_catalog_workbook_v2',:manifest,'ready','online_only',J"
            "SON_ARRAY(),:actor)"
        ),
        {
            "site": site_id,
            "token": token.bytes,
            "base": base,
            "revision": revision,
            "manifest": NORMALIZATION_MANIFEST_ID,
            "actor": actor_id,
        },
    )
    export_id = int(export.lastrowid)
    connection.execute(
        sa.text(
            "INSERT INTO catalog_export_payloads(export_id,site_id,candid"
            "ate_payload_json,candidate_payload_digest,evidence_payload_j"
            "son,evidence_payload_digest,payload_digest)\n        VALUES(:"
            "id,:site,JSON_OBJECT(),:empty,CAST(:payload AS JSON),:digest"
            ",:digest)"
        ),
        {
            "id": export_id,
            "site": site_id,
            "empty": hashlib.sha256(canonical_json_bytes({})).digest(),
            "payload": canonical_json_bytes(payload).decode(),
            "digest": digest,
        },
    )
    return export_id


def create_production_import(
    engine: Engine,
    *,
    site_id: int,
    actor_id: int,
    token: UUID,
    source: ProductionSource,
    expected_revision: int,
) -> dict[str, CanonicalValue]:
    body: dict[str, CanonicalValue] = source.evidence() | {
        "expected_catalog_publication_revision": expected_revision
    }

    def effect(connection: Connection) -> tuple[int, dict[str, CanonicalValue]]:
        base, revision = _publication(connection, site_id, lock=True)
        duplicate = (
            connection.execute(
                sa.text(
                    "SELECT i.id,i.status,i.base_catalog_version_id FROM "
                    "catalog_imports i JOIN catalog_export_payloads p ON "
                    "p.export_id=i.export_id AND p.site_id=i.site_id\n    "
                    "        WHERE i.site_id=:site AND i.source_kind='pro"
                    "duction' AND i.status NOT IN ('withdrawn','supersede"
                    "d') AND JSON_UNQUOTE(JSON_EXTRACT(p.evidence_payload"
                    "_json,'$.production_source.digest'))=:digest ORDER B"
                    "Y i.id DESC LIMIT 1"
                ),
                {"site": site_id, "digest": source.evidence()["digest"]},
            )
            .mappings()
            .one_or_none()
        )
        if duplicate is not None and (
            duplicate["status"] == "approved"
            or duplicate["base_catalog_version_id"] == base
        ):
            return 200, {"import_id": int(duplicate["id"]), "duplicate": True}
        if revision != expected_revision:
            raise CatalogPublicationRevisionConflict()
        validate_source_scope(connection, site_id, source)
        inventory = load_catalog_identity_inventory(
            connection, site_id=site_id, catalog_version_id=base
        )
        prepared, adjustments = prepare_production_source(source, inventory)
        validate_production_source(prepared, inventory)
        projection, observations = project_production_source(prepared, inventory)
        export_id = _create_export(
            connection,
            site_id=site_id,
            actor_id=actor_id,
            token=token,
            source=source.evidence()
            | {"format_adjustments": cast(list[CanonicalValue], adjustments)},
            base=base,
            revision=revision,
            observations=observations,
        )
        inserted = connection.execute(
            sa.text(
                "INSERT INTO catalog_imports(site_id,operation_token,sour"
                "ce_kind,owner_user_id,export_id,base_catalog_version_id,"
                "fact_snapshot_tuple_id,normalization_manifest_id,status,"
                "workflow_revision,parse_attempt_revision)\n            VA"
                "LUES(:site,:token,'production',:actor,:export,:base,NULL"
                ",:manifest,:status,0,0)"
            ),
            {
                "site": site_id,
                "token": token.bytes,
                "actor": actor_id,
                "export": export_id,
                "base": base,
                "manifest": NORMALIZATION_MANIFEST_ID,
                "status": projection.initial_status,
            },
        )
        import_id = int(inserted.lastrowid)
        _insert_projection(
            connection,
            import_id=import_id,
            site_id=site_id,
            workflow_revision=0,
            projection=projection,
        )
        return 201, {"import_id": import_id, "duplicate": False}

    with engine.begin() as connection:
        command = MySqlCatalogImportRepository._execute_command(
            connection,
            operation_token=token,
            operation_kind="production_source_create",
            operation_digest=semantic_command_digest(
                route="production_source_create",
                resource_id=None,
                body=body,
                operation_token=token,
            ),
            site_id=site_id,
            actor_user_id=actor_id,
            resource_id=None,
            effect=effect,
        )
    return command.safe_result


def rebase_production_import(
    engine: Engine,
    *,
    import_id: int,
    site_id: int,
    actor_id: int,
    token: UUID,
    expected_revision: int,
    expected_workflow_revision: int,
) -> dict[str, CanonicalValue]:
    with engine.begin() as connection:
        evidence = production_evidence(connection, import_id=import_id, site_id=site_id)
        if evidence is None:
            from app.api.errors import ApiError

            raise ApiError(
                404, "catalog_import_not_found", "未找到本站点的生产资料批次。"
            )
        if evidence.get("report_selection") is not None:
            from app.api.errors import ApiError

            if (
                cast(dict[str, object], evidence["report_selection"]).get("version")
                != 1
            ):
                raise ApiError(
                    409,
                    "report_selection_unknown",
                    "此报表来源格式版本不能由当前程序重建草稿。",
                )
            raise ApiError(
                409,
                "report_selection_recheck_required",
                "请从待归属与审核重新读取本条来源并预览，建立保留原依据的后继候选；当前草稿保留。",
            )
        if evidence.get("source_schema") == "amazon_listing_v1":
            from app.api.errors import ApiError

            raise ApiError(
                409,
                "listing_recheck_required",
                "请返回亚马逊商品清单重新核对，建立保留原件和依据的后继草稿。",
            )
        if evidence.get("source_schema") is not None:
            from app.api.errors import ApiError

            raise ApiError(
                409, "listing_schema_unknown", "此来源格式版本不能由当前程序重建草稿。"
            )
        source = ProductionSource.model_validate(
            {
                key: evidence[key]
                for key in (
                    "source_name",
                    "rows",
                    "report_source_scope_id",
                    "channel_evidence",
                )
                if key in evidence
            }
        )
        existing = (
            connection.execute(
                sa.text(
                    "SELECT id,base_catalog_version_id,catalog_publication_re"
                    "vision FROM catalog_exports WHERE operation_token=:token"
                    " AND site_id=:site AND created_by_user_id=:actor AND fac"
                    "t_snapshot_tuple_id IS NULL"
                ),
                {"token": token.bytes, "site": site_id, "actor": actor_id},
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            export_id = int(existing["id"])
            base = existing["base_catalog_version_id"]
        else:
            base, revision = _publication(connection, site_id, lock=True)
            if revision != expected_revision:
                raise CatalogPublicationRevisionConflict()
        validate_source_scope(connection, site_id, source)
        inventory = load_catalog_identity_inventory(
            connection, site_id=site_id, catalog_version_id=base
        )
        prepared, adjustments = prepare_production_source(source, inventory)
        validate_production_source(prepared, inventory)
        projection, observations = project_production_source(prepared, inventory)
        from app.catalog.import_repository import _load_projection_rows

        previous = _load_projection_rows(
            connection,
            import_id=import_id,
            workflow_revision=expected_workflow_revision,
        )
        old_styles = {
            row.row_key: row.payload.get("style_code")
            for row in previous
            if row.section == "styles"
        }
        next_styles = {
            row.row_key: row.payload.get("style_code")
            for row in projection.rows
            if row.section == "styles"
        }

        def identity(
            row: DraftRow, styles: dict[str, CanonicalValue]
        ) -> tuple[object, ...]:
            return (
                (row.section, row.payload.get("style_code"))
                if row.section == "styles"
                else (
                    row.section,
                    styles.get(str(row.payload.get("style_row_key"))),
                    row.payload.get("standard_color"),
                    row.payload.get("standard_size"),
                )
            )

        old = {
            identity(row, old_styles): row
            for row in previous
            if row.section in {"styles", "skus"}
        }
        old_by_key = {
            row.row_key: row for row in previous if row.section in {"styles", "skus"}
        }
        retained = []
        for row in projection.rows:
            prior = old_by_key.get(row.row_key) or old.get(identity(row, next_styles))
            fields = (
                (
                    "standard_name",
                    "status",
                    "category_action",
                    "category_code",
                    "change_reason",
                )
                if row.section == "styles"
                else (
                    "internal_display_sku",
                    "standard_color",
                    "standard_size",
                    "status",
                    "code_status",
                    "code_evidence",
                    "change_reason",
                )
            )
            payload = dict(row.payload)
            changed = False
            if prior is not None:
                for field in fields:
                    value = prior.payload.get(field)
                    if value is not None and value != payload.get(field):
                        payload[field] = value
                        changed = True
                if changed:
                    payload["reconfirm_required"] = "yes"
            retained.append(_row(row.section, row.row_key, payload))
        projection = validate_draft_rows(tuple(retained))
        if existing is None:
            export_id = _create_export(
                connection,
                site_id=site_id,
                actor_id=actor_id,
                token=token,
                source=source.evidence()
                | {"format_adjustments": cast(list[CanonicalValue], adjustments)},
                base=base,
                revision=expected_revision,
                observations=observations,
            )
    result = MySqlCatalogImportRepository(engine).rebase_import(
        import_id=import_id,
        site_id=site_id,
        actor_user_id=actor_id,
        operation_token=token,
        expected_workflow_revision=expected_workflow_revision,
        replacement_export_id=export_id,
        expected_catalog_publication_revision=expected_revision,
        projection=projection,
    )
    return result.safe_result
