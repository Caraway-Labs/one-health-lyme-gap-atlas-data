"""Independent expected values and abstention cases for Story #168."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from lyme_gap_atlas_data.infected_tick_metrics import (
    DENSITY,
    PREVALENCE,
    calculate_infected_tick_metric,
)


def _map(rule: str, source: str, canonical_id: str, label: str, dataset: str) -> dict:
    return {
        "source_value": source,
        "canonical_id": canonical_id,
        "canonical_label": label,
        "status": "APPROVED",
        "mapping_rule_id": rule,
        "registry_id": "tick-surveillance-normalization-v1",
        "registry_version": "1.0.4",
        "source_context": {
            "publisher": "NSF NEON",
            "dataset_id": dataset,
            "source_version": "RELEASE-2026",
        },
    }


COLLECTION = "DP1.10093.001"
TESTING = "DP1.10092.001"


def _canonical(metric: str) -> dict:
    is_testing = metric == PREVALENCE
    observation = {
        "canonical_observation_id": "canonical-one",
        "observation_type": "PATHOGEN_TESTING" if is_testing else "COLLECTION_ABUNDANCE",
        "native_sampling_grain": "SITE_EVENT",
        "source_agency": "NSF NEON",
        "source_dataset_id": TESTING if is_testing else COLLECTION,
        "data_source_version_id": "RELEASE-2026",
        "source_record_id": "source-row-one",
        "ingestion_run_id": "run-one",
        "artifact_id": "artifact-one",
        "retrieved_at": "2026-09-23T00:00:00Z",
        "method_version": "tick-surveillance-v1.2",
        "reported_or_derived": "HARMONIZED",
        "tick_species": "Ixodes scapularis",
        "life_stage": "NYMPH",
        "temporal_semantics": "POINT_IN_TIME",
        "surveillance_period_start": "2016-05-02" if is_testing else "2016-05-01",
        "surveillance_period_end": "2016-05-02" if is_testing else "2016-05-01",
        "sampling_site": {"source_site_id": "BLAN", "source_plot_id": "BLAN_001"},
        "sampling_event": {
            "source_event_id": "event-one",
            "source_sample_id": "sample-one",
            "source_subsample_id": "sub-one",
            "source_batch_id": "batch-one" if is_testing else None,
            "source_testing_id": "test-one" if is_testing else None,
        },
        "source_geography": {
            "source_location_id": "BLAN_001",
            "geography_kind": "PLOT",
            "coordinate_reference_system": "EPSG:4326",
            "longitude": -78.5,
            "latitude": 38.0,
            "spatial_uncertainty_meters": 10,
        },
        "county_relationship": {
            "mapping_status": "UNMAPPED",
            "county_fips": None,
            "mapping_method": None,
            "mapping_version": None,
            "mapping_artifact_id": None,
            "representativeness": "NOT_COUNTY_REPRESENTATIVE",
        },
        "quality_flags": [],
        "normalization": {
            "registry_id": "tick-surveillance-normalization-v1",
            "registry_version": "1.0.4",
            "mappings": {
                "taxon": _map(
                    "TAXON_NEON_SCAPULARIS_V1",
                    "Ixodes scapularis",
                    "IXODES_SCAPULARIS",
                    "Ixodes scapularis",
                    COLLECTION,
                ),
                "stage": _map("LIFE_STAGE_NEON_NYMPH_V1", "nymph", "NYMPH", "Nymph", COLLECTION),
            },
        },
    }
    mappings = observation["normalization"]["mappings"]
    if is_testing:
        observation.update(
            {
                "pathogen_name": "Borrelia burgdorferi sensu lato",
                "ticks_tested": 1,
                "ticks_positive": 1,
            }
        )
        mappings["pathogen"] = _map(
            "PATHOGEN_NEON_BBURG_SL_V1",
            "Borrelia burgdorferi sensu lato",
            "BORRELIA_BURGDORFERI_SENSU_LATO",
            "Borrelia burgdorferi sensu lato",
            TESTING,
        )
        mappings["result"] = _map(
            "RESULT_NEON_POSITIVE_V1", "positive", "DETECTED", "Detected", TESTING
        )
    else:
        observation.update(
            {
                "ticks_collected": 8,
                "collection_effort_value": 4.0,
                "collection_effort_unit": "square metre",
                "collection_method": "Drag cloth",
            }
        )
        mappings["method"] = _map(
            "METHOD_NEON_DRAG_V1", "drag", "DRAG_CLOTH", "Drag cloth", COLLECTION
        )
        mappings["effort"] = _map(
            "EFFORT_NEON_SQUARE_METRE_V1", "m2", "SQUARE_METRE", "square metre", COLLECTION
        )
    return observation


def test_synthetic_metric_inputs_are_canonical_schema_compliant() -> None:
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/contracts/tick-surveillance/canonical-tick-surveillance-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    for metric in (PREVALENCE, DENSITY):
        assert list(validator.iter_errors(_canonical(metric))) == []


def test_density_exact_value_zero_conversion_and_repeatability() -> None:
    observation = _canonical(DENSITY)
    result = calculate_infected_tick_metric(DENSITY, [observation])
    assert (result["state"], result["value"], result["numerator"], result["denominator"]) == (
        "NUMERIC",
        2.0,
        8,
        4.0,
    )
    assert result["unit"] == "ticks_per_square_metre"
    assert result["representativeness"] == "NOT_COUNTY_REPRESENTATIVE"
    assert result["county_relationship"]["county_fips"] is None
    assert "UNMAPPED_SITE_GEOGRAPHY" in result["quality_propagation"]["inherited_limitations"]
    assert (
        "METHOD_COMPARABILITY_NOT_ESTABLISHED"
        in result["quality_propagation"]["inherited_limitations"]
    )
    assert calculate_infected_tick_metric(DENSITY, [observation]) == result
    hectare = calculate_infected_tick_metric(
        DENSITY, [observation], output_unit="ticks_per_hectare"
    )
    assert hectare["value"] == 2.0
    assert hectare["unit"] == "ticks_per_square_metre"
    assert hectare["metric_identity"] == result["metric_identity"]
    assert hectare["presentation_conversion"] == {
        "value": 20000.0,
        "unit": "ticks_per_hectare",
        "conversion_rule_id": "ABUNDANCE_SQUARE_METRE_TO_HECTARE_V1",
    }
    zero = deepcopy(observation)
    zero["ticks_collected"] = 0
    assert calculate_infected_tick_metric(DENSITY, [zero])["value"] == 0.0


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"collection_effort_value": None}, "EFFORT_UNAVAILABLE"),
        ({"collection_effort_value": 0}, "ZERO_EFFORT"),
        ({"collection_effort_value": float("inf")}, "NONFINITE_OR_INVALID_EFFORT"),
        ({"collection_effort_unit": None}, "UNSUPPORTED_EFFORT_UNIT"),
        ({"collection_method": "Flag cloth"}, "INCOMPATIBLE_COLLECTION_METHOD"),
        ({"life_stage": "MIXED"}, "UNRESOLVED_LIFE_STAGE"),
    ],
)
def test_density_abstains_for_invalid_inputs(change: dict, reason: str) -> None:
    observation = _canonical(DENSITY) | change
    result = calculate_infected_tick_metric(DENSITY, [observation])
    assert result["state"] == "UNAVAILABLE" and result["value"] is None
    assert reason in result["unavailable_reasons"]


def test_density_unknown_effort_and_impractical_flag_are_unavailable() -> None:
    observation = _canonical(DENSITY)
    observation["collection_effort_value"] = None
    observation["missingness"] = {"collection_effort_value": "UNKNOWN"}
    assert (
        "EFFORT_UNKNOWN"
        in calculate_infected_tick_metric(DENSITY, [observation])["unavailable_reasons"]
    )
    observation = _canonical(DENSITY)
    observation["quality_flags"] = [{"canonical_id": "SAMPLING_IMPRACTICAL"}]
    result = calculate_infected_tick_metric(DENSITY, [observation])
    assert "SAMPLING_IMPRACTICAL" in result["unavailable_reasons"]
    assert "SAMPLING_IMPRACTICAL" in result["quality_propagation"]["inherited_limitations"]


def test_current_collection_shape_without_unit_mapping_fails_closed() -> None:
    observation = _canonical(DENSITY)
    del observation["normalization"]["mappings"]["effort"]
    result = calculate_infected_tick_metric(DENSITY, [observation])
    assert result["state"] == "UNAVAILABLE"
    assert "MISSING_APPROVED_EFFORT_UNIT_MAPPING" in result["unavailable_reasons"]


def test_density_quality_and_native_stratum_boundaries() -> None:
    observation = _canonical(DENSITY)
    observation.pop("temporal_semantics")
    observation["quality_flags"] = ["SOURCE_REVISION_SENSITIVE"]
    result = calculate_infected_tick_metric(DENSITY, [observation])
    assert result["state"] == "NUMERIC"
    assert "TEMPORAL_COVERAGE_UNKNOWN" in result["quality_propagation"]["inherited_limitations"]
    assert "STALE_OR_REVISION_SENSITIVE" in result["quality_propagation"]["inherited_limitations"]
    pathogen_component = next(
        component
        for component in result["quality_propagation"]["propagated_components"]
        if component["dimension"] == "PATHOGEN_TESTING_DENOMINATOR_VALIDITY"
    )
    assert pathogen_component["state"] == "NOT_APPLICABLE"
    missing_lineage = _canonical(DENSITY)
    missing_lineage["artifact_id"] = ""
    unavailable = calculate_infected_tick_metric(DENSITY, [missing_lineage])
    assert "MISSING_REQUIRED_PROVENANCE" in unavailable["unavailable_reasons"]
    assert "QUALITY_EVIDENCE_MISSING_PROVENANCE_COMPLETENESS" in unavailable["unavailable_reasons"]
    other_event = deepcopy(_canonical(DENSITY))
    other_event["canonical_observation_id"] = "canonical-two"
    other_event["sampling_event"]["source_event_id"] = "event-two"
    assert (
        "CROSS_RECORD_DENSITY_AGGREGATION_NOT_APPROVED"
        in calculate_infected_tick_metric(DENSITY, [observation, other_event])[
            "unavailable_reasons"
        ]
    )
    revision_ambiguous = _canonical(DENSITY)
    revision_ambiguous["quality_flags"] = [{"canonical_id": "SOURCE_REVISION_AMBIGUOUS"}]
    assert (
        "REVISION_SELECTION_NOT_APPROVED"
        in calculate_infected_tick_metric(DENSITY, [revision_ambiguous])["unavailable_reasons"]
    )


def test_unsupported_density_output_unit_is_unavailable() -> None:
    result = calculate_infected_tick_metric(
        DENSITY, [_canonical(DENSITY)], output_unit="ticks_per_mile"
    )
    assert result["state"] == "UNAVAILABLE"
    assert "UNSUPPORTED_OUTPUT_CONVERSION" in result["unavailable_reasons"]


def test_prevalence_synthetic_positive_zero_sparse_and_current_shape() -> None:
    first = _canonical(PREVALENCE)
    second = deepcopy(first)
    second["canonical_observation_id"] = "canonical-two"
    second["source_record_id"] = "source-row-two"
    second["sampling_event"]["source_testing_id"] = "test-two"
    second["ticks_positive"] = 0
    second["normalization"]["mappings"]["result"] = _map(
        "RESULT_NEON_NEGATIVE_V1", "negative", "NOT_DETECTED", "Not detected", TESTING
    )
    result = calculate_infected_tick_metric(PREVALENCE, [second, first])
    assert (result["state"], result["value"], result["numerator"], result["denominator"]) == (
        "NUMERIC",
        0.5,
        1,
        2,
    )
    assert result["input_canonical_observation_ids"] == ["canonical-one", "canonical-two"]
    assert (
        "NON_RANDOM_PATHOGEN_TEST_SELECTION"
        in result["quality_propagation"]["inherited_limitations"]
    )
    assert calculate_infected_tick_metric(PREVALENCE, [second])["value"] == 0.0
    assert calculate_infected_tick_metric(PREVALENCE, [first])["value"] == 1.0
    current_shape = deepcopy(first)
    del current_shape["life_stage"]
    del current_shape["normalization"]["mappings"]["stage"]
    unavailable = calculate_infected_tick_metric(PREVALENCE, [current_shape])
    assert unavailable["state"] == "UNAVAILABLE"
    assert "UNRESOLVED_LIFE_STAGE" in unavailable["unavailable_reasons"]


def test_prevalence_independent_two_of_five_expected_value() -> None:
    observations = []
    for index in range(5):
        observation = _canonical(PREVALENCE)
        observation["canonical_observation_id"] = f"canonical-{index}"
        observation["source_record_id"] = f"source-row-{index}"
        observation["sampling_event"]["source_testing_id"] = f"test-{index}"
        if index >= 2:
            observation["ticks_positive"] = 0
            observation["normalization"]["mappings"]["result"] = _map(
                "RESULT_NEON_NEGATIVE_V1", "negative", "NOT_DETECTED", "Not detected", TESTING
            )
        observations.append(observation)
    result = calculate_infected_tick_metric(PREVALENCE, observations)
    assert (result["value"], result["numerator"], result["denominator"], result["unit"]) == (
        0.4,
        2,
        5,
        "proportion",
    )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"ticks_tested": 0}, "ZERO_TESTED_DENOMINATOR"),
        ({"ticks_tested": None}, "TESTED_DENOMINATOR_UNAVAILABLE"),
        ({"ticks_positive": 2}, "POSITIVE_EXCEEDS_TESTED"),
        ({"ticks_positive": -1}, "INVALID_POSITIVE_COUNT"),
        ({"ticks_positive": 0.5}, "INVALID_POSITIVE_COUNT"),
        ({"ticks_tested": -1}, "INVALID_TESTED_DENOMINATOR"),
        ({"testing_grain": "POOLED"}, "POOLED_TESTING_UNSUPPORTED"),
        ({"pathogen_name": "Unsupported"}, "UNSUPPORTED_PATHOGEN_MAPPING"),
        ({"observation_type": "NON_PATHOGEN_SUPPORTING_ASSAY"}, "INELIGIBLE_OBSERVATION_TYPE"),
    ],
)
def test_prevalence_abstains_for_invalid_inputs(change: dict, reason: str) -> None:
    result = calculate_infected_tick_metric(PREVALENCE, [_canonical(PREVALENCE) | change])
    assert result["state"] == "UNAVAILABLE" and result["value"] is None
    assert reason in result["unavailable_reasons"]


@pytest.mark.parametrize(
    "dimension",
    [
        "tick_species",
        "life_stage",
        "pathogen_name",
        "surveillance_period_start",
        "source_geography",
    ],
)
def test_prevalence_does_not_pool_mismatched_strata(dimension: str) -> None:
    first = _canonical(PREVALENCE)
    second = deepcopy(first)
    second["canonical_observation_id"] = "canonical-two"
    second["source_record_id"] = "source-row-two"
    second["sampling_event"]["source_testing_id"] = "test-two"
    second[dimension] = "other"
    assert (
        "INCOMPATIBLE_NATIVE_STRATUM"
        in calculate_infected_tick_metric(PREVALENCE, [first, second])["unavailable_reasons"]
    )


def test_prevalence_does_not_pool_mismatched_testing_scope_or_revision() -> None:
    first = _canonical(PREVALENCE)
    second = deepcopy(first)
    second["canonical_observation_id"] = "canonical-two"
    second["source_record_id"] = "source-row-two"
    second["sampling_event"]["source_testing_id"] = "test-two"
    second["sampling_event"]["source_batch_id"] = "batch-two"
    assert (
        "INCOMPATIBLE_NATIVE_STRATUM"
        in calculate_infected_tick_metric(PREVALENCE, [first, second])["unavailable_reasons"]
    )
    second["sampling_event"]["source_batch_id"] = "batch-one"
    second["source_record_id"] = first["source_record_id"]
    assert (
        "REVISION_SELECTION_NOT_APPROVED"
        in calculate_infected_tick_metric(PREVALENCE, [first, second])["unavailable_reasons"]
    )


def test_identity_changes_with_event_revision_and_input() -> None:
    first = _canonical(DENSITY)
    baseline = calculate_infected_tick_metric(DENSITY, [first])["metric_identity"]
    for field, value in (
        ("canonical_observation_id", "other-id"),
        ("data_source_version_id", "RELEASE-2027"),
    ):
        changed = deepcopy(first)
        changed[field] = value
        assert calculate_infected_tick_metric(DENSITY, [changed])["metric_identity"] != baseline
    changed = deepcopy(first)
    changed["sampling_event"]["source_event_id"] = "event-two"
    assert calculate_infected_tick_metric(DENSITY, [changed])["metric_identity"] != baseline
    changed = deepcopy(first)
    changed["artifact_id"] = "revised-artifact"
    assert calculate_infected_tick_metric(DENSITY, [changed])["metric_identity"] != baseline
