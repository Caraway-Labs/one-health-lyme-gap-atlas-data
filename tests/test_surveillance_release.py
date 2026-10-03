"""Release candidates preserve categorical evidence and exact membership."""

import hashlib
import json
from copy import deepcopy

import pytest
from test_surveillance_coverage import _county, _county_context

from lyme_gap_atlas_data.surveillance_coverage import COUNTY, evaluate_surveillance_coverage
from lyme_gap_atlas_data.surveillance_coverage_results import serialize_surveillance_coverage
from lyme_gap_atlas_data.surveillance_release import build_surveillance_release_candidate


def _result(county: str = "01001", *, complete: bool = True) -> dict:
    return evaluate_surveillance_coverage(
        COUNTY,
        [_county()] if county == "01001" else [],
        source_context=_county_context(complete),
        county_fips=county,
        dimension="Ixodes scapularis",
    )


def _candidate(results: list[dict], *, expected: list[str] | None = None) -> dict:
    ids = [
        str(serialize_surveillance_coverage(r, evidence_basis="SYNTHETIC_FIXTURE")["result_id"])
        for r in results
    ]
    return build_surveillance_release_candidate(
        results,
        release_id="fixture-release-v1",
        scope_reference="fixture-scope-v1",
        expected_result_ids=ids if expected is None else expected,
        evidence_basis="SYNTHETIC_FIXTURE",
    )


def test_snapshot_is_deterministic_and_preserves_internal_evidence() -> None:
    results = [_result(), _result("01003", complete=False)]
    before = deepcopy(results)
    candidate = _candidate(results)
    assert candidate == _candidate(list(reversed(results)))
    assert results == before
    assert candidate["publication_status"] == "CANDIDATE_NOT_PUBLISHED"
    assert candidate["evidence_basis"] == "SYNTHETIC_FIXTURE"
    assert {r["state"] for r in candidate["coverage"]} == {"REPORTED_STATUS", "UNKNOWN"}
    for coverage, priority in zip(candidate["coverage"], candidate["priority"], strict=True):
        assert (
            coverage["publication_status"] == priority["publication_status"] == "INTERNAL_DEV_ONLY"
        )
        assert priority["coverage_result_id"] == coverage["result_id"]
        assert priority["coverage_result_revision"] == coverage["result_revision"]
        assert priority["quality"] == coverage["quality"]
        assert priority["safe_lineage"] == coverage["safe_lineage"]
        assert "score" not in priority


@pytest.mark.parametrize("kind", ["missing", "extra", "duplicate", "empty"])
def test_incomplete_or_conflicting_membership_fails(kind: str) -> None:
    result = _result()
    identifier = str(_candidate([result])["expected_result_ids"][0])
    rows, expected = [result], [identifier]
    if kind == "missing":
        expected.append("coverage-result:v2:missing")
    elif kind == "extra":
        rows.append(_result("01003"))
    elif kind == "duplicate":
        rows.append(result)
    else:
        rows, expected = [], []
    with pytest.raises(ValueError, match="membership"):
        _candidate(rows, expected=expected)


def test_snapshot_membership_cannot_authorize_publisher_omission() -> None:
    result = _result("01003", complete=False)
    result["state"] = "NOT_REPORTED_IN_DATASET"
    with pytest.raises(ValueError, match="snapshot|omission"):
        build_surveillance_release_candidate(
            [result],
            release_id="fixture-release-v1",
            scope_reference="fixture-scope-v1",
            expected_result_ids=["coverage-result:v2:unproven-omission"],
            evidence_basis="SYNTHETIC_FIXTURE",
        )


def test_digest_independently_binds_exact_projection_and_scope() -> None:
    candidate = _candidate([_result()])
    digest = candidate.pop("snapshot_sha256")
    encoded = json.dumps(candidate, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert digest == hashlib.sha256(encoded.encode()).hexdigest()
    changed = deepcopy(candidate)
    changed["scope_reference"] = "different-scope"
    encoded = json.dumps(changed, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert digest != hashlib.sha256(encoded.encode()).hexdigest()


def test_revised_evidence_cannot_satisfy_old_manifest() -> None:
    old = _candidate([_result()])
    changed = _result()
    changed["reason_codes"] = ["NEW_REASON"]
    with pytest.raises(ValueError, match="membership"):
        _candidate([changed], expected=old["expected_result_ids"])


def test_release_reference_cannot_contain_private_location() -> None:
    with pytest.raises(ValueError, match="references"):
        build_surveillance_release_candidate(
            [],
            release_id="https://private",
            scope_reference="scope",
            expected_result_ids=[],
            evidence_basis="SYNTHETIC_FIXTURE",
        )
