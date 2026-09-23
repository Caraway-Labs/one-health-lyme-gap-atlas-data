"""Independent behavioral tests for the v1 surveillance-quality profile."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from lyme_gap_atlas_data.surveillance_quality import (
    DIMENSIONS,
    QUALITY_METHOD_VERSION,
    assess_surveillance_quality,
)


def _components(profile: dict[str, object]) -> dict[str, tuple[str, list[str]]]:
    components = profile["components"]
    assert isinstance(components, list)
    return {
        str(component["dimension"]): (str(component["state"]), list(component["reason_codes"]))
        for component in components
        if isinstance(component, dict)
    }


def test_quality_profiles_match_independently_authored_fixture_expectations() -> None:
    fixtures = json.loads(
        Path("tests/fixtures/tick_surveillance/quality-profiles-v1.json").read_text(
            encoding="utf-8"
        )
    )
    for fixture in fixtures:
        profile = assess_surveillance_quality(fixture["record"])
        components = _components(profile)
        for dimension, expected in fixture["expected"].items():
            assert components[dimension] == (expected[0], expected[1]), fixture["case"]


def test_quality_profile_serialization_is_structurally_valid() -> None:
    fixture = json.loads(
        Path("tests/fixtures/tick_surveillance/quality-profiles-v1.json").read_text(
            encoding="utf-8"
        )
    )[2]
    schema = json.loads(
        Path(
            "docs/contracts/tick-surveillance/surveillance-quality-profile-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    profile = assess_surveillance_quality(fixture["record"])

    assert list(validator.iter_errors(profile)) == []
    profile["quality_method_version"] = "unversioned"
    assert list(validator.iter_errors(profile))


def test_profile_is_complete_deterministic_and_versioned() -> None:
    record = json.loads(
        Path("tests/fixtures/tick_surveillance/quality-profiles-v1.json").read_text(
            encoding="utf-8"
        )
    )[2]["record"]

    first = assess_surveillance_quality(record)
    second = assess_surveillance_quality(record)

    assert first == second
    assert first["quality_method_version"] == QUALITY_METHOD_VERSION
    assert set(_components(first)) == set(DIMENSIONS)
    assert first["ingestion_run_id"] == "ea8db548-62b0-4632-84ca-02eee97ead41"
    assert first["artifact_id"] == "fixture-neon-artifact"


def test_unknown_and_not_applicable_are_never_collapsed() -> None:
    fixtures = json.loads(
        Path("tests/fixtures/tick_surveillance/quality-profiles-v1.json").read_text(
            encoding="utf-8"
        )
    )
    county_status = _components(assess_surveillance_quality(fixtures[0]["record"]))
    unknown_effort = _components(assess_surveillance_quality(fixtures[3]["record"]))

    assert county_status["EFFORT_DENOMINATOR_COMPLETENESS"][0] == "NOT_APPLICABLE"
    assert unknown_effort["EFFORT_DENOMINATOR_COMPLETENESS"][0] == "UNKNOWN"
    assert county_status["PATHOGEN_TESTING_DENOMINATOR_VALIDITY"][0] == "NOT_APPLICABLE"


def test_profile_has_no_score_probability_or_disease_risk_semantics() -> None:
    schema = json.loads(
        Path(
            "docs/contracts/tick-surveillance/surveillance-quality-profile-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    record = json.loads(
        Path("tests/fixtures/tick_surveillance/quality-profiles-v1.json").read_text(
            encoding="utf-8"
        )
    )[0]["record"]
    profile = assess_surveillance_quality(record)

    assert not {"score", "probability", "confidence", "disease_risk"} & set(schema["properties"])
    assert not {"score", "probability", "confidence", "disease_risk"} & set(profile)
