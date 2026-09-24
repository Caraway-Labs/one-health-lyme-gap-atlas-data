"""Synthetic cross-layer mappings; no source approval or runtime replay claim."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from test_infected_tick_results import _document
from test_neon_release_package import DEFINITION, _fixture
from test_semantic_lineage import _trace
from test_surveillance_coverage import _canonical
from test_surveillance_priority import _safe

from lyme_gap_atlas_data.infected_tick_metrics import DENSITY, PREVALENCE
from lyme_gap_atlas_data.ingestion.neon_release_package import NeonReleasePackageAdapter
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.semantic_domain import meaning_signature, observation_key, revision_id
from lyme_gap_atlas_data.semantic_metadata import metadata_revision_id
from lyme_gap_atlas_data.semantic_source_mappings import (
    SemanticMappingError,
    _source_value,
    load_mapping_registry,
    map_record,
    map_records,
)
from lyme_gap_atlas_data.surveillance_coverage import SAMPLING
from lyme_gap_atlas_data.surveillance_priority import evaluate_surveillance_priority
from lyme_gap_atlas_data.surveillance_priority_results import serialize_surveillance_priority
from lyme_gap_atlas_data.tick_normalization import normalize_value

REGISTRY = load_mapping_registry(
    Path(__file__).parents[1]
    / "docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json"
)
SHAPES = {
    "human_surveillance": "case_count_floor_2023",
    "svi": "svi_percentile_2022",
    "rucc": "rucc_2023",
    "county_tick_status": "scapularis_status",
    "county_pathogen_status": "burgdorferi_status",
    "neon_collection": "neon_collection",
    "neon_pathogen_test": "neon_individual_pathogen_test",
    "infected_tick_result": "infected_tick_prevalence",
    "coverage_result": "surveillance_coverage",
    "source_only": "source_only_evidence",
}


def _case(mapping_id: str) -> tuple[dict, dict, dict]:
    mapping = REGISTRY[mapping_id]
    trace, authority = _trace(SHAPES[mapping_id])
    metadata = trace["metadata"]
    measure = metadata["measure"]
    edges = trace["edges"]
    target_source = mapping.get("source_id", edges[0]["source_id"])
    target_dataset = mapping.get("dataset_id", edges[0]["dataset_id"])
    if mapping_id == "source_only":
        target_source = "cdc_tick"
        target_dataset = "county-tick-status"
        measure["temporal_semantics"] = "CUMULATIVE_THROUGH_DATE"
        metadata["applicability"]["temporal_semantics"] = "CUMULATIVE_THROUGH_DATE"
    metadata["provenance"]["source_id"]["value"] = target_source
    metadata["provenance"]["publisher"]["value"] = target_source
    metadata["provenance"]["dataset_id"]["value"] = target_dataset
    metadata["provenance"]["source_vintage"]["value"] = mapping["vintage"]
    metadata["freshness"]["source_vintage"]["value"] = mapping["vintage"]
    if mapping_id == "source_only":
        from lyme_gap_atlas_data.semantic_domain import meaning_signature

        metadata["meaning_signature"] = meaning_signature(measure)
    metadata["revision_id"] = metadata_revision_id(metadata)
    for edge in edges:
        edge["publisher"] = target_source
        edge["source_id"] = target_source
        edge["dataset_id"] = target_dataset
        edge["resource_key"] = mapping["resource_key"]
        edge["source_vintage"] = mapping["vintage"]
    version = edges[0]["source_version_id"]
    authority["source_versions"][version] = {
        "source_id": target_source,
        "dataset_id": target_dataset,
        "resource_key": mapping["resource_key"],
        "source_vintage": mapping["vintage"],
        "publisher": target_source,
        "definition_version": mapping["definition_version"],
        "approved": True,
        "product": mapping.get("product"),
    }
    for run in authority["runs"].values():
        run["dataset_id"] = target_dataset
    geography = copy.deepcopy(trace["observation"]["geography"])
    temporal = copy.deepcopy(trace["observation"]["temporal"])
    if mapping_id == "source_only":
        temporal = {"semantics": "CUMULATIVE_THROUGH_DATE", "date": "2025-12-31"}
    value = trace["observation"]["value"]
    if mapping_id == "neon_pathogen_test":
        value = 1
    if mapping_id == "coverage_result":
        value = "SAMPLED_EVENT"
    record = {
        "fixture": True,
        "mapping_id": mapping_id,
        "indicator_id": measure["indicator_id"],
        "unit": measure["unit"],
        "denominator": measure["denominator"],
        "denominator_value": 1
        if mapping_id == "neon_pathogen_test"
        else (3 if measure["denominator"] != "NONE" else None),
        "value": value,
        "value_state": trace["observation"]["value_state"],
        "geography": geography,
        "temporal": temporal,
        "strata": {},
        "edges": edges,
        "retrieved_at": "2026-09-24T00:00:00Z",
        "transformation": trace["transformation"],
        "result": trace["result"],
        "input_ids": trace["input_ids"],
        "release": None,
        "output_dataset_id": trace["observation"]["provenance"]["dataset_id"],
        "transformation_version": trace["transformation"]["version"],
        "evidence_basis": "SYNTHETIC_FIXTURE",
    }
    output = {mapping["field"]: value}
    if mapping_id == "source_only":
        output.update(mapping_status="UNMAPPED", reported_geography="publisher-place-1")
    elif mapping_id in {"neon_collection", "neon_pathogen_test"}:
        output.update(
            observation_type=(
                "COLLECTION_ABUNDANCE" if mapping_id == "neon_collection" else "PATHOGEN_TESTING"
            ),
            native_sampling_grain="SITE_EVENT",
            source_dataset_id=target_dataset,
            data_source_version_id=mapping["vintage"],
            source_record_id=edges[0]["source_record_id"],
            canonical_observation_id=edges[0]["canonical_record_id"],
            ingestion_run_id=edges[0]["ingestion_run_id"],
            artifact_id=edges[0]["artifact_id"],
            retrieved_at=record["retrieved_at"],
            source_agency="NSF NEON",
            sampling_site={"source_site_id": geography["site_id"]},
            sampling_event={"source_event_id": geography["event_id"]},
            county_relationship={"county_fips": None},
            surveillance_period_start=temporal["date"],
            surveillance_period_end=temporal["date"],
        )
        if mapping_id == "neon_pathogen_test":
            output["ticks_tested"] = 1
    elif mapping_id in {"infected_tick_result", "coverage_result"}:
        output.update(
            contract_version=(
                "infected-tick-derived-result-v1"
                if mapping_id == "infected_tick_result"
                else "surveillance-coverage-result-v2"
            ),
            result_id=record["result"]["result_id"],
            result_revision=record["result"]["revision_id"],
            native_grain="SITE_EVENT",
            date=temporal["date"],
            input_canonical_observation_ids=record["input_ids"],
            quality={},
        )
        if mapping_id == "infected_tick_result":
            output["state"] = "NUMERIC"
            output["evidence_status"] = {"calculation_basis": "SYNTHETIC_FIXTURE"}
            output["unavailable_reasons"] = []
        else:
            output["evidence_basis"] = "SYNTHETIC_FIXTURE"
            output["reason_codes"] = []
            output["scientific_eligibility"] = {}
    else:
        output["county_fips"] = geography["county_fips"]
    record["source_output"] = output
    native_values = {
        "tick_taxon": ("Ixodes scapularis", "DP1.10093.001"),
        "life_stage": ("nymph", "DP1.10093.001"),
        "collection_method": ("drag", "DP1.10093.001"),
        "pathogen_target": ("Borrelia burgdorferi sensu lato", "DP1.10092.001"),
    }
    record["strata_evidence"] = {}
    for field in mapping.get("required_strata", []):
        source_value, product = native_values[field]
        proof = normalize_value(
            field=field,
            source_value=source_value,
            publisher="NSF NEON",
            dataset_id=product,
            source_version="RELEASE-2026",
        )
        record["strata"][field] = proof.canonical_id
        record["strata_evidence"][field] = proof.as_contract_value()
    if mapping_id in {"neon_collection", "neon_pathogen_test"}:
        output["normalization"] = {
            "mappings": {
                item["mapping_rule_id"]: item for item in record["strata_evidence"].values()
            }
        }
    if trace["result"] is not None:
        expected = copy.deepcopy(trace["observation"])
        expected["strata"] = record["strata"]
        expected["value"] = value
        expected["value_state"] = record["value_state"]
        expected["quality_ref"] = record["result"]["result_id"]
        expected["eligibility_ref"] = record["result"]["result_id"]
        expected["limitations_ref"] = record["result"]["result_id"]
        expected["provenance"]["lineage_sources"] = [
            {
                key: edge.get(key)
                for key in (
                    "source_id",
                    "dataset_id",
                    "source_version_id",
                    "source_vintage",
                    "ingestion_run_id",
                    "artifact_id",
                    "source_record_id",
                    "source_row_hash",
                )
            }
            | {"retrieved_at": record["retrieved_at"]}
            for edge in edges
        ]
        expected["observation_key"] = observation_key(expected, measure)
        expected["revision_id"] = revision_id(expected)
        authority["results"][trace["result"]["revision_id"]]["semantic_revision_id"] = expected[
            "revision_id"
        ]
    return record, metadata, authority


@pytest.mark.parametrize("mapping_id", SHAPES)
def test_each_source_family_maps_with_exact_metadata_and_lineage(mapping_id: str) -> None:
    record, metadata, authority = _case(mapping_id)
    mapped = map_record(record, metadata, authority, REGISTRY, fixture_mode=True)
    assert mapped["mapping_id"] == mapping_id
    assert mapped["metadata_revision_id"] == metadata["revision_id"]
    assert mapped["lineage_id"] == mapped["lineage"]["lineage_id"]
    if mapping_id in {"infected_tick_result", "coverage_result"}:
        result_id = record["result"]["result_id"]
        assert mapped["observation"]["quality_ref"] == result_id
        assert mapped["observation"]["eligibility_ref"] == result_id
        assert mapped["observation"]["limitations_ref"] == result_id
    if mapping_id == "source_only":
        assert mapped["observation"]["geography"]["county_fips"] is None
        assert mapped["observation"]["value_state"] == "UNKNOWN"
    if mapping_id.startswith("neon_") or mapping_id in {"infected_tick_result", "coverage_result"}:
        assert mapped["observation"]["geography"]["representativeness"] == (
            "NOT_COUNTY_REPRESENTATIVE"
        )


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda r, m, a: r.update(mapping_id="missing"), "unknown source mapping"),
        (lambda r, m, a: a["source_versions"].clear(), "unknown governed source version"),
        (
            lambda r, m, a: a["source_versions"][r["edges"][0]["source_version_id"]].update(
                definition_version=9
            ),
            "wrong source definition version",
        ),
        (
            lambda r, m, a: r["edges"][0].update(publisher="wrong publisher"),
            "publisher mismatch",
        ),
        (
            lambda r, m, a: a["source_versions"][r["edges"][0]["source_version_id"]].update(
                approved=False
            ),
            "not approved",
        ),
        (lambda r, m, a: r["edges"][0].update(source_vintage="other"), "wrong source vintage"),
        (
            lambda r, m, a: r["source_output"].pop(REGISTRY["human_surveillance"]["field"]),
            "existing source output and mapped field required",
        ),
        (lambda r, m, a: r.update(unit="percent"), "incompatible unit"),
        (lambda r, m, a: r.update(denominator="people"), "incompatible denominator"),
        (
            lambda r, m, a: r["geography"].update(grain="SITE_EVENT"),
            "incompatible native geography",
        ),
        (
            lambda r, m, a: r["temporal"].update(semantics="POINT_IN_TIME"),
            "incompatible native geography or time",
        ),
    ],
)
def test_fail_closed_before_mapping(mutate, expected: str) -> None:  # type: ignore[no-untyped-def]
    record, metadata, authority = _case("human_surveillance")
    mutate(record, metadata, authority)
    with pytest.raises(ValueError, match=expected):
        map_record(record, metadata, authority, REGISTRY, fixture_mode=True)


def test_duplicate_observation_fails() -> None:
    record, metadata, authority = _case("human_surveillance")
    with pytest.raises(SemanticMappingError, match="duplicate semantic observation"):
        map_records(
            [record, copy.deepcopy(record)],
            {"human_surveillance": metadata},
            authority,
            REGISTRY,
            fixture_mode=True,
        )


def test_priority_result_retains_coverage_evidence_basis_and_revision() -> None:
    record, metadata, authority = _case("coverage_result")
    measure = metadata["measure"]
    measure["measure_id"] = "surveillance_priority"
    measure["methodology_version"] = "surveillance-priority-v1"
    measure["definition"] = metadata["definition"] = "Synthetic unordered priority disposition"
    metadata["metadata_id"] = "metadata:surveillance_priority:1.0.0"
    metadata["provenance"]["method_version"]["value"] = "surveillance-priority-v1"
    metadata["provenance"]["transformation_version"]["value"] = "surveillance-priority-v1"
    metadata["meaning_signature"] = meaning_signature(measure)
    metadata["revision_id"] = metadata_revision_id(metadata)
    record["mapping_id"] = "priority_result"
    record["source_output"] = {
        "contract_version": "surveillance-priority-result-v2",
        "disposition": "EVIDENCE_VERIFICATION",
        "result_id": record["result"]["result_id"],
        "result_revision": record["result"]["revision_id"],
        "evidence_basis": "SYNTHETIC_FIXTURE",
        "coverage_result_revision": "fixture-coverage-revision",
        "native_grain": "SITE_EVENT",
        "date": record["temporal"]["date"],
        "quality": {},
        "reason_codes": [],
        "scientific_eligibility": {},
    }
    record["value"] = "EVIDENCE_VERIFICATION"
    record["transformation_version"] = "surveillance-priority-v1"
    record["transformation"]["version"] = "surveillance-priority-v1"
    record["transformation"]["methodology_version"] = "surveillance-priority-v1"
    expected = copy.deepcopy(record)
    source_fields = (
        "source_id",
        "dataset_id",
        "source_version_id",
        "source_vintage",
        "ingestion_run_id",
        "artifact_id",
        "source_record_id",
        "source_row_hash",
    )
    provenance = {
        "dataset_id": record["output_dataset_id"],
        "transformation_version": record["transformation_version"],
        "input_ids": record["input_ids"],
        "evidence_basis": record["evidence_basis"],
        "lineage_sources": [
            {key: edge.get(key) for key in source_fields} | {"retrieved_at": record["retrieved_at"]}
            for edge in record["edges"]
        ],
    }
    expected["origin"] = "DERIVED"
    expected["provenance"] = provenance
    expected["measure_id"] = measure["measure_id"]
    expected["measure_version"] = measure["semantic_version"]
    expected["quality_ref"] = record["result"]["result_id"]
    expected["eligibility_ref"] = record["result"]["result_id"]
    expected["limitations_ref"] = record["result"]["result_id"]
    expected["strata"] = record["strata"]
    expected["observation_key"] = observation_key(expected, measure)
    expected["revision_id"] = revision_id(expected)
    result = record["result"]
    authority["results"][result["revision_id"]]["semantic_revision_id"] = expected["revision_id"]
    authority["results"][result["revision_id"]]["transformation_version"] = (
        "surveillance-priority-v1"
    )
    mapped = map_record(record, metadata, authority, REGISTRY, fixture_mode=True)
    assert mapped["observation"]["value"] == "EVIDENCE_VERIFICATION"
    assert mapped["observation"]["provenance"]["evidence_basis"] == "SYNTHETIC_FIXTURE"


@pytest.mark.parametrize(
    "change,expected",
    [
        (
            lambda r: r["strata"].update(tick_taxon="Ixodes scapularis"),
            "display-label canonical stratum",
        ),
        (
            lambda r: r["strata_evidence"]["tick_taxon"]["source_context"].update(
                source_version="RELEASE-2025"
            ),
            "wrong stratum source version",
        ),
        (
            lambda r: r["strata_evidence"]["tick_taxon"]["source_context"].update(
                dataset_id="DP1.99999.001"
            ),
            "wrong stratum source product",
        ),
        (
            lambda r: r["strata"].pop("tick_taxon"),
            "missing required canonical strata",
        ),
        (
            lambda r: r["edges"][0].update(normalization_ref=None),
            "missing exact-source normalization",
        ),
    ],
)
def test_neon_strata_fail_closed(change, expected: str) -> None:  # type: ignore[no-untyped-def]
    record, metadata, authority = _case("neon_collection")
    change(record)
    with pytest.raises(SemanticMappingError, match=expected):
        map_record(record, metadata, authority, REGISTRY, fixture_mode=True)


def test_globally_valid_but_wrong_canonical_id_fails() -> None:
    record, metadata, authority = _case("neon_collection")
    record["strata"]["tick_taxon"] = "IXODES_PACIFICUS"
    with pytest.raises(SemanticMappingError, match="canonical stratum"):
        map_record(record, metadata, authority, REGISTRY, fixture_mode=True)


def test_source_only_cannot_become_county() -> None:
    record, metadata, authority = _case("source_only")
    record["geography"]["county_fips"] = "08013"
    with pytest.raises(Exception, match="source-only evidence cannot have county FIPS"):
        map_record(record, metadata, authority, REGISTRY, fixture_mode=True)


def test_missing_metadata_and_lineage_fail_closed() -> None:
    record, metadata, authority = _case("human_surveillance")
    with pytest.raises(SemanticMappingError, match="missing mandatory metadata"):
        map_records([record], {}, authority, REGISTRY)
    record["edges"][0]["artifact_id"] = "missing-artifact"
    with pytest.raises(Exception, match="orphan artifacts"):
        map_record(record, metadata, authority, REGISTRY, fixture_mode=True)


def test_numeric_measure_requires_actual_positive_denominator() -> None:
    record, metadata, authority = _case("infected_tick_result")
    record["denominator_value"] = None
    with pytest.raises(SemanticMappingError, match="positive governed denominator"):
        map_record(record, metadata, authority, REGISTRY, fixture_mode=True)


def test_pending_example_metadata_cannot_map_live_record() -> None:
    record, metadata, authority = _case("human_surveillance")
    with pytest.raises(SemanticMappingError, match="unreviewed semantic metadata"):
        map_record(record, metadata, authority, REGISTRY)


@pytest.mark.parametrize(
    "mapping_id,observation_type",
    [("neon_collection", "COLLECTION_ABUNDANCE"), ("neon_pathogen_test", "PATHOGEN_TESTING")],
)
def test_neon_adapter_output_maps_at_native_event_grain(
    tmp_path: Path, mapping_id: str, observation_type: str
) -> None:
    _fixture(tmp_path)
    definition = load_source_definition(DEFINITION)
    adapter = NeonReleasePackageAdapter()
    acquired = adapter.acquire(definition, fixture_dir=tmp_path)
    canonical = next(
        item["record"]["canonical_observation"]
        for item in adapter.normalize(definition, acquired.payload).records
        if item["record"]["canonical_observation"]["observation_type"] == observation_type
    )
    record, metadata, authority = _case(mapping_id)
    edge = record["edges"][0]
    for source_field, edge_field in (
        ("source_record_id", "source_record_id"),
        ("canonical_observation_id", "canonical_record_id"),
        ("ingestion_run_id", "ingestion_run_id"),
        ("artifact_id", "artifact_id"),
    ):
        edge[edge_field] = canonical[source_field]
    authority["runs"] = {
        edge["ingestion_run_id"]: {
            "source_version_id": edge["source_version_id"],
            "dataset_id": edge["dataset_id"],
        }
    }
    authority["artifacts"] = {
        edge["artifact_id"]: {
            "source_version_id": edge["source_version_id"],
            "ingestion_run_id": edge["ingestion_run_id"],
            "sha256": edge["artifact_sha256"],
        }
    }
    authority["records"][edge["record_id"]] = {
        key: edge[key]
        for key in (
            "artifact_id",
            "ingestion_run_id",
            "source_version_id",
            "source_record_id",
            "source_row_hash",
            "canonical_record_id",
            "record_revision",
            "record_kind",
        )
    }
    record["source_output"] = canonical
    record["retrieved_at"] = canonical["retrieved_at"]
    record["value"] = canonical[REGISTRY[mapping_id]["field"]]
    record["value_state"] = "ZERO" if record["value"] == 0 else "OBSERVED"
    record["denominator_value"] = canonical.get("ticks_tested")
    record["geography"] = {
        "grain": "SITE_EVENT",
        "site_id": canonical["sampling_site"]["source_site_id"],
        "event_id": canonical["sampling_event"]["source_event_id"],
        "county_fips": canonical["county_relationship"]["county_fips"],
        "representativeness": "NOT_COUNTY_REPRESENTATIVE",
    }
    record["temporal"] = {
        "semantics": "POINT_IN_TIME",
        "date": canonical["surveillance_period_start"],
    }
    rule_ids = {
        "tick_taxon": {"TAXON_NEON_SCAPULARIS_V1"},
        "life_stage": {"LIFE_STAGE_NEON_NYMPH_V1", "LIFE_STAGE_NEON_NYMPH_CAPITALIZED_V1"},
        "collection_method": {"METHOD_NEON_DRAG_V1"},
        "pathogen_target": {"PATHOGEN_NEON_BBURG_SL_V1"},
    }
    rules = canonical["normalization"]["mappings"].values()
    evidence = {
        dimension: next(item for item in rules if item["mapping_rule_id"] in rule_ids[dimension])
        for dimension in REGISTRY[mapping_id]["required_strata"]
    }
    record["strata_evidence"] = evidence
    record["strata"] = {key: proof["canonical_id"] for key, proof in evidence.items()}
    mapped = map_record(record, metadata, authority, REGISTRY, fixture_mode=True)
    assert mapped["observation"]["value"] == canonical[REGISTRY[mapping_id]["field"]]
    assert mapped["observation"]["geography"]["site_id"] == "BLAN"
    assert mapped["observation"]["geography"]["county_fips"] is None


def test_owning_derived_serializers_supply_mapping_value_states() -> None:
    infected = _document(PREVALENCE)
    assert _source_value(
        {"source_output": infected, "value": infected["value"], "value_state": "OBSERVED"},
        REGISTRY["infected_tick_result"],
    ) == (1, "OBSERVED")
    coverage = _safe(SAMPLING, [_canonical(DENSITY)])
    assert _source_value(
        {"source_output": coverage, "value": coverage["state"], "value_state": "OBSERVED"},
        REGISTRY["coverage_result"],
    ) == ("SAMPLED_EVENT", "OBSERVED")
    priority = serialize_surveillance_priority(evaluate_surveillance_priority(coverage))
    assert _source_value(
        {"source_output": priority, "value": priority["disposition"], "value_state": "OBSERVED"},
        REGISTRY["priority_result"],
    ) == (priority["disposition"], "OBSERVED")


@pytest.mark.parametrize(
    "raw,value,state",
    [
        (0, 0, "ZERO"),
        (None, None, "MISSING"),
        ("Unknown", None, "UNKNOWN"),
        ("Suppressed", None, "SUPPRESSED"),
        ("Not reported", None, "NOT_REPORTED"),
        ("No records", "No records", "NO_RECORDS"),
        ("no_county_linked_record", "NO_COUNTY_LINKED_RECORD", "NO_COUNTY_LINKED_RECORD"),
    ],
)
def test_source_value_states_preserve_distinct_meanings(raw, value, state) -> None:  # type: ignore[no-untyped-def]
    mapping = {"id": "human_status", "field": "human_status"}
    source_output = {"human_status": raw, "value_state": state}
    assert _source_value(
        {"source_output": source_output, "value": value, "value_state": state}, mapping
    ) == (value, state)


@pytest.mark.parametrize(
    "patch,expected",
    [
        (
            lambda r: r["source_output"].update(source_record_id="other-record"),
            "canonical NEON source identity mismatch",
        ),
        (
            lambda r: r["source_output"].update(surveillance_period_start="2016-05-02"),
            "canonical NEON geography or time mismatch",
        ),
        (
            lambda r: r["source_output"].update(ticks_collected=99),
            "source output/value-state disagreement",
        ),
        (
            lambda r: r["source_output"]["normalization"].update(mappings={}),
            "canonical NEON normalization proof mismatch",
        ),
    ],
)
def test_native_output_disagreement_fails(patch, expected: str) -> None:  # type: ignore[no-untyped-def]
    record, metadata, authority = _case("neon_collection")
    patch(record)
    with pytest.raises(SemanticMappingError, match=expected):
        map_record(record, metadata, authority, REGISTRY, fixture_mode=True)


@pytest.mark.parametrize(
    "patch,expected",
    [
        (
            lambda r: r["source_output"].update(result_revision="changed"),
            "derived output identity or evidence mismatch",
        ),
        (
            lambda r: r["source_output"].update(evidence_basis="CURRENT_CODE_SOURCE_BACKED_REPLAY"),
            "derived output identity or evidence mismatch",
        ),
        (
            lambda r: r["source_output"].update(input_canonical_observation_ids=["other"]),
            "derived output input IDs mismatch",
        ),
        (lambda r: r["source_output"].pop("quality"), "derived output quality required"),
        (
            lambda r: r["source_output"].pop("scientific_eligibility"),
            "derived output eligibility required",
        ),
        (
            lambda r: r["source_output"].pop("reason_codes"),
            "derived output limitations required",
        ),
    ],
)
def test_derived_output_disagreement_fails(patch, expected: str) -> None:  # type: ignore[no-untyped-def]
    record, metadata, authority = _case("coverage_result")
    patch(record)
    with pytest.raises(SemanticMappingError, match=expected):
        map_record(record, metadata, authority, REGISTRY, fixture_mode=True)
