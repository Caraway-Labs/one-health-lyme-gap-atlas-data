"""Independent categorical expectations for the four approved #170 constructs."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_infected_tick_metrics import DENSITY, PREVALENCE
from test_infected_tick_metrics import _canonical as _metric_canonical

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_plan,
)
from lyme_gap_atlas_data.surveillance_coverage import (
    COUNTY,
    EFFORT,
    SAMPLING,
    TESTING,
    evaluate_surveillance_coverage,
)
from lyme_gap_atlas_data.surveillance_coverage_result_store import stage_surveillance_coverage
from lyme_gap_atlas_data.surveillance_coverage_results import serialize_surveillance_coverage


def _canonical(metric: str) -> dict:
    observation = _metric_canonical(metric)
    if metric == PREVALENCE:
        observation["testing_scope"] = "INDIVIDUAL_PATHOGEN_TEST"
        observation["test_result"] = "DETECTED"
    return observation


def _county(status: str = "ESTABLISHED", county: str = "01001") -> dict:
    return {
        "canonical_observation_id": "county-1",
        "observation_type": "VECTOR_PRESENCE_STATUS",
        "source_agency": "CDC",
        "source_dataset_id": "cdc-ixodes-county-status-2025",
        "data_source_version_id": "2025",
        "source_record_id": "source-row-1",
        "ingestion_run_id": "run-1",
        "artifact_id": "artifact-1",
        "retrieved_at": "2026-09-23T00:00:00Z",
        "method_version": "tick-surveillance-v1",
        "county_fips": county,
        "tick_species": "Ixodes scapularis",
        "presence_status": status,
        "temporal_semantics": "CUMULATIVE_THROUGH_DATE",
        "surveillance_period_start": None,
        "surveillance_period_end": "2025-12-31",
        "quality_flags": [],
        "reported_or_derived": "REPORTED",
        "normalization": {
            "registry_id": "tick-surveillance-normalization-v1",
            "registry_version": "1.0.4",
            "mappings": {
                "taxon": {
                    "source_value": "Ixodes_scapularis",
                    "canonical_id": "IXODES_SCAPULARIS",
                    "canonical_label": "Ixodes scapularis",
                    "status": "APPROVED",
                    "mapping_rule_id": "TAXON_CDC_SCAPULARIS_V1",
                    "registry_id": "tick-surveillance-normalization-v1",
                    "registry_version": "1.0.4",
                    "source_context": {
                        "publisher": "CDC ArboNET Tick Module",
                        "dataset_id": "cdc-ixodes-county-status-2025",
                        "source_version": "2025",
                    },
                }
            },
        },
    }


def _county_context(complete: bool = True) -> dict:
    return {
        "approved": True,
        "available": True,
        "source_family": "CDC_IXODES_COUNTY_STATUS",
        "publisher": "CDC ArboNET Tick Module",
        "source_dataset_id": "cdc-ixodes-county-status-2025",
        "source_version_id": "2025",
        "source_vintage": "2025",
        "dimension_mapping": _county()["normalization"]["mappings"]["taxon"],
        "snapshot_complete": complete,
        "snapshot_evidence_id": "reviewed-snapshot-1" if complete else None,
        "snapshot_source_version_id": "2025" if complete else None,
        "scope_approved": complete,
        "publisher_scope": ["01001", "01003", "01005"],
        "canonical_eligible_universe": ["01001", "01003", "01005"],
        "publisher_scope_version": "fixture-scope-v1",
        "canonical_universe_version": "fixture-universe-v1",
        "cumulative_through_date": "2025-12-31",
    }


def _active_context(testing: bool = False) -> dict:
    return {
        "approved": True,
        "available": True,
        "source_family": "NSF_NEON",
        "publisher": "NSF NEON",
        "source_dataset_id": "DP1.10092.001" if testing else "DP1.10093.001",
        "source_version_id": "RELEASE-2026",
        "source_vintage": "RELEASE-2026",
    }


def _evaluate_county(rows: list[dict], *, county: str = "01001", complete: bool = True) -> dict:
    return evaluate_surveillance_coverage(
        COUNTY,
        rows,
        source_context=_county_context(complete),
        county_fips=county,
        dimension="Ixodes scapularis",
    )


def test_county_reported_no_records_omission_and_partial_snapshot() -> None:
    assert _evaluate_county([_county()])["state"] == "REPORTED_STATUS"
    assert _evaluate_county([_county("NO_RECORDS")])["state"] == "PUBLISHER_NO_RECORDS"
    assert _evaluate_county([], county="01003")["state"] == "NOT_REPORTED_IN_DATASET"
    assert _evaluate_county([], county="01003", complete=False)["state"] == "UNKNOWN"
    assert _evaluate_county([], county="99999")["state"] == "NOT_APPLICABLE"
    assert _evaluate_county([_county()], county="01003")["state"] == "UNKNOWN"
    assert _evaluate_county([_county()], county="")["state"] == "UNKNOWN"
    out_of_scope = _county_context()
    out_of_scope["source_geography_in_scope"] = False
    assert (
        evaluate_surveillance_coverage(
            COUNTY,
            [],
            source_context=out_of_scope,
            county_fips=None,
            dimension="Ixodes scapularis",
        )["state"]
        == "NOT_APPLICABLE"
    )
    assert _evaluate_county([_county()], complete=False)["state"] == "UNKNOWN"


def test_county_dedup_revision_and_quality() -> None:
    row = _county()
    once = _evaluate_county([row])
    twice = _evaluate_county([row, deepcopy(row)])
    assert twice["state"] == "REPORTED_STATUS"
    assert twice["input_canonical_observation_ids"] == ["county-1"]
    assert once["coverage_identity"] == twice["coverage_identity"]
    revised = deepcopy(row)
    revised["source_record_id"] = "source-row-2"
    revised["canonical_observation_id"] = "county-2"
    assert _evaluate_county([row, revised])["state"] == "UNKNOWN"
    revised["presence_status"] = "NO_RECORDS"
    conflict = _evaluate_county([row, revised])
    assert conflict["state"] == "UNKNOWN"
    assert conflict["coverage_identity"] == _evaluate_county([revised, row])["coverage_identity"]
    stale = deepcopy(row)
    stale["quality_flags"] = ["STALE_OR_REVISION_SENSITIVE"]
    result = _evaluate_county([stale])
    assert result["state"] == "REPORTED_STATUS"
    assert "STALE_OR_REVISION_SENSITIVE" in result["reason_codes"]
    assert "EFFORT_DENOMINATOR_COMPLETENESS" not in str(result["reason_codes"])


def test_county_pathogen_source_stays_separate_and_unavailable_is_explicit() -> None:
    row = _county("REPORTED")
    row["observation_type"] = "PATHOGEN_PRESENCE_STATUS"
    row["source_dataset_id"] = "cdc-ixodes-pathogen-status-2025"
    row["pathogen_name"] = "Borrelia burgdorferi sensu stricto"
    row["normalization"]["mappings"] = {
        "pathogen": {
            "source_value": "Borrelia_burgdorferi_sensu_stricto",
            "canonical_id": "BORRELIA_BURGDORFERI_SENSU_STRICTO",
            "canonical_label": "Borrelia burgdorferi sensu stricto",
            "status": "APPROVED",
            "mapping_rule_id": "PATHOGEN_CDC_BBURG_V1",
            "registry_id": "tick-surveillance-normalization-v1",
            "registry_version": "1.0.4",
            "source_context": {
                "publisher": "CDC ArboNET Tick Module",
                "dataset_id": "cdc-ixodes-pathogen-status-2025",
                "source_version": "2025",
            },
        }
    }
    context = _county_context()
    context["source_family"] = "CDC_PATHOGEN_COUNTY_STATUS"
    context["source_dataset_id"] = "cdc-ixodes-pathogen-status-2025"
    assert (
        evaluate_surveillance_coverage(
            COUNTY,
            [row],
            source_context=context,
            county_fips="01001",
            dimension="Borrelia burgdorferi sensu stricto",
        )["state"]
        == "REPORTED_STATUS"
    )
    context["available"] = False
    assert (
        evaluate_surveillance_coverage(
            COUNTY,
            [row],
            source_context=context,
            county_fips="01001",
            dimension="Borrelia burgdorferi sensu stricto",
        )["state"]
        == "UNAVAILABLE"
    )


def test_active_sampled_zero_missing_zero_impractical_and_repeated_events() -> None:
    row = _canonical(DENSITY)
    first = evaluate_surveillance_coverage(SAMPLING, [row], source_context=_active_context())
    assert first["state"] == "SAMPLED_EVENT"
    zero = deepcopy(row)
    zero["ticks_collected"] = 0
    assert (
        evaluate_surveillance_coverage(SAMPLING, [zero], source_context=_active_context())["state"]
        == "SAMPLED_EVENT"
    )
    missing = deepcopy(row)
    missing["collection_effort_value"] = None
    missing["missingness"] = {"collection_effort_value": "UNKNOWN"}
    assert (
        evaluate_surveillance_coverage(SAMPLING, [missing], source_context=_active_context())[
            "state"
        ]
        == "UNKNOWN"
    )
    assert (
        evaluate_surveillance_coverage(EFFORT, [missing], source_context=_active_context())["state"]
        == "MISSING_EFFORT"
    )
    no_effort = deepcopy(row)
    no_effort["collection_effort_value"] = 0
    assert (
        evaluate_surveillance_coverage(SAMPLING, [no_effort], source_context=_active_context())[
            "state"
        ]
        == "UNKNOWN"
    )
    assert (
        evaluate_surveillance_coverage(EFFORT, [no_effort], source_context=_active_context())[
            "state"
        ]
        == "ZERO_EFFORT"
    )
    impractical = deepcopy(row)
    impractical["quality_flags"] = ["SAMPLING_IMPRACTICAL"]
    assert (
        evaluate_surveillance_coverage(SAMPLING, [impractical], source_context=_active_context())[
            "state"
        ]
        == "SAMPLING_IMPRACTICAL"
    )
    assert (
        evaluate_surveillance_coverage(EFFORT, [impractical], source_context=_active_context())[
            "state"
        ]
        == "SAMPLING_IMPRACTICAL"
    )
    absent = evaluate_surveillance_coverage(SAMPLING, [], source_context=_active_context())
    assert absent["state"] == "UNKNOWN"
    second = deepcopy(row)
    second["canonical_observation_id"] = "canonical-two"
    second["sampling_event"]["source_event_id"] = "event-two"
    second["surveillance_period_start"] = second["surveillance_period_end"] = "2016-05-08"
    second_result = evaluate_surveillance_coverage(
        SAMPLING, [second], source_context=_active_context()
    )
    assert second_result["state"] == "SAMPLED_EVENT"
    assert first["coverage_identity"] != second_result["coverage_identity"]


def test_active_geography_quality_and_unit_are_conservative() -> None:
    row = _canonical(DENSITY)
    result = evaluate_surveillance_coverage(SAMPLING, [row], source_context=_active_context())
    assert "UNMAPPED_SITE_GEOGRAPHY" in result["reason_codes"]
    assert result["representativeness"] == "NOT_COUNTY_REPRESENTATIVE"
    ambiguous = deepcopy(row)
    ambiguous["county_relationship"]["mapping_status"] = "AMBIGUOUS"
    assert (
        "AMBIGUOUS_SITE_GEOGRAPHY"
        in evaluate_surveillance_coverage(SAMPLING, [ambiguous], source_context=_active_context())[
            "reason_codes"
        ]
    )
    unsupported = deepcopy(row)
    unsupported["collection_effort_unit"] = "unknown unit"
    assert (
        evaluate_surveillance_coverage(EFFORT, [unsupported], source_context=_active_context())[
            "state"
        ]
        == "UNKNOWN"
    )
    no_method = deepcopy(row)
    no_method["collection_method"] = None
    assert (
        evaluate_surveillance_coverage(SAMPLING, [no_method], source_context=_active_context())[
            "state"
        ]
        == "UNKNOWN"
    )
    flag = deepcopy(row)
    flag["collection_method"] = "Flag cloth"
    flag["normalization"]["mappings"]["method"].update(
        {
            "source_value": "flag",
            "canonical_id": "FLAG_CLOTH",
            "canonical_label": "Flag cloth",
            "mapping_rule_id": "METHOD_NEON_FLAG_V1",
        }
    )
    flag_result = evaluate_surveillance_coverage(SAMPLING, [flag], source_context=_active_context())
    assert flag_result["state"] == "SAMPLED_EVENT"
    assert flag_result["coverage_identity"] != result["coverage_identity"]
    older = deepcopy(row)
    older["method_version"] = "tick-surveillance-v1.1"
    assert (
        evaluate_surveillance_coverage(SAMPLING, [older], source_context=_active_context())["state"]
        == "UNAVAILABLE"
    )


def test_testing_denominator_does_not_require_resolved_life_stage() -> None:
    row = _canonical(PREVALENCE)
    row["life_stage"] = "UNKNOWN"
    row["normalization"]["mappings"].pop("stage")
    positive = evaluate_surveillance_coverage(TESTING, [row], source_context=_active_context(True))
    assert positive["state"] == "DOCUMENTED_POSITIVE_TEST_DENOMINATOR"
    negative = deepcopy(row)
    negative["ticks_positive"] = 0
    negative["test_result"] = "NOT_DETECTED"
    negative["normalization"]["mappings"]["result"].update(
        {
            "source_value": "negative",
            "canonical_id": "NOT_DETECTED",
            "canonical_label": "Not detected",
            "mapping_rule_id": "RESULT_NEON_NEGATIVE_V1",
        }
    )
    assert (
        evaluate_surveillance_coverage(TESTING, [negative], source_context=_active_context(True))[
            "state"
        ]
        == "DOCUMENTED_POSITIVE_TEST_DENOMINATOR"
    )
    zero = deepcopy(row)
    zero["ticks_tested"] = 0
    zero["ticks_positive"] = 0
    assert (
        evaluate_surveillance_coverage(TESTING, [zero], source_context=_active_context(True))[
            "state"
        ]
        == "ZERO_TEST_DENOMINATOR"
    )
    missing = deepcopy(row)
    missing["ticks_tested"] = None
    assert (
        evaluate_surveillance_coverage(TESTING, [missing], source_context=_active_context(True))[
            "state"
        ]
        == "MISSING_TEST_DENOMINATOR"
    )
    invalid = deepcopy(row)
    invalid["ticks_positive"] = 2
    assert (
        evaluate_surveillance_coverage(TESTING, [invalid], source_context=_active_context(True))[
            "state"
        ]
        == "UNKNOWN"
    )
    supporting = deepcopy(row)
    supporting["observation_type"] = "NON_PATHOGEN_SUPPORTING_ASSAY"
    assert (
        evaluate_surveillance_coverage(TESTING, [supporting], source_context=_active_context(True))[
            "state"
        ]
        == "NOT_APPLICABLE"
    )


def test_cross_type_and_safe_projection() -> None:
    county = _county()
    assert (
        evaluate_surveillance_coverage(SAMPLING, [county], source_context=_active_context())[
            "state"
        ]
        == "UNAVAILABLE"
    )
    collection = _canonical(DENSITY)
    assert _evaluate_county([collection])["state"] == "UNAVAILABLE"
    result = evaluate_surveillance_coverage(
        SAMPLING, [collection], source_context=_active_context()
    )
    safe = serialize_surveillance_coverage(result, evidence_basis="SYNTHETIC_FIXTURE")
    assert safe["state"] == "SAMPLED_EVENT"
    assert (
        safe["result_id"]
        == serialize_surveillance_coverage(result, evidence_basis="SYNTHETIC_FIXTURE")["result_id"]
    )
    revised = deepcopy(collection)
    revised["canonical_observation_id"] = "revised-observation"
    revised["source_record_id"] = "revised-source-row"
    revised_result = evaluate_surveillance_coverage(
        SAMPLING, [revised], source_context=_active_context()
    )
    assert (
        serialize_surveillance_coverage(revised_result, evidence_basis="SYNTHETIC_FIXTURE")[
            "result_id"
        ]
        != safe["result_id"]
    )
    assert "artifact_id" not in str(safe)
    assert "score" not in safe and "value" not in safe
    unsafe = deepcopy(result)
    unsafe["sampling_site"]["source_site_id"] = "https://restricted.example/raw"
    with pytest.raises(ValueError, match="unsafe"):
        serialize_surveillance_coverage(unsafe, evidence_basis="SYNTHETIC_FIXTURE")
    with pytest.raises(ValueError, match="construct"):
        evaluate_surveillance_coverage("COMPOSITE_COVERAGE_SCORE", [], source_context={})


class _MemoryCursor:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}
        self.current: list[tuple[str]] = []
        self.merges = 0

    def execute(self, sql: str, params: tuple) -> None:
        if sql.startswith("SELECT payload_sha256"):
            self.current = [(self.rows[params[0]],)] if params[0] in self.rows else []
        elif sql.startswith("MERGE INTO"):
            self.merges += 1
            self.rows.setdefault(params[0], params[1])
        else:
            raise AssertionError("unexpected SQL")

    def fetchall(self) -> list[tuple[str]]:
        return self.current


def test_dev_store_is_immutable_and_separate_from_county_release() -> None:
    cursor = _MemoryCursor()
    row = _canonical(DENSITY)
    result = evaluate_surveillance_coverage(SAMPLING, [row], source_context=_active_context())
    first_id, first_state = stage_surveillance_coverage(
        cursor, result, evidence_basis="SYNTHETIC_FIXTURE"
    )
    assert first_state == "STAGED" and cursor.merges == 1
    assert stage_surveillance_coverage(cursor, result, evidence_basis="SYNTHETIC_FIXTURE") == (
        first_id,
        "IDENTICAL_REPLAY",
    )
    assert cursor.merges == 1
    cursor.rows[first_id] = "bad-checksum"
    with pytest.raises(ValueError, match="conflicting"):
        stage_surveillance_coverage(cursor, result, evidence_basis="SYNTHETIC_FIXTURE")
    assert "V101" in {item["version"] for item in migration_plan(DEV_DATABASE)}
    assert "V101" not in {item["version"] for item in migration_plan(PROD_DATABASE)}
    migration = next(item for item in load_migrations() if item.version == "V101")
    sql = migration.source
    assert "PRESENTATION.SURVEILLANCE_COVERAGE_DERIVED_RESULTS" in sql
    assert "SEMANTIC_OBSERVATIONS" not in sql
    assert "OH_LYME_DEV_RUNTIME" in sql and "OH_LYME_DEV_READ" in sql
    assert "OH_LYME_PROD" not in sql


def test_machine_readable_examples_are_separate_categorical_profiles() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "docs/contracts/tick-surveillance/examples/surveillance-coverage-v1-safe-examples.json"
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["evidence_basis"] == "SYNTHETIC_FIXTURE"
    examples = document["examples"]
    assert {item["construct_id"] for item in examples} == {COUNTY, SAMPLING, EFFORT, TESTING}
    assert {item["state"] for item in examples} == {
        "REPORTED_STATUS",
        "SAMPLED_EVENT",
        "DOCUMENTED_POSITIVE_EFFORT",
        "DOCUMENTED_POSITIVE_TEST_DENOMINATOR",
    }
    for item in examples:
        assert item["evidence_basis"] == "SYNTHETIC_FIXTURE"
        assert "score" not in item and "value" not in item
        assert "artifact_id" not in str(item)
        assert item["quality"] is not None
