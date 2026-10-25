"""County-year history admits 2008-2021, keeps 2023, and documents the 2022 gap."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lyme_gap_atlas_data import semantic_release
from lyme_gap_atlas_data.alpha_parity import AlphaParityError, existing_county_fields_unchanged
from lyme_gap_atlas_data.cdc_county_year_history import (
    CENSOR_FLOOR,
    CENSOR_UNALLOCATED,
    CENSOR_WITHHELD,
    COUNTY_MEASURE_ID,
    CT_GEOGRAPHY_CLASS,
    HISTORY_EXCLUDED_REPORT_YEARS,
    HISTORY_SOURCE_KEY,
    HISTORY_SOURCE_YEARS,
    LEGACY_CT_GEOGRAPHY_VINTAGE,
    MEASURE_LIMITATION,
    METHODOLOGY_NOTE,
    PROVEN_ANCHORS,
    STATE_MEASURE_ID,
    CountyYearHistory,
    CountyYearHistoryBlocked,
    assert_proven_anchors,
    build_county_year_history,
    history_measure_definitions,
    history_report_years,
)
from lyme_gap_atlas_data.migrations import (
    CDC_COUNTY_YEAR_HISTORY_MIGRATION,
    DEV_ONLY_MIGRATION_VERSIONS,
    HELD_BACK_DEV_MIGRATION_VERSIONS,
    PROD_ONLY_MIGRATION_VERSIONS,
    PROTECTED_INTELLIGENCE_MIGRATIONS,
    load_migrations,
    migration_execution_role,
    migration_plan,
)
from lyme_gap_atlas_data.surveillance_methodology import (
    definition_break_label,
    methodology_era_id_for_year,
)

ROOT_MIGRATION = Path(__file__).parents[1] / "migrations" / "V176__cdc_county_year_history_view.sql"
_RETRIEVED = datetime(2026, 10, 25, tzinfo=UTC)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "county_fips": "01001",
        "report_year": 2008,
        "case_status": "Confirmed",
        "sex": "Male",
        "age_category_years": "5-9",
        "frequency": 5,
        "source_value_status": {"county_fips": "observed"},
        "payload": {"state": "Alabama"},
        "source_record_id": "row",
    }
    row.update(overrides)
    return row


def _built() -> CountyYearHistory:
    rows = [
        _row(source_record_id="a", sex="Male", frequency=5),
        _row(source_record_id="b", sex="Female", case_status="Probable", frequency=2),
        _row(source_record_id="c", frequency=None, sex="Unknown"),
        _row(
            source_record_id="unallocated",
            county_fips="Unknown",
            case_status="Confirmed",
            frequency=3,
            payload={"state": "Alabama"},
        ),
        _row(source_record_id="y2021", report_year=2021, frequency=6, sex="Female"),
        _row(source_record_id="y2022", report_year=2022, frequency=9),
        _row(source_record_id="y2023", report_year=2023, frequency=11),
        _row(
            source_record_id="ct",
            county_fips="09001",
            report_year=2008,
            frequency=10,
            payload={"state": "Connecticut"},
        ),
        _row(
            source_record_id="ct2011",
            county_fips="09003",
            report_year=2011,
            frequency=8,
            payload={"state": "Connecticut"},
        ),
        _row(
            source_record_id="suppressed",
            county_fips=None,
            frequency=4,
            payload={"state": "Suppressed"},
        ),
        _row(
            source_record_id="withheld",
            report_year=2010,
            frequency=None,
            source_value_status={"county_fips": "suppressed"},
        ),
    ]
    return build_county_year_history(
        rows,
        atlas_fips={"01001", "09110"},
        release_id="history-test",
        source_version_id="version-1",
        ingestion_run_id="run-1",
        artifact_id="artifact-1",
        retrieved_at=_RETRIEVED,
    )


def _values(built: CountyYearHistory) -> list[dict[str, object]]:
    parsed = []
    for row in built.observations:
        value = json.loads(row[10])
        value["measure_id"] = row[2]
        value["fips"] = row[3]
        value["value_state"] = row[11]
        value["year"] = int(row[14])
        parsed.append(value)
    return parsed


def test_year_set_excludes_2022_in_one_place_and_leaves_2023_out() -> None:
    assert frozenset({2022}) == HISTORY_EXCLUDED_REPORT_YEARS
    assert history_report_years() == tuple(range(2008, 2022))
    assert 2022 in HISTORY_SOURCE_YEARS
    assert 2023 not in HISTORY_SOURCE_YEARS
    assert tuple(sorted(HISTORY_SOURCE_YEARS - frozenset())) == tuple(range(2008, 2023))
    assert definition_break_label(2008) == "2008_2021_pre_2022_definition"
    assert definition_break_label(2023) == "2022_onward_definition"
    assert methodology_era_id_for_year(2008) == "cdc_2008"
    assert methodology_era_id_for_year(2011) == "cdc_2011"
    assert methodology_era_id_for_year(2017) == "cdc_2017"
    assert methodology_era_id_for_year(2022) == "cdc_2022"


def test_history_builds_2008_and_2021_and_leaves_2022_and_2023_absent() -> None:
    built = _built()
    values = _values(built)
    years = {row["year"] for row in values}
    assert 2008 in years
    assert 2021 in years
    assert 2022 not in years
    assert 2023 not in years
    assert all(row["methodology_note"] == METHODOLOGY_NOTE for row in values)
    assert all(
        "Report year 2022 is not in this release." in str(row["methodology_note"]) for row in values
    )
    assert all(row["methodology_era"] == "2008_2021_pre_2022_definition" for row in values)
    assert all(row["value_state"] in {"OBSERVED", "MISSING"} for row in values)
    forbidden = {"sex", "age", "age_category_years", "trend", "ratio", "difference"}
    assert all(forbidden.isdisjoint(row) for row in values)

    county_2008 = next(row for row in values if row["fips"] == "01001" and row["year"] == 2008)
    assert county_2008["case_count"] == 7
    assert county_2008["value_state"] == "OBSERVED"
    assert county_2008["is_censored"] is True
    assert county_2008["censor_reason"] == CENSOR_UNALLOCATED
    assert county_2008["methodology_era_id"] == "cdc_2008"
    assert county_2008["geography_vintage"] == "county_2025_tiger"

    county_2021 = next(row for row in values if row["fips"] == "01001" and row["year"] == 2021)
    assert county_2021["case_count"] == 6
    assert county_2021["is_censored"] is False
    assert county_2021["censor_reason"] is None
    assert county_2021["methodology_era_id"] == "cdc_2017"

    legacy = next(row for row in values if row["fips"] == "09001")
    assert legacy["case_count"] == 10
    assert legacy["geography_vintage"] == LEGACY_CT_GEOGRAPHY_VINTAGE
    assert legacy["geography_class"] == CT_GEOGRAPHY_CLASS
    assert legacy["state_fips"] == "09"

    planning = next(row for row in values if row["fips"] == "09110" and row["year"] == 2008)
    assert planning["case_count"] is None
    assert planning["value_state"] == "MISSING"
    assert planning["censor_reason"] == CENSOR_FLOOR
    assert planning["geography_vintage"] == "county_2025_tiger"
    assert planning["geography_class"] is None

    withheld = next(row for row in values if row["fips"] == "01001" and row["year"] == 2010)
    assert withheld["case_count"] is None
    assert withheld["censor_reason"] == CENSOR_WITHHELD

    state_row = next(row for row in values if row["measure_id"] == STATE_MEASURE_ID)
    assert state_row["fips"] is None
    assert state_row["case_count"] == 3
    assert state_row["value_state"] == "OBSERVED"
    assert state_row["censor_reason"] == CENSOR_UNALLOCATED
    assert state_row["state_fips"] == "01"
    assert built.summary["suppressed_rows"] == 1
    assert built.summary["suppressed_cases"] == 4
    assert built.summary["cases_2008"] == 20
    assert built.summary["unallocated_2008"] == 3
    assert all(row["case_count"] != 0 for row in values)


def test_2023_human_fields_stay_byte_identical_when_history_years_are_present() -> None:
    identity = {"01001": {"population": 100_000, "state": "AL"}}
    rows = [
        {
            "report_year": 2023,
            "county_fips": "01001",
            "frequency": 10,
            "case_status": "confirmed",
            "payload": {},
        },
        {
            "report_year": 2008,
            "county_fips": "01001",
            "frequency": 99,
            "case_status": "confirmed",
            "payload": {},
        },
    ]
    human = semantic_release._human_values(rows, identity)["01001"]
    assert human["case_count"] == 10
    assert human["incidence"] == 10.0
    assert human["human_status"] == "published_count_floor"
    previous = [{"fips": "01001", "case_count_floor_2023": 10, "incidence_floor_2023": 10.0}]
    candidate = [{"fips": "01001", "incidence_floor_2023": 10.0, "case_count_floor_2023": 10}]
    existing_county_fields_unchanged(previous, candidate)
    candidate[0]["case_count_floor_2023"] = 11
    with pytest.raises(AlphaParityError, match="Existing county release fields changed"):
        existing_county_fields_unchanged(previous, candidate)


def test_proven_anchors_match_the_conformed_contract() -> None:
    assert_proven_anchors(PROVEN_ANCHORS)
    drifted = dict(PROVEN_ANCHORS)
    drifted["numeric_county_years"] = 1
    with pytest.raises(CountyYearHistoryBlocked, match="proven CONFORMED anchors"):
        assert_proven_anchors(drifted)
    built = _built()
    assert built.summary["source_rows"] != PROVEN_ANCHORS["source_rows"]


def test_history_measures_do_not_replace_the_2023_measure_ids() -> None:
    measures = {row[1] for row in history_measure_definitions()}
    assert measures == {COUNTY_MEASURE_ID, STATE_MEASURE_ID}
    assert "case_count_floor_2023" not in measures
    assert all(
        row[8] == METHODOLOGY_NOTE and row[9] == MEASURE_LIMITATION
        for row in history_measure_definitions()
    )


def test_v176_is_a_routine_both_environment_migration() -> None:
    migrations = load_migrations()
    versions = [item.version for item in migrations]
    assert versions.index("V170") < versions.index("V176")
    assert "V176" in versions
    assert not {"V171", "V172", "V173", "V174", "V175"} & set(versions)
    migration = next(item for item in migrations if item.version == "V176")
    assert migration.filename == CDC_COUNTY_YEAR_HISTORY_MIGRATION["filename"]
    assert migration.sha256 == CDC_COUNTY_YEAR_HISTORY_MIGRATION["sha256"]
    assert "V176" not in DEV_ONLY_MIGRATION_VERSIONS
    assert "V176" not in PROD_ONLY_MIGRATION_VERSIONS
    assert "V176" not in HELD_BACK_DEV_MIGRATION_VERSIONS
    assert CDC_COUNTY_YEAR_HISTORY_MIGRATION not in PROTECTED_INTELLIGENCE_MIGRATIONS
    assert "V176" in {item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_DEV")}
    assert "V176" in {item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")}
    assert (
        migration_execution_role(migration, "ONE_HEALTH_LYME_GAP_ATLAS_DEV") == "OH_LYME_DEV_OWNER"
    )
    assert (
        migration_execution_role(migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
        == "OH_LYME_PROD_OWNER"
    )
    source = ROOT_MIGRATION.read_text(encoding="utf-8")
    history_sql = source.split("CDC_LYME_COUNTY_YEAR_HISTORY_V1", 1)[1].split("GRANT SELECT", 1)[0]
    where = history_sql.split("WHERE", 1)[1]
    assert "report_year" not in where
    assert "2022" not in history_sql
    assert "BETWEEN" not in history_sql
    metadata = source.split("CURRENT_METHODOLOGY_METADATA_V", 1)[1]
    assert "LINEAGE_AUDIT" not in source
    assert "FEATURE_STORE" not in source
    assert "CURRENT_COUNTY_OBSERVATIONS_V" not in source
    assert "OH_LYME_{{ ENV }}_READ" in source
    assert METHODOLOGY_NOTE in metadata
    assert MEASURE_LIMITATION in metadata
    assert "ct_legacy_county_codes" in metadata
    assert "legacy_ct_counties_2008_2022" in metadata
    assert HISTORY_SOURCE_KEY == "cdc_historical"
    publish = semantic_release.publish_semantic_release.__doc__
    assert publish is not None
    release_source = semantic_release.__file__
    assert release_source is not None
    text = Path(release_source).read_text(encoding="utf-8")
    assert "o.source_key<>'cdc_historical'" in text
