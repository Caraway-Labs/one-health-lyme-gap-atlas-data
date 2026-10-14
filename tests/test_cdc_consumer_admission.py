"""Controlled synthetic authority; no live approval or PROD acceptance claim.

Pinned source/release IDs exercise scope checks. All runs, records, workbook
hashes, attestations and reviewed revisions below are synthetic test objects.
No fixture_mode or approval argument is supplied to the production mapper.
"""

import copy
import json
from pathlib import Path

import pytest
from test_semantic_source_mappings import REGISTRY, _case

from lyme_gap_atlas_data.cdc_consumer_admission import BUNDLE_SHA256, RELEASE_ID, SLICES
from lyme_gap_atlas_data.semantic_consumer import project_consumer
from lyme_gap_atlas_data.semantic_lineage import SemanticLineageError, lineage_id, validate_lineage
from lyme_gap_atlas_data.semantic_metadata import metadata_revision_id, validate_metadata
from lyme_gap_atlas_data.semantic_source_mappings import map_record
from lyme_gap_atlas_data.surveillance_evidence_mapping import (
    normalize_county_evidence,
    project_surveillance_evidence,
)

PACKAGE = Path(__file__).parents[1] / "docs/contracts/semantic-domain/cdc-2025"


def controlled_case(name="scapularis_status", value="Reported", reviewed=True):
    """Fabricated review authority for negative/positive engineering tests only."""
    mapping_id = "county_tick_status" if name == "scapularis_status" else "county_pathogen_status"
    record, _, authority = _case(mapping_id)
    metadata = json.loads((PACKAGE / f"{name}.metadata.json").read_text())
    if reviewed:
        metadata["metadata_revision"] = 2
        metadata["steward_review"] = {
            "state": "REVIEWED",
            "reviewed_at": {"state": "KNOWN", "value": "2026-10-11"},
        }
        metadata["revision_id"] = metadata_revision_id(metadata)
    edge = record["edges"][0]
    old_version = edge["source_version_id"]
    scope = SLICES[name]
    version = scope["source_version_id"]
    edge.update(**scope, source_id="cdc_arbonet_tick_module", publisher="CDC")
    edge["source_row_hash"] = "b" * 64
    source = authority["source_versions"].pop(old_version)
    source.update(**scope, source_id=edge["source_id"], publisher="CDC")
    authority["source_versions"][version] = source
    for proof in authority["proofs"].values():
        proof["source_version_id"] = version
    run_id = edge["ingestion_run_id"]
    authority["runs"][run_id].update(source_version_id=version, dataset_id=scope["dataset_id"])
    evidence_id = "synthetic-evidence-run"
    evidence_version = "synthetic-evidence-version"
    authority["runs"][evidence_id] = {
        "source_version_id": evidence_version,
        "dataset_id": scope["dataset_id"],
    }
    authority["source_versions"][evidence_version] = dict(source)
    artifact = authority["artifacts"][edge["artifact_id"]]
    artifact.update(ingestion_run_id=evidence_id, source_version_id=evidence_version)
    retained = authority["records"][edge["record_id"]]
    retained.update(
        source_version_id=version,
        source_row_hash=edge["source_row_hash"],
        evidence_run_id=evidence_id,
        workbook_sha256=edge["artifact_sha256"],
        resource_key=scope["resource_key"],
        source_definition_version=1,
        county_fips=record["geography"]["county_fips"],
        coverage_state="OBSERVED",
    )
    retained[name] = value
    record.pop("fixture")
    record.update(value=value, value_state="NO_RECORDS" if value == "No records" else "OBSERVED")
    if value is None:
        record["value_state"] = "MISSING"
    record["source_output"] = {
        name: value,
        "value_state": record["value_state"],
        "county_fips": record["geography"]["county_fips"],
    }
    record["temporal"]["date"] = "2025-12-31"
    record["transformation"].update(
        version="tick-surveillance-v1", methodology_version="tick-surveillance-v1"
    )
    # Obtain the semantic revision without a release or exposure admission.
    internal = map_record(record, metadata, authority, REGISTRY)
    assert internal["lineage"]["visibility"] == "INTERNAL"
    record["release"] = {
        "release_id": RELEASE_ID,
        "bundle_sha256": BUNDLE_SHA256,
        "observation_id": "synthetic-release-observation",
    }
    authority["releases"][RELEASE_ID] = {
        "bundle_sha256": BUNDLE_SHA256,
        "semantic_revision_ids": [internal["observation"]["revision_id"]],
        "observation_ids": [record["release"]["observation_id"]],
        "observation_records": {record["release"]["observation_id"]: edge["record_id"]},
        "metadata_revision_ids": [metadata["revision_id"]],
        "restricted_source_publication_attestations": [
            {
                "attestation_id": "synthetic-final-copy",
                "semantic_release_id": RELEASE_ID,
                "resource_key": scope["resource_key"],
                "data_source_version_id": version,
                "attested_by": "SYNTHETIC_TEST_REVIEWER",
                "delivery_reference": "synthetic-delivery",
                "delivered_at": "2026-10-11T00:00:00Z",
            }
        ],
    }
    return record, metadata, authority


@pytest.mark.parametrize("name", SLICES)
def test_proposals_valid_and_pending_without_false_review(name):
    metadata = json.loads((PACKAGE / f"{name}.metadata.json").read_text())
    validate_metadata(metadata)
    assert metadata["steward_review"] == {
        "state": "PENDING",
        "reviewed_at": {"state": "UNKNOWN", "value": None},
    }
    assert set(metadata["authority"].values()) == {"GOVERNED_GENERATED"}


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("scapularis_status", "Established", "established"),
        ("scapularis_status", "Reported", "detected"),
        ("burgdorferi_status", "Present", "detected"),
        ("burgdorferi_status", "No records", "unknown"),
        ("burgdorferi_status", None, "unknown"),
        ("scapularis_status", "Unsupported publisher label", "unknown"),
    ],
)
def test_reviewed_exact_dual_run_projection_preserves_status(name, value, expected):
    data = controlled_case(name, value)
    before = copy.deepcopy(data)
    result = project_surveillance_evidence(*data, REGISTRY)
    assert result["surveillance_evidence"]["normalized_state"] == expected
    assert result["semantic"]["observation"]["value"] == value
    assert result["semantic"]["release"] == {"id": RELEASE_ID, "bundle_sha256": BUNDLE_SHA256}
    assert data == before
    serialized = json.dumps(result)
    edge = data[0]["edges"][0]
    for private in (
        edge["record_id"],
        edge["ingestion_run_id"],
        edge["artifact_id"],
        edge["source_record_id"],
        edge["artifact_sha256"],
        edge["source_row_hash"],
        "synthetic-evidence-run",
        "synthetic-delivery",
        "synthetic-final-copy",
    ):
        assert private not in serialized


def test_pending_metadata_stays_internal_and_consumer_rejects():
    data = controlled_case(reviewed=False)
    mapped = map_record(*data, REGISTRY)
    assert mapped["lineage"]["visibility"] == "INTERNAL"
    with pytest.raises(ValueError):
        project_surveillance_evidence(*data, REGISTRY)


@pytest.mark.parametrize(
    "field",
    ["metadata_revision_ids", "observation_records", "restricted_source_publication_attestations"],
)
def test_missing_release_admission_stays_internal(field):
    data = controlled_case()
    data[2]["releases"][RELEASE_ID].pop(field)
    mapped = map_record(*data, REGISTRY)
    assert mapped["lineage"]["visibility"] == "INTERNAL"
    with pytest.raises(ValueError):
        project_consumer(mapped["lineage"], data[2])


@pytest.mark.parametrize(
    "tamper",
    [
        "artifact_run",
        "artifact_version",
        "workbook_hash",
        "row_hash",
        "record_run",
        "record_source",
        "evidence_source",
        "evidence_approval",
        "same_run",
        "county",
        "publisher_value",
        "placeholder",
        "source_approval",
        "release_bundle",
        "release_revision",
        "source_version",
    ],
)
def test_mismatched_authority_fails_closed(tamper):
    record, metadata, authority = controlled_case()
    edge = record["edges"][0]
    retained = authority["records"][edge["record_id"]]
    artifact = authority["artifacts"][edge["artifact_id"]]
    if tamper == "artifact_run":
        artifact["ingestion_run_id"] = "wrong-run"
    elif tamper == "artifact_version":
        artifact["source_version_id"] = edge["source_version_id"]
    elif tamper == "workbook_hash":
        retained["workbook_sha256"] = "f" * 64
    elif tamper == "row_hash":
        retained["source_row_hash"] = "f" * 64
    elif tamper == "record_run":
        retained["ingestion_run_id"] = "wrong-run"
    elif tamper == "record_source":
        retained["source_version_id"] = "wrong-version"
    elif tamper == "evidence_source":
        authority["source_versions"]["synthetic-evidence-version"]["dataset_id"] = "wrong-dataset"
    elif tamper == "evidence_approval":
        authority["source_versions"]["synthetic-evidence-version"]["approved"] = False
    elif tamper == "same_run":
        retained["evidence_run_id"] = edge["ingestion_run_id"]
    elif tamper == "county":
        retained["county_fips"] = "99999"
    elif tamper == "publisher_value":
        retained["scapularis_status"] = "Established"
    elif tamper == "placeholder":
        retained["coverage_state"] = "UNKNOWN_SOURCE_COVERAGE"
    elif tamper == "source_approval":
        authority["source_versions"][edge["source_version_id"]]["approved"] = False
    elif tamper == "release_bundle":
        record["release"]["bundle_sha256"] = "f" * 64
    elif tamper == "release_revision":
        authority["releases"][RELEASE_ID]["semantic_revision_ids"] = []
    elif tamper == "source_version":
        edge["source_version_id"] = "unapproved-version"
    with pytest.raises(ValueError):
        project_surveillance_evidence(record, metadata, authority, REGISTRY)


def test_unknown_coverage_never_manufactures_publisher_lineage():
    record, metadata, authority = controlled_case("burgdorferi_status", None)
    assert normalize_county_evidence(record, REGISTRY[record["mapping_id"]]) == "unknown"
    authority["records"][record["edges"][0]["record_id"]]["coverage_state"] = (
        "UNKNOWN_SOURCE_COVERAGE"
    )
    record["edges"][0]["source_row_hash"] = None
    with pytest.raises(ValueError):
        project_surveillance_evidence(record, metadata, authority, REGISTRY)


def test_forged_consumer_visibility_cannot_bypass_release_admission():
    data = controlled_case()
    lineage = map_record(*data, REGISTRY)["lineage"]
    data[2]["releases"][RELEASE_ID]["metadata_revision_ids"] = []
    lineage["lineage_id"] = lineage_id(lineage)
    with pytest.raises(SemanticLineageError, match="admission authority"):
        validate_lineage(lineage, data[2])


@pytest.mark.parametrize("target", ["derivation", "evidence", "record", "both_missing"])
def test_direct_consumer_requires_exact_definition_authority(target):
    data = controlled_case()
    lineage = map_record(*data, REGISTRY)["lineage"]
    authority = data[2]
    version = data[0]["edges"][0]["source_version_id"]
    retained = authority["records"][data[0]["edges"][0]["record_id"]]
    if target == "both_missing":
        authority["source_versions"][version].pop("definition_version")
        retained.pop("source_definition_version")
    elif target == "record":
        retained["source_definition_version"] = 2
    else:
        selected = version if target == "derivation" else "synthetic-evidence-version"
        authority["source_versions"][selected]["definition_version"] = 2
    with pytest.raises(SemanticLineageError, match="definition version"):
        project_consumer(lineage, authority)
