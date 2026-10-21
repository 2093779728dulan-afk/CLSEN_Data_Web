"""Canonical command identity and bounded catalog decision batches."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.catalog.canonical_json import CanonicalValue, canonical_json_bytes

_MUTATION_TYPES: Final = frozenset(
    {
        "create_style",
        "update_style",
        "delete_style",
        "create_sku",
        "update_sku",
        "delete_sku",
        "map_seller_sku",
        "exclude_seller_sku",
        "clear_seller_sku_decision",
        "restore_seller_sku_review",
        "resolve_exception_map_existing",
        "resolve_exception_create_new",
        "resolve_exception_correct_parse",
        "resolve_exception_exclude",
        "clear_exception_group",
        "update_exception_note",
    }
)


@dataclass(frozen=True, slots=True)
class CatalogDecisionMutation:
    mutation_id: UUID
    type: str
    row_key: str | None
    decision_group_key: str | None
    payload: dict[str, CanonicalValue]

    def __post_init__(self) -> None:
        if self.mutation_id.version != 4 or self.type not in _MUTATION_TYPES:
            raise ValueError("invalid catalog decision mutation")
        for value in (self.row_key, self.decision_group_key):
            if value is not None and (not value or len(value) > 64):
                raise ValueError("invalid catalog decision key")


@dataclass(frozen=True, slots=True)
class CatalogDecisionIssue:
    mutation_id: UUID | None
    row_key: str | None
    decision_group_key: str | None
    field: str | None
    reason_code: str
    message: str


class CatalogDecisionBatchError(ValueError):
    code = "catalog_decisions_invalid"

    def __init__(self, issues: tuple[CatalogDecisionIssue, ...]) -> None:
        self.issues = issues
        super().__init__(self.code)


def semantic_command_digest(
    *,
    route: str,
    resource_id: int | None,
    body: dict[str, CanonicalValue],
    operation_token: UUID,
) -> bytes:
    if operation_token.version != 4:
        raise ValueError("operation_token must be UUID v4")
    return hashlib.sha256(
        canonical_json_bytes({"route": route, "resource_id": resource_id, "body": body})
    ).digest()


def _issue(
    mutation: CatalogDecisionMutation,
    reason: str,
    *,
    field: str | None = None,
) -> CatalogDecisionIssue:
    return CatalogDecisionIssue(
        mutation.mutation_id,
        mutation.row_key,
        mutation.decision_group_key,
        field,
        reason,
        "The decision batch contains an invalid or conflicting mutation.",
    )


def validate_decision_batch(
    mutations: tuple[CatalogDecisionMutation, ...],
    *,
    existing_row_keys: frozenset[str] = frozenset(),
    system_row_keys: frozenset[str] = frozenset(),
    allow_repeated_for_test: bool = False,
) -> tuple[CatalogDecisionMutation, ...]:
    if not 1 <= len(mutations) <= 500:
        raise CatalogDecisionBatchError(
            (
                CatalogDecisionIssue(
                    None,
                    None,
                    None,
                    None,
                    "batch_size_invalid",
                    "A decision batch must contain between 1 and 500 mutations.",
                ),
            )
        )
    issues: list[CatalogDecisionIssue] = []
    seen_ids: set[UUID] = set()
    seen_targets: set[tuple[str, str]] = set()
    created = {
        mutation.row_key
        for mutation in mutations
        if mutation.type in {"create_style", "create_sku"}
        and mutation.row_key is not None
    }
    for mutation in mutations:
        if mutation.mutation_id in seen_ids and not allow_repeated_for_test:
            issues.append(_issue(mutation, "duplicate_target"))
        seen_ids.add(mutation.mutation_id)
        locator = mutation.decision_group_key or mutation.row_key
        if locator is not None:
            kind = (
                "exception"
                if mutation.decision_group_key is not None
                else mutation.type.rpartition("_")[2]
            )
            target = (kind, locator)
            if target in seen_targets and not allow_repeated_for_test:
                issues.append(_issue(mutation, "duplicate_target"))
            seen_targets.add(target)
        if (
            mutation.type in {"delete_style", "delete_sku"}
            and mutation.row_key in system_row_keys
        ):
            issues.append(_issue(mutation, "system_row_delete_forbidden"))
        if mutation.type == "create_sku":
            style_ref = mutation.payload.get("style_row_key")
            if (
                not isinstance(style_ref, str)
                or style_ref not in existing_row_keys | created
            ):
                issues.append(
                    _issue(mutation, "invalid_reference", field="/style_row_key")
                )
        if (
            mutation.type.startswith("resolve_exception")
            or mutation.type == "map_seller_sku"
        ):
            target_ref = mutation.payload.get("target_sku_row_key")
            if target_ref is not None and (
                not isinstance(target_ref, str)
                or target_ref not in existing_row_keys | created
            ):
                issues.append(
                    _issue(
                        mutation,
                        "invalid_reference",
                        field="/target_sku_row_key",
                    )
                )
    if issues:
        raise CatalogDecisionBatchError(tuple(issues))
    return mutations


__all__ = (
    "CatalogDecisionBatchError",
    "CatalogDecisionIssue",
    "CatalogDecisionMutation",
    "semantic_command_digest",
    "validate_decision_batch",
)
