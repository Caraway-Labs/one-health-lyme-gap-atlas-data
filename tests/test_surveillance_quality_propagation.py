"""Independent behavioral tests for bounded surveillance-quality propagation."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from lyme_gap_atlas_data.surveillance_quality import assess_surveillance_quality
from lyme_gap_atlas_data.surveillance_quality_propagation import (
    PROPAGATION_SCHEMA_VERSION,
    propagate_surveillance_quality,
    serialize_safe_propagation,
)

FIXTURE_DIR = Path("tests/fixtures/tick_surveillance")


def _source_records() -> dict[str, dict[str, object]]:
    return {
        item["case"]: item["record"]
        for item in json.loads(
            (FIXTURE_DIR / "quality-profiles-v1.json").read_text(encoding="utf-8")
        )
    }


def _component(envelope: dict[str, object], dimension: str) -> dict[str, object]:
    components = envelope["propagated_components"]
    assert isinstance(components, list)
    return next(item for item in components if item["dimension"] == dimension)


def _build_case(case: dict[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
    sources = _source_records()
    names = case["sources"]
    assert isinstance(names, list)
    records = [copy.deepcopy(sources[str(name)]) for name in names]
    if "record_patch" in case:
        assert isinstance(case["record_patch"], dict)
        records[0].update(case["record_patch"])
    if "record_limitations" in case:
        assert isinstance(case["record_limitations"], list)
        for record, limitations in zip(records, case["record_limitations"], strict=True):
            record["limitations"] = limitations
    if "second_source_patch" in case:
        assert isinstance(case["second_source_patch"], dict)
        records[1].update(case["second_source_patch"])
    profiles = [assess_surveillance_quality(record) for record in records]
    envelope = propagate_surveillance_quality(
        records,
        profiles,
        transformation_id="fixture-propagation",
        transformation_version="fixture-v1",
        added_reason_codes=case.get("added_reason_codes", []),
        added_limitations=case.get("added_limitations", []),
    )
    return records, envelope


def test_propagation_matches_independently_authored_fixture_expectations() -> None:
    cases = json.loads((FIXTURE_DIR / "quality-propagation-v1.json").read_text(encoding="utf-8"))
    for case in cases:
        records, envelope = _build_case(case)
        expected = case["expected"]
        limitations = envelope["inherited_limitations"]
        assert isinstance(limitations, list)
        for value in expected.get("must_include", []):
            assert value in limitations, case["case"]
        if "effort_state" in expected:
            assert (
                _component(envelope, "EFFORT_DENOMINATOR_COMPLETENESS")["state"]
                == expected["effort_state"]
            ), case["case"]
        if "pathogen_denominator_state" in expected:
            assert (
                _component(envelope, "PATHOGEN_TESTING_DENOMINATOR_VALIDITY")["state"]
                == expected["pathogen_denominator_state"]
            ), case["case"]
        if "comparability_state" in expected:
            assert (
                _component(envelope, "COMPARABILITY_ELIGIBILITY")["state"]
                == expected["comparability_state"]
            ), case["case"]
        if expected.get("retained_zero"):
            assert envelope["inputs"][0]["retained_input_values"]["ticks_collected"] == 0
        if "source_versions" in expected:
            assert [item["data_source_version_id"] for item in envelope["inputs"]] == expected[
                "source_versions"
            ]
        if "added_reason_codes" in expected:
            assert envelope["transformation_added_reason_codes"] == expected["added_reason_codes"]
        if "added_limitations" in expected:
            assert envelope["transformation_added_limitations"] == expected["added_limitations"]
        if "safe_absent" in expected:
            serialized = serialize_safe_propagation(envelope)
            rendered = json.dumps(serialized, sort_keys=True)
            for key in expected["safe_absent"]:
                assert key not in rendered


def test_propagation_preserves_each_input_component_without_flattening() -> None:
    records = _source_records()
    selected = [records["neon_valid_zero_with_effort"], records["neon_unknown_effort"]]
    envelope = propagate_surveillance_quality(
        selected,
        [assess_surveillance_quality(item) for item in selected],
        transformation_id="fixture-propagation",
        transformation_version="fixture-v1",
    )
    effort = _component(envelope, "EFFORT_DENOMINATOR_COMPLETENESS")
    assert effort["state"] == "UNKNOWN"
    assert [item["state"] for item in effort["input_components"]] == ["ASSESSED", "UNKNOWN"]


def test_safe_projection_is_structurally_valid_and_excludes_private_lineage() -> None:
    records = _source_records()
    record = records["neon_valid_zero_with_effort"]
    envelope = propagate_surveillance_quality(
        [record],
        [assess_surveillance_quality(record)],
        transformation_id="fixture-propagation",
        transformation_version="fixture-v1",
    )
    serialized = serialize_safe_propagation(envelope)
    schema = json.loads(
        Path(
            "docs/contracts/tick-surveillance/surveillance-quality-propagation-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(serialized)) == []
    assert serialized["propagation_schema_version"] == PROPAGATION_SCHEMA_VERSION
    assert "artifact_id" not in json.dumps(serialized)
    assert "retained_input_values" not in json.dumps(serialized)


def test_invalid_alignment_and_quality_method_fail_closed() -> None:
    record = _source_records()["neon_valid_zero_with_effort"]
    profile = assess_surveillance_quality(record)
    profile["quality_method_version"] = "unversioned"
    try:
        propagate_surveillance_quality(
            [record],
            profile and [profile],
            transformation_id="fixture",
            transformation_version="v1",
        )
    except ValueError as error:
        assert "surveillance-quality-profile-v1" in str(error)
    else:
        raise AssertionError("invalid quality-method version must fail closed")
