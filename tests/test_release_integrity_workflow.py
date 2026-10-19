"""The new migration pair uses the existing protected immutable-image path."""

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def test_scope_uses_protected_promotion_and_cannot_run_other_mutation_modes():
    raw = (ROOT / ".github/workflows/promote-prod.yml").read_text()
    workflow = yaml.safe_load(raw)
    assert workflow["jobs"]["promote"]["environment"] == "production"
    assert 'test "$dev_digest" = "$IMAGE_DIGEST"' in raw
    assert 'test "$source_digest" = "$IMAGE_DIGEST"' in raw
    step = next(
        s
        for s in workflow["jobs"]["promote"]["steps"]
        if s.get("name") == "Apply only reviewed release integrity migrations"
    )
    assert "inputs.release_integrity_only == true" in step["if"]
    assert "scripts/apply_release_integrity_migrations.py" in step["run"]
    for flag in (
        "cdc_admission_only",
        "county_context_only",
        "january_climate_only",
        "january_bulk_recovery_only",
        "january_point_query_only",
        "protected_intelligence_prerequisite",
    ):
        assert f"test '${{{{ inputs.{flag} }}}}' = false" in step["run"]
    assert "inputs.release_integrity_only != true" in workflow["jobs"]["january-climate"]["if"]


def test_unapproved_entrypoint_stops_before_connecting(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "integrity_install", ROOT / "scripts/apply_release_integrity_migrations.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("RELEASE_INTEGRITY_ONLY", raising=False)
    monkeypatch.setattr(
        module, "SnowflakeSettings", lambda: pytest.fail("No credentials before gate")
    )
    with pytest.raises(SystemExit, match="PROTECTED_REVIEWED_MAIN"):
        module.main()
