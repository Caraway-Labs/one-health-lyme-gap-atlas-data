"""Synthetic consumer contract tests; no live publication or source replay."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from test_semantic_lineage import _trace

from lyme_gap_atlas_data.semantic_consumer import (
    CONTRACT_VERSION,
    SemanticConsumerError,
    canonical_consumer_json,
    page_consumer,
    project_consumer,
)
from lyme_gap_atlas_data.semantic_domain import meaning_signature, revision_id
from lyme_gap_atlas_data.semantic_lineage import lineage_id
from lyme_gap_atlas_data.semantic_metadata import metadata_revision_id

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads(
    (ROOT / "docs/contracts/semantic-domain/atlas-semantic-consumer-v1.schema.json").read_text()
)
EXAMPLES = json.loads(
    (
        ROOT / "docs/contracts/semantic-domain/examples/story-194-consumer-safe-fixtures.json"
    ).read_text()
)


def _safe_case(shape: str = "case_count_floor_2023") -> tuple[dict, dict]:
    trace, authority = _trace(shape)
    trace["visibility"] = "CONSUMER_SAFE"
    trace["metadata"]["visibility"] = "CONSUMER_SAFE"
    trace["metadata"]["revision_id"] = metadata_revision_id(trace["metadata"])
    trace["metadata_revision_id"] = trace["metadata"]["revision_id"]
    trace["lineage_id"] = lineage_id(trace)
    return trace, authority


@pytest.mark.parametrize(
    "shape",
    [
        "case_count_floor_2023",
        "svi_percentile_2022",
        "rucc_2023",
        "scapularis_status",
        "burgdorferi_status",
        "neon_collection",
        "neon_individual_pathogen_test",
        "source_only_evidence",
    ],
)
def test_representative_safe_shapes_are_deterministic_fixture_only(shape: str) -> None:
    trace, authority = _safe_case(shape)
    result = project_consumer(trace, authority, fixture_mode=True)
    assert result["contract_version"] == CONTRACT_VERSION
    assert result["evidence_tier"] == "SYNTHETIC_FIXTURE"
    assert result["measure"]["id"] == shape
    assert canonical_consumer_json(result) == canonical_consumer_json(
        project_consumer(trace, authority, fixture_mode=True)
    )
    serialized = canonical_consumer_json(result)
    for forbidden in ("artifact_id", "ingestion_run_id", "source_row_hash", "private_key"):
        assert forbidden not in serialized
    if shape.startswith("neon_"):
        assert (
            result["observation"]["geography"]["representativeness"] == "NOT_COUNTY_REPRESENTATIVE"
        )
    if shape == "source_only_evidence":
        assert result["observation"]["geography"]["county_fips"] is None
        assert result["observation"]["value_state"] == "UNKNOWN"
        assert result["release"] is None


@pytest.mark.parametrize("shape", ["infected_tick_prevalence", "surveillance_coverage"])
def test_internal_derived_products_stay_unavailable(shape: str) -> None:
    trace, authority = _trace(shape)
    with pytest.raises(SemanticConsumerError, match="internal"):
        project_consumer(trace, authority, fixture_mode=True)


def test_internal_and_pending_review_fail_closed() -> None:
    trace, authority = _trace("case_count_floor_2023")
    with pytest.raises(SemanticConsumerError, match="lineage is internal"):
        project_consumer(trace, authority)
    trace, authority = _safe_case()
    with pytest.raises(SemanticConsumerError, match="reviewed"):
        project_consumer(trace, authority)


def test_restricted_value_and_unsafe_lineage_are_rejected() -> None:
    trace, authority = _safe_case()
    trace["metadata"]["label"] = "C:\\private\\workbook.xlsx"
    trace["metadata"]["revision_id"] = metadata_revision_id(trace["metadata"])
    trace["metadata_revision_id"] = trace["metadata"]["revision_id"]
    trace["lineage_id"] = lineage_id(trace)
    with pytest.raises(ValueError, match="restricted"):
        project_consumer(trace, authority, fixture_mode=True)


def test_invalid_science_fails_before_projection() -> None:
    trace, authority = _safe_case()
    trace["observation"]["unit"] = "percent"
    with pytest.raises(ValueError, match="incompatible unit or denominator"):
        project_consumer(trace, authority, fixture_mode=True)


def test_bounded_discovery_ids_empty_and_order() -> None:
    trace, authority = _safe_case()
    item = project_consumer(trace, authority, fixture_mode=True)
    assert page_consumer([item], indicator_id=item["indicator"]["id"], limit=1)["total"] == 1
    assert page_consumer([item], offset=1)["items"] == []
    assert page_consumer([])["items"] == []
    with pytest.raises(KeyError, match="indicator"):
        page_consumer([item], indicator_id="missing")
    with pytest.raises(KeyError, match="measure"):
        page_consumer([item], measure_id="missing")
    for kwargs in (
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"indicator_id": ""},
        {"measure_id": "x OR 1=1"},
    ):
        with pytest.raises(SemanticConsumerError):
            page_consumer([item], **kwargs)
    with pytest.raises(SemanticConsumerError, match="duplicate"):
        page_consumer([copy.deepcopy(item), item], limit=1)


def test_version_revision_and_release_are_pinned() -> None:
    trace, authority = _safe_case()
    result = project_consumer(trace, authority, fixture_mode=True)
    assert result["measure"]["semantic_version"] == trace["metadata"]["measure"]["semantic_version"]
    assert result["measure"]["metadata_revision_id"] == trace["metadata"]["revision_id"]
    assert result["observation"]["revision_id"] == trace["semantic_revision_id"]
    assert result["lineage"]["lineage_id"] == trace["lineage_id"]
    assert result["release"]["id"] == trace["release"]["release_id"]
    assert json.loads(canonical_consumer_json(result)) == result


@pytest.mark.parametrize(
    ("state", "value"),
    [
        ("OBSERVED", 3),
        ("ZERO", 0),
        ("UNKNOWN", None),
        ("SUPPRESSED", None),
        ("NOT_REPORTED", None),
        ("UNAVAILABLE", None),
        ("NOT_DEFENSIBLE", None),
    ],
)
def test_value_states_preserve_meaning(state: str, value: int | None) -> None:
    trace, authority = _safe_case()
    measure = trace["metadata"]["measure"]
    measure["allowed_value_states"] = sorted(set(measure["allowed_value_states"]) | {state})
    trace["metadata"]["allowed_value_states"] = measure["allowed_value_states"]
    trace["metadata"]["meaning_signature"] = meaning_signature(measure)
    observation = trace["observation"]
    observation["value_state"] = state
    observation["value"] = value
    observation["revision_id"] = revision_id(observation)
    trace["semantic_revision_id"] = observation["revision_id"]
    authority["releases"][trace["release"]["release_id"]]["semantic_revision_ids"] = [
        observation["revision_id"]
    ]
    trace["metadata"]["revision_id"] = metadata_revision_id(trace["metadata"])
    trace["metadata_revision_id"] = trace["metadata"]["revision_id"]
    trace["lineage_id"] = lineage_id(trace)
    result = project_consumer(trace, authority, fixture_mode=True)
    assert result["observation"]["value_state"] == state
    assert result["observation"]["value"] == value


def test_contextual_site_mapping_proof_is_not_emitted() -> None:
    trace, authority = _safe_case("neon_collection")
    geography = trace["observation"]["geography"]
    geography.update(
        county_fips="08013",
        county_relationship="ATLAS_DERIVED_MATCH",
        mapping_version="mapping-v1",
        mapping_artifact_id="private-artifact-123",
    )
    trace["observation"]["revision_id"] = revision_id(trace["observation"])
    trace["semantic_revision_id"] = trace["observation"]["revision_id"]
    trace["lineage_id"] = lineage_id(trace)
    result = project_consumer(trace, authority, fixture_mode=True)
    assert result["observation"]["geography"]["county_fips"] == "08013"
    assert result["observation"]["geography"]["representativeness"] == "NOT_COUNTY_REPRESENTATIVE"
    assert "mapping_artifact_id" not in canonical_consumer_json(result)


@pytest.mark.parametrize(
    "unsafe",
    [
        "C:\\private\\source.xlsx",
        "-----BEGIN PRIVATE KEY-----",
        "https://example.test/path?token=x",
    ],
)
def test_unsafe_values_cannot_be_canonicalized(unsafe: str) -> None:
    trace, authority = _safe_case()
    payload = project_consumer(trace, authority, fixture_mode=True)
    payload["measure"]["label"] = unsafe
    with pytest.raises(ValueError, match="restricted"):
        canonical_consumer_json(payload)


def test_machine_readable_schema_and_frozen_examples() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    validator = Draft202012Validator(SCHEMA)
    for shape in (
        "case_count_floor_2023",
        "svi_percentile_2022",
        "rucc_2023",
        "scapularis_status",
        "burgdorferi_status",
        "neon_collection",
        "neon_individual_pathogen_test",
        "source_only_evidence",
    ):
        payload = project_consumer(*_safe_case(shape), fixture_mode=True)
        validator.validate(payload)
        if shape in EXAMPLES:
            assert payload == EXAMPLES[shape]
            assert payload["evidence_tier"] == "SYNTHETIC_FIXTURE"
    assert set(EXAMPLES) == {"case_count_floor_2023", "neon_collection", "source_only_evidence"}
    invalid = copy.deepcopy(EXAMPLES["case_count_floor_2023"])
    invalid["observation"]["artifact_id"] = "private"
    with pytest.raises(ValidationError):
        validator.validate(invalid)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["measure"].update(warehouse_table="PRIVATE.TABLE"),
        lambda p: p["observation"].update(value={"warehouse_table": "PRIVATE.TABLE"}),
        lambda p: p["observation"]["strata"].update(warehouse_table="PRIVATE.TABLE"),
        lambda p: p["lineage"].update(storage_location="PRIVATE.TABLE"),
    ],
)
def test_helpers_reject_unprojected_fields(mutation: Callable[[dict], None]) -> None:
    trace, authority = _safe_case()
    payload = project_consumer(trace, authority, fixture_mode=True)
    mutation(payload)
    with pytest.raises(SemanticConsumerError, match="consumer shape"):
        canonical_consumer_json(payload)
    with pytest.raises(SemanticConsumerError, match="consumer shape"):
        page_consumer([payload])
