"""Independent contract checks for Story #170; no #171 calculator is imported."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/contracts/tick-surveillance/surveillance-coverage-v1.md"
MATRIX = ROOT / "docs/contracts/tick-surveillance/surveillance-coverage-v1-source-eligibility.json"
FIXTURES = ROOT / "tests/fixtures/tick_surveillance/surveillance-coverage-v1-fixtures.json"


def test_coverage_matrix_has_separate_source_shapes_and_no_composite() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert matrix["methodology_version"] == "surveillance-coverage-v1"
    assert matrix["no_pooling"] is True
    assert matrix["numeric_composite"] == "DEFERRED"
    assert len(matrix["constructs"]) == 4
    rows = {row["observation_type"]: row for row in matrix["rows"]}
    assert set(rows) == {
        "VECTOR_PRESENCE_STATUS",
        "PATHOGEN_PRESENCE_STATUS",
        "COLLECTION_ABUNDANCE",
        "PATHOGEN_TESTING",
        "NON_PATHOGEN_SUPPORTING_ASSAY",
    }
    for row in rows.values():
        assert len(row["eligibility"]) == len(matrix["constructs"])
        assert set(row["eligibility"]) <= set(matrix["eligibility_values"])
        assert row["reason"]
    assert rows["VECTOR_PRESENCE_STATUS"]["eligibility"][1:] == ["INELIGIBLE"] * 3
    assert rows["COLLECTION_ABUNDANCE"]["eligibility"][0] == "INELIGIBLE"
    assert rows["PATHOGEN_TESTING"]["eligibility"][0] == "INELIGIBLE"
    assert rows["NON_PATHOGEN_SUPPORTING_ASSAY"]["eligibility"][-1] == "INELIGIBLE"


def test_independent_expected_cases_cover_methodological_failures() -> None:
    document = CONTRACT.read_text(encoding="utf-8")
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in fixtures["cases"]}
    assert fixtures["evidence_basis"] == "INDEPENDENT_SYNTHETIC_METHODOLOGY_EXPECTATIONS"
    assert len(cases) == len(fixtures["cases"])
    assert {
        "county-reported",
        "county-absent",
        "county-no-records",
        "county-revision-conflict",
        "county-unresolved-fips",
        "county-source-only",
        "county-stale",
        "site-valid-zero",
        "site-missing-effort",
        "site-zero-effort",
        "site-impractical",
        "site-unmapped",
        "site-ambiguous",
        "site-repeated-events",
        "site-partial-period",
        "test-missing-denominator",
        "test-valid-zero-positive",
        "quality-unknown",
        "quality-not-applicable",
        "cross-county-status-not-active",
        "cross-site-not-county",
        "cross-no-pooled-score",
    } <= set(cases)
    assert cases["site-valid-zero"]["expected_state"] == "SAMPLED_EVENT"
    assert cases["site-impractical"]["expected_state"] == "SAMPLING_IMPRACTICAL"
    assert (
        cases["test-valid-zero-positive"]["expected_state"]
        == "DOCUMENTED_POSITIVE_TEST_DENOMINATOR"
    )
    assert cases["county-duplicate-identical"]["expected_canonical_count"] == 1
    assert cases["cross-no-pooled-score"]["expected_state"] == "DEFERRED"
    for case in fixtures["cases"]:
        assert (
            case["construct"] in json.loads(MATRIX.read_text(encoding="utf-8"))["constructs"]
            or case["construct"] == "COMPOSITE_COVERAGE_SCORE"
        )
        assert case["expected_state"]
    for term in (
        "CUMULATIVE_THROUGH_DATE",
        "NOT_COUNTY_REPRESENTATIVE",
        "STALE_OR_REVISION_SENSITIVE",
        "METHOD_COMPARABILITY_NOT_ESTABLISHED",
        "INFORMATIONAL ONLY",
        "DEFERRED",
        "#171 handoff",
    ):
        assert term in document
