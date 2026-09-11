# Canonical tick-surveillance observation contract v1

Status: Proposed for steward review
Owner: Atlas data stewardship and engineering
Schema: `canonical-tick-surveillance-v1.schema.json`
Method version: `tick-surveillance-v1`

## Purpose and boundary

This contract provides one provenance-bearing shape for heterogeneous active
tick-surveillance observations. It supports county presence/status, collection
abundance, and pathogen-testing evidence without pretending that unlike methods
are equivalent. It does not define a human-disease risk score, infer tick absence
from missing surveillance, or authorize any source for ingestion.

The first evidence candidate is the CDC county-status workbook for *Ixodes
scapularis* and *Ixodes pacificus*. That workbook supplies cumulative county
status only. It does not supply sampling effort, life stage, abundance, or
pathogen testing. Those optional fields exist so later, separately reviewed
active-surveillance sources can be represented without changing the core
provenance contract.

## Required fields

Every canonical record requires a stable canonical observation ID, observation
type, five-character county FIPS, scientific tick species, source agency and
dataset/record identifiers, governed source version, ingestion run, immutable
artifact, retrieval timestamp, method version, and quality flags. Observation
types add their own requirements:

- `VECTOR_PRESENCE_STATUS` requires presence status and explicit temporal
  semantics.
- `COLLECTION_ABUNDANCE` requires the reported tick count. Normalized abundance
  remains optional unless effort and unit evidence support it.
- `PATHOGEN_TESTING` requires pathogen, ticks tested, and ticks positive.

## Optional fields and missingness

Date/year/season, source location, life stage, sex, collection method and effort,
normalized abundance, pathogen prevalence, and harmonization metadata are
optional because publishers do not report them consistently. Their absence must
be described in `missingness`; it must not be filled with zero. Allowed states
are `PRESENT`, `NULL`, `UNKNOWN`, `SUPPRESSED`, `NOT_REPORTED`, and
`NOT_APPLICABLE`.

`NO_RECORDS` is a reported surveillance status, not a missing-value state and
not evidence that ticks are absent. Zero collected ticks is numeric evidence only
when the source documents a completed collection effort.

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

## Promotion gates

Before any source maps into this contract, a steward must approve its source
version, terms, geography/time semantics, source-record identity, method mapping,
and missingness behavior. Source-specific tests must cover identifiers, domains,
units, duplicate handling, effort denominators, positive/tested reconciliation,
and provenance. Evidence-only onboarding cannot populate RAW, STAGING,
CONFORMED, ANALYTICS, or FEATURE_STORE relations.
