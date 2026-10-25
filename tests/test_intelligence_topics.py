"""Vocabulary v1 topic assignment: pure matches, coverage, and a fail-soft daily hook."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from test_intelligence_feed import definition
from test_intelligence_storage import Ledger, item
from typer.testing import CliRunner

from lyme_gap_atlas_data import cli
from lyme_gap_atlas_data.ingestion import Tier
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.ingestion.intelligence_effects import IntelligenceStageEffects
from lyme_gap_atlas_data.ingestion.types import RunState, RunStatus
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
    BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS,
    DEV_DATABASE,
    DEV_ONLY_MIGRATION_VERSIONS,
    INTELLIGENCE_ITEM_TOPICS_MIGRATION,
    PROD_DATABASE,
    PROD_ONLY_MIGRATION_VERSIONS,
    PROTECTED_INTELLIGENCE_MIGRATIONS,
    apply_migrations,
    load_migrations,
    migration_plan,
    render_migration,
)

ROOT = Path(__file__).parents[1]
FEEDS = ROOT / "tests" / "fixtures" / "intelligence" / "publisher-descriptions" / "2026-10-25"
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


def test_field_bounds_reject_oversized_or_mistyped_plain_text() -> None:
    with pytest.raises(ValueError, match="TOPIC_FIELD_LIMIT:title"):
        map_topics("a" * 4097, None, [], [], [], VOCAB)
    with pytest.raises(ValueError, match="TOPIC_FIELD_TYPE"):
        map_topics("Lyme", None, "Lyme Disease", [], [], VOCAB)  # type: ignore[arg-type]


def test_coverage_gate_on_recorded_mmwr_and_newsroom_fixtures() -> None:
    """Recorded public MMWR and Newsroom items already in the repository.

    The capture manifest is dated 2026-10-25. The PubMed coverage gate is
    provisional until #810/#820 bring recorded captures. This test does not
    treat a hand-written PubMed fixture as meeting that gate.
    """
    manifest = json.loads((FEEDS / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["captured_on"] == "2026-10-25"
    recorded_ids = {row["source_id"] for row in manifest["sources"]}
    assert {"cdc-mmwr", "cdc-newsroom"} <= recorded_ids
    mmwr = _feed_items(FEEDS / "cdc-mmwr.xml")
    newsroom = _feed_items(FEEDS / "cdc-newsroom.xml")
    assert len(mmwr) >= 20 and len(newsroom) >= 20
    mmwr_fraction = _tagged_fraction(mmwr)
    newsroom_fraction = _tagged_fraction(newsroom)
    assert mmwr_fraction >= 0.40, mmwr_fraction
    assert newsroom_fraction >= 0.40, newsroom_fraction
    assert not (ROOT / "tests/fixtures/intelligence/topics/pubmed-coverage.json").exists()


def test_pubmed_coverage_gate_is_provisional_until_recorded_captures() -> None:
    """The PubMed coverage gate is provisional until #810/#820 bring recorded captures.

    No recorded 2026-10-24 PubMed item capture is in this repository. A
    hand-written PubMed fixture is not used, and this test does not claim the
    85 percent PubMed gate is met.
    """
    assert not (ROOT / "tests/fixtures/intelligence/topics/pubmed-coverage.json").exists()
    text = test_pubmed_coverage_gate_is_provisional_until_recorded_captures.__doc__ or ""
    assert "provisional until #810/#820" in text
    assert "85 percent" in text


def test_missing_topic_table_keeps_the_daily_hook_inert() -> None:
    cursor = _TopicCursor(table_exists=False)
    result = runtime.record_topics_after_merge(
        cursor,
        [_item("Needlesticks in hospital workers")],
        enabled=False,
    )
    assert result == {"status": "inert", "reason": "topics_table_absent", "rows": 0, "warnings": 0}
    assert len(cursor.statements) == 1
    assert "INTELLIGENCE_ITEM_TOPICS" in cursor.statements[0][0]
    assert "MERGE" not in cursor.statements[0][0].upper()


def test_present_topic_table_merges_explainable_rows() -> None:
    cursor = _TopicCursor(table_exists=True)
    item_document = _item("Babesiosis cases rise in New York")
    result = runtime.record_topics_after_merge(cursor, [item_document], enabled=False)
    assert result["status"] == "recorded"
    assert result["rows"] == 1
    assert result["warnings"] == 0
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
    assert item_document["derived_metadata"] == {}


def test_oversized_field_yields_no_topics_and_a_counted_warning() -> None:
    cursor = _TopicCursor(table_exists=True)
    oversized = _item("a" * 4097)
    kept = _item("Babesiosis cases rise in New York")
    result = runtime.record_topics_after_merge(cursor, [oversized, kept], enabled=False)
    assert result["warnings"] == 1
    assert result["rows"] == 1
    payload = json.loads(cursor.statements[-1][1][0])
    assert [row["item_id"] for row in payload] == [kept["item_id"]]
    assert payload[0]["topic_id"] == "babesiosis"
    assert oversized["derived_metadata"] == {}

    database = Ledger()
    effects = _effects(database)

    def hook(cursor: Any, items: list[dict[str, Any]]) -> dict[str, Any]:
        del cursor, items
        return runtime.record_topics_after_merge(
            _TopicCursor(table_exists=True),
            [oversized],
            enabled=False,
        )

    effects.store.after_merge = hook
    detail = effects.load(_definition(database), _state(), [item()])
    assert detail["topic_warnings"] == 1
    assert detail["items_new"] == 1
    assert detail["wrote"] is True
    assert detail["mode"] == "atomic_intelligence"
    assert len(database.revisions) == 1


def test_badly_typed_field_and_bad_vocabulary_count_warnings_without_topics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _TopicCursor(table_exists=True)
    typed = _item("Babesiosis cases rise in New York")
    typed["title"] = 12
    typed_result = runtime.record_topics_after_merge(cursor, [typed], enabled=False)
    assert typed_result["rows"] == 0
    assert typed_result["warnings"] == 1
    assert not any("MERGE" in sql.upper() for sql, _params in cursor.statements)

    def broken(_version: str = "v1") -> dict[str, Any]:
        raise ValueError("TOPIC_VOCABULARY_INVALID")

    monkeypatch.setattr(runtime, "load_vocabulary", broken)
    vocabulary_cursor = _TopicCursor(table_exists=True)
    vocabulary_result = runtime.record_topics_after_merge(
        vocabulary_cursor,
        [_item("Babesiosis cases rise in New York")],
        enabled=False,
    )
    assert vocabulary_result == {
        "status": "skipped",
        "reason": "topics_vocabulary_invalid",
        "rows": 0,
        "warnings": 1,
    }
    assert not any("MERGE" in sql.upper() for sql, _params in vocabulary_cursor.statements)


def test_raising_topic_hook_leaves_the_source_write_successful() -> None:
    database = Ledger()
    effects = _effects(database)
    document = item()

    def boom(cursor: Any, items: list[dict[str, Any]]) -> None:
        del cursor, items
        raise RuntimeError("TOPIC_FIELD_LIMIT:title")

    effects.store.after_merge = boom
    detail = effects.load(_definition(database), _state(), [document])
    assert detail["wrote"] is True
    assert detail["items_new"] == 1
    assert detail["items_changed"] == 0
    assert detail["items_unchanged"] == 0
    assert detail["revisions_inserted"] == 1
    assert detail["captures_inserted"] == 1
    assert detail["topic_warnings"] == 1
    assert effects.store.topic_report["status"] == "skipped"
    assert effects.store.topic_report["rows"] == 0
    assert len(database.revisions) == 1
    assert len(database.captures) == 1
    assert "commit" in database.events


def test_explicit_flag_attempts_recording_when_the_table_probe_is_empty() -> None:
    cursor = _TopicCursor(table_exists=False)
    result = runtime.record_topics_after_merge(
        cursor,
        [_item("Babesiosis cases rise in New York")],
        enabled=True,
    )
    assert result["status"] == "recorded"
    assert result["warnings"] == 0
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


def test_topic_migration_is_protected_on_both_environments() -> None:
    versions = [item.version for item in load_migrations()]
    assert "V170" not in versions
    assert "V169" in versions
    migration = next(loaded for loaded in load_migrations() if loaded.version == "V171")
    pinned = INTELLIGENCE_ITEM_TOPICS_MIGRATION
    assert migration.filename == pinned["filename"] == "V171__intelligence_item_topics.sql"
    assert migration.sha256 == pinned["sha256"]
    assert versions.count("V171") == 1
    assert pinned["version"] in BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS
    assert pinned in PROTECTED_INTELLIGENCE_MIGRATIONS
    assert "V171" not in DEV_ONLY_MIGRATION_VERSIONS
    assert "V171" not in PROD_ONLY_MIGRATION_VERSIONS
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
    assert pinned in migration_plan(DEV_DATABASE)
    assert pinned in migration_plan(PROD_DATABASE)


@pytest.mark.parametrize("database", [DEV_DATABASE, PROD_DATABASE])
def test_routine_migration_path_refuses_v171(
    monkeypatch: pytest.MonkeyPatch, database: str
) -> None:
    migration = next(loaded for loaded in load_migrations() if loaded.version == "V171")
    monkeypatch.setattr(
        "lyme_gap_atlas_data.migrations.load_migrations",
        lambda: [migration],
    )
    cursor = Mock()
    cursor.fetchall.return_value = []
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(
        "lyme_gap_atlas_data.migrations.connect",
        lambda *_, **__: nullcontext(connection),
    )
    pinned = INTELLIGENCE_ITEM_TOPICS_MIGRATION
    for expected in (None, [pinned]):
        with pytest.raises(PermissionError, match="V171 requires the protected intelligence"):
            apply_migrations(Mock(), database, expected_pending=expected)
    connection.execute_string.assert_not_called()
    assert apply_migrations(
        Mock(),
        database,
        expected_pending=[pinned],
        protected_intelligence_prerequisite=True,
    ) == ["V171"]
    connection.execute_string.assert_called_once()
    assert "INTELLIGENCE_ITEM_TOPICS" in connection.execute_string.call_args.args[0]


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
    for feed_item in items:
        matches = map_topics(
            feed_item.get("title"),
            feed_item.get("description"),
            feed_item.get("categories") or [],
            feed_item.get("mesh") or [],
            feed_item.get("keywords") or [],
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


def _effects(database: Ledger) -> IntelligenceStageEffects:
    return IntelligenceStageEffects(
        connection_factory=database.connect,
        retention_allowed=lambda ref: ref == "synthetic-test-policy",
        artifact_policy_allowed=lambda ref, policy: True,
    )


def _definition(database: Ledger) -> Any:
    return definition(database.sources[0])


def _state() -> RunState:
    return RunState(
        ingestion_run_id="fixture-run",
        resource_key="synthetic-publication",
        source_definition_version=1,
        tier=Tier.A,
        status=RunStatus.RUNNING,
    )


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
