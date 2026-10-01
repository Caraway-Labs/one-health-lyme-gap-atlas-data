"""Offline end-to-end existing mapper/lineage/consumer path for bounded climate."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import test_semantic_lineage as fixtures
from test_climate_publication import fixture_record
from test_climate_release import extension

from lyme_gap_atlas_data.climate_semantics import METHOD
from lyme_gap_atlas_data.semantic_consumer import project_consumer
from lyme_gap_atlas_data.semantic_domain import observation_key, revision_id
from lyme_gap_atlas_data.semantic_lineage import SemanticLineageError, validate_lineage
from lyme_gap_atlas_data.semantic_metadata import SemanticMetadataError
from lyme_gap_atlas_data.semantic_source_mappings import (
    _SOURCE_FIELDS,
    load_mapping_registry,
    map_record,
)


def case(monkeypatch):
    metadata = extension()["metadata"][0]
    monkeypatch.setattr(fixtures, "_metadata", lambda shape: copy.deepcopy(metadata))
    trace, authority = fixtures._trace("infected_tick_prevalence")
    mappings = load_mapping_registry(
        Path(__file__).parents[1]
        / "docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json"
    )
    mapping = mappings["nclimgrid_prcp"]
    version = metadata["provenance"]["source_version_id"]["value"]
    authority["source_versions"][version].update(
        resource_key=mapping["resource_key"],
        definition_version=2,
        approved=True,
    )
    tiger_version = "fixture-tiger-version"
    authority["source_versions"][tiger_version] = {
        "source_id": "fixture-census-tiger",
        "dataset_id": "fixture-tiger-2025",
        "resource_key": "fixture-tiger-resource-2025",
        "source_vintage": "2025",
        "publisher": "Census",
        "approved": True,
    }
    output = fixture_record(
        id=f"{mapping['resource_key']}:08013:2025-01-01:PRCP",
        county_fips="08013",
    )
    run = "fixture-climate-run"
    authority["runs"][run] = {
        "source_version_id": version,
        "dataset_id": mapping["dataset_id"],
        "input_source_versions": {tiger_version: "fixture-tiger-2025"},
    }
    for index, edge in enumerate(trace["edges"]):
        source_version = version if index == 0 else tiger_version
        source = authority["source_versions"][source_version]
        edge.update(
            {
                key: source[key]
                for key in (
                    "source_id",
                    "dataset_id",
                    "resource_key",
                    "source_vintage",
                    "publisher",
                )
            }
        )
        edge.update(
            source_version_id=source_version,
            ingestion_run_id=run,
            artifact_sha256=output["noaa_sha256" if index == 0 else "tiger_sha256"],
        )
        authority["artifacts"][edge["artifact_id"]].update(
            ingestion_run_id=run,
            source_version_id=source_version,
            sha256=edge["artifact_sha256"],
        )
        authority["records"][edge["record_id"]].update(
            ingestion_run_id=run,
            source_version_id=source_version,
        )
        authority["proofs"][edge["eligibility_ref"]]["source_version_id"] = source_version
    observation = trace["observation"]
    observation["temporal"] = {"semantics": "PERIOD", "start": "2025-01-01", "end": "2025-01-01"}
    observation.update(value=output["value"], value_state="ZERO")
    observation["provenance"].update(
        transformation_version=METHOD,
        evidence_basis="CURRENT_CODE_SOURCE_BACKED_REPLAY",
        lineage_sources=[
            {key: edge.get(key) for key in _SOURCE_FIELDS}
            | {"retrieved_at": "2026-09-24T00:00:00Z"}
            for edge in trace["edges"]
        ],
    )
    result = trace["result"]
    observation.update(
        quality_ref=result["result_id"],
        eligibility_ref=result["result_id"],
        limitations_ref=result["result_id"],
    )
    observation["observation_key"] = observation_key(observation, metadata["measure"])
    observation["revision_id"] = revision_id(observation)
    authority["results"][result["revision_id"]].update(
        semantic_revision_id=observation["revision_id"],
        transformation_version=METHOD,
        evidence_basis="CURRENT_CODE_SOURCE_BACKED_REPLAY",
    )
    record = {
        "mapping_id": "nclimgrid_prcp",
        "indicator_id": metadata["measure"]["indicator_id"],
        "source_output": output,
        "value": output["value"],
        "value_state": "ZERO",
        "unit": "mm",
        "denominator": "NONE",
        "geography": observation["geography"],
        "temporal": observation["temporal"],
        "edges": trace["edges"],
        "input_ids": trace["input_ids"],
        "output_dataset_id": observation["provenance"]["dataset_id"],
        "transformation_version": METHOD,
        "evidence_basis": "CURRENT_CODE_SOURCE_BACKED_REPLAY",
        "retrieved_at": "2026-09-24T00:00:00Z",
        "result": result,
        "transformation": trace["transformation"],
    }
    return record, metadata, authority, mappings


def test_existing_mapper_lineage_consumer_path_accepts_only_explicit_climate_authority(monkeypatch):
    record, metadata, authority, mappings = case(monkeypatch)
    approved = {metadata["revision_id"]}
    with pytest.raises(SemanticMetadataError):
        map_record(record, metadata, authority, mappings)
    mapped = map_record(
        record, metadata, authority, mappings, approved_climate_metadata_revisions=approved
    )
    lineage = mapped["lineage"]
    validate_lineage(lineage, authority, approved_climate_metadata_revisions=approved)
    consumer = project_consumer(lineage, authority, approved_climate_metadata_revisions=approved)
    assert consumer["observation"]["value"] == 0
    assert consumer["observation"]["value_state"] == "ZERO"
    assert consumer["measure"]["semantic_version"] == "2.0.0"
    with pytest.raises(SemanticMetadataError):
        project_consumer(lineage, authority)
    authority["artifacts"][record["edges"][1]["artifact_id"]]["sha256"] = "0" * 64
    with pytest.raises(SemanticLineageError, match="artifact"):
        project_consumer(lineage, authority, approved_climate_metadata_revisions=approved)
