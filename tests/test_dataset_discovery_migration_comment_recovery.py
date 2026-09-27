"""Protect the checksum-locked V111/V112 deployment retry."""

import hashlib

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    _executable_migration_sql,
    load_migrations,
    render_migration,
)


def test_trailing_comment_does_not_become_empty_connector_statement() -> None:
    migrations = {item.version: item for item in load_migrations()}
    for version in ("V111", "V112"):
        migration = migrations[version]
        rendered = render_migration(migration, DEV_DATABASE)
        executable = _executable_migration_sql(migration, DEV_DATABASE)
        assert rendered.strip().splitlines()[-1].lstrip().startswith("--")
        assert executable.rstrip().endswith(";")
        assert hashlib.sha256(migration.source.encode()).hexdigest() == migration.sha256


def test_non_comment_migration_statement_is_preserved() -> None:
    migration = next(item for item in load_migrations() if item.version == "V113")
    assert (
        _executable_migration_sql(migration, DEV_DATABASE).strip()
        == render_migration(migration, DEV_DATABASE).strip()
    )
