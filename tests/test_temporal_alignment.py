"""Data #431: timing metadata cannot turn hindsight into a point-in-time input."""

from copy import deepcopy

import pytest

from lyme_gap_atlas_data.temporal_alignment import (
    CONTRACT_VERSION,
    TemporalAlignmentError,
    evaluate_alignment,
    project_temporal_alignment,
)

EVIDENCE = "https://example.org/synthetic-timing-fixture"


def window(start: str, end: str) -> dict[str, str]:
    return {"start": start, "end_exclusive": end, "calendar": "GREGORIAN", "timezone": "UTC"}


def spec() -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "method_id": "declared-context-window",
        "method_version": "1.0.0",
        "source_id": "synthetic-source",
        "measure_id": "county-context",
        "source_version_id": "synthetic-version",
        "source_vintage": "synthetic-vintage",
        "revision_id": "synthetic-revision",
        "observation_window": window("2025-01-01", "2025-02-01"),
        "target_window": window("2025-02-01", "2025-03-01"),
        "lag": {"kind": "FIXED", "anchor": "START", "offset_days": 31},
        "rationale_reference": EVIDENCE,
        "aggregation": {
            "rule": "MEAN",
            "denominator": "valid_source_days",
            "coverage": {
                "expected": 31,
                "observed": 31,
                "unit": "DAYS",
                "partial_allowed": False,
            },
        },
        "availability": {
            "first_published_at": "2025-02-01T00:00:00Z",
            "first_publication_reference": EVIDENCE,
            "revision_available_at": "2025-02-01T00:00:00Z",
            "revision_reference": EVIDENCE,
            "complete_at": "2025-02-01T00:00:00Z",
            "completeness_reference": EVIDENCE,
            "retrieved_at": "2025-02-02T00:00:00Z",
            "source_modified_at": "2025-02-01T00:00:00Z",
        },
        "decision_cutoff": "2025-02-01T00:00:00Z",
        "limitations": ["Synthetic contract fixture; no scientific lag is selected."],
    }


def outcome(candidate: dict[str, object]) -> str:
    return str(evaluate_alignment(candidate)["disposition"])


def test_fixed_prior_period_with_proven_timing_is_eligible() -> None:
    candidate = spec()
    original = deepcopy(candidate)
    assert outcome(candidate) == "ELIGIBLE"
    assert candidate == original


def test_zero_lag_is_explicit_and_same_period_only() -> None:
    candidate = spec()
    candidate["target_window"] = window("2025-01-01", "2025-02-01")
    candidate["lag"] = {"kind": "ZERO", "anchor": "START", "offset_days": 0}
    candidate["rationale_reference"] = None
    assert outcome(candidate) == "ELIGIBLE"
    del candidate["lag"]
    with pytest.raises(TemporalAlignmentError, match="lag must be a mapping"):
        evaluate_alignment(candidate)


def test_rolling_window_requires_exact_declared_length() -> None:
    candidate = spec()
    candidate["lag"] = {"kind": "ROLLING", "anchor": "START", "offset_days": 31, "window_days": 31}
    assert outcome(candidate) == "ELIGIBLE"
    candidate["lag"]["window_days"] = 30  # type: ignore[index]
    with pytest.raises(TemporalAlignmentError, match="rolling window_days"):
        evaluate_alignment(candidate)


def test_cross_year_season_and_leap_day_use_actual_calendar_days() -> None:
    candidate = spec()
    candidate["observation_window"] = window("2023-12-01", "2024-03-01")
    candidate["target_window"] = window("2024-06-01", "2024-09-01")
    candidate["lag"] = {
        "kind": "SEASONAL",
        "anchor": "START",
        "offset_days": 183,
        "season_id": "synthetic-winter-to-summer",
    }
    candidate["aggregation"]["coverage"] = {  # type: ignore[index]
        "expected": 91,
        "observed": 91,
        "unit": "DAYS",
        "partial_allowed": False,
    }
    assert outcome(candidate) == "ELIGIBLE"
    candidate["aggregation"]["coverage"]["expected"] = 90  # type: ignore[index]
    candidate["aggregation"]["coverage"]["observed"] = 90  # type: ignore[index]
    with pytest.raises(TemporalAlignmentError, match="every calendar day"):
        evaluate_alignment(candidate)


def test_previous_year_human_label_is_not_available_on_january_first() -> None:
    candidate = spec()
    candidate["source_id"] = "synthetic-cdc-reported-label"
    candidate["aggregation"]["coverage"] = {  # type: ignore[index]
        "expected": 1,
        "observed": 1,
        "unit": "RECORDS",
        "partial_allowed": False,
    }
    candidate["observation_window"] = window("2023-01-01", "2024-01-01")
    candidate["target_window"] = window("2024-01-01", "2025-01-01")
    candidate["lag"] = {"kind": "FIXED", "anchor": "START", "offset_days": 365}
    candidate["decision_cutoff"] = "2024-01-01T00:00:00Z"
    candidate["availability"]["first_published_at"] = "2024-05-01T00:00:00Z"  # type: ignore[index]
    assert outcome(candidate) == "INELIGIBLE"


def test_monthly_climate_cannot_use_incomplete_future_month() -> None:
    candidate = spec()
    candidate["source_id"] = "synthetic-monthly-nclimgrid"
    candidate["decision_cutoff"] = "2025-01-31T12:00:00Z"
    assert outcome(candidate) == "INELIGIBLE"


def test_revised_climate_snapshot_cannot_enter_earlier_cutoff() -> None:
    candidate = spec()
    candidate["source_id"] = "synthetic-revised-nclimgrid"
    candidate["availability"]["revision_available_at"] = "2025-03-01T00:00:00Z"  # type: ignore[index]
    assert outcome(candidate) == "INELIGIBLE"


def test_future_nlcd_vintage_cannot_be_back_projected() -> None:
    candidate = spec()
    candidate["source_id"] = "synthetic-annual-nlcd"
    candidate["aggregation"]["coverage"] = {  # type: ignore[index]
        "expected": 1,
        "observed": 1,
        "unit": "RECORDS",
        "partial_allowed": False,
    }
    candidate["source_vintage"] = "2025"
    candidate["observation_window"] = window("2025-01-01", "2026-01-01")
    candidate["target_window"] = window("2026-01-01", "2027-01-01")
    candidate["lag"] = {"kind": "FIXED", "anchor": "START", "offset_days": 365}
    candidate["decision_cutoff"] = "2024-12-31T00:00:00Z"
    assert outcome(candidate) == "INELIGIBLE"


def test_modis_composite_requires_declared_source_coverage() -> None:
    candidate = spec()
    candidate["source_id"] = "synthetic-modis-composite"
    candidate["aggregation"]["coverage"] = {  # type: ignore[index]
        "expected": 2,
        "observed": 1,
        "unit": "COMPOSITES",
        "partial_allowed": False,
    }
    assert outcome(candidate) == "INELIGIBLE"
    candidate["aggregation"]["coverage"]["partial_allowed"] = True  # type: ignore[index]
    with pytest.raises(TemporalAlignmentError, match="coverage.policy_reference"):
        evaluate_alignment(candidate)


def test_partial_support_requires_explicit_source_policy() -> None:
    candidate = spec()
    candidate["aggregation"]["coverage"] = {  # type: ignore[index]
        "expected": 100,
        "observed": 75,
        "unit": "SOURCE_SUPPORTED_AREA",
        "partial_allowed": True,
        "policy_reference": EVIDENCE,
    }
    assert outcome(candidate) == "ELIGIBLE"
    candidate["aggregation"]["coverage"]["observed"] = 0  # type: ignore[index]
    assert outcome(candidate) == "INELIGIBLE"


def test_anomaly_reference_cannot_extend_past_cutoff() -> None:
    candidate = spec()
    candidate["aggregation"]["rule"] = "ANOMALY"  # type: ignore[index]
    candidate["reference_period"] = {
        **window("1991-01-01", "2026-01-01"),
        "id": "synthetic-full-history-climatology",
        "source_vintage": "synthetic-full-history",
        "revision_id": "synthetic-reference-revision",
        "first_published_at": "2026-02-01T00:00:00Z",
        "first_publication_reference": EVIDENCE,
    }
    assert outcome(candidate) == "INELIGIBLE"
    projected = project_temporal_alignment(evaluate_alignment(candidate))
    assert projected["reference_period"]["id"] == "synthetic-full-history-climatology"


def test_current_cumulative_tick_status_is_not_historical_annual_status() -> None:
    candidate = spec()
    candidate["source_id"] = "synthetic-current-cumulative-tick-status"
    candidate["aggregation"]["coverage"] = {  # type: ignore[index]
        "expected": 1,
        "observed": 1,
        "unit": "RECORDS",
        "partial_allowed": False,
    }
    candidate["observation_window"] = window("2000-01-01", "2026-01-01")
    candidate["target_window"] = window("2026-01-01", "2027-01-01")
    candidate["lag"] = {"kind": "FIXED", "anchor": "END_EXCLUSIVE", "offset_days": 0}
    candidate["decision_cutoff"] = "2019-01-01T00:00:00Z"
    assert outcome(candidate) == "INELIGIBLE"


def test_unknown_publication_is_never_inferred_from_retrieval_or_modification() -> None:
    candidate = spec()
    candidate["availability"]["first_published_at"] = None  # type: ignore[index]
    candidate["availability"]["first_publication_reference"] = None  # type: ignore[index]
    assert outcome(candidate) == "RETROSPECTIVE_ONLY"
    candidate["availability"]["retrieved_at"] = None  # type: ignore[index]
    assert outcome(candidate) == "UNKNOWN_AVAILABILITY"


def test_era_flag_does_not_override_time_or_as_of_and_projection_is_bounded() -> None:
    candidate = spec()
    candidate["methodology_era_id"] = "cdc_2017"
    candidate["physical_artifact_id"] = "private-fixture-artifact"
    candidate["lag"]["physical_artifact_id"] = "nested-private-fixture"  # type: ignore[index]
    candidate["availability"]["revision_available_at"] = "2025-03-01T00:00:00Z"  # type: ignore[index]
    result = evaluate_alignment(candidate)
    assert result["disposition"] == "INELIGIBLE"
    projected = project_temporal_alignment(result)
    assert "physical_artifact_id" not in projected
    assert "source_version_id" not in projected
    assert "availability" not in projected
    assert "physical_artifact_id" not in projected["lag"]
    result["lag"]["physical_artifact_id"] = "injected-private-fixture"
    assert "physical_artifact_id" not in project_temporal_alignment(result)["lag"]
    result["limitations"] = ["private: C:\\restricted\\source"]
    with pytest.raises(TemporalAlignmentError, match="restricted temporal projection"):
        project_temporal_alignment(result)
