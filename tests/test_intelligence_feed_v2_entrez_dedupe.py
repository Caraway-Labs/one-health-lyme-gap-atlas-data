"""V174 feed view: V173 fields, entrez newest-item dedupe, and FEED_SORT_AT."""

from __future__ import annotations

import re
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from lyme_gap_atlas_data import migrations
from lyme_gap_atlas_data.migrations import (
    BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS,
    DEV_DATABASE,
    DEV_ONLY_MIGRATION_VERSIONS,
    INTELLIGENCE_FEED_ENTREZ_DEDUPE_MIGRATION,
    PROD_DATABASE,
    PROD_ONLY_MIGRATION_VERSIONS,
    PROTECTED_INTELLIGENCE_MIGRATIONS,
    is_intelligence_prerequisite_batch,
    load_migrations,
    migration_plan,
)

ROOT = Path(__file__).parents[1]
V173 = ROOT / "migrations" / "V173__intelligence_feed_v2_description.sql"
V174 = ROOT / "migrations" / "V174__intelligence_feed_v2_entrez_dedupe.sql"
EID_ITEM = "bd4c0099" + ("ab" * 26) + "4eee"
PUBLISHER_KEYS = (
    "publisher",
    "source_family",
    "source_item_id",
    "authors",
    "categories",
    "language",
    "media",
    "date_states",
    "description",
    "abstract",
    "abstract_suppressed",
)
_DML = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE)\b", re.IGNORECASE)


def _view(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    return source[source.index("CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2") :]


def _outer_publisher_keys(view: str) -> tuple[str, ...]:
    construct = view.split("OBJECT_CONSTRUCT_KEEP_NULL(", 1)[1].split(") AS publisher_metadata", 1)[
        0
    ]
    keys: list[str] = []
    for line in construct.splitlines():
        if len(line) > 11 and line[:11] == "           " and line[11] == "'":
            keys.append(line.split("'", 2)[1])
    return tuple(keys)


def _v173_body(view: str) -> str:
    select = view.split("COPY GRANTS AS\n", 1)[1]
    return select.split("QUALIFY", 1)[0]


def test_v174_is_v173_plus_entrez_dedupe_and_feed_sort_at() -> None:
    pinned = INTELLIGENCE_FEED_ENTREZ_DEDUPE_MIGRATION
    migration = next(item for item in load_migrations() if item.version == "V174")
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
    assert _DML.search(sql) is None
    assert "matched_queries" not in sql
    assert "GRANT " not in sql
    assert "COPY GRANTS" in sql
    previous = _view(V173)
    updated = _view(V174)
    assert _outer_publisher_keys(updated) == _outer_publisher_keys(previous) == PUBLISHER_KEYS
    body = _v173_body(previous)
    prefix, from_clause = body.split("FROM GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES", 1)
    shared, last = prefix.rsplit("\n", 1)
    assert shared in updated
    assert last + "," in updated
    joins = from_clause.split("QUALIFY", 1)[0]
    assert "FROM GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES" + joins in updated
    assert "PARTITION BY c.item_id, c.revision_id, c.source_id, c.transport" not in updated
    assert "IFF(c.transport = 'entrez', NULL, c.revision_id)" in updated
    assert "IFF(c.transport = 'entrez', NULL, c.source_id)" in updated
    assert "IFF(c.transport = 'entrez', c.capture_id, NULL) DESC" in updated
    assert "ORDER BY c.retrieved_at DESC, c.capture_id" not in updated
    assert "c.capture_id\n) = 1" in updated
    assert (
        "IFF(published_at IS NULL\n"
        "           OR TRY_TO_TIMESTAMP_TZ(published_at) > first_loaded_at,\n"
        "           first_loaded_at,\n"
        "           TRY_TO_TIMESTAMP_TZ(published_at))::TIMESTAMP_TZ AS FEED_SORT_AT"
    ) in updated
    assert "MIN(c.retrieved_at) OVER" in updated
    assert "CURRENT_TIMESTAMP" not in updated
    assert updated.index("AS FEED_SORT_AT") > updated.index("reviewed_trust_classification")


def _newer(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """True when left wins the V174 QUALIFY order against right."""
    if left["retrieved_at"] != right["retrieved_at"]:
        return left["retrieved_at"] > right["retrieved_at"]
    left_entrez = left["capture_id"] if left["transport"] == "entrez" else None
    right_entrez = right["capture_id"] if right["transport"] == "entrez" else None
    if left_entrez != right_entrez:
        if left_entrez is None or right_entrez is None:
            return left_entrez is None
        return left_entrez > right_entrez
    return left["capture_id"] < right["capture_id"]


def _partition(row: dict[str, Any]) -> tuple[Any, ...]:
    if row["transport"] == "entrez":
        return (row["item_id"], None, None, row["transport"])
    return (row["item_id"], row["revision_id"], row["source_id"], row["transport"])


def _first_loaded(rows: list[dict[str, Any]], row: dict[str, Any]) -> datetime:
    if row["transport"] == "entrez":
        group = [
            item
            for item in rows
            if item["item_id"] == row["item_id"] and item["transport"] == "entrez"
        ]
    else:
        group = [
            item
            for item in rows
            if item["item_id"] == row["item_id"]
            and item["source_id"] == row["source_id"]
            and item["transport"] != "entrez"
        ]
    return min(item["retrieved_at"] for item in group)


def _feed_sort(published_at: datetime | None, first_loaded: datetime) -> datetime:
    if published_at is None or published_at > first_loaded:
        return first_loaded
    return published_at


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    winners: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = _partition(row)
        current = winners.get(key)
        if current is None or _newer(row, current):
            winners[key] = row
    return list(winners.values())


def test_entrez_collapses_to_one_row_and_the_eid_pair_stays() -> None:
    assert EID_ITEM.startswith("bd4c0099") and EID_ITEM.endswith("4eee")
    early = datetime.fromisoformat("2026-10-20T04:28:00+00:00")
    later = datetime.fromisoformat("2026-10-20T04:37:00+00:00")
    future = datetime.fromisoformat("2027-01-01T00:00:00+00:00")
    published = datetime.fromisoformat("2026-10-01T00:00:00+00:00")
    rows = [
        {
            "item_id": "pmid-overlap",
            "revision_id": "rev-old",
            "source_id": "pubmed-tick-borne",
            "transport": "entrez",
            "capture_id": "a",
            "retrieved_at": early,
            "published_at": future,
        },
        {
            "item_id": "pmid-overlap",
            "revision_id": "rev-new",
            "source_id": "pubmed-lyme-borrelia",
            "transport": "entrez",
            "capture_id": "b",
            "retrieved_at": later,
            "published_at": future,
        },
        {
            "item_id": "pmid-same-time",
            "revision_id": "rev",
            "source_id": "pubmed-tick-borne",
            "transport": "entrez",
            "capture_id": "m",
            "retrieved_at": early,
            "published_at": None,
        },
        {
            "item_id": "pmid-same-time",
            "revision_id": "rev",
            "source_id": "pubmed-lyme-borrelia",
            "transport": "entrez",
            "capture_id": "z",
            "retrieved_at": early,
            "published_at": None,
        },
        {
            "item_id": EID_ITEM,
            "revision_id": "eid-rev",
            "source_id": "cdc-eid-ahead-of-print",
            "transport": "rss",
            "capture_id": "eid-a",
            "retrieved_at": early,
            "published_at": published,
        },
        {
            "item_id": EID_ITEM,
            "revision_id": "eid-rev",
            "source_id": "cdc-eid-expedited",
            "transport": "rss",
            "capture_id": "eid-b",
            "retrieved_at": later,
            "published_at": published,
        },
        {
            "item_id": "rss-repeat",
            "revision_id": "rss-rev",
            "source_id": "cdc-mmwr",
            "transport": "rss",
            "capture_id": "z-late-name",
            "retrieved_at": early,
            "published_at": published,
        },
        {
            "item_id": "rss-repeat",
            "revision_id": "rss-rev",
            "source_id": "cdc-mmwr",
            "transport": "rss",
            "capture_id": "a-early-name",
            "retrieved_at": early,
            "published_at": published,
        },
    ]
    kept = _dedupe(rows)
    overlap = [row for row in kept if row["item_id"] == "pmid-overlap"]
    assert len(overlap) == 1
    assert overlap[0]["capture_id"] == "b"
    assert overlap[0]["published_at"] == future
    same_time = [row for row in kept if row["item_id"] == "pmid-same-time"]
    assert [row["capture_id"] for row in same_time] == ["z"]
    eid = [row for row in kept if row["item_id"] == EID_ITEM]
    assert len(eid) == 2
    assert {row["source_id"] for row in eid} == {"cdc-eid-ahead-of-print", "cdc-eid-expedited"}
    repeated = [row for row in kept if row["item_id"] == "rss-repeat"]
    assert [row["capture_id"] for row in repeated] == ["a-early-name"]
    entrez_items = {row["item_id"] for row in kept if row["transport"] == "entrez"}
    assert len([row for row in kept if row["transport"] == "entrez"]) == len(entrez_items)
    sorts = []
    for row in kept:
        first = _first_loaded(rows, row)
        sort_at = _feed_sort(row["published_at"], first)
        sorts.append(sort_at)
        assert sort_at <= first
        if row["published_at"] is None or row["published_at"] > first:
            assert sort_at == first
        else:
            assert sort_at == row["published_at"]
    newest_load = max(row["retrieved_at"] for row in rows)
    assert all(sort_at <= newest_load for sort_at in sorts)
    assert all(sort_at <= datetime.fromisoformat("2026-10-27T00:00:00+00:00") for sort_at in sorts)


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
        expected_pending=[INTELLIGENCE_FEED_ENTREZ_DEDUPE_MIGRATION],
        protected_intelligence_prerequisite=protected,
    )
    return connection, executed


@pytest.mark.parametrize("database", [DEV_DATABASE, PROD_DATABASE])
def test_v174_requires_recorded_v173_and_the_protected_path(
    monkeypatch: pytest.MonkeyPatch, database: str
) -> None:
    loaded = load_migrations()
    v173 = next(item for item in loaded if item.version == "V173")
    v174 = next(item for item in loaded if item.version == "V174")
    with pytest.raises(PermissionError, match="V174 requires recorded V173"):
        _apply(monkeypatch, database, [v174], [], protected=True)
    with pytest.raises(PermissionError, match="protected intelligence prerequisite"):
        _apply(
            monkeypatch,
            database,
            [v173, v174],
            [("V173", v173.sha256)],
            protected=False,
        )
    connection, executed = _apply(
        monkeypatch,
        database,
        [v173, v174],
        [("V173", v173.sha256)],
        protected=True,
    )
    assert executed == ["V174"]
    statement = connection.execute_string.call_args.args[0]
    assert "FEED_SORT_AT" in statement
    assert "GRANT " not in statement
    assert _DML.search(statement) is None
