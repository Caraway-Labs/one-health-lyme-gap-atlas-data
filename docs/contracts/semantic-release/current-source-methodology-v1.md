# Current source and methodology metadata v1

Owner: Atlas Data. Consumer: API #55. Migration: V128. All three projections
resolve the `ATLAS` pointer only when its release is `PUBLISHED`.

## Objects and identifiers

`PRESENTATION.CURRENT_SOURCE_METADATA_V` retains its original columns
`source_key`, `label`, `vintage`, `source_url`, `note`, and appends `source_id`,
`dataset_id`, `publisher`, `upstream_updated_at`, `source_retrieved_at`,
`semantic_contract_version`, `release_version`. `source_key` is the stable
source resource key within the release; `source_id` and `dataset_id` are the
governed source and dataset lineage identities, not display labels. The
approved `human` / `cdc_lyme` / `x5j9-wybp` tuple has publisher `Centers for
Disease Control and Prevention`. Other tuples have SQL NULL publisher until
individually governed. A changed tuple does not inherit that attribution.
The two source-level timestamps are SQL NULL because the current release has
no authoritative source-level publication/update or retrieval time. They are
not derived from vintage, release time, or an aggregate of observations.

`PRESENTATION.CURRENT_METHODOLOGY_METADATA_V` exposes exactly
`methodology_id`, `measure_id`, `methodology`, `methodology_version`,
`limitation`, `semantic_contract_version`, `release_version`. Its three IDs
are the steward-approved distinct methodological meanings:

| Measure | Methodology ID | Governed text | Limitation |
| --- | --- | --- | --- |
| `human_status` | `human_source_native_status_mapping_v1` | `source-native status mapping` | `Published floors are not complete incidence.` |
| `case_count_floor_2023` | `human_confirmed_probable_case_floor_v1` | `x5j9 confirmed plus probable` | `Privacy-protected floor.` |
| `incidence_floor_2023` | `human_case_floor_population_incidence_v1` | `case floor divided by population` | `Not complete incidence.` |

`methodology_version` is the existing governed release methodology version;
it is a release-level version, not a claim that these three meanings are the
same resource. An approved ID is emitted only while its exact measure text,
limitation, and source tuple match this contract. A future changed meaning
requires a reviewed mapping rather than silently reusing the ID.
`transformation_version` remains a distinct observation processing fact.

`PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V` preserves the first 26 columns,
allowlist, county and period filtering, values, value states, and limitations
from Data #513. V128 appends `source_id`, `dataset_id`, `methodology_id`.
`source_key` resolves the source resource; `methodology_id` resolves the
methodology resource in the same `release_version`. A changed method meaning
leaves the observation row in place with a NULL methodology ID until reviewed.
Observation `retrieved_at` remains its own Atlas retrieval time. Observation
period, retrieval, transformation version, and governed release version are
separate facts. No universal `last_updated` is defined.

## Access and representative queries

`OH_LYME_{ENV}_READ` receives SELECT on these three views only. The source
view also preserves its existing API runtime and pipeline grants through
`COPY GRANTS`. V128 adds no access to `SEMANTIC_*` tables, release internals,
restricted artifacts, RAW, STAGING, or CONFORMED.

```sql
SELECT source_key, source_id, dataset_id, publisher, label, vintage,
       source_url, note, upstream_updated_at, source_retrieved_at,
       release_version
FROM PRESENTATION.CURRENT_SOURCE_METADATA_V
WHERE source_key = 'human';

SELECT methodology_id, measure_id, methodology, methodology_version,
       limitation, release_version
FROM PRESENTATION.CURRENT_METHODOLOGY_METADATA_V
ORDER BY methodology_id;

SELECT observation_id, measure_id, county_fips, source_key, source_id,
       dataset_id, methodology_id, retrieved_at, transformation_version,
       release_version
FROM PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V
WHERE county_fips = '01001'
ORDER BY measure_id, observation_id;

SELECT COUNT(*) FROM PRESENTATION.SEMANTIC_DATA_SOURCES;
-- Must be denied under OH_LYME_PROD_READ.
```

The views do not impose ordering or pagination. API #55 owns HTTP response
shape, links, filtering, and caching.
