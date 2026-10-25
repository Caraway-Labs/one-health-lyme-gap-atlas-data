"""Activation-table feed admission. Offline only: no warehouse connection."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lyme_gap_atlas_data.intelligence_activations import (
    activation_for_registration,
    activation_merge_statement,
    load_registry_documents,
    prior_stays_active,
    rows_for_reviewed_registration,
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
    is_intelligence_prerequisite_batch,
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
PREDICATE = re.compile(
    r"s\.registry_version=1 AND newer\.registry_version=2\n"
    r"\s+AND s\.registry_sha256=(CASE s\.source_id WHEN .*? ELSE '' END)\n"
    r"\s+AND newer\.registry_sha256=(CASE s\.source_id WHEN .*? ELSE '' END)\n"
    r"\s+AND newer\.registry_document:state::VARCHAR='active'\n"
    r"\s+AND newer\.registry_document:approval:status::VARCHAR='approved'\n"
    r"\s+AND newer\.registry_document:trust_review:status::VARCHAR='approved'"
)


def _migration_sql() -> str:
    pinned = INTELLIGENCE_SOURCE_ACTIVATION_MIGRATION
    migration = next(item for item in load_migrations() if item.version == pinned["version"])
    assert migration.filename == pinned["filename"]
    assert migration.sha256 == pinned["sha256"]
    return migration.source


PIN_ROW = re.compile(r"\('([a-z0-9-]+)', '([0-9a-f]{64})', '([0-9a-f]{64})'\)")


def _using_sql(sql: str) -> str:
    merge = sql.split("MERGE INTO GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS target", 1)[1]
    return merge.split("USING (", 1)[1].split(") source\nON target.source_id", 1)[0]


def _pin_pairs(sql: str) -> dict[str, tuple[str, str]]:
    using = _using_sql(sql)
    pins = using.split("WITH pins AS (", 1)[1].split("),\n    candidates AS (", 1)[0]
    found = {source_id: (old, new) for source_id, old, new in PIN_ROW.findall(pins)}
    assert len(found) == len(PIN_ROW.findall(pins))
    assert set(found) == set(LIVE_SOURCES)
    return found


def _view_sql(sql: str) -> str:
    return sql.split("CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2", 1)[1]


def _pairs(sql: str) -> dict[str, tuple[str, str]]:
    match = PREDICATE.search(sql)
    assert match is not None
    found: dict[str, tuple[str, str]] = {}
    for body, side in ((match.group(1), 0), (match.group(2), 1)):
        for source_id, digest in re.findall(r"WHEN '([^']+)' THEN '([0-9a-f]{64})'", body):
            current = found.get(source_id, ("", ""))
            if side == 0:
                found[source_id] = (digest, current[1])
            else:
                found[source_id] = (current[0], digest)
    assert set(found) == set(LIVE_SOURCES)
    return found


def _blocked(
    version: dict[str, Any],
    versions: list[dict[str, Any]],
    *,
    prod: bool,
    pairs: dict[str, tuple[str, str]],
) -> bool:
    for newer in versions:
        if (
            newer["source_id"] != version["source_id"]
            or newer["registry_version"] <= version["registry_version"]
        ):
            continue
        document = newer["document"]
        exception = (
            prod
            and version["registry_version"] == 1
            and newer["registry_version"] == 2
            and pairs.get(version["source_id"])
            == (version["registry_sha256"], newer["registry_sha256"])
            and document["state"] == "active"
            and document["approval"]["status"] == "approved"
            and document["trust_review"]["status"] == "approved"
        )
        if not exception:
            return True
    return False


def _publishable(version: dict[str, Any]) -> bool:
    document = version["document"]
    return (
        document["approval"]["status"] == "approved"
        and document["trust_review"]["status"] == "approved"
        and document["state"] in {"active", "manual"}
    )


def _seed(
    versions: list[dict[str, Any]],
    *,
    prod: bool,
    pairs: dict[str, tuple[str, str]],
) -> list[dict[str, Any]]:
    rows = []
    for version in versions:
        if version["source_id"] not in LIVE_SOURCES:
            continue
        if _blocked(version, versions, prod=prod, pairs=pairs):
            continue
        rows.append(
            {
                "source_id": version["source_id"],
                "registry_version": version["registry_version"],
                "registry_sha256": version["registry_sha256"],
                "state": "ACTIVE",
            }
        )
    return rows


def _feed_items(
    captures: list[dict[str, Any]],
    versions: list[dict[str, Any]],
    *,
    mode: str,
    pairs: dict[str, tuple[str, str]],
    activations: list[dict[str, Any]] | None = None,
) -> dict[str, set[tuple[str, int]]]:
    candidates = []
    for capture in captures:
        if capture["contract_version"] != "2.0.0":
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
        if version is None or not _publishable(version):
            continue
        if mode == "v142" and _blocked(version, versions, prod=False, pairs=pairs):
            continue
        if mode == "v167" and _blocked(version, versions, prod=True, pairs=pairs):
            continue
        if mode == "activation":
            assert activations is not None
            admitted = any(
                row["state"] == "ACTIVE"
                and row["source_id"] == version["source_id"]
                and row["registry_version"] == version["registry_version"]
                and row["registry_sha256"] == version["registry_sha256"]
                for row in activations
            )
            if not admitted:
                continue
        candidates.append(capture)
    winners: dict[tuple[Any, ...], dict[str, Any]] = {}
    for capture in candidates:
        if mode == "v142":
            key = (
                capture["item_id"],
                capture["revision_id"],
                capture["source_id"],
                capture["registry_version"],
                capture["transport"],
            )
        else:
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
    grouped: dict[str, set[tuple[str, int]]] = {}
    for capture in winners.values():
        grouped.setdefault(capture["source_id"], set()).add(
            (capture["item_id"], capture["registry_version"])
        )
    return grouped


def _live_versions() -> list[dict[str, Any]]:
    versions = []
    for document in load_registry_documents():
        if document["source_id"] not in LIVE_SOURCES:
            continue
        versions.append(
            {
                "source_id": document["source_id"],
                "registry_version": document["registry_version"],
                "registry_sha256": identity_hash(document),
                "document": document,
            }
        )
    return versions


def _captures_for(versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    captures = []
    seen: set[str] = set()
    for version in versions:
        source_id = version["source_id"]
        registry_version = version["registry_version"]
        captures.append(
            {
                "item_id": f"{source_id}-v{registry_version}",
                "revision_id": "revision",
                "source_id": source_id,
                "registry_version": registry_version,
                "transport": "rss",
                "contract_version": "2.0.0",
                "retrieved_at": f"2026-10-2{registry_version}T00:00:00Z",
                "capture_id": f"{source_id}-{registry_version}",
            }
        )
        if source_id in seen:
            continue
        seen.add(source_id)
        for registry_version, retrieved_at, capture_id in (
            (1, "2026-10-21T00:00:00Z", "shared-old"),
            (2, "2026-10-22T00:00:00Z", "shared-new"),
        ):
            captures.append(
                {
                    "item_id": f"{source_id}-shared",
                    "revision_id": "revision",
                    "source_id": source_id,
                    "registry_version": registry_version,
                    "transport": "rss",
                    "contract_version": "2.0.0",
                    "retrieved_at": retrieved_at,
                    "capture_id": f"{source_id}-{capture_id}",
                }
            )
        captures.append(
            {
                "item_id": f"{source_id}-other-contract",
                "revision_id": "revision",
                "source_id": source_id,
                "registry_version": 2,
                "transport": "rss",
                "contract_version": "1.0.0",
                "retrieved_at": "2026-10-22T00:00:00Z",
                "capture_id": f"{source_id}-other-contract",
            }
        )
    return captures


def test_activation_migration_is_one_protected_step_for_both_databases() -> None:
    pinned = INTELLIGENCE_SOURCE_ACTIVATION_MIGRATION
    assert pinned["version"] in BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS
    assert pinned in PROTECTED_INTELLIGENCE_MIGRATIONS
    assert pinned["version"] not in DEV_ONLY_MIGRATION_VERSIONS
    assert pinned["version"] not in PROD_ONLY_MIGRATION_VERSIONS
    assert pinned in migration_plan(DEV_DATABASE)
    assert pinned in migration_plan(PROD_DATABASE)
    assert is_intelligence_prerequisite_batch([pinned])
    sql = _migration_sql()
    assert sql.count("CREATE TABLE") == 1
    assert sql.count("MERGE INTO GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS") == 1
    assert sql.count("CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2") == 1
    assert "PRIMARY KEY (source_id, registry_version)" in sql
    assert "'ACTIVE' AS state" in sql
    assert "'BLOCKED'" not in sql
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


def test_backfill_keeps_every_version_the_current_feed_serves() -> None:
    current = (ROOT / "migrations/V167__prod_cdc_mmwr_daily_activation_view.sql").read_text()
    migration = _migration_sql()
    assert _pairs(current) == _pin_pairs(migration)
    assert "'{{ ENV }}' = 'PROD'" in _using_sql(migration)
    pairs = _pairs(current)
    versions = _live_versions()
    assert {version["registry_version"] for version in versions} == {1, 2}
    for source_id in LIVE_SOURCES:
        assert pairs[source_id] == (
            next(
                version["registry_sha256"]
                for version in versions
                if version["source_id"] == source_id and version["registry_version"] == 1
            ),
            next(
                version["registry_sha256"]
                for version in versions
                if version["source_id"] == source_id and version["registry_version"] == 2
            ),
        )
    prod_seed = _seed(versions, prod=True, pairs=pairs)
    dev_seed = _seed(versions, prod=False, pairs=pairs)
    assert {(row["source_id"], row["registry_version"]) for row in prod_seed} == {
        (source_id, version) for source_id in LIVE_SOURCES for version in (1, 2)
    }
    assert {(row["source_id"], row["registry_version"]) for row in dev_seed} == {
        (source_id, 2) for source_id in LIVE_SOURCES
    }
    assert all(row["state"] == "ACTIVE" for row in prod_seed + dev_seed)
    ahead = next(
        version
        for version in versions
        if version["source_id"] == "cdc-eid-ahead-of-print" and version["registry_version"] == 1
    )
    tampered = json.loads(json.dumps(versions))
    for version in tampered:
        if version["source_id"] == "cdc-eid-ahead-of-print" and version["registry_version"] == 2:
            version["registry_sha256"] = "0" * 64
    hidden = _seed(tampered, prod=True, pairs=pairs)
    assert (ahead["source_id"], 1) not in {
        (row["source_id"], row["registry_version"]) for row in hidden
    }


def test_new_view_returns_the_same_live_source_items_as_the_case_logic() -> None:
    current = (ROOT / "migrations/V167__prod_cdc_mmwr_daily_activation_view.sql").read_text()
    pairs = _pairs(current)
    versions = _live_versions()
    captures = _captures_for(versions)
    prod_items = _feed_items(
        captures,
        versions,
        mode="activation",
        pairs=pairs,
        activations=_seed(versions, prod=True, pairs=pairs),
    )
    dev_items = _feed_items(
        captures,
        versions,
        mode="activation",
        pairs=pairs,
        activations=_seed(versions, prod=False, pairs=pairs),
    )
    assert prod_items == _feed_items(captures, versions, mode="v167", pairs=pairs)
    assert dev_items == _feed_items(captures, versions, mode="v142", pairs=pairs)
    ahead_v1 = ("cdc-eid-ahead-of-print-v1", 1)
    assert ahead_v1 in prod_items["cdc-eid-ahead-of-print"]
    assert ahead_v1 not in dev_items["cdc-eid-ahead-of-print"]
    assert ("cdc-eid-ahead-of-print-shared", 2) in prod_items["cdc-eid-ahead-of-print"]
    assert ("cdc-eid-ahead-of-print-shared", 1) not in prod_items["cdc-eid-ahead-of-print"]
    only_v1 = [version for version in versions if version["registry_version"] == 1]
    only_captures = [
        capture
        for capture in captures
        if capture["registry_version"] == 1 and "shared" not in capture["item_id"]
    ]
    prod_only = _feed_items(
        only_captures,
        only_v1,
        mode="activation",
        pairs=pairs,
        activations=_seed(only_v1, prod=True, pairs=pairs),
    )
    assert prod_only == _feed_items(only_captures, only_v1, mode="v167", pairs=pairs)
    assert ("cdc-eid-ahead-of-print-v1", 1) in prod_only["cdc-eid-ahead-of-print"]


def test_synthetic_blocked_version_is_hidden_and_a_new_source_needs_no_ddl() -> None:
    sql = _migration_sql()
    view = _view_sql(sql)
    assert "example-blocked-feed" not in sql and "example-new-feed" not in sql
    synthetic = {
        "source_id": "example-blocked-feed",
        "registry_version": 1,
        "registry_sha256": "a" * 64,
        "document": {
            "state": "manual",
            "approval": {"status": "approved"},
            "trust_review": {"status": "approved"},
        },
    }
    successor = {
        "source_id": "example-blocked-feed",
        "registry_version": 2,
        "registry_sha256": "b" * 64,
        "document": {
            "state": "active",
            "approval": {"status": "approved"},
            "trust_review": {"status": "approved"},
        },
    }
    captures = [
        {
            "item_id": "old-item",
            "revision_id": "revision",
            "source_id": "example-blocked-feed",
            "registry_version": 1,
            "transport": "rss",
            "contract_version": "2.0.0",
            "retrieved_at": "2026-10-21T00:00:00Z",
            "capture_id": "old",
        },
        {
            "item_id": "new-item",
            "revision_id": "revision",
            "source_id": "example-blocked-feed",
            "registry_version": 2,
            "transport": "rss",
            "contract_version": "2.0.0",
            "retrieved_at": "2026-10-22T00:00:00Z",
            "capture_id": "new",
        },
    ]
    activations = [
        {**synthetic, "state": "BLOCKED"},
        {**successor, "state": "ACTIVE"},
    ]
    published = _feed_items(
        captures,
        [synthetic, successor],
        mode="activation",
        pairs={},
        activations=activations,
    )
    assert published == {"example-blocked-feed": {("new-item", 2)}}
    fresh = json.loads(json.dumps(successor))
    fresh["source_id"] = "example-new-feed"
    fresh_capture = json.loads(json.dumps(captures[1]))
    fresh_capture["source_id"] = "example-new-feed"
    fresh_capture["item_id"] = "fresh-item"
    admitted = _feed_items(
        [fresh_capture],
        [fresh],
        mode="activation",
        pairs={},
        activations=[{**fresh, "state": "ACTIVE"}],
    )
    assert admitted == {"example-new-feed": {("fresh-item", 2)}}
    assert "example-new-feed" not in view


def test_registration_merge_does_not_block_a_version_prod_still_serves() -> None:
    documents = {
        (document["source_id"], document["registry_version"]): document
        for document in load_registry_documents()
    }
    current = documents[("cdc-eid-ahead-of-print", 2)]
    previous = documents[("cdc-eid-ahead-of-print", 1)]
    assert prior_stays_active(previous, current)
    prod_rows = rows_for_reviewed_registration(
        current, previous, database="ONE_HEALTH_LYME_GAP_ATLAS_PROD"
    )
    assert [row.state for row in prod_rows] == ["ACTIVE"]
    assert prod_rows[0].registry_version == 2
    assert prod_rows[0].registry_sha256 == identity_hash(current)
    dev_rows = rows_for_reviewed_registration(
        current, previous, database="ONE_HEALTH_LYME_GAP_ATLAS_DEV"
    )
    assert [(row.registry_version, row.state) for row in dev_rows] == [
        (2, "ACTIVE"),
        (1, "BLOCKED"),
    ]
    forced = activation_for_registration(current, superseded=(previous,))
    assert [row.state for row in forced] == ["ACTIVE", "BLOCKED"]
    synthetic = json.loads(json.dumps(current))
    synthetic_prior = json.loads(json.dumps(previous))
    synthetic["source_id"] = "example-blocked-feed"
    synthetic_prior["source_id"] = "example-blocked-feed"
    blocked = activation_for_registration(synthetic, superseded=(synthetic_prior,))
    assert [row.state for row in blocked] == ["ACTIVE", "BLOCKED"]
    statement, params = activation_merge_statement(prod_rows)
    again, again_params = activation_merge_statement(prod_rows)
    assert statement == again and params == again_params
    assert statement.count("MERGE INTO") == 1
    assert "WHEN MATCHED AND" in statement and "WHEN NOT MATCHED THEN INSERT" in statement
    assert params == (
        current["source_id"],
        2,
        identity_hash(current),
        "ACTIVE",
        current["approval"]["decision_ref"],
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
    rows = rows_for_reviewed_registration(
        current, previous, database="ONE_HEALTH_LYME_GAP_ATLAS_PROD"
    )
    assert source_is_active(current, documents, rows)
    assert not source_is_active(previous, documents, rows)
    fresh = json.loads(json.dumps(current))
    fresh["source_id"] = "example-new-feed"
    fresh_rows = activation_for_registration(fresh)
    assert source_is_active(fresh, (fresh,), fresh_rows)
    assert not any(row.source_id == "example-new-feed" for row in rows)


def test_backfill_using_has_no_correlated_case_subquery() -> None:
    """PROD Snowflake rejects a correlated subquery with CASE (error 002031)."""
    using = _using_sql(_migration_sql())
    upper = using.upper()
    assert "CASE" not in upper
    assert "EXISTS" not in upper
    assert "CASE S.SOURCE_ID" not in upper
    # Four plain SELECTs (pins, candidates, superseded, result) and no nested subquery.
    assert upper.count("SELECT") == 4
    assert "JOIN GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS NEWER" in upper
    assert "LEFT JOIN PINS P" in upper and "LEFT JOIN SUPERSEDED X" in upper
    assert "WHERE X.SOURCE_ID IS NULL" in upper
    for check in (
        "newer.registry_document:state::VARCHAR='active'",
        "newer.registry_document:approval:status::VARCHAR='approved'",
        "newer.registry_document:trust_review:status::VARCHAR='approved'",
        "c.registry_version=1 AND newer.registry_version=2",
        "s.registry_document:approval:decision_ref::VARCHAR IS NOT NULL",
    ):
        assert check in using
