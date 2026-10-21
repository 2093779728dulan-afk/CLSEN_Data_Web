from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPOSITORY_ROOT / "scripts" / "stage6-demo.ps1"
MODULE = REPOSITORY_ROOT / "backend" / "app" / "demo" / "stage6.py"


def test_stage6_script_requires_two_explicit_dates_and_calls_demo_module() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert source.count("[Parameter(Mandatory)]") >= 2
    assert "[string]$PrimaryDate" in source
    assert "[string]$IsolationDate" in source
    assert '"--primary-date", $PrimaryDate' in source
    assert '"--isolation-date", $IsolationDate' in source
    assert '"-m", "app.demo.stage6"' in source
    assert "SupportsShouldProcess" in source


def test_stage6_entry_never_selects_a_production_database_contract() -> None:
    script_source = SCRIPT.read_text(encoding="utf-8")
    module_source = MODULE.read_text(encoding="utf-8")

    assert "APP_TEST_DATABASE_URL" in module_source
    assert "APP_TEST_RUNTIME_DATABASE_URL" in module_source
    assert 'os.environ.get("APP_DATABASE_URL")' not in module_source
    assert 'from_env("APP_DATABASE_URL")' not in module_source
    assert "APP_DATABASE_URL" not in script_source
    assert "alembic" not in script_source.casefold()
    assert "DROP DATABASE" not in module_source
    assert "TRUNCATE" not in module_source


def test_stage6_entry_fail_closes_on_schema_and_database_name() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "clsen_data_test(?:_[a-z0-9_]+)?" in source
    assert "requires migration 0009 or newer" in source
    assert "never runs migrations" in source
    assert 'stage7_api_available": False' in source
    assert 'stage8_ui_available": False' in source
