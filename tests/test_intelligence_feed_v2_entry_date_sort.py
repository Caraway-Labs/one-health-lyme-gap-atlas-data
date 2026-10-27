"""V178 feed view: V175 columns, with FEED_SORT_AT falling back to the entry date."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from lyme_gap_atlas_data import migrations
from lyme_gap_atlas_data.migrations import (
    BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS,
    DEV_DATABASE,
    DEV_ONLY_MIGRATION_VERSIONS,
    INTELLIGENCE_FEED_ENTRY_DATE_SORT_MIGRATION,
    PROD_DATABASE,
    PROD_ONLY_MIGRATION_VERSIONS,
    PROTECTED_INTELLIGENCE_MIGRATIONS,
    is_intelligence_prerequisite_batch,
    load_migrations,
    migration_plan,
)

ROOT = Path(__file__).parents[1]
V175 = ROOT / "migrations" / "V175__intelligence_abstract_suppressions_feed_v2.sql"
V178 = ROOT / "migrations" / "V178__intelligence_feed_v2_entry_date_sort.sql"
_DML = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|CREATE\s+TABLE)\b", re.IGNORECASE)
_SORT_EXPR = re.compile(r"IFF\(.*\)::TIMESTAMP_TZ AS FEED_SORT_AT", re.DOTALL)
_ENTRY_DATE = "TRY_TO_TIMESTAMP_TZ(item_document:publisher_metadata:entry_date::VARCHAR)"
_PUBLISHED = "TRY_TO_TIMESTAMP_TZ(published_at)"


def _view(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    marker = "CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2"
    return source[source.index(marker) :]


def _outer_columns(view: str) -> list[str]:
    outer = view.split("FROM (", 1)[0]
    select = _SORT_EXPR.sub("FEED_SORT_AT", outer.split("SELECT", 1)[1], count=1)
    names: list[str] = []
    for part in select.split(","):
        token = part.strip()
        if not token:
            continue
        if " AS " in token:
            token = token.split(" AS ")[-1].strip()
        names.append(token)
    return names


def _feed_sort_at(
    published_at: datetime | None,
    entry_date: datetime | None,
    first_loaded_at: datetime,
    *,
    published_parses: bool = True,
    entry_parses: bool = True,
) -> datetime:
    """Publish date, then PubMed entry date, then first load. Never later than first load."""
    if published_at is not None and published_parses and published_at <= first_loaded_at:
        return published_at
    if entry_date is not None and entry_parses and entry_date <= first_loaded_at:
        return entry_date
    return first_loaded_at


def _legacy_sort(published_at: datetime | None, first_loaded_at: datetime) -> datetime:
    if published_at is None or published_at > first_loaded_at:
        return first_loaded_at
    return published_at


def test_v178_keeps_the_v175_column_list_and_changes_only_feed_sort_at() -> None:
    previous = _view(V175)
    updated = _view(V178)
    assert updated.count("COPY GRANTS") == 1
    assert "CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2 COPY GRANTS" in updated
    columns = _outer_columns(updated)
    assert columns == _outer_columns(previous)
    assert len(columns) == 28
    assert columns[-2:] == ["FEED_SORT_AT", "ABSTRACT_SUPPRESSED"]
    assert updated.index("AS FEED_SORT_AT") < updated.index("AS ABSTRACT_SUPPRESSED")
    expression = updated.split("AS FEED_SORT_AT", 1)[0]
    published_at = expression.rfind(_PUBLISHED)
    entry_at = expression.rfind(_ENTRY_DATE)
    fallback_at = expression.rfind("first_loaded_at")
    assert 0 <= published_at < entry_at < fallback_at
    assert expression.count(_PUBLISHED) == 3
    assert expression.count(_ENTRY_DATE) == 3
    assert "c.item_document AS item_document" in updated
    assert "IFF(c.transport = 'entrez', NULL, c.revision_id)" in updated
    assert "IFF(c.transport = 'entrez', c.capture_id, NULL) DESC" in updated
    assert "MIN(c.retrieved_at) OVER" in updated
    restored = updated.replace(
        "       c.item_document AS item_document,\n",
        "",
        1,
    )
    previous_sort = previous.split("reviewed_trust_classification,\n", 1)[1].split(
        "\n       abstract_suppressed AS ABSTRACT_SUPPRESSED",
        1,
    )[0]
    updated_sort = restored.split("reviewed_trust_classification,\n", 1)[1].split(
        "\n       abstract_suppressed AS ABSTRACT_SUPPRESSED",
        1,
    )[0]
    restored = restored.replace(updated_sort, previous_sort, 1)
    assert restored == previous


def test_month_only_pubmed_row_sorts_by_entry_date() -> None:
    first_loaded = datetime.fromisoformat("2026-10-20T04:28:00+00:00")
    entry_date = datetime.fromisoformat("2024-03-15T00:00:00+00:00")
    assert _feed_sort_at(None, entry_date, first_loaded) == entry_date


def test_future_dates_fall_back_and_a_usable_publish_date_wins() -> None:
    first_loaded = datetime.fromisoformat("2026-10-20T04:28:00+00:00")
    entry_date = datetime.fromisoformat("2024-03-15T00:00:00+00:00")
    future = datetime.fromisoformat("2027-01-01T00:00:00+00:00")
    published = datetime.fromisoformat("2026-09-01T00:00:00+00:00")
    assert _feed_sort_at(future, entry_date, first_loaded) == entry_date
    assert _feed_sort_at(future, future, first_loaded) == first_loaded
    assert _feed_sort_at(None, future, first_loaded) == first_loaded
    assert _feed_sort_at(published, entry_date, first_loaded) == published
    assert _feed_sort_at(first_loaded, entry_date, first_loaded) == first_loaded
    assert _feed_sort_at(None, first_loaded, first_loaded) == first_loaded
    assert _feed_sort_at(future, entry_date, first_loaded, entry_parses=False) == first_loaded
    assert _feed_sort_at(None, entry_date, first_loaded, entry_parses=False) == first_loaded
    assert _feed_sort_at(published, entry_date, first_loaded, published_parses=False) == entry_date


def test_non_pubmed_rows_keep_the_publish_date_or_first_load_choice() -> None:
    first_loaded = datetime.fromisoformat("2026-10-20T04:28:00+00:00")
    published = datetime.fromisoformat("2026-09-01T00:00:00+00:00")
    future = datetime.fromisoformat("2027-01-01T00:00:00+00:00")
    cases = (None, published, future, first_loaded)
    for published_at in cases:
        assert _feed_sort_at(published_at, None, first_loaded) == _legacy_sort(
            published_at, first_loaded
        )
        assert _feed_sort_at(published_at, None, first_loaded) <= first_loaded


def test_v178_is_one_protected_view_step_for_both_databases() -> None:
    pinned = INTELLIGENCE_FEED_ENTRY_DATE_SORT_MIGRATION
    migration = next(item for item in load_migrations() if item.version == pinned["version"])
    assert migrations._migration_metadata(migration) == pinned
    digest = hashlib.sha256(V178.read_text(encoding="utf-8").encode()).hexdigest()
    assert pinned["sha256"] == digest == migration.sha256
    assert pinned["filename"] == V178.name
    assert pinned["version"] == "V178"
    assert pinned["version"] in BOTH_ENVIRONMENT_INTELLIGENCE_MIGRATIONS
    assert pinned in PROTECTED_INTELLIGENCE_MIGRATIONS
    assert pinned["version"] not in DEV_ONLY_MIGRATION_VERSIONS
    assert pinned["version"] not in PROD_ONLY_MIGRATION_VERSIONS
    assert pinned in migration_plan(DEV_DATABASE)
    assert pinned in migration_plan(PROD_DATABASE)
    assert is_intelligence_prerequisite_batch([pinned])
    versions = [item.version for item in load_migrations()]
    assert versions.index("V175") < versions.index("V177") < versions.index("V178")
    assert "V176" not in versions
    allow_list = json.dumps([pinned], separators=(",", ":"))
    workflow = (ROOT / ".github/workflows/promote-prod.yml").read_text(encoding="utf-8")
    guard = (ROOT / "tests/test_ci_guard.py").read_text(encoding="utf-8")
    assert workflow.count(allow_list) == 1
    assert allow_list in guard
    sql = migration.source
    assert sql.count("CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2") == 1
    assert _DML.search(sql) is None
    assert "GRANT" not in sql.replace("COPY GRANTS", "")
    assert "REVOKE" not in sql
    assert "QUERY_TEXT" not in sql.upper()
    assert "ERROR_MESSAGE" not in sql.upper()
    assert "{{ ENV }}" not in sql
    assert sql.count("{{ DATABASE }}") == 1


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
        expected_pending=[INTELLIGENCE_FEED_ENTRY_DATE_SORT_MIGRATION],
        protected_intelligence_prerequisite=protected,
    )
    return connection, executed


@pytest.mark.parametrize("database", [DEV_DATABASE, PROD_DATABASE])
def test_v178_requires_recorded_v175_and_the_protected_path(
    monkeypatch: pytest.MonkeyPatch, database: str
) -> None:
    loaded = load_migrations()
    v174 = next(item for item in loaded if item.version == "V174")
    v175 = next(item for item in loaded if item.version == "V175")
    v178 = next(item for item in loaded if item.version == "V178")
    with pytest.raises(PermissionError, match="V178 requires recorded V175"):
        _apply(
            monkeypatch,
            database,
            [v178],
            [("V174", v174.sha256)],
            protected=True,
        )
    with pytest.raises(PermissionError, match="protected intelligence prerequisite"):
        _apply(
            monkeypatch,
            database,
            [v178],
            [("V175", v175.sha256)],
            protected=False,
        )
    connection, executed_versions = _apply(
        monkeypatch,
        database,
        [v178],
        [("V175", v175.sha256)],
        protected=True,
    )
    assert executed_versions == ["V178"]
    executed = connection.execute_string.call_args.args[0]
    assert database in executed
    assert "{{ DATABASE }}" not in executed
    assert "COPY GRANTS" in executed
    assert _ENTRY_DATE in executed
    assert "CREATE TABLE" not in executed.upper()
    assert _DML.search(executed) is None
