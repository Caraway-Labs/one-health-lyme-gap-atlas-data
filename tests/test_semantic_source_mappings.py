"""Synthetic cross-layer mappings; no source approval or runtime replay claim."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from test_semantic_lineage import _trace

from lyme_gap_atlas_data.semantic_domain import meaning_signature, observation_key, revision_id
from lyme_gap_atlas_data.semantic_metadata import metadata_revision_id
from lyme_gap_atlas_data.semantic_source_mappings import (
    SemanticMappingError,
    load_mapping_registry,
    map_record,
    map_records,
)
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
    record = {
        "fixture": True,
        "mapping_id": mapping_id,
        "indicator_id": measure["indicator_id"],
        "unit": measure["unit"],
        "denominator": measure["denominator"],
        "denominator_value": 3 if measure["denominator"] != "NONE" else None,
        "fields": {mapping["field"]: value},
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
    if trace["result"] is not None:
        expected = copy.deepcopy(trace["observation"])
        expected["strata"] = record["strata"]
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
        (lambda r, m, a: r["fields"].clear(), "missing required canonical field"),
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
    record["fields"] = {"disposition": "EVIDENCE_VERIFICATION"}
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
    expected["quality_ref"] = None
    expected["eligibility_ref"] = None
    expected["limitations_ref"] = None
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
