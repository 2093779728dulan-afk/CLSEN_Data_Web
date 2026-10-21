"""Application rules for irreversible P0 Seller Account scope confirmation."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.scope_repository import (
    MySqlCatalogScopeRepository,
    ScopeConfirmationRecord,
)
from app.site_context import CurrentSiteContext

_MARKETPLACE = "amazon_us"


class CatalogScopeServiceError(RuntimeError):
    code = "catalog_scope_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class CatalogScopePermissionDenied(CatalogScopeServiceError):
    code = "catalog_scope_permission_denied"


class CatalogScopeCommandInvalid(CatalogScopeServiceError):
    code = "catalog_scope_confirmation_invalid"


@dataclass(frozen=True, slots=True)
class ConfirmScopeCommand:
    operation_token: UUID
    expected_site_config_revision: int
    seller_account_scope_key: str
    seller_account_display_name: str
    marketplace_scope_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class CatalogScopePermissions:
    can_confirm: bool


@dataclass(frozen=True, slots=True)
class CatalogScopeStatus:
    status: str
    report_source_scope_id: int | None
    seller_account_display_name: str | None
    marketplace_scope_code: str
    site_config_version_id: int
    site_config_revision: int
    permissions: CatalogScopePermissions


def _safe_trimmed_text(value: str, *, maximum: int) -> str:
    if not isinstance(value, str) or any(
        0xD800 <= ord(character) <= 0xDFFF for character in value
    ):
        raise CatalogScopeCommandInvalid()
    result = value.strip()
    if not result or len(result) > maximum:
        raise CatalogScopeCommandInvalid()
    if any(
        ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in result
    ):
        raise CatalogScopeCommandInvalid()
    return result


def _uuid4(value: object) -> UUID:
    if not isinstance(value, UUID) or value.version != 4:
        raise CatalogScopeCommandInvalid()
    return value


class CatalogScopeService:
    def __init__(
        self,
        repository: MySqlCatalogScopeRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    @staticmethod
    def _permissions(context: CurrentSiteContext) -> CatalogScopePermissions:
        return CatalogScopePermissions(can_confirm=context.is_admin)

    def status(self, context: CurrentSiteContext) -> CatalogScopeStatus:
        scope = self._repository.status(context)
        return CatalogScopeStatus(
            status="unconfirmed" if scope is None else "confirmed",
            report_source_scope_id=(
                None if scope is None else scope.report_source_scope_id
            ),
            seller_account_display_name=(
                None if scope is None else scope.seller_account_display_name
            ),
            marketplace_scope_code=_MARKETPLACE,
            site_config_version_id=context.site_config_version_id,
            site_config_revision=context.site_config_revision,
            permissions=self._permissions(context),
        )

    def confirm(
        self,
        context: CurrentSiteContext,
        command: ConfirmScopeCommand,
    ) -> CatalogScopeStatus:
        if not context.is_admin:
            raise CatalogScopePermissionDenied()
        token = _uuid4(command.operation_token)
        if (
            isinstance(command.expected_site_config_revision, bool)
            or command.expected_site_config_revision < 1
            or command.marketplace_scope_code != _MARKETPLACE
        ):
            raise CatalogScopeCommandInvalid()
        scope_key = _safe_trimmed_text(
            command.seller_account_scope_key,
            maximum=255,
        )
        display_name = _safe_trimmed_text(
            command.seller_account_display_name,
            maximum=128,
        )
        reason = _safe_trimmed_text(command.reason, maximum=1000)
        scope_key_digest = hashlib.sha256(scope_key.encode("utf-8")).digest()
        semantics = {
            "actor_user_id": context.principal_user_id,
            "expected_site_config_revision": command.expected_site_config_revision,
            "marketplace_scope_code": _MARKETPLACE,
            "reason": reason,
            "route": "catalog.source_scope.confirm.v1",
            "seller_account_display_name": display_name,
            "seller_account_scope_key_sha256": scope_key_digest.hex(),
            "site_id": context.site_id,
        }
        operation_digest = hashlib.sha256(canonical_json_bytes(semantics)).digest()
        result = self._repository.confirm(
            context,
            operation_token=token,
            operation_digest=operation_digest,
            expected_site_config_revision=command.expected_site_config_revision,
            seller_account_scope_key=scope_key_digest,
            seller_account_display_name=display_name,
            marketplace_scope_code=_MARKETPLACE,
            reason=reason,
            occurred_at=self._clock(),
        )
        return self._confirmed_status(context, result)

    def _confirmed_status(
        self,
        context: CurrentSiteContext,
        result: ScopeConfirmationRecord,
    ) -> CatalogScopeStatus:
        return CatalogScopeStatus(
            status="confirmed",
            report_source_scope_id=result.scope.report_source_scope_id,
            seller_account_display_name=result.scope.seller_account_display_name,
            marketplace_scope_code=result.scope.marketplace_scope_code,
            site_config_version_id=result.site_config_version_id,
            site_config_revision=result.site_config_revision,
            permissions=self._permissions(context),
        )


__all__ = (
    "CatalogScopeCommandInvalid",
    "CatalogScopePermissionDenied",
    "CatalogScopePermissions",
    "CatalogScopeService",
    "CatalogScopeServiceError",
    "CatalogScopeStatus",
    "ConfirmScopeCommand",
)
