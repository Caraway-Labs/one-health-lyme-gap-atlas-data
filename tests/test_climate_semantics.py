"""Offline metadata alignment: no live approval or publication is inferred."""

from __future__ import annotations

import pytest
from test_climate_publication import DEFINITION, fixture_capture
from test_semantic_metadata import absent, fixture, known, seal

from lyme_gap_atlas_data.climate_semantics import METHOD, PERIOD, january_measure_definitions
from lyme_gap_atlas_data.semantic_domain import meaning_signature, validate_measures
from lyme_gap_atlas_data.semantic_metadata import SemanticMetadataError, validate_metadata


def climate_metadata(index: int = 0) -> dict:
    metadata = fixture(7)
    measure = january_measure_definitions()[index]
    metadata.update(
        measure=measure,
        metadata_id=f"metadata:{measure['measure_id']}:{measure['semantic_version']}",
        meaning_signature=meaning_signature(measure),
        label=measure["measure_id"],
        definition=measure["definition"],
        unit=measure["unit"],
        denominator="NONE",
        allowed_value_states=measure["allowed_value_states"],
    )
    metadata["applicability"].update(
        geography_grain="COUNTY",
        temporal_semantics="PERIOD",
        allowed_strata=[],
        origin="DERIVED",
        representativeness="COUNTY_NATIVE_STATUS",
    )
    metadata["provenance"].update(
        publisher=known("NOAA"),
        source_id=known("noaa_nclimgrid_daily"),
        dataset_id=known("nclimgrid-daily-v1.0.0-scaled"),
        source_vintage=known("v1.0.0-scaled-202501"),
        method_version=known(METHOD),
        transformation_version=known(METHOD),
    )
    metadata["freshness"].update(
        observation_period=known(PERIOD), source_vintage=known("v1.0.0-scaled-202501")
    )
    metadata["quality_evidence"].update(
        quality_contract=absent("NOT_APPLICABLE"),
        propagation_contract=absent("NOT_APPLICABLE"),
        eligibility_contract=absent("NOT_APPLICABLE"),
    )
    seal(metadata)
    return metadata


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("basis", ["SYNTHETIC_FIXTURE", "CURRENT_CODE_SOURCE_BACKED_REPLAY"])
def test_four_internal_definitions_align_with_verified_method(index: int, basis: str) -> None:
    metadata = climate_metadata(index)
    metadata["quality_evidence"]["evidence_basis"] = known(basis)
    seal(metadata)
    validate_measures(january_measure_definitions())
    validate_metadata(metadata)


@pytest.mark.parametrize("visibility", ["CONSUMER_SAFE", "PUBLIC"])
def test_reviewed_climate_metadata_alone_cannot_authorize_publication(visibility: str) -> None:
    metadata = climate_metadata()
    metadata["visibility"] = visibility
    metadata["steward_review"] = {"state": "REVIEWED", "reviewed_at": known("2026-10-01")}
    seal(metadata)
    with pytest.raises(SemanticMetadataError, match="separate exposure approval"):
        validate_metadata(metadata)


def test_historical_method_cannot_be_silently_relabelled() -> None:
    metadata = climate_metadata()
    metadata["provenance"]["transformation_version"] = known("atlas-nclimgrid-county-day/1")
    seal(metadata)
    with pytest.raises(SemanticMetadataError, match="transformation version"):
        validate_metadata(metadata)


def test_explicit_narrow_climate_exposure_accepts_reviewed_safe_revision() -> None:
    metadata = climate_metadata()
    metadata["visibility"] = "CONSUMER_SAFE"
    metadata["steward_review"] = {"state": "REVIEWED", "reviewed_at": known("2026-10-01")}
    metadata["quality_evidence"]["evidence_basis"] = known("CURRENT_CODE_SOURCE_BACKED_REPLAY")
    seal(metadata)
    validate_metadata(metadata, approved_climate_metadata_revisions={metadata["revision_id"]})
    metadata["limitations"][0]["text"] = "https://private.example/payload"
    seal(metadata)
    with pytest.raises(SemanticMetadataError, match="restricted"):
        validate_metadata(metadata, approved_climate_metadata_revisions={metadata["revision_id"]})


@pytest.mark.parametrize("index", [7, 8])
def test_narrow_exposure_does_not_unlock_unrelated_derived_results(index: int) -> None:
    metadata = fixture(index)
    metadata["visibility"] = "CONSUMER_SAFE"
    metadata["steward_review"] = {"state": "REVIEWED", "reviewed_at": known("2026-10-01")}
    seal(metadata)
    with pytest.raises(SemanticMetadataError, match="separate exposure approval"):
        validate_metadata(metadata, approved_climate_metadata_revisions={metadata["revision_id"]})


def test_existing_source_identity_matches_real_writer_capture_shape() -> None:
    capture = fixture_capture()
    assert capture["source_id"] == DEFINITION.source_id == "noaa_nclimgrid_daily"
    metadata = climate_metadata()
    assert metadata["provenance"]["source_id"]["value"] == capture["source_id"]
    metadata["visibility"] = "CONSUMER_SAFE"
    metadata["steward_review"] = {"state": "REVIEWED", "reviewed_at": known("2026-10-01")}
    metadata["quality_evidence"]["evidence_basis"] = known("CURRENT_CODE_SOURCE_BACKED_REPLAY")
    seal(metadata)
    validate_metadata(metadata, approved_climate_metadata_revisions={metadata["revision_id"]})
    metadata["provenance"]["source_id"] = known("source_noaa_nclimgrid_daily")
    seal(metadata)
    with pytest.raises(SemanticMetadataError, match="separate exposure approval"):
        validate_metadata(metadata, approved_climate_metadata_revisions={metadata["revision_id"]})


def test_definitions_do_not_share_mutable_state() -> None:
    definitions = january_measure_definitions()
    definitions[0]["allowed_value_states"].clear()
    assert january_measure_definitions()[0]["allowed_value_states"]
