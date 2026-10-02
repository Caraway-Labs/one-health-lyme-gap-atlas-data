"""DATA202 fixture evidence over existing SVI/RUCC contracts and gates."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from test_semantic_governance import BASELINE, _ReleaseConnection
from test_semantic_release import _manifest, _row
from test_semantic_source_mappings import REGISTRY, _case
from test_svi_context import _assembly, _synthetic_state_metadata

from lyme_gap_atlas_data import semantic_release as release
from lyme_gap_atlas_data.semantic_governance import (
    Outcome,
    SemanticGovernanceError,
    compare_mapping,
    compare_measure,
    compare_revision,
    validate_cross_contract,
    validate_historical_release_adapter,
)
from lyme_gap_atlas_data.semantic_lineage import SemanticLineageError
from lyme_gap_atlas_data.semantic_metadata import (
    SemanticMetadataError,
    metadata_revision_id,
    validate_metadata,
)
from lyme_gap_atlas_data.semantic_source_mappings import (
    SemanticMappingError,
    map_record,
    map_records,
)


def _pair() -> tuple[list[dict], dict, dict]:
    """Namespace synthetic authority versions, preserving actual source selectors."""
    records, metadata_by_mapping, combined = [], {}, {}
    for mapping_id in ("svi", "rucc"):
        record, metadata, authority = _case(mapping_id)
        old_version = record["edges"][0]["source_version_id"]
        version = f"fixture-version-{mapping_id}"
        authority["source_versions"][version] = authority["source_versions"].pop(old_version)
        for edge in record["edges"]:
            edge["source_version_id"] = version
        for group in ("runs", "artifacts", "records", "proofs"):
            for entry in authority[group].values():
                if entry.get("source_version_id") == old_version:
                    entry["source_version_id"] = version
        metadata["provenance"]["source_version_id"]["value"] = version
        metadata["revision_id"] = metadata_revision_id(metadata)
        authority["releases"] = {
            f"{mapping_id}-{key}": value for key, value in authority["releases"].items()
        }
        for group, entries in authority.items():
            target = combined.setdefault(group, {})
            assert not target.keys() & entries.keys()
            target.update(entries)
        records.append(record)
        metadata_by_mapping[mapping_id] = metadata
    return records, metadata_by_mapping, combined


def test_context_pair_composes_without_coercing_vintage_time_or_meaning() -> None:
    records, metadata, authority = _pair()
    mapped = map_records(records, metadata, authority, REGISTRY, fixture_mode=True)
    validate_cross_contract(
        [item["measure"] for item in metadata.values()],
        list(metadata.values()),
        [item["lineage"] for item in mapped],
        authority,
        {key: REGISTRY[key] for key in metadata},
        mapped,
    )
    svi, rucc = [item["observation"] for item in mapped]
    assert svi["geography"]["county_fips"] == rucc["geography"]["county_fips"] == "08013"
    assert svi["temporal"] == {"semantics": "PERIOD", "start": "2018-01-01", "end": "2022-12-31"}
    assert rucc["temporal"] == {"semantics": "POINT_IN_TIME", "date": "2023-12-31"}
    assert (svi["unit"], rucc["unit"]) == ("percentile", "code")
    assert (svi["provenance"]["source_vintage"], rucc["provenance"]["source_vintage"]) == (
        "2022",
        "2023",
    )
    assert (
        compare_measure(metadata["svi"]["measure"], metadata["rucc"]["measure"]).outcome
        == Outcome.NOT_COMPARABLE
    )
    for item in mapped:
        assert item["lineage"]["metadata"]["limitations"]
        assert (
            item["lineage"]["edges"][0]["source_version_id"]
            == f"fixture-version-{item['mapping_id']}"
        )


@pytest.mark.parametrize("mapping_id", ["svi", "rucc"])
@pytest.mark.parametrize("group", ["runs", "artifacts", "records"])
def test_pair_rejects_borrowed_cross_source_lineage(mapping_id: str, group: str) -> None:
    records, metadata, authority = _pair()
    index = 0 if mapping_id == "svi" else 1
    key = {"runs": "ingestion_run_id", "artifacts": "artifact_id", "records": "record_id"}[group]
    own_edge, foreign_edge = records[index]["edges"][0], records[1 - index]["edges"][0]
    authority[group][own_edge[key]] = copy.deepcopy(authority[group][foreign_edge[key]])
    with pytest.raises((SemanticMappingError, SemanticLineageError)):
        map_records(records, metadata, authority, REGISTRY, fixture_mode=True)


def test_pair_keeps_duplicate_and_revision_policies_separate() -> None:
    records, metadata, authority = _pair()
    mapped = map_records(records, metadata, authority, REGISTRY, fixture_mode=True)
    with pytest.raises(SemanticMappingError, match="duplicate"):
        map_records([*records, records[0]], metadata, authority, REGISTRY, fixture_mode=True)
    revised = copy.deepcopy(records[0])
    revised["source_output"]["RPL_THEMES"] = revised["value"] = 0.75
    changed = map_record(revised, metadata["svi"], authority, REGISTRY, fixture_mode=True)
    assert (
        compare_revision(mapped[0]["observation"], changed["observation"]).outcome
        == Outcome.REQUIRES_NEW_REVISION
    )
    assert mapped[0]["observation"]["value"] == 0.5
    assert mapped[1]["observation"]["value"] == records[1]["value"]


@pytest.mark.parametrize("mapping_id,old_vintage", [("svi", "2020"), ("rucc", "2013")])
def test_replaced_context_vintage_requires_revision_and_cannot_join_silently(
    mapping_id: str, old_vintage: str
) -> None:
    records, metadata, authority = _pair()
    rule = REGISTRY[mapping_id]
    assert (
        compare_mapping(rule, dict(rule, vintage=old_vintage)).reason_code
        == "SOURCE_VINTAGE_CHANGED"
    )
    authority["source_versions"][f"fixture-version-{mapping_id}"]["source_vintage"] = old_vintage
    with pytest.raises(SemanticMappingError):
        map_records(records, metadata, authority, REGISTRY, fixture_mode=True)


@pytest.mark.parametrize("mapping_id", ["svi", "rucc"])
def test_old_valid_context_keeps_unknown_publisher_availability(mapping_id: str) -> None:
    _, metadata, _ = _pair()
    item = metadata[mapping_id]
    item["freshness"]["retrieved_at"] = {"state": "KNOWN", "value": "2026-10-02T00:00:00Z"}
    item["revision_id"] = metadata_revision_id(item)
    validate_metadata(item)
    assert item["freshness"]["published_at"] == {"state": "UNKNOWN", "value": None}
    assert item["freshness"]["source_vintage"]["value"] == REGISTRY[mapping_id]["vintage"]
    assert item["freshness"]["metadata_revised_at"]["value"] != "2026-10-02"


@pytest.mark.parametrize("mapping_id", ["svi", "rucc"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("published_at", "2026-10-02T00:00:00Z"),
        ("retrieved_at", "2022"),
        ("observation_period", "2026-10-02T00:00:00Z"),
    ],
)
def test_availability_retrieval_and_observation_time_shapes_cannot_be_interchanged(
    mapping_id: str, field: str, value: str
) -> None:
    _, metadata, _ = _pair()
    item = metadata[mapping_id]
    item["freshness"][field] = {"state": "KNOWN", "value": value}
    item["revision_id"] = metadata_revision_id(item)
    with pytest.raises(SemanticMetadataError):
        validate_metadata(item)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("unit", "percent", "UNIT_INCOMPATIBLE"),
        ("denominator", "population", "DENOMINATOR_INCOMPATIBLE"),
    ],
)
def test_context_unit_or_denominator_drift_reuses_measure_governance(
    field: str, value: str, reason: str
) -> None:
    _, metadata, _ = _pair()
    measure = metadata["svi"]["measure"]
    drifted = dict(measure, **{field: value})
    assert compare_measure(measure, drifted).reason_code == reason


def test_missing_svi_does_not_replace_rucc_or_erase_its_lineage() -> None:
    records, metadata, authority = _pair()
    records[0]["source_output"]["RPL_THEMES"] = -999
    records[0].update(value=None, value_state="MISSING")
    metadata["svi"] = _synthetic_state_metadata(metadata["svi"])
    mapped = map_records(records, metadata, authority, REGISTRY, fixture_mode=True)
    assert (mapped[0]["observation"]["value"], mapped[0]["observation"]["value_state"]) == (
        None,
        "MISSING",
    )
    assert mapped[1]["observation"]["value"] == records[1]["value"]
    assert mapped[1]["lineage"]["edges"] == records[1]["edges"]


def _county_pair(monkeypatch: pytest.MonkeyPatch) -> tuple[object, dict, dict]:
    manifest, rows, gates = _assembly(monkeypatch)
    monkeypatch.setattr(release, "EXPECTED_COUNTIES", 2)
    for source_key, field in (
        ("context_svi", "STCNTY"),
        ("context_rucc", "FIPS"),
        ("tick", "FIPSCode"),
        ("pathogen", "FIPSCode"),
    ):
        row = copy.deepcopy(rows[source_key][0])
        row["payload"][field] = "01001"
        rows[source_key].append(row)
    rows["context_svi"][1]["payload"].update(
        STATE="Alabama", ST_ABBR="AL", COUNTY="Autauga", RPL_THEMES=0, EPL_UNINSUR=0, EP_UNINSUR=0
    )
    for fips in ("08001", "01001"):
        rows["human"].append(
            _row({}, county_fips=fips, report_year=2023, case_status="Confirmed", frequency=5)
        )
    return manifest, rows, gates


def test_county_join_preserves_zero_partial_missingness_and_denominator_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, rows, gates = _county_pair(monkeypatch)
    rows["context_svi"][0]["payload"]["E_TOTPOP"] = -999
    counties, observations = release._assemble_counties(manifest, rows, gates)
    assert len(counties) == 2 and len(observations) == 28
    values = {(row[3], row[2]): row for row in observations}
    assert values["01001", "svi_percentile_2022"][10:12] == ("0.0", "ZERO")
    assert values["08001", "population_2022"][10:12] == (None, "MISSING")
    assert values["08001", "incidence_floor_2023"][10:12] == (None, "MISSING")
    assert values["08001", "case_count_floor_2023"][10:12] == ("5", "OBSERVED")
    assert values["08001", "rucc_2023"][10:12] == ("4", "OBSERVED")
    with pytest.raises(SemanticGovernanceError, match="HISTORICAL_INPUTS_INCOMPLETE"):
        validate_historical_release_adapter("incidence_floor_2023", "COUNTY", ["human"], BASELINE)
    validate_historical_release_adapter(
        "incidence_floor_2023", "COUNTY", ["human", "context_svi"], BASELINE
    )


def test_same_row_count_does_not_prove_county_alignment(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, rows, gates = _county_pair(monkeypatch)
    rows["context_rucc"][1]["payload"]["FIPS"] = "08013"
    with pytest.raises(release.SemanticReleaseBlocked, match="does not cover every"):
        release._assemble_counties(manifest, rows, gates)


@pytest.mark.parametrize("source_key", ["context_svi", "context_rucc"])
def test_old_source_vintage_with_passing_quality_remains_valid(source_key: str) -> None:
    source = _manifest().source(source_key)
    source = replace(
        source, vintage="2022 (2018-2022 ACS)" if source_key == "context_svi" else "2023"
    )
    captured = datetime(2026, 10, 2, tzinfo=UTC)
    connection = _ReleaseConnection(
        [
            ("APPROVED", "fixture-decision", None),
            ("SUCCEEDED",),
            ("a" * 64,),
            (1, 0),
            (captured,),
            (captured,),
        ]
    )
    gate = release._verify_source_gate(connection.sql, source)
    assert gate.source == source and gate.retrieved_at == captured


@pytest.mark.parametrize("source_key", ["context_svi", "context_rucc"])
@pytest.mark.parametrize("quality", [(0, 0), (1, 1)])
def test_missing_or_failed_context_quality_cannot_replace_last_release(
    monkeypatch: pytest.MonkeyPatch, source_key: str, quality: tuple[int, int]
) -> None:
    manifest = _manifest()
    selected = manifest.source(source_key)
    manifest = replace(
        manifest,
        sources=(
            selected,
            *(source for source in manifest.sources if source.source_key != source_key),
        ),
    )
    connection = _ReleaseConnection(
        [(0,), ("APPROVED", "fixture-decision", None), ("SUCCEEDED",), ("a" * 64,), quality]
    )
    monkeypatch.setattr(release, "load_manifest", lambda _path: manifest)
    monkeypatch.setattr(release, "connect", lambda _settings: connection)
    with pytest.raises(release.SemanticReleaseBlocked, match="passing blocking quality evidence"):
        release.build_semantic_release(
            SimpleNamespace(snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_DEV"), "fixture.json"
        )
    assert connection.rolled_back and not connection.committed
    assert not any(
        "SEMANTIC_RELEASE_POINTER" in sql or "INSERT INTO PRESENTATION" in sql
        for sql in connection.sql.statements
    )
