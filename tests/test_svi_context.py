"""DATA199 source-specific fixtures; no source approval or live replay claim."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

import pytest
from test_semantic_release import _manifest, _row
from test_semantic_source_mappings import REGISTRY, _case

from lyme_gap_atlas_data import semantic_release
from lyme_gap_atlas_data.ingestion.adapters import HttpJsonAdapter
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.semantic_release import SemanticReleaseBlocked, SourceGate
from lyme_gap_atlas_data.semantic_source_mappings import (
    SemanticMappingError,
    _source_value,
    map_record,
)
from lyme_gap_atlas_data.svi_context import TRANSFORMATION_VERSION, numeric_value

FIELDS = ("E_TOTPOP", "RPL_THEMES", "EPL_UNINSUR", "EP_UNINSUR")


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("raw", [None, "", -999, "-999", -999.0])
def test_missing_and_sentinel_never_become_observed_numbers(field: str, raw: Any) -> None:
    assert numeric_value(field, raw) is None


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("raw", [True, False, -1, "bad", float("nan"), float("inf")])
def test_invalid_native_numbers_fail_closed(field: str, raw: Any) -> None:
    with pytest.raises(ValueError, match="SVI"):
        numeric_value(field, raw)


@pytest.mark.parametrize(
    "field,maximum", [("RPL_THEMES", 1), ("EPL_UNINSUR", 1), ("EP_UNINSUR", 100)]
)
def test_percentage_and_percentile_domains_remain_distinct(field: str, maximum: int) -> None:
    assert numeric_value(field, 0) == 0
    assert numeric_value(field, maximum) == maximum
    with pytest.raises(ValueError, match="domain"):
        numeric_value(field, maximum + 0.01)
    assert numeric_value("E_TOTPOP", 519572) == 519572


def _assembly(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, dict, dict]:
    monkeypatch.setattr(semantic_release, "EXPECTED_COUNTIES", 1)
    manifest = _manifest()
    gates = {
        source.source_key: SourceGate(source, datetime(2026, 10, 2, tzinfo=UTC))
        for source in manifest.sources
    }
    rows = {
        "context_svi": [
            _row(
                {
                    "STCNTY": "08001",
                    "COUNTY": "Adams",
                    "ST_ABBR": "CO",
                    "STATE": "Colorado",
                    "E_TOTPOP": 100,
                    "RPL_THEMES": 0.5,
                    "EPL_UNINSUR": 0.25,
                    "EP_UNINSUR": 5,
                    "geometry": {"type": "Polygon", "coordinates": []},
                }
            )
        ],
        "context_rucc": [_row({"FIPS": "08001", "Attribute": "RUCC_2023", "Value": "4"})],
        "human": [],
        "tick": [
            _row(
                {
                    "FIPSCode": "08001",
                    "Ixodes_scapularis_County_Status": "Established",
                    "Ixodes_pacificus_county_status": "No records",
                }
            )
        ],
        "pathogen": [_row({"FIPSCode": "08001", "burgdorferi_status": "No records"})],
    }
    return manifest, rows, gates


@pytest.mark.parametrize(
    "field,measure",
    [
        ("E_TOTPOP", "population_2022"),
        ("RPL_THEMES", "svi_percentile_2022"),
        ("EPL_UNINSUR", "uninsured_percentile_2022"),
        ("EP_UNINSUR", "uninsured_percent_2022"),
    ],
)
def test_release_sentinel_preserves_raw_and_exact_lineage(
    monkeypatch: pytest.MonkeyPatch, field: str, measure: str
) -> None:
    manifest, rows, gates = _assembly(monkeypatch)
    rows["context_svi"][0]["payload"][field] = -999
    retained = copy.deepcopy(rows)
    _, observations = semantic_release._assemble_counties(manifest, rows, gates)
    observation = next(row for row in observations if row[2] == measure)
    assert observation[10:12] == (None, "MISSING")
    assert observation[5:8] == ("version-context_svi", "run-context_svi", "artifact-context_svi")
    assert observation[15] == TRANSFORMATION_VERSION
    assert rows == retained
    assert (
        next(row for row in observations if row[2] == "rucc_2023")[15]
        == semantic_release.SEMANTIC_TRANSFORMATION
    )


@pytest.mark.parametrize(
    "mutation,expected",
    [("duplicate", "duplicate"), ("fips", "invalid county FIPS"), ("range", "domain")],
)
def test_release_rejects_invalid_svi_identity_or_values(
    monkeypatch: pytest.MonkeyPatch, mutation: str, expected: str
) -> None:
    manifest, rows, gates = _assembly(monkeypatch)
    if mutation == "duplicate":
        rows["context_svi"].append(copy.deepcopy(rows["context_svi"][0]))
    elif mutation == "fips":
        rows["context_svi"][0]["payload"]["STCNTY"] = "8001"
    else:
        rows["context_svi"][0]["payload"]["RPL_THEMES"] = 1.01
    with pytest.raises(SemanticReleaseBlocked, match=expected):
        semantic_release._assemble_counties(manifest, rows, gates)


def test_generic_normalization_keeps_publisher_sentinel_and_geometry() -> None:
    definition = load_source_definition("config/sources/cdc_atsdr_svi_2022_county.yml")
    row = {
        "STCNTY": "08001",
        "RPL_THEMES": -999,
        "geometry": {"type": "Polygon", "coordinates": []},
    }
    normalized = HttpJsonAdapter().normalize(definition, {"sample": [row]})
    assert normalized.records[0]["record"] == row
    assert normalized.records[0]["temporal_semantics"] == "SVI_2022_ACS_2018_2022"


def test_semantic_svi_mapper_has_same_numeric_boundary() -> None:
    assert _source_value(
        {"source_output": {"RPL_THEMES": -999}, "value": None, "value_state": "MISSING"},
        REGISTRY["svi"],
    ) == (
        None,
        "MISSING",
    )
    assert _source_value(
        {"source_output": {"RPL_THEMES": 0}, "value": 0, "value_state": "ZERO"}, REGISTRY["svi"]
    ) == (0, "ZERO")
    with pytest.raises(SemanticMappingError, match="domain"):
        _source_value({"source_output": {"RPL_THEMES": 1.1}}, REGISTRY["svi"])


def test_svi_mapping_rejects_cross_vintage_authority() -> None:
    record, metadata, authority = _case("svi")
    authority["source_versions"][record["edges"][0]["source_version_id"]]["source_vintage"] = "2020"
    with pytest.raises(SemanticMappingError):
        map_record(record, metadata, authority, REGISTRY, fixture_mode=True)


def test_svi_mapping_rejects_observation_period_coercion() -> None:
    record, metadata, authority = _case("svi")
    record["value"] = record["source_output"]["RPL_THEMES"] = 0.5
    record["temporal"] = {"semantics": "PERIOD", "start": "2018-01-01", "end": "2022-12-31"}
    mapped = map_record(record, metadata, authority, REGISTRY, fixture_mode=True)
    assert mapped["observation"]["temporal"] == record["temporal"]
    record["temporal"] = {"semantics": "PERIOD", "start": "2023-01-01", "end": "2023-12-31"}
    with pytest.raises(SemanticMappingError, match="ACS observation period"):
        map_record(record, metadata, authority, REGISTRY, fixture_mode=True)


def test_svi_mapping_preserves_matching_county_fips() -> None:
    record, metadata, authority = _case("svi")
    assert record["source_output"]["county_fips"] == record["geography"]["county_fips"]
    mapped = map_record(record, metadata, authority, REGISTRY, fixture_mode=True)
    assert (
        mapped["observation"]["geography"]["county_fips"] == record["source_output"]["county_fips"]
    )


@pytest.mark.parametrize("source_fips", ["08001", "01001"])
def test_svi_mapping_rejects_differing_valid_county_fips(source_fips: str) -> None:
    record, metadata, authority = _case("svi")
    assert record["geography"]["county_fips"] == "08013"
    record["source_output"]["county_fips"] = source_fips
    with pytest.raises(SemanticMappingError, match="county source output/FIPS mismatch"):
        map_record(record, metadata, authority, REGISTRY, fixture_mode=True)
