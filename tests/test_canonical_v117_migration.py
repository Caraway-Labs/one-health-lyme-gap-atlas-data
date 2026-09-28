"""The repository retains the immutable migration sequence already applied in DEV."""

from lyme_gap_atlas_data.migrations import (
    DEV_ONLY_MIGRATION_VERSIONS,
    load_migrations,
    migration_execution_role,
    migration_plan,
)

APPLIED_V117_SHA256 = "97dc205df634efdefa5dc561b36481068cfaa09dc6391d2acdc8cdf474add5e0"


def test_v117_matches_existing_dev_receipt_and_owner() -> None:
    migrations = load_migrations()
    versions = [item.version for item in migrations]
    assert len(versions) == len(set(versions))
    assert [version for version in versions if version >= "V117"] == [
        "V117",
        "V119",
        "V120",
    ]
    assert "V118" not in versions
    stage = next(item for item in migrations if item.version == "V117")
    assert stage.filename == "V117__ingestion_bulk_transport_stage.sql"
    assert stage.sha256 == APPLIED_V117_SHA256
    assert migration_execution_role(stage, "ONE_HEALTH_LYME_GAP_ATLAS_DEV") == ("OH_LYME_DEV_OWNER")
    assert "CREATE STAGE IF NOT EXISTS GOVERNANCE.INGESTION_BULK_STAGE" in stage.source
    assert "GRANT READ, WRITE ON STAGE" in stage.source
    assert all(word not in stage.source for word in ("DELETE", "TRUNCATE", "DROP", "REPLACE"))


def test_applied_sequence_is_dev_only_with_intentional_gap() -> None:
    assert {"V117", "V119", "V120"} <= DEV_ONLY_MIGRATION_VERSIONS
    dev = [item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_DEV")]
    prod = {item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")}
    assert [version for version in dev if version >= "V117"] == ["V117", "V119", "V120"]
    assert not {"V117", "V118", "V119", "V120"} & prod
