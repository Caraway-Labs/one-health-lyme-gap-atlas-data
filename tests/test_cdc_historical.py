from copy import deepcopy

import pytest

from lyme_gap_atlas_data.cdc_historical import REQUIRED_COLUMNS, validate_historical_evidence


def metadata() -> dict[str, object]:
    return {"id": "qtbi-xd4i", "columns": [{"fieldName": key} for key in REQUIRED_COLUMNS]}


def test_historical_sample_preserves_unknowns_and_does_not_claim_complete_quality() -> None:
    sample = [{"year": "2008", "frequency": 0}, {"year": "2021", "fips": "Unknown"}]
    original = deepcopy(sample)
    result = validate_historical_evidence(metadata(), sample, environment="dev", sample_limit=25)
    assert sample == original
    assert result["full_dataset_validated"] is False
    assert result["publisher_record_identity_verified"] is False


@pytest.mark.parametrize("year", ["2007", "2022", None, "Unknown", "2010.0"])
def test_historical_sample_rejects_wrong_era(year: object) -> None:
    with pytest.raises(ValueError, match="era"):
        validate_historical_evidence(
            metadata(), [{"year": year}], environment="dev", sample_limit=25
        )


def test_historical_candidate_cannot_enter_prod_or_exceed_sample_bound() -> None:
    with pytest.raises(ValueError, match="DEV-only"):
        validate_historical_evidence(
            metadata(), [{"year": "2008"}], environment="prod", sample_limit=25
        )
    with pytest.raises(ValueError, match="bound"):
        validate_historical_evidence(
            metadata(), [{"year": "2008"}] * 2, environment="dev", sample_limit=1
        )


def test_historical_candidate_rejects_wrong_dataset_and_missing_schema() -> None:
    wrong = metadata()
    wrong["id"] = "x5j9-wybp"
    with pytest.raises(ValueError, match="identity"):
        validate_historical_evidence(wrong, [{"year": "2008"}], environment="dev", sample_limit=25)
    with pytest.raises(ValueError, match="columns"):
        validate_historical_evidence(
            {"id": "qtbi-xd4i", "columns": []},
            [{"year": "2008"}],
            environment="dev",
            sample_limit=25,
        )
