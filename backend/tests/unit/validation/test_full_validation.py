from __future__ import annotations

import csv
from dataclasses import fields, replace
from datetime import date
from io import StringIO
from uuid import UUID

from app.parsers.parser import parse_report
from app.parsers.rules import REPORT_RULES
from app.parsers.types import ParsedRow, ParseSettings
from app.validation.fidelity import (
    BaselineRowEvidence,
    FieldMappingEvidence,
    ParseFidelityEvidence,
    SourceFieldMappingEvidence,
    SourceRowEvidence,
)
from app.validation.fields import FieldValue, as_field_value
from app.validation.full import (
    FullValidationEvidence,
    ParseFidelityInput,
    evaluate_full_validation,
)
from app.validation.replay import DraftReplayEvidence, DraftRow


def _typed_values(row: ParsedRow) -> tuple[tuple[str, FieldValue], ...]:
    return tuple(
        (field.name, as_field_value(getattr(row, field.name)))
        for field in fields(row)
        if field.name not in {"source", "typed_digest"}
    )


def _parse_input() -> ParseFidelityInput:
    values = (
        "2026-08-08T08:30:12.345678+00:00",
        "ORDER-1",
        "SKU-1",
        "ASIN-1",
        "FNSKU-1",
        "商品",
        "2",
        "FC-1",
        "SELLABLE",
        "REASON",
        "STATUS",
        "LPN-1",
        "买家留言",
    )
    target = StringIO(newline="")
    writer = csv.writer(target, lineterminator="\r\n")
    writer.writerow(REPORT_RULES["return_report"].source_header)
    writer.writerow(values)
    settings = ParseSettings(report_type="return_report", encoding="utf-8")
    parsed = parse_report(target.getvalue().encode(), settings)
    source = parsed.source_rows[0]
    typed = parsed.rows[0]
    evidence = ParseFidelityEvidence(
        report_type="return_report",
        parser_version=parsed.parser_version,
        ruleset_version=parsed.ruleset_version,
        settings=settings,
        header=parsed.header,
        source_rows=(
            SourceRowEvidence(
                source_row_id=101,
                source_row_number=source.source_row_number,
                raw_values=source.raw_values,
                row_digest=source.row_digest,
            ),
        ),
        baseline_rows=(
            BaselineRowEvidence(
                baseline_row_id=201,
                source_row_id=101,
                row_ordinal=1,
                values=_typed_values(typed),
                row_digest=typed.typed_digest,
            ),
        ),
        field_mapping=FieldMappingEvidence(
            source_header=parsed.header,
            fields=tuple(
                SourceFieldMappingEvidence(
                    source_name=field.source_name,
                    target_name=field.target_name,
                    kind=field.kind,
                )
                for field in REPORT_RULES["return_report"].fields
            ),
        ),
        stored_source_row_count=1,
        stored_baseline_row_count=1,
        stored_totals=parsed.summary.totals,
        stored_data_digest=parsed.summary.data_digest,
    )
    return ParseFidelityInput(
        import_batch_id=71,
        parse_attempt_id=81,
        parse_baseline_id=91,
        evidence=evidence,
    )


def _full_evidence(parse_input: ParseFidelityInput) -> FullValidationEvidence:
    values = parse_input.evidence.baseline_rows[0].values
    row = DraftRow(
        row_id=301,
        logical_row_id=UUID("00000000-0000-0000-0000-000000000001"),
        row_ordinal=1,
        row_state="active",
        values=values,
        base_row_id=401,
        source_parse_baseline_row_id=101,
        source_batch_id=71,
        parse_baseline_row_id=201,
    )
    draft = DraftReplayEvidence(
        report_type="return_report",
        ruleset_version="return_report_v1",
        base_rows=(row,),
        events=(),
        current_rows=(row,),
        data_revision=0,
    )
    return FullValidationEvidence(
        dataset_id=5,
        version_id=23,
        version_status="draft",
        data_revision=0,
        review_revision=7,
        report_date=date(2026, 8, 8),
        report_type="return_report",
        ruleset_version="return_report_v1",
        parse_inputs=(parse_input,),
        draft=draft,
    )


def test_full_validation_builds_the_frozen_publish_summary() -> None:
    evaluation = evaluate_full_validation(_full_evidence(_parse_input()))

    assert evaluation.result.passed
    assert (
        evaluation.result.data_digest
        == evaluation.result.draft_explainability.data_digest
    )
    assert evaluation.summary.as_payload() == {
        "schema_version": 1,
        "report_date": "2026-08-08",
        "report_type": "return_report",
        "row_count": 1,
        "totals": {"quantity": "2"},
        "stages": {
            "parse_fidelity": {
                "data_digest": evaluation.result.parse_fidelity.data_digest,
                "row_count": 1,
                "totals": {"quantity": "2"},
                "warning_count": 0,
                "blocking_count": 0,
            },
            "draft_explainability": {
                "data_digest": evaluation.result.draft_explainability.data_digest,
                "row_count": 1,
                "totals": {"quantity": "2"},
                "warning_count": 0,
                "blocking_count": 0,
            },
        },
    }


def test_full_validation_preserves_parse_issue_lineage_for_persistence() -> None:
    parse_input = _parse_input()
    source = replace(
        parse_input.evidence.source_rows[0],
        row_digest="00" * 32,
    )
    changed = replace(
        parse_input,
        evidence=replace(parse_input.evidence, source_rows=(source,)),
    )

    evaluation = evaluate_full_validation(_full_evidence(changed))

    issue = next(
        item
        for item in evaluation.issues
        if item.issue.code == "parse.source_digest_mismatch"
    )
    assert not evaluation.result.passed
    assert issue.import_batch_id == 71
    assert issue.parse_attempt_id == 81
    assert issue.parsed_source_row_id == 101
    assert issue.parse_baseline_id == 91
    assert issue.parse_baseline_row_id is None
    assert issue.version_row_id == 301
