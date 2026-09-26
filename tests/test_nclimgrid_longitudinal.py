"""Longitudinal month registration, inventory, and fail-closed coverage cases."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lyme_gap_atlas_data.ingestion.nclimgrid_coverage import (
    build_coverage_report,
    selected_successful_runs,
)
from lyme_gap_atlas_data.ingestion.nclimgrid_longitudinal import (
    batch_definition_specs,
    definition_mapping,
    months,
    scaled_inventory,
)
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
from lyme_gap_atlas_data.semantic_source_mappings import (
    SemanticMappingError,
    _bind_source,
    load_mapping_registry,
    nclimgrid_month_mapping_registry,
)

MAPPING_PATH = (
    Path(__file__).parents[1]
    / "docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json"
)


def test_month_semantic_mapping_keeps_exact_source_identity() -> None:
    original = load_mapping_registry(MAPPING_PATH)
    january_1951 = nclimgrid_month_mapping_registry(MAPPING_PATH, "195101")
    january_1988 = nclimgrid_month_mapping_registry(MAPPING_PATH, "198801")
    assert original["nclimgrid_prcp"]["resource_key"] == "noaa_nclimgrid_daily_202501"
    for identity in ("nclimgrid_prcp", "nclimgrid_tmin", "nclimgrid_tmax", "nclimgrid_tavg"):
        assert january_1951[identity]["resource_key"] == "noaa_nclimgrid_daily_195101"
        assert january_1951[identity]["vintage"] == "v1.0.0-scaled-195101"
        assert january_1951[identity]["measure_id"] == original[identity]["measure_id"]
    source = {
        "resource_key": "noaa_nclimgrid_daily_195101",
        "source_id": "noaa_nclimgrid_daily",
        "dataset_id": "nclimgrid-daily-v1.0.0-scaled",
        "source_vintage": "v1.0.0-scaled-195101",
        "definition_version": 2,
        "approved": True,
    }
    edge = {**source, "source_version_id": "195101"}
    _bind_source(edge, january_1951["nclimgrid_prcp"], {"source_versions": {"195101": source}})
    with pytest.raises(SemanticMappingError, match="resource_key"):
        _bind_source(edge, january_1988["nclimgrid_prcp"], {"source_versions": {"195101": source}})
    with pytest.raises(ValueError, match="outside"):
        nclimgrid_month_mapping_registry(MAPPING_PATH, "202609")


def test_frozen_months_are_ordered_and_month_pins_are_unique() -> None:
    selected = months()
    assert len(selected) == 908
    assert selected[0] == "195101" and selected[-1] == "202608"
    assert len(set(selected)) == len(selected)
    assert selected.index("198801") < selected.index("202501")
    with pytest.raises(ValueError, match="outside"):
        months("195001", "195101")
    with pytest.raises(ValueError, match="outside"):
        months("202609", "202609")


def test_batch_specs_are_bounded_and_reject_duplicate_registration(tmp_path: Path) -> None:
    assert batch_definition_specs("nclimgrid:195101..195103") == (
        "nclimgrid:195101",
        "nclimgrid:195102",
        "nclimgrid:195103",
    )
    with pytest.raises(ValueError, match="twelve"):
        batch_definition_specs("nclimgrid:195101..195202")
    path = tmp_path / "definitions.txt"
    path.write_text("nclimgrid:195101\nnclimgrid:195101\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        batch_definition_specs(str(path))


@pytest.mark.parametrize("month", ["195101", "198801", "202501", "202608"])
def test_generated_definition_uses_canonical_adapter_and_exact_month(month: str) -> None:
    definition = load_source_definition(f"nclimgrid:{month}")
    assert validate_source_definition(definition).ok
    assert definition.resource_key == f"noaa_nclimgrid_daily_{month}"
    assert definition.extra["year_month"] == month
    assert definition.endpoint_template.endswith(f"/{month[:4]}/ncdd-{month}-grd-scaled.nc")
    assert definition.extra["tiger_sha256"] == definition_mapping("202501")["tiger_sha256"]
    assert len(str(definition.extra["expected_grid_id"])) == 64
    assert len(str(definition.extra["source_definition_sha256"])) == 64
    assert definition.source_id == "noaa_nclimgrid_daily"


def test_longitudinal_definition_rejects_grid_pin_tampering() -> None:
    mapping = definition_mapping("198801")
    mapping["expected_grid_id"] = "0" * 64
    result = validate_source_definition(source_definition_from_mapping(mapping))
    assert not result.ok
    assert any(issue.code == "NCLIMGRID_LONGITUDINAL_GRID_PIN" for issue in result.issues)


def test_generated_definition_rejects_out_of_window_and_malformed_months() -> None:
    for month in ("195013", "195001", "202609", "202501;rm", "20251"):
        with pytest.raises(ValueError):
            load_source_definition(f"nclimgrid:{month}")


def test_live_inventory_detects_missing_and_duplicate_months(monkeypatch: Any) -> None:
    listing = (
        b'<a href="ncdd-202501-grd-scaled.nc">January</a>'
        b'<a href="ncdd-202501-grd-scaled.nc">duplicate</a>'
        b'<a href="ncdd-202503-grd-scaled.nc">March</a>'
    )

    class Response(io.BytesIO):
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            self.close()

    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.nclimgrid_longitudinal.urlopen",
        lambda *_args, **_kwargs: Response(listing),
    )
    result = scaled_inventory("202501", "202503")
    assert result["available_months"] == ["202501", "202503"]
    assert result["missing_months"] == ["202502"]
    assert result["duplicate_months"] == ["202501"]


def test_coverage_report_preserves_explicit_missing_months(tmp_path: Path) -> None:
    class EmptyStore:
        def list_runs(self) -> list[object]:
            return []

        def iter_partitions(self, _run_id: str) -> object:
            raise AssertionError("No run may be read")

    csv_path = tmp_path / "county.csv"
    report = build_coverage_report(EmptyStore(), start="202501", end="202502", county_csv=csv_path)  # type: ignore[arg-type]
    assert report["captured_month_count"] == 0
    assert report["not_attempted_months"] == ["202501", "202502"]
    assert report["unavailable_months"] == []
    assert report["captured_months_by_tier"] == {}
    assert report["months"][0]["attempted_tiers"] == []  # type: ignore[index]
    assert len(csv_path.read_text(encoding="utf-8").splitlines()) == 1


def test_coverage_report_rejects_cross_measure_source_support_drift(tmp_path: Path) -> None:
    run = RunState(
        "drift-run",
        "noaa_nclimgrid_daily_195101",
        2,
        Tier.A,
        RunStatus.SUCCEEDED,
        stages=[
            StageCheckpoint(
                stage=Stage.ACQUIRE,
                status=StageStatus.COMPLETED,
                artifact_sha256="noaa-digest",
            )
        ],
    )

    class Store:
        def list_runs(self) -> list[RunState]:
            return [run]

        def iter_partitions(self, _run_id: str) -> object:
            return iter(
                [
                    SimpleNamespace(
                        byte_count=100,
                        records=[
                            {
                                "record": {
                                    "county_fips": "01001",
                                    "observation_date": "1951-01-01",
                                    "measure": measure,
                                    "coverage_status": "COMPLETE",
                                    "noaa_sha256": "noaa-digest",
                                    "source_supported_area_m2": area,
                                    "source_coverage_fraction": 1.0,
                                }
                            }
                            for measure, area in (("PRCP", 10.0), ("TMIN", 9.0))
                        ],
                    )
                ]
            )

    with pytest.raises(ValueError, match="source support changed"):
        build_coverage_report(
            Store(), start="195101", end="195101", county_csv=tmp_path / "drift.csv"
        )  # type: ignore[arg-type]
    assert not (tmp_path / "drift.csv").exists()


def test_coverage_report_distinguishes_noaa_404_from_unattempted(tmp_path: Path) -> None:
    run = RunState(
        ingestion_run_id="unavailable-run",
        resource_key="noaa_nclimgrid_daily_195101",
        source_definition_version=2,
        tier=Tier.A,
        status=RunStatus.FAILED,
        stages=[
            StageCheckpoint(
                stage=Stage.ACQUIRE,
                status=StageStatus.FAILED,
                redacted_diagnostic_code="NCLIMGRID_UNAVAILABLE",
            )
        ],
    )

    class Store:
        def list_runs(self) -> list[RunState]:
            return [run]

        def iter_partitions(self, _run_id: str) -> object:
            raise AssertionError("Failed run partitions must not be read")

    report = build_coverage_report(
        Store(),
        start="195101",
        end="195102",
        county_csv=tmp_path / "county.csv",  # type: ignore[arg-type]
    )
    assert report["unavailable_months"] == ["195101"]
    assert report["not_attempted_months"] == ["195102"]
    assert report["months"][0]["attempted_tiers"] == ["A"]  # type: ignore[index]


@pytest.mark.parametrize(
    ("run_status", "month_status", "summary_field"),
    [
        (RunStatus.RUNNING, "IN_PROGRESS", "in_progress_months"),
        (RunStatus.POLICY_BLOCKED, "REVIEW_REQUIRED", "review_required_months"),
        (RunStatus.FAILED, "FAILED", "failed_months"),
    ],
)
def test_coverage_report_preserves_non_success_run_state(
    tmp_path: Path, run_status: RunStatus, month_status: str, summary_field: str
) -> None:
    run = RunState("run-1", "noaa_nclimgrid_daily_195101", 2, Tier.A, run_status)

    class Store:
        def list_runs(self) -> list[RunState]:
            return [run]

        def iter_partitions(self, _run_id: str) -> object:
            raise AssertionError("Unfinished run partitions must not be read")

    report = build_coverage_report(
        Store(),
        start="195101",
        end="195101",
        county_csv=tmp_path / "county.csv",  # type: ignore[arg-type]
    )
    assert report[summary_field] == ["195101"]
    assert report["months"][0]["status"] == month_status  # type: ignore[index]


def test_failed_recapture_does_not_replace_last_successful_month() -> None:
    def run(run_id: str, status: RunStatus, time: str) -> RunState:
        return RunState(
            run_id,
            "noaa_nclimgrid_daily_195101",
            2,
            Tier.A,
            status,
            stages=[
                StageCheckpoint(
                    stage=Stage.ACQUIRE,
                    status=StageStatus.COMPLETED,
                    completed_at=time,
                )
            ],
        )

    older = run("older", RunStatus.SUCCEEDED, "2026-01-01T00:00:00+00:00")
    newer = run("newer", RunStatus.SUCCEEDED, "2026-02-01T00:00:00+00:00")
    failed = run("failed", RunStatus.FAILED, "2026-03-01T00:00:00+00:00")
    assert selected_successful_runs([failed, newer, older]) == [older, newer]


def test_batch_skips_completed_month_and_resumes_failed_month(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    import lyme_gap_atlas_data.cli as cli

    definitions = tmp_path / "months.txt"
    definitions.write_text("nclimgrid:195101\nnclimgrid:195102\n", encoding="utf-8")
    completed = RunState(
        "run-january",
        "noaa_nclimgrid_daily_195101",
        2,
        Tier.A,
        RunStatus.SUCCEEDED,
        stages=[
            StageCheckpoint(
                stage=Stage.ACQUIRE,
                status=StageStatus.COMPLETED,
                detail={
                    "source_definition_sha256": definition_mapping("195101")[
                        "source_definition_sha256"
                    ]
                },
            )
        ],
    )
    failed = RunState("run-february", "noaa_nclimgrid_daily_195102", 2, Tier.A, RunStatus.FAILED)
    calls: list[str] = []

    class Store:
        def __init__(self, *_args: object) -> None:
            pass

        def list_runs(self) -> list[RunState]:
            return [completed, failed]

    class Orchestrator:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def validate(self, _definition: object) -> object:
            return type("Result", (), {"ok": True})()

        def run(self, *_args: object, **_kwargs: object) -> RunState:
            raise AssertionError("No new capture is expected")

        def resume(self, run_id: str, **_kwargs: object) -> RunState:
            calls.append(run_id)
            failed.status = RunStatus.SUCCEEDED
            return failed

    monkeypatch.setattr(cli, "FileCheckpointStore", Store)
    monkeypatch.setattr(cli, "IngestionOrchestrator", Orchestrator)
    cli.source_batch(str(definitions), "A", str(tmp_path), False)
    assert calls == ["run-february"]
    assert "skip_succeeded" in capsys.readouterr().out
