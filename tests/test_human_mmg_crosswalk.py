"""Offline crosswalk integrity; no notification ingestion or runtime acceptance."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
CONTRACTS = ROOT / "docs/contracts/semantic-domain"
DOCUMENT = json.loads((CONTRACTS / "atlas-human-mmg-crosswalk-v1.json").read_text())


def validate(document: dict) -> None:
    """Bind metadata to existing release identities, never a new registry."""
    tree = ast.parse((ROOT / "src/lyme_gap_atlas_data/semantic_release.py").read_text())
    pairs = {
        (node.elts[0].value, node.elts[1].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Tuple)
        and len(node.elts) > 2
        and all(isinstance(value, ast.Constant) for value in node.elts[:2])
    }
    expected = {measure for indicator, measure in pairs if indicator == "human_disease_burden"}
    mappings = document["mappings"]
    assert len(mappings) == len(expected)
    assert {entry["measure_id"] for entry in mappings} == expected
    registry = json.loads((CONTRACTS / "atlas-semantic-source-mappings-v1.json").read_text())
    source = next(entry for entry in registry["mappings"] if entry["id"] == "human_surveillance")
    contexts = {entry["id"]: entry for entry in document["context_fields"]}
    assert len(contexts) == len(document["context_fields"])
    assert document["contract_version"] == "atlas-human-mmg-crosswalk-v1"
    assert document["crosswalk_version"] == "1.0.0"
    assert document["standards"]["mmg"]["version"] == "1.0.2"
    assert document["standards"]["mmg"]["published_on"] == "2022-05-10"
    assert document["standards"]["mmg"]["sha256"] == (
        "acf7fa235ad672b9404687c14c74adb13a6e6508dfd8cf37d3b2fcee4a5d930d"
    )
    assert document["standards"]["mmg"]["url"] == (
        "https://ndc.services.cdc.gov/wp-content/uploads/"
        "Lyme_TBRD_v1_0_2_MMG-and-TS_F_20220510.xlsx"
    )
    assert document["standards"]["vads_view"]["version"] == 6
    assert document["standards"]["vads_view"]["published_on"] == "2026-07-16"
    for entry in mappings:
        assert (entry["indicator_id"], entry["measure_id"]) in pairs
        for field in ("source_id", "dataset_id", "resource_key"):
            assert entry[field] == source[field]
        assert entry["source_definition_version"] == source["definition_version"]
        assert entry["source_vintage"] == source["vintage"]
        assert entry["source_fields"] and entry["transformation"] and entry["limitations"]
        assert entry["time_grain"] == "ANNUAL_SURVEILLANCE_YEAR"
        assert entry["geography_grain"] == (
            "STATE" if entry["measure_id"] == "state_unallocated_records_2023" else "COUNTY"
        )
        assert entry["mmg_field"] is None and entry["value_set"] is None
        assert set(entry["mmg_context_refs"]) <= contexts.keys()
        if entry["measure_id"] in {"case_count_floor_2023", "incidence_floor_2023"}:
            assert entry["match_type"] == "derived"
            assert set(entry["mmg_context_refs"]) == set(contexts)
        else:
            assert entry["match_type"] == "not applicable"
            assert not entry["mmg_context_refs"]
    context_pins = {
        "residence_county": (
            "narrower",
            "reviewed",
            "fips",
            "county_fips",
            "Subject Address County",
            "N/A: PID-11.9",
            "N/A",
            14,
        ),
        "surveillance_year": (
            "broader",
            "ambiguous",
            "year",
            "report_year",
            "MMWR Year",
            "77992-6",
            "LN",
            69,
        ),
        "case_category": (
            "narrower",
            "unsupported",
            "case_status",
            "case_status",
            "Case Class Status Code",
            "77990-0",
            "LN",
            50,
        ),
    }
    assert contexts.keys() == context_pins.keys()
    for identity, pins in context_pins.items():
        context = contexts[identity]
        match, status, source_field, conformed_field, name, identifier, code_system, row = pins
        assert context["match_type"] == match
        assert context["status"] == status
        assert context["source_field"] == source_field
        assert context["conformed_field"] == conformed_field
        assert context["mmg"] == {
            "name": name,
            "identifier": identifier,
            "code_system": code_system,
            "sheet": "Lyme TCSW",
            "row": row,
            "component": "GenV2",
        }
    assert contexts["surveillance_year"]["value_set"] is None
    assert contexts["surveillance_year"]["relationship_status"] == "unresolved_candidate"
    assert contexts["case_category"]["value_set"] is None
    assert contexts["case_category"]["unresolved_value_set_code"] == "PHVS_CaseClassStatus_NND"
    county = contexts["residence_county"]["value_set"]
    assert (county["code"], county["oid"], county["version"]) == (
        "PHVS_County_FIPS_6-4",
        "2.16.840.1.114222.4.11.829",
        7,
    )
    assert document["non_applicable_domains"] and document["unsupported"]


def test_committed_crosswalk_references_existing_semantics() -> None:
    validate(DOCUMENT)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("measure_id", "invented_case_count"),
        ("indicator_id", "new_human_indicator"),
        ("source_vintage", "2022"),
        ("dataset_id", "unapproved_dataset"),
        ("match_type", "exact"),
        ("mmg_context_refs", ["unknown_field"]),
    ],
)
def test_reject_incompatible_mapping(field: str, value: object) -> None:
    document = copy.deepcopy(DOCUMENT)
    document["mappings"][0][field] = value
    with pytest.raises(AssertionError):
        validate(document)


def test_reject_duplicate_or_missing_human_measure() -> None:
    document = copy.deepcopy(DOCUMENT)
    document["mappings"][1] = copy.deepcopy(document["mappings"][0])
    with pytest.raises(AssertionError):
        validate(document)


def test_reject_unreviewed_standards_update() -> None:
    document = copy.deepcopy(DOCUMENT)
    document["standards"]["vads_view"]["version"] = 7
    with pytest.raises(AssertionError):
        validate(document)


@pytest.mark.parametrize(
    ("context_id", "path", "value"),
    [
        (identity, ("match_type",), "exact")
        for identity in ("residence_county", "surveillance_year", "case_category")
    ]
    + [
        (identity, ("mmg", field), value)
        for identity in ("residence_county", "surveillance_year", "case_category")
        for field, value in (
            ("identifier", "invented"),
            ("row", 999),
            ("sheet", "TBRD TCSW"),
            ("component", "Lyme"),
            ("code_system", "invented"),
        )
    ]
    + [("surveillance_year", ("relationship_status",), "verified")],
)
def test_reject_changed_context_science(context_id: str, path: tuple, value: object) -> None:
    document = copy.deepcopy(DOCUMENT)
    context = next(entry for entry in document["context_fields"] if entry["id"] == context_id)
    target = context
    for field in path[:-1]:
        target = target[field]
    target[path[-1]] = value
    with pytest.raises(AssertionError):
        validate(document)


@pytest.mark.parametrize("measure_index", range(4))
def test_reject_changed_native_grain(measure_index: int) -> None:
    document = copy.deepcopy(DOCUMENT)
    document["mappings"][measure_index]["geography_grain"] = (
        "COUNTY" if measure_index == 3 else "STATE"
    )
    with pytest.raises(AssertionError):
        validate(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [("sha256", "0" * 64), ("url", "https://ndc.services.cdc.gov/invented.xlsx")],
)
def test_reject_changed_workbook_identity(field: str, value: str) -> None:
    document = copy.deepcopy(DOCUMENT)
    document["standards"]["mmg"][field] = value
    with pytest.raises(AssertionError):
        validate(document)


def test_synthetic_aggregate_example_preserves_existing_release_behavior() -> None:
    from lyme_gap_atlas_data.semantic_release import _human_values

    identity = {
        "45001": {"state": "SC", "population": 100_000},
        "45003": {"state": "SC", "population": 100_000},
    }
    rows = [
        {
            "report_year": 2023,
            "county_fips": "45001",
            "case_status": "Confirmed",
            "frequency": 3,
            "payload": {},
        },
        {
            "report_year": 2023,
            "county_fips": "45001",
            "case_status": "Probable",
            "frequency": 2,
            "payload": {},
        },
        {
            "report_year": 2023,
            "county_fips": "suppressed",
            "case_status": "Unknown",
            "frequency": 7,
            "payload": {"state": "SC"},
        },
    ]
    result = _human_values(rows, identity)
    assert result["45001"]["case_count"] == 5
    assert result["45001"]["incidence"] == 5.0
    assert result["45001"]["human_status"] == "published_count_floor"
    assert result["45003"]["case_count"] is None
    assert result["45003"]["incidence"] is None
    assert result["45003"]["human_status"] == "no_county_linked_record"
    assert result["45001"]["state_unallocated"] == result["45003"]["state_unallocated"] == 7
