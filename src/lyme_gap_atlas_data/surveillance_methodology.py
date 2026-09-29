"""Storage-neutral Lyme surveillance methodology evidence for Data #430.

Comparison describes case-definition compatibility only. It never changes a
source value, establishes an exact label, or admits a point-in-time ML row.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

CONTRACT_VERSION = "atlas-lyme-surveillance-methodology-v1"
CDC_DEFINITIONS = "https://www.cdc.gov/lyme/data-research/facts-stats/index.html"
CDC_2022 = "https://ndc.services.cdc.gov/case-definitions/lyme-disease-2022/"
CDC_2017 = "https://ndc.services.cdc.gov/case-definitions/lyme-disease-2017/"
CDC_2011 = "https://ndc.services.cdc.gov/case-definitions/lyme-disease-2011/"
CDC_2008 = "https://ndc.services.cdc.gov/case-definitions/lyme-disease-2008/"
CDC_MMWR = "https://www.cdc.gov/mmwr/volumes/73/wr/mm7306a1.htm"

# The 2022 case definition identifies these jurisdictions as high incidence at
# the 2021 position-statement date. The MMWR table identifies Alabama as low
# incidence in 2022. Neither source proves an unchanged classification in 2023.
HIGH_2022 = frozenset(
    {"09", "10", "11", "23", "24", "25", "27", "33", "34", "36", "42", "44", "50", "51", "54", "55"}
)
LOW_2022 = frozenset({"01"})
_FIPS = re.compile(r"[0-9]{5}")
_SOURCE = {"cdc_lyme_qtbi_xd4i": (2008, 2021), "cdc_lyme_x5j9_wybp": (2022, 2023)}
_ERAS = (
    (2008, 2010, "cdc_2008", CDC_2008),
    (2011, 2016, "cdc_2011", CDC_2011),
    (2017, 2021, "cdc_2017", CDC_2017),
    (2022, 2023, "cdc_2022", CDC_2022),
)
STATES = frozenset({"COMPARABLE", "CAUTION_REQUIRED", "NOT_COMPARABLE", "UNKNOWN"})


def _unknown(reason: str) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "comparison_state": "UNKNOWN",
        "reason_codes": [reason],
        "methodology_era_ids": [],
        "jurisdiction_class": "UNKNOWN",
        "references": [CDC_DEFINITIONS],
        "limitations": ["No source value, historical availability, or ML eligibility is inferred."],
    }


def _jurisdiction_class(state: str, year: int, evidence: Mapping[str, Any] | None) -> str:
    if year == 2022:
        if state in HIGH_2022:
            return "HIGH"
        if state in LOW_2022:
            return "LOW"
    if evidence is None:
        return "UNKNOWN"
    if (
        evidence.get("state_fips") == state
        and evidence.get("classification") in {"HIGH", "LOW"}
        and evidence.get("reviewed") is True
        and isinstance(evidence.get("reference_url"), str)
        and str(evidence["reference_url"]).startswith("https://")
        and isinstance(evidence.get("effective_start_year"), int)
        and isinstance(evidence.get("effective_end_year"), int)
        and evidence["effective_start_year"] <= year <= evidence["effective_end_year"]
    ):
        return str(evidence["classification"])
    return "UNKNOWN"


def classify_methodology(
    observation: Mapping[str, Any], *, jurisdiction_evidence: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Classify one source-backed assertion without touching its value."""
    resource = observation.get("resource_key")
    year = observation.get("report_year")
    fips = observation.get("county_fips")
    if resource not in _SOURCE or observation.get("definition_version") != 2:
        return _unknown("SOURCE_VERSION_UNVERIFIED")
    if (
        not isinstance(year, int)
        or isinstance(year, bool)
        or not _SOURCE[resource][0] <= year <= _SOURCE[resource][1]
    ):
        return _unknown("PERIOD_OUTSIDE_SOURCE_ERA")
    if not isinstance(fips, str) or not _FIPS.fullmatch(fips):
        return _unknown("JURISDICTION_UNMAPPED")
    if observation.get("case_status") not in {"Confirmed", "Probable"}:
        return _unknown("CASE_CATEGORY_UNVERIFIED")
    if (
        not isinstance(observation.get("data_source_version_id"), str)
        or not observation["data_source_version_id"]
    ):
        return _unknown("SOURCE_VERSION_UNVERIFIED")
    era_id, reference = next((era, url) for start, end, era, url in _ERAS if start <= year <= end)
    jurisdiction = _jurisdiction_class(fips[:2], year, jurisdiction_evidence)
    references = [reference, CDC_DEFINITIONS]
    if year == 2022:
        references.append(CDC_MMWR)
    if jurisdiction_evidence is not None and jurisdiction != "UNKNOWN":
        references.append(str(jurisdiction_evidence["reference_url"]))
    return {
        "contract_version": CONTRACT_VERSION,
        "methodology_era_id": era_id,
        "methodology_version": era_id.removeprefix("cdc_"),
        "source_family": resource,
        "source_definition_version": 2,
        "source_version_id": observation["data_source_version_id"],
        "effective_start_year": next(start for start, _, era, _ in _ERAS if era == era_id),
        "effective_end_year": next(end for _, end, era, _ in _ERAS if era == era_id),
        "state_fips": fips[:2],
        "jurisdiction_class": jurisdiction,
        "case_category": observation["case_status"],
        "year_basis": "surveillance_report_year",
        "revision_id": observation.get("revision_id"),
        "references": sorted(set(references)),
        "limitations": [
            "Report year is not illness onset, diagnosis, publication, or availability time.",
            "Methodology classification does not establish complete or exact county counts.",
        ],
    }


def compare_methodology(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    jurisdiction_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare case-definition rules, never numerical trend validity."""
    a = classify_methodology(left, jurisdiction_evidence=jurisdiction_evidence)
    b = classify_methodology(right, jurisdiction_evidence=jurisdiction_evidence)
    if "methodology_era_id" not in a or "methodology_era_id" not in b:
        reason = (a if "methodology_era_id" not in a else b)["reason_codes"][0]
        return _unknown(reason)
    eras = sorted({a["methodology_era_id"], b["methodology_era_id"]})
    refs = sorted(set(a["references"] + b["references"]))
    reasons: list[str]
    state: str
    if a["state_fips"] != b["state_fips"]:
        state, reasons = "UNKNOWN", ["JURISDICTION_DIFFERENT"]
    elif "cdc_2022" in eras and len(eras) > 1:
        if a["jurisdiction_class"] == "UNKNOWN" or b["jurisdiction_class"] == "UNKNOWN":
            state, reasons = "UNKNOWN", ["JURISDICTION_APPLICABILITY_UNKNOWN"]
        elif a["jurisdiction_class"] != b["jurisdiction_class"]:
            state, reasons = "CAUTION_REQUIRED", ["JURISDICTION_CLASS_CHANGED"]
        else:
            state, reasons = "NOT_COMPARABLE", ["CASE_DEFINITION_2022_BREAK"]
    elif len(eras) > 1:
        if a["jurisdiction_class"] == "UNKNOWN" or b["jurisdiction_class"] == "UNKNOWN":
            state, reasons = "UNKNOWN", ["JURISDICTION_APPLICABILITY_UNKNOWN"]
        else:
            state, reasons = "CAUTION_REQUIRED", ["CASE_DEFINITION_VERSION_CHANGE"]
    elif a["source_version_id"] != b["source_version_id"]:
        state, reasons = "UNKNOWN", ["SOURCE_VERSION_CHANGED"]
    elif a["jurisdiction_class"] == "UNKNOWN" or b["jurisdiction_class"] == "UNKNOWN":
        state, reasons = "UNKNOWN", ["JURISDICTION_APPLICABILITY_UNKNOWN"]
    elif a["jurisdiction_class"] != b["jurisdiction_class"]:
        state, reasons = "CAUTION_REQUIRED", ["JURISDICTION_CLASS_CHANGED"]
    elif a["case_category"] != b["case_category"]:
        state, reasons = "CAUTION_REQUIRED", ["CASE_CATEGORY_DIFFERENT"]
    elif a["revision_id"] != b["revision_id"]:
        state, reasons = "CAUTION_REQUIRED", ["REVISION_DIFFERENT"]
    else:
        state, reasons = "COMPARABLE", ["SAME_REVIEWED_CASE_DEFINITION_SCOPE"]
    return {
        "contract_version": CONTRACT_VERSION,
        "comparison_state": state,
        "reason_codes": reasons,
        "methodology_era_ids": eras,
        "jurisdiction_class": a["jurisdiction_class"]
        if a["jurisdiction_class"] == b["jurisdiction_class"]
        else "UNKNOWN",
        "references": refs,
        "limitations": [
            "Comparable means case-definition scope only; label completeness, value state, "
            "and as-of eligibility remain separate.",
            "No historical source value is changed or numerically adjusted.",
        ],
    }


def project_methodology_comparison(result: Mapping[str, Any]) -> dict[str, Any]:
    """Select bounded consumer-safe methodology metadata; no source payload."""
    if (
        result.get("contract_version") != CONTRACT_VERSION
        or result.get("comparison_state") not in STATES
    ):
        raise ValueError("Invalid methodology comparison")
    fields = (
        "contract_version",
        "comparison_state",
        "reason_codes",
        "methodology_era_ids",
        "jurisdiction_class",
        "references",
        "limitations",
    )
    return {field: result[field] for field in fields}
