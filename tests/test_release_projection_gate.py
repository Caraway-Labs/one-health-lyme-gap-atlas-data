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
        return [("new", "bundle")]

    def fetchone(self):
        if "COUNT(DISTINCT county_fips)" in self.sql:
            return (0, 0) if self.missing_model else (3144, 3144)
        return (3144,)

    def fetchall(self):
        if "SELECT release_id,fips" in self.sql:
            return [("new", f) for f in canonical()]
        if "SELECT release_version,source_key" in self.sql:
            return [("new", k, *(["pin"] * len(gate.SOURCE_FIELDS))) for k in sources()]
        if self.sql.startswith("SHOW GRANTS"):
            return [("SELECT", "OH_LYME_PROD_READ")] if self.grant else []
        if "CURRENT_CLIMATE_MEASURE_METADATA_V" in self.sql:
            return [(m,) for m in gate.CLIMATE_MEASURES]
        if "GROUP BY measure_id" in self.sql:
            return [
                (m, 97464, 3144, 97464, "2025-01-01", "2025-01-31") for m in gate.CLIMATE_MEASURES
            ]
        if "GROUP BY source_key" in self.sql:
            return [
                (k, m, 3144, 3144, 0)
                for k, names in gate.PRESENTATION_MEASURES.items()
                for m in names
            ]
        if "GROUP BY" in self.sql:
            if self.missing_model:
                return []
            return [("class", 3144)] if self.distribution else [("other", 3144)]
        return [("required",)] if self.metadata else [("replacement",)]


def receipt():
    return {
        "bundle_sha256": "bundle",
        "artifacts": {
            k: {
                **dict.fromkeys(gate.SOURCE_FIELDS, "pin"),
                "expected_rows": 389856 if k == "climate" else 3144,
                "presentation_measures": sorted(gate.PRESENTATION_MEASURES.get(k, [])),
                "presentation_counties": 3144,
                "measures": sorted(gate.CLIMATE_MEASURES),
                "rows_per_measure": 97464,
                "counties_per_measure": 3144,
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "presentation_rows": 3144 * len(gate.PRESENTATION_MEASURES.get(k, [None])),
                "input_release_id": "old",
                "batch_id": "batch",
                "batch_version": "v1",
                "model_version": "v1",
                "class_counts": {"class": 3144},
            }
            for k in gate.REQUIRED
        },
        "independent_consumers": [
            {"view": v, "minimum_rows": 0, "expected_keys": ["required"]} for v in gate.INDEPENDENT
        ],
    }


def canonical():
    return (
        gate.files("lyme_gap_atlas_data")
        .joinpath("data/canonical-county-fips-2022.txt")
        .read_text()
        .split()
    )


def sources():
    return gate.REQUIRED - {
        "tier1",
        "climate",
        "surveillance-situation-four-state",
        "surveillance-situation-tick-pathogen",
    }


@pytest.mark.parametrize(
    "kind",
    [
        "old_release",
        "replaced_fips",
        "empty_sources",
        "replaced_source",
        "wrong_source_release",
        "lost_provenance",
    ],
)
def test_same_counts_do_not_authorize_wrong_projection_identity(kind):
    class WrongIdentity(ProjectionCursor):
        def fetchall(self):
            rows = super().fetchall()
            if "SELECT release_id,fips" in self.sql:
                if kind == "old_release":
                    return [("old", f) for _, f in rows]
                if kind == "replaced_fips":
                    rows[0] = ("new", "99999")
            if "SELECT release_version,source_key" in self.sql:
                if kind == "empty_sources":
                    return []
                if kind == "replaced_source":
                    rows[0] = ("new", "replacement", *rows[0][2:])
                if kind == "wrong_source_release":
                    rows[0] = ("old", *rows[0][1:])
                if kind == "lost_provenance":
                    rows[0] = (*rows[0][:-1], None)
            return rows

    with pytest.raises(gate.ReleaseCompletenessBlocked, match="identity|attribution"):
        gate.verify_current(WrongIdentity(), "new", receipt())


def test_valid_projected_release_passes():
    gate.verify_current(ProjectionCursor(), "new", receipt())


def test_explicit_zero_eligibility_receipt_is_checked_without_inventing_classes():
    expected = receipt()
    for key in (
        "tier1",
        "surveillance-situation-four-state",
        "surveillance-situation-tick-pathogen",
    ):
        expected["artifacts"][key].update(expected_rows=0, class_counts={})
    gate.verify_current(ProjectionCursor(missing_model=True), "new", expected)


def test_one_measure_cannot_disappear_behind_unchanged_domain_totals():
    class CompensatedLoss(ProjectionCursor):
        def fetchall(self):
            rows = super().fetchall()
            if "GROUP BY source_key" not in self.sql:
                return rows
            removed = next(r for r in rows if r[0] == "context_svi")
            rows.remove(removed)
            index = next(i for i, r in enumerate(rows) if r[0] == "context_svi")
            row = rows[index]
            rows[index] = (row[0], row[1], row[2] * 2, row[3], row[4])
            return rows

    with pytest.raises(gate.ReleaseCompletenessBlocked, match="measure/county footprint changed"):
        gate.verify_current(CompensatedLoss(), "new", receipt())


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
