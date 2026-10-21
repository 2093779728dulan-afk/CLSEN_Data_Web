from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import socket
from collections import Counter
from datetime import UTC, date
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from app.catalog.candidates import parse_seller_sku_candidate
from app.db.settings import DatabaseSettings
from app.parsers.parser import parse_report
from app.parsers.types import BusinessReportRow, ParseSettings, ReturnReportRow

from tests.integration.test_real_csv_regression import (
    _load_manifest,
    _manifest_cases,
    _require_complete_private_corpus,
    _sequence_digest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / "data" / "golden" / "golden-manifest.json"
PRIVATE_ROOT = REPOSITORY_ROOT / "表格"
PRIVATE_MANIFEST_ENV = "APP_PRODUCT_CATALOG_PRIVATE_MANIFEST"
PRIVATE_CORPUS_ENV = "APP_PRODUCT_CATALOG_PRIVATE_CORPUS_ROOT"
CANARY_URL_ENV = "APP_PRODUCT_CATALOG_CANARY_DATABASE_URL"
REQUIRE_ENV = "APP_REQUIRE_PRODUCT_CATALOG_CANARY"
OUTPUT_ENV = "APP_PRODUCT_CATALOG_CANARY_EVIDENCE_PATH"
SYNTHETIC_ONLY_ENV = "APP_PROJECT_OPTIMIZATION_SYNTHETIC_ONLY"
LOOPBACK_PORT_ENV = "APP_PRODUCT_CATALOG_CANARY_LOOPBACK_PORT"
ALLOWED_EVIDENCE_KEYS = {
    "artifact_digest",
    "candidate_style_count",
    "consistent_as_of",
    "distinct_seller_sku_count",
    "normalization_version",
    "query_digest",
    "report_membership_counts",
    "safe_output",
    "strict_seller_sku_count",
    "anomaly_count",
}


def _required() -> bool:
    return os.getenv(REQUIRE_ENV) == "1"


def _unavailable(message: str) -> None:
    if _required():
        pytest.fail(message, pytrace=False)
    pytest.skip(message)


def _grants_are_select_only(grants: list[str], *, database: str) -> bool:
    quoted_database = f"`{database.replace('`', '``')}`"
    unquoted_database = database if re.fullmatch(r"[A-Za-z0-9_$]+", database) else None
    database_targets = [f"{quoted_database}."]
    if unquoted_database is not None:
        database_targets.append(f"{unquoted_database}.")

    saw_select = False
    for grant in grants:
        normalized = " ".join(grant.strip().split())
        if " WITH GRANT OPTION" in normalized.upper():
            return False
        match = re.fullmatch(
            r"GRANT\s+(?P<privileges>.+?)\s+ON\s+(?P<target>.+?)\s+TO\s+.+",
            normalized,
            flags=re.IGNORECASE,
        )
        if match is None:
            return False
        privileges = match.group("privileges").upper()
        target = match.group("target")
        if privileges == "USAGE":
            if target != "*.*":
                return False
            continue
        if privileges != "SELECT" or not target.startswith(tuple(database_targets)):
            return False
        saw_select = True
    return saw_select


@pytest.mark.parametrize(
    ("grants", "expected"),
    [
        (
            [
                "GRANT USAGE ON *.* TO `canary`@`localhost`",
                "GRANT SELECT ON `clsen_data`.* TO `canary`@`localhost`",
            ],
            True,
        ),
        (
            ["GRANT SELECT, INSERT ON `clsen_data`.* TO `canary`@`localhost`"],
            False,
        ),
        (["GRANT SELECT ON *.* TO `canary`@`localhost`"], False),
        (
            ["GRANT SELECT ON `another_database`.* TO `canary`@`localhost`"],
            False,
        ),
        (["GRANT USAGE ON *.* TO `canary`@`localhost`"], False),
        (
            [
                "GRANT SELECT ON `clsen_data`.* TO `canary`@`localhost` "
                "WITH GRANT OPTION"
            ],
            False,
        ),
        (["GRANT `reader_role`@`%` TO `canary`@`localhost`"], False),
        ([], False),
    ],
)
def test_canary_grant_validation_is_strictly_select_only(
    grants: list[str], expected: bool
) -> None:
    assert _grants_are_select_only(grants, database="clsen_data") is expected


def test_private_representatives_preserve_shape_quoting_and_identity_semantics() -> (
    None
):
    manifest = _load_manifest()
    cases = _manifest_cases(manifest)
    _require_complete_private_corpus(cases)
    comma_title = comma_comment = False
    # Exercise every approved input, including multiline/quoted cells. Compare
    # exact source identities/text, not historic counts of a hand-picked file.
    for case in cases:
        payload = case.source_path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != case.expected["sha256"]:
            pytest.fail("private canary file digest changed", pytrace=False)
        report_type = case.expected["report_type"]
        encoding = case.expected["encoding"]
        try:
            raw = list(csv.DictReader(io.StringIO(payload.decode(encoding))))
            parsed = parse_report(
                payload,
                settings=ParseSettings(
                    report_type=report_type,
                    encoding=encoding,
                    source_timezone="America/Los_Angeles",
                ),
            )
            matched = len(raw) == len(parsed.rows) == case.expected["row_count"]
            for source, row in zip(raw, parsed.rows, strict=True):
                if isinstance(row, BusinessReportRow):
                    matched &= (row.sku, row.title) == (source["SKU"], source["标题"])
                    comma_title |= "," in (row.title or "")
                elif isinstance(row, ReturnReportRow):
                    matched &= (
                        row.sku,
                        row.product_name,
                        row.customer_comments or "",
                    ) == (
                        source["sku"],
                        source["product-name"],
                        source["customer-comments"],
                    )
                    matched &= row.return_date.tzinfo is UTC
                    comma_comment |= "," in (row.customer_comments or "")
        except Exception:
            pytest.fail("private canary shape or parsing failed", pytrace=False)
        if not matched:
            pytest.fail("private canary decoded identities/text changed", pytrace=False)
    if not comma_title or not comma_comment:
        pytest.fail("private canary corpus lacks quoted-comma coverage", pytrace=False)


def _snapshot_query() -> sa.TextClause:
    return sa.text(
        """
        SELECT datasets.report_type, datasets.report_date, report_rows.sku
        FROM daily_datasets AS datasets
        INNER JOIN dataset_publications AS publications
            ON publications.dataset_id = datasets.id
        LEFT JOIN version_rows AS version_rows
            ON version_rows.version_id = publications.version_id
           AND version_rows.row_state = 'active'
        LEFT JOIN business_report_rows AS report_rows
            ON report_rows.version_id = publications.version_id
           AND report_rows.version_row_id = version_rows.id
        WHERE datasets.report_type = 'business_report'
          AND datasets.site_id = :site_id AND datasets.report_date IN :report_dates
        UNION ALL
        SELECT datasets.report_type, datasets.report_date, report_rows.sku
        FROM daily_datasets AS datasets
        INNER JOIN dataset_publications AS publications
            ON publications.dataset_id = datasets.id
        LEFT JOIN version_rows AS version_rows
            ON version_rows.version_id = publications.version_id
           AND version_rows.row_state = 'active'
        LEFT JOIN return_report_rows AS report_rows
            ON report_rows.version_id = publications.version_id
           AND report_rows.version_row_id = version_rows.id
        WHERE datasets.report_type = 'return_report'
          AND datasets.site_id = :site_id AND datasets.report_date IN :report_dates
        """
    ).bindparams(sa.bindparam("report_dates", expanding=True))


def _snapshot_metrics(rows: list[Any], manifest: dict[str, Any]) -> dict[str, Any]:
    expected_rows = {
        (entry["report_type"], entry["detected_report_date"]): entry["row_count"]
        for entry in manifest["files"]
    }
    actual_rows = Counter(
        (kind, str(day)) for kind, day, sku in rows if sku is not None
    )
    actual_pairs = {(kind, str(day)) for kind, day, _ in rows}
    if actual_pairs != set(expected_rows) or any(
        actual_rows[key] != count for key, count in expected_rows.items()
    ):
        pytest.fail(
            "canary published report coverage/row counts differ from approved CSVs",
            pytrace=False,
        )
    by_report = {
        kind: {
            str(sku)
            for report_type, _, sku in rows
            if report_type == kind and sku is not None
        }
        for kind in ("business_report", "return_report")
    }
    expected = manifest["canary_expected"]
    if {
        kind: _sequence_digest(sorted(values)) for kind, values in by_report.items()
    } != expected["seller_sku_sets_sha256"]:
        pytest.fail("canary SKU identity sets differ from approved CSVs", pytrace=False)
    combined = by_report["business_report"] | by_report["return_report"]
    strict = {sku for sku in combined if parse_seller_sku_candidate(sku) is not None}
    styles = {sku.split("-", 1)[0] for sku in strict}
    metrics = {
        "candidate_style_count": len(styles),
        "distinct_seller_sku_count": len(combined),
        "strict_seller_sku_count": len(strict),
        "anomaly_count": len(combined - strict),
        "report_membership_counts": {
            "business_only": len(
                by_report["business_report"] - by_report["return_report"]
            ),
            "returns_only": len(
                by_report["return_report"] - by_report["business_report"]
            ),
            "both": len(by_report["business_report"] & by_report["return_report"]),
        },
    }
    if any(value != expected.get(key) for key, value in metrics.items()):
        pytest.fail(
            "canary identity counts differ from independent approved expectations",
            pytrace=False,
        )
    return metrics


def _synthetic_manifest() -> dict[str, Any]:
    return {
        "approved_scope": {
            "site_id": 1,
            "report_dates": ["2026-07-31"],
            "report_types": ["business_report", "return_report"],
        },
        "files": [
            {
                "path": f"{kind}.csv",
                "sha256": "0" * 64,
                "report_type": kind,
                "detected_report_date": "2026-07-31",
                "row_count": 1,
            }
            for kind in ("business_report", "return_report")
        ],
        "summary": {
            "file_count": 2,
            "report_types": {
                kind: {"file_count": 1} for kind in ("business_report", "return_report")
            },
        },
        "canary_expected": {
            "candidate_style_count": 1,
            "distinct_seller_sku_count": 1,
            "strict_seller_sku_count": 1,
            "anomaly_count": 0,
            "report_membership_counts": {
                "business_only": 0,
                "returns_only": 0,
                "both": 1,
            },
            "seller_sku_sets_sha256": {
                kind: _sequence_digest(["100-BLUE-S"])
                for kind in ("business_report", "return_report")
            },
        },
    }


@pytest.mark.parametrize(
    "defect",
    ["missing_scope", "missing_day", "duplicate_day", "wrong_type", "extra_date"],
)
def test_canary_manifest_requires_exact_approved_scope(defect: str) -> None:
    manifest = _synthetic_manifest()
    assert len(_manifest_cases(manifest)) == 2
    if defect == "missing_scope":
        del manifest["approved_scope"]
    elif defect == "missing_day":
        manifest["files"].pop()
        manifest["summary"]["file_count"] = 1
    elif defect == "duplicate_day":
        manifest["files"][1]["report_type"] = "business_report"
    elif defect == "wrong_type":
        manifest["files"][1]["report_type"] = "unknown"
    else:
        manifest["files"][1]["detected_report_date"] = "2026-08-01"
    with pytest.raises(pytest.fail.Exception):
        _manifest_cases(manifest)


@pytest.mark.parametrize(
    "defect",
    ["missing_report", "extra_row", "same_count_other_sku", "wrong_expected_count"],
)
def test_canary_snapshot_rejects_scope_and_identity_drift(defect: str) -> None:
    manifest = _synthetic_manifest()
    rows = [
        (kind, "2026-07-31", "100-BLUE-S")
        for kind in ("business_report", "return_report")
    ]
    assert _snapshot_metrics(rows, manifest)["distinct_seller_sku_count"] == 1
    if defect == "missing_report":
        rows.pop()
    elif defect == "extra_row":
        rows.append(rows[0])
    elif defect == "same_count_other_sku":
        rows = [(kind, day, "101-BLUE-S") for kind, day, _ in rows]
    else:
        manifest["canary_expected"]["distinct_seller_sku_count"] = 2
    with pytest.raises(pytest.fail.Exception):
        _snapshot_metrics(rows, manifest)


def test_canary_query_excludes_other_sites_dates_and_inactive_rows() -> None:
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            for sql in (
                "CREATE TABLE daily_datasets (id, site_id, report_date, report_type)",
                "CREATE TABLE dataset_publications (dataset_id, version_id)",
                "CREATE TABLE version_rows (id, version_id, row_state)",
                "CREATE TABLE business_report_rows (version_id, version_row_id, sku)",
                "CREATE TABLE return_report_rows (version_id, version_row_id, sku)",
            ):
                connection.exec_driver_sql(sql)
            for number, (site, day, kind) in enumerate(
                (
                    (1, "2026-07-31", "business_report"),
                    (1, "2026-07-31", "return_report"),
                    (2, "2026-07-31", "business_report"),
                    (2, "2026-07-31", "return_report"),
                    (1, "2026-08-01", "business_report"),
                    (1, "2026-08-01", "return_report"),
                ),
                start=1,
            ):
                connection.exec_driver_sql(
                    "INSERT INTO daily_datasets VALUES (?,?,?,?)",
                    (number, site, day, kind),
                )
                connection.exec_driver_sql(
                    "INSERT INTO dataset_publications VALUES (?,?)", (number, number)
                )
                connection.exec_driver_sql(
                    "INSERT INTO version_rows VALUES (?,?,'active')", (number, number)
                )
                connection.exec_driver_sql(
                    f"INSERT INTO {kind}_rows VALUES (?,?,'100-BLUE-S')",
                    (number, number),
                )
            connection.exec_driver_sql(
                "INSERT INTO version_rows VALUES (20,1,'deleted')"
            )
            connection.exec_driver_sql(
                "INSERT INTO business_report_rows VALUES (1,20,'EXCLUDED')"
            )
            rows = list(
                connection.execute(
                    _snapshot_query(), {"site_id": 1, "report_dates": ["2026-07-31"]}
                )
            )
            assert len(rows) == 2
            assert _snapshot_metrics(rows, _synthetic_manifest())["anomaly_count"] == 0
    finally:
        engine.dispose()


def _canary_engine(settings: DatabaseSettings) -> sa.Engine:
    """Keep the certificate hostname while connecting through a local TCP tunnel."""
    engine = sa.create_engine(settings.url, pool_pre_ping=True)
    port_value = os.getenv(LOOPBACK_PORT_ENV)
    if port_value is None:
        return engine
    try:
        port = int(port_value)
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        pytest.fail("canary loopback port is invalid", pytrace=False)

    @sa.event.listens_for(engine, "do_connect")
    def connect_via_loopback(
        dialect: Any, connection_record: Any, args: Any, params: Any
    ) -> Any:
        connection = dialect.loaded_dbapi.Connection(**params, defer_connect=True)
        if not connection.ssl or not connection.ctx.check_hostname:
            pytest.fail("canary tunnel requires verified TLS identity", pytrace=False)
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        try:
            connection.connect(sock=sock)
        except BaseException:
            sock.close()
            raise
        return connection

    return engine


def test_current_database_read_only_snapshot_matches_approved_counts() -> None:
    value = os.getenv(CANARY_URL_ENV, "").strip()
    if not value:
        _unavailable("SELECT-only current database URL is required")
    settings = DatabaseSettings.from_url(value, pool_size=1, max_overflow=0)
    manifest = _load_manifest()
    _manifest_cases(manifest)
    if manifest.get("canary_expected", {}).get("oracle") != "stdlib_csv_ascii_sku_v1":
        pytest.fail(
            "independent approved canary expectations are required", pytrace=False
        )
    scope = manifest["approved_scope"]
    query = _snapshot_query()
    engine = _canary_engine(settings)
    try:
        with engine.connect() as connection:
            grants = [str(row[0]) for row in connection.execute(sa.text("SHOW GRANTS"))]
            if not _grants_are_select_only(grants, database=str(settings.url.database)):
                pytest.fail("canary account is not SELECT-only", pytrace=False)
            cipher = connection.exec_driver_sql(
                "SHOW SESSION STATUS LIKE 'Ssl_cipher'"
            ).first()
            if cipher is None or not cipher[1]:
                pytest.fail("canary connection must use TLS", pytrace=False)
            connection.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
            )
            connection.exec_driver_sql(
                "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY"
            )
            consistent_as_of = str(
                connection.scalar(sa.text("SELECT UTC_TIMESTAMP(6)"))
            )
            rows = list(
                connection.execute(
                    query,
                    {
                        "site_id": scope["site_id"],
                        "report_dates": [
                            date.fromisoformat(day) for day in scope["report_dates"]
                        ],
                    },
                )
            )
            connection.rollback()
    except Exception as error:
        pytest.fail(
            f"read-only canary connection/query failed ({type(error).__name__})",
            pytrace=False,
        )
    finally:
        engine.dispose()
    metrics = _snapshot_metrics(rows, manifest)
    evidence = {
        **metrics,
        "artifact_digest": hashlib.sha256(
            Path(os.getenv(PRIVATE_MANIFEST_ENV, str(MANIFEST_PATH))).read_bytes()
        ).hexdigest(),
        "consistent_as_of": consistent_as_of,
        "normalization_version": "seller_sku_match_v1",
        "query_digest": hashlib.sha256(query.text.encode("utf-8")).hexdigest(),
        "safe_output": True,
    }
    assert set(evidence) == ALLOWED_EVIDENCE_KEYS
    output = os.getenv(OUTPUT_ENV, "")
    if output:
        Path(output).write_text(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
