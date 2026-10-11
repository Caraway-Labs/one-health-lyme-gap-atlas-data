"""Keep the DEV repair pinned to the reviewed intelligence SQL."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_plan,
    render_migration,
)


def test_v142_is_dev_only_and_uses_reviewed_shapes() -> None:
    migration = next(item for item in load_migrations() if item.version == "V142")
    sql = render_migration(migration, DEV_DATABASE)
    assert "V142" in {row["version"] for row in migration_plan(DEV_DATABASE)}
    assert "V142" not in {row["version"] for row in migration_plan(PROD_DATABASE)}

    root = Path(__file__).resolve().parents[1] / "docs/contracts/intelligence/v2"
    raw = (root / "raw-runtime-schema-review.sql").read_text(encoding="utf-8")
    projection = (root / "presentation-projection.sql").read_text(encoding="utf-8")
    for name in ("INTELLIGENCE_RAW_RETENTION_DOCUMENTS", "INTELLIGENCE_RAW_RETENTION_AUDIT"):
        reviewed = raw.split(f"CREATE TABLE GOVERNANCE.{name} (", 1)[1].split(";", 1)[0]
        assert f"CREATE TABLE IF NOT EXISTS GOVERNANCE.{name} ({reviewed};" in sql
    for view in ("INTELLIGENCE_FEED_V", "INTELLIGENCE_FEED_V2"):
        start = (
            "CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V COPY GRANTS AS"
            if view == "INTELLIGENCE_FEED_V"
            else "CREATE VIEW IF NOT EXISTS PRESENTATION.INTELLIGENCE_FEED_V2 AS"
        )
        reviewed = projection.split(start, 1)[1].split(";", 1)[0]
        assert f"{start}{reviewed};" in sql

    grants = [line for line in sql.splitlines() if line.startswith("GRANT ")]
    assert grants == [
        "GRANT SELECT, INSERT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS "
        "TO ROLE OH_LYME_DEV_RUNTIME;",
        "GRANT INSERT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_RETENTION_AUDIT "
        "TO ROLE OH_LYME_DEV_RUNTIME;",
        "GRANT SELECT ON VIEW PRESENTATION.INTELLIGENCE_FEED_V2 TO ROLE OH_LYME_DEV_READ;",
    ]
    assert "DELETE " not in sql
    assert "GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS" not in sql
