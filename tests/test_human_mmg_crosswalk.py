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
        assert entry["mmg_field"] is None and entry["value_set"] is None
        assert set(entry["mmg_context_refs"]) <= contexts.keys()
        if entry["measure_id"] in {"case_count_floor_2023", "incidence_floor_2023"}:
            assert entry["match_type"] == "derived"
            assert set(entry["mmg_context_refs"]) == set(contexts)
        else:
            assert entry["match_type"] == "not applicable"
            assert not entry["mmg_context_refs"]
    assert contexts["surveillance_year"]["status"] == "ambiguous"
    assert contexts["case_category"]["status"] == "unsupported"
    assert contexts["case_category"]["value_set"] is None
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
