"""FEED_V2 abstract projection and the suppression table. Offline only."""

from __future__ import annotations

import hashlib
import json
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
    INTELLIGENCE_ABSTRACT_SUPPRESSION_MIGRATION,
    PROD_DATABASE,
    PROD_ONLY_MIGRATION_VERSIONS,
    PROTECTED_INTELLIGENCE_MIGRATIONS,
    is_intelligence_prerequisite_batch,
    load_migrations,
    migration_plan,
)

ROOT = Path(__file__).parents[1]
V175 = ROOT / "migrations" / "V175__intelligence_abstract_suppressions_feed_v2.sql"
LIVE_SOURCES = (
    "cdc-eid-ahead-of-print",
    "cdc-eid-expedited",
    "cdc-mmwr",
    "cdc-outbreaks",
    "nih-news-releases",
)
SUPPRESSED_ABSTRACT = {"text": None, "state": "suppressed", "copyright_line": None}
COPYRIGHT = "Copyright National Library of Medicine."


def _is_suppressed(publisher: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    source_item_id = publisher.get("source_item_id")
    publisher_name = publisher.get("publisher")
    pmid_hits = {
        row["pmid"] for row in rows if row.get("scope") == "PMID" and row.get("pmid") is not None
    }
    publisher_hits = {
        row["publisher"]
        for row in rows
        if row.get("scope") == "PUBLISHER" and row.get("publisher") is not None
    }
    return source_item_id in pmid_hits or publisher_name in publisher_hits


def _project(document: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    publisher = document["publisher_metadata"]
    states = document["field_states"]
    suppressed = _is_suppressed(publisher, rows)
    abstract = SUPPRESSED_ABSTRACT if suppressed else publisher.get("abstract")
    return {
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
        "description": publisher.get("description"),
        "abstract": abstract,
        "mesh": publisher.get("mesh"),
        "publication_types": publisher.get("publication_types"),
        "matched_queries": publisher.get("matched_queries"),
        "abstract_suppressed": suppressed,
    }


def _version(source_id: str, registry_version: int = 1) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "registry_version": registry_version,
        "registry_sha256": f"{registry_version:064x}"[-64:],
        "document": {
            "state": "active",
            "approval": {"status": "approved"},
            "trust_review": {"status": "approved"},
        },
    }


def _capture(
    source_id: str,
    publisher: dict[str, Any],
    *,
    item_id: str | None = None,
    registry_version: int = 1,
    retrieved_at: str = "2026-10-25T00:00:00Z",
    capture_id: str = "current",
    contract_version: str = "2.0.0",
) -> dict[str, Any]:
    return {
        "item_id": item_id or f"{source_id}-item",
        "revision_id": "revision",
        "source_id": source_id,
        "registry_version": registry_version,
        "transport": "api",
        "retrieved_at": retrieved_at,
        "capture_id": capture_id,
        "item_document": {
            "contract_version": contract_version,
            "publisher_metadata": publisher,
            "field_states": {"published_at": "present", "updated_at": "not_provided"},
        },
    }


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


def _activations(versions: list[dict[str, Any]], *, blocked: set[str] | None = None) -> list[dict]:
    blocked = blocked or set()
    rows = []
    for version in versions:
        state = "BLOCKED" if version["source_id"] in blocked else "ACTIVE"
        rows.append(
            {
                "source_id": version["source_id"],
                "registry_version": version["registry_version"],
                "registry_sha256": version["registry_sha256"],
                "state": state,
            }
        )
    return rows


def _publisher(
    source_family: str,
    source_item_id: str,
    publisher: str,
    abstract: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    document = {
        "publisher": publisher,
        "source_family": source_family,
        "source_item_id": source_item_id,
        "authors": ["Test Author"],
        "categories": ["Lyme disease"],
        "language": "en",
        "media": [],
    }
    if abstract is not None:
        document["abstract"] = abstract
    document.update(extra)
    return document


def _feed(
    captures: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    blocked: set[str] | None = None,
) -> list[dict[str, Any]]:
    versions = _unique_versions(captures)
    admitted = _admit(captures, versions, _activations(versions, blocked=blocked))
    projected = []
    for capture in admitted:
        projected.append(
            {
                "item_id": capture["item_id"],
                "source_id": capture["source_id"],
                "abstract_suppressed": _is_suppressed(
                    capture["item_document"]["publisher_metadata"], rows
                ),
                "publisher_metadata": _project(capture["item_document"], rows),
            }
        )
    return projected


def _unique_versions(captures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, int]] = set()
    versions = []
    for capture in captures:
        key = (capture["source_id"], capture["registry_version"])
        if key in seen:
            continue
        seen.add(key)
        versions.append(_version(capture["source_id"], capture["registry_version"]))
    return versions


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["source_id"]] = counts.get(row["source_id"], 0) + 1
    return counts


def test_suppressed_pmid_hides_captured_abstract_without_dropping_the_row() -> None:
    captured = {
        "text": "Lyme disease abstract text.",
        "state": "present",
        "copyright_line": COPYRIGHT,
        "format": "plain_text",
    }
    captures = [
        _capture(
            "pubmed",
            _publisher("pubmed", "12345678", "National Library of Medicine", captured),
        )
    ]
    rows = [{"scope": "PMID", "pmid": "12345678", "publisher": None}]
    feed = _feed(captures, rows)
    assert len(feed) == 1
    row = feed[0]
    assert row["abstract_suppressed"] is True
    assert row["publisher_metadata"]["abstract"] == SUPPRESSED_ABSTRACT
    assert row["publisher_metadata"]["abstract_suppressed"] is True
    assert "format" not in row["publisher_metadata"]["abstract"]


def test_suppressed_publisher_hides_every_item_from_that_publisher() -> None:
    captured = {"text": "Visible until the publisher is suppressed.", "state": "present"}
    publisher = "National Library of Medicine"
    captures = [
        _capture(
            "pubmed",
            _publisher("pubmed", "12345678", publisher, captured),
            item_id="pmid-one",
        ),
        _capture(
            "pubmed",
            _publisher("pubmed", "87654321", publisher, dict(captured)),
            item_id="pmid-two",
        ),
        _capture(
            "pubmed",
            _publisher("pubmed", "11111111", "Other Publisher", dict(captured)),
            item_id="other-publisher",
        ),
    ]
    rows = [{"scope": "PUBLISHER", "pmid": None, "publisher": publisher}]
    feed = _feed(captures, rows)
    assert len(feed) == 3
    hidden = [row for row in feed if row["item_id"] != "other-publisher"]
    assert len(hidden) == 2
    assert all(row["abstract_suppressed"] is True for row in hidden)
    assert all(row["publisher_metadata"]["abstract"] == SUPPRESSED_ABSTRACT for row in hidden)
    kept = next(row for row in feed if row["item_id"] == "other-publisher")
    assert kept["abstract_suppressed"] is False
    assert kept["publisher_metadata"]["abstract"]["text"] == captured["text"]


def test_unsuppressed_abstract_is_the_captured_object() -> None:
    captured = {
        "text": "Lyme disease abstract text.",
        "state": "present",
        "copyright_line": COPYRIGHT,
        "language": "eng",
    }
    mesh = ["Lyme Disease"]
    publication_types = ["Journal Article"]
    matched_queries = ["lyme"]
    captures = [
        _capture(
            "pubmed",
            _publisher(
                "pubmed",
                "12345678",
                "National Library of Medicine",
                captured,
                mesh=mesh,
                publication_types=publication_types,
                matched_queries=matched_queries,
            ),
        )
    ]
    feed = _feed(captures, [])
    abstract = feed[0]["publisher_metadata"]["abstract"]
    assert abstract == captured
    assert abstract["text"] == captured["text"]
    assert abstract["state"] == "present"
    assert abstract["copyright_line"] == COPYRIGHT
    assert feed[0]["abstract_suppressed"] is False
    metadata = feed[0]["publisher_metadata"]
    assert metadata["mesh"] == mesh
    assert metadata["publication_types"] == publication_types
    assert metadata["matched_queries"] == matched_queries
    assert metadata["abstract_suppressed"] is False


@pytest.mark.parametrize(
    "captured",
    [
        {"text": None, "state": "withheld", "copyright_line": COPYRIGHT},
        {"text": "", "state": "empty", "copyright_line": None},
        {"text": None, "state": "not_provided", "copyright_line": None},
    ],
)
def test_captured_abstract_states_pass_through_without_invented_text(
    captured: dict[str, Any],
) -> None:
    captures = [
        _capture(
            "pubmed",
            _publisher("pubmed", "12345678", "National Library of Medicine", captured),
        )
    ]
    feed = _feed(captures, [])
    assert feed[0]["publisher_metadata"]["abstract"] == captured
    assert feed[0]["abstract_suppressed"] is False
    assert feed[0]["publisher_metadata"]["abstract"]["text"] == captured["text"]


def test_pmid_and_publisher_matches_still_project_one_row() -> None:
    captured = {"text": "Captured text.", "state": "present", "copyright_line": COPYRIGHT}
    publisher = "National Library of Medicine"
    captures = [
        _capture("pubmed", _publisher("pubmed", "12345678", publisher, captured)),
        _capture(
            "pubmed",
            _publisher("pubmed", "12345678", publisher, captured),
            retrieved_at="2026-10-24T00:00:00Z",
            capture_id="older",
        ),
    ]
    rows = [
        {"scope": "PMID", "pmid": "12345678", "publisher": None},
        {"scope": "PMID", "pmid": "12345678", "publisher": None},
        {"scope": "PUBLISHER", "pmid": None, "publisher": publisher},
    ]
    feed = _feed(captures, rows)
    assert len(feed) == 1
    assert feed[0]["abstract_suppressed"] is True
    assert feed[0]["publisher_metadata"]["abstract"] == SUPPRESSED_ABSTRACT


def test_existing_source_row_counts_stay_identical_and_non_pubmed_abstracts_stay_null() -> None:
    captures = []
    for source_id in LIVE_SOURCES:
        captures.append(
            _capture(
                source_id,
                _publisher("cdc_other", f"{source_id}-id", "Centers for Disease Control"),
            )
        )
    captures.append(
        _capture(
            "pubmed",
            _publisher(
                "pubmed",
                "12345678",
                "National Library of Medicine",
                {"text": "PubMed abstract.", "state": "present", "copyright_line": COPYRIGHT},
            ),
        )
    )
    before = _feed(captures, [])
    after = _feed(
        captures,
        [{"scope": "PMID", "pmid": "12345678", "publisher": None}],
    )
    assert _counts(before) == _counts(after)
    assert _counts(before) == {source_id: 1 for source_id in (*LIVE_SOURCES, "pubmed")}
    for row in before:
        if row["source_id"] == "pubmed":
            continue
        assert row["publisher_metadata"]["abstract"] is None
        assert row["abstract_suppressed"] is False
        assert row["publisher_metadata"]["abstract_suppressed"] is False
    pubmed = next(row for row in after if row["source_id"] == "pubmed")
    assert pubmed["abstract_suppressed"] is True
    assert _counts(before)[pubmed["source_id"]] == 1


def test_blocked_activation_stays_out_of_the_feed() -> None:
    captures = [
        _capture(
            "pubmed",
            _publisher(
                "pubmed",
                "12345678",
                "National Library of Medicine",
                {"text": "Hidden by activation.", "state": "present"},
            ),
        )
    ]
    assert _feed(captures, [], blocked={"pubmed"}) == []


def test_v175_is_one_protected_step_for_both_databases() -> None:
    pinned = INTELLIGENCE_ABSTRACT_SUPPRESSION_MIGRATION
    migration = next(item for item in load_migrations() if item.version == pinned["version"])
    assert migrations._migration_metadata(migration) == pinned
    digest = hashlib.sha256(V175.read_text(encoding="utf-8").encode()).hexdigest()
    assert pinned["sha256"] == digest
    assert pinned["filename"] == V175.name
    assert pinned["version"] == "V175"
    assert all(item.version != "V172" for item in load_migrations())
    assert not list((ROOT / "migrations").glob("V172*"))
    assert pinned["version"] in BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS
    assert pinned in PROTECTED_INTELLIGENCE_MIGRATIONS
    assert pinned["version"] not in DEV_ONLY_MIGRATION_VERSIONS
    assert pinned["version"] not in PROD_ONLY_MIGRATION_VERSIONS
    assert pinned in migration_plan(DEV_DATABASE)
    assert pinned in migration_plan(PROD_DATABASE)
    assert is_intelligence_prerequisite_batch([pinned])
    versions = [item.version for item in load_migrations()]
    assert versions.index("V170") < versions.index("V173") < versions.index("V175")
    allow_list = json.dumps([pinned], separators=(",", ":"))
    workflow = (ROOT / ".github/workflows/promote-prod.yml").read_text(encoding="utf-8")
    guard = (ROOT / "tests/test_ci_guard.py").read_text(encoding="utf-8")
    assert workflow.count(allow_list) == 1
    assert allow_list in guard
    sql = migration.source
    table, view = sql.split("CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2", 1)
    assert "CREATE TABLE IF NOT EXISTS GOVERNANCE.INTELLIGENCE_ABSTRACT_SUPPRESSIONS" in table
    for column in ("scope", "pmid", "publisher", "reason", "decision_id", "created_at"):
        assert column in table
    assert "scope = 'PMID'" in table and "pmid IS NOT NULL" in table
    assert "publisher IS NULL" in table
    assert "scope = 'PUBLISHER'" in table and "publisher IS NOT NULL" in table
    assert "pmid IS NULL" in table
    assert "reason VARCHAR NOT NULL" in table
    assert "decision_id VARCHAR(200) NOT NULL" in table
    assert "DEFAULT CURRENT_TIMESTAMP()" in table
    assert table.count("GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_ABSTRACT_SUPPRESSIONS") == 2
    assert "OH_LYME_{{ ENV }}_RUNTIME" in table
    assert "OH_LYME_{{ ENV }}_READ" in table
    assert "GRANT INSERT" not in sql and "GRANT UPDATE" not in sql and "GRANT DELETE" not in sql
    assert "MERGE " not in sql and "INSERT INTO" not in sql
    assert view.count("COPY GRANTS") == 1
    assert "GRANT" not in view.replace("COPY GRANTS", "")
    assert "REVOKE" not in view
    assert "QUERY_TEXT" not in sql.upper() and "ERROR_MESSAGE" not in sql.upper()
    assert "reason" not in view.lower()
    for key in (
        "description",
        "abstract",
        "categories",
        "authors",
        "source_family",
        "source_item_id",
        "abstract_suppressed",
        "mesh",
        "publication_types",
        "matched_queries",
    ):
        assert f"'{key}'" in view
    assert "c.item_document:publisher_metadata:abstract" in view
    preflight = (ROOT / "scripts/verify_intelligence_dev_preflight.py").read_text(encoding="utf-8")
    daily = (ROOT / "scripts/verify_intelligence_daily_view_dev.py").read_text(encoding="utf-8")
    assert pinned["filename"] in preflight
    assert f'MIGRATION = "{pinned["filename"]}"' in daily


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
        expected_pending=[INTELLIGENCE_ABSTRACT_SUPPRESSION_MIGRATION],
        protected_intelligence_prerequisite=protected,
    )
    return connection, executed


@pytest.mark.parametrize("database", [DEV_DATABASE, PROD_DATABASE])
def test_v175_requires_recorded_v173_and_the_protected_path(
    monkeypatch: pytest.MonkeyPatch, database: str
) -> None:
    loaded = load_migrations()
    v173 = next(item for item in loaded if item.version == "V173")
    v175 = next(item for item in loaded if item.version == "V175")
    with pytest.raises(PermissionError, match="V175 requires recorded V173"):
        _apply(monkeypatch, database, [v175], [], protected=True)

    with pytest.raises(PermissionError, match="protected intelligence prerequisite"):
        _apply(
            monkeypatch,
            database,
            [v173, v175],
            [("V173", v173.sha256)],
            protected=False,
        )

    connection, executed_versions = _apply(
        monkeypatch,
        database,
        [v173, v175],
        [("V173", v173.sha256)],
        protected=True,
    )
    assert executed_versions == ["V175"]
    executed = connection.execute_string.call_args.args[0]
    assert database in executed
    assert "{{ DATABASE }}" not in executed and "{{ ENV }}" not in executed
    environment = "DEV" if database == DEV_DATABASE else "PROD"
    assert f"OH_LYME_{environment}_RUNTIME" in executed
    assert f"OH_LYME_{environment}_READ" in executed
    assert "INTELLIGENCE_ABSTRACT_SUPPRESSIONS" in executed
    assert "COPY GRANTS" in executed
    assert "a.state = 'ACTIVE'" in executed
    assert "c.item_document:publisher_metadata:abstract" in executed
