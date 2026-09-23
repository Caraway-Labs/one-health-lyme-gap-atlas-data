"""Contract-only checks for independently authored Story #167 fixtures."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("docs/contracts/tick-surveillance")
FIXTURES = Path("tests/fixtures/tick_surveillance/infected-tick-metrics-v1-fixtures.json")


def test_source_eligibility_matrix_covers_every_canonical_shape_and_disposition() -> None:
    matrix = json.loads(
        (ROOT / "infected-tick-metrics-v1-source-eligibility.json").read_text(encoding="utf-8")
    )
    assert matrix["methodology_version"] == "infected-tick-metrics-v1"
    assert {entry["canonical_shape"] for entry in matrix["canonical_shape_matrix"]} == {
        "VECTOR_PRESENCE_STATUS",
        "PATHOGEN_PRESENCE_STATUS",
        "COLLECTION_ABUNDANCE",
        "PATHOGEN_TESTING",
        "NON_PATHOGEN_SUPPORTING_ASSAY",
    }
    assert matrix["metrics"]["OBSERVED_PATHOGEN_PREVALENCE"]["disposition"] == "APPROVED"
    assert matrix["metrics"]["EFFORT_NORMALIZED_COLLECTION_DENSITY"]["disposition"] == "APPROVED"
    assert matrix["metrics"]["COMBINED_INFECTED_TICK_ESTIMATOR"]["disposition"] == "DEFERRED"


def test_independent_methodology_fixtures_cover_required_cases() -> None:
    by_name = {case["case"]: case for case in json.loads(FIXTURES.read_text(encoding="utf-8"))}
    required = {
        "valid-positive-prevalence",
        "valid-zero-positive-prevalence",
        "zero-tested",
        "positive-exceeds-tested",
        "missing-tested-denominator",
        "valid-collection-density",
        "zero-collection-documented-effort",
        "missing-unknown-effort",
        "zero-effort",
        "sampling-impractical",
        "incompatible-method",
        "mismatched-species-life-stage",
        "mismatched-event-period",
        "non-random-pathogen-selection",
        "partial-nonrepresentative-site",
        "source-revision-vintage",
        "sparse-sample",
        "combined-estimator-deferred",
    }
    assert required <= by_name.keys()
    assert by_name["valid-positive-prevalence"]["expected"]["value"] == 0.4
    assert by_name["valid-zero-positive-prevalence"]["expected"]["value"] == 0.0
    assert by_name["zero-collection-documented-effort"]["expected"]["value"] == 0.0
    assert by_name["combined-estimator-deferred"]["expected"]["state"] == "UNAVAILABLE"


def test_methodology_document_locks_formula_and_no_county_or_interval_claim() -> None:
    document = (ROOT / "infected-tick-metrics-v1.md").read_text(encoding="utf-8")
    for text in (
        "`prevalence_s = P_s / T_s`",
        "`density_c = C_c / A_c`",
        "No county output exists",
        "no confidence interval",
        "METHOD_COMPARABILITY_NOT_ESTABLISHED",
    ):
        assert text in document
