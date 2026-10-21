"""Comparison detects predictor, evidence and geographic drift without inference."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "input_comparison", ROOT / "scripts/compare_tier1_release_inputs.py"
)
assert SPEC and SPEC.loader
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)
PREDICTORS = tuple("predictor_" + str(i) for i in range(6))


def rows():
    return [
        {
            "county_fips": f"{i:05d}",
            **dict.fromkeys(PREDICTORS, 1),
            "rucc_2023_context": 1,
            "human_evidence_state": "state",
            "pathogen_evidence_state": "state",
            "vector_evidence_state": "state",
            "feature_evidence_state": "state",
            "feature_set_version": "v2",
        }
        for i in range(3144)
    ]


def test_full_input_equality_is_separate_from_release_approval():
    result = comparison.compare(rows(), rows(), PREDICTORS)
    assert result["model_input_equality"]
    assert result["predictor_cells_compared"] == 18864


@pytest.mark.parametrize("column,value", [(PREDICTORS[0], 2), ("vector_evidence_state", "changed")])
def test_changed_cells_are_reported_without_refit(column, value):
    changed = rows()
    changed[100][column] = value
    result = comparison.compare(changed, rows(), PREDICTORS)
    assert not result["model_input_equality"]
    assert result["changed_cells_by_field"][column] == 1


def test_missing_county_cannot_be_ignored():
    with pytest.raises(ValueError, match="membership differs"):
        comparison.compare(rows()[:-1], rows(), PREDICTORS)
