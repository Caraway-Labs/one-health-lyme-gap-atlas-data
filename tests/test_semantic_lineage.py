"""Synthetic cross-layer trace and adversarial reference tests for Story #193."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lyme_gap_atlas_data.semantic_domain import CONTRACT_VERSION as DOMAIN_VERSION
from lyme_gap_atlas_data.semantic_domain import observation_key, revision_id
from lyme_gap_atlas_data.semantic_lineage import (
    CONTRACT_VERSION,
    SemanticLineageError,
    consumer_safe_lineage,
    lineage_id,
    validate_lineage,
    validate_lineages,
)
from lyme_gap_atlas_data.semantic_metadata import metadata_revision_id

METADATA = json.loads(
    (
        Path(__file__).parents[1]
        / "docs/contracts/semantic-domain/examples/story-191-safe-metadata-fixtures.json"
    ).read_text()
)
SHAPES = [
    "case_count_floor_2023",
    "svi_percentile_2022",
    "rucc_2023",
    "scapularis_status",
    "burgdorferi_status",
    "neon_collection",
    "neon_individual_pathogen_test",
    "infected_tick_prevalence",
    "surveillance_coverage",
    "source_only_evidence",
]


def _metadata(shape: str) -> dict:
    if shape == "source_only_evidence":
        item = copy.deepcopy(METADATA[0])
        item["measure"]["measure_id"] = shape
        item["measure"]["geography_grain"] = "SOURCE_ONLY_COUNTY"
        item["measure"]["allowed_value_states"] = ["UNKNOWN"]
        item["metadata_id"] = f"metadata:{shape}:1.0.0"
        item["definition"] = item["measure"]["definition"] = "Synthetic unresolved source geography"
        item["applicability"]["geography_grain"] = "SOURCE_ONLY_COUNTY"
        item["applicability"]["representativeness"] = "UNKNOWN"
        item["allowed_value_states"] = ["UNKNOWN"]
        item["limitations"].append(
            {
                "category": "REPRESENTATIVENESS",
                "code": "SOURCE_ONLY",
                "text": "No canonical county identity is established.",
            }
        )
        from lyme_gap_atlas_data.semantic_domain import meaning_signature

        item["meaning_signature"] = meaning_signature(item["measure"])
    else:
        item = copy.deepcopy(next(m for m in METADATA if m["measure"]["measure_id"] == shape))
    item["revision_id"] = metadata_revision_id(item)
    return item


def _trace(shape: str) -> tuple[dict, dict]:
    metadata = _metadata(shape)
    measure = metadata["measure"]
    derived = measure["origin"] == "DERIVED"
    site = measure["geography_grain"] == "SITE_EVENT"
    source_only = shape == "source_only_evidence"
    count = 2 if derived else 1
    source_id = metadata["provenance"]["source_id"]["value"]
    dataset_id = metadata["provenance"]["dataset_id"]["value"]
    version = metadata["provenance"]["source_version_id"]["value"]
    vintage = metadata["provenance"]["source_vintage"]["value"]
    publisher = metadata["provenance"]["publisher"]["value"]
    registry: dict = {
        k: {}
        for k in (
            "source_versions",
            "runs",
            "artifacts",
            "records",
            "proofs",
            "inputs",
            "results",
            "releases",
        )
    }
    registry["source_versions"][version] = {
        "source_id": source_id,
        "dataset_id": dataset_id,
        "resource_key": "product-v1",
        "source_vintage": vintage,
        "publisher": publisher,
    }
    edges = []
    for n in range(count):
        run_id, artifact_id, record_id = (
            f"run-{shape}-{n}",
            f"artifact-{shape}-{n}",
            f"record-{shape}-{n}",
        )
        source_record_id = f"source-record-{shape}-{n}"
        hash_value = f"{n + 1:064x}"
        edge = {
            "publisher": publisher,
            "source_id": source_id,
            "dataset_id": dataset_id,
            "resource_key": "product-v1",
            "source_version_id": version,
            "source_vintage": vintage,
            "ingestion_run_id": run_id,
            "artifact_id": artifact_id,
            "artifact_sha256": hash_value,
            "record_id": record_id,
            "source_record_id": source_record_id,
            "source_row_hash": None,
            "canonical_record_id": None if source_only else f"canonical-{shape}-{n}",
            "record_revision": "1",
            "record_kind": "SOURCE_ONLY" if source_only else "CANONICAL",
            "normalization_ref": None,
            "eligibility_ref": None,
        }
        if source_only:
            edge["unresolved_reason"] = "UNMAPPED"
        if shape in {
            "scapularis_status",
            "burgdorferi_status",
            "neon_collection",
            "neon_individual_pathogen_test",
        }:
            proof_id = f"normalization-{shape}-{n}"
            edge["normalization_ref"] = proof_id
            registry["proofs"][proof_id] = {
                "kind": "NORMALIZATION",
                "record_id": record_id,
                "source_version_id": version,
                "contract_version": "tick-surveillance-normalization-v1",
            }
        if derived:
            proof_id = f"eligibility-{shape}-{n}"
            edge["eligibility_ref"] = proof_id
            registry["proofs"][proof_id] = {
                "kind": "ELIGIBILITY",
                "record_id": record_id,
                "source_version_id": version,
                "contract_version": "surveillance-scientific-eligibility-v1",
            }
        registry["runs"][run_id] = {"source_version_id": version, "dataset_id": dataset_id}
        registry["artifacts"][artifact_id] = {
            "ingestion_run_id": run_id,
            "source_version_id": version,
            "sha256": hash_value,
        }
        registry["records"][record_id] = {
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
        edges.append(edge)
    geography = (
        {
            "grain": "SOURCE_ONLY_COUNTY",
            "reported_geography_id": "publisher-place-1",
            "county_fips": None,
            "mapping_status": "UNMAPPED",
        }
        if source_only
        else {
            "grain": "SITE_EVENT",
            "site_id": "BLAN",
            "event_id": f"event-{shape}",
            "county_fips": None,
            "representativeness": "NOT_COUNTY_REPRESENTATIVE",
        }
        if site
        else {
            "grain": "COUNTY",
            "county_fips": "08013",
            "representativeness": "COUNTY_NATIVE_STATUS",
        }
    )
    temporal = {"semantics": measure["temporal_semantics"]}
    if measure["temporal_semantics"] == "PERIOD":
        temporal.update(start="2023-01-01", end="2023-12-31")
    else:
        temporal["date"] = "2023-12-31"
    if derived:
        inputs = [f"input-{shape}-{n}" for n in range(count)]
        for n, input_id in enumerate(inputs):
            registry["inputs"][input_id] = edges[n]["record_id"]
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
            "dataset_id": "derived-product-v1",
            "transformation_version": metadata["provenance"]["transformation_version"]["value"],
            "input_ids": inputs,
            "lineage_sources": [
                {field: edge[field] for field in source_fields}
                | {"retrieved_at": "2026-09-24T00:00:00Z"}
                for edge in edges
            ],
            "evidence_basis": "SYNTHETIC_FIXTURE",
        }
    else:
        provenance = {
            key: edges[0][key]
            for key in (
                "source_id",
                "dataset_id",
                "source_version_id",
                "source_vintage",
                "ingestion_run_id",
                "artifact_id",
                "source_record_id",
            )
        } | {"retrieved_at": "2026-09-24T00:00:00Z"}
    observation = {
        "contract_version": DOMAIN_VERSION,
        "measure_id": measure["measure_id"],
        "measure_version": measure["semantic_version"],
        "unit": measure["unit"],
        "denominator": measure["denominator"],
        "origin": measure["origin"],
        "geography": geography,
        "temporal": temporal,
        "strata": {},
        "provenance": provenance,
        "value_state": "UNKNOWN" if source_only else "OBSERVED",
        "value": None if source_only else 3,
    }
    observation["observation_key"] = observation_key(observation, measure)
    observation["revision_id"] = revision_id(observation)
    result = None
    if derived:
        result = {"result_id": f"result-{shape}", "revision_id": f"result-revision-{shape}-1"}
        registry["results"][result["revision_id"]] = {
            "result_id": result["result_id"],
            "semantic_revision_id": observation["revision_id"],
            "evidence_basis": "SYNTHETIC_FIXTURE",
            "transformation_version": provenance["transformation_version"],
            "input_ids": inputs,
        }
    release = None
    if not derived and not site and not source_only:
        release = {
            "release_id": "fixture-release-1",
            "bundle_sha256": "a" * 64,
            "observation_id": f"release-observation-{shape}",
        }
        registry["releases"]["fixture-release-1"] = {
            "bundle_sha256": "a" * 64,
            "semantic_revision_ids": [observation["revision_id"]],
            "observation_ids": [release["observation_id"]],
        }
    lineage = {
        "contract_version": CONTRACT_VERSION,
        "visibility": "INTERNAL",
        "semantic_observation_id": observation["observation_key"],
        "semantic_revision_id": observation["revision_id"],
        "metadata_revision_id": metadata["revision_id"],
        "metadata": metadata,
        "observation": observation,
        "edges": edges,
        "input_ids": inputs if derived else [],
        "transformation": {
            "id": f"transformation-{shape}",
            "version": provenance.get("transformation_version", "release-builder-v1"),
            "methodology_version": measure["methodology_version"],
        },
        "result": result,
        "release": release,
    }
    lineage["lineage_id"] = lineage_id(lineage)
    return lineage, registry


@pytest.mark.parametrize("shape", SHAPES)
def test_complete_synthetic_trace(shape: str) -> None:
    lineage, registry = _trace(shape)
    validate_lineage(lineage, registry)
    safe = consumer_safe_lineage(lineage)
    assert safe["measure_id"] == shape
    assert safe["record_refs"]
    assert "artifact_id" not in json.dumps(safe)
    if shape.startswith("neon_"):
        assert safe["representativeness"] == "NOT_COUNTY_REPRESENTATIVE"
    if shape == "source_only_evidence":
        assert lineage["observation"]["geography"]["county_fips"] is None
        assert safe["release_id"] is None
    if shape in {"infected_tick_prevalence", "surveillance_coverage"}:
        assert len(lineage["edges"]) == 2


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda lineage, registry: registry["source_versions"].clear(), "orphan source_versions"),
        (
            lambda lineage, registry: lineage["edges"][0].update(source_version_id="wrong"),
            "orphan source_versions",
        ),
        (
            lambda lineage, registry: registry["runs"][
                lineage["edges"][0]["ingestion_run_id"]
            ].update(source_version_id="wrong"),
            "run/source version",
        ),
        (
            lambda lineage, registry: registry["artifacts"][
                lineage["edges"][0]["artifact_id"]
            ].update(ingestion_run_id="wrong"),
            "artifact/run",
        ),
        (
            lambda lineage, registry: lineage["edges"][0].update(artifact_sha256="0" * 64),
            "artifact hash",
        ),
        (
            lambda lineage, registry: lineage["edges"][0].update(source_record_id="wrong"),
            "record/source_record_id",
        ),
        (
            lambda lineage, registry: lineage["edges"][0].update(canonical_record_id="wrong"),
            "record/canonical_record_id",
        ),
        (
            lambda lineage, registry: lineage["edges"].append(copy.deepcopy(lineage["edges"][0])),
            "duplicate ambiguous",
        ),
        (
            lambda lineage, registry: lineage["transformation"].update(version=""),
            "transformation version",
        ),
        (
            lambda lineage, registry: lineage["edges"][0].update(normalization_ref="missing"),
            "orphan proofs",
        ),
        (
            lambda lineage, registry: lineage["release"].update(release_id="other"),
            "orphan releases",
        ),
    ],
)
def test_rejects_broken_county_chain(mutation, expected: str) -> None:
    lineage, registry = _trace("scapularis_status")
    mutation(lineage, registry)
    with pytest.raises(SemanticLineageError, match=expected):
        validate_lineage(lineage, registry)


def test_rejects_derived_input_and_basis_mismatch() -> None:
    lineage, registry = _trace("surveillance_coverage")
    registry["inputs"].clear()
    with pytest.raises(SemanticLineageError, match="orphan derived input"):
        validate_lineage(lineage, registry)
    lineage, registry = _trace("surveillance_coverage")
    lineage["observation"]["provenance"]["evidence_basis"] = "HISTORICAL_SOURCE_BACKED"
    lineage["observation"]["revision_id"] = revision_id(lineage["observation"])
    lineage["semantic_revision_id"] = lineage["observation"]["revision_id"]
    with pytest.raises(SemanticLineageError, match="invalid evidence-basis combination"):
        validate_lineage(lineage, registry)


def test_rejects_eligibility_and_result_revision_mismatch() -> None:
    lineage, registry = _trace("surveillance_coverage")
    proof = registry["proofs"][lineage["edges"][0]["eligibility_ref"]]
    proof["source_version_id"] = "wrong"
    with pytest.raises(SemanticLineageError, match="eligibility_ref/source version"):
        validate_lineage(lineage, registry)
    lineage, registry = _trace("surveillance_coverage")
    registry["results"][lineage["result"]["revision_id"]]["input_ids"] = ["other"]
    with pytest.raises(SemanticLineageError, match="result inputs"):
        validate_lineage(lineage, registry)


def test_rejects_cross_release_membership() -> None:
    lineage, registry = _trace("case_count_floor_2023")
    registry["releases"]["fixture-release-1"]["semantic_revision_ids"] = ["other"]
    with pytest.raises(SemanticLineageError, match="ambiguous cross-release"):
        validate_lineage(lineage, registry)


def test_consumer_projection_rejects_restricted_values() -> None:
    lineage, registry = _trace("case_count_floor_2023")
    lineage["visibility"] = "CONSUMER_SAFE"
    lineage["edges"][0]["record_id"] = "C:\\private\\raw.csv"
    with pytest.raises(SemanticLineageError):
        validate_lineage(lineage, registry)
    lineage, _ = _trace("case_count_floor_2023")
    lineage["metadata"]["limitations"][0]["text"] = "https://example.com/signed?token=secret"
    with pytest.raises(SemanticLineageError, match="restricted"):
        consumer_safe_lineage(lineage)


def test_ordering_and_duplicate_immutable_identity() -> None:
    lineage, registry = _trace("infected_tick_prevalence")
    shuffled = copy.deepcopy(lineage)
    shuffled["edges"].reverse()
    shuffled["input_ids"].reverse()
    assert lineage_id(shuffled) == lineage["lineage_id"]
    with pytest.raises(SemanticLineageError, match="duplicate immutable"):
        validate_lineages([lineage, lineage], registry)


def test_source_only_cannot_claim_release() -> None:
    lineage, registry = _trace("source_only_evidence")
    lineage["release"] = {
        "release_id": "fixture-release-1",
        "bundle_sha256": "a" * 64,
        "observation_id": "fabricated",
    }
    with pytest.raises(SemanticLineageError, match="invalid release inclusion"):
        validate_lineage(lineage, registry)
