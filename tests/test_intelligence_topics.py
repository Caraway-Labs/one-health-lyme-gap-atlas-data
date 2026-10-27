"""Vocabulary v1 topic assignment: pure matches, coverage, and a fail-soft daily hook."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from test_intelligence_feed import definition
from test_intelligence_storage import Ledger, item
from typer.testing import CliRunner

from lyme_gap_atlas_data import cli
from lyme_gap_atlas_data.ingestion import Tier
from lyme_gap_atlas_data.ingestion import intelligence_entrez as entrez
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.ingestion.intelligence_effects import IntelligenceStageEffects
from lyme_gap_atlas_data.ingestion.intelligence_entrez import ABSTRACT_LIMIT
from lyme_gap_atlas_data.ingestion.types import RunState, RunStatus
from lyme_gap_atlas_data.intelligence_items import permitted_text
from lyme_gap_atlas_data.intelligence_topics import (
    _MERGE,
    FALLBACK_TOPIC_ID,
    MAX_ABSTRACT_CHARS,
    MAX_FIELD_CHARS,
    MAX_TOPICS,
    backfill_topics,
    load_vocabulary,
    map_topics,
    merge_topic_rows,
    topic_rows_for_items,
    vocabulary_path,
)
from lyme_gap_atlas_data.migrations import (
    BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS,
    DEV_DATABASE,
    DEV_ONLY_MIGRATION_VERSIONS,
    INTELLIGENCE_ITEM_TOPICS_MIGRATION,
    INTELLIGENCE_SOURCE_ACTIVATION_MIGRATION,
    PROD_DATABASE,
    PROD_ONLY_MIGRATION_VERSIONS,
    PROTECTED_INTELLIGENCE_MIGRATIONS,
    Migration,
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
            "matched_term": None,
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


def test_fallback_null_matched_term_round_trips_through_the_merge_payload() -> None:
    cursor = _TopicCursor(table_exists=True)
    document = _item("Workshop agenda for editors")
    result = runtime.record_topics_after_merge(cursor, [document], enabled=False)
    assert result["status"] == "recorded"
    assert result["rows"] == 1
    assert result["warnings"] == 0
    sql, params = cursor.statements[-1]
    payload = json.loads(params[0])
    assert payload[0]["topic_id"] == FALLBACK_TOPIC_ID
    assert payload[0]["matched_field"] == "fallback"
    assert payload[0]["matched_term"] is None
    assert '"matched_term":null' in params[0]
    assert "IS_NULL_VALUE(value:matched_term)" in sql
    assert "value:matched_term IS NULL" in sql
    assert document["derived_metadata"] == {}


def test_merge_updates_when_matched_term_changes_including_null() -> None:
    assert "target.matched_term <> source.matched_term" not in _MERGE
    assert "target.matched_field <> source.matched_field" not in _MERGE
    assert "target.matched_term IS DISTINCT FROM source.matched_term" in _MERGE
    assert "target.matched_field IS DISTINCT FROM source.matched_field" in _MERGE
    identity = {
        "item_id": "a" * 64,
        "revision_id": "b" * 64,
        "topic_id": FALLBACK_TOPIC_ID,
        "vocabulary_version": "v1",
        "matched_field": "fallback",
    }
    changes = (
        (None, "Babesiosis"),
        ("Babesiosis", None),
        ("Babesiosis", "babesiosis"),
    )
    for before, after in changes:
        assert _is_distinct_from(before, after)
        if before is None or after is None:
            assert not _sql_inequality_matches(before, after)
        cursor = _TopicCursor(table_exists=True)
        merge_topic_rows(cursor, [{**identity, "matched_term": before}])
        merge_topic_rows(cursor, [{**identity, "matched_term": after}])
        first = json.loads(cursor.statements[0][1][0])
        second = json.loads(cursor.statements[1][1][0])
        assert first[0]["matched_term"] == before
        assert second[0]["matched_term"] == after
        assert cursor.statements[0][0] == cursor.statements[1][0] == _MERGE


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


def test_failed_topic_merge_leaves_the_committed_item_write_unchanged() -> None:
    """A topic MERGE failure is counted after the item commit and does not undo it."""
    database = Ledger()
    effects = _effects(database)
    document = item()

    def hook(cursor: Any, items: list[dict[str, Any]]) -> dict[str, Any]:
        original = cursor.execute

        def execute(statement: str, params: tuple[Any, ...] = ()) -> None:
            compact = " ".join(statement.split()).upper()
            if compact.startswith("SELECT COUNT(*)") and "INTELLIGENCE_ITEM_TOPICS" in compact:
                cursor.rows = [(1,)]
                return
            if compact.startswith("MERGE INTO CONFORMED.INTELLIGENCE_ITEM_TOPICS"):
                raise RuntimeError("TOPIC_MERGE_FAILED")
            original(statement, params)

        cursor.execute = execute
        return runtime.record_topics_after_merge(cursor, items)

    effects.store.after_merge = hook
    detail = effects.load(_definition(database), _state(), [document])
    assert detail["wrote"] is True
    assert detail["items_new"] == 1
    assert detail["items_changed"] == 0
    assert detail["items_unchanged"] == 0
    assert detail["topic_warnings"] == 1
    assert effects.store.topic_report["status"] == "skipped"
    assert effects.store.topic_report["reason"] == "topics_merge_failed"
    assert effects.store.topic_report["rows"] == 0
    assert len(database.revisions) == 1
    assert len(database.captures) == 1
    assert database.events.count("commit") == 2


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
    assert first == {"items": 1, "topic_rows": 1, "warnings": 0}
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
    assert payload == {"items": 0, "topic_rows": 0, "vocabulary_version": "v1", "warnings": 0}
    assert observed["committed"] is True
    assert "Babesiosis" not in result.output


def test_topic_migration_is_protected_on_both_environments() -> None:
    versions = [item.version for item in load_migrations()]
    assert versions.count("V170") == 1
    assert "V169" in versions
    activation = next(loaded for loaded in load_migrations() if loaded.version == "V170")
    assert activation.filename == INTELLIGENCE_SOURCE_ACTIVATION_MIGRATION["filename"]
    assert activation.sha256 == INTELLIGENCE_SOURCE_ACTIVATION_MIGRATION["sha256"]
    assert INTELLIGENCE_SOURCE_ACTIVATION_MIGRATION in PROTECTED_INTELLIGENCE_MIGRATIONS
    assert "V170" in BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS
    migration = next(loaded for loaded in load_migrations() if loaded.version == "V171")
    pinned = INTELLIGENCE_ITEM_TOPICS_MIGRATION
    assert migration.filename == pinned["filename"] == "V171__intelligence_item_topics.sql"
    assert migration.sha256 == pinned["sha256"]
    assert versions.count("V171") == 1
    assert pinned["version"] in BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS
    assert pinned in PROTECTED_INTELLIGENCE_MIGRATIONS
    assert "V171" not in DEV_ONLY_MIGRATION_VERSIONS
    assert "V171" not in PROD_ONLY_MIGRATION_VERSIONS
    assert frozenset({"V170", "V171", "V173", "V174"}) == BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS
    assert "CREATE SCHEMA" not in migration.source.upper()
    assert "INTELLIGENCE_FEED_V2" not in migration.source
    assert "FEED_SORT_AT" not in migration.source
    for database, environment in ((DEV_DATABASE, "DEV"), (PROD_DATABASE, "PROD")):
        rendered = render_migration(migration, database)
        assert f"USE DATABASE {database};" in rendered
        assert "CONFORMED.INTELLIGENCE_ITEM_TOPICS" in rendered
        assert "PRESENTATION.INTELLIGENCE_ITEM_TOPICS_V1" in rendered
        assert "CONFORMED.INTELLIGENCE_TOPICS" in rendered
        assert "PRESENTATION.INTELLIGENCE_TOPICS_V1" in rendered
        assert "vocabulary_version = 'v1'" in rendered
        assert "matched_term VARCHAR(4096)," in rendered
        assert (
            "GRANT SELECT, INSERT, UPDATE ON TABLE CONFORMED.INTELLIGENCE_ITEM_TOPICS" in rendered
        )
        assert "DELETE" not in rendered.upper()
        assert f"OH_LYME_{environment}_RUNTIME" in rendered
        assert f"OH_LYME_{environment}_READ" in rendered
        assert "GRANT SELECT, INSERT, UPDATE ON TABLE CONFORMED.INTELLIGENCE_TOPICS" not in rendered
        assert "ON TABLE CONFORMED.INTELLIGENCE_TOPICS" not in rendered
        assert "{{" not in rendered
    assert pinned in migration_plan(DEV_DATABASE)
    assert pinned in migration_plan(PROD_DATABASE)


def _install_topic_apply(
    monkeypatch: pytest.MonkeyPatch,
    plan: list[Migration],
    ledger: list[tuple[str, str]],
) -> Mock:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.migrations.load_migrations",
        lambda: plan,
    )
    cursor = Mock()
    cursor.fetchall.side_effect = [ledger, []]
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(
        "lyme_gap_atlas_data.migrations.connect",
        lambda *_, **__: nullcontext(connection),
    )
    return connection


@pytest.mark.parametrize("database", [DEV_DATABASE, PROD_DATABASE])
def test_routine_migration_path_refuses_v171(
    monkeypatch: pytest.MonkeyPatch, database: str
) -> None:
    loaded = load_migrations()
    v170 = next(item for item in loaded if item.version == "V170")
    migration = next(item for item in loaded if item.version == "V171")
    pinned = INTELLIGENCE_ITEM_TOPICS_MIGRATION
    for expected in (None, [pinned]):
        connection = _install_topic_apply(monkeypatch, [migration], [])
        with pytest.raises(PermissionError, match="V171 requires the protected intelligence"):
            apply_migrations(Mock(), database, expected_pending=expected)
        connection.execute_string.assert_not_called()
    connection = _install_topic_apply(monkeypatch, [migration], [])
    with pytest.raises(PermissionError, match="V171 requires recorded V170"):
        apply_migrations(
            Mock(),
            database,
            expected_pending=[pinned],
            protected_intelligence_prerequisite=True,
        )
    connection.execute_string.assert_not_called()
    connection = _install_topic_apply(monkeypatch, [v170, migration], [("V170", v170.sha256)])
    assert apply_migrations(
        Mock(),
        database,
        expected_pending=[pinned],
        protected_intelligence_prerequisite=True,
    ) == ["V171"]
    connection.execute_string.assert_called_once()
    assert "INTELLIGENCE_ITEM_TOPICS" in connection.execute_string.call_args.args[0]
    assert "INTELLIGENCE_FEED_V2" not in connection.execute_string.call_args.args[0]
    v173 = next(item for item in loaded if item.version == "V173")
    v174 = next(item for item in loaded if item.version == "V174")
    connection = _install_topic_apply(
        monkeypatch,
        [migration],
        [
            ("V170", v170.sha256),
            ("V173", v173.sha256),
            ("V174", v174.sha256),
        ],
    )
    assert apply_migrations(
        Mock(),
        database,
        expected_pending=[pinned],
        protected_intelligence_prerequisite=True,
    ) == ["V171"]


def test_v171_vocabulary_rows_equal_the_json_exactly() -> None:
    migration = next(loaded for loaded in load_migrations() if loaded.version == "V171")
    topics = VOCAB["topics"]
    assert _vocabulary_rows(migration.source) == [
        (topic["id"], "v1", topic["label"], topic["definition"], index)
        for index, topic in enumerate(topics)
    ]
    assert len(topics) == 19


def test_daily_hook_records_topics_for_a_recorded_pubmed_item() -> None:
    """The recorded efetch fixture stores MeSH as name/ui objects, not strings.

    Overlap PMIDs become one item. The source is the first entry in the fixed
    order, tick-borne before Lyme/Borrelia.
    """
    items = _recorded_pubmed_items()
    assert set(items) == {"12345678", "23456789"}
    item = items["12345678"]
    assert item["source_id"] == "pubmed-tick-borne"
    assert item["publisher_metadata"]["matched_queries"] == [
        "pubmed-tick-borne",
        "pubmed-lyme-borrelia",
    ]
    mesh = item["publisher_metadata"]["mesh"]
    abstract = item["publisher_metadata"]["abstract"]
    assert mesh == [{"name": "Lyme Disease", "ui": "D008193"}]
    assert abstract["state"] == "present"
    assert "Borrelia burgdorferi" in abstract["text"]
    assert item["publisher_metadata"]["categories"] == ["Borrelia", "tick-borne"]
    cursor = _TopicCursor(table_exists=True)
    result = runtime.record_topics_after_merge(cursor, [item], enabled=False)
    assert result["status"] == "recorded"
    assert result["warnings"] == 0
    payload = json.loads(cursor.statements[-1][1][0])
    lyme = next(row for row in payload if row["topic_id"] == "lyme-disease")
    assert lyme["matched_field"] == "mesh"
    assert lyme["matched_term"] == "D008193"
    named = map_topics(
        None,
        None,
        [],
        [{"name": mesh[0]["name"], "ui": "D000000"}],
        [],
        VOCAB,
    )
    assert named[0]["topic_id"] == "lyme-disease"
    assert named[0]["matched_field"] == "mesh"
    assert named[0]["matched_term"] == "Lyme Disease"
    with pytest.raises(ValueError, match="TOPIC_FIELD_TYPE"):
        map_topics(None, None, [], [{"name": "Lyme Disease"}], [], VOCAB)
    with pytest.raises(ValueError, match="TOPIC_FIELD_TYPE"):
        map_topics(None, None, [], [12], [], VOCAB)


def test_backfill_counts_a_bad_pubmed_item_and_continues() -> None:
    good = _recorded_pubmed_items()["12345678"]
    bad = {
        "title": "Babesiosis cases rise in New York",
        "publisher_metadata": {"mesh": [12], "abstract": {"text": None, "state": "not_provided"}},
    }
    cursor = _PageCursor(
        [
            [
                ("bad-item", "bad-rev", json.dumps(bad)),
                (good["item_id"], good["revision_id"], json.dumps(good)),
            ],
            [],
        ]
    )
    summary = backfill_topics(cursor, vocabulary_version="v1")
    assert summary["items"] == 2
    assert summary["warnings"] == 1
    assert summary["topic_rows"] == 1
    payload = json.loads(next(params[0] for sql, params in cursor.statements if "MERGE" in sql))
    assert any(
        row["topic_id"] == "lyme-disease" and row["matched_term"] == "D008193" for row in payload
    )
    assert all(row["item_id"] != "bad-item" for row in payload)


def test_recorded_pubmed_abstract_accepts_the_6000_character_cap() -> None:
    item = _recorded_pubmed_items()["23456789"]
    abstract = item["publisher_metadata"]["abstract"]
    assert abstract["state"] == "present"
    assert item["publisher_metadata"]["mesh"] == []
    term = "Borrelia burgdorferi"
    abstract["text"] = term + ("." * (MAX_ABSTRACT_CHARS - len(term)))
    assert len(abstract["text"]) == MAX_ABSTRACT_CHARS == ABSTRACT_LIMIT
    rows = topic_rows_for_items([item], VOCAB)
    lyme = next(row for row in rows if row["topic_id"] == "lyme-disease")
    assert lyme["matched_field"] == "abstract"
    assert lyme["matched_term"] == term
    over = deepcopy(item)
    over["publisher_metadata"]["abstract"]["text"] += "."
    with pytest.raises(ValueError, match="TOPIC_FIELD_LIMIT:abstract"):
        topic_rows_for_items([over], VOCAB)
    with pytest.raises(ValueError, match="TOPIC_FIELD_LIMIT:title"):
        map_topics("a" * (MAX_FIELD_CHARS + 1), None, [], [], [], VOCAB)
    hidden = deepcopy(item)
    hidden["title"] = "Workshop agenda for editors"
    hidden["publisher_metadata"]["categories"] = []
    hidden["publisher_metadata"]["abstract"] = {
        "text": term,
        "state": "suppressed",
    }
    assert [row["topic_id"] for row in topic_rows_for_items([hidden], VOCAB)] == [FALLBACK_TOPIC_ID]


def _recorded_pubmed_items() -> dict[str, dict[str, Any]]:
    """Items produced by the Entrez parser from the recorded overlap fixtures."""
    fixture_dir = ROOT / "tests" / "fixtures" / "pubmed"
    searches = json.loads((fixture_dir / "esearch_overlap.json").read_text(encoding="utf-8"))
    records = entrez._parse_efetch((fixture_dir / "efetch_overlap.xml").read_bytes())
    sources = entrez._load_sources()
    policies = entrez._load_policies(sources)
    items: dict[str, dict[str, Any]] = {}
    for record in records:
        matched = tuple(
            source_id
            for source_id in entrez.SOURCE_ORDER
            if record.pmid in searches[source_id]["idlist"]
        )
        items[record.pmid] = entrez._build_item(
            record,
            matched=matched,
            sources=sources,
            policies=policies,
            fetched_at="2026-10-25T12:00:00Z",
            run_id="dev-pubmed-fixture",
            artifact_sha="a" * 64,
            suppress_pmids=frozenset(),
            suppress_publishers=frozenset(),
        )
    return items


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


def _vocabulary_rows(sql: str) -> list[tuple[str, str, str, str, int]]:
    marker = "MERGE INTO CONFORMED.INTELLIGENCE_TOPICS"
    start = sql.index(marker)
    assert "INSERT INTO CONFORMED.INTELLIGENCE_TOPICS" not in sql
    body = sql[sql.index("VALUES", start) + len("VALUES") :]
    body = body[: body.index(") AS source")]
    rows: list[tuple[str, str, str, str, int]] = []
    index = 0
    while index < len(body):
        if body[index] == ";":
            break
        if body[index] != "(":
            index += 1
            continue
        index += 1
        fields: list[str | int] = []
        while True:
            while body[index] in " \n\t,":
                index += 1
            if body[index] == ")":
                index += 1
                break
            if body[index] == "'":
                index += 1
                chars: list[str] = []
                while True:
                    if body[index : index + 2] == "''":
                        chars.append("'")
                        index += 2
                        continue
                    if body[index] == "'":
                        index += 1
                        break
                    chars.append(body[index])
                    index += 1
                fields.append("".join(chars))
                continue
            end = index
            while body[end].isdigit():
                end += 1
            fields.append(int(body[index:end]))
            index = end
        topic_id, version, label, definition, order = fields
        assert isinstance(topic_id, str)
        assert isinstance(version, str)
        assert isinstance(label, str)
        assert isinstance(definition, str)
        assert isinstance(order, int)
        rows.append((topic_id, version, label, definition, order))
    return rows


def _is_distinct_from(left: str | None, right: str | None) -> bool:
    return left != right


def _sql_inequality_matches(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    return left != right


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
