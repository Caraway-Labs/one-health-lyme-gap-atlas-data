"""Adding a registry source and a migration must not depend on literal counts."""

from __future__ import annotations

from semantic_contracts import (
    WORKFLOWS,
    assert_migrations_agree,
    assert_workflow_security,
    definition_paths_by_source_id,
    migration_records_from_filenames,
    planned_versions,
    registry_source_ids,
    selection_source_ids,
)

from lyme_gap_atlas_data.ingestion.intelligence_runtime import PROD_SOURCE_DEFINITIONS
from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_plan,
)


def test_migration_filenames_agree_with_loader_and_plans() -> None:
    loaded = assert_migrations_agree()
    assert [item.version for item in loaded] == [item.version for item in load_migrations()]
    assert [record[0] for record in migration_records_from_filenames()] == [
        item.version for item in loaded
    ]
    for database in (DEV_DATABASE, PROD_DATABASE):
        assert [item["version"] for item in migration_plan(database)] == planned_versions(database)


def test_prod_intelligence_definitions_are_selected_and_registered() -> None:
    selected = selection_source_ids()
    registered = registry_source_ids()
    definitions = definition_paths_by_source_id()
    assert set(PROD_SOURCE_DEFINITIONS) <= selected
    assert set(PROD_SOURCE_DEFINITIONS) <= registered
    for source_id, path in PROD_SOURCE_DEFINITIONS.items():
        assert definitions[source_id] == path


def test_every_workflow_satisfies_semantic_security_properties() -> None:
    paths = sorted(WORKFLOWS.glob("*.yml"))
    assert paths
    for path in paths:
        assert_workflow_security(path)
