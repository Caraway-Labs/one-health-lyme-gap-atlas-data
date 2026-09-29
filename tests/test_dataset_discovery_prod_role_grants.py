"""PROD Dataset Discovery role boundary under accepted ADR 0041."""

from pathlib import Path

import pytest

from lyme_gap_atlas_data.migrations import load_migrations, migration_plan, render_migration

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/bootstrap_dataset_discovery_roles_prod.sql"
GRANTS = ROOT / "migrations/V126__prod_dataset_discovery_role_grants.sql"


def statements(path: Path) -> list[str]:
    source = "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("--")
    )
    return [
        " ".join(statement.upper().split()) for statement in source.split(";") if statement.strip()
    ]


def test_account_bootstrap_is_prod_only_and_separates_roles() -> None:
    sql = statements(BOOTSTRAP)
    assert [s for s in sql if s.startswith("CREATE ROLE IF NOT EXISTS")] == [
        f"CREATE ROLE IF NOT EXISTS OH_LYME_PROD_DATASET_DISCOVERY_{name}"
        for name in ("RUNTIME", "REVIEWER", "WRITE_OWNER")
    ]
    assert [s for s in sql if s.startswith("GRANT READ SESSION")] == [
        "GRANT READ SESSION ON ACCOUNT TO ROLE OH_LYME_PROD_DATASET_DISCOVERY_WRITE_OWNER"
    ]
    assert [s for s in sql if s.startswith("GRANT ROLE")] == [
        "GRANT ROLE OH_LYME_PROD_DATASET_DISCOVERY_WRITE_OWNER "
        "TO ROLE OH_LYME_PROD_MIGRATION_DEPLOYER"
    ]
    assert not any("OH_LYME_DEV" in s for s in sql)
    assert not any("TO USER" in s or "CREATE USER" in s or "ALTER USER" in s for s in sql)
    assert not any("GRANT MANAGE GRANTS" in s for s in sql)


def test_grant_migration_is_protected_prod_only() -> None:
    migration = next(item for item in load_migrations() if item.version == "V126")
    assert migration.filename == GRANTS.name
    assert migration.sha256 == "35d369399ccae3f936dee7e7b32c530f963c5a81d0b1ff7664d85f791f08568c"
    assert "V126" in {item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")}
    assert "V126" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_DEV")
    }
    with pytest.raises(ValueError, match="PROD-only"):
        render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_DEV")
    assert "USE DATABASE ONE_HEALTH_LYME_GAP_ATLAS_PROD" in render_migration(
        migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
    )


def test_account_owned_catalog_grants_are_admin_bootstrap_only() -> None:
    bootstrap = statements(BOOTSTRAP)
    migration = statements(GRANTS)
    for table in ("CATALOG_DISCOVERY_OBSERVATIONS", "CATALOG_RESOURCES"):
        expected = (
            "GRANT SELECT ON TABLE ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE."
            f"{table} TO ROLE OH_LYME_PROD_DATASET_DISCOVERY_WRITE_OWNER"
        )
        assert expected in bootstrap
        assert not any(f"GOVERNANCE.{table}" in statement for statement in migration)


def test_runtime_reviewer_and_write_owner_are_bounded() -> None:
    sql = statements(GRANTS)
    assert not any("OH_LYME_DEV" in s for s in sql)
    assert not any("READ SESSION" in s or "CREATE ROLE" in s for s in sql)
    ownership = [s for s in sql if s.startswith("GRANT OWNERSHIP")]
    assert len(ownership) == 6
    assert all("ON PROCEDURE" in s and "COPY CURRENT GRANTS" in s for s in ownership)
    assert all("TO ROLE OH_LYME_PROD_DATASET_DISCOVERY_WRITE_OWNER" in s for s in ownership)
    for statement in sql:
        assert not any(
            token in statement
            for token in ("GRANT ALL", "GRANT DELETE", "GRANT CREATE", "GRANT MANAGE GRANTS")
        )
        if "TO ROLE OH_LYME_PROD_DATASET_DISCOVERY_RUNTIME" in statement:
            assert "ON TABLE" not in statement
            assert "GOVERNANCE." not in statement
            assert "SP_APPEND_REVIEW_EVENT" not in statement
            assert "SP_HANDOFF_DATASET_DISCOVERY_RECOMMENDATION" not in statement
        if "TO ROLE OH_LYME_PROD_DATASET_DISCOVERY_REVIEWER" in statement:
            assert "ON TABLE" not in statement
            assert not any(
                name in statement
                for name in (
                    "SP_CREATE_RUN",
                    "SP_RECORD_CANDIDATE_OUTCOME",
                    "SP_COMMIT_RECOMMENDATION",
                    "SP_FINALIZE_RUN",
                    "SP_RECORD_SOURCE_REVIEW_DECISION",
                )
            )
