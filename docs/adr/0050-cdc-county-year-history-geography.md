# 0050: CDC 2008–2021 county-year history geography

Status: Proposed
Date: 2026-10-25
Decision owner: Data Steward, inside the 2026-10-25 owner approval of story #855
Issue: DATA #855

## Context

CDC Lyme surveillance for 2008–2021 uses Connecticut's eight legacy county FIPS
codes, 09001 through 09015. The 2025 atlas geography uses Connecticut planning
regions 09110 through 09190. Those codes do not join. Splitting legacy counts
by area or population would invent a geography CDC did not publish.

Report year 2022 is not in this release. Story #856 admits that year later.
The 2023 county measures stay on their current fields.

## Decision

Publish each legacy Connecticut county as its own geography. Do not crosswalk
the codes and do not split values. The geography class is
`ct_legacy_county_codes`. The geography vintage is
`legacy_ct_counties_2008_2022`. Every other county keeps
`county_2025_tiger`, including the 2023 Connecticut planning regions.

Legacy rows have no atlas geometry. The release builder accepts the eight
legacy codes and does not treat them as unknown counties.

The admitted years are the historical source years minus one exclusion set
that contains 2022. Story #856 removes 2022 from that set. It does not add a
second measure, label, vintage, or release path.

The public wording is reported Lyme surveillance cases by county of residence.
These counts are not infection incidence. The 2008–2021 case definition is not
directly comparable with the 2022 onward definition. No field in this release
computes a difference, ratio, or trend across that boundary.

## Consequences

`PRESENTATION.CDC_LYME_COUNTY_YEAR_HISTORY_V1` projects the current semantic
release. It does not filter report year. 2023 county observations and the
current API views stay as they are. The 2022 gap is carried in
`methodology_note` and in `CURRENT_METHODOLOGY_METADATA_V`.
