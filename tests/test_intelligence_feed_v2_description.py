"""Publisher description on the activation-table feed. Offline only."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from lyme_gap_atlas_data import migrations
from lyme_gap_atlas_data.migrations import (
    BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS,
    DEV_DATABASE,
    DEV_ONLY_MIGRATION_VERSIONS,
    INTELLIGENCE_FEED_DESCRIPTION_MIGRATION,
    PROD_DATABASE,
    PROD_ONLY_MIGRATION_VERSIONS,
    PROTECTED_INTELLIGENCE_MIGRATIONS,
    is_intelligence_prerequisite_batch,
    load_migrations,
    migration_plan,
)

ROOT = Path(__file__).parents[1]
V170 = ROOT / "migrations" / "V170__intelligence_source_activations.sql"
V173 = ROOT / "migrations" / "V173__intelligence_feed_v2_description.sql"
PROJECTION = ROOT / "docs/contracts/intelligence/v2/presentation-projection.sql"
DESCRIPTION_ARGUMENT = (
    "           ),\n           'description', c.item_document:publisher_metadata:description\n"
)
KEPT_KEYS = (
    "publisher",
    "source_family",
    "source_item_id",
    "authors",
    "categories",
    "language",
    "media",
    "date_states",
)


def _view(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    return source[source.index("CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2") :]


def _project(document: dict[str, Any], *, description: bool) -> dict[str, Any]:
    publisher = document["publisher_metadata"]
    states = document["field_states"]
    projected = {
        "publisher": publisher.get("publisher"),
        "source_family": publisher.get("source_family"),
        "source_item_id": publisher.get("source_item_id"),
        "authors": publisher.get("authors"),
        "categories": publisher.get("categories"),
        "language": publisher.get("language"),
        "media": publisher.get("media"),
        "date_states": {
            "published_at": states.get("published_at"),
            "updated_at": states.get("updated_at"),
        },
    }
    if description:
        projected["description"] = publisher.get("description")
    return projected


def _admit(
    captures: list[dict[str, Any]],
    versions: list[dict[str, Any]],
    activations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = []
    for capture in captures:
        document = capture["item_document"]
        if document.get("contract_version") != "2.0.0":
            continue
        version = next(
            (
                item
                for item in versions
                if item["source_id"] == capture["source_id"]
                and item["registry_version"] == capture["registry_version"]
            ),
            None,
        )
        if version is None:
            continue
        registry = version["document"]
        if (
            registry["approval"]["status"] != "approved"
            or registry["trust_review"]["status"] != "approved"
            or registry["state"] not in {"active", "manual"}
        ):
            continue
        admitted = any(
            row["state"] == "ACTIVE"
            and row["source_id"] == version["source_id"]
            and row["registry_version"] == version["registry_version"]
            and row["registry_sha256"] == version["registry_sha256"]
            for row in activations
        )
        if admitted:
            candidates.append(capture)
    winners: dict[tuple[Any, ...], dict[str, Any]] = {}
    for capture in candidates:
        key = (
            capture["item_id"],
            capture["revision_id"],
            capture["source_id"],
            capture["transport"],
        )
        current = winners.get(key)
        rank = (capture["retrieved_at"], capture["capture_id"])
        if current is None or rank > (current["retrieved_at"], current["capture_id"]):
            winners[key] = capture
    return list(winners.values())


def test_description_migration_is_one_protected_step_for_both_databases() -> None:
    pinned = INTELLIGENCE_FEED_DESCRIPTION_MIGRATION
    migration = next(item for item in load_migrations() if item.version == pinned["version"])
    assert migrations._migration_metadata(migration) == pinned
    assert pinned["version"] in BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS
    assert pinned in PROTECTED_INTELLIGENCE_MIGRATIONS
    assert pinned["version"] not in DEV_ONLY_MIGRATION_VERSIONS
    assert pinned["version"] not in PROD_ONLY_MIGRATION_VERSIONS
    assert pinned in migration_plan(DEV_DATABASE)
    assert pinned in migration_plan(PROD_DATABASE)
    assert is_intelligence_prerequisite_batch([pinned])
    sql = migration.source
    assert sql.count("CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2") == 1
    assert "CREATE TABLE" not in sql
    assert "MERGE " not in sql
    assert "GRANT SELECT" not in sql and "GRANT INSERT" not in sql
    assert "COPY GRANTS" in sql
    view = _view(V173)
    for key in KEPT_KEYS:
        assert f"'{key}'" in view
    assert view.index("'description'") > view.index("'date_states'")
    assert "abstract" not in view.lower()
    assert view.split("WHERE", 1)[1].count("description") == 0


def test_v173_view_matches_v170_except_the_description_argument() -> None:
    previous = _view(V170)
    updated = _view(V173)
    assert updated.replace(DESCRIPTION_ARGUMENT, "           )\n", 1) == previous
    assert updated.count(DESCRIPTION_ARGUMENT) == 1
    contract = PROJECTION.read_text(encoding="utf-8")
    updated_construct = updated.split("OBJECT_CONSTRUCT_KEEP_NULL(", 1)[1].split(
        ") AS publisher_metadata", 1
    )[0]
    contract_construct = contract.split("OBJECT_CONSTRUCT_KEEP_NULL(", 1)[1].split(
        ") AS publisher_metadata", 1
    )[0]
    assert contract_construct == updated_construct


def test_description_is_visible_for_v3_and_null_for_v2_without_changing_row_count() -> None:
    description = {
        "text": "E. coli Outbreak linked to Raw Milk Cheese",
        "state": "present",
        "format": "plain_text",
        "origin": "publisher",
    }
    shared = {
        "publisher": "Centers for Disease Control and Prevention",
        "source_family": "cdc_mmwr",
        "source_item_id": "mmwr-guid",
        "authors": ["Test Author"],
        "categories": ["Tick borne disease"],
        "language": "en",
        "media": [],
        "date_states": {"published_at": "present", "updated_at": "not_provided"},
    }
    historical = {**shared}
    current = {**shared, "description": description}
    versions = [
        {
            "source_id": "cdc-mmwr",
            "registry_version": version,
            "registry_sha256": f"{version}" * 32,
            "document": {
                "state": "active",
                "approval": {"status": "approved"},
                "trust_review": {"status": "approved"},
            },
        }
        for version in (2, 3)
    ]
    activations = [
        {
            "source_id": "cdc-mmwr",
            "registry_version": version,
            "registry_sha256": f"{version}" * 32,
            "state": "ACTIVE",
        }
        for version in (2, 3)
    ]

    def capture(
        item_id: str,
        registry_version: int,
        publisher: dict[str, Any],
        retrieved_at: str,
        capture_id: str,
    ) -> dict[str, Any]:
        return {
            "item_id": item_id,
            "revision_id": "revision",
            "source_id": "cdc-mmwr",
            "registry_version": registry_version,
            "transport": "rss",
            "retrieved_at": retrieved_at,
            "capture_id": capture_id,
            "item_document": {
                "contract_version": "2.0.0",
                "publisher_metadata": publisher,
                "field_states": {"published_at": "present", "updated_at": "not_provided"},
            },
        }

    captures = [
        capture("historical-item", 2, historical, "2026-10-24T00:00:00Z", "v2"),
        capture("current-item", 3, current, "2026-10-25T00:00:00Z", "v3-old"),
        capture("current-item", 3, current, "2026-10-25T01:00:00Z", "v3"),
    ]
    admitted = _admit(captures, versions, activations)
    previous = [_project(row["item_document"], description=False) for row in admitted]
    updated = [_project(row["item_document"], description=True) for row in admitted]
    assert len(previous) == len(updated) == 2
    assert {row["item_id"] for row in admitted} == {"historical-item", "current-item"}
    historical_row = next(row for row in admitted if row["item_id"] == "historical-item")
    current_row = next(row for row in admitted if row["item_id"] == "current-item")
    assert current_row["capture_id"] == "v3"
    projected_current = _project(current_row["item_document"], description=True)
    projected_historical = _project(historical_row["item_document"], description=True)
    assert projected_current["description"]["text"] == description["text"]
    assert projected_current["description"]["state"] == "present"
    assert projected_historical["description"] is None
    for key in KEPT_KEYS:
        assert (
            projected_current[key] == _project(current_row["item_document"], description=False)[key]
        )
        assert projected_historical[key] == projected_current[key]


def _cursor(ledger: list[tuple[str, str]]) -> Mock:
    cursor = Mock()
    cursor.fetchall.side_effect = [ledger, []]
    return cursor


def _apply(
    monkeypatch: pytest.MonkeyPatch,
    database: str,
    planned: list[migrations.Migration],
    ledger: list[tuple[str, str]],
    *,
    protected: bool,
) -> tuple[Mock, list[str]]:
    monkeypatch.setattr(migrations, "load_migrations", lambda: planned)
    cursor = _cursor(ledger)
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *_, **__: nullcontext(connection))
    executed = migrations.apply_migrations(
        Mock(),
        database,
        expected_pending=[INTELLIGENCE_FEED_DESCRIPTION_MIGRATION],
        protected_intelligence_prerequisite=protected,
    )
    return connection, executed


@pytest.mark.parametrize("database", [DEV_DATABASE, PROD_DATABASE])
def test_v173_requires_recorded_v170_and_the_protected_path(
    monkeypatch: pytest.MonkeyPatch, database: str
) -> None:
    loaded = load_migrations()
    v170 = next(item for item in loaded if item.version == "V170")
    v173 = next(item for item in loaded if item.version == "V173")
    with pytest.raises(PermissionError, match="V173 requires recorded V170"):
        _apply(monkeypatch, database, [v173], [], protected=True)

    with pytest.raises(PermissionError, match="protected intelligence prerequisite"):
        _apply(
            monkeypatch,
            database,
            [v170, v173],
            [("V170", v170.sha256)],
            protected=False,
        )

    connection, executed_versions = _apply(
        monkeypatch,
        database,
        [v170, v173],
        [("V170", v170.sha256)],
        protected=True,
    )
    assert executed_versions == ["V173"]
    executed = connection.execute_string.call_args.args[0]
    assert "c.item_document:publisher_metadata:description" in executed
    assert "GRANT SELECT" not in executed
    assert "JOIN GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS" in executed
