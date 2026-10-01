"""Candidate climate projection against the real ingestion revision writer.

All rows below are labeled offline fixtures; they are not live capture proof.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from lyme_gap_atlas_data import climate_publication as publication
from lyme_gap_atlas_data.ingestion.runtime import _insert_revisions, _lineage_rows
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.ingestion.types import (
    RunState,
    RunStatus,
    Stage,
    StageCheckpoint,
    StageStatus,
    Tier,
)

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = load_source_definition(ROOT / "config/sources/noaa_nclimgrid_daily_202501.yml")
KEYS = (
    "capture_record_id",
    "record_revision",
    "record_id",
    "source_id",
    "dataset_id",
    "resource_key",
    "source_definition_version",
    "ingestion_run_id",
    "source_record_id",
    "artifact_id",
    "artifact_sha256",
    "source_row_hash",
    "normalized_sha256",
    "transformation_version",
    "payload",
    "retrieved_at",
    "observed_at",
)


class RevisionCursor:
    inserted: tuple[Any, ...] = ()

    def execute(self, sql: str, parameters: tuple[Any, ...]) -> None:
        if sql.startswith("MERGE"):
            self.inserted = parameters

    def fetchall(self) -> list[Any]:
        return []


def fixture_record(**changes: Any) -> dict[str, Any]:
    record = {
        "id": "fixture:01001:2025-01-01:PRCP",
        "county_fips": "01001",
        "observation_date": "2025-01-01",
        "source_year_month": "202501",
        "source_time_present": True,
        "measure": "PRCP",
        "source_variable": "prcp",
        "value": 0.0,
        "unit": "mm",
        "source_unit": "millimeter",
        "coverage_status": "COMPLETE",
        "expected_area_m2": 100.0,
        "intersected_area_m2": 100.0,
        "source_supported_area_m2": 60.0,
        "valid_area_m2": 60.0,
        "source_coverage_fraction": 0.6,
        "valid_fraction_of_supported_area": 1.0,
        "grid_id": "fixture-grid",
        "grid_crs": "EPSG:4326",
        "weight_id": "fixture-weight",
        "weight_version": "atlas-grid-county-area-weight/1",
        "geometry_version": "fixture-geometry/1",
        "geometry_digest": "a" * 64,
        "noaa_sha256": publication.NOAA_SHA,
        "tiger_sha256": publication.TIGER_SHA,
        "noaa_member_name": "noaa-scaled-monthly-netcdf",
        "tiger_member_name": "tiger-2025-analysis-county-zip",
        "noaa_product_version": "v1-0-0 fixture",
        "upstream_date_modified": "2025-04-05",
        "transformation_version": "atlas-nclimgrid-county-day/2",
        "trace_state": "NOT_REPRESENTED",
    }
    return record | changes


def fixture_capture(record: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = {
        "id": "fixture",
        "source_id": DEFINITION.source_id,
        "dataset_id": DEFINITION.dataset_id,
        "source_definition_version": DEFINITION.definition_version,
        "geography_semantics": DEFINITION.geography_semantics,
        "temporal_semantics": DEFINITION.temporal_semantics,
        "record": record or fixture_record(),
    }
    state = RunState(
        publication.RUN_ID,
        DEFINITION.resource_key,
        2,
        Tier.B,
        RunStatus.SUCCEEDED,
        [
            StageCheckpoint(
                Stage.ACQUIRE, StageStatus.COMPLETED, completed_at="2026-09-28T02:59:48+00:00"
            )
        ],
    )
    cursor = RevisionCursor()
    _insert_revisions(
        cursor,
        _lineage_rows(DEFINITION, state, [normalized]),
        publication.NOAA_ARTIFACT_ID,
        publication.NOAA_SHA,
        "simplified-ingestion-v2",
    )
    return dict(zip(KEYS, cursor.inserted, strict=True))


def test_real_writer_zero_and_small_source_footprint_are_preserved() -> None:
    projected = publication.project_capture_record(fixture_capture())
    assert projected["value"] == 0 and projected["value_state"] == "ZERO"
    assert projected["source_coverage_fraction"] == 0.6
    assert projected["valid_fraction_of_supported_area"] == 1.0
    assert projected["source_published_at"] is None
    assert projected["publication_status"] == "CANDIDATE_NOT_RELEASED"
    assert "release_id" not in projected
    assert projected["atlas_acquired_at"] == "2026-09-28T02:59:48+00:00"


def test_geometry_relative_tolerance_matches_producer() -> None:
    record = fixture_record(
        expected_area_m2=1e9,
        intersected_area_m2=1e9 + 5,
        source_supported_area_m2=1e9,
        valid_area_m2=1e9,
        source_coverage_fraction=1.0,
    )
    assert publication.project_capture_record(fixture_capture(record))["value_state"] == "ZERO"
    record["intersected_area_m2"] = 1e9 + 11
    with pytest.raises(publication.ClimatePublicationBlocked, match="AREAS"):
        publication.project_capture_record(fixture_capture(record))


def test_equivalent_session_offsets_produce_identical_candidate_bytes() -> None:
    capture = fixture_capture()
    capture["retrieved_at"] = "2026-09-27T19:59:48-07:00"
    offset_projection = publication.project_capture_record(capture)
    capture["retrieved_at"] = datetime.fromisoformat("2026-09-28T02:59:48+00:00")
    utc_projection = publication.project_capture_record(capture)
    assert (
        json.dumps(offset_projection, sort_keys=True).encode()
        == json.dumps(utc_projection, sort_keys=True).encode()
    )


@pytest.mark.parametrize("status,valid", [("PARTIAL_COVERAGE", 30.0), ("SOURCE_MISSING", 0.0)])
def test_missing_states_remain_distinguishable(status: str, valid: float) -> None:
    capture = fixture_capture(
        fixture_record(
            value=None,
            coverage_status=status,
            valid_area_m2=valid,
            valid_fraction_of_supported_area=valid / 60,
        )
    )
    projected = publication.project_capture_record(capture)
    assert projected["value"] is None and projected["value_state"] == "MISSING"
    assert projected["coverage_status"] == status


def test_outside_noaa_coverage_is_unavailable_not_missing_or_zero() -> None:
    record = fixture_record(
        county_fips="02013",
        value=None,
        coverage_status="OUT_OF_SOURCE_COVERAGE",
        expected_area_m2=None,
        intersected_area_m2=None,
        source_supported_area_m2=None,
        valid_area_m2=0,
        source_coverage_fraction=None,
        valid_fraction_of_supported_area=None,
        weight_id=None,
    )
    projected = publication.project_capture_record(fixture_capture(record))
    assert projected["value_state"] == "UNAVAILABLE" and projected["value"] is None


def test_negative_temperature_and_source_supplied_tavg() -> None:
    record = fixture_record(
        measure="TAVG",
        source_variable="tavg",
        unit="degree_Celsius",
        source_unit="degree_Celsius",
        value=-8.5,
    )
    projected = publication.project_capture_record(fixture_capture(record))
    assert projected["value"] == -8.5 and projected["value_state"] == "OBSERVED"
    assert projected["measure_id"] == "nclimgrid_tavg_county_day"


@pytest.mark.parametrize(
    "change",
    [
        {"value": None},
        {"value": False},
        {"value": float("nan")},
        {"value": -1},
        {"unit": "inches"},
        {"observation_date": "2025-02-01"},
        {"observation_date": "20250101"},
        {"county_fips": "99999"},
        {"source_year_month": "200801"},
        {"coverage_status": "UNKNOWN"},
        {"source_time_present": False},
        {"source_time_present": "false"},
        {"valid_fraction_of_supported_area": 0.2},
        {"source_coverage_fraction": 1.0},
        {"transformation_version": "atlas-nclimgrid-county-day/1"},
        {"noaa_sha256": "b" * 64},
        {"tiger_sha256": "b" * 64},
        {"noaa_product_version": "v2-0-0"},
        {"measure": "TAVG", "source_variable": "derived"},
        {"expected_area_m2": 0},
        {"valid_area_m2": 150},
        {"value": 1, "coverage_status": "PARTIAL_COVERAGE"},
        {"weight_id": None},
        {"weight_version": "atlas-county-raster-weights/1"},
        {"weight_version": None},
    ],
)
def test_invalid_content_rehashed_by_writer_still_fails_scientific_gate(
    change: dict[str, Any],
) -> None:
    with pytest.raises(publication.ClimatePublicationBlocked):
        publication.project_capture_record(fixture_capture(fixture_record(**change)))


@pytest.mark.parametrize(
    "field",
    [
        "record_id",
        "record_revision",
        "capture_record_id",
        "normalized_sha256",
        "source_row_hash",
        "ingestion_run_id",
        "artifact_sha256",
        "artifact_id",
        "source_id",
    ],
)
def test_lineage_corruption_or_relabel_cannot_be_published(field: str) -> None:
    capture = fixture_capture()
    capture[field] = "wrong"
    with pytest.raises(publication.ClimatePublicationBlocked):
        publication.project_capture_record(capture)


def test_private_and_unregistered_fields_never_enter_projection() -> None:
    capture = fixture_capture(fixture_record(private_uri="secret", extra_value="secret"))
    capture["artifact_uri"] = "secret"
    projected = publication.project_capture_record(capture)
    assert "secret" not in json.dumps(projected)
    assert "payload" not in projected and "artifact_id" not in projected


@pytest.mark.parametrize("value", [None, "bad", datetime(2025, 1, 1)])
def test_retrieval_time_must_be_real_and_timezone_aware(value: Any) -> None:
    capture = fixture_capture()
    capture["retrieved_at"] = value
    with pytest.raises(publication.ClimatePublicationBlocked):
        publication.project_capture_record(capture)


def test_partial_or_duplicate_export_preserves_existing_artifact(tmp_path: Path) -> None:
    output = tmp_path / "candidate.ndjson"
    output.write_text("previous approved artifact", encoding="utf-8")
    for captures in ([], [fixture_capture()], [fixture_capture(), fixture_capture()]):
        with pytest.raises(publication.ClimatePublicationBlocked):
            publication.write_candidate_projection(captures, output)
        assert output.read_text(encoding="utf-8") == "previous approved artifact"
        assert list(tmp_path.iterdir()) == [output]


def test_complete_fixture_scope_is_atomic_and_reproducible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Shrink only the immutable test universe, not any production function argument.
    monkeypatch.setattr(publication, "COUNTIES", frozenset({"01001"}))

    def captures() -> Any:
        for day in range(1, 32):
            for measure, unit in sorted(publication.MEASURES.items()):
                yield fixture_capture(
                    fixture_record(
                        id=f"fixture:{day}:{measure}",
                        observation_date=f"2025-01-{day:02}",
                        measure=measure,
                        source_variable=measure.lower(),
                        unit=unit,
                        source_unit="millimeter" if measure == "PRCP" else unit,
                    )
                )

    first = publication.write_candidate_projection(captures(), tmp_path / "first.ndjson")
    second = publication.write_candidate_projection(captures(), tmp_path / "second.ndjson")
    assert first == second and first["rows"] == 124
    assert (tmp_path / "first.ndjson").read_bytes() == (tmp_path / "second.ndjson").read_bytes()


def test_full_production_counties_are_frozen_and_reader_query_is_bounded() -> None:
    assert len(publication.COUNTIES) == 3144
    assert publication.CAPTURE_QUERY.strip().startswith("SELECT")
    assert "WHERE ingestion_run_id = %s" in publication.CAPTURE_QUERY
    assert "ORDER BY" in publication.CAPTURE_QUERY
    assert "artifact_uri" not in publication.CAPTURE_QUERY.lower()


class ReadCursor:
    def __init__(self, *, identity: tuple[str, ...] | None = None, corrupt: int = -1) -> None:
        self.identity = identity or (
            "OH_LYME_DEV_PIPELINE_SVC",
            "OH_LYME_DEV_RUNTIME",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "OH_LYME_DEV_INGEST_XS_WH",
        )
        self.calls: list[str] = []
        self.corrupt = corrupt
        self.description = [(name,) for name in fixture_capture()]
        self.sent = False

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> None:
        assert sql.strip().startswith("SELECT")
        self.calls.append(sql)
        if parameters:
            assert parameters == (publication.RUN_ID,)

    def fetchone(self) -> tuple[str, ...]:
        return self.identity

    def fetchall(self) -> list[Any]:
        if len(self.calls) == self.corrupt:
            return []
        return {
            2: [(publication.RESOURCE_KEY, "COMPLETED")],
            3: [(publication.NOAA_SHA, 61013299), (publication.TIGER_SHA, 83989800)],
            4: [
                (stage, "COMPLETED")
                for stage in (
                    "ACQUIRE",
                    "VALIDATE",
                    "NORMALIZE",
                    "LOAD",
                    "QUALITY",
                    "PUBLISH_STAGE",
                )
            ],
            5: [(1560,)],
            6: [(1560, 389856, 0, 1559, 1560)],
        }[len(self.calls)]

    def fetchmany(self, size: int) -> list[Any]:
        assert size == 1000
        if self.sent:
            return []
        self.sent = True
        return [tuple(fixture_capture().values())]


@pytest.mark.parametrize(
    "role,database",
    [
        ("ACCOUNTADMIN", "ONE_HEALTH_LYME_GAP_ATLAS_DEV"),
        ("OH_LYME_DEV_OWNER", "ONE_HEALTH_LYME_GAP_ATLAS_DEV"),
        ("OH_LYME_DEV_READ", "ONE_HEALTH_LYME_GAP_ATLAS_DEV"),
        ("OH_LYME_PROD_RUNTIME", "ONE_HEALTH_LYME_GAP_ATLAS_PROD"),
    ],
)
def test_context_gate_runs_before_any_private_read_or_file_write(
    tmp_path: Path, role: str, database: str
) -> None:
    cursor = ReadCursor(
        identity=("OH_LYME_DEV_PIPELINE_SVC", role, database, "OH_LYME_DEV_INGEST_XS_WH")
    )
    with pytest.raises(publication.ClimatePublicationBlocked, match="RUNTIME_IDENTITY"):
        publication.prepare_candidate(cursor, tmp_path / "candidate")
    assert len(cursor.calls) == 1 and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("corrupt", [2, 3, 4, 5, 6])
def test_ledger_gates_stop_before_projection(tmp_path: Path, corrupt: int) -> None:
    cursor = ReadCursor(corrupt=corrupt)
    with pytest.raises(publication.ClimatePublicationBlocked):
        publication.prepare_candidate(cursor, tmp_path / "candidate")
    assert len(cursor.calls) == corrupt and list(tmp_path.iterdir()) == []


def test_reader_without_complete_capture_cannot_emit_a_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lyme_gap_atlas_data.ingestion.checkpoints import SnowflakeCheckpointStore

    monkeypatch.setattr(SnowflakeCheckpointStore, "iter_partitions", lambda self, run: iter(()))
    cursor = ReadCursor()
    with pytest.raises(publication.ClimatePublicationBlocked, match="INCOMPLETE_CAPTURE"):
        publication.prepare_candidate(cursor, tmp_path / "candidate")
    assert len(cursor.calls) == 6 and list(tmp_path.iterdir()) == []


def test_candidate_evidence_repeats_frozen_reader_and_emits_only_bounded_safe_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(publication, "COUNTIES", frozenset({"01001"}))
    reads: list[Path] = []

    def read(output: Path) -> dict[str, Any]:
        reads.append(output)
        captures = (
            fixture_capture(
                fixture_record(
                    observation_date=f"2025-01-{day:02}",
                    measure=measure,
                    source_variable=measure.lower(),
                    unit=unit,
                    source_unit="millimeter" if measure == "PRCP" else unit,
                    value=0 if measure == "PRCP" else -2,
                )
            )
            for day in range(1, 32)
            for measure, unit in sorted(publication.MEASURES.items())
        )
        return publication.write_candidate_projection(captures, output)

    monkeypatch.setattr(publication, "create_candidate", read)
    evidence = publication.candidate_evidence(tmp_path)
    assert len(reads) == 2
    assert evidence["capture_run_id"] == publication.RUN_ID
    assert evidence["projection_sha256"] == evidence["repeat_projection_sha256"]
    assert evidence["coverage_value_state_counts"] == {"COMPLETE:ZERO": 31, "COMPLETE:OBSERVED": 93}
    assert len(evidence["examples"]) == 2 and evidence["writes_performed"] is False
    assert all(len(example) == 7 for example in evidence["examples"].values())
    assert "payload" not in json.dumps(evidence) and "artifact_uri" not in json.dumps(evidence)


def test_candidate_evidence_rejects_changed_second_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = iter([{"projection_sha256": "a"}, {"projection_sha256": "b"}])
    monkeypatch.setattr(publication, "create_candidate", lambda output: next(reports))
    with pytest.raises(publication.ClimatePublicationBlocked, match="NONREPEATABLE_CANDIDATE"):
        publication.candidate_evidence(tmp_path)


def test_candidate_workflow_reuses_protected_read_only_envelope() -> None:
    workflow = (ROOT / ".github/workflows/run-ingestion.yml").read_text(encoding="utf-8")
    assert 'test "$MEASUREMENT_RUN_ID" = "c2eb2146-005d-44d2-bac4-e2805ca42577"' in workflow
    assert 'test "${{ inputs.recapture }}" = "false"' in workflow
    assert 'test "${{ inputs.publish }}" = "false"' in workflow
    block = workflow.rsplit(
        'if [ "${{ inputs.operation }}" = "nclimgrid-pilot-measurement" ]; then', 1
    )[1]
    block = block.split('elif [ "${{ inputs.operation }}" = "run" ]; then', 1)[0]
    assert "atlas-data source nclimgrid-pilot-measure" in block
    assert "source run" not in block and "resume" not in block


def test_candidate_dispatch_rejects_other_run_before_read(monkeypatch: pytest.MonkeyPatch) -> None:
    from lyme_gap_atlas_data.ingestion import nclimgrid_pilot_measurement as measurement

    monkeypatch.setattr(
        publication, "candidate_evidence", lambda output: pytest.fail("private read")
    )
    with pytest.raises(measurement.MeasurementError, match="approved January capture"):
        measurement.candidate_report("another-run")


def test_candidate_dispatch_uses_runner_temp_and_removes_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lyme_gap_atlas_data.ingestion import nclimgrid_pilot_measurement as measurement

    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("GITHUB_SHA", "reviewed-code-sha")

    def evidence(directory: Path) -> dict[str, Any]:
        assert directory.parent == tmp_path
        (directory / "fixture.ndjson").write_text("offline fixture", encoding="utf-8")
        return {"projection_sha256": "fixture-digest"}

    monkeypatch.setattr(publication, "candidate_evidence", evidence)
    assert measurement.candidate_report(publication.RUN_ID)["code_sha"] == "reviewed-code-sha"
    assert list(tmp_path.iterdir()) == []


def test_encoding_diagnostic_distinguishes_numeric_representation_without_exposing_values() -> None:
    from types import SimpleNamespace

    capture = fixture_capture()
    original = json.loads(capture["payload"])
    returned = json.loads(capture["payload"])
    returned["record"]["value"] = 0  # Model a distinct JSON number representation.
    capture["payload"] = returned
    partitions = [SimpleNamespace(records=[original], partition_id="verified-fixture")]
    partitions += [SimpleNamespace(records=[], partition_id="empty-fixture")] * 1559
    report = publication.compare_capture_encoding(capture, partitions)
    assert report["stored_source_sha256"] == report["partition_source_sha256"]
    assert report["stored_source_sha256"] != report["revision_source_sha256"]
    assert report["records_equal"] is True
    assert report["differing_fields"] == [
        {"field": "value", "partition_type": "float", "revision_type": "int"}
    ]
    assert "payload" not in report and "record" not in report
    with pytest.raises(publication.ClimatePublicationBlocked, match="SOURCE_HASH"):
        publication.project_capture_record(capture)


def test_diagnostic_dispatch_rejects_other_run_before_read(monkeypatch: pytest.MonkeyPatch) -> None:
    from lyme_gap_atlas_data.ingestion import nclimgrid_pilot_measurement as measurement

    monkeypatch.setattr(measurement, "_identity", lambda: pytest.fail("private read"))
    with pytest.raises(measurement.MeasurementError, match="approved January capture"):
        measurement.candidate_diagnostic("another-run")


def test_reconciliation_restores_only_verified_canonical_representation() -> None:
    capture = fixture_capture()
    original = json.loads(capture["payload"])
    returned = json.loads(capture["payload"])
    returned["record"]["value"] = 0
    returned["record"]["valid_fraction_of_supported_area"] = 1
    capture["payload"] = returned
    reconciled = publication.reconcile_capture(capture, original)
    assert reconciled["payload"] == publication.canonical_source_row(original)
    assert publication.project_capture_record(reconciled)["value_state"] == "ZERO"


@pytest.mark.parametrize(
    "left,right,equal",
    [
        (0.0, 0, True),
        (1.0, 1, True),
        (-2.0, -2, True),
        (True, 1, False),
        (False, 0.0, False),
        (1.0000000000000002, 1, False),
        (float(2**53), 2**53 + 1, False),
        (float("nan"), float("nan"), False),
        (float("inf"), float("inf"), False),
        ({"a": None}, {}, False),
        ([1], [1, 2], False),
        ("1", 1, False),
        ({"a": True}, {"a": 1}, False),
    ],
)
def test_content_equivalence_is_exact_and_preserves_structure(
    left: Any, right: Any, equal: bool
) -> None:
    assert publication.content_equivalent(left, right) is equal


@pytest.mark.parametrize(
    "field", ["source_row_hash", "normalized_sha256", "record_revision", "record_id"]
)
def test_reconciliation_keeps_every_original_hash_and_identity_gate(field: str) -> None:
    capture = fixture_capture()
    original = json.loads(capture["payload"])
    capture[field] = "b" * 64
    with pytest.raises(publication.ClimatePublicationBlocked):
        publication.reconcile_capture(capture, original)


def test_reconciliation_rejects_real_content_change() -> None:
    capture = fixture_capture()
    original = json.loads(capture["payload"])
    returned = json.loads(capture["payload"])
    returned["record"]["value"] = 1
    capture["payload"] = returned
    with pytest.raises(publication.ClimatePublicationBlocked, match="REVISION_CONTENT"):
        publication.reconcile_capture(capture, original)


@pytest.mark.parametrize("mode", ["missing", "duplicate", "unmatched"])
def test_batch_reconciliation_fails_closed_without_emitting_output(
    tmp_path: Path, mode: str
) -> None:
    from types import SimpleNamespace

    capture = fixture_capture()
    original = json.loads(capture["payload"])

    class Cursor:
        description = [(field,) for field in capture]

        def execute(self, sql: str, parameters: tuple[Any, ...]) -> None:
            assert sql.startswith("SELECT")
            assert parameters == (publication.RUN_ID, capture["record_id"])

        def fetchall(self) -> list[Any]:
            if mode == "missing":
                return []
            if mode == "duplicate":
                return [tuple(capture.values())] * 2
            changed = dict(capture) | {"record_id": "other"}
            return [tuple(changed.values())]

    partition = SimpleNamespace(ordinal=0, records=[original])
    with pytest.raises(publication.ClimatePublicationBlocked):
        publication.project_verified_partitions(Cursor(), [partition], tmp_path / "candidate")
    assert list(tmp_path.iterdir()) == []
