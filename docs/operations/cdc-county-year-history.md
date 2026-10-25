# CDC 2008–2021 county-year history

Story #855 adds CDC reported Lyme surveillance cases by county of residence for
report years 2008–2021 to the governed semantic release. These counts are not
infection incidence. Nothing in this release computes a difference, ratio, or
trend across the 2022 case-definition boundary.

## What is released

- Measure `human_case_count_published_floor_annual`: confirmed plus probable
  county-year floor. Sex and age strata are not released.
- Measure `state_unallocated_records_annual`: state remainder with no county.
- `value_state` stays `OBSERVED` or `MISSING`. A null case count is not zero.
  `censor_reason` is `state_year_unallocated_remainder`,
  `cdc_published_floor_lt5_not_published`, or `geography_withheld`.
- Legacy Connecticut counties 09001–09015 use geography class
  `ct_legacy_county_codes` and vintage `legacy_ct_counties_2008_2022`.
  They are not split and they have no atlas geometry. Other counties use
  `county_2025_tiger`. See ADR 0050.
- The 2023 measures, including `case_count_floor_2023` and
  `incidence_floor_2023`, stay on their current fields.
- Report year 2022 is not in this release. The gap is in `methodology_note`
  and in `CURRENT_METHODOLOGY_METADATA_V`. Story #856 removes 2022 from
  `HISTORY_EXCLUDED_REPORT_YEARS` in
  `src/lyme_gap_atlas_data/cdc_county_year_history.py`.

## View

`PRESENTATION.CDC_LYME_COUNTY_YEAR_HISTORY_V1` shows the current semantic
release pointer. It does not filter report year. Columns: `county_fips`,
`geography_vintage`, `state_fips`, `report_year`, `period_start`, `period_end`,
`methodology_era`, `methodology_era_id`, `methodology_note`, `measure_id`,
`case_count`, `value_state`, `is_censored`, `censor_reason`, `release_id`,
`source_version_id`.

`OH_LYME_{ENV}_READ` receives SELECT. ML read verification is ML story #172.

The view returns rows only after a history release is the current pointer in
that database. DEV and PROD pointers differ.

## Proven CONFORMED anchors

A full 40,468-row extract must match: 6,445 numeric county-years; 2008 = 35,198
cases including 3,337 unallocated; 2021 = 24,611 including 1,583 unallocated;
31,245 unallocated cases; 83 state-`Suppressed` rows totaling 561 cases kept
out of the sums.

## Release path gap for #762

The manifest-driven `PUBLISHED` schema path in #762 and #765 is not live.
This story uses the current semantic-release builder and the reviewed
`promote-prod.yml` pending-set allow-list. It does not add a second release
path. Record that gap on #762 when the steward reviews this change.

## Release manifest

The completeness artifact id is `cdc_historical`. It must preserve
`human_status`, `case_count_floor_2023`, and `incidence_floor_2023`, repeat the
methodology gap note, and name `previous_release_id`. `expected_rows` is the
history observation count, including missing atlas county-years and state
remainder rows.
