"""Behavioral fixture proof of the storage-neutral Story #190 contract."""

from __future__ import annotations

import ast
import copy
import inspect
import textwrap

import pytest

from lyme_gap_atlas_data import semantic_release
from lyme_gap_atlas_data.semantic_domain import (
    CONTRACT_VERSION,
    SemanticDomainError,
    observation_key,
    revision_id,
    validate_domain,
    validate_measures,
    validate_observation,
)

COUNTY_IDS = (
    "county_fips",
    "geometry",
    "human_status",
    "case_count_floor_2023",
    "incidence_floor_2023",
    "state_unallocated_records_2023",
    "scapularis_status",
    "pacificus_status",
    "burgdorferi_status",
    "population_2022",
    "svi_percentile_2022",
    "uninsured_percentile_2022",
    "uninsured_percent_2022",
    "rucc_2023",
)


def measure(
    measure_id: str = "case_count_floor_2023",
    *,
    grain: str = "COUNTY",
    time: str = "PERIOD",
    origin: str = "REPORTED",
    unit: str = "cases",
    denominator: str = "NONE",
    strata: list[str] | None = None,
    states: list[str] | None = None,
) -> dict:
    return {
        "measure_id": measure_id,
        "indicator_id": "human_disease_burden",
        "semantic_version": "1.0.0",
        "definition": f"Reviewed {measure_id} meaning",
        "data_type": "number",
        "unit": unit,
        "denominator": denominator,
        "geography_grain": grain,
        "temporal_semantics": time,
        "allowed_strata": strata or [],
        "origin": origin,
        "methodology_version": "reviewed-v1",
        "allowed_value_states": states
        or [
            "OBSERVED",
            "ZERO",
            "MISSING",
            "UNKNOWN",
            "SUPPRESSED",
            "NOT_REPORTED",
            "UNAVAILABLE",
            "NOT_DEFENSIBLE",
            "NO_RECORDS",
            "NO_COUNTY_LINKED_RECORD",
        ],
        "label": "Fixture label",
    }


def observation(m: dict, *, value: object = 3, state: str = "OBSERVED") -> dict:
    grain = m["geography_grain"]
    geography = {
        "COUNTY": {
            "grain": grain,
            "county_fips": "08013",
            "representativeness": "COUNTY_NATIVE_STATUS",
        },
        "SITE_EVENT": {
            "grain": grain,
            "site_id": "BLAN",
            "event_id": "sample-1",
            "county_fips": None,
            "representativeness": "NOT_COUNTY_REPRESENTATIVE",
        },
        "SOURCE_ONLY_COUNTY": {
            "grain": grain,
            "reported_geography_id": "publisher-row-1",
            "county_fips": None,
            "mapping_status": "UNMAPPED",
        },
    }[grain]
    temporal = {"semantics": m["temporal_semantics"]}
    if m["temporal_semantics"] == "PERIOD":
        temporal.update(start="2023-01-01", end="2023-12-31")
    else:
        temporal["date"] = "2025-12-31"
    provenance = {
        "source_id": "cdc_lyme",
        "dataset_id": "x5j9-wybp",
        "source_version_id": "source-v1",
        "source_vintage": "2023",
        "ingestion_run_id": "run-1",
        "artifact_id": "artifact-1",
        "source_record_id": "row-1",
        "retrieved_at": "2026-09-18T00:00:00Z",
    }
    if m["origin"] == "DERIVED":
        source = {
            key: provenance[key]
            for key in (
                "source_id",
                "dataset_id",
                "source_version_id",
                "source_vintage",
                "ingestion_run_id",
                "artifact_id",
                "source_record_id",
                "retrieved_at",
            )
        }
        provenance = {
            "dataset_id": "derived-product-v1",
            "transformation_version": "calculation-v1",
            "input_ids": ["canonical-input-1"],
            "lineage_sources": [source],
            "evidence_basis": "SYNTHETIC_FIXTURE",
        }
    result = {
        "contract_version": CONTRACT_VERSION,
        "measure_id": m["measure_id"],
        "measure_version": m["semantic_version"],
        "unit": m["unit"],
        "denominator": m["denominator"],
        "origin": m["origin"],
        "geography": geography,
        "temporal": temporal,
        "strata": {},
        "value": value,
        "value_state": state,
        "provenance": provenance,
        "quality_ref": None,
        "eligibility_ref": None,
        "limitations_ref": "reviewed-source-limitation-v1",
    }
    reseal(result, m)
    return result


def reseal(o: dict, m: dict) -> None:
    o["observation_key"] = observation_key(o, m)
    o["revision_id"] = revision_id(o)


def test_existing_county_release_has_exactly_the_14_unchanged_slots() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(semantic_release._county_observations)))
    definitions = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "definitions" for target in node.targets
        )
    )
    actual = tuple(item.elts[1].value for item in definitions.elts)
    assert actual == COUNTY_IDS
    assert semantic_release.EXPECTED_COUNTIES == 3_144
    assert semantic_release.EXPECTED_OBSERVATIONS_PER_COUNTY == 14
    assert len({observation(measure(slot))["observation_key"] for slot in actual}) == 14


@pytest.mark.parametrize("slot", COUNTY_IDS)
def test_each_existing_county_slot_has_a_valid_domain_identity(slot: str) -> None:
    m = measure(slot)
    validate_domain([m], [observation(m)])


@pytest.mark.parametrize(
    "name,unit,denominator,time,value,state",
    [
        ("case_count_floor_2023", "cases", "NONE", "PERIOD", 3, "OBSERVED"),
        ("incidence_floor_2023", "per 100,000", "population", "PERIOD", 2.1, "OBSERVED"),
        ("svi_percentile_2022", "percentile", "NONE", "PERIOD", 0.6, "OBSERVED"),
        ("rucc_2023", "code", "NONE", "POINT_IN_TIME", 4, "OBSERVED"),
        (
            "scapularis_status",
            "status",
            "NONE",
            "CUMULATIVE_THROUGH_DATE",
            "No records",
            "NO_RECORDS",
        ),
        (
            "burgdorferi_status",
            "status",
            "NONE",
            "CUMULATIVE_THROUGH_DATE",
            None,
            "UNKNOWN",
        ),
    ],
)
def test_representative_county_meanings(
    name: str, unit: str, denominator: str, time: str, value: object, state: str
) -> None:
    m = measure(name, unit=unit, denominator=denominator, time=time)
    validate_domain([m], [observation(m, value=value, state=state)])


@pytest.mark.parametrize(
    "name,grain,time,origin,unit,denominator",
    [
        ("neon_collection", "SITE_EVENT", "POINT_IN_TIME", "REPORTED", "ticks", "NONE"),
        (
            "neon_individual_pathogen_test",
            "SITE_EVENT",
            "POINT_IN_TIME",
            "REPORTED",
            "ticks",
            "individual_tests",
        ),
        (
            "infected_tick_prevalence",
            "SITE_EVENT",
            "POINT_IN_TIME",
            "DERIVED",
            "proportion",
            "ticks_tested",
        ),
        (
            "surveillance_coverage",
            "SITE_EVENT",
            "POINT_IN_TIME",
            "DERIVED",
            "categorical_state",
            "NONE",
        ),
        (
            "surveillance_priority",
            "SITE_EVENT",
            "POINT_IN_TIME",
            "DERIVED",
            "unordered_disposition",
            "NONE",
        ),
        (
            "source_only_county_evidence",
            "SOURCE_ONLY_COUNTY",
            "CUMULATIVE_THROUGH_DATE",
            "REPORTED",
            "categorical_state",
            "NONE",
        ),
    ],
)
def test_native_and_derived_shapes(
    name: str, grain: str, time: str, origin: str, unit: str, denominator: str
) -> None:
    allowed = (
        ["tick_taxon", "life_stage", "pathogen_target", "collection_method", "testing_scope"]
        if grain == "SITE_EVENT"
        else []
    )
    m = measure(
        name,
        grain=grain,
        time=time,
        origin=origin,
        unit=unit,
        denominator=denominator,
        strata=allowed,
    )
    value, state = (None, "UNKNOWN") if grain == "SOURCE_ONLY_COUNTY" else ("PRESENT", "OBSERVED")
    o = observation(m, value=value, state=state)
    if name == "neon_collection":
        o["strata"] = {"tick_taxon": "ixodes_scapularis", "collection_method": "drag_sampling"}
    if name == "neon_individual_pathogen_test":
        o["strata"] = {
            "tick_taxon": "ixodes_scapularis",
            "pathogen_target": "borrelia_burgdorferi",
            "testing_scope": "individual_pathogen_test",
        }
    reseal(o, m)
    validate_domain([m], [o])


def test_display_label_change_preserves_semantic_key() -> None:
    m = measure()
    o = observation(m)
    m["label"] = "New display wording"
    o["display_label"] = "Different county name"
    validate_observation(o, m)
    assert o["observation_key"] == observation_key(o, m)


@pytest.mark.parametrize(
    "change,error",
    [
        (lambda o: o.update(unit="ticks"), "incompatible unit"),
        (lambda o: o.update(denominator="population"), "denominator"),
        (lambda o: o["geography"].update(grain="SITE_EVENT"), "geography grain"),
        (lambda o: o["temporal"].update(semantics="POINT_IN_TIME"), "temporal semantics"),
        (lambda o: o["strata"].update(tick_taxon="Ixodes"), "invalid strata"),
        (lambda o: o.update(value=3, value_state="UNKNOWN"), "must be null"),
        (lambda o: o.update(value=None, value_state="ZERO"), "numeric zero"),
        (lambda o: o["provenance"].pop("artifact_id"), "artifact_id"),
        (lambda o: o.update(origin="DERIVED"), "reported/derived"),
    ],
)
def test_incompatible_assertions_fail(change: object, error: str) -> None:
    m = measure()
    o = observation(m)
    change(o)
    with pytest.raises(SemanticDomainError, match=error):
        validate_observation(o, m)


@pytest.mark.parametrize(
    "state,value",
    [
        ("ZERO", 0),
        ("MISSING", None),
        ("UNKNOWN", None),
        ("SUPPRESSED", None),
        ("NOT_REPORTED", None),
        ("UNAVAILABLE", None),
        ("NOT_DEFENSIBLE", None),
        ("NO_RECORDS", "No records"),
    ],
)
def test_distinct_value_states(state: str, value: object) -> None:
    m = measure()
    validate_observation(observation(m, state=state, value=value), m)


def test_source_only_never_becomes_canonical_county() -> None:
    m = measure("source_only", grain="SOURCE_ONLY_COUNTY", time="CUMULATIVE_THROUGH_DATE")
    o = observation(m, state="UNKNOWN", value=None)
    o["geography"]["county_fips"] = "08013"
    with pytest.raises(SemanticDomainError, match="cannot have county FIPS"):
        validate_observation(o, m)


def test_site_county_mapping_remains_contextual() -> None:
    m = measure("collection", grain="SITE_EVENT", time="POINT_IN_TIME")
    o = observation(m)
    o["geography"]["county_fips"] = "08013"
    with pytest.raises(SemanticDomainError, match="mapping proof"):
        validate_observation(o, m)
    o["geography"]["county_relationship"] = "ATLAS_DERIVED_MATCH"
    with pytest.raises(SemanticDomainError, match="mapping_version"):
        validate_observation(o, m)
    o["geography"]["mapping_version"] = "crosswalk-v1"
    o["geography"]["mapping_artifact_id"] = "crosswalk-artifact-1"
    reseal(o, m)
    validate_observation(o, m)


@pytest.mark.parametrize("state,value", [("OBSERVED", "Unknown"), ("OBSERVED", "No records")])
def test_publisher_sentinels_need_explicit_state(state: str, value: str) -> None:
    m = measure("status", unit="status")
    with pytest.raises(SemanticDomainError, match="sentinel value"):
        validate_observation(observation(m, state=state, value=value), m)


def test_invalid_temporal_date_fails() -> None:
    m = measure()
    o = observation(m)
    o["temporal"]["end"] = "2023-13-31"
    with pytest.raises(SemanticDomainError, match="invalid temporal date"):
        validate_observation(o, m)


def test_derived_requires_input_and_evidence_basis() -> None:
    m = measure("metric", grain="SITE_EVENT", time="POINT_IN_TIME", origin="DERIVED")
    o = observation(m)
    del o["provenance"]["evidence_basis"]
    with pytest.raises(SemanticDomainError, match="evidence_basis"):
        validate_observation(o, m)


def test_derived_result_references_multiple_source_records_without_fake_single_record() -> None:
    m = measure("coverage", grain="SITE_EVENT", time="POINT_IN_TIME", origin="DERIVED")
    o = observation(m)
    second = copy.deepcopy(o["provenance"]["lineage_sources"][0])
    second.update(
        source_id="neon_testing",
        dataset_id="DP1.10092.001",
        source_version_id="RELEASE-2026",
        artifact_id="artifact-2",
        source_record_id="testing-row-2",
    )
    o["provenance"]["lineage_sources"].append(second)
    o["provenance"]["input_ids"].append("canonical-input-2")
    reseal(o, m)
    validate_observation(o, m)
    assert "source_record_id" not in o["provenance"]
    incomplete = copy.deepcopy(o)
    del incomplete["provenance"]["lineage_sources"][1]["artifact_id"]
    with pytest.raises(SemanticDomainError, match="artifact_id"):
        validate_observation(incomplete, m)


def test_duplicate_revision_and_unversioned_meaning_change_fail() -> None:
    m = measure()
    o = observation(m)
    with pytest.raises(SemanticDomainError, match="duplicate revision"):
        validate_domain([m], [o, copy.deepcopy(o)])
    changed = copy.deepcopy(m)
    changed["denominator"] = "population"
    with pytest.raises(SemanticDomainError, match="unversioned meaning change"):
        validate_measures([m, changed])


def test_revision_and_observation_keys_track_different_changes() -> None:
    m = measure()
    first = observation(m)
    revised = copy.deepcopy(first)
    revised["value"] = 4
    reseal(revised, m)
    assert revised["observation_key"] == first["observation_key"]
    assert revised["revision_id"] != first["revision_id"]
    validate_domain([m], [first, revised])
    next_period = copy.deepcopy(first)
    next_period["temporal"]["start"] = "2024-01-01"
    next_period["temporal"]["end"] = "2024-12-31"
    reseal(next_period, m)
    assert next_period["observation_key"] != first["observation_key"]
    new_vintage = copy.deepcopy(first)
    new_vintage["provenance"]["source_vintage"] = "2024"
    reseal(new_vintage, m)
    assert new_vintage["observation_key"] != first["observation_key"]


def test_evidence_basis_changes_revision_not_scientific_scope() -> None:
    m = measure("metric", grain="SITE_EVENT", time="POINT_IN_TIME", origin="DERIVED")
    synthetic = observation(m)
    source_backed = copy.deepcopy(synthetic)
    source_backed["provenance"]["evidence_basis"] = "CURRENT_CODE_SOURCE_BACKED_REPLAY"
    reseal(source_backed, m)
    assert source_backed["observation_key"] == synthetic["observation_key"]
    assert source_backed["revision_id"] != synthetic["revision_id"]


def test_revision_identity_tampering_fails() -> None:
    m = measure()
    o = observation(m)
    o["provenance"]["artifact_id"] = "different-artifact"
    with pytest.raises(SemanticDomainError, match="revision identity"):
        validate_observation(o, m)
