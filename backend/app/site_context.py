"""Fail-closed server-derived context for the P0 single-site deployment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from app.auth.sessions import Principal


class SiteContextUnavailable(RuntimeError):
    """The server cannot prove the P0 single-active-site invariant."""

    code = "site_context_unavailable"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CurrentSiteContext:
    """Authenticated principal bound to exactly one server-selected site config."""

    principal_user_id: int
    principal_roles: frozenset[str]
    site_id: int
    site_code: str
    site_display_name: str
    site_config_version_id: int
    site_config_revision: int
    source_timezone: str
    reporting_timezone: str
    currency_code: str

    @property
    def is_admin(self) -> bool:
        return "admin" in self.principal_roles


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SiteContextUnavailable()
    return value


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SiteContextUnavailable()
    return value


def resolve_current_site_context(
    database_session: Any,
    principal: Principal,
) -> CurrentSiteContext:
    """Resolve exactly one active site and its valid current configuration.

    The query deliberately reads at most two rows. Zero, ambiguity, a dangling
    pointer, or malformed configuration data all produce the same closed error.
    No request value participates in selection.
    """

    result = database_session.execute(
        sa.text(
            """
            SELECT sites.id AS site_id,
                   sites.code AS site_code,
                   sites.display_name AS site_display_name,
                   configs.id AS site_config_version_id,
                   configs.version_number AS site_config_revision,
                   configs.source_timezone,
                   configs.reporting_timezone,
                   configs.currency_code
            FROM sites AS sites
            INNER JOIN site_current_configs AS current_configs
                ON current_configs.site_id = sites.id
            INNER JOIN site_config_versions AS configs
                ON configs.site_id = current_configs.site_id
               AND configs.id = current_configs.current_config_version_id
            WHERE sites.status = 'active'
            LIMIT 2
            """
        )
    )
    mappings = getattr(result, "mappings", None)
    if not callable(mappings):
        raise SiteContextUnavailable()
    rows = mappings().all()
    if len(rows) != 1:
        raise SiteContextUnavailable()
    row = rows[0]
    try:
        return CurrentSiteContext(
            principal_user_id=_positive_int(principal.user_id),
            principal_roles=frozenset(principal.roles),
            site_id=_positive_int(row["site_id"]),
            site_code=_required_text(row["site_code"]),
            site_display_name=_required_text(row["site_display_name"]),
            site_config_version_id=_positive_int(row["site_config_version_id"]),
            site_config_revision=_positive_int(row["site_config_revision"]),
            source_timezone=_required_text(row["source_timezone"]),
            reporting_timezone=_required_text(row["reporting_timezone"]),
            currency_code=_required_text(row["currency_code"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SiteContextUnavailable() from error


__all__ = (
    "CurrentSiteContext",
    "SiteContextUnavailable",
    "resolve_current_site_context",
)
