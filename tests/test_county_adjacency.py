"""Code-only Census 2025 county adjacency checks for issue #872."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from lyme_gap_atlas_data import migrations
from lyme_gap_atlas_data.county_adjacency import (
    EXPECTED_EDGE_PAIRS,
    EXPECTED_ISLANDS,
    EXPECTED_POINT_PAIRS,
    EXPECTED_UNDIRECTED_PAIRS,
    PINNED_SHA256,
    RELEASE_ID,
    RESOURCE_KEY,
    CountyAdjacencyError,
    apply_prepared_load,
    conform_published_rows,
    prepare_load,
    project_counties,
    quality_results,
)
from lyme_gap_atlas_data.ingestion.adapters import AcquisitionError, HttpCsvAdapter, _csv_rows
from lyme_gap_atlas_data.ingestion.runtime import _with_downloaded_adjacency_pin
from lyme_gap_atlas_data.ingestion.source_definition import (
    load_source_definition,
    source_definition_from_mapping,
    validate_source_definition,
)
from lyme_gap_atlas_data.ingestion.types import (
    RunState,
    RunStatus,
    Stage,
    StageCheckpoint,
    StageStatus,
    Tier,
)
from lyme_gap_atlas_data.migrations import (
    COUNTY_ADJACENCY_MIGRATION,
    DEV_DATABASE,
    DEV_ONLY_MIGRATION_VERSIONS,
    HELD_BACK_DEV_MIGRATION_VERSIONS,
    PROD_DATABASE,
    PROD_ONLY_MIGRATION_VERSIONS,
    load_migrations,
    migration_plan,
    render_migration,
)

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = ROOT / "config" / "sources" / "census_county_adjacency_2025.yml"
RUCC = ROOT / "config" / "sources" / "usda_ers_rucc_2023.yml"
WHEN = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
RUN_ID = "run-1"


def _row(
    county: str,
    neighbor: str,
    length: str,
    *,
    county_name: str = "Autauga County, AL",
    neighbor_name: str = "Chilton County, AL",
) -> dict[str, str]:
    if neighbor == "":
        neighbor_name = ""
        length = ""
    return {
        "County Name": county_name,
        "County GEOID": county,
        "Neighbor Name": neighbor_name,
        "Neighbor GEOID": neighbor,
        "Length": length,
    }


def _symmetric(left: str, right: str, length: str) -> list[dict[str, str]]:
    return [
        _row(left, right, length),
        _row(
            right,
            left,
            length,
            county_name="Chilton County, AL",
            neighbor_name="Autauga County, AL",
        ),
    ]


def _definition():
    return load_source_definition(DEFINITION)


class _Cursor:
    def __init__(self, fetches: list[list[tuple[str, ...]]]) -> None:
        self._fetches = list(fetches)
        self.calls: list[str] = []

    def execute(self, sql: str, _params: object = None) -> None:
        self.calls.append(sql)

    def fetchall(self) -> list[tuple[str, ...]]:
        return self._fetches.pop(0)


def test_http_csv_delimiter_defaults_to_comma_and_accepts_pipe(tmp_path: Path) -> None:
    comma = _csv_rows(b"FIPS,Attribute,Value\n01001,RUCC_2023,1\n", load_source_definition(RUCC))
    assert comma[0]["FIPS"] == "01001"
    body = (
        b"County Name|County GEOID|Neighbor Name|Neighbor GEOID|Length\n"
        b"Autauga County, AL|01001|||\n"
    )
    rows = _csv_rows(body, _definition())
    assert rows == [_row("01001", "", "")]
    (tmp_path / "sample.csv").write_bytes(body)
    acquired = HttpCsvAdapter().acquire(_definition(), fixture_dir=tmp_path)
    assert acquired.payload["sample"] == rows


def test_pipe_delimiter_keeps_commas_and_rejects_wide_rows() -> None:
    body = (
        b"County Name|County GEOID|Neighbor Name|Neighbor GEOID|Length\n"
        b"Autauga County, AL|01001|Chilton County, AL|01021|10\n"
    )
    definition = _definition()
    row = _csv_rows(body, definition)[0]
    assert row["County Name"] == "Autauga County, AL"
    assert row["Neighbor GEOID"] == "01021"
    comma = source_definition_from_mapping({**_document(), "delimiter": ","})
    with pytest.raises(AcquisitionError) as caught:
        _csv_rows(body, comma)
    assert caught.value.code == "MISSING_COLUMNS"
    wide = (
        b"County Name|County GEOID|Neighbor Name|Neighbor GEOID|Length\n"
        b"Autauga County, AL|01001|Chilton County, AL|01021|10|extra\n"
    )
    with pytest.raises(AcquisitionError) as width:
        _csv_rows(wide, definition)
    assert width.value.code == "ROW_WIDTH"
    invalid = source_definition_from_mapping({**_document(), "delimiter": "||"})
    assert any(issue.code == "DELIMITER" for issue in validate_source_definition(invalid).issues)


def test_source_definition_is_pinned() -> None:
    definition = _definition()
    result = validate_source_definition(definition)
    assert result.ok, result.to_dict()
    assert definition.extra["delimiter"] == "|"
    assert definition.extra["artifact_sha256"] == PINNED_SHA256
    assert definition.destination == "RAW.CENSUS_COUNTY_ADJACENCY_2025"
    drifted = source_definition_from_mapping({**_document(), "artifact_sha256": "a" * 64})
    assert any(
        issue.code == "ADJACENCY_SHA256" for issue in validate_source_definition(drifted).issues
    )


def test_structural_failures_and_islands() -> None:
    reference = frozenset({"01001", "01021", "15001"})
    rows = [*_symmetric("01001", "01021", "10"), _row("15001", "", "")]
    result = conform_published_rows(rows, reference=reference)
    assert [pair.fips_a + pair.fips_b for pair in result.pairs] == ["0100101021"]
    assert result.pairs[0].contact_type == "EDGE"
    assert result.islands == ("15001",)
    point = conform_published_rows(
        _symmetric("01001", "01021", "0"), reference=frozenset({"01001", "01021"})
    )
    assert point.pairs[0].contact_type == "POINT"
    assert point.edge_count == 0 and point.point_count == 1
    excluded = conform_published_rows(
        [*_symmetric("01001", "01021", "10"), *_symmetric("72001", "72003", "4")],
        reference=frozenset({"01001", "01021"}),
    )
    assert [pair.fips_a for pair in excluded.pairs] == ["01001"]
    with pytest.raises(CountyAdjacencyError, match="MISSING_COUNTY"):
        conform_published_rows(_symmetric("72001", "72003", "4"), reference=frozenset({"01001"}))
    with pytest.raises(CountyAdjacencyError, match="CROSS_SCOPE"):
        conform_published_rows(_symmetric("01001", "72001", "4"), reference=frozenset({"01001"}))
    with pytest.raises(CountyAdjacencyError, match="ASYMMETRIC_PAIR"):
        conform_published_rows(
            [_row("01001", "01021", "10")], reference=frozenset({"01001", "01021"})
        )
    with pytest.raises(CountyAdjacencyError, match="SELF_PAIR"):
        conform_published_rows([_row("01001", "01001", "1")], reference=frozenset({"01001"}))
    with pytest.raises(CountyAdjacencyError, match="FIPS_SHAPE"):
        conform_published_rows([_row("1001", "01021", "1")], reference=frozenset({"01001"}))
    with pytest.raises(CountyAdjacencyError, match="SHA256_MISMATCH"):
        prepare_load(
            rows,
            artifact_sha256="b" * 64,
            ingestion_run_id=RUN_ID,
            retrieved_at=WHEN,
            reference=reference,
        )
    assert excluded.pairs[0].fips_b == "01021"


def test_merge_is_keyed_and_idempotent() -> None:
    reference = frozenset({"01001", "01021"})
    rows = _symmetric("01001", "01021", "10")
    prepared = prepare_load(
        rows,
        artifact_sha256=PINNED_SHA256,
        ingestion_run_id=RUN_ID,
        retrieved_at=WHEN,
        reference=reference,
    )
    first = _Cursor([[], []])
    receipt = apply_prepared_load(first, prepared, environment="DEV")
    assert (receipt.inserted, receipt.updated, receipt.deleted) == (1, 0, 0)
    governed = "\n".join(sql for sql in first.calls if "CONFORMED.COUNTY_ADJACENCY" in sql)
    assert "MERGE INTO ONE_HEALTH_LYME_GAP_ATLAS_DEV.CONFORMED.COUNTY_ADJACENCY target" in governed
    assert "target.RELEASE_ID = source.RELEASE_ID" in governed
    assert "target.FIPS_A = source.FIPS_A" in governed
    assert "target.FIPS_B = source.FIPS_B" in governed
    assert "ONE_HEALTH_LYME_GAP_ATLAS_DEV.RAW.CENSUS_COUNTY_ADJACENCY_2025" in "\n".join(
        first.calls
    )
    existing_pair = [("01001", "01021", "10", "EDGE", "2025", PINNED_SHA256)]
    existing_raw = [
        ("01001", "01021", "Autauga County, AL", "Chilton County, AL", "10"),
        ("01021", "01001", "Chilton County, AL", "Autauga County, AL", "10"),
    ]
    second = _Cursor([existing_pair, existing_raw])
    again = apply_prepared_load(second, prepared, environment="PROD")
    assert (again.inserted, again.updated, again.deleted) == (0, 0, 0)
    assert again.pair_count == 1
    assert all(sql.startswith("SELECT ") for sql in second.calls)
    changed = _Cursor([[("01001", "01021", "0", "POINT", "2025", PINNED_SHA256)], existing_raw])
    updated = apply_prepared_load(changed, prepared, environment="DEV")
    assert (updated.inserted, updated.updated, updated.deleted) == (0, 1, 0)
    assert "WHEN MATCHED" in "\n".join(changed.calls)


def test_quality_reports_islands_and_rejects_bad_rows() -> None:
    definition = _definition()
    reference = frozenset({"01001", "01021", "15001"})
    rows = [*_symmetric("01001", "01021", "12"), _row("15001", "", "")]
    results = quality_results(definition, [{"record": row} for row in rows], reference=reference)
    assert [item["status"] for item in results] == ["PASSED"] * 6
    islands = next(item for item in results if item["rule_id"] == "census_adjacency_islands")
    assert islands["observed"] == {"islands": ["15001"], "stored_as_pairs": 0}
    failed = quality_results(
        definition,
        [{"record": _row("01001", "01021", "10")}],
        reference=frozenset({"01001", "01021"}),
    )
    assert failed[0]["rule_id"] == "census_adjacency_symmetry"
    assert failed[0]["observed"] == {"code": "ASYMMETRIC_PAIR"}
    state = RunState(
        ingestion_run_id=RUN_ID,
        resource_key=RESOURCE_KEY,
        source_definition_version=1,
        tier=Tier.A,
        status=RunStatus.RUNNING,
        dry_run=False,
        stages=[
            StageCheckpoint(
                stage=Stage.ACQUIRE,
                status=StageStatus.COMPLETED,
                artifact_sha256="c" * 64,
            )
        ],
    )
    pinned = _with_downloaded_adjacency_pin(definition, state, results)
    checksum = next(item for item in pinned if item["rule_id"] == "census_adjacency_checksum")
    assert checksum["status"] == "FAILED"
    assert checksum["observed"] == {"code": "SHA256_MISMATCH"}
    state.dry_run = True
    assert _with_downloaded_adjacency_pin(definition, state, results)[0]["status"] == "PASSED"


def test_release_counts_are_the_issue_values() -> None:
    assert RELEASE_ID == "census-county-adjacency-2025-8233d2ae"
    assert EXPECTED_UNDIRECTED_PAIRS == 9286
    assert EXPECTED_EDGE_PAIRS == 8938
    assert EXPECTED_POINT_PAIRS == 348
    assert frozenset({"15001", "15003", "15007"}) == EXPECTED_ISLANDS
    assert len(project_counties()) == 3144


def test_v177_is_the_next_free_migration_for_both_databases() -> None:
    pinned = COUNTY_ADJACENCY_MIGRATION
    migration = next(item for item in load_migrations() if item.version == "V177")
    assert migrations._migration_metadata(migration) == pinned
    digest = hashlib.sha256((ROOT / "migrations" / pinned["filename"]).read_bytes()).hexdigest()
    assert pinned["sha256"] == digest == migration.sha256
    versions = [item.version for item in load_migrations()]
    assert "V177" in versions
    assert "V178" in versions
    assert versions.index("V175") < versions.index("V177") < versions.index("V178")
    assert "V176" not in versions
    assert "V172" not in versions
    assert pinned["version"] not in DEV_ONLY_MIGRATION_VERSIONS
    assert pinned["version"] not in PROD_ONLY_MIGRATION_VERSIONS
    assert pinned["version"] not in HELD_BACK_DEV_MIGRATION_VERSIONS
    assert pinned in migration_plan(DEV_DATABASE)
    assert pinned in migration_plan(PROD_DATABASE)
    allow_list = json.dumps([pinned], separators=(",", ":"))
    workflow = (ROOT / ".github/workflows/promote-prod.yml").read_text(encoding="utf-8")
    guard = (ROOT / "tests/test_ci_guard.py").read_text(encoding="utf-8")
    assert workflow.count(allow_list) == 1
    assert allow_list in guard
    sql = migration.source.upper()
    for banned in ("GEOGRAPHY", "GEOMETRY", "GEOJSON", "QUERY_TEXT", "ERROR_MESSAGE"):
        assert banned not in sql
    assert "OH_LYME_PROD_ML_EDA_READ" not in migration.source
    assert "OH_LYME_ML_AGENT" not in migration.source
    assert migration.source.count("GRANT SELECT ON VIEW PRESENTATION.COUNTY_ADJACENCY_V1") == 1
    assert "OH_LYME_{{ ENV }}_READ" in migration.source
    assert "OH_LYME_{{ ENV }}_RUNTIME" in migration.source
    assert "MERGE " not in migration.source and "INSERT INTO" not in migration.source
    rendered = render_migration(migration, DEV_DATABASE)
    assert "ONE_HEALTH_LYME_GAP_ATLAS_DEV" in rendered
    assert "OH_LYME_DEV_READ" in rendered
    assert "{{ ENV }}" not in rendered and "{{ DATABASE }}" not in rendered


def test_v177_apply_uses_the_reviewed_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = next(item for item in load_migrations() if item.version == "V177")
    monkeypatch.setattr(migrations, "load_migrations", lambda: [migration])
    cursor = Mock()
    cursor.fetchall.return_value = []
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *_args, **_kwargs: nullcontext(connection))
    applied = migrations.apply_migrations(
        Mock(),
        DEV_DATABASE,
        expected_pending=[COUNTY_ADJACENCY_MIGRATION],
    )
    assert applied == ["V177"]
    fake = migrations.Migration("V177", migration.filename, "SELECT 1;\n", "b" * 64)
    monkeypatch.setattr(migrations, "load_migrations", lambda: [fake])
    with pytest.raises(PermissionError, match="reviewed county adjacency migration pin"):
        migrations.apply_migrations(
            Mock(),
            PROD_DATABASE,
            expected_pending=[migrations._migration_metadata(fake)],
        )


@pytest.mark.skipif(
    not os.environ.get("COUNTY_ADJACENCY_2025_PATH"),
    reason="pinned Census file is not part of the repository",
)
def test_pinned_file_matches_issue_counts() -> None:
    path = Path(os.environ["COUNTY_ADJACENCY_2025_PATH"])
    body = path.read_bytes()
    assert hashlib.sha256(body).hexdigest() == PINNED_SHA256
    rows = _csv_rows(body, _definition())
    result = conform_published_rows(rows, reference=project_counties())
    assert len(result.pairs) == EXPECTED_UNDIRECTED_PAIRS
    assert result.edge_count == EXPECTED_EDGE_PAIRS
    assert result.point_count == EXPECTED_POINT_PAIRS
    assert frozenset(result.islands) == EXPECTED_ISLANDS


def _document() -> dict[str, object]:
    document = yaml.safe_load(DEFINITION.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document
