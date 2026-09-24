"""Executable Story #195 compatibility and frozen county-release contract gates."""

from __future__ import annotations

import ast
import copy
import inspect
import json
import textwrap
from pathlib import Path

import pytest
from test_semantic_domain import measure
from test_semantic_lineage import _trace
from test_semantic_release import _manifest
from test_semantic_source_mappings import _case

from lyme_gap_atlas_data import semantic_release
from lyme_gap_atlas_data.semantic_governance import (
    Outcome,
    SemanticGovernanceError,
    compare_lineage,
    compare_mapping,
    compare_measure,
    compare_metadata,
    compare_release,
    compare_revision,
    require_measure_transition,
    validate_cross_contract,
    validate_mapping_transition,
)
from lyme_gap_atlas_data.semantic_metadata import metadata_revision_id
from lyme_gap_atlas_data.semantic_source_mappings import load_mapping_registry, map_record

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads(
    (ROOT / "tests/fixtures/semantic_governance/county-release-v1.json").read_text()
)
MAPPINGS = load_mapping_registry(
    ROOT / "docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json"
)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("definition", "different meaning", "SEMANTIC_VERSION_REQUIRED"),
        ("unit", "persons", "UNIT_INCOMPATIBLE"),
        ("denominator", "population", "DENOMINATOR_INCOMPATIBLE"),
        ("geography_grain", "SITE_EVENT", "GEOGRAPHY_INCOMPATIBLE"),
        ("temporal_semantics", "POINT_IN_TIME", "TEMPORAL_SEMANTICS_INCOMPATIBLE"),
    ],
)
def test_breaking_measure_requires_major_version(field: str, value: str, reason: str) -> None:
    old = measure()
    new = copy.deepcopy(old)
    new[field] = value
    assert compare_measure(old, new).reason_code == reason
    with pytest.raises(SemanticGovernanceError, match=reason):
        require_measure_transition(old, new)
    new["semantic_version"] = "2.0.0"
    assert require_measure_transition(old, new).outcome == Outcome.REQUIRES_NEW_SEMANTIC_VERSION


def test_label_and_optional_stratum_transitions() -> None:
    old = measure()
    label = copy.deepcopy(old)
    label["label"] = "A better display label"
    assert compare_measure(old, label).outcome == Outcome.IDENTICAL
    extension = copy.deepcopy(old)
    extension["allowed_strata"] = ["tick_taxon"]
    assert compare_measure(old, extension).outcome == Outcome.COMPATIBLE
    with pytest.raises(SemanticGovernanceError, match="SEMANTIC_VERSION_REQUIRED"):
        require_measure_transition(old, extension)
    extension["semantic_version"] = "1.1.0"
    assert require_measure_transition(old, extension).outcome == Outcome.COMPATIBLE
    extension["allowed_strata"] = ["unreviewed_stratum"]
    with pytest.raises(ValueError, match="invalid allowed strata"):
        compare_measure(old, extension)


def test_label_only_metadata_revision_is_compatible() -> None:
    trace, _ = _trace("case_count_floor_2023")
    old = trace["metadata"]
    new = copy.deepcopy(old)
    new["metadata_revision"] += 1
    new["label"] = "Clearer label"
    new["revision_id"] = metadata_revision_id(new)
    assert compare_metadata(old, new).outcome == Outcome.COMPATIBLE
    new["definition"] = "Changed scientific definition"
    new["measure"]["definition"] = new["definition"]
    new["revision_id"] = metadata_revision_id(new)
    with pytest.raises(SemanticGovernanceError):
        compare_metadata(old, new)


@pytest.mark.parametrize("identity", list(MAPPINGS))
def test_governed_mapping_identity_is_stable(identity: str) -> None:
    mapping = MAPPINGS[identity]
    assert compare_mapping(mapping, copy.deepcopy(mapping)).outcome == Outcome.IDENTICAL
    changed = dict(mapping, vintage="new-vintage")
    assert compare_mapping(mapping, changed).outcome == Outcome.REQUIRES_NEW_REVISION


def test_mapping_removal_and_foreign_source_fail() -> None:
    remaining = dict(MAPPINGS)
    remaining.pop("human_surveillance")
    with pytest.raises(SemanticGovernanceError, match="MAPPING_REMOVAL_UNDECLARED"):
        validate_mapping_transition(MAPPINGS, remaining, {})
    replacement = copy.deepcopy(MAPPINGS)
    replacement["human_surveillance"] = dict(
        replacement["human_surveillance"], resource_key="foreign_resource"
    )
    with pytest.raises(SemanticGovernanceError, match="UNKNOWN_GOVERNED_MAPPING"):
        validate_mapping_transition(MAPPINGS, replacement, {})
    validate_mapping_transition(
        MAPPINGS,
        remaining,
        {
            "human_surveillance": {
                "identity": "human_surveillance",
                "kind": "SOURCE_MAPPING",
                "state": "DEPRECATED",
                "effective_semantic_version": "2.0.0",
                "replacement_identity": None,
                "migration_expectation": "Retain historical v1 mapping for old releases.",
            }
        },
    )


def test_lineage_and_result_revisions_are_immutable() -> None:
    trace, authority = _trace("case_count_floor_2023")
    assert compare_lineage(trace, copy.deepcopy(trace)).outcome == Outcome.IDENTICAL
    observation = trace["observation"]
    assert compare_revision(observation, copy.deepcopy(observation)).outcome == Outcome.IDENTICAL
    tampered = copy.deepcopy(trace)
    tampered["metadata"]["label"] = "silent edit"
    with pytest.raises(SemanticGovernanceError, match="IMMUTABLE_LINEAGE_COLLISION"):
        compare_lineage(trace, tampered)
    validate_cross_contract(
        [trace["metadata"]["measure"]], [trace["metadata"]], [trace], authority, {}
    )
    orphan = copy.deepcopy(trace)
    orphan["metadata"]["revision_id"] = "missing"
    with pytest.raises(SemanticGovernanceError, match="METADATA_REVISION_INVALID"):
        validate_cross_contract(
            [trace["metadata"]["measure"]], [trace["metadata"]], [orphan], authority, {}
        )


def test_composed_mapping_references_and_exact_source() -> None:
    record, metadata, authority = _case("human_surveillance")
    mapped = map_record(record, metadata, authority, MAPPINGS, fixture_mode=True)
    validate_cross_contract(
        [metadata["measure"]],
        [metadata],
        [mapped["lineage"]],
        authority,
        {"human_surveillance": MAPPINGS["human_surveillance"]},
        [mapped],
    )
    foreign = copy.deepcopy(mapped)
    foreign["mapping_id"] = "foreign"
    foreign_mapping = dict(MAPPINGS["human_surveillance"], resource_key="foreign_resource")
    with pytest.raises(SemanticGovernanceError, match="UNKNOWN_GOVERNED_MAPPING"):
        validate_cross_contract(
            [metadata["measure"]],
            [metadata],
            [mapped["lineage"]],
            authority,
            {"foreign": foreign_mapping},
            [foreign],
        )


class _CaptureCursor:
    def __init__(self) -> None:
        self.rows: dict[str, list[tuple]] = {}

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        if "SEMANTIC_MEASURES" in sql:
            self.rows["measures"] = rows


def _physical_observation_slots() -> list[tuple[str, str]]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(semantic_release._county_observations)))
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    definition = next(
        node
        for node in function.body
        if isinstance(node, ast.Assign) and node.targets[0].id == "definitions"
    )
    assert isinstance(definition.value, ast.Tuple)
    return [
        (ast.literal_eval(row.elts[1]), ast.literal_eval(row.elts[4]))
        for row in definition.value.elts
        if isinstance(row, ast.Tuple)
    ]


def test_frozen_county_release_slots_and_meaning() -> None:
    assert BASELINE["schema"] == semantic_release.SEMANTIC_SCHEMA
    assert BASELINE["schema_version"] == semantic_release.SEMANTIC_SCHEMA_VERSION
    assert BASELINE["transformation"] == semantic_release.SEMANTIC_TRANSFORMATION
    assert BASELINE["county_count"] == semantic_release.EXPECTED_COUNTIES
    assert BASELINE["observations_per_county"] == semantic_release.EXPECTED_OBSERVATIONS_PER_COUNTY
    assert set(BASELINE["source_slots"]) == semantic_release.REQUIRED_SOURCE_KEYS
    assert _physical_observation_slots() == [
        tuple(row[:2]) for row in BASELINE["observation_slots"]
    ]
    cursor = _CaptureCursor()
    semantic_release._insert_hierarchy(cursor, _manifest())
    rows = cursor.rows["measures"]
    meanings = {row[2]: (row[1], row[4], row[5], row[6], row[7]) for row in rows}
    for measure_id, _, indicator, data_type, unit, grain, temporal in BASELINE["observation_slots"]:
        canonical_id = "county_geometry" if measure_id == "geometry" else measure_id
        assert meanings[canonical_id] == (indicator, data_type, unit, grain, temporal)
    assert BASELINE["historical_exceptions"]["incidence_floor_2023"]["required_inputs"] == [
        "human",
        "context_svi",
    ]
    assert (
        BASELINE["historical_exceptions"]["state_unallocated_records_2023"]["native_grain"]
        == "STATE"
    )
    views_sql = (ROOT / "migrations/V072__governed_semantic_release_views.sql").read_text()
    for view in BASELINE["public_views"]:
        assert f"CREATE OR REPLACE VIEW PRESENTATION.{view} AS" in views_sql
    assert semantic_release._value_state(None) == "MISSING"
    assert semantic_release._value_state(0) == "ZERO"
    assert semantic_release._value_state("Unknown") == "UNKNOWN"
    assert semantic_release._value_state("Suppressed") == "SUPPRESSED"


def test_candidate_cannot_change_old_release_meaning() -> None:
    old = dict(BASELINE, release_id="current")
    candidate = copy.deepcopy(old)
    candidate["release_id"] = "candidate"
    assert compare_release(old, candidate).outcome == Outcome.REQUIRES_NEW_REVISION
    candidate["observation_slots"].pop()
    assert compare_release(old, candidate).reason_code == "RELEASE_BASELINE_REGRESSION"


def test_incidence_floor_uses_human_count_and_svi_population() -> None:
    identity = {"08013": {"population": 100_000, "state": "CO"}}
    rows = [
        {
            "report_year": 2023,
            "county_fips": "08013",
            "frequency": 10,
            "case_status": "confirmed",
            "payload": {},
        }
    ]
    first = semantic_release._human_values(rows, identity)["08013"]
    assert first["incidence"] == 10
    identity["08013"]["population"] = 200_000
    second = semantic_release._human_values(rows, identity)["08013"]
    assert second["incidence"] == 5
    assert first["case_count"] == second["case_count"] == 10


def test_state_unallocated_is_not_county_native() -> None:
    slots = {row[0]: row for row in BASELINE["observation_slots"]}
    assert slots["state_unallocated_records_2023"][5] == "STATE"
    assert not BASELINE["historical_exceptions"]["state_unallocated_records_2023"][
        "county_observation_adapter_allowed"
    ]


class _ReleaseCursor:
    def __init__(self, responses: list[tuple | None]) -> None:
        self.responses = iter(responses)
        self.statements: list[str] = []

    def __enter__(self) -> _ReleaseCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, *_args: object) -> None:
        self.statements.append(sql)

    def fetchone(self) -> tuple | None:
        return next(self.responses)


class _ReleaseConnection:
    def __init__(self, responses: list[tuple | None]) -> None:
        self.sql = _ReleaseCursor(responses)
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> _ReleaseConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _ReleaseCursor:
        return self.sql

    def autocommit(self, _enabled: bool) -> None:
        return None

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.parametrize(
    "responses",
    [
        [("PUBLISHED", "bundle")],
        [("CANDIDATE", "bundle"), (3144, 3144, 44015)],
    ],
)
def test_invalid_candidate_cannot_replace_current_pointer(
    monkeypatch: pytest.MonkeyPatch, responses: list[tuple | None]
) -> None:
    connection = _ReleaseConnection(responses)
    monkeypatch.setattr(semantic_release, "connect", lambda _settings: connection)
    with pytest.raises(semantic_release.SemanticReleaseBlocked):
        semantic_release.publish_semantic_release(None, "candidate", reason="fixture")
    assert connection.rolled_back
    assert not connection.committed
    assert not any(
        "MERGE INTO PRESENTATION.SEMANTIC_RELEASE_POINTER" in sql
        for sql in connection.sql.statements
    )
