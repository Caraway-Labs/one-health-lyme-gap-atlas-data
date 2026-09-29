"""PROD migration authority must fail before any migration DDL or GRANT."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from lyme_gap_atlas_data.migrations import (
    load_migrations,
    migration_authority_preflight,
    pending_schema_creation_versions,
)

PROD = "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
ROLE = "OH_LYME_PROD_MIGRATION_DEPLOYER"


class Cursor:
    description = [("privilege",), ("granted_on",), ("name",), ("grant_option",)]

    def __init__(
        self,
        grants: list[tuple[str, str, str, bool]],
        applied_versions: set[str] | None = None,
    ) -> None:
        self.grants = grants
        self.applied_versions = applied_versions or {f"V{number:03d}" for number in range(1, 106)}
        self.statements: list[str] = []

    def __enter__(self) -> "Cursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def fetchone(self) -> tuple[str]:
        return (ROLE,)

    def fetchall(self) -> list[tuple[str, ...]]:
        if self.statements[-1].startswith("SELECT version"):
            return [(version,) for version in sorted(self.applied_versions)]
        return self.grants


@contextmanager
def connection(cursor: Cursor):
    class Connection:
        def cursor(self) -> Cursor:
            return cursor

    yield Connection()


def test_pending_prod_schema_migration_is_v106() -> None:
    applied = {f"V{number:03d}" for number in range(1, 106)}
    assert pending_schema_creation_versions(PROD, applied) == ["V106"]


def test_preflight_rejects_missing_create_schema_without_ddl() -> None:
    cursor = Cursor([("USAGE", "DATABASE", PROD, False)])
    with (
        patch("lyme_gap_atlas_data.migrations.connect", return_value=connection(cursor)),
        pytest.raises(ValueError, match="lacks CREATE SCHEMA.*V106"),
    ):
        migration_authority_preflight(object(), PROD)  # type: ignore[arg-type]
    assert cursor.statements == [
        f"USE DATABASE {PROD}",
        "SELECT CURRENT_ROLE()",
        "SELECT version FROM GOVERNANCE.SCHEMA_MIGRATIONS",
        f"SHOW GRANTS TO ROLE {ROLE}",
    ]


def test_preflight_accepts_exact_prod_database_grant() -> None:
    cursor = Cursor(
        [
            ("CREATE SCHEMA", "DATABASE", PROD, False),
            *catalog_delegation_grants(),
        ]
    )
    with patch("lyme_gap_atlas_data.migrations.connect", return_value=connection(cursor)):
        result = migration_authority_preflight(object(), PROD)  # type: ignore[arg-type]
    assert result == {
        "pending_schema_creation": ["V106"],
        "create_schema_grant": "present",
        "v126_grant_authority": "present",
    }


def catalog_delegation_grants() -> list[tuple[str, str, str, bool]]:
    return [
        ("SELECT", "TABLE", f"{PROD}.GOVERNANCE.{table}", True)
        for table in ("CATALOG_DISCOVERY_OBSERVATIONS", "CATALOG_RESOURCES")
    ]


def test_partial_v124_state_fails_on_first_unauthorized_v126_grant() -> None:
    applied = {f"V{number:03d}" for number in range(1, 114)} | {"V123", "V124"}
    cursor = Cursor([], applied)
    with (
        patch("lyme_gap_atlas_data.migrations.connect", return_value=connection(cursor)),
        pytest.raises(ValueError, match="CATALOG_DISCOVERY_OBSERVATIONS"),
    ):
        migration_authority_preflight(object(), PROD)  # type: ignore[arg-type]
    assert cursor.statements[-1] == f"SHOW GRANTS TO ROLE {ROLE}"


def test_partial_v124_state_requires_both_exact_grant_options() -> None:
    applied = {f"V{number:03d}" for number in range(1, 114)} | {"V123", "V124"}
    cursor = Cursor([catalog_delegation_grants()[0]], applied)
    with (
        patch("lyme_gap_atlas_data.migrations.connect", return_value=connection(cursor)),
        pytest.raises(ValueError, match="CATALOG_RESOURCES"),
    ):
        migration_authority_preflight(object(), PROD)  # type: ignore[arg-type]


def test_partial_v124_state_accepts_only_both_grant_options() -> None:
    applied = {f"V{number:03d}" for number in range(1, 114)} | {"V123", "V124"}
    cursor = Cursor(catalog_delegation_grants(), applied)
    with patch("lyme_gap_atlas_data.migrations.connect", return_value=connection(cursor)):
        result = migration_authority_preflight(object(), PROD)  # type: ignore[arg-type]
    assert result["v126_grant_authority"] == "present"
    assert result["create_schema_grant"] == "not_required"


def test_v126_checksum_and_narrow_admin_bootstrap_are_preserved() -> None:
    v126 = next(item for item in load_migrations() if item.version == "V126")
    assert v126.sha256 == "97f2684ce6fff946d2c07c28cfae59d06482a985b8f38af827a151a09280da12"
    bootstrap = Path("scripts/bootstrap_dataset_discovery_roles_prod.sql").read_text()
    for table in ("CATALOG_DISCOVERY_OBSERVATIONS", "CATALOG_RESOURCES"):
        assert (
            f"GRANT SELECT ON TABLE {PROD}.GOVERNANCE.{table}\n"
            "  TO ROLE OH_LYME_PROD_MIGRATION_DEPLOYER WITH GRANT OPTION;"
        ) in bootstrap
    assert bootstrap.count("WITH GRANT OPTION") == 2
    assert "MANAGE GRANTS" not in bootstrap
    assert (
        "GRANT ROLE OH_LYME_PROD_DATASET_DISCOVERY_WRITE_OWNER\n"
        "  TO ROLE OH_LYME_PROD_MIGRATION_DEPLOYER;"
    ) in bootstrap
