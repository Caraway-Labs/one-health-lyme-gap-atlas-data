"""Activation-table feed admission. Offline only: no warehouse connection."""

from __future__ import annotations

import json
from pathlib import Path

from lyme_gap_atlas_data.intelligence_activations import (
    activation_for_registration,
    activation_merge_statement,
    load_registry_documents,
    source_is_active,
)
from lyme_gap_atlas_data.intelligence_items import identity_hash
from lyme_gap_atlas_data.migrations import (
    BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS,
    DEV_DATABASE,
    DEV_ONLY_MIGRATION_VERSIONS,
    INTELLIGENCE_SOURCE_ACTIVATION_MIGRATION,
    PROD_DATABASE,
    PROD_ONLY_MIGRATION_VERSIONS,
    PROTECTED_INTELLIGENCE_MIGRATIONS,
    load_migrations,
    migration_plan,
)

ROOT = Path(__file__).parents[1]
LIVE_SOURCES = (
    "cdc-eid-ahead-of-print",
    "cdc-eid-expedited",
    "cdc-mmwr",
    "cdc-outbreaks",
    "nih-news-releases",
)


def _migration_sql() -> str:
    pinned = INTELLIGENCE_SOURCE_ACTIVATION_MIGRATION
    migration = next(item for item in load_migrations() if item.version == pinned["version"])
    assert migration.filename == pinned["filename"]
    assert migration.sha256 == pinned["sha256"]
    return migration.source


def _view_sql(sql: str) -> str:
    return sql.split("CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2", 1)[1]


def test_activation_migration_is_one_protected_step_for_both_databases() -> None:
    pinned = INTELLIGENCE_SOURCE_ACTIVATION_MIGRATION
    assert pinned["version"] in BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS
    assert pinned in PROTECTED_INTELLIGENCE_MIGRATIONS
    assert pinned["version"] not in DEV_ONLY_MIGRATION_VERSIONS
    assert pinned["version"] not in PROD_ONLY_MIGRATION_VERSIONS
    assert pinned in migration_plan(DEV_DATABASE)
    assert pinned in migration_plan(PROD_DATABASE)
    sql = _migration_sql()
    assert sql.count("CREATE TABLE") == 1
    assert sql.count("MERGE INTO GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS") == 1
    assert sql.count("CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2") == 1
    assert "PRIMARY KEY (source_id, registry_version)" in sql
    for column in (
        "source_id",
        "registry_version",
        "registry_sha256",
        "state",
        "decision_id",
        "activated_at",
    ):
        assert column in sql
    assert "GRANT INSERT" not in sql and "GRANT UPDATE" not in sql and "GRANT DELETE" not in sql


def test_view_uses_one_active_join_and_keeps_the_contract_filters() -> None:
    view = _view_sql(_migration_sql())
    assert view.count("JOIN GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS") == 1
    assert "a.state = 'ACTIVE'" in view
    assert "CASE" not in view and "blocked_source_versions" not in view
    assert "c.item_document:contract_version::VARCHAR = '2.0.0'" in view
    assert "s.registry_document:approval:status::VARCHAR = 'approved'" in view
    assert "s.registry_document:trust_review:status::VARCHAR = 'approved'" in view
    assert "s.registry_document:state::VARCHAR IN ('active', 'manual')" in view
    for source_id in LIVE_SOURCES:
        assert source_id not in view


def test_backfill_blocks_superseded_versions_of_the_live_sources() -> None:
    sql = _migration_sql().split("CREATE OR REPLACE VIEW", 1)[0]
    for source_id in LIVE_SOURCES:
        assert f"'{source_id}'" in sql
    assert "IFF(newer.source_id IS NULL, 'ACTIVE', 'BLOCKED')" in sql
    documents = load_registry_documents()
    by_source: dict[str, list[dict]] = {}
    for document in documents:
        if document["source_id"] in LIVE_SOURCES:
            by_source.setdefault(document["source_id"], []).append(document)
    assert set(by_source) == set(LIVE_SOURCES)
    for versions in by_source.values():
        assert {document["registry_version"] for document in versions} == {1, 2}


def test_registration_merge_is_one_idempotent_statement() -> None:
    documents = {
        (document["source_id"], document["registry_version"]): document
        for document in load_registry_documents()
    }
    current = documents[("cdc-eid-ahead-of-print", 2)]
    previous = documents[("cdc-eid-ahead-of-print", 1)]
    rows = activation_for_registration(current, superseded=(previous,))
    again = activation_for_registration(current, superseded=(previous,))
    assert rows == again
    assert [row.state for row in rows] == ["ACTIVE", "BLOCKED"]
    assert rows[0].registry_sha256 == identity_hash(current)
    assert rows[1].registry_sha256 == identity_hash(previous)
    assert rows[0].decision_id == current["approval"]["decision_ref"]
    statement, params = activation_merge_statement(rows)
    assert statement.count("MERGE INTO") == 1
    assert "WHEN MATCHED AND" in statement and "WHEN NOT MATCHED THEN INSERT" in statement
    assert params == (
        current["source_id"],
        2,
        identity_hash(current),
        "ACTIVE",
        current["approval"]["decision_ref"],
        previous["source_id"],
        1,
        identity_hash(previous),
        "BLOCKED",
        previous["approval"]["decision_ref"],
    )


def test_active_set_is_the_registry_json_intersected_with_activation_rows() -> None:
    documents = load_registry_documents()
    current = next(
        document
        for document in documents
        if document["source_id"] == "nih-news-releases" and document["registry_version"] == 2
    )
    previous = next(
        document
        for document in documents
        if document["source_id"] == "nih-news-releases" and document["registry_version"] == 1
    )
    rows = activation_for_registration(current, superseded=(previous,))
    assert source_is_active(current, documents, rows)
    assert not source_is_active(previous, documents, rows)
    fresh = json.loads(json.dumps(current))
    fresh["source_id"] = "example-new-feed"
    fresh_rows = activation_for_registration(fresh)
    assert source_is_active(fresh, (fresh,), fresh_rows)
    assert not any(row.source_id == "example-new-feed" for row in rows)
