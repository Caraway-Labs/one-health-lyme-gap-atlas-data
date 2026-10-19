"""Preparation may render the approved pair but cannot apply it or escape schemas."""

import importlib.util
from pathlib import Path

import pytest

from lyme_gap_atlas_data.migrations import load_migrations

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dev_preparation", ROOT / "scripts/prepare_release_integrity_dev_plan.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize("version", ["V157", "V158", "V159"])
def test_every_static_and_javascript_sql_reference_is_isolated(version):
    migration = next(m for m in load_migrations() if m.version == version)
    sql = module.render_fixture(migration)
    for schema in module.SCHEMAS:
        assert schema + "." not in sql.replace("RI706_" + schema + ".", "")
    assert "{{" not in sql
    assert "OH_LYME_PROD_" not in sql
    assert sql.startswith("-- UNAPPROVED")


def test_unrelated_migration_cannot_enter_fixture_scope():
    migration = next(m for m in load_migrations() if m.version == "V155")
    with pytest.raises(ValueError, match="exact V157/V158"):
        module.render_fixture(migration)


def test_proposal_does_not_claim_image_or_execution_and_cannot_overwrite(tmp_path):
    plan = module.prepare(tmp_path / "plan")
    assert plan["image_digest"] is plan["dev_execution_receipt"] is None
    assert plan["status"] == "PROPOSAL_NOT_AUTHORIZATION_NOT_EXECUTED"
    assert len(plan["migrations"]) == 3
    with pytest.raises(ValueError, match="fresh"):
        module.prepare(tmp_path / "plan")
