from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tools.build_golden_manifest import ManifestError, build_manifest, write_manifest
from tools.verify_golden_manifest import verify_manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "backend" / "tests" / "fixtures" / "synthetic"


def sequence_digest(values: list[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big"))
        digest.update(encoded)
    return digest.hexdigest()


class GoldenManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.source_root = Path(self.temporary_directory.name) / "表格"
        (self.source_root / "1").mkdir(parents=True)
        (self.source_root / "2").mkdir(parents=True)

        business_text = (FIXTURE_ROOT / "business-report.csv").read_text(
            encoding="utf-8"
        )
        (self.source_root / "1" / "20260731-BusinessReport-synthetic.csv").write_text(
            business_text,
            encoding="utf-8-sig",
            newline="",
        )
        shutil.copyfile(
            FIXTURE_ROOT / "return-report.csv",
            self.source_root / "2" / "亚马逊物流买家退货-20260731-00000000000.csv",
        )

    def test_build_manifest_records_expected_aggregate_facts(self) -> None:
        manifest = build_manifest(self.source_root)

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["summary"]["file_count"], 2)
        self.assertEqual(manifest["summary"]["row_count"], 4)
        self.assertEqual(
            manifest["summary"]["report_types"]["business_report"],
            {"file_count": 1, "row_count": 2},
        )
        self.assertEqual(
            manifest["summary"]["report_types"]["return_report"],
            {"file_count": 1, "row_count": 2},
        )

        files_by_type = {entry["report_type"]: entry for entry in manifest["files"]}
        business = files_by_type["business_report"]
        returns = files_by_type["return_report"]

        self.assertEqual(business["detected_report_date"], "2026-07-31")
        self.assertEqual(business["encoding"], "utf-8-sig")
        self.assertEqual(business["column_count"], 22)
        self.assertEqual(
            business["numeric_totals"],
            {
                "order_items_b2b": "1",
                "order_items_total": "3",
                "ordered_product_sales_b2b": "59.99",
                "ordered_product_sales_total": "169.97",
                "page_views_b2b": "3",
                "page_views_total": "22",
                "sessions_b2b": "2",
                "sessions_total": "15",
                "units_ordered_b2b": "1",
                "units_ordered_total": "3",
            },
        )
        self.assertEqual(
            business["percentage_fields"]["conversion_rate_total"],
            {
                "parsed_count": 2,
                "min_ratio": "0.1",
                "max_ratio": "0.2",
                "ordered_ratios_sha256": sequence_digest(["0.2", "0.1"]),
            },
        )
        self.assertEqual(len(business["percentage_fields"]), 8)

        self.assertEqual(returns["detected_report_date"], "2026-07-31")
        self.assertEqual(returns["encoding"], "windows-1252")
        self.assertEqual(returns["column_count"], 13)
        self.assertEqual(returns["numeric_totals"], {"quantity": "3"})
        self.assertEqual(returns["event_dates_utc"], ["2026-07-31", "2026-08-01"])
        self.assertEqual(returns["event_date_mismatch_count"], 1)

    def test_return_fixture_preserves_windows_1252_export_bytes(self) -> None:
        raw_fixture = (FIXTURE_ROOT / "return-report.csv").read_bytes()

        self.assertIn(b"\x92", raw_fixture)
        self.assertNotIn(b"\xe2\x80\x99", raw_fixture)
        self.assertIn("wasn’t", raw_fixture.decode("windows-1252"))

    def test_manifest_is_deterministic_and_contains_no_business_identifiers(
        self,
    ) -> None:
        first = build_manifest(self.source_root)
        second = build_manifest(self.source_root)

        self.assertEqual(first, second)
        serialized = json.dumps(first, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("SYN-BLUE-S", serialized)
        self.assertNotIn("000-0000000-0000000", serialized)
        self.assertNotIn("Fabric felt", serialized)

    def test_verifier_detects_source_changes(self) -> None:
        manifest_path = Path(self.temporary_directory.name) / "golden-manifest.json"
        write_manifest(self.source_root, manifest_path)
        self.assertEqual(verify_manifest(self.source_root, manifest_path), [])

        return_path = (
            self.source_root / "2" / "亚马逊物流买家退货-20260731-00000000000.csv"
        )
        return_path.write_text(
            return_path.read_text(encoding="windows-1252").replace(
                '"2","LAS1"', '"3","LAS1"'
            ),
            encoding="windows-1252",
            newline="",
        )

        mismatches = verify_manifest(self.source_root, manifest_path)
        self.assertTrue(mismatches)
        self.assertTrue(any("sha256" in mismatch for mismatch in mismatches))

    def test_scoped_oracle_is_independent_and_verified(self) -> None:
        destination = Path(self.temporary_directory.name) / "scoped.json"
        manifest = write_manifest(
            self.source_root,
            destination,
            site_id=1,
            start=date(2026, 7, 31),
            end=date(2026, 7, 31),
        )
        expected = manifest["canary_expected"]
        self.assertEqual(expected["distinct_seller_sku_count"], 2)
        self.assertEqual(expected["strict_seller_sku_count"], 0)
        self.assertEqual(expected["anomaly_count"], 2)
        self.assertEqual(
            expected["report_membership_counts"],
            {
                "business_only": 0,
                "returns_only": 0,
                "both": 2,
            },
        )
        self.assertEqual(verify_manifest(self.source_root, destination), [])
        expected["anomaly_count"] = 0
        destination.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertIn(
            "manifest field changed: canary_expected",
            verify_manifest(self.source_root, destination),
        )

    def test_scope_cannot_be_inferred_from_an_incomplete_corpus(self) -> None:
        with self.assertRaisesRegex(ManifestError, "exactly one report"):
            write_manifest(
                self.source_root,
                Path(self.temporary_directory.name) / "scoped.json",
                site_id=1,
                start=date(2026, 7, 30),
                end=date(2026, 7, 31),
            )

    def test_scope_rejects_duplicate_daily_report(self) -> None:
        shutil.copyfile(
            self.source_root / "1" / "20260731-BusinessReport-synthetic.csv",
            self.source_root / "1" / "20260731-BusinessReport-duplicate.csv",
        )
        with self.assertRaisesRegex(ManifestError, "exactly one report"):
            write_manifest(
                self.source_root,
                Path(self.temporary_directory.name) / "scoped.json",
                site_id=1,
                start=date(2026, 7, 31),
                end=date(2026, 7, 31),
            )

    def test_unknown_csv_name_is_rejected(self) -> None:
        shutil.copyfile(
            FIXTURE_ROOT / "return-report.csv", self.source_root / "unknown.csv"
        )

        with self.assertRaisesRegex(ManifestError, "Unsupported CSV filename"):
            build_manifest(self.source_root)

    def test_non_finite_numeric_values_are_rejected(self) -> None:
        business_path = self.source_root / "1" / "20260731-BusinessReport-synthetic.csv"
        business_text = business_path.read_text(encoding="utf-8-sig")
        business_path.write_text(
            business_text.replace("US$119.98", "US$NaN"),
            encoding="utf-8-sig",
            newline="",
        )

        with self.assertRaisesRegex(ManifestError, "non-finite"):
            build_manifest(self.source_root)

    def test_non_finite_percentage_values_are_rejected(self) -> None:
        business_path = self.source_root / "1" / "20260731-BusinessReport-synthetic.csv"
        business_text = business_path.read_text(encoding="utf-8-sig")
        business_path.write_text(
            business_text.replace("20.00%", "NaN%", 1),
            encoding="utf-8-sig",
            newline="",
        )

        with self.assertRaisesRegex(ManifestError, "non-finite"):
            build_manifest(self.source_root)


if __name__ == "__main__":
    unittest.main()
