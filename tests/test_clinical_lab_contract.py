"""Future-only clinical contract guards, with fabricated data only."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONTRACT = json.loads(
    (ROOT / "docs/contracts/interoperability/clinical-lab-signal-v1.json").read_text()
)
SPEC = importlib.util.spec_from_file_location(
    "synthetic_clinical_demo", ROOT / "scripts/demo_clinical_lab_contract.py"
)
assert SPEC is not None and SPEC.loader is not None
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


def test_future_boundary_and_terminology_claims() -> None:
    assert CONTRACT["status"] == "FUTURE_CONCEPTUAL_ONLY"
    assert CONTRACT["mvp_status"] == "NOT_PART_OF_CURRENT_MVP"
    assert CONTRACT["production_scoring_enabled"] is False
    boundary = CONTRACT["privacy_boundary"]
    assert boundary["atlas_stores_identifiable_patient_records"] is False
    assert boundary["patient_level_location"] != boundary["atlas_receives"]
    assert "patient_id" in boundary["disallowed_downstream_fields"]
    assert "never implies case" in CONTRACT["semantics"]["surveillance_case"]
    loinc = next(row for row in CONTRACT["standards"] if row["name"] == "LOINC")
    assert "no universal" in loinc["application"]
    assert loinc["version"] == "source-specific, pending validation"


def test_every_candidate_has_denominator_method_and_required_provenance() -> None:
    ids = [row["id"] for row in CONTRACT["candidate_signals"]]
    assert len(ids) == len(set(ids)) == 7
    for row in CONTRACT["candidate_signals"]:
        assert row["numerator"] and row["unit"] and row["method"]
        assert "denominator" in row
    required = set(CONTRACT["aggregate_output"]["required_fields"])
    assert {
        "county_fips",
        "period_start",
        "period_end",
        "source_organization",
        "source_version",
        "acquired_at",
        "method_version",
        "limitations",
        "lineage_digest",
    } <= required
    assert CONTRACT["aggregate_output"]["grain"] == "COUNTY"
    assert CONTRACT["aggregate_output"]["time_grain"] == "ISO_WEEK"
    assert {"ZERO", "MISSING", "UNKNOWN", "SUPPRESSED", "NOT_REPORTED"} <= set(
        CONTRACT["aggregate_output"]["value_states"]
    )


def test_synthetic_example_aggregates_and_removes_patient_fields() -> None:
    output = demo.aggregate(demo.synthetic_observations())
    assert len(output) == 1
    row = output[0]
    assert row["numerator"] is None and row["denominator"] is None
    assert row["value_state"] == "SUPPRESSED"
    assert row["period_start"] == "2026-09-28"
    assert not set(row) & set(CONTRACT["privacy_boundary"]["disallowed_downstream_fields"])
    assert row["status"] == "SYNTHETIC_FUTURE_CONCEPT"
    assert row["lineage_digest"] == "synthetic-only-no-source-artifact"
    assert "surveillance case count" in row["limitations"]


def test_fixture_suppression_and_zero_are_distinct() -> None:
    rows = demo.synthetic_observations()
    unsuppressed = demo.aggregate(rows, minimum_cell=1)[0]
    assert unsuppressed["denominator"] == 5  # corrected repeat is one event
    assert unsuppressed["numerator"] == 2
    negatives = [{**row, "value": "negative"} for row in rows]
    zero = demo.aggregate(negatives)[0]
    assert zero["value_state"] == "ZERO" and zero["value"] == 0
