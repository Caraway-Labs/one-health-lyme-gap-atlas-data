"""The forward DEV view exposes bounded public metadata at its retained path."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import load_migrations, migration_plan

SQL = Path(__file__).resolve().parents[1] / (
    "migrations/V117__dev_dataset_discovery_safe_metadata_projection.sql"
)
AUDIT_SQL = Path(__file__).resolve().parents[1] / (
    "migrations/V118__dev_dataset_discovery_candidate_decision_audit.sql"
)


def test_forward_migration_is_dev_only_and_preserves_grants() -> None:
    assert "V117" in {item.version for item in load_migrations()}
    assert "V117" in {item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_DEV")}
    assert "V117" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    assert "V118" in {item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_DEV")}
    assert "V118" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    sql = SQL.read_text(encoding="utf-8")
    assert "V_CANDIDATE_OBSERVATION_FIELDS\nCOPY GRANTS AS" in sql
    assert "CREATE OR REPLACE VIEW" in sql


def test_public_dcat_paths_are_bounded_without_raw_payload_projection() -> None:
    sql = SQL.read_text(encoding="utf-8")
    for field in ("issued", "modified", "spatial", "temporal", "license", "accessLevel"):
        assert f"metadata_payload:catalog_record:dcat:{field}::VARCHAR" in sql
    for field in (
        "keywords",
        "theme",
        "resource_title",
        "resource_role",
        "resource_type",
        "canonical_url",
        "distribution_description",
        "distribution_media_type",
        "distribution_format",
        "catalog_record_id",
        "parent_dataset_id",
        "documentation_url",
    ):
        assert f"'{field}'" in sql
    assert "OBJECT_CONSTRUCT_KEEP_NULL" in sql
    assert "r.resource_payload AS" not in sql
    assert "d.metadata_payload AS" not in sql


def test_decision_audit_is_atomic_with_candidate_outcome() -> None:
    sql = AUDIT_SQL.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS decision_record VARIANT" in sql
    assert "UNEXPECTED_DECISION_FIELD" in sql
    assert "DECISION_OUTCOME_MISMATCH" in sql
    assert "BEGIN TRANSACTION" in sql
    assert "decision_record)" in sql
    assert "CONFLICTING_OPERATION_REPLAY" in sql
    assert "COPY GRANTS" in sql
