# Current county observation projection v1

Owner: Atlas Data. Consumer: API #54. Object:
`ONE_HEALTH_LYME_GAP_ATLAS_{ENV}.PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V`.
Migration: V127. This is a view of the existing immutable semantic release,
selected by the `ATLAS` pointer only while its release is `PUBLISHED`.

## Published scope

The closed measure allowlist is `human_status`, `case_count_floor_2023`, and
`incidence_floor_2023`, all from the `human` release source. Measure IDs are
canonical through `CURRENT_MEASURE_METADATA_V`, which corrects the historical
physical indicator/measure reversal. Only observations whose stored time window
and measure temporal resolution both equal `2023` are exposed. This explicit
calendar-year mapping produces `period_start = 2023-01-01`, `period_end =
2023-12-31`, and `temporal_grain = YEAR`. The dates describe the observation
year, not the source retrieval or release date.

Rows require `COUNTY_FIPS_5`, a five-digit FIPS, and membership in the same
release's county atlas. `geography_id` and `county_fips` are that FIPS;
`geography_type` is `COUNTY`. State-unallocated records are not county-native
even though legacy physical rows repeat them with county FIPS. They are
excluded. County identity and geometry reference slots are excluded. Tick and
pathogen status have a `through 2025-12-31` cumulative window without a
governed start date and are excluded. The ACS context slots mix vintage and
survey period in one legacy string and are excluded pending an explicit
period contract. RUCC is a vintage-specific classification, not a measured
annual interval, and is excluded. No site/event or derived result is published.

## Columns and semantics

| Column | Meaning |
| --- | --- |
| `observation_id` | Existing immutable release observation ID; unique and deterministic within the release. |
| `measure_id` | Canonical measure ID from the governed metadata view. |
| `geography_id`, `county_fips`, `geography_type` | Five-digit county FIPS and literal `COUNTY`. |
| `period_start`, `period_end`, `temporal_grain` | Inclusive annual 2023 period and `YEAR`. |
| `value`, `value_state` | Actual VARIANT payload and stored state, unchanged. `MISSING` retains SQL NULL; `NO_COUNTY_LINKED_RECORD` remains a distinct literal status, never zero. |
| `unit`, `denominator`, `supported_stratifications` | Governed measure metadata. The latter two are currently null where no governed value exists. No strata filter is supported. |
| `semantic_contract_version`, `release_version` | Current release schema version and release ID. |
| `source_key`, `source_label`, `source_vintage`, `source_url`, `retrieved_at` | Public source description and observation retrieval time. Internal run, artifact, and row identifiers are withheld. |
| `transformation_version`, `methodology`, `release_methodology_version` | Existing observation transform and measure/release method references. |
| `observation_limitations`, `measure_limitation`, `release_limitations` | Existing interpretation limits at three scopes. |

The view is unordered. API #54 can filter by exact `measure_id`, exact
`county_fips`, inclusive period bounds, and the current `release_version`;
sort by `measure_id, county_fips, period_start, observation_id` for deterministic
pages. Only one period exists per published measure/county in the present
release. There is no legitimate multi-period county series in the current
physical release; obtaining one requires a separately governed future release.

## Access and negative boundary

V127 grants `SELECT` on this view to `OH_LYME_{ENV}_READ`. It grants nothing
on `SEMANTIC_OBSERVATIONS`, release internals, source artifacts, RAW,
STAGING, or CONFORMED. Verify with that role after protected promotion:

```sql
SELECT measure_id, county_fips, period_start, period_end, value,
       value_state, release_version
FROM PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V
WHERE measure_id = 'case_count_floor_2023' AND county_fips = '01001'
ORDER BY measure_id, county_fips, period_start, observation_id
LIMIT 10;

SELECT COUNT(*) FROM PRESENTATION.SEMANTIC_OBSERVATIONS;
-- Must remain denied to OH_LYME_PROD_READ.
```

The positive query and denial are deployment checks, not local test claims.
