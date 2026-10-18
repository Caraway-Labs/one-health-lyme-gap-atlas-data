"""Adversarial consumer disappearance tests for the tentative pointer state."""

from copy import deepcopy

import pytest

from lyme_gap_atlas_data import release_completeness as gate


class ProjectionCursor:
    description = [("privilege",), ("grantee_name",)]

    def __init__(self, *, missing_model=False, grant=True, metadata=True, distribution=True):
        self.sql = ""
        self.params = ()
        self.missing_model = missing_model
        self.grant = grant
        self.metadata = metadata
        self.distribution = distribution

    def execute(self, sql, params=()):
        self.sql, self.params = sql, params

    def fetchmany(self, size):
        return [("new",)]

    def fetchone(self):
        if "COUNT(DISTINCT county_fips)" in self.sql:
            return (0, 0) if self.missing_model else (3144, 3144)
        return (3144,)

    def fetchall(self):
        if self.sql.startswith("SHOW GRANTS"):
            return [("SELECT", "OH_LYME_PROD_READ")] if self.grant else []
        if "GROUP BY source_key" in self.sql:
            return [
                (k, 3144) for k in ("human", "context_svi", "context_rucc", "context_nlcd_2025")
            ]
        if "GROUP BY" in self.sql:
            return [("class", 3144)] if self.distribution else [("other", 3144)]
        return [("required",)] if self.metadata else [("replacement",)]


def receipt():
    return {
        "artifacts": {
            k: {
                "expected_rows": 3144,
                "presentation_rows": 3144,
                "input_release_id": "old",
                "batch_id": "batch",
                "class_counts": {"class": 3144},
            }
            for k in gate.REQUIRED
        },
        "independent_consumers": [
            {"view": v, "minimum_rows": 0, "expected_keys": ["required"]} for v in gate.INDEPENDENT
        ],
    }


def test_valid_projected_release_passes():
    gate.verify_current(ProjectionCursor(), "new", receipt())


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"missing_model": True}, "model becomes unavailable"),
        ({"grant": False}, "read grant missing"),
        ({"metadata": False}, "metadata disappeared"),
        ({"distribution": False}, "class distribution changed"),
    ],
)
def test_real_projection_must_preserve_every_consumer(kwargs, message):
    before = receipt()
    original = deepcopy(before)
    with pytest.raises(gate.ReleaseCompletenessBlocked, match=message):
        gate.verify_current(ProjectionCursor(**kwargs), "new", before)
    assert before == original
