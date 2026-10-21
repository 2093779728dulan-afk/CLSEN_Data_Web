from __future__ import annotations

import csv
from dataclasses import fields, replace
from decimal import Decimal
from io import StringIO

from app.parsers.parser import parse_report
from app.parsers.rules import REPORT_RULES
from app.parsers.types import ParsedReport, ParsedRow, ParseSettings
from app.validation.fidelity import (
    BaselineRowEvidence,
    FieldMappingEvidence,
    ParseFidelityEvidence,
    SourceFieldMappingEvidence,
    SourceRowEvidence,
    validate_parse_fidelity,
)
from app.validation.fields import FieldValue, as_field_value


def _csv_bytes(
    header: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    *,
    encoding: str,
) -> bytes:
    target = StringIO(newline="")
    writer = csv.writer(target, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return target.getvalue().encode(encoding)


def _typed_values(row: ParsedRow) -> tuple[tuple[str, FieldValue], ...]:
    return tuple(
        (field.name, as_field_value(getattr(row, field.name)))
        for field in fields(row)
        if field.name not in {"source", "typed_digest"}
    )


def _evidence(parsed: ParsedReport, settings: ParseSettings) -> ParseFidelityEvidence:
    source_ids = tuple(range(101, 101 + len(parsed.source_rows)))
    return ParseFidelityEvidence(
        report_type=parsed.report_type,
        parser_version=parsed.parser_version,
        ruleset_version=parsed.ruleset_version,
        settings=settings,
        header=parsed.header,
        source_rows=tuple(
            SourceRowEvidence(
                source_row_id=source_id,
                source_row_number=row.source_row_number,
                raw_values=row.raw_values,
                row_digest=row.row_digest,
            )
            for source_id, row in zip(source_ids, parsed.source_rows, strict=True)
        ),
        baseline_rows=tuple(
            BaselineRowEvidence(
                baseline_row_id=201 + index,
                source_row_id=source_id,
                row_ordinal=index + 1,
                values=_typed_values(row),
                row_digest=row.typed_digest,
            )
            for index, (source_id, row) in enumerate(
                zip(source_ids, parsed.rows, strict=True)
            )
        ),
        field_mapping=FieldMappingEvidence(
            source_header=parsed.header,
            fields=tuple(
                SourceFieldMappingEvidence(
                    source_name=field.source_name,
                    target_name=field.target_name,
                    kind=field.kind,
                )
                for field in REPORT_RULES[parsed.report_type].fields
            ),
        ),
        stored_source_row_count=parsed.summary.row_count,
        stored_baseline_row_count=parsed.summary.row_count,
        stored_totals=parsed.summary.totals,
        stored_data_digest=parsed.summary.data_digest,
    )


def _business_evidence(*, row_count: int = 1) -> ParseFidelityEvidence:
    values = (
        "PARENT",
        "CHILD",
        "标题,保留 Unicode\n第二行",
        "SKU-1",
        "10",
        "2",
        "15.90%",
        "10.00%",
        "15",
        "3",
        "30.00%",
        "15.00%",
        "100.00%",
        "100.00%",
        "2",
        "1",
        "20.00%",
        "50.00%",
        "US$111.980000",
        "US$59.99",
        "2",
        "1",
    )
    settings = ParseSettings(report_type="business_report", encoding="utf-8")
    parsed = parse_report(
        _csv_bytes(
            REPORT_RULES["business_report"].source_header,
            tuple(values for _index in range(row_count)),
            encoding="utf-8",
        ),
        settings,
    )
    return _evidence(parsed, settings)


def _return_evidence() -> ParseFidelityEvidence:
    values = (
        "2026-08-08T08:30:12.345678+00:00",
        "ORDER-1",
        "SKU-1",
        "ASIN-1",
        "FNSKU-1",
        "商品,Unicode",
        "2",
        "FC-1",
        "SELLABLE",
        "REASON",
        "STATUS",
        "LPN-1",
        '买家留言\r\n第二行 says "quoted"',
    )
    settings = ParseSettings(report_type="return_report", encoding="utf-8")
    parsed = parse_report(
        _csv_bytes(
            REPORT_RULES["return_report"].source_header,
            (values,),
            encoding="utf-8",
        ),
        settings,
    )
    return _evidence(parsed, settings)


def test_fidelity_passes_for_exact_decimal_unicode_and_utc_evidence() -> None:
    business = validate_parse_fidelity(_business_evidence())
    returns = validate_parse_fidelity(_return_evidence())

    assert business.passed
    assert returns.passed
    assert business.issues == ()
    assert returns.issues == ()


def test_fidelity_blocks_when_a_baseline_row_is_missing() -> None:
    evidence = _business_evidence()
    changed = replace(evidence, baseline_rows=())

    result = validate_parse_fidelity(changed)

    assert not result.passed
    assert "parse.baseline_row_count_mismatch" in {
        issue.code for issue in result.issues
    }
    assert "parse.missing_baseline_row" in {issue.code for issue in result.issues}


def test_fidelity_blocks_an_exact_typed_value_mismatch() -> None:
    evidence = _business_evidence()
    baseline = evidence.baseline_rows[0]
    values = dict(baseline.values)
    amount = values["ordered_product_sales"]
    assert isinstance(amount, Decimal)
    values["ordered_product_sales"] = amount + Decimal(1)
    changed_row = replace(baseline, values=tuple(values.items()))

    result = validate_parse_fidelity(replace(evidence, baseline_rows=(changed_row,)))

    issue = next(
        issue for issue in result.issues if issue.code == "parse.value_mismatch"
    )
    assert issue.field_name == "ordered_product_sales"
    assert not result.passed


def test_fidelity_blocks_source_digest_and_total_mismatches() -> None:
    evidence = _return_evidence()
    source = replace(evidence.source_rows[0], row_digest="00" * 32)
    changed = replace(
        evidence,
        source_rows=(source,),
        stored_totals=(("quantity", "999"),),
    )

    result = validate_parse_fidelity(changed)

    assert {issue.code for issue in result.issues} >= {
        "parse.source_digest_mismatch",
        "parse.total_mismatch",
    }


def test_fidelity_locates_attempt_and_baseline_count_drift_independently() -> None:
    evidence = _business_evidence()
    changed = replace(
        evidence,
        stored_source_row_count=2,
        stored_baseline_row_count=3,
    )

    result = validate_parse_fidelity(changed)

    assert {issue.code for issue in result.issues} >= {
        "parse.attempt_source_count_mismatch",
        "parse.baseline_row_count_mismatch",
    }


def test_fidelity_requires_exact_persisted_field_mapping() -> None:
    evidence = _business_evidence()
    mapping = evidence.field_mapping
    first = replace(mapping.fields[0], target_name="wrong_target")
    changed_mapping = replace(mapping, fields=(first, *mapping.fields[1:]))

    result = validate_parse_fidelity(replace(evidence, field_mapping=changed_mapping))

    assert "parse.field_mapping_mismatch" in {issue.code for issue in result.issues}


def test_fidelity_requires_baseline_ordinal_to_follow_source_order() -> None:
    evidence = _business_evidence(row_count=2)
    first, second = evidence.baseline_rows
    changed_rows = (
        replace(first, source_row_id=second.source_row_id),
        replace(second, source_row_id=first.source_row_id),
    )

    result = validate_parse_fidelity(replace(evidence, baseline_rows=changed_rows))

    assert "parse.baseline_source_order_mismatch" in {
        issue.code for issue in result.issues
    }
