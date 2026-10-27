"""County-year CDC Lyme history for the governed semantic release.

Sex and age strata are summed away and are not released. Confirmed and probable
counts become one published floor per county-year. Report year 2022 is omitted
by ``HISTORY_EXCLUDED_REPORT_YEARS`` only. Story #856 admits 2022 by removing
that year from the set. There is no second history path, measure, label, or
vintage for 2022.

The 2023 measures stay on their existing fields. This module does not write
``case_count_floor_2023`` or any other current-release county column.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .surveillance_methodology import definition_break_label, methodology_era_id_for_year

HISTORY_SOURCE_KEY = "cdc_historical"
COUNTY_MEASURE_ID = "human_case_count_published_floor_annual"
STATE_MEASURE_ID = "state_unallocated_records_annual"
TRANSFORMATION_VERSION = "cdc_county_year_history_v1"
COUNTY_GEOGRAPHY_VINTAGE = "county_2025_tiger"
LEGACY_CT_GEOGRAPHY_VINTAGE = "legacy_ct_counties_2008_2022"
CT_GEOGRAPHY_CLASS = "ct_legacy_county_codes"
LEGACY_CT_FIPS = frozenset({"09001", "09003", "09005", "09007", "09009", "09011", "09013", "09015"})
PUBLISHED_FLOOR = 5
CENSOR_UNALLOCATED = "state_year_unallocated_remainder"
CENSOR_FLOOR = "cdc_published_floor_lt5_not_published"
CENSOR_WITHHELD = "geography_withheld"
VALUE_OBSERVED = "OBSERVED"
VALUE_MISSING = "MISSING"
# Years the historical source can contribute. 2023 stays on the current
# measures. #856 removes 2022 from HISTORY_EXCLUDED_REPORT_YEARS and does not
# add another filter.
HISTORY_SOURCE_YEARS = frozenset(range(2008, 2023))
HISTORY_EXCLUDED_REPORT_YEARS = frozenset({2022})
METHODOLOGY_NOTE = (
    "CDC reported Lyme surveillance cases by county of residence. "
    "Report year 2022 is not in this release. "
    "The 2008-2021 case definition is not directly comparable with the 2022 onward definition. "
    "These counts are not infection incidence."
)
MEASURE_LIMITATION = (
    "A null case count is not a reported zero. "
    "Sex and age strata are not released. "
    "Legacy Connecticut counties use geography class ct_legacy_county_codes "
    "and geography vintage legacy_ct_counties_2008_2022 and have no atlas geometry. "
    "Report year 2022 is not in this release."
)
PROVEN_SOURCE_ROWS = 40_468
PROVEN_ANCHORS = {
    "source_rows": PROVEN_SOURCE_ROWS,
    "distinct_county_fips": 784,
    "numeric_county_years": 6_445,
    "cases_2008": 35_198,
    "unallocated_2008": 3_337,
    "cases_2021": 24_611,
    "unallocated_2021": 1_583,
    "unallocated_cases": 31_245,
    "suppressed_rows": 83,
    "suppressed_cases": 561,
}
_WITHHELD_TOKENS = frozenset({"unknown", "suppressed", "not reported"})
_CONFIRMED_PROBABLE = frozenset({"confirmed", "probable"})
_STATE_NAMES = {
    "ALABAMA": "AL",
    "ALASKA": "AK",
    "ARIZONA": "AZ",
    "ARKANSAS": "AR",
    "CALIFORNIA": "CA",
    "COLORADO": "CO",
    "CONNECTICUT": "CT",
    "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "HAWAII": "HI",
    "IDAHO": "ID",
    "ILLINOIS": "IL",
    "INDIANA": "IN",
    "IOWA": "IA",
    "KANSAS": "KS",
    "KENTUCKY": "KY",
    "LOUISIANA": "LA",
    "MAINE": "ME",
    "MARYLAND": "MD",
    "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI",
    "MINNESOTA": "MN",
    "MISSISSIPPI": "MS",
    "MISSOURI": "MO",
    "MONTANA": "MT",
    "NEBRASKA": "NE",
    "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM",
    "NEW YORK": "NY",
    "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND",
    "OHIO": "OH",
    "OKLAHOMA": "OK",
    "OREGON": "OR",
    "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN",
    "TEXAS": "TX",
    "UTAH": "UT",
    "VERMONT": "VT",
    "VIRGINIA": "VA",
    "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI",
    "WYOMING": "WY",
}
_POSTAL_TO_FIPS = {
    "AL": "01",
    "AK": "02",
    "AZ": "04",
    "AR": "05",
    "CA": "06",
    "CO": "08",
    "CT": "09",
    "DE": "10",
    "DC": "11",
    "FL": "12",
    "GA": "13",
    "HI": "15",
    "ID": "16",
    "IL": "17",
    "IN": "18",
    "IA": "19",
    "KS": "20",
    "KY": "21",
    "LA": "22",
    "ME": "23",
    "MD": "24",
    "MA": "25",
    "MI": "26",
    "MN": "27",
    "MS": "28",
    "MO": "29",
    "MT": "30",
    "NE": "31",
    "NV": "32",
    "NH": "33",
    "NJ": "34",
    "NM": "35",
    "NY": "36",
    "NC": "37",
    "ND": "38",
    "OH": "39",
    "OK": "40",
    "OR": "41",
    "PA": "42",
    "RI": "44",
    "SC": "45",
    "SD": "46",
    "TN": "47",
    "TX": "48",
    "UT": "49",
    "VT": "50",
    "VA": "51",
    "WA": "53",
    "WV": "54",
    "WI": "55",
    "WY": "56",
}


class CountyYearHistoryBlocked(ValueError):
    """Raised when history rows cannot be admitted without changing a value."""


@dataclass(frozen=True)
class CountyYearHistory:
    observations: tuple[tuple[Any, ...], ...]
    summary: dict[str, int]
    methodology_note: str


def history_report_years() -> tuple[int, ...]:
    """Admitted report years. 2022 leaves this set only via the exclusion constant."""
    return tuple(sorted(HISTORY_SOURCE_YEARS - HISTORY_EXCLUDED_REPORT_YEARS))


def history_measure_definitions() -> tuple[tuple[Any, ...], ...]:
    """Semantic measure rows for the two history measures. Existing measures stay."""
    shared = (
        "integer",
        "cases",
        "report_year",
        "Null means no published county-year value. Null is not zero.",
        METHODOLOGY_NOTE,
        MEASURE_LIMITATION,
    )
    return (
        (
            "human_disease_burden",
            COUNTY_MEASURE_ID,
            "Reported surveillance case floor",
            shared[0],
            shared[1],
            "COUNTY_FIPS_5",
            *shared[2:],
        ),
        (
            "human_disease_burden",
            STATE_MEASURE_ID,
            "State-unallocated reported surveillance cases",
            shared[0],
            "records",
            "STATE",
            *shared[2:],
        ),
    )


def assert_proven_anchors(summary: Mapping[str, int]) -> None:
    """Fail closed when a full CONFORMED extract does not match the proven sums."""
    mismatches = [
        f"{key}={summary.get(key)}"
        for key, expected in PROVEN_ANCHORS.items()
        if summary.get(key) != expected
    ]
    if mismatches:
        raise CountyYearHistoryBlocked(
            "CDC history does not match the proven CONFORMED anchors: " + ", ".join(mismatches)
        )


def build_county_year_history(
    rows: Iterable[Mapping[str, Any]],
    *,
    atlas_fips: Collection[str],
    release_id: str,
    source_version_id: str,
    ingestion_run_id: str,
    artifact_id: str,
    retrieved_at: Any,
) -> CountyYearHistory:
    """Sum stratified rows into release observations. Null never becomes zero."""
    admitted = set(history_report_years())
    atlas = set(atlas_fips)
    source_rows = list(rows)
    distinct_fips = {
        str(row.get("county_fips")).strip()
        for row in source_rows
        if row.get("county_fips") not in (None, "")
    }
    county_totals: dict[tuple[str, int], int] = defaultdict(int)
    county_seen: set[tuple[str, int]] = set()
    county_lineage: dict[tuple[str, int], list[str]] = defaultdict(list)
    unallocated: dict[tuple[str, int], int] = defaultdict(int)
    unallocated_lineage: dict[tuple[str, int], list[str]] = defaultdict(list)
    withheld_counties: set[tuple[str, int]] = set()
    suppressed_rows = 0
    suppressed_cases = 0

    for row in source_rows:
        payload = _payload(row)
        year = _year(row.get("report_year"), payload.get("year"))
        if year not in admitted:
            continue
        frequency = _frequency(row.get("frequency"), payload.get("frequency"))
        fips = _fips(row.get("county_fips"), payload.get("fips"))
        state_text = _text(payload.get("state") or payload.get("STATE") or row.get("state"))
        record_id = _text(row.get("source_record_id")) or _stable_id(
            json.dumps(payload, default=str)
        )
        status = _text(row.get("case_status") or payload.get("case_status")).casefold()
        if _is_state_suppressed(state_text):
            suppressed_rows += 1
            if frequency is not None:
                suppressed_cases += frequency
            continue
        if fips is None:
            state_fips = _state_fips(state_text)
            if state_fips is None:
                raise CountyYearHistoryBlocked(
                    "Historical row has no county and no resolvable state"
                )
            if frequency is not None:
                unallocated[(state_fips, year)] += frequency
            unallocated_lineage[(state_fips, year)].append(record_id)
            continue
        field_status = _status_token(row.get("source_value_status"), "county_fips")
        if field_status in _WITHHELD_TOKENS and frequency is None:
            withheld_counties.add((fips, year))
            continue
        if status not in _CONFIRMED_PROBABLE:
            continue
        county_seen.add((fips, year))
        county_lineage[(fips, year)].append(record_id)
        if frequency is None:
            continue
        county_totals[(fips, year)] += frequency

    observations: list[tuple[Any, ...]] = []
    observed_keys: set[tuple[str, int]] = set()
    numeric_county_years = 0
    cases_by_year: dict[int, int] = defaultdict(int)
    for fips, year in sorted(county_seen):
        total = county_totals.get((fips, year), 0)
        if (fips, year) not in county_totals or total < PUBLISHED_FLOOR:
            withheld_counties.discard((fips, year))
            continue
        state_fips = fips[:2]
        censored = unallocated.get((state_fips, year), 0) > 0
        observations.append(
            _observation(
                release_id=release_id,
                measure_id=COUNTY_MEASURE_ID,
                fips=fips,
                year=year,
                case_count=total,
                value_state=VALUE_OBSERVED,
                is_censored=censored,
                censor_reason=CENSOR_UNALLOCATED if censored else None,
                source_version_id=source_version_id,
                ingestion_run_id=ingestion_run_id,
                artifact_id=artifact_id,
                source_record_id=_stable_id(f"county:{fips}:{year}"),
                source_row_hash=_stable_id("|".join(sorted(county_lineage[(fips, year)]))),
                retrieved_at=retrieved_at,
                geography_semantics="COUNTY_FIPS_5",
            )
        )
        observed_keys.add((fips, year))
        numeric_county_years += 1
        cases_by_year[year] += total

    for fips in sorted(atlas):
        if not _five_digit(fips):
            raise CountyYearHistoryBlocked("Atlas county identity is not a five-digit FIPS")
        for year in history_report_years():
            if (fips, year) in observed_keys:
                continue
            reason = CENSOR_WITHHELD if (fips, year) in withheld_counties else CENSOR_FLOOR
            observations.append(
                _observation(
                    release_id=release_id,
                    measure_id=COUNTY_MEASURE_ID,
                    fips=fips,
                    year=year,
                    case_count=None,
                    value_state=VALUE_MISSING,
                    is_censored=True,
                    censor_reason=reason,
                    source_version_id=source_version_id,
                    ingestion_run_id=ingestion_run_id,
                    artifact_id=artifact_id,
                    source_record_id=_stable_id(f"missing:{fips}:{year}"),
                    source_row_hash=_stable_id(f"missing:{fips}:{year}"),
                    retrieved_at=retrieved_at,
                    geography_semantics="COUNTY_FIPS_5",
                )
            )

    unallocated_cases = 0
    unallocated_by_year: dict[int, int] = defaultdict(int)
    for (state_fips, year), total in sorted(unallocated.items()):
        if total <= 0:
            continue
        unallocated_cases += total
        unallocated_by_year[year] += total
        observations.append(
            _observation(
                release_id=release_id,
                measure_id=STATE_MEASURE_ID,
                fips=None,
                year=year,
                case_count=total,
                value_state=VALUE_OBSERVED,
                is_censored=True,
                censor_reason=CENSOR_UNALLOCATED,
                source_version_id=source_version_id,
                ingestion_run_id=ingestion_run_id,
                artifact_id=artifact_id,
                source_record_id=_stable_id(f"state:{state_fips}:{year}"),
                source_row_hash=_stable_id(
                    "|".join(sorted(unallocated_lineage[(state_fips, year)]))
                ),
                retrieved_at=retrieved_at,
                geography_semantics="STATE",
                state_fips=state_fips,
            )
        )

    summary = {
        "source_rows": len(source_rows),
        "distinct_county_fips": len(distinct_fips),
        "numeric_county_years": numeric_county_years,
        "cases_2008": cases_by_year[2008] + unallocated_by_year[2008],
        "unallocated_2008": unallocated_by_year[2008],
        "cases_2021": cases_by_year[2021] + unallocated_by_year[2021],
        "unallocated_2021": unallocated_by_year[2021],
        "unallocated_cases": unallocated_cases,
        "suppressed_rows": suppressed_rows,
        "suppressed_cases": suppressed_cases,
        "observation_count": len(observations),
        "state_remainder_rows": sum(1 for row in observations if row[2] == STATE_MEASURE_ID),
    }
    if len(source_rows) == PROVEN_SOURCE_ROWS:
        assert_proven_anchors(summary)
    return CountyYearHistory(
        observations=tuple(observations),
        summary=summary,
        methodology_note=METHODOLOGY_NOTE,
    )


def _observation(
    *,
    release_id: str,
    measure_id: str,
    fips: str | None,
    year: int,
    case_count: int | None,
    value_state: str,
    is_censored: bool,
    censor_reason: str | None,
    source_version_id: str,
    ingestion_run_id: str,
    artifact_id: str,
    source_record_id: str,
    source_row_hash: str,
    retrieved_at: Any,
    geography_semantics: str,
    state_fips: str | None = None,
) -> tuple[Any, ...]:
    if value_state not in {VALUE_OBSERVED, VALUE_MISSING}:
        raise CountyYearHistoryBlocked("History value_state must stay OBSERVED or MISSING")
    if value_state == VALUE_MISSING and case_count is not None:
        raise CountyYearHistoryBlocked("A missing history value cannot carry a count")
    if value_state == VALUE_OBSERVED and case_count is None:
        raise CountyYearHistoryBlocked("An observed history value requires a published count")
    if case_count == 0:
        raise CountyYearHistoryBlocked("A reported zero is not a history value state")
    resolved_state = state_fips if state_fips is not None else (fips[:2] if fips else None)
    if resolved_state is None:
        raise CountyYearHistoryBlocked("History row is missing a state FIPS")
    vintage = _vintage(fips, resolved_state)
    geography_class = _geography_class(fips, resolved_state)
    era = definition_break_label(year)
    era_id = methodology_era_id_for_year(year)
    value = {
        "case_count": case_count,
        "censor_reason": censor_reason,
        "geography_class": geography_class,
        "geography_vintage": vintage,
        "is_censored": is_censored,
        "methodology_era": era,
        "methodology_era_id": era_id,
        "methodology_note": METHODOLOGY_NOTE,
        "state_fips": resolved_state,
    }
    return (
        _stable_id(f"observation:{release_id}:{measure_id}:{fips or resolved_state}:{year}"),
        release_id,
        measure_id,
        fips,
        HISTORY_SOURCE_KEY,
        source_version_id,
        ingestion_run_id,
        artifact_id,
        source_record_id,
        source_row_hash,
        json.dumps(value, separators=(",", ":"), sort_keys=True),
        value_state,
        retrieved_at,
        geography_semantics,
        str(year),
        TRANSFORMATION_VERSION,
        "PASSED",
        MEASURE_LIMITATION,
    )


def _vintage(fips: str | None, state_fips: str) -> str:
    if fips in LEGACY_CT_FIPS or (fips is None and state_fips == "09"):
        return LEGACY_CT_GEOGRAPHY_VINTAGE
    return COUNTY_GEOGRAPHY_VINTAGE


def _geography_class(fips: str | None, state_fips: str) -> str | None:
    if fips in LEGACY_CT_FIPS or (fips is None and state_fips == "09"):
        return CT_GEOGRAPHY_CLASS
    return None


def _payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as error:
            raise CountyYearHistoryBlocked("Historical payload is not valid JSON") from error
    if payload in (None, ""):
        return {}
    if not isinstance(payload, dict):
        raise CountyYearHistoryBlocked("Historical payload is not an object")
    record = payload.get("record")
    return record if isinstance(record, dict) else payload


def _year(primary: Any, fallback: Any) -> int | None:
    for value in (primary, fallback):
        if value in (None, ""):
            continue
        if isinstance(value, bool):
            raise CountyYearHistoryBlocked("Historical report year is not numeric")
        try:
            year = int(value)
        except (TypeError, ValueError) as error:
            raise CountyYearHistoryBlocked("Historical report year is not numeric") from error
        return year
    return None


def _frequency(primary: Any, fallback: Any) -> int | None:
    for value in (primary, fallback):
        if value is None or value == "":
            continue
        if isinstance(value, str) and value.strip().casefold() in _WITHHELD_TOKENS | {"null"}:
            return None
        if isinstance(value, bool):
            raise CountyYearHistoryBlocked("Historical frequency is not numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise CountyYearHistoryBlocked("Historical frequency is not numeric") from error
        if not number.is_integer():
            raise CountyYearHistoryBlocked("Historical frequency is not a whole number")
        return int(number)
    return None


def _fips(primary: Any, fallback: Any) -> str | None:
    for value in (primary, fallback):
        text = _text(value)
        if _five_digit(text):
            return text
    return None


def _five_digit(value: str) -> bool:
    return len(value) == 5 and value.isdigit()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _is_state_suppressed(state_text: str) -> bool:
    return state_text.casefold() == "suppressed"


def _state_fips(state_text: str) -> str | None:
    if state_text.casefold() in _WITHHELD_TOKENS:
        return None
    postal = state_text.upper() if len(state_text) == 2 and state_text.isalpha() else None
    if postal is None:
        postal = _STATE_NAMES.get(state_text.upper())
    if postal is None:
        return None
    return _POSTAL_TO_FIPS.get(postal)


def _status_token(status: Any, field: str) -> str | None:
    if isinstance(status, str):
        raw = status
        try:
            status = json.loads(raw)
        except ValueError:
            return raw.casefold()
    if isinstance(status, Mapping):
        value = status.get(field)
        return _text(value).casefold() or None
    return None


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
