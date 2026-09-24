"""Synthetic contract fixtures and negative invariants for Story #191."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lyme_gap_atlas_data import semantic_release
from lyme_gap_atlas_data.semantic_domain import meaning_signature
from lyme_gap_atlas_data.semantic_metadata import (
    CONTRACT_VERSION,
    SemanticMetadataError,
    metadata_revision_id,
    validate_metadata,
    validate_metadata_revisions,
)


def known(value: str) -> dict[str, str]:
    return {"state": "KNOWN", "value": value}


def absent(state: str = "UNKNOWN") -> dict[str, str | None]:
    return {"state": state, "value": None}


SHAPES = [
    # All source/version labels here are synthetic contract references, not source approval.
    (
        "case_count_floor_2023",
        "human_disease_burden",
        "cases",
        "NONE",
        "COUNTY",
        "PERIOD",
        "REPORTED",
        "cdc_lyme",
        "x5j9-wybp",
        "2023",
    ),
    (
        "svi_percentile_2022",
        "population_context",
        "percentile",
        "NONE",
        "COUNTY",
        "PERIOD",
        "REPORTED",
        "cdc_atsdr_svi",
        "atsdr-svi-2022-county-layer",
        "2022",
    ),
    (
        "rucc_2023",
        "rurality_context",
        "code",
        "NONE",
        "COUNTY",
        "POINT_IN_TIME",
        "REPORTED",
        "usda_ers",
        "rural-urban-continuum-codes-2023",
        "2023",
    ),
    (
        "scapularis_status",
        "tick_surveillance",
        "status",
        "NONE",
        "COUNTY",
        "CUMULATIVE_THROUGH_DATE",
        "REPORTED",
        "cdc_tick",
        "county-tick-status",
        "2025",
    ),
    (
        "burgdorferi_status",
        "pathogen_surveillance",
        "status",
        "NONE",
        "COUNTY",
        "CUMULATIVE_THROUGH_DATE",
        "REPORTED",
        "cdc_pathogen",
        "county-pathogen-status",
        "2025",
    ),
    (
        "neon_collection",
        "tick_surveillance",
        "ticks",
        "NONE",
        "SITE_EVENT",
        "POINT_IN_TIME",
        "REPORTED",
        "neon",
        "DP1.10093.001",
        "RELEASE-2026",
    ),
    (
        "neon_individual_pathogen_test",
        "pathogen_surveillance",
        "ticks",
        "individual_tests",
        "SITE_EVENT",
        "POINT_IN_TIME",
        "REPORTED",
        "neon",
        "DP1.10092.001",
        "RELEASE-2026",
    ),
    (
        "infected_tick_prevalence",
        "tick_surveillance",
        "proportion",
        "ticks_tested",
        "SITE_EVENT",
        "POINT_IN_TIME",
        "DERIVED",
        "neon",
        "DP1.10092.001",
        "RELEASE-2026",
    ),
    (
        "surveillance_coverage",
        "tick_surveillance",
        "categorical_state",
        "NONE",
        "SITE_EVENT",
        "POINT_IN_TIME",
        "DERIVED",
        "neon",
        "DP1.10093.001",
        "RELEASE-2026",
    ),
]


def fixture(index: int = 0) -> dict:
    name, indicator, unit, denominator, grain, time, origin, source, dataset, vintage = SHAPES[
        index
    ]
    method = (
        "infected-tick-metrics-v1"
        if index == 7
        else ("surveillance-coverage-v1" if index == 8 else "reviewed-v1")
    )
    measure = {
        "measure_id": name,
        "indicator_id": indicator,
        "semantic_version": "1.0.0",
        "definition": f"Synthetic fixture meaning for {name}",
        "data_type": "number"
        if unit in {"cases", "percentile", "code", "ticks", "proportion"}
        else "string",
        "unit": unit,
        "denominator": denominator,
        "geography_grain": grain,
        "temporal_semantics": time,
        "allowed_strata": [
            "tick_taxon",
            "life_stage",
            "pathogen_target",
            "collection_method",
            "testing_scope",
        ]
        if grain == "SITE_EVENT"
        else [],
        "origin": origin,
        "methodology_version": method,
        "allowed_value_states": ["OBSERVED", "UNKNOWN", "UNAVAILABLE"],
    }
    limitations = [
        {
            "category": "INTERPRETATION",
            "code": "no_human_risk_inference",
            "text": "This measure does not estimate individual human risk.",
        },
    ]
    if grain != "COUNTY":
        limitations.append(
            {
                "category": "REPRESENTATIVENESS",
                "code": "not_county_representative",
                "text": "Site and event evidence does not establish county representativeness.",
            }
        )
    if denominator != "NONE":
        limitations.append(
            {
                "category": "DENOMINATOR",
                "code": "bounded_denominator",
                "text": "The denominator applies only to the recorded testing scope.",
            }
        )
    if name in {"scapularis_status", "burgdorferi_status"}:
        limitations.append(
            {
                "category": "SOURCE",
                "code": "no_records_not_absence",
                "text": "No records does not establish biological absence.",
            }
        )
    metadata = {
        "contract_version": CONTRACT_VERSION,
        "metadata_id": f"metadata:{name}:1.0.0",
        "metadata_revision": 1,
        "measure": measure,
        "meaning_signature": meaning_signature(measure),
        "label": name.replace("_", " ").title(),
        "definition": measure["definition"],
        "short_description": known(f"Synthetic description of {name}"),
        "authority": {
            "label": "STEWARD_REVIEWED",
            "definition": "STEWARD_REVIEWED",
            "short_description": "STEWARD_REVIEWED",
        },
        "steward_review": {"state": "PENDING", "reviewed_at": absent("UNKNOWN")},
        "applicability": {
            "geography_grain": grain,
            "temporal_semantics": time,
            "allowed_strata": measure["allowed_strata"],
            "origin": origin,
            "representativeness": "COUNTY_NATIVE_STATUS"
            if grain == "COUNTY"
            else "NOT_COUNTY_REPRESENTATIVE",
        },
        "unit": unit,
        "denominator": denominator,
        "allowed_value_states": measure["allowed_value_states"],
        "provenance": {
            "publisher": known(source),
            "source_id": known(source),
            "dataset_id": known(dataset),
            "source_version_id": known("fixture-version-1"),
            "source_vintage": known(vintage),
            "method_version": known(method),
            "transformation_version": known(
                "infected-tick-calculation-v1"
                if index == 7
                else "surveillance-coverage-calculation-v2"
            )
            if origin == "DERIVED"
            else absent("NOT_APPLICABLE"),
        },
        "freshness": {
            "observation_period": absent("UNKNOWN"),
            "source_vintage": known(vintage),
            "retrieved_at": absent("UNAVAILABLE"),
            "published_at": absent("UNKNOWN"),
            "metadata_revised_at": known("2026-09-24"),
        },
        "quality_evidence": {
            "quality_contract": known("surveillance-quality-profile-v1")
            if index >= 3
            else absent("NOT_APPLICABLE"),
            "propagation_contract": known("surveillance-quality-propagation-v1")
            if origin == "DERIVED"
            else absent("NOT_APPLICABLE"),
            "eligibility_contract": known("surveillance-scientific-eligibility-v1")
            if index == 8
            else absent("NOT_APPLICABLE"),
            "uncertainty": absent("UNKNOWN"),
            "evidence_basis": known("SYNTHETIC_FIXTURE")
            if origin == "DERIVED"
            else absent("NOT_APPLICABLE"),
        },
        "limitations": limitations,
        "visibility": "INTERNAL" if origin == "DERIVED" else "CONSUMER_SAFE",
    }
    seal(metadata)
    return metadata


def seal(metadata: dict) -> None:
    metadata["revision_id"] = metadata_revision_id(metadata)


@pytest.mark.parametrize("index", range(len(SHAPES)))
def test_representative_synthetic_metadata(index: int) -> None:
    metadata = fixture(index)
    validate_metadata(metadata)
    source = metadata["provenance"]
    approved = {
        (
            source["source_id"]["value"],
            source["dataset_id"]["value"],
            source["source_version_id"]["value"],
        )
    }
    validate_metadata(metadata, approved_source_versions=approved)


def test_checked_in_safe_examples_match_validated_fixtures() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "docs/contracts/semantic-domain/examples/story-191-safe-metadata-fixtures.json"
    )
    examples = json.loads(path.read_text(encoding="utf-8"))
    assert examples == [fixture(index) for index in range(len(SHAPES))]
    for example in examples:
        validate_metadata(example)


def test_label_and_explanatory_revision_keep_scientific_identity() -> None:
    first = fixture()
    second = copy.deepcopy(first)
    second["metadata_revision"] = 2
    second["label"] = "Corrected display label"
    second["short_description"] = known("Clearer explanation of the same reviewed definition")
    seal(second)
    validate_metadata_revisions([first, second])
    assert second["meaning_signature"] == first["meaning_signature"]
    assert second["metadata_id"] == first["metadata_id"]
    assert second["revision_id"] != first["revision_id"]


@pytest.mark.parametrize("field", ["unit", "denominator"])
def test_measurement_change_rejected_without_new_semantic_version(field: str) -> None:
    item = fixture(7)
    item[field] = "different"
    seal(item)
    with pytest.raises(SemanticMetadataError, match="incompatible"):
        validate_metadata(item)


@pytest.mark.parametrize(
    "field,value",
    [("geography_grain", "COUNTY"), ("temporal_semantics", "PERIOD"), ("allowed_strata", [])],
)
def test_applicability_must_agree_with_domain(field: str, value: object) -> None:
    item = fixture(5)
    item["applicability"][field] = value
    seal(item)
    with pytest.raises(SemanticMetadataError, match="applicability"):
        validate_metadata(item)


def test_definition_change_requires_new_measure_version() -> None:
    first = fixture()
    changed = copy.deepcopy(first)
    changed["metadata_revision"] = 2
    changed["measure"]["definition"] = "Different scientific meaning"
    changed["definition"] = "Different scientific meaning"
    changed["meaning_signature"] = meaning_signature(changed["measure"])
    seal(changed)
    with pytest.raises(SemanticMetadataError, match="unversioned meaning change"):
        validate_metadata_revisions([first, changed])


def test_unknown_not_applicable_unavailable_are_distinct_and_never_empty() -> None:
    item = fixture()
    for state in ("UNKNOWN", "NOT_APPLICABLE", "UNAVAILABLE"):
        item["short_description"] = absent(state)
        seal(item)
        validate_metadata(item)
    item["short_description"] = {"state": "UNKNOWN", "value": ""}
    seal(item)
    with pytest.raises(SemanticMetadataError, match="requires null"):
        validate_metadata(item)


def test_source_reported_and_steward_reviewed_authority() -> None:
    item = fixture()
    item["authority"]["label"] = "SOURCE_REPORTED"
    seal(item)
    validate_metadata(item)
    item["authority"]["definition"] = "NON_AUTHORITATIVE_GENERATED_SUMMARY"
    seal(item)
    with pytest.raises(SemanticMetadataError, match="cannot author"):
        validate_metadata(item)


def test_generated_summary_references_prior_authoritative_revision() -> None:
    first = fixture()
    first["steward_review"] = {"state": "REVIEWED", "reviewed_at": known("2026-09-24")}
    seal(first)
    second = copy.deepcopy(first)
    second["metadata_revision"] = 2
    second["short_description"] = known("Generated summary of the prior reviewed definition")
    second["authority"]["short_description"] = "NON_AUTHORITATIVE_GENERATED_SUMMARY"
    second["summary_source_revision"] = first["revision_id"]
    seal(second)
    validate_metadata_revisions([first, second])
    second["summary_source_revision"] = "metadata-revision:v1:unknown"
    seal(second)
    with pytest.raises(SemanticMetadataError, match="not authoritative"):
        validate_metadata_revisions([first, second])
    pending = fixture()
    second["summary_source_revision"] = pending["revision_id"]
    seal(second)
    with pytest.raises(SemanticMetadataError, match="not authoritative"):
        validate_metadata_revisions([pending, second])


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("retrieved_at", "last week", "UTC ISO timestamp"),
        ("observation_period", "2024-01-01", "ISO start/end"),
        ("observation_period", "2024-12-31/2024-01-01", "start exceeds end"),
        ("published_at", "2026-13-40", "ISO date"),
    ],
)
def test_known_freshness_requires_distinct_valid_time_shape(
    field: str, value: str, error: str
) -> None:
    item = fixture()
    item["freshness"][field] = known(value)
    seal(item)
    with pytest.raises(SemanticMetadataError, match=error):
        validate_metadata(item)


def test_known_observation_period_and_retrieval_are_validated() -> None:
    item = fixture()
    item["freshness"]["observation_period"] = known("2023-01-01/2023-12-31")
    item["freshness"]["retrieved_at"] = known("2026-09-18T00:00:00Z")
    seal(item)
    validate_metadata(item)
    item = fixture(5)
    item["freshness"]["observation_period"] = known("2016-05-01")
    seal(item)
    validate_metadata(item)


@pytest.mark.parametrize("index", [7, 8])
def test_unapproved_derived_calculation_version_fails(index: int) -> None:
    item = fixture(index)
    item["provenance"]["transformation_version"] = known("unreviewed-calculation-v1")
    seal(item)
    with pytest.raises(SemanticMetadataError, match="unapproved derived transformation"):
        validate_metadata(item)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_version_id", "REPLACE_WITH_APPROVED_SOURCE_VERSION"),
        ("source_id", ""),
        ("source_vintage", ""),
    ],
)
def test_invalid_source_version_reference(field: str, value: str) -> None:
    item = fixture()
    item["provenance"][field] = known(value)
    seal(item)
    with pytest.raises(SemanticMetadataError, match="source|version"):
        validate_metadata(item)


def test_governed_approval_set_rejects_stale_version() -> None:
    item = fixture()
    with pytest.raises(SemanticMetadataError, match="stale or unapproved"):
        validate_metadata(
            item, approved_source_versions={("cdc_lyme", "x5j9-wybp", "prior-version")}
        )


def test_quality_eligibility_and_evidence_compose_without_score() -> None:
    item = fixture(8)
    validate_metadata(item)
    assert (
        item["quality_evidence"]["quality_contract"]["value"] == "surveillance-quality-profile-v1"
    )
    assert (
        item["quality_evidence"]["eligibility_contract"]["value"]
        == "surveillance-scientific-eligibility-v1"
    )
    assert "confidence_score" not in item
    item["quality_evidence"]["eligibility_contract"] = known("unreviewed-v1")
    seal(item)
    with pytest.raises(SemanticMetadataError, match="unapproved quality"):
        validate_metadata(item)
    item = fixture(8)
    item["quality_evidence"]["evidence_basis"] = known("UNVERIFIED_LIVE_PROOF")
    seal(item)
    with pytest.raises(SemanticMetadataError, match="unapproved derived evidence basis"):
        validate_metadata(item)
    item = fixture()
    item["confidence_score"] = 0.9
    seal(item)
    with pytest.raises(SemanticMetadataError, match="unsupported metadata field"):
        validate_metadata(item)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_url", "https://private.example"),
        ("private_artifact", "artifact-1"),
        ("credential", "secret"),
        ("note", "C:\\private\\restricted\\payload.json"),
    ],
)
def test_consumer_safe_metadata_rejects_restricted_material(field: str, value: str) -> None:
    item = fixture()
    item[field] = value
    seal(item)
    with pytest.raises(SemanticMetadataError, match="restricted"):
        validate_metadata(item)


def test_required_limits_and_reviewed_interpretation_change() -> None:
    first = fixture(7)
    changed = copy.deepcopy(first)
    changed["metadata_revision"] = 2
    changed["limitations"][0]["text"] = "Revised interpretation limitation"
    changed["steward_review"] = {"state": "PENDING", "reviewed_at": absent()}
    seal(changed)
    with pytest.raises(SemanticMetadataError, match="requires steward review"):
        validate_metadata_revisions([first, changed])
    changed["steward_review"] = {"state": "REVIEWED", "reviewed_at": known("2026-09-24")}
    seal(changed)
    validate_metadata_revisions([first, changed])
    changed["limitations"] = [changed["limitations"][0]]
    seal(changed)
    with pytest.raises(SemanticMetadataError, match="representativeness"):
        validate_metadata(changed)


def test_current_county_release_compatibility_and_internal_derived_boundary() -> None:
    assert {
        "human",
        "context_svi",
        "context_rucc",
        "tick",
        "pathogen",
    } == semantic_release.REQUIRED_SOURCE_KEYS
    assert (
        semantic_release.EXPECTED_COUNTIES,
        semantic_release.EXPECTED_OBSERVATIONS_PER_COUNTY,
    ) == (3_144, 14)
    for index in range(5):
        assert fixture(index)["measure"]["geography_grain"] == "COUNTY"
    for index in (7, 8):
        item = fixture(index)
        assert item["visibility"] == "INTERNAL"
        item["visibility"] = "PUBLIC"
        seal(item)
        with pytest.raises(SemanticMetadataError, match="derived result"):
            validate_metadata(item)
