from __future__ import annotations

import json
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.catalog.canonical_json import CanonicalValue
from app.catalog.commands import (
    CatalogDecisionBatchError,
    CatalogDecisionMutation,
    semantic_command_digest,
)
from app.catalog.import_repository import MySqlCatalogImportRepository

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import PublicationIntegrationCase
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)
from tests.integration.test_catalog_import_workflow import (
    catalog_import_case_fixture as _catalog_import_case,  # noqa: F401
)
from tests.integration.test_catalog_import_workflow import ready_export_projection

pytestmark = pytest.mark.mysql


def _body(
    expected_revision: int,
    mutations: tuple[CatalogDecisionMutation, ...],
) -> dict[str, CanonicalValue]:
    return {
        "expected_workflow_revision": expected_revision,
        "mutations": [
            {
                "mutation_id": str(mutation.mutation_id),
                "type": mutation.type,
                "row_key": mutation.row_key,
                "decision_group_key": mutation.decision_group_key,
                "payload": mutation.payload,
            }
            for mutation in mutations
        ],
    }


def test_decision_batch_one_five_hundred_and_501_are_atomic(
    catalog_import_case: PublicationIntegrationCase,
) -> None:
    runtime, command, _workbook, projection = ready_export_projection(
        catalog_import_case
    )
    try:
        repository = MySqlCatalogImportRepository(runtime)
        import_id = repository.create_online_from_export(
            site_id=1,
            owner_user_id=catalog_import_case.owner_user_id,
            operation_token=uuid4(),
            export_id=command.export_id,
            expected_catalog_publication_revision=0,
            projection=projection,
        )
        one = (
            CatalogDecisionMutation(
                uuid4(),
                "create_style",
                "single-created-style",
                None,
                {
                    "style_code": "SINGLE",
                    "standard_name": "Approved standard name",
                    "status": "enabled",
                },
            ),
        )
        token = uuid4()
        first = repository.apply_decisions(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=token,
            expected_workflow_revision=0,
            mutations=one,
        )
        replay = repository.apply_decisions(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=token,
            expected_workflow_revision=0,
            mutations=one,
        )
        assert first == replay
        assert (
            repository.get_state(import_id=import_id, site_id=1).workflow_revision == 1
        )

        five_hundred = tuple(
            CatalogDecisionMutation(
                uuid4(),
                "create_style",
                f"created-style-{index:03d}",
                None,
                {
                    "style_code": f"STYLE-{index:03d}",
                    "standard_name": f"Standard {index:03d}",
                    "status": "enabled",
                },
            )
            for index in range(500)
        )
        result = repository.apply_decisions(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=uuid4(),
            expected_workflow_revision=1,
            mutations=five_hundred,
        )
        assert result.safe_result["applied_mutation_count"] == 500
        before = repository.get_state(import_id=import_id, site_id=1)
        with pytest.raises(CatalogDecisionBatchError):
            repository.apply_decisions(
                import_id=import_id,
                site_id=1,
                actor_user_id=catalog_import_case.owner_user_id,
                operation_token=uuid4(),
                expected_workflow_revision=before.workflow_revision,
                mutations=(*five_hundred, five_hundred[0]),
            )
        after = repository.get_state(import_id=import_id, site_id=1)
        assert after.workflow_revision == before.workflow_revision
    finally:
        runtime.dispose()


def test_claim_only_and_saved_effect_recover_without_duplicate_business_write(
    catalog_import_case: PublicationIntegrationCase,
) -> None:
    runtime, command, _workbook, projection = ready_export_projection(
        catalog_import_case
    )
    try:
        repository = MySqlCatalogImportRepository(runtime)
        import_id = repository.create_online_from_export(
            site_id=1,
            owner_user_id=catalog_import_case.owner_user_id,
            operation_token=uuid4(),
            export_id=command.export_id,
            expected_catalog_publication_revision=0,
            projection=projection,
        )
        mutation = (
            CatalogDecisionMutation(
                uuid4(),
                "create_style",
                "recovered-created-style",
                None,
                {
                    "style_code": "RECOVERED",
                    "standard_name": "Recovered standard name",
                    "status": "enabled",
                },
            ),
        )
        token = uuid4()
        digest = semantic_command_digest(
            route="catalog_import_decisions",
            resource_id=import_id,
            body=_body(0, mutation),
            operation_token=token,
        )
        with catalog_import_case.dataset_case.migration_engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_command_claims (
                        operation_token, operation_kind, operation_digest,
                        site_id, actor_user_id, resource_kind, resource_id, status
                    ) VALUES (
                        :token, 'decisions', :digest, 1, :actor,
                        'catalog_import', :resource_id, 'claimed'
                    )
                    """
                ),
                {
                    "token": token.bytes,
                    "digest": digest,
                    "actor": catalog_import_case.owner_user_id,
                    "resource_id": import_id,
                },
            )
        recovered = repository.apply_decisions(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=token,
            expected_workflow_revision=0,
            mutations=mutation,
        )
        assert recovered.safe_result["workflow_revision"] == 1

        saved_token = uuid4()
        saved_mutation = (
            CatalogDecisionMutation(
                uuid4(),
                "create_style",
                "saved-effect-style",
                None,
                {
                    "style_code": "SAVED",
                    "standard_name": "Must not execute",
                    "status": "enabled",
                },
            ),
        )
        saved_digest = semantic_command_digest(
            route="catalog_import_decisions",
            resource_id=import_id,
            body=_body(1, saved_mutation),
            operation_token=saved_token,
        )
        safe_result = {
            "import_id": import_id,
            "source_kind": "online",
            "workflow_revision": 77,
            "parse_attempt_revision": 0,
            "applied_mutation_count": 1,
        }
        with catalog_import_case.dataset_case.migration_engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_command_claims (
                        operation_token, operation_kind, operation_digest,
                        site_id, actor_user_id, resource_kind, resource_id, status
                    ) VALUES (
                        :token, 'decisions', :digest, 1, :actor,
                        'catalog_import', :resource_id, 'completed'
                    )
                    """
                ),
                {
                    "token": saved_token.bytes,
                    "digest": saved_digest,
                    "actor": catalog_import_case.owner_user_id,
                    "resource_id": import_id,
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_command_effects (
                        operation_token, operation_kind, operation_digest,
                        site_id, actor_user_id, response_schema_version,
                        response_status_code, safe_result_json, completed_at
                    ) VALUES (
                        :token, 'decisions', :digest, 1, :actor, 1, 200,
                        CAST(:result AS JSON), UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": saved_token.bytes,
                    "digest": saved_digest,
                    "actor": catalog_import_case.owner_user_id,
                    "result": json.dumps(safe_result, separators=(",", ":")),
                },
            )
        saved = repository.apply_decisions(
            import_id=import_id,
            site_id=1,
            actor_user_id=catalog_import_case.owner_user_id,
            operation_token=saved_token,
            expected_workflow_revision=1,
            mutations=saved_mutation,
        )
        assert saved.safe_result["workflow_revision"] == 77
        assert (
            repository.get_state(import_id=import_id, site_id=1).workflow_revision == 1
        )
    finally:
        runtime.dispose()
