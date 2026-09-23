# Canonical tick-surveillance observation contract v1

Status: Proposed for steward review; v1.2 governed normalization extension prepared by Story #386
Owner: Atlas data stewardship and engineering
Schema: `canonical-tick-surveillance-v1.schema.json`
Method versions: `tick-surveillance-v1` (legacy county status),
`tick-surveillance-v1.1` (backward-compatible site/event extension), and
`tick-surveillance-v1.2` (additive governed-normalization envelope)

## Purpose and boundary

This contract provides one provenance-bearing shape for heterogeneous active
tick-surveillance observations. It supports county presence/status, pathogen
presence/status, collection abundance, and pathogen-testing evidence without
pretending that unlike methods are equivalent. It does not define a
human-disease risk score, infer tick or pathogen absence from missing
surveillance, or authorize any source for ingestion.

The first evidence candidate is the CDC county-status workbook for *Ixodes
scapularis* and *Ixodes pacificus*. That workbook supplies cumulative county
status only. It does not supply sampling effort, life stage, abundance, or
pathogen testing. Those optional fields exist so later, separately reviewed
active-surveillance sources can be represented without changing the core
provenance contract.

## Required fields

Every canonical record requires a stable canonical observation ID, observation
type, scientific tick species, source agency and
dataset/record identifiers, governed source version, ingestion run, immutable
artifact, retrieval timestamp, method version, and quality flags. Observation
types add their own requirements:

- `VECTOR_PRESENCE_STATUS` requires presence status and explicit temporal
  semantics.
- `PATHOGEN_PRESENCE_STATUS` requires pathogen, a reported county status, and
  explicit temporal semantics. It does not imply that a tick was tested or that
  a prevalence can be calculated.
- `COLLECTION_ABUNDANCE` requires the reported tick count. Normalized abundance
  remains optional unless effort and unit evidence support it.
- `PATHOGEN_TESTING` requires pathogen, ticks tested, and ticks positive.

`county_fips` remains required for the existing county-native
`VECTOR_PRESENCE_STATUS` and `PATHOGEN_PRESENCE_STATUS` mappings. It is not a
required field for an observation whose native grain is a sampling site/event.
No loader may synthesize it from a site name, coordinate, or a broad coverage
claim.

## Site, event, replicate, and geography extension (v1.1)

For `native_sampling_grain: SITE_EVENT`, the canonical record must retain
`sampling_site`, `sampling_event`, `source_geography`, and
`county_relationship`. `sampling_site` retains the publisher's stable site
and, when supplied, plot/location identifiers. `sampling_event` retains the
publisher event plus sample, subsample, test, batch, and replicate identifiers
when they exist. These are source-native identifiers; they are not Atlas
vocabulary normalization and must not be replaced by labels from #386.

`source_geography` is the publisher-reported location/geometry, CRS, and
uncertainty. `harmonized_geography` is optional and records only a transparent
format/identifier harmonization. `county_relationship` is the separate,
derived relationship to a canonical county. Its allowed states are:

| State | County FIPS | Required behavior |
| --- | --- | --- |
| `SOURCE_REPORTED_COUNTY` | present | retain source-reported county and source/version provenance |
| `ATLAS_DERIVED_MATCH` | present | retain mapping method, version, and crosswalk artifact |
| `UNMAPPED` | null | retain source site/event; do not invent a county |
| `AMBIGUOUS` | null | retain the attempted mapping provenance; do not choose one county |

Every site/event county relationship has
`representativeness: NOT_COUNTY_REPRESENTATIVE`. It is a provenance-bearing
join, never evidence about unsampled county area. Any downstream county
aggregate is a separately versioned derived observation and must retain the
source observation ID, site, event, mapping status/method/version/artifact, and
this limitation.

### Canonical identity

Canonical identity is deterministic over source dataset and frozen source
version, immutable source-record identity, observation type, and all applicable
native site/event/sample/subsample/test/replicate identifiers plus reported
strata (species, life stage, collection method, pathogen, and any other
source-supported dimension). County FIPS is deliberately excluded from this
natural-key behavior. A changed event, replicate, source-record revision, or
applicable stratum produces a distinct observation identity; repeated events
at one location therefore cannot collide. The reference helper
`tick_contract.canonical_observation_id` implements this serialization without
making scientific equivalence decisions.

## Compatibility and migration

The v1 schema is evolved additively: existing `tick-surveillance-v1`
county-status records remain valid and retain their current IDs, FIPS behavior,
and downstream consumers. New site/event records use
`tick-surveillance-v1.1`; no existing record is rewritten and no Snowflake DDL
or production migration is part of this contract-only story. A future adapter
must persist both the legacy top-level `county_fips` (when applicable) and the
separate v1.1 `county_relationship`, verify equality where both are present,
and block rather than silently resolve a conflict.

## Optional fields and missingness

Date/year/season, source location, life stage, sex, collection method and effort,
normalized abundance, pathogen prevalence, and harmonization metadata are
optional because publishers do not report them consistently. Their absence must
be described in `missingness`; it must not be filled with zero. Allowed states
are `PRESENT`, `NULL`, `UNKNOWN`, `SUPPRESSED`, `NOT_REPORTED`, and
`NOT_APPLICABLE`.

`NO_RECORDS` is a reported surveillance status, not a missing-value state and
not evidence that ticks or pathogens are absent. Zero collected ticks is numeric
evidence only when the source documents a completed collection effort.

## Governed vocabulary and normalization extension (v1.2)

Story #386 adds the machine-readable
[`tick-surveillance-normalization-v1.json`](tick-surveillance-normalization-v1.json)
registry, validated independently by
[`tick-surveillance-normalization-v1.schema.json`](tick-surveillance-normalization-v1.schema.json).
The registry is the only approved location for source aliases, canonical IDs,
display labels, dimensional conversions, and mapping-rule identity. An adapter
must consume a pinned registry version; it must not duplicate aliases or
conversion constants.

The additive `normalization` envelope on a v1.2 observation has one mapping
record per normalized field. Each record retains the source-reported value,
canonical ID and label (when approved), mapping status, mapping rule ID,
registry/version, and publisher/dataset/release context. Top-level legacy
fields remain readable canonical display values for compatibility; they do not
replace the source value or the mapping provenance.

The current registry covers only the currently approved CDC county-status
sources and the #383-frozen NSF NEON `DP1.10093.001` / `DP1.10092.001`
`RELEASE-2026` scope. It contains tick taxa, life stages, pathogen targets,
collection methods, effort/abundance units, individual-test result terms, and
the qualification-required quality terms. An unlisted source value is returned
as `UNKNOWN`, while a reviewed-but-not-representable target is `UNSUPPORTED`;
both retain the original source value and have null canonical values. No value
may be silently guessed, coerced, dropped, or treated as a negative result.

`samplingImpractical=true` maps to `SAMPLING_IMPRACTICAL`. The documented
`dataQF` codes `legacyData`, `ID lab count subsample of total field larvae`,
and `field/ID lab larva/nymph/adult count higher than field/ID lab (PDE >25%)`
have separate canonical IDs. A different source `dataQF` value must be retained
verbatim and remains `UNKNOWN` until #162 captures the frozen RELEASE-2026
variable dictionary and a reviewed registry version adds an exact mapping.
This avoids pretending that the field name alone proves the meaning of any
code.

The registry defines `SQUARE_METRE -> HECTARE` for effort and
`TICKS_PER_SQUARE_METRE -> TICKS_PER_HECTARE` for abundance as exact,
one-direction dimensional conversions. The abundance conversion requires the
documented denominator that produced the reported density. It does not create
an abundance value from a count, and it does not make two methods, strata,
events, sites, or surveillance designs comparable.

`DRAG_CLOTH` and `FLAG_CLOTH` are deliberately distinct canonical method IDs.
Lexical normalization to either ID is not a comparability conclusion. #163
must test this boundary; any method compatibility, pooling, or aggregation rule
requires separately reviewed methodology and remains outside this contract.

### #162 and #163 handoff

- #162 must pin `tick-surveillance-normalization-v1` at its recorded version,
  persist `normalization` alongside the native value, and block on an
  `UNKNOWN`, `UNSUPPORTED`, or `AMBIGUOUS` result. It must capture the frozen
  NEON package/variable dictionary before proposing any additional aliases or
  `dataQF` code mappings.
- #162 must preserve NEON source-native method detail, `totalSampledArea`,
  `samplingImpractical`, test result, and QA value separately from the
  canonical mapping; it must not infer a denominator or convert collection
  ticks into test counts.
- #163 must test exact aliases, source-specific aliases, unknown and aggregate
  taxa, pathogen aliases, unknown/unsupported targets, method distinction,
  conversion denominator guards, source-value retention, and replay using the
  pinned registry version. Its comparability tests must demonstrate that equal
  vocabulary labels do not authorize analytical pooling.

## Normalization rules

1. Preserve the original source row unchanged in source-specific RAW storage;
   canonical records retain its artifact and source-record identity.
2. Keep reported, harmonized, and derived values distinguishable with
   `reported_or_derived` and `harmonization_method`.
3. Normalize scientific species names without collapsing different species.
4. Retain source units. Calculate a shared unit such as ticks per hectare only
   when the denominator and conversion are documented and testable.
5. Calculate prevalence only when tested and positive counts share the same
   species, life stage, place, period, and testing method. Require
   `ticks_positive <= ticks_tested`; zero tested yields no prevalence.
6. Preserve nymph and adult observations separately. A mixed or unknown life
   stage must not be silently assigned to either season.
7. A cumulative county status is not an annual observation or abundance trend.
8. A pathogen-presence status is not pathogen testing: it must not populate
   `ticks_tested`, `ticks_positive`, or `prevalence` unless the publisher
   supplies those values and the source is mapped as `PATHOGEN_TESTING`.

## Example: CDC cumulative county status

This illustrative record shows the intended mapping pattern; IDs are fixtures,
not production evidence.

```json
{
  "canonical_observation_id": "fixture-cdc-01001-scapularis-2025",
  "observation_type": "VECTOR_PRESENCE_STATUS",
  "county_fips": "01001",
  "observation_year": 2025,
  "surveillance_period_end": "2025-12-31",
  "temporal_semantics": "CUMULATIVE_THROUGH_DATE",
  "tick_species": "Ixodes scapularis",
  "life_stage": "NOT_REPORTED",
  "presence_status": "ESTABLISHED",
  "source_agency": "CDC NCEZID",
  "source_dataset_id": "cdc-ixodes-county-status-2025",
  "source_record_id": "fixture-source-row-01001",
  "data_source_version_id": "fixture-source-version",
  "ingestion_run_id": "fixture-run",
  "artifact_id": "fixture-artifact",
  "retrieved_at": "2026-09-09T00:00:00Z",
  "method_version": "tick-surveillance-v1",
  "reported_or_derived": "REPORTED",
  "harmonization_method": "Publisher status label normalized to uppercase vocabulary",
  "missingness": {"collection_method": "NOT_REPORTED", "collection_effort_value": "NOT_REPORTED"},
  "quality_flags": ["CUMULATIVE_STATUS", "NO_EFFORT_DENOMINATOR"],
  "limitations": ["No records must not be interpreted as tick absence"]
}
```

## Example: effort-normalized pathogen surveillance

This second fixture represents an aggregated active-sampling source with a
different grain. It is not present in the CDC county-status workbook.

```json
{
  "canonical_observation_id": "fixture-active-36001-nymph-bb-2025",
  "observation_type": "PATHOGEN_TESTING",
  "county_fips": "36001",
  "observation_year": 2025,
  "season": "NYMPH",
  "temporal_semantics": "PERIOD",
  "tick_species": "Ixodes scapularis",
  "life_stage": "NYMPH",
  "collection_method": "DRAG",
  "area_sampled_hectares": 1.5,
  "ticks_collected": 30,
  "abundance_value": 20.0,
  "abundance_unit": "ticks_per_hectare",
  "pathogen_name": "Borrelia burgdorferi sensu stricto",
  "ticks_tested": 30,
  "ticks_positive": 6,
  "prevalence": 0.2,
  "source_agency": "fixture-state-agency",
  "source_dataset_id": "fixture-active-surveillance",
  "source_record_id": "fixture-aggregate-1",
  "data_source_version_id": "fixture-source-version",
  "ingestion_run_id": "fixture-run",
  "artifact_id": "fixture-artifact",
  "retrieved_at": "2026-09-09T00:00:00Z",
  "method_version": "tick-surveillance-v1",
  "reported_or_derived": "HARMONIZED",
  "harmonization_method": "Reported count divided by documented sampled hectares",
  "missingness": {},
  "quality_flags": [],
  "limitations": ["Comparable only to observations using reviewed compatible collection methods"]
}
```

## Example: CDC cumulative pathogen county status

This fixture represents the separately restricted CDC ArboNET pathogen-status
workbook. It is a county-level, cumulative published-record status, not a
negative test or individual health result.

```json
{
  "canonical_observation_id": "fixture-cdc-01001-bburgdorferi-2025",
  "observation_type": "PATHOGEN_PRESENCE_STATUS",
  "county_fips": "01001",
  "observation_year": 2025,
  "surveillance_period_end": "2025-12-31",
  "temporal_semantics": "CUMULATIVE_THROUGH_DATE",
  "tick_species": "Ixodes scapularis or Ixodes pacificus",
  "life_stage": "NOT_REPORTED",
  "pathogen_name": "Borrelia burgdorferi sensu stricto",
  "presence_status": "PRESENT",
  "source_agency": "CDC ArboNET Tick Module",
  "source_dataset_id": "cdc-ixodes-pathogen-status-2025",
  "source_record_id": "fixture-source-row-01001-bburgdorferi",
  "data_source_version_id": "fixture-source-version",
  "ingestion_run_id": "fixture-run",
  "artifact_id": "fixture-artifact",
  "retrieved_at": "2026-09-16T00:00:00Z",
  "method_version": "tick-surveillance-v1",
  "reported_or_derived": "REPORTED",
  "harmonization_method": "Publisher county status label normalized to uppercase vocabulary",
  "missingness": {
    "ticks_tested": "NOT_REPORTED",
    "ticks_positive": "NOT_REPORTED",
    "prevalence": "NOT_REPORTED"
  },
  "quality_flags": ["CUMULATIVE_STATUS", "NO_TEST_COUNTS"],
  "limitations": ["No records is not pathogen absence or a negative test"]
}
```

## Promotion gates

Before any source maps into this contract, a steward must approve its source
version, terms, geography/time semantics, source-record identity, method mapping,
and missingness behavior. Source-specific tests must cover identifiers, domains,
units, duplicate handling, effort denominators, positive/tested reconciliation,
and provenance. Evidence-only onboarding cannot populate RAW, STAGING,
CONFORMED, ANALYTICS, or FEATURE_STORE relations. The only current exception is
the private DEV-only CDC pathogen boundary in ADR 0031: it may retain
source-faithful restricted RAW/STAGING rows and emits only its approved derived
county-status CONFORMED projection. It remains unavailable to API, Streamlit,
and public delivery pending protected parity and Tier C release gates.
