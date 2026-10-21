from pathlib import Path

import yaml  # type: ignore[import-untyped]


def test_public_ci_uses_only_standard_hosted_runners_and_mysql84() -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.load(
        (root / ".github/workflows/public-ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    jobs = workflow["jobs"]
    profiles = {"backend-ubuntu", "backend-windows", "frontend", "mysql-84"}
    assert set(jobs) == profiles | {"public-required"}
    assert set(jobs["public-required"]["needs"]) == profiles
    assert workflow["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in workflow["on"]
    for name, job in jobs.items():
        assert job["runs-on"] == (
            "windows-2025" if name == "backend-windows" else "ubuntu-24.04"
        )
        assert "environment" not in job
        assert "secrets." not in str(job)
    mysql = jobs["mysql-84"]
    assert mysql["timeout-minutes"] == "120"
    execution = next(step for step in mysql["steps"] if step.get("id") == "mysql")
    assert "-MySqlVersion 8.4" in execution["run"]
    assert execution["timeout-minutes"] == "110"
    assert mysql["steps"][-1]["if"] == "always()"
    assert mysql["steps"][-1]["run"] == "./scripts/cleanup-ci-mysql.ps1"
