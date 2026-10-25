"""Vocabulary v1 topic assignment: pure matches, coverage, and an inert daily hook."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lyme_gap_atlas_data import cli
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.intelligence_items import permitted_text
from lyme_gap_atlas_data.intelligence_topics import (
    _MERGE,
    FALLBACK_TOPIC_ID,
    MAX_TOPICS,
    backfill_topics,
    load_vocabulary,
    map_topics,
    vocabulary_path,
)
from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    DEV_ONLY_MIGRATION_VERSIONS,
    PROD_DATABASE,
    PROD_ONLY_MIGRATION_VERSIONS,
    PROTECTED_INTELLIGENCE_MIGRATIONS,
    load_migrations,
    migration_plan,
    render_migration,
)

ROOT = Path(__file__).parents[1]
FEEDS = ROOT / "tests" / "fixtures" / "intelligence" / "publisher-descriptions" / "2026-10-25"
PUBMED = ROOT / "tests" / "fixtures" / "intelligence" / "topics" / "pubmed-coverage.json"
VOCAB = load_vocabulary("v1")


def test_vocabulary_v1_is_the_fixed_topic_set() -> None:
    topics = VOCAB["topics"]
    assert VOCAB["vocabulary_version"] == "v1"
    assert [topic["id"] for topic in topics][-1] == FALLBACK_TOPIC_ID
    assert len(topics) == 19
    assert vocabulary_path("v1").name == "topic-vocabulary-v1.json"
    with pytest.raises(ValueError, match="TOPIC_VOCABULARY_VERSION"):
        load_vocabulary("v2")
    with pytest.raises(ValueError, match="TOPIC_VOCABULARY_VERSION"):
        vocabulary_path("../v1")


def test_map_topics_is_deterministic() -> None:
    arguments = (
        "Babesiosis and Lyme disease in Ixodes ticks",
        "Anaplasma phagocytophilum was also detected by PCR.",
        ["Tick-borne diseases"],
        ["D008193", "Lyme Disease"],
        ["Borrelia burgdorferi"],
        VOCAB,
    )
    first = map_topics(*arguments)
    second = map_topics(*arguments)
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_title_match_is_explainable() -> None:
    matches = map_topics("Babesiosis cases rise in New York", None, [], [], [], VOCAB)
    assert {
        "topic_id": "babesiosis",
        "matched_field": "title",
        "matched_term": "Babesiosis",
    } in matches


def test_tick_synonym_does_not_match_inside_needlesticks() -> None:
    matches = map_topics("Needlesticks in hospital workers", None, [], [], [], VOCAB)
    assert [row["topic_id"] for row in matches] == [FALLBACK_TOPIC_ID]


def test_no_match_returns_only_the_fallback_topic() -> None:
    matches = map_topics("Workshop agenda for editors", "Bring a pencil.", [], [], [], VOCAB)
    assert matches == [
        {
            "topic_id": FALLBACK_TOPIC_ID,
            "matched_field": "fallback",
            "matched_term": FALLBACK_TOPIC_ID,
        }
    ]


def test_matches_follow_vocabulary_order_and_stop_at_ten() -> None:
    title = " ".join(topic["synonyms"][0] for topic in VOCAB["topics"] if topic["synonyms"])
    matches = map_topics(title, None, [], [], [], VOCAB)
    assert len(matches) == MAX_TOPICS
    assert [row["topic_id"] for row in matches] == [
        topic["id"] for topic in VOCAB["topics"] if topic["id"] != FALLBACK_TOPIC_ID
    ][:MAX_TOPICS]
    assert FALLBACK_TOPIC_ID not in {row["topic_id"] for row in matches}


def test_mesh_ui_and_publisher_category_are_exact() -> None:
    mesh = map_topics(None, None, [], ["D008193"], [], VOCAB)
    assert mesh[0]["topic_id"] == "lyme-disease"
    assert mesh[0]["matched_field"] == "mesh"
    assert mesh[0]["matched_term"] == "D008193"
    categories = map_topics(None, None, ["Lyme Disease"], [], [], VOCAB)
    assert categories[0] == {
        "topic_id": "lyme-disease",
        "matched_field": "categories",
        "matched_term": "Lyme Disease",
    }


def test_field_bounds_reject_oversized_plain_text() -> None:
    with pytest.raises(ValueError, match="TOPIC_FIELD_LIMIT:title"):
        map_topics("a" * 4097, None, [], [], [], VOCAB)
    with pytest.raises(ValueError, match="TOPIC_FIELD_TYPE"):
        map_topics("Lyme", None, "Lyme Disease", [], [], VOCAB)  # type: ignore[arg-type]


def test_coverage_gate_on_recorded_feed_and_pubmed_fixtures() -> None:
    mmwr = _feed_items(FEEDS / "cdc-mmwr.xml")
    newsroom = _feed_items(FEEDS / "cdc-newsroom.xml")
    pubmed = json.loads(PUBMED.read_text(encoding="utf-8"))["items"]
    assert len(mmwr) >= 20 and len(newsroom) >= 20 and len(pubmed) >= 20
    mmwr_fraction = _tagged_fraction(mmwr)
    newsroom_fraction = _tagged_fraction(newsroom)
    pubmed_fraction = _tagged_fraction(pubmed)
    assert mmwr_fraction >= 0.40, mmwr_fraction
    assert newsroom_fraction >= 0.40, newsroom_fraction
    assert pubmed_fraction >= 0.85, pubmed_fraction


def test_missing_topic_table_keeps_the_daily_hook_inert() -> None:
    cursor = _TopicCursor(table_exists=False)
    result = runtime.record_topics_after_merge(
        cursor,
        [_item("Needlesticks in hospital workers")],
        enabled=False,
    )
    assert result == {"status": "inert", "reason": "topics_table_absent", "rows": 0}
    assert len(cursor.statements) == 1
    assert "INTELLIGENCE_ITEM_TOPICS" in cursor.statements[0][0]
    assert "MERGE" not in cursor.statements[0][0].upper()


def test_present_topic_table_merges_explainable_rows() -> None:
    cursor = _TopicCursor(table_exists=True)
    item = _item("Babesiosis cases rise in New York")
    result = runtime.record_topics_after_merge(cursor, [item], enabled=False)
    assert result["status"] == "recorded"
    assert result["rows"] == 1
    sql, params = cursor.statements[-1]
    assert "MERGE INTO CONFORMED.INTELLIGENCE_ITEM_TOPICS" in sql
    assert "target.item_id = source.item_id" in sql
    assert "target.revision_id = source.revision_id" in sql
    assert "target.topic_id = source.topic_id" in sql
    assert "target.vocabulary_version = source.vocabulary_version" in sql
    payload = json.loads(params[0])
    assert payload[0]["topic_id"] == "babesiosis"
    assert payload[0]["matched_field"] == "title"
    assert payload[0]["matched_term"] == "Babesiosis"
    assert payload[0]["vocabulary_version"] == "v1"
    assert item["derived_metadata"] == {}


def test_explicit_flag_attempts_recording_when_the_table_probe_is_empty() -> None:
    cursor = _TopicCursor(table_exists=False)
    result = runtime.record_topics_after_merge(
        cursor,
        [_item("Babesiosis cases rise in New York")],
        enabled=True,
    )
    assert result["status"] == "recorded"
    assert any(statement[0] == _MERGE for statement in cursor.statements)


def test_backfill_pages_revisions_and_merges_on_the_natural_key() -> None:
    document = {
        "title": "Babesiosis cases rise in New York",
        "publisher_metadata": {"categories": [], "description": {"text": None}},
        "derived_metadata": {},
    }
    cursor = _PageCursor(
        [
            [("item-1", "rev-1", json.dumps(document))],
            [],
        ]
    )
    first = backfill_topics(cursor, vocabulary_version="v1")
    assert first == {"items": 1, "topic_rows": 1}
    merge = next(sql for sql, _params in cursor.statements if "MERGE" in sql.upper())
    assert "item_id" in merge and "revision_id" in merge
    assert "topic_id" in merge and "vocabulary_version" in merge
    second_cursor = _PageCursor([[("item-1", "rev-1", json.dumps(document))], []])
    second = backfill_topics(second_cursor, vocabulary_version="v1")
    assert second == first
    assert document["derived_metadata"] == {}


def test_topics_backfill_command_prints_counts_without_item_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class _Connection:
        def __enter__(self) -> _Connection:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def cursor(self) -> _PageCursor:
            cursor = _PageCursor([[], []])
            observed["cursor"] = cursor
            return cursor

        def commit(self) -> None:
            observed["committed"] = True

    monkeypatch.setattr(cli, "connect", lambda settings: _Connection())
    result = CliRunner().invoke(cli.app, ["topics", "backfill", "--vocabulary-version", "v1"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"items": 0, "topic_rows": 0, "vocabulary_version": "v1"}
    assert observed["committed"] is True
    assert "Babesiosis" not in result.output


def test_topic_migration_is_environment_neutral_and_leaves_v169_free() -> None:
    versions = [item.version for item in load_migrations()]
    assert "V169" not in versions
    migration = next(item for item in load_migrations() if item.version == "V170")
    assert migration.filename == "V170__intelligence_item_topics.sql"
    assert versions.count("V170") == 1
    assert "V170" not in DEV_ONLY_MIGRATION_VERSIONS
    assert "V170" not in PROD_ONLY_MIGRATION_VERSIONS
    assert "V170" not in {item["version"] for item in PROTECTED_INTELLIGENCE_MIGRATIONS}
    assert "CREATE SCHEMA" not in migration.source.upper()
    for database, environment in ((DEV_DATABASE, "DEV"), (PROD_DATABASE, "PROD")):
        rendered = render_migration(migration, database)
        assert f"USE DATABASE {database};" in rendered
        assert "CONFORMED.INTELLIGENCE_ITEM_TOPICS" in rendered
        assert "PRESENTATION.INTELLIGENCE_ITEM_TOPICS_V1" in rendered
        assert "vocabulary_version = 'v1'" in rendered
        assert f"OH_LYME_{environment}_RUNTIME" in rendered
        assert f"OH_LYME_{environment}_READ" in rendered
        assert "{{" not in rendered
    assert "V170" in {item["version"] for item in migration_plan(DEV_DATABASE)}
    assert "V170" in {item["version"] for item in migration_plan(PROD_DATABASE)}


def _feed_items(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node in ET.parse(path).getroot().iter("item"):
        categories = []
        for category in node.findall("category"):
            text = permitted_text(category.text or "", 4096)
            if text:
                categories.append(text)
        items.append(
            {
                "title": permitted_text(node.findtext("title") or "", 4096),
                "description": permitted_text(node.findtext("description") or "", 4096),
                "categories": categories,
                "mesh": [],
                "keywords": [],
            }
        )
    return items


def _tagged_fraction(items: list[dict[str, Any]]) -> float:
    tagged = 0
    for item in items:
        matches = map_topics(
            item.get("title"),
            item.get("description"),
            item.get("categories") or [],
            item.get("mesh") or [],
            item.get("keywords") or [],
            VOCAB,
        )
        if any(row["topic_id"] != FALLBACK_TOPIC_ID for row in matches):
            tagged += 1
    return tagged / len(items)


def _item(title: str) -> dict[str, Any]:
    return {
        "item_id": "a" * 64,
        "revision_id": "b" * 64,
        "title": title,
        "publisher_metadata": {"categories": [], "description": {"text": None}},
        "derived_metadata": {},
    }


class _TopicCursor:
    def __init__(self, *, table_exists: bool) -> None:
        self.table_exists = table_exists
        self.statements: list[tuple[str, tuple[Any, ...]]] = []
        self.rowcount = 1

    def execute(self, statement: str, params: tuple[Any, ...] = ()) -> None:
        self.statements.append((statement, params))

    def fetchone(self) -> tuple[int]:
        return (1 if self.table_exists else 0,)


class _PageCursor:
    def __init__(self, pages: list[list[tuple[Any, ...]]]) -> None:
        self.pages = pages
        self.statements: list[tuple[str, tuple[Any, ...]]] = []
        self.rowcount = 1
        self._rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> _PageCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[Any, ...] = ()) -> None:
        self.statements.append((statement, params))
        if "INTELLIGENCE_ITEM_REVISIONS" in statement:
            self._rows = self.pages.pop(0)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows
