"""Data #430: source-backed era comparison cannot manufacture comparability."""

from copy import deepcopy

import pytest

from lyme_gap_atlas_data.surveillance_methodology import (
    classify_methodology,
    compare_methodology,
    project_methodology_comparison,
)


def record(year: int, fips: str = "42001", category: str = "Probable") -> dict[str, object]:
    return {
        "resource_key": "cdc_lyme_qtbi_xd4i" if year <= 2021 else "cdc_lyme_x5j9_wybp",
        "definition_version": 2,
        "data_source_version_id": "approved-historical" if year <= 2021 else "approved-current",
        "report_year": year,
        "county_fips": fips,
        "case_status": category,
        "revision_id": "revision-1",
        "frequency": 7,
        "source_value_status": "published_floor",
    }


def attestation(state: str, classification: str, start: int, end: int) -> dict[str, object]:
    return {
        "state_fips": state,
        "classification": classification,
        "reviewed": True,
        "reference_url": "https://example.org/fixture-reviewed-jurisdiction-evidence",
        "effective_start_year": start,
        "effective_end_year": end,
    }


def test_pre_2022_same_definition_requires_reviewed_jurisdiction_scope() -> None:
    left, right = record(2008), record(2009)
    assert compare_methodology(left, right)["comparison_state"] == "UNKNOWN"
    result = compare_methodology(
        left, right, jurisdiction_evidence=attestation("42", "HIGH", 2008, 2009)
    )
    assert result["comparison_state"] == "COMPARABLE"
    assert result["methodology_era_ids"] == ["cdc_2008"]


def test_post_2022_supported_high_and_low_examples_do_not_become_global_rules() -> None:
    high = classify_methodology(record(2022, "42001"))
    low = classify_methodology(record(2022, "01001"))
    other = classify_methodology(record(2022, "06001"))
    future = classify_methodology(record(2023, "42001"))
    assert high["jurisdiction_class"] == "HIGH"
    assert low["jurisdiction_class"] == "LOW"
    assert other["jurisdiction_class"] == "UNKNOWN"
    assert future["jurisdiction_class"] == "UNKNOWN"
    assert (
        compare_methodology(record(2022, "42001"), record(2022, "42003"))["comparison_state"]
        == "COMPARABLE"
    )
    assert (
        compare_methodology(record(2022, "01001"), record(2022, "01003"))["comparison_state"]
        == "COMPARABLE"
    )


def test_2022_break_and_other_definition_changes_are_distinct() -> None:
    boundary = compare_methodology(record(2021), record(2022))
    assert boundary["comparison_state"] == "UNKNOWN"
    boundary = compare_methodology(
        record(2021), record(2022), jurisdiction_evidence=attestation("42", "HIGH", 2021, 2022)
    )
    assert boundary["comparison_state"] == "NOT_COMPARABLE"
    assert boundary["reason_codes"] == ["CASE_DEFINITION_2022_BREAK"]
    earlier = compare_methodology(
        record(2010), record(2011), jurisdiction_evidence=attestation("42", "HIGH", 2010, 2011)
    )
    assert earlier["comparison_state"] == "CAUTION_REQUIRED"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("resource_key", "other", "SOURCE_VERSION_UNVERIFIED"),
        ("definition_version", 99, "SOURCE_VERSION_UNVERIFIED"),
        ("data_source_version_id", "", "SOURCE_VERSION_UNVERIFIED"),
        ("county_fips", "Suppressed", "JURISDICTION_UNMAPPED"),
        ("case_status", "Suspected", "CASE_CATEGORY_UNVERIFIED"),
    ],
)
def test_unknown_input_fails_closed(field: str, value: object, reason: str) -> None:
    candidate = record(2022)
    candidate[field] = value
    result = compare_methodology(candidate, record(2022))
    assert result["comparison_state"] == "UNKNOWN"
    assert result["reason_codes"] == [reason]


def test_unreviewed_or_expired_applicability_remains_unknown() -> None:
    evidence = attestation("42", "HIGH", 2008, 2008)
    assert (
        compare_methodology(record(2008), record(2009), jurisdiction_evidence=evidence)[
            "comparison_state"
        ]
        == "UNKNOWN"
    )

    evidence["effective_end_year"] = 2009
    evidence["reviewed"] = False
    assert (
        compare_methodology(record(2008), record(2009), jurisdiction_evidence=evidence)[
            "comparison_state"
        ]
        == "UNKNOWN"
    )


def test_invalid_optional_evidence_cannot_crash_supported_2022_classification() -> None:
    result = classify_methodology(record(2022), jurisdiction_evidence={})
    assert result["jurisdiction_class"] == "HIGH"
    assert all("None" not in reference for reference in result["references"])


def test_revision_and_category_changes_are_cautions_and_values_untouched() -> None:
    left, right = record(2022), record(2022)
    before = deepcopy((left, right))
    right["revision_id"] = "revision-2"
    assert compare_methodology(left, right)["reason_codes"] == ["REVISION_DIFFERENT"]
    right["revision_id"] = "revision-1"
    right["case_status"] = "Confirmed"
    assert compare_methodology(left, right)["reason_codes"] == ["CASE_CATEGORY_DIFFERENT"]
    assert left == before[0]
    assert right["frequency"] == before[1]["frequency"]
    assert right["source_value_status"] == before[1]["source_value_status"]


def test_generic_era_flag_cannot_override_unknown_and_projection_is_bounded() -> None:
    left, right = record(2022, "06001"), record(2022, "06003")
    left["era_flag"] = right["era_flag"] = "same"
    result = compare_methodology(left, right)
    assert result["comparison_state"] == "UNKNOWN"
    projected = project_methodology_comparison(result)
    assert "frequency" not in projected
    assert "source_version_id" not in projected
    assert projected["reason_codes"] == ["JURISDICTION_APPLICABILITY_UNKNOWN"]
    with pytest.raises(ValueError):
        project_methodology_comparison(
            {"contract_version": "bad", "comparison_state": "COMPARABLE"}
        )
