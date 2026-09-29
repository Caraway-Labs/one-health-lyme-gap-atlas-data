"""PROD migration authority must fail before schema DDL when its grant is missing."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from lyme_gap_atlas_data.migrations import (
    migration_authority_preflight,
    pending_schema_creation_versions,
)

PROD = "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
ROLE = "OH_LYME_PROD_MIGRATION_DEPLOYER"


class Cursor:
    description = [("privilege",), ("granted_on",), ("name",)]

    def __init__(self, grants: list[tuple[str, str, str]]) -> None:
        self.grants = grants
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
            return [(f"V{number:03d}",) for number in range(1, 106)]
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
    cursor = Cursor([("USAGE", "DATABASE", PROD)])
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
    cursor = Cursor([("CREATE SCHEMA", "DATABASE", PROD)])
    with patch("lyme_gap_atlas_data.migrations.connect", return_value=connection(cursor)):
        result = migration_authority_preflight(object(), PROD)  # type: ignore[arg-type]
    assert result == {"pending_schema_creation": ["V106"], "create_schema_grant": "present"}
